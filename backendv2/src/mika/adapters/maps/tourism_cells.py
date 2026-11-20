"""Le cache des données touristiques par cases (ADR 0245) : on interroge DATAtourisme sur une case de la grille
(``cells`` : ``geo_bounding`` de la case, jamais la position de la personne), et la base garde les lieux et les
événements à venir de la case, avec la date de sa lecture (``cell``).

**Deux listes par case**, chacune sa durée (``TourismConfig.places_days``, sept jours ; ``events_days``, un jour :
les événements changent plus vite). Une lecture va page après page, chacune écrite avec la page suivante : coupée, elle
reprend là ; finie, ce que la case ne rend plus s'efface (retiré, fini, au-delà de l'horizon), puis ce qui est neuf se
rapproche de l'index des lieux.

**En direct** (``ensure``) : une case jamais vue, ou dont la lecture est restée en route, que la personne ouvre (les
événements autour d'elle, la fiche d'un lieu) se lit tout de suite — quelques pages, sur la réserve du limiteur —, si
le quota le permet ; sinon on montre ce qu'on a, et ``coverage`` dit pourquoi. Autour d'un point, ce sont les cases
que son rayon touche (``area``, ADR 0259), la sienne d'abord puis les plus proches, au plus ``LIVE_READS_MAX`` par
demande, quelques-unes à la fois : au-delà, ``coverage`` dit que la zone n'est lue qu'en partie, et la suite se lit à
la demande suivante, ou le soir. **Le soir** (``warm.Warmer``) : c'est
une source du réchauffage — autour des points du passage, leurs cases d'abord, puis celles d'à côté ; dans chacune,
les événements à venir avant les lieux ; les cases jamais lues, puis les plus vieilles ; en travail de fond."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path

from mika.adapters.maps.cells import Cell, cell_of, cells_in, cells_near, distance_km, neighbours
from mika.adapters.maps.config import TourismConfig
from mika.adapters.maps.datatourisme import (
    CURSOR,
    EVENT,
    EVENTS,
    LIVE_WAIT_S,
    PLACE,
    PLACES,
    DataTourismeClient,
    TourismUnavailable,
    filters,
    params,
    read_fiche,
)
from mika.adapters.maps.quota import QuotaExceeded
from mika.adapters.maps.tourism import (
    NO_INDEX,
    CellState,
    CellStep,
    Tourism,
    TourismBase,
    paris_today,
    stamp,
    utc_now,
)
from mika.adapters.maps.warm import WarmTask
from mika.ports.maps import TourismCoverage

#: en direct, au plus tant de pages par case et par liste (le reste suit, au prochain regard ou le soir)
LIVE_PAGES = {EVENTS: 3, PLACES: 5}
#: le soir, au plus tant de pages par case (une boucle de l'API ne tourne pas sans fin)
WARM_PAGES = 500
#: en direct, au plus tant de lectures (une case et une liste) par demande, les plus proches d'abord, et tant à la
#: fois (ADR 0259) : un rayon de douze kilomètres touche une dizaine de cases de dix
LIVE_READS_MAX = 12
LIVE_PARALLEL = 3
#: les cases d'un rayon ou d'une zone : au plus tant (au-delà, un endroit trop grand pour les compter : rien ne s'y lit
#: en direct, on montre ce qu'on a)
AREA_CELLS_MAX = 64
#: ce qu'on dit d'une zone lue en partie, et d'une zone trop grande
PARTIAL = ("Cette zone n'est lue qu'en partie (cases lues : {loaded} sur {cells}) : la suite se lit à la prochaine "
           "recherche, ou ce soir.")
TOO_WIDE = "Une zone trop grande pour la lire d'un coup : on montre ce que les cases déjà lues en ont."
#: ce qu'on a dit d'une case qui ne s'est pas lue en direct, le temps qu'on le redise
NOTE_KEEP = timedelta(hours=1)
KIND = {EVENTS: EVENT, PLACES: PLACE}
PART_FR = {EVENTS: "événements", PLACES: "lieux"}


class TourismCells:
    """Les cases de ``tourism`` (sa base), lues par ``client`` avec le réglage ``config`` (relu à chaque fois) ;
    ``index`` : l'index des lieux pour le rapprochement (son chemin et sa date ; ``None`` : aucun)."""

    name = "datatourisme"
    label = "DATAtourisme"

    def __init__(self, tourism: Tourism, config: Callable[[], TourismConfig], client: DataTourismeClient, *,
                 index: Callable[[], tuple[Path, str] | None] = lambda: None,
                 clock: Callable[[], datetime] = utc_now) -> None:
        self.tourism = tourism
        self.config = config
        self.client = client
        self.index = index
        self.clock = clock
        self._notes: dict[str, tuple[datetime, str]] = {}
        self._reading: dict[tuple[str, str], asyncio.Future[tuple[int, bool]]] = {}

    def cell(self, lat: float, lon: float) -> Cell:
        return cell_of(lat, lon, self.config().cell_km)

    def ttl(self, part: str) -> timedelta:
        cfg = self.config()
        return timedelta(days=cfg.events_days if part == EVENTS else cfg.places_days)

    def stale(self, state: CellState | None, part: str, now: datetime) -> bool:
        """À relire : jamais lue jusqu'au bout, une lecture en route, ou plus vieille que sa durée."""
        if state is None or not state.fetched or state.reading:
            return True
        try:
            at = datetime.fromisoformat(state.fetched.replace("Z", "+00:00"))
        except ValueError:
            return True
        return now - at >= self.ttl(part)

    # ── lire une case ──
    async def load(self, cell: Cell, part: str, *, background: bool, pages_max: int) -> tuple[int, bool]:
        """Une case et une liste lues (ou continuées), au plus ``pages_max`` pages : (fiches lues, finie). Deux
        lectures de la même case en même temps n'en font qu'une."""
        key = (cell.key, part)
        pending = self._reading.get(key)
        if pending is None:
            pending = asyncio.ensure_future(self._load(cell, part, background=background, pages_max=pages_max))
            self._reading[key] = pending
            pending.add_done_callback(lambda done, key=key: self._settled(key, done))
        return await asyncio.shield(pending)

    def _settled(self, key: tuple[str, str], done: asyncio.Future[tuple[int, bool]]) -> None:
        self._reading.pop(key, None)
        if not done.cancelled():
            done.exception()  # lue : une lecture que plus personne n'attendait ne se plaint pas au journal

    async def _load(self, cell: Cell, part: str, *, background: bool, pages_max: int) -> tuple[int, bool]:
        cfg = self.config()
        wait = 0.0 if background else LIVE_WAIT_S
        conn = await asyncio.to_thread(self.tourism.base.open)
        try:
            now = self.clock()
            today = paris_today(now)
            row = TourismBase.cell_row(conn, cell.key, part)
            page = None
            started = row["started"] if row is not None else ""
            if started and row["next"]:
                try:
                    page = await self.client.follow(row["next"], background=background, wait_max=wait)
                except TourismUnavailable as exc:
                    if exc.kind != CURSOR:
                        raise
            if page is None:
                started = stamp(now)
                await asyncio.to_thread(TourismBase.cell_begin, conn, cell.key, part, cell.bbox, started)
                events = part == EVENTS
                expression = filters(events_from=today if events else None,
                                     events_to=today + timedelta(days=cfg.horizon_days) if events else None)
                page = await self.client.first(part, params(part, expression, bounding=cell.bbox),
                                               background=background, wait_max=wait)
            count = 0
            for number in range(1, pages_max + 1):
                fiches = [f for f in map(read_fiche, page.objects) if f is not None]
                await asyncio.to_thread(TourismBase.write_page, conn, fiches, run=None, synced=stamp(self.clock()),
                                        today=today, cell=CellStep(cell.key, part, started, page.next))
                count += len(fiches)
                if not page.next:
                    await asyncio.to_thread(TourismBase.cell_finish, conn, cell.key, part, KIND[part],
                                            stamp(self.clock()))
                    await asyncio.to_thread(self._match, conn)
                    self._notes.pop(cell.key, None)
                    return count, True
                if number == pages_max:
                    break
                page = await self.client.follow(page.next, background=background, wait_max=wait)
            await asyncio.to_thread(self._match, conn)
            return count, False
        finally:
            conn.close()

    def _match(self, conn: sqlite3.Connection) -> None:
        """Ce qui est neuf, rapproché de l'index des lieux. Une base jamais rapprochée l'est en entier (elle naît :
        quelques cases) ; un index qui a changé depuis le dernier rapprochement, ou qui est arrivé depuis un
        rapprochement sans lui : rien ici — tout se refait d'un coup, par la boucle de la synchronisation
        (``TourismSync.rematch``), et d'ici là le neuf attend (ni pendant, ni ``t:``)."""
        index = self.index()
        built = index[1] if index is not None else NO_INDEX
        matched = TourismBase.meta(conn).get("matched_with", "")
        if matched and matched != built:
            return
        TourismBase.match(conn, index[0] if index is not None else None, everything=not matched)
        if not matched:
            TourismBase.set_meta(conn, {"matched_with": built})

    # ── en direct ──
    def area(self, near: tuple[float, float] | None, bbox: tuple[float, float, float, float] | None,
             radius_m: float | None = None) -> list[Cell] | None:
        """Les cases d'un endroit, les plus proches d'abord : celle d'un point ; avec un rayon, celles qu'il touche
        (ADR 0259) ; celles d'une zone, depuis son centre. ``None`` : plus de ``AREA_CELLS_MAX``, trop grand pour les
        compter ; ``[]`` : nulle part."""
        size = self.config().cell_km
        if bbox is not None:
            found = cells_in(bbox, size, AREA_CELLS_MAX)
            if found is None:
                return None
            lat, lon = (bbox[1] + bbox[3]) / 2, (bbox[0] + bbox[2]) / 2
            return sorted(found, key=lambda c: (distance_km(c, lat, lon), c.key))
        if near is None:
            return []
        if radius_m is None:
            return [cell_of(near[0], near[1], size)]
        return cells_near(near[0], near[1], radius_m / 1000, size, AREA_CELLS_MAX)

    async def ensure(self, cells: Sequence[Cell] | None, parts: Sequence[str]) -> None:
        """Les cases jamais vues (ou restées en route) de cet endroit, lues en direct, si le quota le permet — les
        plus proches d'abord, au plus ``LIVE_READS_MAX`` lectures, ``LIVE_PARALLEL`` à la fois ; sinon on garde ce
        qui l'a empêché, pour le dire (``coverage``). Un endroit trop grand (``None``) : rien."""
        if not cells or not self.client.ready():
            return
        states = self.tourism.cell_states([c.key for c in cells])
        due = [(cell, part) for cell in cells for part in parts
               if not ((s := states.get((cell.key, part))) is not None and s.fetched and not s.reading)]
        due = due[:LIVE_READS_MAX]
        for k in range(0, len(due), LIVE_PARALLEL):
            went = await asyncio.gather(*(self._live(cell, part) for cell, part in due[k:k + LIVE_PARALLEL]))
            if not all(went):
                return  # un quota, une panne : la suite attendra

    async def _live(self, cell: Cell, part: str) -> bool:
        """Une case et une liste lues en direct ; faux : ce qui l'a empêché (un quota, une panne, la base), gardé
        pour le dire — on s'arrête là."""
        try:
            _count, done = await self.load(cell, part, background=False, pages_max=LIVE_PAGES[part])
        except (QuotaExceeded, TourismUnavailable) as exc:
            self._notes[cell.key] = (self.clock(), f"{exc} On montre ce qu'on avait.")
            return False
        except (sqlite3.Error, OSError):
            self._notes[cell.key] = (self.clock(), "La base des données touristiques ne s'écrit pas : on montre ce "
                                                   "qu'on avait.")
            return False
        if not done:
            self._notes[cell.key] = (self.clock(), f"Les {PART_FR[part]} de cette case sont nombreux : la suite se "
                                                   "lit à la prochaine ouverture, ou ce soir.")
        return True

    def coverage(self, cells: Sequence[Cell] | None, parts: Sequence[str] = (EVENTS, PLACES)) -> TourismCoverage:
        """Ce que la base sait de ces cases, pour ces listes : combien sont lues, la lecture la plus ancienne, et ce
        qu'il faut en dire (un quota, une panne, une zone lue en partie, une zone trop grande)."""
        info = self.tourism.info()
        if cells is None:
            return TourismCoverage(info.ready, note=TOO_WIDE if info.ready else self._why_not())
        if not cells:
            return TourismCoverage(info.ready, note="" if info.ready else self._why_not())
        states = self.tourism.cell_states([c.key for c in cells])
        loaded = [c for c in cells if all((s := states.get((c.key, p))) is not None and s.fetched and not s.reading
                                          for p in parts)]
        fetched = [s.fetched for (_key, part), s in states.items() if s.fetched and part in parts]
        now = self.clock()
        notes = [text for key, (at, text) in self._notes.items() if key in {c.key for c in cells}
                 and now - at < NOTE_KEEP]
        note = notes[0] if notes else ""
        if not note and len(loaded) < len(cells):
            if not self.client.ready():
                note = self._why_not()
            elif not loaded and len(cells) == 1:
                note = "" if info.ready else self._why_not()
            else:
                note = PARTIAL.format(loaded=len(loaded), cells=len(cells))
        return TourismCoverage(info.ready, len(cells), len(loaded), min(fetched) if fetched else "", note)

    def _why_not(self) -> str:
        if not self.client.ready():
            return "Les données touristiques ne sont pas réglées (aucune clé DATAtourisme)."
        return "Les données touristiques de cet endroit ne sont pas encore lues : elles le seront ce soir."

    # ── le réchauffage (``warm.WarmSource``) ──
    def ready(self) -> bool:
        return self.client.ready()

    def plan(self, points: Sequence[tuple[float, float]], now: datetime) -> list[WarmTask]:
        """Les cases des points d'abord, puis celles d'à côté ; dans chacun de ces cercles, les événements de toutes
        les cases avant leurs lieux ; les jamais lues, puis les plus vieilles."""
        size = self.config().cell_km
        own = list({c.key: c for c in (cell_of(lat, lon, size) for lat, lon in points)}.values())
        ring = list({c.key: c for cell in own for c in neighbours(cell, size) if c.key not in
                     {o.key for o in own}}.values())
        states = self.tourism.cell_states([c.key for c in (*own, *ring)])
        tasks = []
        for circle in (own, ring):
            for part in (EVENTS, PLACES):
                due = [(states.get((c.key, part)), c) for c in circle]
                due = [(s, c) for s, c in due if self.stale(s, part, now)]
                due.sort(key=lambda item: (item[0].fetched if item[0] is not None else "", item[1].key))
                tasks += [WarmTask(c, part, s.fetched if s is not None else "") for s, c in due]
        return tasks

    async def warm(self, task: WarmTask) -> int:
        count, _done = await self.load(task.cell, task.part, background=True, pages_max=WARM_PAGES)
        return count

    def budget(self) -> str:
        return self.client.limiter.describe()

