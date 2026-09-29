"""Le pipeline d'épisode, fixe.

``admission → baux → départ gardé → enrichissements ∥ → composition → appel
(boucle d'outils) → analyse → commit gardé → règlement``. Pendant tout
l'épisode, le Mind revérifie sa garde à chaque ajout d'autrui : si ce qu'il a
lu change (la personne a écrit entre-temps, un démenti d'identité est tombé…),
l'épisode est annulé et se règle en ``superseded`` — il n'est jamais livré en
retard. Les baux (la parole avec une personne, l'atelier d'un but) sont
rendus quoi qu'il arrive.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mika.contracts.runtime import EPISODE_ENDED, EPISODE_STARTED, UTTERANCE, ToolOutcome
from mika.kernel.arbitration import Row
from mika.kernel.builtin import LEASE, LEASE_ACQUIRED, LEASE_RELEASED
from mika.kernel.episode import EpisodePolicy, Outcome
from mika.kernel.events import Content, Origin, VoiceProvenance
from mika.kernel.facts import FactView
from mika.kernel.frame import CLOSED, Audience, EpisodeRef, Frame
from mika.kernel.guards import Guard, Superseded, combine, floor
from mika.kernel.prompt import Budget, Composer, SectionBody
from mika.kernel.state import FrozenDict
from mika.ports.llm import PREEMPTED, LLMGateway, LLMRequest, Message, PersonaRender
from mika.runtime.boundary import Failed, acall, call
from mika.runtime.tools import ToolContext, declare, run_tool_loop

if TYPE_CHECKING:
    from mika.runtime.mind import Mind

SILENCE = "[SILENCE]"

PersonaProvider = Callable[[Frame, str], PersonaRender]
AudienceResolver = Callable[[Frame, "EpisodeRequest"], Audience]
Parser = Callable[[str], tuple[str, Mapping[str, str]]]


@dataclass(frozen=True, slots=True)
class EpisodeRequest:
    kind: str
    target: str | None = None
    audience: Audience | None = None
    trigger: str = ""
    reply_to: int | None = None
    message: str = ""
    selected: Row | None = None
    reason: str = ""
    priority: int = 1
    extra_guard: Guard | None = None
    channel: str | None = None
    room: str | None = None
    #: L'état sur lequel la décision a été prise (une sélection de l'arbitre) :
    #: la garde se vérifie contre lui, pas contre l'état au démarrage — une
    #: initiative restée en file pendant que la personne écrivait est devancée.
    basis: Any = None


@dataclass(slots=True)
class EpisodeReport:
    id: str
    kind: str
    outcome: Outcome
    text: str | None = None
    detail: str = ""
    utterance_seq: int | None = None
    tools: list[tuple[str, bool]] = field(default_factory=list)
    trace: Any = None


class _Supersession:
    def __init__(self) -> None:
        self.failure: Superseded | None = None


class EpisodeRunner:
    def __init__(
        self,
        mind: Mind,
        gateway: LLMGateway | None,
        *,
        policies: Mapping[str, EpisodePolicy],
        persona: PersonaProvider | None = None,
        audience_of: AudienceResolver | None = None,
        parsers: Sequence[Parser] = (),
        composer: Composer | None = None,
        budget: Budget | None = None,
        lease_margin_s: float = 30.0,
        ports: Mapping[str, Any] | None = None,
    ) -> None:
        self.mind = mind
        self.ports = dict(ports or {})
        self.gateway = gateway
        self.policies = dict(policies)
        self.persona = persona
        self.audience_of = audience_of
        self.parsers = list(parsers)
        self.composer = composer or Composer()
        self.budget = budget or Budget(max_tokens=24_000)
        self.lease_margin_us = int(lease_margin_s * 1_000_000)
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    # ── préemption ──
    def holder_task(self, correlation: str) -> asyncio.Task[Any] | None:
        return self._tasks.get(correlation)

    async def run(self, req: EpisodeRequest) -> EpisodeReport:
        await self._preludes(req)
        policy = self.policies[req.kind]
        mind = self.mind
        now = mind.clock.now()
        eid = mind.ids.new(now)
        frame0 = mind.frame()
        self._tasks[eid] = asyncio.current_task()  # type: ignore[assignment]
        try:
            return await self._run(req, policy, eid, frame0)
        finally:
            self._tasks.pop(eid, None)

    async def _preludes(self, req: EpisodeRequest) -> None:
        """Ce qui précède un épisode (un murmure avant de parler), mené jusqu'au
        bout avant lui ; un prélude qui échoue n'empêche rien."""
        for spec in self.mind.registry.preludes:
            if req.kind not in spec.kinds:
                continue
            pre = call(spec.fn, self.mind.frame(), req, label=f"prélude {spec.owner}")
            if isinstance(pre, Failed) or pre is None or pre.kind not in self.policies or pre.kind == req.kind:
                continue
            await acall(lambda pre=pre: self.run(EpisodeRequest(
                kind=pre.kind, message=pre.message, reason=pre.reason, trigger=f"prélude:{req.trigger}",
                priority=req.priority)), label=f"prélude {pre.kind}")

    async def _run(self, req: EpisodeRequest, policy: EpisodePolicy, eid: str, frame0: Frame) -> EpisodeReport:
        mind = self.mind
        report = EpisodeReport(eid, req.kind, Outcome.DONE)

        # identification, au bord : toute panne → audience fermée
        audience = req.audience
        if audience is None and self.audience_of is not None:
            got = call(self.audience_of, frame0, req, label="résolution d'audience")
            audience = CLOSED if isinstance(got, Failed) else got
        audience = audience or CLOSED

        # ressources et garde
        resources = set(req.selected.resources) if req.selected else set()
        if policy.voice and policy.delivered and req.target:
            resources.add(floor(req.target))
        guard = combine(
            policy.guard(frame0, req.target, audience) if policy.guard else None,
            *(req.selected.guards if req.selected else ()),
            req.extra_guard,
            Guard("baux", leases=tuple(sorted(resources))) if resources else None,
        )
        held: list[str] = []
        superseded = _Supersession()
        me = asyncio.current_task()

        def on_supersede(failure: Superseded) -> None:
            superseded.failure = failure
            if me is not None and not me.done():
                me.cancel()

        try:
            async with asyncio.timeout(policy.deadline_s):
                held = await self._acquire(eid, sorted(resources), policy, req)
                start = await mind.append(
                    [EPISODE_STARTED.draft(kind=req.kind, target=req.target, trigger=req.trigger,
                                           reason=req.reason, reply_to=req.reply_to)],
                    emitter="runtime", correlation=eid, origin=Origin.KERNEL,
                    basis=req.basis if req.basis is not None else frame0.root, guard=guard, holder=eid,
                )
                mind.track(eid, guard, start.root, eid, on_supersede)
                attrs: dict[str, Any] = {"channel": req.channel or audience.channel, "reply_to": req.reply_to,
                                         "reason": req.reason, "room": req.room or audience.room}
                if req.selected is not None:
                    attrs["reasons"] = tuple(sorted({p[1] for p in req.selected.parts}))
                    attrs["args"] = req.selected.args
                episode = EpisodeRef(eid, req.kind, req.target, policy.muted_tags, FrozenDict(attrs))
                frame = Frame(start.root, mind.clock.now(), mind.registry, audience, episode)
                message = req.message
                if not message and policy.brief is not None:
                    got = call(policy.brief, frame, req, label=f"consigne {req.kind}")
                    message = "" if isinstance(got, Failed) else str(got or "")

                enrich = await self._enrich(frame, policy)
                blocks = self._sections(frame, enrich)
                prompt, trace = self.composer.compose(
                    blocks, kind=req.kind, audience_level=audience.level, witness_level=audience.witness_level,
                    muted_tags=policy.muted_tags,
                    message=message, budget=self.budget, thread_key=req.target or req.kind,
                )
                report.trace = trace
                if policy.role is None:
                    await self._end(eid, req, Outcome.DONE)
                    return report
                persona = self.persona(frame, policy.persona_depth) if (policy.voice and self.persona) else None
                tools = self._tools(policy, req.kind, audience)
                llm_req = LLMRequest(
                    role=policy.role, call_id=f"{eid}#0",
                    system_stable=(persona.text + "\n\n" + prompt.system_stable).strip() if persona else prompt.system_stable,
                    # l'état volatil voyage dans le dernier tour utilisateur (après les
                    # points de cache) : ne pas le répéter dans le système
                    system_volatile="",
                    messages=tuple(Message(m["role"], m["content"]) for m in prompt.chat_messages()),
                    tools=declare(list(tools.values())), max_tokens=policy.max_tokens, persona=persona,
                    lane=policy.lane, priority=req.priority,
                    meta={"episode": eid, "kind": req.kind, "target": req.target, "sections": trace.included,
                          "audience_level": audience.level},
                )

                def make_ctx(spec: Any, call_id: str) -> ToolContext:
                    return ToolContext(mind, spec, call_id, eid, Frame(mind.root, mind.clock.now(),
                                       mind.registry, audience, episode), guard=None, ports=self.ports)

                assert self.gateway is not None, "pas de passerelle LLM"
                gateway = self.gateway
                loop = await acall(
                    lambda: run_tool_loop(gateway, llm_req, tools, make_ctx, max_turns=policy.max_tool_turns),
                    label=f"appel du modèle ({policy.role})",
                )
                if isinstance(loop, Failed):
                    return await self._settle(eid, req, report, Outcome.FAILED, None,
                                              detail=_describe(loop.error))
                report.tools = loop.calls
                text, annotations = self._parse(loop.text)
                if not text.strip() or text.strip() == SILENCE:
                    await self._end(eid, req, Outcome.ABSTAINED)
                    report.outcome = Outcome.ABSTAINED
                    return report
                basis = mind.inflight(eid).basis if mind.inflight(eid) else start.root
                voice = VoiceProvenance(
                    call_id=llm_req.call_id, persona_hash=persona.hash if persona else "",
                    role=policy.role, model=(loop.last.model if loop.last else ""),
                )
                commit = await mind.append(
                    [UTTERANCE.draft(
                        kind=req.kind, text=Content.of(text, level=0), voice=voice, target=req.target,
                        channel=req.channel or audience.channel or None, room=req.room or audience.room,
                        reply_to=req.reply_to, visible=policy.visible,
                        annotations=tuple(sorted(annotations.items())),
                        tools=tuple(ToolOutcome(name=n, ok=ok) for n, ok in loop.calls),
                        sections=trace.included, provenance=trace.provenance,
                    )],
                    emitter="runtime", correlation=eid, origin=Origin.KERNEL, basis=basis,
                    guard=guard, holder=eid,
                )
                report.text = text
                report.utterance_seq = commit.seqs[-1]
                mind.untrack(eid)
                await self._end(eid, req, Outcome.DONE)
                return report
        except Superseded as failure:
            return await self._settle(eid, req, report, Outcome.SUPERSEDED, failure)
        except asyncio.CancelledError as exc:
            if PREEMPTED in exc.args:
                if me is not None:
                    me.uncancel()
                return await self._settle(eid, req, report, Outcome.PREEMPTED, None)
            if superseded.failure is not None:
                if me is not None:
                    me.uncancel()  # l'annulation venait de la supplantation : absorbée
                return await self._settle(eid, req, report, Outcome.SUPERSEDED, superseded.failure)
            await self._settle(eid, req, report, Outcome.CANCELLED, None)
            raise
        except TimeoutError:
            return await self._settle(eid, req, report, Outcome.TIMEOUT, None)
        except _Busy as busy:
            return await self._settle(eid, req, report, Outcome.SUPERSEDED,
                                      Superseded("baux", f"ressource occupée : {busy.resource}"))
        finally:
            mind.untrack(eid)
            await self._release(eid, held)

    # ── étapes ──
    async def _acquire(self, eid: str, resources: Sequence[str], policy: EpisodePolicy, req: EpisodeRequest) -> list[str]:
        held: list[str] = []
        until = self.mind.clock.now() + int(policy.deadline_s * 1_000_000) + self.lease_margin_us
        for res in resources:
            for _attempt in range(40):
                lease = self.mind.view().get(LEASE(res))
                if lease is not None and lease.holder != eid:
                    if policy.priority == 0:
                        # Premier plan : on supplante le détenteur (une initiative
                        # vers quelqu'un qui vient d'écrire), puis on attend qu'il rende.
                        inf = self.mind.inflight(lease.holder)
                        if inf is not None:
                            self.mind.untrack(lease.holder)
                            inf.on_supersede(Superseded("préemption", f"{res} demandé au premier plan"))
                        await asyncio.sleep(0.05)
                        continue
                    raise _Busy(res)
                predicate_res = res

                def free(view: FactView, res: str = predicate_res) -> bool:
                    current = view.get(LEASE(res))
                    return current is None or current.holder == eid

                try:
                    await self.mind.append(
                        [LEASE_ACQUIRED.draft(resource=res, holder=eid, until=until)],
                        emitter="kernel", correlation=eid, origin=Origin.KERNEL,
                        guard=Guard("libre", predicate=free), holder=eid,
                    )
                except Superseded:
                    await asyncio.sleep(0.05)
                    continue
                held.append(res)
                break
            else:
                raise _Busy(res)
        return held

    async def _release(self, eid: str, held: Sequence[str]) -> None:
        if not held:
            return
        drafts = [LEASE_RELEASED.draft(resource=r, holder=eid) for r in held]
        await acall(
            lambda: self.mind.append(drafts, emitter="kernel", correlation=eid, origin=Origin.KERNEL),
            label="rendre les baux",
        )

    async def _enrich(self, frame: Frame, policy: EpisodePolicy) -> dict[str, Any]:
        specs = [s for s in self.mind.registry.enrichers if policy.kind in s.episodes]
        if not specs:
            return {}

        async def one(spec: Any) -> tuple[str, Any]:
            try:
                async with asyncio.timeout(spec.deadline_ms / 1000):
                    out = await acall(spec.fn, frame.state(spec.owner), frame, self.ports,
                                      label=f"enrichisseur {spec.key}")
            except TimeoutError:
                return spec.key, None
            return spec.key, None if isinstance(out, Failed) else out

        results = await asyncio.gather(*(one(s) for s in specs))
        return {k: v for k, v in results if v is not None}

    def _sections(self, frame: Frame, enrich: Mapping[str, Any]) -> list[tuple[Any, SectionBody]]:
        out = []
        kind = frame.episode.kind if frame.episode else ""
        for spec in self.mind.registry.sections:
            if kind not in spec.episodes:
                continue
            body = call(spec.fn, frame.state(spec.owner), frame, enrich, label=f"section {spec.key}")
            if isinstance(body, Failed) or body is None:
                continue
            if isinstance(body, str):
                body = SectionBody(body)
            out.append((spec, body))
        return out

    def _tools(self, policy: EpisodePolicy, kind: str, audience: Audience) -> dict[str, Any]:
        out = {}
        for name, spec in self.mind.registry.tools.items():
            if kind not in spec.episodes or spec.bundle not in policy.tool_bundles:
                continue
            if spec.min_level is not None and audience.level < spec.min_level:
                continue
            out[name] = spec
        return out

    def _parse(self, text: str) -> tuple[str, dict[str, str]]:
        annotations: dict[str, str] = {}
        for parser in self.parsers:
            got = call(parser, text, label="analyse de réponse")
            if isinstance(got, Failed):
                continue
            text, extra = got
            annotations.update(extra)
        return text, annotations

    async def _end(self, eid: str, req: EpisodeRequest, outcome: Outcome, failure: Superseded | None = None,
                   detail: str = "") -> None:
        draft = EPISODE_ENDED.draft(
            kind=req.kind, outcome=outcome.value, target=req.target, reply_to=req.reply_to,
            detail=detail or (failure.reason if failure else ""),
            guard=failure.guard if failure else None, changed=failure.changed if failure else (),
        )
        await acall(
            lambda: self.mind.append([draft], emitter="runtime", correlation=eid, origin=Origin.KERNEL),
            label="régler l'épisode",
        )

    async def _settle(self, eid: str, req: EpisodeRequest, report: EpisodeReport, outcome: Outcome,
                      failure: Superseded | None, detail: str = "") -> EpisodeReport:
        self.mind.untrack(eid)
        await self._end(eid, req, outcome, failure, detail=detail)
        report.outcome = outcome
        report.detail = str(failure) if failure else detail
        return report


def _describe(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}"[:500]


class _Busy(Exception):
    def __init__(self, resource: str) -> None:
        self.resource = resource
        super().__init__(resource)
