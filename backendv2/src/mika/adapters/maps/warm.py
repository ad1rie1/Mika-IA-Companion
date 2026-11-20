"""Le réchauffage des caches de la carte (ADR 0245), partagé par leurs sources (DATAtourisme, puis Google Places) :
chaque soir à l'heure réglée (``WarmConfig.hour``, 22:00 de Paris par défaut), il rafraîchit ou crée le cache autour
des dernières positions connues des personnes (que la composition lui donne : ``points``) et des points fixes réglés,
sur ce qui reste du budget de chaque source, sa réserve gardée au direct.

**Une source** (``WarmSource``) dit ce qu'il y a à faire autour de ces points, dans l'ordre où elle le veut
(``plan`` : DATAtourisme les événements d'abord, puis les lieux ; les cases les plus vieilles d'abord), et le fait une
tâche à la fois (``warm``, en travail de fond pour son limiteur). Les sources tournent ensemble, chacune sur son propre
quota : quand le sien est pris, elle attend qu'il revienne si c'est avant la fin du passage (``WINDOW_H`` heures),
sinon elle s'arrête en le disant. Pour en brancher une : ``warmer.add_source(source)``.

Ce qu'il a fait se garde dans ``cartes/rechauffage.json`` : la console le montre (dernier passage, cases rafraîchies,
budget consommé et restant, prochaine heure), et un redémarrage ne relance pas un passage déjà fait."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Protocol

from mika.adapters.maps.cells import Cell
from mika.adapters.maps.config import MAPS_DIR, WarmConfig
from mika.adapters.maps.hours import PARIS
from mika.adapters.maps.quota import QuotaExceeded
from mika.ports.maps import MapsUnavailable

log = logging.getLogger("mika.maps.warm")

STATE_FILE = f"{MAPS_DIR}/rechauffage.json"
#: un passage dure au plus tant d'heures (de 22:00 à 06:00) : au-delà, ce qui reste attend le soir suivant
WINDOW_H = 8
#: après tant d'erreurs de suite (pas un quota), une source s'arrête pour ce passage
ERRORS_MAX = 5
TICK_S = 60.0


def last_slot(now: datetime, hour: int) -> datetime:
    """La dernière heure ``hour`` passée (heure de Paris), à cet instant."""
    local = now.astimezone(PARIS)
    slot = datetime.combine(local.date(), time(hour), PARIS)
    return slot if slot <= local else datetime.combine(local.date() - timedelta(days=1), time(hour), PARIS)


@dataclass(frozen=True, slots=True)
class WarmTask:
    """Une case à rafraîchir pour une source : ``part`` (ses événements, ses lieux…), ``fetched`` (quand elle l'a été,
    ISO 8601 ; vide : jamais)."""

    cell: Cell
    part: str
    fetched: str = ""


class WarmSource(Protocol):
    name: str
    label: str

    def ready(self) -> bool:
        """Elle peut travailler (une clé est réglée)."""
        ...

    def plan(self, points: Sequence[tuple[float, float]], now: datetime) -> list[WarmTask]:
        """Ce qu'il y a à faire autour de ces points (dans ses cases), dans l'ordre où elle le veut."""
        ...

    async def warm(self, task: WarmTask) -> int:
        """Une tâche, en travail de fond : combien de fiches lues. Son quota pris : ``QuotaExceeded`` ; une autre
        panne : ``MapsUnavailable``."""
        ...

    def budget(self) -> str:
        """Son budget en mots : consommé, restant, ce qui le bloque."""
        ...


@dataclass(slots=True)
class SourceRun:
    """Ce qu'une source a fait d'un passage."""

    label: str
    planned: int = 0
    done: int = 0
    fiches: int = 0
    errors: int = 0
    stopped: str = ""


@dataclass(slots=True)
class WarmRun:
    started: str
    ended: str = ""
    points: int = 0
    sources: list[SourceRun] = field(default_factory=list)


def _stamp(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def parse_point(text: str) -> tuple[float, float] | None:
    """« 45.90, 6.13 » : un point ; autre chose : ``None`` (un nom, à chercher dans l'index des lieux)."""
    lat, sep, lon = text.replace(";", ",").partition(",")
    if not sep:
        return None
    try:
        at = float(lat), float(lon)
    except ValueError:
        return None
    return at if -90 <= at[0] <= 90 and -180 <= at[1] <= 180 else None


class Warmer:
    """Le réchauffage : ses sources, les positions des personnes (``points``, rendues par la composition), ses
    réglages (``config``, relus à chaque fois), ``resolve`` pour un point fixe nommé (une ville de l'index des lieux)."""

    def __init__(self, data: Path, config: Callable[[], WarmConfig], *,
                 points: Callable[[], Sequence[tuple[float, float]]] = lambda: (),
                 resolve: Callable[[str], Awaitable[tuple[float, float] | None]] | None = None,
                 sources: Sequence[WarmSource] = (), clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 sleep: Callable[[float], Awaitable[object]] = asyncio.sleep) -> None:
        self.path = data / STATE_FILE
        self.config = config
        self.points = points
        self.resolve = resolve
        self.sources: list[WarmSource] = list(sources)
        self.clock = clock
        self._sleep = sleep
        self.running = False
        self.last: WarmRun | None = self._load()
        self._worker: asyncio.Task[None] | None = None
        self._forced = False
        self._wake = asyncio.Event()

    def add_source(self, source: WarmSource) -> None:
        self.sources.append(source)

    # ── ce qu'il a fait ──
    def _load(self) -> WarmRun | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return WarmRun(started=str(raw["started"]), ended=str(raw.get("ended", "")),
                           points=int(raw.get("points", 0)),
                           sources=[SourceRun(**s) for s in raw.get("sources", []) if isinstance(s, dict)])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _save(self, run: WarmRun) -> None:
        with contextlib.suppress(OSError):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            partial = self.path.with_name(self.path.name + ".partiel")
            partial.write_text(json.dumps(asdict(run), ensure_ascii=False), encoding="utf-8")
            os.replace(partial, self.path)

    # ── un passage ──
    async def where(self) -> list[tuple[float, float]]:
        """Les points d'un passage : les positions des personnes (si le réglage le veut), puis les points fixes ; à une
        centaine de mètres près, chacun une fois."""
        cfg = self.config()
        found: list[tuple[float, float]] = list(self.points()) if cfg.people else []
        for text in cfg.points:
            at = parse_point(text)
            if at is None and self.resolve is not None:
                with contextlib.suppress(MapsUnavailable, ValueError):
                    at = await self.resolve(text)
            if at is not None:
                found.append(at)
        return list(dict.fromkeys((round(lat, 3), round(lon, 3)) for lat, lon in found))

    async def run(self) -> WarmRun:
        """Un passage, maintenant : chaque source prête, ensemble, jusqu'à la fin de la fenêtre."""
        started = self.clock()
        deadline = started + timedelta(hours=WINDOW_H)
        self.running = True
        try:
            points = await self.where()
            ready = [s for s in self.sources if s.ready()]
            run = WarmRun(_stamp(started), points=len(points), sources=[SourceRun(s.label) for s in ready])
            self.last = run
            await asyncio.gather(*(self._source(s, r, points, deadline) for s, r in zip(ready, run.sources,
                                                                                     strict=True)))
            run.ended = _stamp(self.clock())
            self._save(run)
            log.info("réchauffage : %s", " ; ".join(f"{r.label} {r.done}/{r.planned} cases" for r in run.sources)
                     or "aucune source prête")
            return run
        finally:
            self.running = False

    async def _source(self, source: WarmSource, report: SourceRun, points: Sequence[tuple[float, float]],
                      deadline: datetime) -> None:
        tasks = source.plan(points, self.clock())
        report.planned = len(tasks)
        errors = 0
        for task in tasks:
            while True:
                try:
                    report.fiches += await source.warm(task)
                    report.done += 1
                    errors = 0
                    break
                except QuotaExceeded as exc:
                    if exc.until is None or exc.until > deadline:
                        report.stopped = str(exc)
                        return
                    await self._sleep(max(1.0, (exc.until - self.clock()).total_seconds()))
                except MapsUnavailable as exc:
                    errors += 1
                    report.errors += 1
                    if errors >= ERRORS_MAX or getattr(exc, "kind", "") == "cle":
                        report.stopped = str(exc)
                        return
                    break

    # ── quand ──
    def due(self, now: datetime) -> bool:
        if self.running or not any(s.ready() for s in self.sources):
            return False
        last = _parse(self.last.started) if self.last is not None else None
        return last is None or last < last_slot(now, self.config().hour)

    def next_at(self, now: datetime) -> datetime | None:
        if self.running or not any(s.ready() for s in self.sources):
            return None
        return now if self.due(now) else last_slot(now, self.config().hour) + timedelta(days=1)

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
        """« Réchauffer maintenant » : (ton, message)."""
        if not any(s.ready() for s in self.sources):
            return "danger", "Aucune source n'est prête (une clé à régler)."
        if self.running:
            return "info", "Un passage est déjà en cours."
        if self._worker is None:
            return "danger", "Le réchauffage ne tourne pas sur ce serveur."
        self._forced = True
        self._wake.set()
        return "ok", "Le réchauffage part : la page le dira en se rechargeant."

    async def _loop(self) -> None:
        while True:
            try:
                if self._forced or self.due(self.clock()):
                    self._forced = False
                    await self.run()
            except Exception:  # noqa: BLE001 — un réchauffage en panne ne fait rien tomber : il reviendra le soir suivant
                log.exception("réchauffage : le passage a échoué")
                self.last = WarmRun(_stamp(self.clock()), ended=_stamp(self.clock()))
                self._save(self.last)
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), TICK_S)

    # ── ce que la console en dit ──
    def describe(self, at_fr: Callable[[str], str]) -> list[tuple[str, str]]:
        now = self.clock()
        cfg = self.config()
        facts = [("Quand", f"chaque soir à {cfg.hour:02d}:00 (heure de Paris), {WINDOW_H} heures au plus, sur ce qui "
                           "reste des quotas de chaque source (leur réserve gardée au direct)"),
                 ("Autour de", ("la dernière position de chaque personne qui l'a permise" if cfg.people else
                                "personne") + (f", et {len(cfg.points)} point(s) fixe(s)" if cfg.points else ""))]
        if not self.sources:
            facts.append(("Sources", "aucune n'est branchée"))
            return facts
        last = self.last
        if self.running:
            facts.append(("En ce moment", "un passage est en cours"))
        if last is not None:
            facts.append(("Dernier passage", f"{at_fr(last.started)}, autour de {last.points} point(s)"
                                             + ("" if last.ended else " (pas fini)")))
            for r in last.sources:
                said = f"{r.done} case(s) rafraîchie(s) sur {r.planned}, {r.fiches} fiche(s)"
                if r.errors:
                    said += f", {r.errors} erreur(s)"
                if r.stopped:
                    said += f" — arrêté : {r.stopped}"
                facts.append((r.label, said))
        else:
            facts.append(("Dernier passage", "jamais"))
        for source in self.sources:
            facts.append((f"Budget de {source.label}", source.budget() if source.ready() else
                          "pas de clé : rien ne part"))
        upcoming = self.next_at(now)
        if upcoming is not None:
            facts.append(("Prochain passage", "maintenant" if upcoming <= now else at_fr(_stamp(upcoming))))
        return facts
