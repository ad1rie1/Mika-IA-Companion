"""La synchronisation des départements tenus en entier (ADR 0245) — une option : le cache par cases
(``tourism_cells``) est le chemin ordinaire ; ``TourismConfig.zones`` nomme des départements (« France » : tous) à
copier en entier dans ``cartes/tourisme.db``, en flux, page après page (jamais toute la France en mémoire). Vide : rien
ne se synchronise ainsi.

**Complète** : département par département (ou les zones réglées), les événements d'abord (ceux qui ne sont pas finis
et commencent avant l'horizon), puis les lieux ; chaque page s'écrit avec l'endroit où l'on en est (``progress``) :
interrompue, elle reprend là où elle s'est arrêtée (un curseur que l'API ne reconnaît plus refait son département).
Finie, ce qu'elle n'a pas vu s'efface — il n'y a pas de liste des fiches retirées. **Incrémentale** : ce qui a changé
(``lastUpdate``) depuis la dernière synchronisation, la veille comprise. Après chacune : le passé s'efface, et ce qui
a changé se rapproche de l'index des lieux (tout, quand l'index a été reconstruit).

**Quand** : le serveur la lance (``start``) quand une clé et des départements sont réglés — complète si elle n'en a
jamais eu, si une est en cours (reprise), si les départements ont changé ou si la dernière a plus d'une semaine ;
incrémentale chaque nuit à l'heure réglée (et au démarrage, si la nuit passée a été manquée) ; après une erreur, plus
tard (``RETRY_S``) ; et quand on la demande (« Synchroniser maintenant », ``wake``). Ses demandes sont un travail de
fond pour le limiteur : la réserve reste au direct. La commande ``mika carte tourisme`` la lance aussi (une première,
longue, sur le PC). **Un verrou** (``cartes/tourisme.lock``) empêche deux synchronisations d'écrire en même temps,
d'un processus ou de deux. Sa boucle refait aussi tout le rapprochement quand l'index des lieux a été reconstruit."""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import hashlib
import logging
import os
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from mika.adapters.maps.config import DEPARTMENTS, TourismConfig, tourism_key
from mika.adapters.maps.datatourisme import (
    AUTH,
    BROKEN,
    BUSY,
    CURSOR,
    ENDPOINTS,
    EVENTS,
    NETWORK,
    NO_KEY,
    REFUSED,
    SERVER,
    DataTourismeClient,
    Page,
    TourismUnavailable,
    filters,
    params,
    read_fiche,
)
from mika.adapters.maps.hours import PARIS
from mika.adapters.maps.tourism import NO_INDEX, Step, Tourism, TourismBase, paris_today, stamp, utc_now
from mika.adapters.maps.warm import last_slot

log = logging.getLogger("mika.maps.tourism")

LOCK_NAME = "tourisme.lock"
COMPLETE, INCREMENTAL = "complete", "incrementale"
KIND_FR = {COMPLETE: "complète", INCREMENTAL: "incrémentale"}
ENDPOINT_FR = {EVENTS: "événements", "placeOfInterest": "lieux"}
#: une synchronisation complète au moins tous les tant de jours (ce qu'elle ne voit plus s'efface)
FULL_EVERY = timedelta(days=7)
#: après une erreur, réessayer dans tant de secondes, selon sa sorte ; une clé refusée attend qu'on la change
RETRY_S = {BUSY: 900.0, SERVER: 600.0, NETWORK: 600.0, BROKEN: 900.0, REFUSED: 3600.0, CURSOR: 60.0,
           AUTH: 86_400.0}
BUSY_RETRY_S = 300.0
CRASH_RETRY_S = 900.0
#: le serveur regarde s'il y a lieu de synchroniser au moins tant de secondes
TICK_S = 60.0
#: au plus tant de pages pour un département (une boucle de l'API ne tourne pas sans fin)
PAGES_MAX = 20_000
SAY_EVERY = 20
#: les départements d'une synchronisation de toute la France : chacun, puis les fiches sans département
ALL_PARTS: tuple[str, ...] = (*DEPARTMENTS, "")


class SyncBusy(Exception):
    """Une autre synchronisation écrit déjà la base."""


class SyncLock:
    """Le verrou de la base : un seul qui écrive à la fois, d'un processus ou de deux (``flock`` : il tombe avec le
    processus)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return False
        self._fd = fd
        return True

    def release(self) -> None:
        if self._fd is not None:
            with contextlib.suppress(OSError):
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None


@dataclass(slots=True)
class Report:
    """Ce qu'une synchronisation a fait."""

    kind: str
    pages: int = 0
    fiches: int = 0
    unread: int = 0
    removed: int = 0
    passed: int = 0
    twins: int = 0
    venues: int = 0
    requests: int = 0
    seconds: float = 0.0
    resumed: bool = False


def _parse(iso: str) -> datetime | None:
    try:
        at = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return at if at.tzinfo is not None else at.replace(tzinfo=PARIS)


def _zones_key(cfg: TourismConfig) -> str:
    return ",".join(cfg.zones)


def _zones(cfg: TourismConfig) -> tuple[str, ...]:
    """Les départements d'une synchronisation (« France » : aucun filtre, tous)."""
    return () if cfg.everywhere else cfg.zones


NO_ZONES = ("Aucun département n'est tenu en entier : le cache par cases suffit (Réglages › Carte et téléphone › "
            "Données touristiques, « Départements tenus en entier », ou --zones).")


def _fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16] if key else ""


class TourismSync:
    """La synchronisation de ``tourism`` (sa base), avec la clé et les zones de ``config`` (relu à chaque fois),
    rapprochée de l'index des lieux que ``index`` rend (son chemin et sa date de construction ; ``None`` : aucun)."""

    def __init__(self, tourism: Tourism, config: Callable[[], TourismConfig], client: DataTourismeClient, *,
                 index: Callable[[], tuple[Path, str] | None] = lambda: None,
                 clock: Callable[[], datetime] = utc_now, say: Callable[[str], None] = log.info,
                 sleep: Callable[[float], Awaitable[object]] = asyncio.sleep) -> None:
        self.tourism = tourism
        self.config = config
        self.client = client
        self.index = index
        self.clock = clock
        self.say = say
        self._sleep = sleep
        self.lock = SyncLock(tourism.path.with_name(LOCK_NAME))
        #: ce qu'elle fait, pour la console
        self.running = False
        self.doing = ""
        self.last_error = ""
        self.retry_at: datetime | None = None
        self._failed_key = ""
        self._forced = False
        self._wake = asyncio.Event()
        self._worker: asyncio.Task[None] | None = None

    # ── une synchronisation ──
    async def run(self, *, full: bool | None = None) -> Report:
        """Une synchronisation, complète (``full``), incrémentale, ou ce qui est dû (``None`` : complète si la base
        n'en a jamais eu, si une est à reprendre, si les zones ont changé ou si la dernière a une semaine). Une autre
        en cours : ``SyncBusy`` ; DATAtourisme injoignable : ``TourismUnavailable`` (ce qui est écrit reste, une
        complète reprendra là)."""
        cfg = self.config()
        if not tourism_key(cfg)[0]:
            raise TourismUnavailable(NO_KEY, AUTH)
        if not cfg.zones:
            raise ValueError(NO_ZONES)
        if not self.lock.acquire():
            raise SyncBusy("Une synchronisation des données touristiques est déjà en cours.")
        started = self.clock()
        asked = self.client.asked
        self.running = True
        conn: sqlite3.Connection | None = None
        try:
            conn = await asyncio.to_thread(self.tourism.base.open)
            meta = TourismBase.meta(conn)
            if full is None:
                full = self._full_due(meta, cfg, started)
            try:
                report = await (self._full(conn, cfg, meta, started) if full else
                                self._incremental(conn, cfg, meta, started))
            except TourismUnavailable as exc:
                self.last_error = str(exc)
                TourismBase.set_meta(conn, {"last_error": str(exc), "last_error_at": stamp(self.clock())})
                raise
            today = paris_today(self.clock())
            report.passed = await asyncio.to_thread(TourismBase.purge, conn, today)
            report.twins, report.venues = await asyncio.to_thread(self._match, conn, meta)
            ended = self.clock()
            TourismBase.set_meta(conn, {"last_sync": stamp(started), "last_kind": report.kind,
                                        "last_ended": stamp(ended), "zones": _zones_key(cfg), "last_error": None,
                                        "last_error_at": None})
            self.last_error = ""
            report.requests = self.client.asked - asked
            report.seconds = round((ended - started).total_seconds(), 1)
            self.say(f"données touristiques : synchronisation {KIND_FR[report.kind]} finie — {report.fiches} fiches "
                     f"en {report.pages} pages, {report.removed + report.passed} effacées, {report.requests} "
                     "demandes")
            return report
        finally:
            if conn is not None:
                conn.close()
            self.lock.release()
            self.running = False
            self.doing = ""

    def _full_due(self, meta: dict[str, str], cfg: TourismConfig, now: datetime) -> bool:
        if meta.get("run") or not meta.get("last_full") or not meta.get("since"):
            return True
        if meta.get("zones", "") != _zones_key(cfg):
            return True
        last = _parse(meta["last_full"])
        return last is None or now - last >= FULL_EVERY

    async def _full(self, conn: sqlite3.Connection, cfg: TourismConfig, meta: dict[str, str],
                    started: datetime) -> Report:
        zones = _zones_key(cfg)
        today = paris_today(started)
        run = meta.get("run", "")
        report = Report(COMPLETE)
        if run and meta.get("run_zones") == zones and meta.get("run_horizon") == str(cfg.horizon_days):
            report.resumed = True
            self.say(f"données touristiques : reprise de la synchronisation complète du {run}")
        else:
            run = stamp(started)
            parts = [(endpoint, part) for endpoint in ENDPOINTS for part in (_zones(cfg) or ALL_PARTS)]
            await asyncio.to_thread(TourismBase.begin_run, conn, run, zones, cfg.horizon_days, parts)
        horizon = today + timedelta(days=cfg.horizon_days)
        for endpoint, part, following, count in await asyncio.to_thread(TourismBase.pending, conn, run):
            events = endpoint == EVENTS
            expression = filters(department=part, events_from=today if events else None,
                                 events_to=horizon if events else None)
            page: Page | None = None
            if following:
                try:
                    page = await self.client.follow(following)
                except TourismUnavailable as exc:
                    if exc.kind != CURSOR:
                        raise
                    await asyncio.to_thread(TourismBase.restart_part, conn, run, endpoint, part)
                    count = 0
            if page is None:
                try:
                    page = await self.client.first(endpoint, params(endpoint, expression))
                except TourismUnavailable as exc:
                    if exc.kind != REFUSED or part:
                        raise
                    # les fiches sans département : un filtre que l'API pourrait refuser — elles ne bloquent rien
                    self.say(f"données touristiques : {ENDPOINT_FR[endpoint]} sans département laissées ({exc})")
                    page = Page([])
            await self._pages(conn, page, report, run=run, today=today, endpoint=endpoint, part=part, count=count)
        report.removed = await asyncio.to_thread(TourismBase.finish_run, conn, run, _zones(cfg))
        TourismBase.set_meta(conn, {"last_full": stamp(self.clock()), "since": run})
        return report

    async def _pages(self, conn: sqlite3.Connection, page: Page, report: Report, *, run: str | None, today: date,
                     endpoint: str, part: str | None, count: int = 0) -> None:
        """Une liste, page après page : chacune lue, écrite (avec l'endroit où l'on en est), puis la suivante."""
        where = ENDPOINT_FR[endpoint] + (f" · {part or 'sans département'}" if part is not None else "")
        seen: set[str] = set()
        for number in range(1, PAGES_MAX + 1):
            fiches = [f for f in map(read_fiche, page.objects) if f is not None]
            report.unread += len(page.objects) - len(fiches)
            done = not page.next
            step = Step(run, endpoint, part, page.next, done) if run is not None and part is not None else None
            await asyncio.to_thread(TourismBase.write_page, conn, fiches, run=run, synced=stamp(self.clock()),
                                    today=today, step=step)
            report.pages += 1
            report.fiches += len(fiches)
            count += len(fiches)
            self.doing = f"{KIND_FR[report.kind]} · {where} : {count} fiches"
            if done:
                self.say(f"données touristiques : {where} — {count} fiches")
                return
            if number % SAY_EVERY == 0:
                self.say(f"données touristiques : {where} — {count} fiches (sur {page.total})")
            if page.next in seen:
                raise TourismUnavailable("DATAtourisme renvoie à une page déjà lue.", BROKEN)
            seen.add(page.next)
            page = await self.client.follow(page.next)
        raise TourismUnavailable(f"DATAtourisme donne plus de {PAGES_MAX} pages pour {where}.", BROKEN)

    async def _incremental(self, conn: sqlite3.Connection, cfg: TourismConfig, meta: dict[str, str],
                           started: datetime) -> Report:
        since_at = _parse(meta.get("since", "")) or started
        since = paris_today(since_at) - timedelta(days=1)  # ``lastUpdate`` est un jour : la veille comprise
        today = paris_today(started)
        report = Report(INCREMENTAL)
        for endpoint in ENDPOINTS:
            events = endpoint == EVENTS
            expression = filters(zones=_zones(cfg), since=since, events_from=today if events else None,
                                 events_to=today + timedelta(days=cfg.horizon_days) if events else None)
            page = await self.client.first(endpoint, params(endpoint, expression))
            await self._pages(conn, page, report, run=None, today=today, endpoint=endpoint, part=None)
        TourismBase.set_meta(conn, {"since": stamp(started)})
        return report

    def _match(self, conn: sqlite3.Connection, meta: dict[str, str]) -> tuple[int, int]:
        index = self.index()
        built = index[1] if index is not None else NO_INDEX
        everything = TourismBase.meta(conn).get("matched_with", "") != built
        got = TourismBase.match(conn, index[0] if index is not None else None, everything=everything)
        TourismBase.set_meta(conn, {"matched_with": built})
        return got

    async def refresh(self, uuid: str) -> bool:
        """Une fiche relue tout de suite (``/catalog/{uuid}``, la fiche d'un lieu qu'on actualise), écrite, rapprochée ;
        disparue chez DATAtourisme : effacée. Rend si elle existe encore. Ce qui ne va pas : ``TourismUnavailable``."""
        raw = await self.client.fiche(uuid)
        try:
            conn = await asyncio.to_thread(self.tourism.base.open)
        except (sqlite3.Error, OSError):  # tenue par une autre écriture : elle reste, on le dit
            raise TourismUnavailable("La base des données touristiques ne s'écrit pas en ce moment : réessaie dans "
                                     "un instant.", BROKEN) from None
        try:
            if raw is None:
                await asyncio.to_thread(TourismBase.forget, conn, uuid)
                return False
            fiche = read_fiche(raw)
            if fiche is None:
                return False
            await asyncio.to_thread(TourismBase.write_page, conn, [fiche], run=None, synced=stamp(self.clock()),
                                    today=paris_today(self.clock()))
            index = self.index()
            if index is not None and TourismBase.meta(conn).get("matched_with", "") == index[1]:
                await asyncio.to_thread(TourismBase.match, conn, index[0], everything=False)
            return True
        finally:
            conn.close()

    async def rematch(self) -> bool:
        """L'index des lieux a été reconstruit depuis le dernier rapprochement : tout se rapproche à nouveau (sans rien
        demander à DATAtourisme). Rend s'il l'a fait."""
        info = self.tourism.info()
        index = self.index()
        if not info.ready or index is None or info.matched_with == index[1] or self.running or \
                not self.lock.acquire():
            return False
        try:
            conn = await asyncio.to_thread(self.tourism.base.open)
            try:
                if TourismBase.meta(conn).get("matched_with", "") == index[1]:
                    return False
                self.doing = "rapprochement avec l'index des lieux"
                await asyncio.to_thread(self._match, conn, {})
                return True
            finally:
                conn.close()
        finally:
            self.lock.release()
            self.doing = ""

    # ── quand ──
    def due(self, now: datetime) -> str | None:
        """Ce qu'il y a à faire à cet instant : ``COMPLETE``, ``INCREMENTAL`` ou rien."""
        cfg = self.config()
        key = tourism_key(cfg)[0]
        if not key or not cfg.zones or self.running:
            return None
        if self._failed_key and _fingerprint(key) != self._failed_key:  # une autre clé : on réessaie
            self._failed_key, self.retry_at = "", None
        if self._forced:
            return COMPLETE if self._complete_due(cfg, now) else INCREMENTAL
        if self.retry_at is not None and now < self.retry_at:
            return None
        if self._complete_due(cfg, now, at_night=False):
            return COMPLETE
        info = self.tourism.info()
        last = _parse(info.last_sync)
        if last is None or last < last_slot(now, cfg.night_hour):
            return COMPLETE if self._complete_due(cfg, now) else INCREMENTAL
        return None

    def _complete_due(self, cfg: TourismConfig, now: datetime, *, at_night: bool = True) -> bool:
        """Une complète : tout de suite si la base n'en a jamais eu, si une est à reprendre, si les zones ont changé ;
        la nuit (``at_night``), aussi si la dernière a une semaine."""
        info = self.tourism.info()
        if info.run or not info.last_full or info.zones != _zones_key(cfg):
            return True
        last = _parse(info.last_full)
        return at_night and (last is None or now - last >= FULL_EVERY)

    def next_at(self, now: datetime) -> datetime | None:
        """Quand la prochaine partira (``None`` : en cours, ou aucune clé)."""
        cfg = self.config()
        if self.running or not tourism_key(cfg)[0] or not cfg.zones:
            return None
        if self.retry_at is not None and now < self.retry_at:
            return self.retry_at
        if self.due(now):
            return now
        return last_slot(now, cfg.night_hour) + timedelta(days=1)

    def failed(self, exc: TourismUnavailable, now: datetime) -> None:
        self.last_error = str(exc)
        self.retry_at = now + timedelta(seconds=RETRY_S.get(exc.kind, CRASH_RETRY_S))
        if exc.kind == AUTH:
            self._failed_key = _fingerprint(tourism_key(self.config())[0])
        log.warning("données touristiques : %s (nouvel essai vers %s)", exc,
                    self.retry_at.astimezone(PARIS).strftime("%H:%M"))

    # ── le cycle de vie (le serveur) ──
    def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.get_running_loop().create_task(self._loop())

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None

    def wake(self) -> tuple[str, str]:
        """« Synchroniser maintenant » : (ton, message)."""
        if not tourism_key(self.config())[0]:
            return "danger", NO_KEY
        if not self.config().zones:
            return "info", NO_ZONES
        if self.running:
            return "info", f"Une synchronisation est déjà en cours ({self.doing or 'elle commence'})."
        if self._worker is None:
            return "danger", "La synchronisation ne tourne pas sur ce serveur."
        self._forced = True
        self.retry_at = None
        self._wake.set()
        return "ok", "La synchronisation part : la page le dira en se rechargeant."

    async def _loop(self) -> None:
        while True:
            now = self.clock()
            try:
                what = self.due(now)
                if what:
                    self._forced = False
                    await self.run(full=what == COMPLETE)
                    self.retry_at = None
                else:
                    await self.rematch()
            except SyncBusy:
                self.retry_at = now + timedelta(seconds=BUSY_RETRY_S)
            except TourismUnavailable as exc:
                self.failed(exc, now)
            except (sqlite3.Error, OSError) as exc:
                self.last_error = f"la base des données touristiques : {exc}"
                self.retry_at = now + timedelta(seconds=CRASH_RETRY_S)
                log.warning("données touristiques : %s", self.last_error)
            except Exception:  # noqa: BLE001 — une synchronisation en panne ne fait rien tomber : elle réessaiera
                self.last_error = "une erreur inattendue (le journal du serveur la détaille)"
                self.retry_at = now + timedelta(seconds=CRASH_RETRY_S)
                log.exception("données touristiques : la synchronisation a échoué")
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), TICK_S)
