"""Ce qui remplit le cache des avis (ADR 0250, 0256) : les cases de la grille lues chez Google Places, la fiche d'un
lieu en direct, le préchargement autour d'une position, le réchauffage du soir, les photos.

**Une case** (``load``) : par sorte (restaurants, à voir, hébergements), les vingt lieux les plus connus du cercle qui
la couvre (son centre, la moitié de sa diagonale : jamais un point d'une personne) — une recherche « Nearby Search
Enterprise ». Google n'en rend pas plus, sans page suivante : un cercle qui en rend vingt est plein, et ses quatre
quarts se demandent à leur tour (``circle``), jusqu'à ``ReviewsConfig.split_depth`` niveaux. Chaque cercle lu s'écrit
avec ceux qui restent : coupée (un quota), la lecture reprend là le jour même. Puis ce qui est neuf se rapproche de
l'index des lieux.

**La fiche d'un lieu** (``facts``) : son pendant chez Google, s'il en a un. Pas encore rapproché, il se cherche tout
près de lui (``PROBE_RADIUS_M``, les plus proches d'abord) une fois par durée du cache — ce qu'on a trouvé, ou rien, se
garde. Puis sa fiche avec ses avis (« Place Details Enterprise + Atmosphere ») se lit si elle manque ou est vieille, en
direct, sur la réserve du limiteur ; quand le quota manque, on montre ce qu'on avait, en le disant. « Actualiser »
(``refresh``) relit tout, quel que soit l'âge, et dit ce qui n'a pas pu l'être.

**Le préchargement** (``preload``) : la case d'une position et les huit d'à côté, mises en file et lues en fond,
celles qui sont vieilles seulement ; la position ne part jamais. **Le soir** (``warm.Warmer``) : c'est une source du
réchauffage — les restaurants d'abord, puis ce qui est à voir, puis les hébergements ; pour chacun, les cases des
points puis leurs voisines, les jamais lues puis les plus vieilles ; ensuite, s'il reste du budget, la fiche des lieux
de ces cases ouverts depuis peu, les plus regardés d'abord ; en travail de fond (la réserve gardée au direct).

**Les photos** (``photo_origin``, une source du relais) : l'adresse d'une image ne se garde pas, elle se demande à
Google quand le relais va la chercher (un appel « Place Details Photos », une fois : le relais garde l'image) ; le nom
d'une photo expire — refusé (400 ou 404), la fiche se relit et la photo reprend son nom neuf, sous la même référence."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import sqlite3
from collections import deque
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path

from mika.adapters.maps.cells import Cell, cell_of, cells_in, neighbours
from mika.adapters.maps.config import ReviewsConfig
from mika.adapters.maps.geo import meters_between
from mika.adapters.maps.google_places import (
    AUTH,
    BROKEN,
    DISTANCE,
    FOR_CATEGORY,
    FOR_KIND,
    FORBIDDEN,
    LIVE_WAIT_S,
    MISSING,
    PHOTO_HOSTS,
    PROBE_COUNT,
    PROBE_RADIUS_M,
    REFUSED,
    RESULTS_MAX,
    SKUS,
    SORTS,
    PlacesClient,
    PlacesUnavailable,
    read_place,
)
from mika.adapters.maps.hours import PARIS
from mika.adapters.maps.photos import UNKNOWN, PhotoOrigin
from mika.adapters.maps.quota import MONTHS_FR, QuotaExceeded
from mika.adapters.maps.reviews import (
    PURGE_TIMES,
    SOURCE,
    TWIN_M,
    CellState,
    Reviews,
    ReviewsBase,
    older_than,
    parse,
    stamp,
)
from mika.adapters.maps.tourism import NO_INDEX, utc_now
from mika.adapters.maps.warm import WarmTask
from mika.ports.maps import MapsNotFound, ReviewFacts, ReviewsCoverage

log = logging.getLogger("mika.maps.reviews")

#: le réchauffage, une fois les cases lues : la fiche des lieux qu'on a ouverts (``WarmTask.part``)
AVIS = "avis"
#: le soir, au plus tant de lieux par case dont on relit la fiche (une « fiche avec avis » chacun)
WARM_SPOTS_PER_CELL = 5
#: une lecture de case coupée reprend à son cercle suivant si elle a commencé il y a moins de tant (sinon : du début)
RESUME_WITHIN = timedelta(hours=20)
#: la file du préchargement : au plus tant de lectures en attente
QUEUE_MAX = 200
#: ce qu'on a dit d'un préchargement arrêté, le temps qu'on le redise
NOTE_KEEP = timedelta(hours=1)
#: une zone d'au plus tant de cases se dit dans ``coverage`` (au-delà : trop grande pour les compter)
COVERAGE_CELLS_MAX = 25
#: le cercle d'une case la couvre à ses coins, avec cette marge
CIRCLE_MARGIN = 1.01
NO_KEY_NOTE = "Les avis ne sont pas réglés (aucune clé Google)."
GONE = "Cette photo n'est plus chez Google."
_DB_ERRORS = (sqlite3.Error, OSError)


def day_fr(iso: str) -> str:
    """« le 18 novembre » (heure de Paris) ; illisible : tel quel."""
    at = parse(iso)
    if at is None:
        return iso
    local = at.astimezone(PARIS)
    return f"le {'1er' if local.day == 1 else local.day} {MONTHS_FR[local.month - 1]}"


def not_found(fetched: str) -> ReviewFacts:
    """Ce qu'on dit d'un lieu que Google n'a pas, tout près de lui, sous son nom."""
    return ReviewFacts(id="", cached=fetched, note=f"Rien trouvé sur Google sous ce nom à moins de {TWIN_M} m "
                                                   f"(cherché {day_fr(fetched)}).")


def circle(cell: Cell, path: str = "") -> tuple[float, float, float]:
    """Le cercle d'une partie d'une case — « » la case entière, « 0 » à « 3 » ses quarts (sud-ouest, sud-est,
    nord-ouest, nord-est), « 03 » le quart nord-est de son quart sud-ouest… — : son centre et son rayon en mètres (la
    moitié de sa diagonale, et un peu plus : il couvre ses coins). Rien que la case : jamais un point d'une personne."""
    s, w, n, e = cell.south, cell.west, cell.north, cell.east
    for digit in path:
        k = int(digit)
        mid_lat, mid_lon = (s + n) / 2, (w + e) / 2
        w, e = (mid_lon, e) if k & 1 else (w, mid_lon)
        s, n = (mid_lat, n) if k & 2 else (s, mid_lat)
    lat, lon = (s + n) / 2, (w + e) / 2
    return round(lat, 6), round(lon, 6), round(meters_between(lat, lon, n, e) * CIRCLE_MARGIN, 1)


class ReviewsCells:
    """Le cache des avis (``reviews``) et ce qui le remplit, par ``client`` (Google Places), au réglage ``config`` (relu
    à chaque fois) ; ``index`` : l'index des lieux pour le rapprochement (son chemin et sa date ; ``None`` : aucun) ;
    ``tourism`` : la base des données touristiques (ses lieux sans pendant d'OpenStreetMap)."""

    name = "google"
    label = "Google"

    def __init__(self, reviews: Reviews, config: Callable[[], ReviewsConfig], client: PlacesClient, *,
                 index: Callable[[], tuple[Path, str] | None] = lambda: None,
                 tourism: Callable[[], Path | None] = lambda: None,
                 clock: Callable[[], datetime] = utc_now) -> None:
        self.reviews = reviews
        self.config = config
        self.client = client
        self.index = index
        self.tourism = tourism
        self.clock = clock
        self._reading: dict[tuple[str, str], asyncio.Future[tuple[int, bool]]] = {}
        #: la fiche d'un lieu relue pour le nom neuf de ses photos : une à la fois par lieu (R3-10)
        self._renaming: dict[str, asyncio.Future[None]] = {}
        self._queue: deque[tuple[Cell, str]] = deque()
        self._queued: set[tuple[str, str]] = set()
        self._wake = asyncio.Event()
        self._worker: asyncio.Task[None] | None = None
        #: ce que le préchargement a fait depuis le démarrage, et ce qui l'a arrêté (pour la console, ``coverage``)
        self.preloaded = 0
        self.note = ""
        self.note_at: datetime | None = None

    def cell(self, lat: float, lon: float) -> Cell:
        return cell_of(lat, lon, self.config().cell_km)

    def ttl(self) -> timedelta:
        return timedelta(days=self.config().cache_days)

    def stale(self, fetched: str, now: datetime) -> bool:
        """Vieux : jamais lu, illisible, ou plus vieux que la durée du cache."""
        at = parse(fetched) if fetched else None
        return at is None or now - at >= self.ttl()

    def _cell_stale(self, state: CellState | None, now: datetime) -> bool:
        return state is None or state.reading or self.stale(state.fetched, now)

    def ready(self) -> bool:
        return self.client.ready()

    # ── l'écriture, hors de la boucle ──
    def _match(self, conn: sqlite3.Connection) -> None:
        """Ce qui est neuf, rapproché de l'index des lieux (et des lieux DATAtourisme sans pendant) ; tout, quand
        l'index a été reconstruit. Une panne de la base laisse le neuf pour la prochaine fois."""
        index = self.index()
        with contextlib.suppress(*_DB_ERRORS):
            ReviewsBase.match(conn, index[0] if index is not None else None,
                              index[1] if index is not None else NO_INDEX, self.tourism())

    def _purge(self, conn: sqlite3.Connection) -> None:
        with contextlib.suppress(*_DB_ERRORS):
            ReviewsBase.purge(conn, older_than(self.clock(), PURGE_TIMES * self.config().cache_days))

    async def _write(self, fn: Callable[[sqlite3.Connection], object]) -> None:
        """Une écriture au cache, hors de la boucle, puis le rapprochement de ce qui est neuf."""
        def run() -> None:
            conn = self.reviews.base.open()
            try:
                fn(conn)
                self._match(conn)
            finally:
                conn.close()

        await asyncio.to_thread(run)

    # ── lire une case ──
    async def load(self, cell: Cell, sort: str, *, background: bool) -> tuple[int, bool]:
        """Une case et une sorte lues (ou continuées) : (lieux lus, finie). Deux lectures de la même case en même temps
        n'en font qu'une."""
        key = (cell.key, sort)
        pending = self._reading.get(key)
        if pending is None:
            pending = asyncio.ensure_future(self._load(cell, sort, background=background))
            self._reading[key] = pending
            pending.add_done_callback(lambda done, key=key: self._settled(key, done))
        return await asyncio.shield(pending)

    def _settled(self, key: tuple[str, str], done: asyncio.Future[tuple[int, bool]]) -> None:
        self._reading.pop(key, None)
        if not done.cancelled():
            done.exception()  # lue : une lecture que plus personne n'attendait ne se plaint pas au journal

    async def _load(self, cell: Cell, sort: str, *, background: bool) -> tuple[int, bool]:
        wait = 0.0 if background else LIVE_WAIT_S
        depth = self.config().split_depth
        conn = await asyncio.to_thread(self.reviews.base.open)
        try:
            now = self.clock()
            row = ReviewsBase.cell_row(conn, cell.key, sort)
            begun = parse(row["started"]) if row is not None and row["started"] else None
            queue: list[str] = []
            if begun is not None and now - begun < RESUME_WITHIN:
                with contextlib.suppress(ValueError, TypeError):
                    queue = [str(p) for p in json.loads(row["queue"]) if str(p).isdigit() or p == ""]
            if not queue:
                queue = [""]
                await asyncio.to_thread(ReviewsBase.cell_begin, conn, cell.key, sort, cell.bbox, stamp(now), queue)
            count = 0
            try:
                while queue:
                    path = queue[0]
                    lat, lon, radius = circle(cell, path)
                    raw = await self.client.nearby(lat, lon, radius, sort, background=background, wait_max=wait)
                    spots = [s for s in (read_place(r, sort) for r in raw) if s is not None]
                    full = len(raw) >= RESULTS_MAX
                    queue = queue[1:] + ([path + d for d in "0123"] if full and len(path) < depth else [])
                    await asyncio.to_thread(ReviewsBase.cell_step, conn, cell.key, sort, spots, queue, full,
                                            stamp(self.clock()))
                    count += len(spots)
                await asyncio.to_thread(ReviewsBase.cell_finish, conn, cell.key, sort, stamp(self.clock()))
                await asyncio.to_thread(self._purge, conn)
                return count, True
            finally:
                await asyncio.to_thread(self._match, conn)
        finally:
            conn.close()

    # ── la fiche d'un lieu ──
    async def facts(self, category: str, kind: str, lat: float, lon: float, keys: Sequence[str], *,
                    refresh: bool = False) -> ReviewFacts | None:
        """Ce que Google dit d'un lieu de l'index (``category`` et ``kind`` : sa catégorie de l'écran Carte et sa sorte,
        qui disent sous quelle sorte le chercher chez lui ; ``keys`` : ses identifiants, le durable d'abord — son objet
        d'OpenStreetMap, sa ligne, ``t:<uuid>``). ``None`` : rien à en dire (aucune clé et rien en cache, ou une sorte de
        lieu dont on ne lit pas les avis). Ce qui manque ou est vieux se lit en direct ; ce qui ne l'a pas pu se dit
        dans ``note``. ``refresh`` : tout se relit, et ce qui n'a pas pu l'être lève (``QuotaExceeded``,
        ``PlacesUnavailable``)."""
        keys = [k for k in dict.fromkeys(keys) if k]
        if not keys:
            return None
        try:
            return await self._facts(FOR_CATEGORY.get(category) or FOR_KIND.get(kind, ""), lat, lon, keys,
                                     refresh=refresh)
        except _DB_ERRORS:
            if refresh:
                raise PlacesUnavailable("Le cache des avis ne s'écrit pas.", "base") from None
            row = await self.reviews.spot_for(keys)
            return await self.reviews.facts(row["id"], note="Le cache des avis ne s'écrit pas : on montre ce qu'on "
                                                            "avait.") if row is not None else None

    async def _facts(self, sort: str, lat: float, lon: float, keys: list[str], *,
                     refresh: bool) -> ReviewFacts | None:
        ready = self.client.ready()
        row = await self.reviews.spot_for(keys)
        now = self.clock()
        if row is None:
            if not ready or not sort:
                return None
            probe = await self.reviews.probe_of(keys[0])
            if probe is not None and not refresh and not self.stale(probe["fetched"], now):
                return not_found(probe["fetched"])
            try:
                await self._probe(keys, lat, lon, sort)
            except (QuotaExceeded, PlacesUnavailable) as exc:
                if refresh:
                    raise
                return ReviewFacts(id="", note=f"{exc} Ce lieu n'a pas pu se chercher sur Google.")
            row = await self.reviews.spot_for(keys)
            if row is None:
                return not_found(stamp(now))
        notes = []
        if ready and (refresh or self.stale(row["detailed"], now)):
            try:
                await self._detail(row["id"], row["category"], background=False)
            except (QuotaExceeded, PlacesUnavailable) as exc:
                if refresh:
                    raise
                notes.append(f"{exc} On montre ce qu'on avait.")
        await asyncio.to_thread(self._look, row["id"])
        return await self.reviews.facts(row["id"], note=" ".join(notes))

    async def read_at(self, category: str, kind: str, keys: Sequence[str]) -> tuple[bool, datetime | None]:
        """Pour « Actualiser » (ADR 0269) : Google a-t-il de quoi relire ce lieu (son pendant, ou une sorte dont on lit
        les avis), et quand on l'a lu la dernière fois — sa fiche avec ses avis, ou la recherche tout près de lui
        (``None`` : jamais)."""
        keys = [k for k in dict.fromkeys(keys) if k]
        if not keys:
            return False, None
        row = await self.reviews.spot_for(keys)
        if row is not None:
            return True, parse(row["detailed"]) if row["detailed"] else None
        if not (FOR_CATEGORY.get(category) or FOR_KIND.get(kind, "")):
            return False, None
        probe = await self.reviews.probe_of(keys[0])
        return True, parse(probe["fetched"]) if probe is not None else None

    def _look(self, spot: str) -> None:
        with contextlib.suppress(*_DB_ERRORS):
            conn = self.reviews.base.open()
            try:
                ReviewsBase.look(conn, spot, stamp(self.clock()))
            finally:
                conn.close()

    async def _probe(self, keys: Sequence[str], lat: float, lon: float, sort: str) -> None:
        """Un lieu de l'index pas encore rapproché, cherché tout près de lui chez Google (les plus proches d'abord) :
        ce qu'on y trouve s'écrit et se rapproche, et ce qu'on a trouvé pour lui (un lieu, ou rien) se garde."""
        raw = await self.client.nearby(lat, lon, PROBE_RADIUS_M, sort, rank=DISTANCE, count=PROBE_COUNT,
                                       background=False, wait_max=LIVE_WAIT_S)
        spots = [s for s in (read_place(r, sort) for r in raw) if s is not None]
        at = stamp(self.clock())

        def write(conn: sqlite3.Connection) -> None:
            ReviewsBase.write_spots(conn, spots, at)
            self._match(conn)
            found = conn.execute(f"SELECT id FROM spot WHERE twin IN ({', '.join('?' * len(keys))}) "
                                 "ORDER BY twin_m LIMIT 1", list(keys)).fetchone()
            ReviewsBase.write_probe(conn, keys[0], found[0] if found else None, at)

        await self._write(write)

    async def _detail(self, spot: str, sort: str, *, background: bool) -> None:
        """La fiche d'un lieu relue chez Google, avec ses avis, son résumé, ses photos (leurs noms neufs) et ce qu'il
        sert : un appel « fiche avec avis ». Un lieu que Google ne connaît plus garde ce qu'on en avait (il s'effacera
        de lui-même)."""
        raw = await self.client.details(spot, background=background, wait_max=0.0 if background else LIVE_WAIT_S)
        read = read_place(raw, sort, detailed=True)
        if read is None or read.id != spot:
            raise PlacesUnavailable("Google a rendu une fiche illisible.", BROKEN)
        at = stamp(self.clock())
        await self._write(lambda conn: ReviewsBase.write_spots(conn, [read], at))

    # ── les photos (``photos.PhotoSource``) ──
    def photo_origin(self, ref: str) -> PhotoOrigin | None:
        """Une photo du cache : son adresse se demande à Google au moment où le relais va la chercher (seulement si
        l'image n'est pas déjà gardée), sur ses hôtes d'images seulement. Appelée hors de la boucle."""
        if self.reviews.photo_row(ref) is None:
            return None
        return PhotoOrigin("", SOURCE, resolve=lambda: self._photo_uri(ref), hosts=PHOTO_HOSTS)

    async def _photo_uri(self, ref: str) -> str:
        """L'adresse de l'image de cette photo chez Google (un appel « photo ») ; son nom expiré (400 ou 404) : la fiche
        se relit, et la photo reprend son nom neuf sous la même référence — partie, elle le dit. Les photos d'un même
        lieu relevées ensemble ne relisent sa fiche qu'une fois ; une photo déjà renommée entre-temps prend son nom neuf
        sans la relire (R3-10)."""
        row = await asyncio.to_thread(self.reviews.photo_row, ref)
        if row is None:
            raise MapsNotFound(UNKNOWN)
        try:
            return await self.client.photo_uri(row["name"])
        except PlacesUnavailable as exc:
            if exc.kind not in (REFUSED, MISSING):
                raise
        again = await asyncio.to_thread(self.reviews.photo_row, ref)
        if again is not None and again["name"] == row["name"]:
            await self._rename(row["spot"])
            again = await asyncio.to_thread(self.reviews.photo_row, ref)
        if again is None:
            raise MapsNotFound(GONE)
        return await self.client.photo_uri(again["name"])

    async def _rename(self, spot: str) -> None:
        """La fiche de ce lieu relue pour le nom neuf de ses photos : une seule relecture en cours par lieu, que les
        autres attendent."""
        pending = self._renaming.get(spot)
        if pending is None:
            pending = asyncio.ensure_future(self._detail(spot, "", background=False))
            self._renaming[spot] = pending
            pending.add_done_callback(lambda done, spot=spot: self._renamed(spot, done))
        await asyncio.shield(pending)

    def _renamed(self, spot: str, done: asyncio.Future[None]) -> None:
        self._renaming.pop(spot, None)
        if not done.cancelled():
            done.exception()  # lue : une relecture que plus personne n'attendait ne se plaint pas au journal

    # ── le préchargement ──
    def preload(self, lat: float, lon: float) -> int:
        """La case de ce point et les huit d'à côté, par sorte (les restaurants d'abord), mises en file pour une
        lecture en fond — celles qui sont vieilles le seront ; la position ne part jamais. Rend combien de lectures
        sont mises en file (0 : coupé, aucune clé, ou un point hors du monde)."""
        cfg = self.config()
        if not cfg.preload or not self.client.ready() or not (math.isfinite(lat) and math.isfinite(lon)) or \
                not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return 0
        own = cell_of(lat, lon, cfg.cell_km)
        cells = [own, *neighbours(own, cfg.cell_km)]
        queued = 0
        for sort in SORTS:
            for cell in cells:
                key = (cell.key, sort)
                if key in self._queued or len(self._queue) >= QUEUE_MAX:
                    continue
                self._queued.add(key)
                self._queue.append((cell, sort))
                queued += 1
        if queued:
            self._wake.set()
        return queued

    async def drain(self) -> int:
        """La file du préchargement lue jusqu'au bout, en fond : les cases encore fraîches passent sans rien demander.
        Un quota pris vide la file (ce soir, le réchauffage reprendra) ; une clé refusée aussi. Rend combien de cases
        ont été lues."""
        read = 0
        while self._queue:
            cell, sort = self._queue.popleft()
            self._queued.discard((cell.key, sort))
            state = self.reviews.cell_states([cell.key]).get((cell.key, sort))
            if not self._cell_stale(state, self.clock()):
                continue
            try:
                await self.load(cell, sort, background=True)
                read += 1
                self.preloaded += 1
            except QuotaExceeded as exc:
                self._stop(f"Le préchargement des avis s'est arrêté : {exc}")
                break
            except PlacesUnavailable as exc:
                if exc.kind in (AUTH, FORBIDDEN):
                    self._stop(f"Le préchargement des avis s'est arrêté : {exc}")
                    break
                self.note, self.note_at = str(exc), self.clock()
            except _DB_ERRORS:
                self.note, self.note_at = "Le cache des avis ne s'écrit pas.", self.clock()
        return read

    def _stop(self, said: str) -> None:
        self.note, self.note_at = said, self.clock()
        self._queue.clear()
        self._queued.clear()
        log.info("avis : %s", said)

    def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.get_running_loop().create_task(self._loop())

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None

    async def _loop(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            try:
                await self.drain()
            except Exception:  # noqa: BLE001 — un préchargement en panne ne fait rien tomber : il reviendra
                log.exception("avis : le préchargement a échoué")

    # ── le réchauffage (``warm.WarmSource``) ──
    def plan(self, points: Sequence[tuple[float, float]], now: datetime) -> list[WarmTask]:
        """Les restaurants, puis ce qui est à voir, puis les hébergements ; pour chacun, les cases des points d'abord,
        puis celles d'à côté, les jamais lues puis les plus vieilles ; ensuite la fiche des lieux qu'on a ouverts (les
        cases des points, puis les autres). Rien si les avis ne prennent pas part au réchauffage."""
        cfg = self.config()
        if not cfg.warm:
            return []
        size = cfg.cell_km
        own = list({c.key: c for c in (cell_of(lat, lon, size) for lat, lon in points)}.values())
        mine = {c.key for c in own}
        ring = list({c.key: c for cell in own for c in neighbours(cell, size) if c.key not in mine}.values())
        states = self.reviews.cell_states([c.key for c in (*own, *ring)])
        tasks = []
        for sort in SORTS:
            for around in (own, ring):
                due = [(states.get((c.key, sort)), c) for c in around]
                due = [(s, c) for s, c in due if self._cell_stale(s, now)]
                due.sort(key=lambda item: (item[0].fetched if item[0] is not None else "", item[1].key))
                tasks += [WarmTask(c, sort, s.fetched if s is not None else "") for s, c in due]
        for around in (own, ring):
            tasks += [WarmTask(c, AVIS) for c in around]
        return tasks

    async def warm(self, task: WarmTask) -> int:
        """Une tâche, en travail de fond : une case et une sorte (combien de lieux lus), ou la fiche des lieux d'une
        case ouverts depuis peu (``PURGE_TIMES`` fois la durée du cache), dont la fiche est vieille (combien de
        fiches lues)."""
        if task.part in SORTS:
            count, _done = await self.load(task.cell, task.part, background=True)
            return count
        now = self.clock()
        days = self.config().cache_days
        count = 0
        for spot in await asyncio.to_thread(self.reviews.due, task.cell.bbox,
                                            looked_since=older_than(now, PURGE_TIMES * days),
                                            before=older_than(now, days), limit=WARM_SPOTS_PER_CELL):
            await self._detail(spot, "", background=True)
            count += 1
        return count

    def budget(self) -> str:
        said = self.client.limiter.describe()
        for sku in SKUS:
            said += f" ; {self.client.skus[sku.service].describe()}"
        if not self.config().warm:
            said += " — les avis ne prennent pas part au réchauffage (réglé dans Avis (Google))"
        return said

    # ── ce qu'on en dit ──
    def coverage(self, near: tuple[float, float] | None,
                 bbox: tuple[float, float, float, float] | None) -> ReviewsCoverage:
        """Ce que le cache sait autour d'un point (sa case) ou dans une zone (ses cases, si elle n'en compte pas
        trop)."""
        info = self.reviews.info()
        size = self.config().cell_km
        if bbox is not None:
            found = cells_in(bbox, size, COVERAGE_CELLS_MAX)
            cells = found or []
        else:
            cells = [cell_of(near[0], near[1], size)] if near is not None else []
        if not self.client.ready():
            return ReviewsCoverage(info.ready, note=NO_KEY_NOTE + (" Les notes sont celles qu'on avait."
                                                                   if info.ready else ""))
        if not cells:
            return ReviewsCoverage(info.ready)
        states = self.reviews.cell_states([c.key for c in cells])
        loaded = [c for c in cells if all((s := states.get((c.key, k))) is not None and s.fetched for k in SORTS)]
        fetched = [s.fetched for s in states.values() if s.fetched]
        note = ""
        if len(loaded) < len(cells):
            recent = self.note_at is not None and self.clock() - self.note_at < NOTE_KEEP
            note = self.note if recent and self.note else \
                "Les notes de cet endroit ne sont pas encore toutes lues : elles le seront au préchargement ou ce soir."
        return ReviewsCoverage(info.ready, len(cells), len(loaded), min(fetched) if fetched else "", note)
