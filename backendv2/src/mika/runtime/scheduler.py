"""Ordonnanceur à événements discrets.

Chaque processus déclare ``next_due(état, frame, dernière_exécution)`` : un
instant, ou ``None`` (en sommeil jusqu'à un événement de réveil). La boucle
attend la plus proche échéance — ou un réveil — puis lance les processus dus,
un seul à la fois par processus.

Après un arrêt ou un saut d'horloge, une échéance très en retard donne **une**
exécution, avec ``missed=(échéance, maintenant)`` : pas de rafale. Avec
``CatchUp.SKIP``, elle est sautée une fois ; si ``next_due`` la redonne telle
quelle (une échéance qui ne lit pas ``last_run``), le processus fait un passage
ordinaire, sans ``missed``, au lieu de rester figé. Un quantum
borne l'attente pour réévaluer les échéances qui dépendent du temps.

**Boucles sûres par construction.** Un processus qui échoue n'est pas relancé
aussitôt : son échéance est repoussée par un recul exponentiel (5 s, 10 s, …
jusqu'à une heure), et seul le premier échec d'une série est journalisé
(``runtime.process_failed``) — un port indisponible ne remplit pas le journal.
Un passage qui n'a rien écrit (un ajout entièrement dédoublonné ne compte
pas) et se redit dû tout de suite attend 30 s, puis 1 min, 2 min… jusqu'à une
heure tant que rien de ce qui le réveille ne bouge : un processus qui croit
avoir du travail sans jamais en faire ne tourne pas à vide. Et quoi qu'il
fasse, un processus qui enchaîne plus de ``STORM_RUNS`` passages en une
minute est retenu une minute, puis deux, quatre… (une rafale, que la santé
montre) : même un passage qui écrit à chaque fois sans jamais finir ne
remplit pas le journal.
Un passage a une échéance (``deadline_s``) : au-delà il est coupé et compte
comme un échec.

**Les voies selon la nature du travail.** Le calcul pur ne prend aucune place :
un processus ne tient la voie ``model`` (bornée) que le temps de ses appels de
modèle — deux consolidations lentes n'empêchent plus le sommeil de tomber ni
l'attention de remarquer. Une voie déclarée exclusive (``night``) se tient pour
tout le passage : le travail de la nuit se fait un à la fois.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from mika.contracts.runtime import PROCESS_FAILED
from mika.kernel.events import Draft, Event, Origin
from mika.kernel.faculty import CatchUp, ProcessSpec
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, combine
from mika.kernel.state import Root
from mika.ports.llm import RETRY_AFTER_CUT
from mika.runtime.boundary import Failed, acall, call
from mika.runtime.tools import TOOL_CALL_CAP_CEILING, release

if TYPE_CHECKING:
    from mika.runtime.mind import Commit, Mind

ANY_EVENT = "*"
US = 1_000_000
#: la voie des appels de modèle des processus (bornée)
MODEL_LANE = "model"
#: les voies tenues pour tout le passage (le travail de la nuit, un à la fois)
EXCLUSIVE_LANES = frozenset({"night"})
DEFAULT_LANES: Mapping[str, int] = {MODEL_LANE: 2, "night": 1}
#: recul après un échec : 5 s, doublé à chaque échec d'affilée, jamais plus d'une heure
BACKOFF_BASE_US = 5 * US
BACKOFF_MAX_US = 3600 * US
#: un passage qui n'a rien écrit et se redit dû aussitôt attend ce délai, doublé à chaque passage à vide
#: d'affilée (rien de ce qui le réveille n'ayant bougé), jusqu'à une heure
IDLE_GUARD_US = 30 * US
IDLE_GUARD_MAX_US = 3600 * US
#: au-delà de tant de passages d'un même processus en ``STORM_WINDOW_US``, il est retenu ``STORM_WINDOW_US``
STORM_RUNS = 120
STORM_WINDOW_US = 60 * US
#: l'échéance d'un passage quand son processus n'en déclare pas
DEFAULT_DEADLINE_S = 900.0


@dataclass(slots=True)
class ProcessContext:
    mind: Mind
    spec: ProcessSpec
    run_id: str
    frame: Frame
    missed: tuple[int, int] | None = None
    llm: Any = None
    ports: Mapping[str, Any] = field(default_factory=dict)
    #: ce que ce passage a écrit (nombre d'ajouts) : un passage qui n'écrit rien n'a pas avancé
    emitted: int = 0

    @property
    def state(self) -> Any:
        return self.frame.state(self.spec.owner)

    @property
    def now(self) -> int:
        return self.mind.clock.now()

    async def emit(self, *drafts: Draft[Any], guard: Guard | None = None, emitter: str | None = None) -> Commit:
        commit = await self.mind.append(
            list(drafts), emitter=emitter or self.spec.owner, correlation=self.run_id,
            origin=Origin.PROCESS, basis=self.frame.root, guard=combine(guard) if guard else None,
            holder=self.run_id,
        )
        if not commit.deduped:
            self.emitted += 1  # un ajout entièrement dédoublonné n'a rien écrit : ce n'est pas un progrès
        self.frame = Frame(commit.root, self.mind.clock.now(), self.mind.registry)
        return commit

    async def refresh(self) -> Frame:
        self.frame = self.mind.frame()
        return self.frame

    async def ask(self, request: Any) -> Any:
        """Un appel de modèle dont la panne est une absence (``None``) : un tri
        raté n'empêche pas de remarquer un mail."""
        if self.llm is None:
            return None
        got = await acall(self.llm.call, request, label=f"modèle ({getattr(request, 'role', '?')})")
        return None if isinstance(got, Failed) else got


class _BoundedLLM:
    """La passerelle vue d'un processus : chaque appel tient une place de la voie ``model`` le temps de
    l'appel, et seulement lui. Un processus ne mène pas de boucle d'outils (il lit une sortie structurée, au
    besoin sur un appel d'outil) : chaque appel est relâché dès qu'il revient (``release(call_id)``). Cette
    sortie lue sur un appel d'outil, coupée par son plafond, personne d'autre ne la redemande (la passerelle
    laisse ce rejeu à la boucle d'outils des épisodes) : elle l'est ici, une fois, au plafond doublé."""

    __slots__ = ("_llm", "_sem")

    def __init__(self, llm: Any, sem: asyncio.Semaphore) -> None:
        self._llm = llm
        self._sem = sem

    async def call(self, request: Any) -> Any:
        try:
            async with self._sem:
                resp = await self._llm.call(request)
                if getattr(resp, "truncated_tool_call", False) and request.max_tokens < TOOL_CALL_CAP_CEILING:
                    resp = await self._llm.call(replace(
                        request, max_tokens=min(TOOL_CALL_CAP_CEILING, request.max_tokens * 2),
                        meta={**dict(request.meta), RETRY_AFTER_CUT: True}))
                return resp
        finally:
            release(self._llm, str(getattr(request, "call_id", "")))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._llm, name)


class Scheduler:
    def __init__(
        self,
        mind: Mind,
        *,
        extra: Iterable[ProcessSpec] = (),
        lanes: Mapping[str, int] | None = None,
        llm: Any = None,
        ports: Mapping[str, Any] | None = None,
        deadline_s: float = DEFAULT_DEADLINE_S,
    ) -> None:
        self.mind = mind
        self.specs: list[ProcessSpec] = sorted(
            list(mind.registry.processes.values()) + list(extra), key=lambda s: (s.priority, s.name)
        )
        self.ports = dict(ports or {})
        self.deadline_s = deadline_s
        #: une instance par processus et par ordonnanceur (jamais partagée entre noyaux)
        self.instances: dict[str, Any] = {
            s.name: s.process() if isinstance(s.process, type) else s.process for s in self.specs
        }
        caps = {**DEFAULT_LANES, **dict(lanes or {})}
        self._lanes = {name: asyncio.Semaphore(max(1, n)) for name, n in caps.items()}
        self.llm = _BoundedLLM(llm, self._lanes[MODEL_LANE]) if llm is not None else None
        self._last_run: dict[str, int] = {}
        #: l'échéance en retard sautée (``CatchUp.SKIP``) : si elle revient telle quelle, le processus tourne
        self._skipped: dict[str, int] = {}
        self._running: dict[str, asyncio.Task[None]] = {}
        self._wake = asyncio.Event()
        self._stopping = False
        self._wake_types: set[str] = set()
        self._any = False
        for s in self.specs:
            if ANY_EVENT in s.wake_on:
                self._any = True
            self._wake_types |= s.wake_on
        self.failures: dict[str, int] = {}
        self.runs: dict[str, int] = {}
        #: échecs d'affilée (remis à zéro par un succès) et dernière erreur : la santé
        self.consecutive: dict[str, int] = {}
        self.last_error: dict[str, tuple[int, str]] = {}
        #: pas avant cet instant (recul après un échec)
        self.not_before: dict[str, int] = {}
        #: la fin du dernier passage qui n'a rien écrit, et combien d'affilée
        self._idle_at: dict[str, int] = {}
        self._idle_streak: dict[str, int] = {}
        #: les débuts des derniers passages (une rafale se voit à leur densité) ; les rafales retenues
        self._recent: dict[str, deque[int]] = {}
        self.storms: dict[str, int] = {}
        mind.subscribe(self._on_events)

    def _on_events(self, events: Sequence[Event[Any]], root: Root) -> None:
        if self._any or any(e.type.name in self._wake_types for e in events):
            self._wake.set()
        if self._idle_at:
            names = {e.type.name for e in events}
            for spec in self.specs:
                if spec.name in self._idle_at and (ANY_EVENT in spec.wake_on or spec.wake_on & names):
                    del self._idle_at[spec.name]  # ce qui l'intéresse a bougé : il peut repasser tout de suite
                    self._idle_streak.pop(spec.name, None)

    def poke(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stopping = True
        self._wake.set()

    async def run(self) -> None:
        clock = self.mind.clock
        while not self._stopping:
            self._wake.clear()
            frame = self.mind.frame()
            now = frame.now
            timer: int | None = None
            due: list[tuple[int, ProcessSpec]] = []
            for spec in self.specs:
                if spec.name in self._running:
                    continue
                state = frame.root.slices.get(spec.owner)
                nd = call(self.instances[spec.name].next_due, state, frame, self._last_run.get(spec.name),
                          label=f"échéance de {spec.name}")
                if isinstance(nd, Failed):
                    self._failed(spec.name, now, nd.error)
                    continue
                nd = self._held_back(spec.name, nd, now)
                if nd is not None and nd <= now:
                    due.append((nd, spec))
                    continue
                horizon = now + spec.max_quantum_us if spec.max_quantum_us > 0 else None
                candidates = [t for t in (nd, horizon) if t is not None]
                if candidates:
                    wake_at = min(candidates)
                    timer = wake_at if timer is None else min(timer, wake_at)
            for nd, spec in sorted(due, key=lambda x: (x[0], x[1].priority, x[1].name)):
                missed = (nd, now) if spec.max_quantum_us > 0 and now - nd > spec.max_quantum_us else None
                skipped = self._skipped.pop(spec.name, None)
                if missed and spec.catch_up is CatchUp.SKIP:
                    if skipped is None or nd > skipped:
                        self._skipped[spec.name] = nd
                        self._last_run[spec.name] = now
                        continue
                    # la même échéance revient : son ``next_due`` ne lit pas ``last_run``. Sauter voulait dire ne
                    # pas rattraper l'occurrence manquée, pas ne plus jamais tourner : un passage ordinaire.
                    missed = None
                self._start(spec, frame, missed)
            if self._stopping:
                break
            if timer is None:
                await self._wake.wait()
            else:
                delay = max(0, timer - clock.now()) / 1_000_000
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=delay)
                except TimeoutError:
                    pass

    def _start(self, spec: ProcessSpec, frame: Frame, missed: tuple[int, int] | None) -> None:
        now = self.mind.clock.now()
        if self._storming(spec.name, now):
            return
        self._last_run[spec.name] = now
        run_id = f"{spec.name}:{self.mind.ids.new(now)}"

        async def job() -> None:
            sem = self._lanes.get(spec.lane) if spec.lane in EXCLUSIVE_LANES else None
            try:
                if sem is None:
                    await self._execute(spec, run_id, missed)
                else:
                    async with sem:
                        await self._execute(spec, run_id, missed)
            finally:
                self._running.pop(spec.name, None)
                self._wake.set()

        self._running[spec.name] = asyncio.create_task(job(), name=f"process:{spec.name}")

    async def _execute(self, spec: ProcessSpec, run_id: str, missed: tuple[int, int] | None) -> None:
        ctx = ProcessContext(self.mind, spec, run_id, self.mind.frame(), missed, self.llm, self.ports)
        deadline = spec.deadline_s if spec.deadline_s is not None else self.deadline_s
        try:
            async with asyncio.timeout(deadline):
                out = await acall(self.instances[spec.name].run, ctx, label=f"processus {spec.name}")
        except TimeoutError:
            out = Failed(TimeoutError(f"passage coupé après {deadline:.0f} s"))
        self.runs[spec.name] = self.runs.get(spec.name, 0) + 1
        now = self.mind.clock.now()
        if not isinstance(out, Failed):
            self.consecutive[spec.name] = 0
            self.not_before.pop(spec.name, None)
            if ctx.emitted:
                self._idle_at.pop(spec.name, None)
                self._idle_streak.pop(spec.name, None)
            else:
                self._idle_at[spec.name] = now
                self._idle_streak[spec.name] = self._idle_streak.get(spec.name, 0) + 1
            return
        self._failed(spec.name, now, out.error)
        k = self.consecutive[spec.name]
        self.not_before[spec.name] = now + min(BACKOFF_MAX_US, BACKOFF_BASE_US * 2 ** min(k - 1, 20))
        if k > 1:
            return  # une série d'échecs : journalisée une fois, la santé compte la suite
        draft = PROCESS_FAILED.draft(process=spec.name, error=repr(out.error)[:500])
        await acall(
            lambda: self.mind.append([draft], emitter="runtime", correlation=run_id, origin=Origin.KERNEL),
            label="journal d'échec de processus",
        )

    def _held_back(self, name: str, nd: int | None, now: int) -> int | None:
        """L'échéance retenue : jamais avant la fin d'un recul ; et un processus qui, après un passage qui n'a
        rien écrit, se redit dû sur-le-champ (une échéance déjà passée, ou « maintenant ») sans que rien de ce
        qui le réveille n'ait bougé attend ``IDLE_GUARD_US``, doublé à chaque fois. Un processus qui se donne
        une échéance à venir (un agenda, un relevé périodique qui n'a rien trouvé) ne tourne pas à vide : il
        est quitte."""
        idle = self._idle_at.get(name)
        if idle is not None and (nd is None or nd > now):
            self._idle_at.pop(name, None)  # il attend un instant à venir, ou un événement : il ne tourne pas
            self._idle_streak.pop(name, None)
        elif idle is not None and nd is not None:
            streak = self._idle_streak.get(name, 1)
            nd = max(nd, idle + min(IDLE_GUARD_MAX_US, IDLE_GUARD_US * 2 ** min(max(0, streak - 1), 20)))
        if nd is None:
            return None
        floor = self.not_before.get(name)
        if floor is not None and nd < floor:
            nd = floor
        return nd

    def _storming(self, name: str, now: int) -> bool:
        """Une rafale : plus de ``STORM_RUNS`` passages en ``STORM_WINDOW_US``. Le processus est retenu une
        fenêtre, puis deux, quatre… à chaque rafale (jusqu'à une heure), et la santé le montre — rien ne
        tourne en boucle, quoi qu'il fasse."""
        recent = self._recent.setdefault(name, deque(maxlen=STORM_RUNS))
        if len(recent) == STORM_RUNS and now - recent[0] < STORM_WINDOW_US:
            recent.clear()
            k = self.storms[name] = self.storms.get(name, 0) + 1
            hold = min(BACKOFF_MAX_US, STORM_WINDOW_US * 2 ** min(k - 1, 20))
            self.not_before[name] = max(self.not_before.get(name, 0), now + hold)
            self.last_error[name] = (now, f"rafale : plus de {STORM_RUNS} passages en une minute — retenu")
            self._wake.set()  # la boucle recalcule son réveil (la fin de la retenue)
            return True
        recent.append(now)
        return False

    def _failed(self, name: str, at: int, error: BaseException) -> None:
        self.failures[name] = self.failures.get(name, 0) + 1
        self.consecutive[name] = self.consecutive.get(name, 0) + 1
        self.last_error[name] = (at, repr(error)[:300])

    def last_run(self, name: str) -> int | None:
        return self._last_run.get(name)

    def running(self) -> list[str]:
        return sorted(self._running)

    async def drain(self) -> None:
        """Attend la fin des processus en cours (arrêt propre, tests)."""
        while self._running:
            await asyncio.gather(*list(self._running.values()), return_exceptions=True)

    async def cancel_all(self) -> None:
        for t in list(self._running.values()):
            t.cancel()
        await asyncio.gather(*list(self._running.values()), return_exceptions=True)
        self._running.clear()
