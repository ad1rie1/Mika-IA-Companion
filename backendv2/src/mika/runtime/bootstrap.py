"""Assemblage du noyau — la même racine pour le serveur et le simulateur.

``Kernel(deps)`` construit le registre (runtime + facultés), le Mind, le
lanceur d'épisodes et ses voies, l'arbitre, l'ordonnanceur, l'exécuteur de la
file de sortie et le moteur des projections. Il ne sait jamais s'il est
simulé : l'horloge, les identifiants, le magasin et la passerelle LLM lui sont
donnés.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from mika.contracts.runtime import EPISODE_ENDED, PERCEPTION_RECEIVED, PerceptionReceived
from mika.kernel.arbitration import Row
from mika.kernel.builtin import BOOT, PARAMS_CHANGED
from mika.kernel.clock import Clock
from mika.kernel.codec import canonical_json
from mika.kernel.episode import EpisodePolicy
from mika.kernel.events import Origin
from mika.kernel.faculty import Faculty
from mika.kernel.frame import Frame
from mika.kernel.ids import IdGen
from mika.kernel.prompt import Budget
from mika.kernel.registry import ArbitrationPolicy, Registry
from mika.ports.llm import LLMGateway
from mika.ports.store import EventStore
from mika.runtime.arbiter import Arbiter, arbiter_spec
from mika.runtime.effects import EffectExecutor, with_content
from mika.runtime.lanes import Lanes
from mika.runtime.mind import BootReport, Commit, Mind
from mika.runtime.pipeline import (
    AudienceResolver,
    EpisodeReport,
    EpisodeRequest,
    EpisodeRunner,
    Parser,
    PersonaProvider,
)
from mika.runtime.projections import ProjectionWorker, ensure_t0
from mika.runtime.scheduler import Scheduler
from mika.runtime.state import MAX_REPLY_ATTEMPTS, RUNTIME


@dataclass(slots=True)
class KernelDeps:
    faculties: Sequence[Faculty[Any, Any]]
    store: EventStore
    clock: Clock
    ids: IdGen
    gateway: LLMGateway | None = None
    policies: Mapping[str, EpisodePolicy] = field(default_factory=dict)
    arbitration: ArbitrationPolicy | None = None
    persona: PersonaProvider | None = None
    audience_of: AudienceResolver | None = None
    parsers: Sequence[Parser] = ()
    budget: Budget | None = None
    lanes: Mapping[str, int] | None = None
    process_lanes: Mapping[str, int] | None = None
    ports: Mapping[str, Any] = field(default_factory=dict)
    code: str = ""
    seed: int | str = 0
    snapshot_every: int = 500
    reply_kind: str = "REPLY"
    arbiter_quantum_s: float = 600.0
    max_pending: int = 100


class ReadOnlyStore:
    """Ce que les facultés peuvent lire du magasin (enrichisseurs, effets) :
    des requêtes SQL en lecture, jamais une écriture."""

    __slots__ = ("_store",)

    def __init__(self, store: EventStore) -> None:
        self._store = store

    def query_mind(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        return self._store.query_mind(sql, params)

    def query_views(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        return self._store.query_views(sql, params)

    def content(self, refs: Sequence[str]) -> dict[str, str]:
        return self._store.content(list(refs))


@dataclass(frozen=True, slots=True)
class Perceived:
    commit: Commit | None
    reply: asyncio.Future[EpisodeReport] | None
    overloaded: bool = False

    @property
    def seq(self) -> int | None:
        return self.commit.seqs[-1] if self.commit is not None else None


class Kernel:
    def __init__(self, deps: KernelDeps) -> None:
        self.deps = deps
        registry = Registry([RUNTIME, *deps.faculties], arbitration=deps.arbitration)
        self.mind = Mind(registry, deps.store, deps.clock, deps.ids, code=deps.code,
                         snapshot_every=deps.snapshot_every)
        ports = {"store": ReadOnlyStore(deps.store), "frame": self._head_frame, **dict(deps.ports)}
        self.ports = ports
        self.runner = EpisodeRunner(
            self.mind, deps.gateway, policies=deps.policies, persona=deps.persona,
            audience_of=deps.audience_of, parsers=deps.parsers, budget=deps.budget, ports=ports,
        )
        self.lanes = Lanes(self.runner, capacities=deps.lanes, max_pending=deps.max_pending)
        self.arbiter = Arbiter(lambda: self.mind.registry, self._submit_selected, seed=deps.seed)
        self.mind.subscribe(self.arbiter.invalidate)
        self.scheduler = Scheduler(
            self.mind, extra=[arbiter_spec(self.arbiter, quantum_s=deps.arbiter_quantum_s)],
            lanes=deps.process_lanes, llm=deps.gateway, ports=ports,
        )
        self.effects = EffectExecutor(self.mind, ports)
        self.projections = ProjectionWorker(self.mind)
        self._tasks: list[asyncio.Task[None]] = []
        self.started = False

    @property
    def registry(self) -> Registry:
        return self.mind.registry

    def _head_frame(self) -> Frame:
        """Une vue en lecture sur la tête (effets, enrichisseurs)."""
        return self.mind.frame()

    # ── cycle de vie ──
    async def start(self) -> BootReport:
        report = await self.mind.boot(append_boot=False)
        await ensure_t0(self.mind)
        failures = self.registry.check_invariants(self.mind.root)
        if failures:
            raise RuntimeError("invariants de composition violés :\n" + "\n".join(failures))
        await self.mind.append([BOOT.draft(code=self.deps.code)], emitter="kernel", origin=Origin.KERNEL,
                               correlation="boot")
        self.lanes.start()
        await self.recover()
        self._tasks = [
            asyncio.create_task(self.scheduler.run(), name="ordonnanceur"),
            asyncio.create_task(self.effects.run(), name="file-de-sortie"),
            asyncio.create_task(self.projections.run(), name="projections"),
        ]
        self.started = True
        return report

    async def stop(self) -> None:
        self.scheduler.stop()
        self.effects.stop()
        self.projections.stop()
        await self.scheduler.cancel_all()
        await self.lanes.stop()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await self.mind.close()
        self.started = False

    async def abort(self) -> None:
        """Arrêt brutal (simulation d'un ``kill -9`` : rien n'est écrit)."""
        for t in self._tasks:
            t.cancel()
        await self.scheduler.cancel_all()
        await self.lanes.stop()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await self.mind.close()
        self.started = False

    # ── entrées ──
    async def perceive(self, data: PerceptionReceived, *, dedupe_key: str | None = None,
                       correlation: str | None = None) -> Perceived:
        """Une perception : journalisée, puis une réponse demandée. File pleine →
        refusée avant d'être journalisée (sinon la reprise au démarrage
        répondrait des heures plus tard à un message qu'on a dit refusé)."""
        if self.deps.reply_kind in self.runner.policies and self.lanes.full(self.deps.reply_kind):
            return Perceived(None, None, overloaded=True)
        commit = await self.mind.append(
            [PERCEPTION_RECEIVED.draft(data, dedupe_key=dedupe_key)], emitter="runtime", origin=Origin.EXTERNAL,
            correlation=correlation or f"perception:{self.mind.ids.new(self.mind.clock.now())}",
        )
        if commit.deduped or self.deps.reply_kind not in self.runner.policies:
            return Perceived(commit, None)
        seq = commit.seqs[-1]
        fut = self.lanes.submit(EpisodeRequest(
            kind=self.deps.reply_kind, target=data.handle, trigger=f"perception:{seq}", reply_to=seq,
            message=data.text.text or "", priority=0, channel=data.channel, room=data.room,
        ))
        return Perceived(commit, fut, overloaded=fut is None)

    async def set_params(self, owner: str, params: BaseModel) -> bool:
        """Journalise de nouveaux paramètres s'ils diffèrent de ceux en vigueur."""
        data = canonical_json(params)
        current = self.mind.root.slices["kernel"].params.get(owner)
        if current is not None and current.data == data:
            return False
        await self.mind.append([PARAMS_CHANGED.draft(owner=owner, data=data)], emitter="kernel",
                               origin=Origin.KERNEL, correlation="params")
        return True

    # ── reprise après arrêt ──
    async def recover(self) -> dict[str, int]:
        rs = self.mind.root.slices["runtime"]
        interrupted = 0
        for eid, ep in rs.open.items():
            await self.mind.append(
                [EPISODE_ENDED.draft(kind=ep.kind, outcome="interrupted", target=ep.target, reply_to=ep.reply_to)],
                emitter="runtime", correlation=eid, origin=Origin.KERNEL,
            )
            interrupted += 1
        rs = self.mind.root.slices["runtime"]
        resumed = abandoned = 0
        for seq, pending in rs.pending.items():
            if pending.attempts >= MAX_REPLY_ATTEMPTS:
                await self.mind.append(
                    [EPISODE_ENDED.draft(kind=self.deps.reply_kind, outcome="failed", target=pending.handle,
                                         reply_to=seq, detail="abandonnée après deux tentatives")],
                    emitter="runtime", correlation=f"abandon:{seq}", origin=Origin.KERNEL,
                )
                abandoned += 1
                continue
            if self.deps.reply_kind not in self.runner.policies:
                continue
            ev = with_content(self.mind, self.mind.decode(self.mind.store.get_events([seq])[0]))
            self.lanes.submit(EpisodeRequest(
                kind=self.deps.reply_kind, target=ev.data.handle, trigger=f"reprise:{seq}", reply_to=seq,
                message=ev.data.text.text or "", priority=0, channel=ev.data.channel, room=ev.data.room,
            ))
            resumed += 1
        return {"interrupted": interrupted, "resumed": resumed, "abandoned": abandoned}

    async def _submit_selected(self, row: Row, frame: Frame) -> None:
        policy = self.runner.policies.get(row.kind)
        if policy is None or policy.role is None:
            return  # DECISION : l'événement kernel.selected est l'action
        target = None if row.target in ("none", "any") else row.target
        self.lanes.submit(EpisodeRequest(
            kind=row.kind, target=target, selected=row, reason=",".join(p[1] for p in row.parts),
            trigger=f"selected:{frame.seq}", priority=policy.priority,
        ))
