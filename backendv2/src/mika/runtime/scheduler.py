"""Ordonnanceur à événements discrets.

Chaque processus déclare ``next_due(état, frame, dernière_exécution)`` : un
instant, ou ``None`` (en sommeil jusqu'à un événement de réveil). La boucle
attend la plus proche échéance — ou un réveil — puis lance les processus dus,
un seul à la fois par processus, dans la limite de capacité de leur voie.

Après un arrêt ou un saut d'horloge, une échéance très en retard donne **une**
exécution, avec ``missed=(échéance, maintenant)`` : pas de rafale. Un quantum
borne l'attente pour réévaluer les échéances qui dépendent du temps.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mika.contracts.runtime import PROCESS_FAILED
from mika.kernel.events import Draft, Event, Origin
from mika.kernel.faculty import CatchUp, ProcessSpec
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, combine
from mika.kernel.state import Root
from mika.runtime.boundary import Failed, acall, call

if TYPE_CHECKING:
    from mika.runtime.mind import Commit, Mind

ANY_EVENT = "*"


@dataclass(slots=True)
class ProcessContext:
    mind: Mind
    spec: ProcessSpec
    run_id: str
    frame: Frame
    missed: tuple[int, int] | None = None
    llm: Any = None
    ports: Mapping[str, Any] = field(default_factory=dict)

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


class Scheduler:
    def __init__(
        self,
        mind: Mind,
        *,
        extra: Iterable[ProcessSpec] = (),
        lanes: Mapping[str, int] | None = None,
        llm: Any = None,
        ports: Mapping[str, Any] | None = None,
    ) -> None:
        self.mind = mind
        self.specs: list[ProcessSpec] = sorted(
            list(mind.registry.processes.values()) + list(extra), key=lambda s: (s.priority, s.name)
        )
        self.llm = llm
        self.ports = dict(ports or {})
        #: une instance par processus et par ordonnanceur (jamais partagée entre noyaux)
        self.instances: dict[str, Any] = {
            s.name: s.process() if isinstance(s.process, type) else s.process for s in self.specs
        }
        self._lanes = {name: asyncio.Semaphore(n) for name, n in (lanes or {"background": 2, "night": 1}).items()}
        self._last_run: dict[str, int] = {}
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
        mind.subscribe(self._on_events)

    def _on_events(self, events: Sequence[Event[Any]], root: Root) -> None:
        if self._any or any(e.type.name in self._wake_types for e in events):
            self._wake.set()

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
                if missed and spec.catch_up is CatchUp.SKIP:
                    self._last_run[spec.name] = now
                    continue
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
        self._last_run[spec.name] = now
        run_id = f"{spec.name}:{self.mind.ids.new(now)}"

        async def job() -> None:
            sem = self._lanes.get(spec.lane)
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
        out = await acall(self.instances[spec.name].run, ctx, label=f"processus {spec.name}")
        self.runs[spec.name] = self.runs.get(spec.name, 0) + 1
        if not isinstance(out, Failed):
            self.consecutive[spec.name] = 0
        else:
            self._failed(spec.name, self.mind.clock.now(), out.error)
            draft = PROCESS_FAILED.draft(process=spec.name, error=repr(out.error)[:500])
            await acall(
                lambda: self.mind.append([draft], emitter="runtime", correlation=run_id, origin=Origin.KERNEL),
                label="journal d'échec de processus",
            )

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
