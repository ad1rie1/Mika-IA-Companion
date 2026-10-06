"""Le pipeline d'épisode, fixe.

``admission → baux → départ gardé → enrichissements ∥ → composition → appel
(boucle d'outils) → analyse → prélude → commit gardé → règlement``. Chaque
épisode composé laisse une trace (``runtime/traces.py``) : ce qui a été envoyé
au modèle, la composition, les outils et leurs résultats. Pendant tout
l'épisode, le Mind revérifie sa garde à chaque ajout d'autrui : si ce qu'il a
lu change (la personne a écrit entre-temps, un démenti d'identité est tombé…),
l'épisode est annulé et se règle en ``superseded`` — il n'est jamais livré en
retard. Les baux (la parole avec une personne, l'atelier d'un but) sont
rendus quoi qu'il arrive.

**Le tour de conversation.** Une réponse porte sur le tour de la personne
(ses messages encore sans réponse, au même endroit) et répond au dernier :
sa garde exige que ``reply_to`` soit toujours le dernier message du tour, si
bien qu'un nouveau message la supplante — elle sera recomposée en le lisant —
et son énoncé règle le tour entier (``answers``). Une rafale de trois messages
reçoit une seule réponse, qui les a tous lus ; une réponse ne part jamais en
retard sur une question dépassée.

**Toujours réglé, jamais un artefact.** Un épisode se règle une fois et une
seule (``episode.ended``), quoi qu'il arrive — une exception imprévue le règle
en ``failed``. Il ne livre jamais un marqueur de la boucle d'outils, ni un
silence déguisé (``[silence]``, ``**[SILENCE]**``, ``(silence)``…).

**Préemption.** Une réponse ne passe jamais derrière une initiative ou un
pas : la voie qui la reçoit annule l'épisode moins prioritaire en cours
(``preempted`` — l'arbitre le reproposera), tant qu'il n'écrit pas encore.

**Le prélude** (un murmure avant une initiative) passe *après* le départ
gardé de l'épisode principal et une fois sa réponse prête, sous la même
garde : si l'initiative est devancée avant de parler, le murmure ne part pas.
"""

from __future__ import annotations

import asyncio
import difflib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mika.contracts import runtime as rt
from mika.contracts.runtime import EPISODE_ENDED, EPISODE_STARTED, UTTERANCE, ToolOutcome
from mika.kernel.arbitration import Row
from mika.kernel.builtin import LEASE, LEASE_ACQUIRED, LEASE_RELEASED
from mika.kernel.codec import canonical_json, to_plain
from mika.kernel.episode import EpisodePolicy, Outcome, Prelude
from mika.kernel.events import Content, Origin, VoiceProvenance
from mika.kernel.facts import FactView
from mika.kernel.frame import CLOSED, Audience, EpisodeRef, Frame
from mika.kernel.guards import Guard, Superseded, combine, floor
from mika.kernel.prompt import CONTEXT_FOOTER, Budget, Composer, ComposeTrace, SectionBody
from mika.kernel.state import FrozenDict
from mika.ports.llm import PREEMPTED, LLMGateway, LLMRequest, Message, PersonaRender, ToolDecl
from mika.runtime.boundary import Failed, acall, call
from mika.runtime.state import RUNTIME, turn_upto, unanswered_at_end
from mika.runtime.tools import (
    LoopResult,
    ToolContext,
    acting,
    catalogue,
    declare,
    defers_tools,
    offer,
    run_tool_loop,
)
from mika.runtime.traces import STABLE_KEY, EpisodeTraces

if TYPE_CHECKING:
    from mika.runtime.mind import Mind

SILENCE = "[SILENCE]"
#: la balise de silence, où qu'elle soit (crochets, casse et espaces indifférents) : sans ambiguïté
_SILENCE_TAG = re.compile(r"\[\s*silence\s*\]", re.IGNORECASE)
#: ce qui habille un mot seul : emphase markdown, guillemets, ponctuation finale
_DRESSING = "*_`~«»\"“”„‟'’ \t\r\n"
_BARE_SILENCE = re.compile(r"[(\[]?\s*silence\s*[)\]]?", re.IGNORECASE)
#: les issues d'une boucle d'outils qui n'a pas pu finir (plafond de tours, appel coupé)
_UNFINISHED = frozenset({"max_turns", "truncated"})

PersonaProvider = Callable[[Frame, str], PersonaRender]
AudienceResolver = Callable[[Frame, "EpisodeRequest"], Audience]
#: ``(texte, son nom)`` → (texte livrable, annotations) ; son nom vient de la persona rendue (vide : inconnu)
Parser = Callable[[str, str], tuple[str, Mapping[str, str]]]


def is_silence(text: str) -> bool:
    """Elle a choisi de se taire : la balise ``[SILENCE]`` sous toutes ses formes réelles (``[silence]``,
    ``[SILENCE].``, ``**[SILENCE]**``, « [SILENCE] », ``[SILENCE] (un commentaire)``, une phrase suivie de
    ``[SILENCE]``), ou le seul mot *silence*, nu ou entre parenthèses (``SILENCE``, ``(silence)``). Jamais
    un vrai message qui contient le mot (« le silence de la nuit me plaît »)."""
    if _SILENCE_TAG.search(text):
        return True
    bare = text.strip(_DRESSING).rstrip(".!?…:;,").strip(_DRESSING)
    return bool(_BARE_SILENCE.fullmatch(bare))


#: les balises (``[EMOTION:happy:0.5]``, que le fil montré au modèle garde ; ``[SIGH]``, ``[PAUSE:500]``) et la
#: ponctuation ne font pas une autre phrase
_VOICE_TOKEN = re.compile(r"\[[^\[\]\n]{1,40}\]")
_NOT_WORDS = re.compile(r"[^\w]+")
#: en deçà (en caractères), un petit mot (« d'accord ») : il se redit
REPEAT_MIN_CHARS = 30
#: une réponse à quelques mots seulement (« re », « hey ») …
SHORT_WORDS = 2
#: … qui ressemble à ce point à son dernier message en est une redite
NEAR_RATIO = 0.85


def _plain(text: str) -> str:
    return " ".join(_NOT_WORDS.sub(" ", _VOICE_TOKEN.sub(" ", text).lower()).split())


def repeats_last(text: str, req: LLMRequest) -> bool:
    """Elle allait redire, mot pour mot, son dernier message du fil qu'on lui a montré (sonde réelle du
    2026-10-03 : à « re », la même phrase que son initiative d'une minute plus tôt, à l'identique). Une personne ne
    se répète pas ainsi : mieux vaut se taire."""
    last = next((m.content for m in reversed(req.messages) if m.role == "assistant" and m.content.strip()), "")
    mine, before = _plain(text), _plain(last)
    if min(len(mine), len(before)) < REPEAT_MIN_CHARS:
        return False  # « d'accord », « haha ok » : un petit mot se redit sans qu'on se répète
    if mine == before:
        return True  # à l'identique (à la ponctuation et aux balises près)
    # presque la même phrase, quand la personne n'a dit que deux mots (« re », « hey ») : la sonde du 2026-10-03,
    # « joyeux anniversaire pour tes 30 ans… » à son initiative, puis « joyeux anniv' pour tes 30 ans… » à « hey ».
    # Ailleurs, une variante (« numéro 3 », « numéro 4 ») n'est pas une redite : « CE QUE TU TE RÉPÈTES » s'en charge
    heard = _plain(_current_message(req))
    return 0 < len(heard.split()) <= SHORT_WORDS and difflib.SequenceMatcher(None, mine, before).ratio() >= NEAR_RATIO


def _current_message(req: LLMRequest) -> str:
    """Ce que la personne vient d'écrire : la fin du dernier tour (après l'état interne, s'il y est)."""
    last = req.messages[-1].content if req.messages and req.messages[-1].role == "user" else ""
    return last.rsplit(CONTEXT_FOOTER, 1)[-1]


@dataclass(frozen=True, slots=True)
class EpisodeRequest:
    kind: str
    target: str | None = None
    audience: Audience | None = None
    trigger: str = ""
    reply_to: int | None = None
    message: str = ""
    #: combien de caractères, au début de ``message``, la personne a tapés (la suite vient de ses pièces
    #: jointes) : le composeur coupe la suite d'abord ; ``None`` : rien à séparer
    typed_chars: int | None = None
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
    #: ce sur quoi porte l'épisode quand ce n'est pas sa cible (``goal:12``)
    subject: str | None = None
    #: le ``seq`` de l'événement ``kernel.selected`` qui l'a choisi (journalisé dans ``episode.started``)
    selected_seq: int | None = None
    #: les personnes que son énoncé peut nommer sans les viser (``Utterance.about``) : la cible de
    #: l'épisode qu'un prélude précède
    about: tuple[str, ...] = ()


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


@dataclass(slots=True)
class _Live:
    """Un épisode en cours : ce qu'il tient, ce qu'il a vu, où il en est."""

    id: str
    req: EpisodeRequest
    policy: EpisodePolicy
    frame0: Frame
    report: EpisodeReport
    task: asyncio.Task[Any] | None
    parent: str | None = None
    held: list[str] = field(default_factory=list)
    #: la trace de l'épisode, remplie au fil des phases (vide tant qu'il n'est pas composé)
    seen: dict[str, Any] = field(default_factory=dict)
    loop: LoopResult = field(default_factory=lambda: LoopResult(text=""))
    settled: bool = False
    superseded: Superseded | None = None
    #: une annulation déjà demandée (``superseded`` ou ``preempted``) : jamais deux
    cancel: str | None = None
    #: il attend le modèle (ou ses outils) : une préemption l'interrompt sur-le-champ ; ailleurs elle est
    #: notée et prise au prochain passage (jamais une annulation au milieu d'un règlement)
    preemptible: bool = False
    #: il écrit son énoncé : plus rien ne l'interrompt
    committing: bool = False


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
        traces: EpisodeTraces | None = None,
    ) -> None:
        self.mind = mind
        self.ports = dict(ports or {})
        self.traces = traces
        self.gateway = gateway
        self.policies = dict(policies)
        self.persona = persona
        self.audience_of = audience_of
        self.parsers = list(parsers)
        self.composer = composer or Composer()
        self.budget = budget or Budget(max_tokens=24_000)
        self.lease_margin_us = int(lease_margin_s * 1_000_000)
        self._live: dict[str, _Live] = {}

    # ── préemption ──
    def holder_task(self, correlation: str) -> asyncio.Task[Any] | None:
        live = self._live.get(correlation)
        return live.task if live is not None else None

    def preempt(self, lane: str) -> bool:
        """Interrompt (``preempted``) l'épisode le moins prioritaire en cours dans ``lane`` — jamais une
        réponse, jamais un épisode qui écrit déjà son énoncé, jamais un prélude (son épisode principal porte
        la décision). S'il attend le modèle, tout de suite ; sinon dès qu'il y arrive (avant tout appel).
        Rend ``True`` si un épisode a été désigné ; l'arbitre le reproposera."""
        candidates = [
            ep for ep in self._live.values()
            if ep.policy.lane == lane and ep.req.priority > 0 and ep.cancel is None and not ep.committing
            and not ep.settled and ep.parent is None and ep.task is not None and not ep.task.done()
        ]
        if not candidates:
            return False
        victim = max(candidates, key=lambda ep: (ep.req.priority, ep.id))
        victim.cancel = "preempted"
        if victim.preemptible:
            assert victim.task is not None
            victim.task.cancel(PREEMPTED)
        return True

    async def run(self, req: EpisodeRequest, *, parent: str | None = None) -> EpisodeReport:
        policy = self.policies[req.kind]
        mind = self.mind
        eid = mind.ids.new(mind.clock.now())
        ep = _Live(eid, req, policy, mind.frame(), EpisodeReport(eid, req.kind, Outcome.DONE),
                   asyncio.current_task(), parent=parent)
        self._live[eid] = ep
        try:
            got = await acall(self._run, ep, label=f"épisode {req.kind}")
            if isinstance(got, Failed):
                # une exception imprévue : l'épisode est réglé quand même (jamais laissé ouvert)
                await self._settle(ep, Outcome.FAILED, detail=_describe(got.error))
        finally:
            self._live.pop(eid, None)
            mind.untrack(eid)
            if ep.seen:
                self._record(ep, settled=True)
            await self._release(eid, ep.held)
        return ep.report

    async def _run(self, ep: _Live) -> None:
        mind, req, policy = self.mind, ep.req, ep.policy
        eid, report, frame0 = ep.id, ep.report, ep.frame0

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
            _turn_guard(req),
            Guard("baux", leases=tuple(sorted(resources))) if resources else None,
        )
        me = ep.task

        def on_supersede(failure: Superseded) -> None:
            ep.superseded = failure
            if ep.cancel is None and me is not None and not me.done():
                ep.cancel = "superseded"
                me.cancel()

        try:
            async with asyncio.timeout(policy.deadline_s):
                await self._acquire(ep, sorted(resources))
                start = await mind.append(
                    [EPISODE_STARTED.draft(kind=req.kind, target=req.target, trigger=req.trigger,
                                           reason=req.reason, reply_to=req.reply_to, subject=req.subject,
                                           selected=req.selected_seq)],
                    emitter="runtime", correlation=eid, origin=Origin.KERNEL,
                    basis=req.basis if req.basis is not None else frame0.root, guard=guard, holder=eid,
                )
                mind.track(eid, guard, start.root, eid, on_supersede)
                scope = _scope(start.root, req, eid)
                attrs: dict[str, Any] = {"channel": req.channel or audience.channel, "reply_to": req.reply_to,
                                         "reason": req.reason, "room": req.room or audience.room,
                                         "subject": req.subject}
                if req.selected is not None:
                    attrs["reasons"] = tuple(sorted({p[1] for p in req.selected.parts}))
                    attrs["args"] = req.selected.args
                episode = EpisodeRef(eid, req.kind, req.target, policy.muted_tags, FrozenDict(attrs))
                frame = Frame(start.root, mind.clock.now(), mind.registry, audience, episode)
                message = req.message
                if not message and policy.brief is not None:
                    got = call(policy.brief, frame, req, label=f"consigne {req.kind}")
                    message = "" if isinstance(got, Failed) else str(got or "")

                preludes = self._prelude_requests(ep, frame0)
                if any(pre.instead for pre in preludes):
                    # elle y pense, puis se ravise : la pensée part seule (sous la garde de l'épisode), l'épisode
                    # n'est pas composé ; ce que la pensée change (« elle s'est ravisée ») ne le supplante pas
                    mind.untrack(eid)
                    await self._preludes(ep, guard, [pre for pre in preludes if pre.instead])
                    await self._settle(ep, Outcome.ABSTAINED, detail="elle s'est ravisée")
                    return

                enrich = await self._enrich(frame, policy)
                blocks = self._sections(frame, enrich)
                # ce qui part au modèle hors du composeur (persona, catalogue, outils) : le budget le réserve
                persona = self.persona(frame, policy.persona_depth) if (
                    policy.role is not None and policy.voice and self.persona) else None
                tools = self._tools(policy, req.kind, audience,
                                    req.selected.args.get("bundles") if req.selected is not None else None)
                offered = list(tools.values())
                core = _in_hand(policy, req)
                if core is not None and policy.role is not None and not _defers(self.gateway, policy.role):
                    # un fournisseur sans recherche d'outils reçoit tout : le prompt ne parle pas d'outils à chercher
                    core = None
                # une parole que quelqu'un lira : ses outils sont ses mains (faire, pas annoncer ni inventer)
                more = "\n\n".join(filter(None, (acting(offered) if policy.visible else "",
                                                 catalogue(offered, core, mind.registry.bundles))))
                declared = declare(offered, core)
                prompt, trace = self.composer.compose(
                    blocks, kind=req.kind, audience_level=audience.level, witness_level=audience.witness_level,
                    tied_level=audience.tied_level, muted_tags=policy.muted_tags, message=message, budget=self.budget,
                    reserved=_reserved(persona, more, declared) if policy.role is not None else 0,
                    typed_chars=req.typed_chars if message == req.message else None,
                )
                report.trace = trace
                ep.seen.update(_composition(req, audience, policy.role, message, trace, enrich),
                               at=mind.clock.now())
                if policy.role is None:
                    await self._settle(ep, Outcome.DONE)
                    return
                stable = (persona.text + "\n\n" + prompt.system_stable).strip() if persona else prompt.system_stable
                llm_req = LLMRequest(
                    role=policy.role, call_id=f"{eid}#0",
                    system_stable=f"{stable}\n\n{more}".strip() if more else stable,
                    # l'état volatil voyage dans le dernier tour utilisateur (après les
                    # points de cache) : ne pas le répéter dans le système
                    system_volatile="",
                    messages=tuple(Message(m["role"], m["content"]) for m in prompt.chat_messages()),
                    tools=declared, max_tokens=policy.max_tokens, persona=persona,
                    lane=policy.lane, priority=req.priority,
                    meta={"episode": eid, "kind": req.kind, "target": req.target, "sections": trace.included,
                          "audience_level": audience.level},
                )

                ep.seen.update(_request(llm_req))
                self._record(ep, settled=False)

                def make_ctx(spec: Any, call_id: str) -> ToolContext:
                    return ToolContext(mind, spec, call_id, eid, Frame(mind.root, mind.clock.now(),
                                       mind.registry, audience, episode), guard=None, ports=self.ports,
                                       dedupe_scope=scope)

                assert self.gateway is not None, "pas de passerelle LLM"
                gateway = self.gateway
                self._check_preempted(ep)  # désigné avant d'arriver au modèle : il ne l'appelle pas
                ep.preemptible = True
                loop = await acall(
                    lambda: run_tool_loop(gateway, llm_req, tools, make_ctx, max_turns=policy.max_tool_turns,
                                          clock=mind.clock.now, result=ep.loop),
                    label=f"appel du modèle ({policy.role})",
                )
                ep.preemptible = False
                if isinstance(loop, Failed):
                    await self._settle(ep, Outcome.FAILED, detail=_describe(loop.error))
                    return
                report.tools = loop.calls
                text, annotations = self._parse(loop.text, persona.name if persona is not None else "")
                if not text.strip() or is_silence(text):
                    if loop.stop in _UNFINISHED and not loop.text.strip():
                        # elle n'a pas pu finir (trop d'appels d'outils) : ce n'est pas un silence choisi
                        await self._settle(ep, Outcome.FAILED, detail=f"pas de réponse au bout des outils "
                                                                      f"({loop.stop})")
                    else:
                        await self._settle(ep, Outcome.ABSTAINED)
                    return
                # un message qui emporte un fichier n'est pas une redite, même s'il redit sa phrase (« tiens, la
                # voilà ») : se taire perdrait le fichier
                if policy.delivered and not loop.attachments and repeats_last(text, llm_req):
                    await self._settle(ep, Outcome.ABSTAINED, detail="elle allait redire son dernier message")
                    return
                # le prélude (un murmure) : après le départ gardé, la réponse prête, sous la même garde
                await self._preludes(ep, guard, preludes)
                if ep.superseded is not None:
                    raise ep.superseded
                self._check_preempted(ep)
                ep.committing = True  # point de non-retour : l'énoncé s'écrit
                answers = (turn_upto(mind.root.slices[RUNTIME.name], req.reply_to)
                           if req.reply_to is not None else ())
                inflight = mind.inflight(eid)
                basis = inflight.basis if inflight is not None else start.root
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
                        sections=trace.included, provenance=trace.provenance, answers=answers,
                        attachments=tuple(loop.attachments), about=req.about,
                    )],
                    emitter="runtime", correlation=eid, origin=Origin.KERNEL, basis=basis,
                    guard=guard, holder=eid,
                )
                report.text = text
                report.utterance_seq = commit.seqs[-1]
                mind.untrack(eid)
                await self._settle(ep, Outcome.DONE)
        except Superseded as failure:
            await self._settle(ep, Outcome.SUPERSEDED, failure)
        except asyncio.CancelledError as exc:
            ep.preemptible = False
            if ep.superseded is not None:
                if me is not None:
                    me.uncancel()  # l'annulation venait de la supplantation : absorbée
                await self._settle(ep, Outcome.SUPERSEDED, ep.superseded)
                return
            if PREEMPTED in exc.args:
                if me is not None:
                    me.uncancel()
                await self._settle(ep, Outcome.PREEMPTED)
                return
            await self._settle(ep, Outcome.CANCELLED)
            raise
        except _Preempted:
            await self._settle(ep, Outcome.PREEMPTED)
        except TimeoutError:
            await self._settle(ep, Outcome.TIMEOUT)
        except _Busy as busy:
            await self._settle(ep, Outcome.SUPERSEDED, Superseded("baux", f"ressource occupée : {busy.resource}"))

    @staticmethod
    def _check_preempted(ep: _Live) -> None:
        """Une préemption désignée hors d'un appel de modèle est prise ici, avant tout appel."""
        if ep.cancel == "preempted":
            raise _Preempted

    def _record(self, ep: _Live, *, settled: bool) -> None:
        """La trace de l'épisode : à la composition (ce qui part au modèle, gardé
        même si l'appel ne revient jamais), puis au règlement (outils, appels,
        issue). Une trace ne retient jamais un épisode : l'écriture part en tâche."""
        if self.traces is None:
            return
        data = dict(ep.seen)
        at = int(data.pop("at", self.mind.clock.now()))
        data.update(_results(ep.loop))
        report = ep.report
        if settled:
            data.update(outcome=report.outcome.value, detail=report.detail, utterance_seq=report.utterance_seq)
        else:
            data.update(outcome="running")
        call(self.traces.record, ep.id, at, ep.req.kind, ep.req.target, data, label="trace d'épisode")

    # ── étapes ──
    async def _acquire(self, ep: _Live, resources: Sequence[str]) -> None:
        """Prend les baux un à un ; chacun est noté dès qu'il est pris (``ep.held``) : une panne en route
        les rend tous, jamais un bail oublié."""
        eid = ep.id
        until = self.mind.clock.now() + int(ep.policy.deadline_s * 1_000_000) + self.lease_margin_us
        for res in resources:
            for _attempt in range(40):
                lease = self.mind.view().get(LEASE(res))
                if lease is not None and lease.holder != eid:
                    if ep.policy.priority == 0:
                        # Premier plan : on supplante un détenteur moins prioritaire (une initiative
                        # vers quelqu'un qui vient d'écrire), puis on attend qu'il rende.
                        holder = self._live.get(lease.holder)
                        inf = self.mind.inflight(lease.holder)
                        if inf is not None and (holder is None or holder.req.priority > 0):
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
                ep.held.append(res)
                break
            else:
                raise _Busy(res)

    async def _release(self, eid: str, held: Sequence[str]) -> None:
        if not held:
            return
        drafts = [LEASE_RELEASED.draft(resource=r, holder=eid) for r in held]
        await acall(
            lambda: self.mind.append(drafts, emitter="kernel", correlation=eid, origin=Origin.KERNEL),
            label="rendre les baux",
        )

    def _prelude_requests(self, ep: _Live, frame: Frame) -> list[Prelude]:
        """Les préludes de cet épisode, décidés une fois — sur l'état où l'épisode a été admis (``frame``) —
        et lus au départ gardé : leur sort ne dépend pas de l'instant où ils passent."""
        req, out = ep.req, []
        for spec in self.mind.registry.preludes:
            if req.kind not in spec.kinds:
                continue
            pre = call(spec.fn, frame, req, label=f"prélude {spec.owner}")
            if isinstance(pre, Failed) or pre is None or pre.kind not in self.policies or pre.kind == req.kind:
                continue
            out.append(pre)
        return out

    async def _preludes(self, ep: _Live, guard: Guard, preludes: Sequence[Prelude]) -> None:
        """Ce qui précède l'énoncé d'un épisode (un murmure avant de parler) : un épisode à part entière,
        mené jusqu'au bout avant l'énoncé, sous la garde de l'épisode principal (s'il est devancé, le
        prélude l'est aussi et ne part pas). Un prélude qui échoue n'empêche rien."""
        req = ep.req
        for pre in preludes:
            sub = EpisodeRequest(kind=pre.kind, message=pre.message, reason=pre.reason,
                                 trigger=f"prélude:{req.trigger}", priority=req.priority,
                                 extra_guard=_follows(ep, guard),
                                 about=(req.target,) if req.target else ())
            task = asyncio.ensure_future(self.run(sub, parent=ep.id))
            try:
                await task
            except asyncio.CancelledError:
                if not task.done():
                    task.cancel()
                raise
            # une supplantation demandée pendant le prélude a pu être absorbée par lui (il se règle) : elle
            # vaut toujours pour l'épisode principal
            if ep.cancel == "superseded" and ep.superseded is not None:
                if ep.task is not None and ep.task.cancelling():
                    ep.task.uncancel()  # l'annulation a été absorbée par le prélude : on la solde ici
                raise ep.superseded

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

    def _tools(self, policy: EpisodePolicy, kind: str, audience: Audience, only: Any = None) -> dict[str, Any]:
        """Les outils offerts (``tools.offer``, la seule porte)."""
        return offer(self.mind.registry.tools, policy, kind, audience, only)

    def _parse(self, text: str, speaker: str = "") -> tuple[str, dict[str, str]]:
        annotations: dict[str, str] = {}
        for parser in self.parsers:
            got = call(parser, text, speaker, label="analyse de réponse")
            if isinstance(got, Failed):
                continue
            text, extra = got
            annotations.update(extra)
        return text, annotations

    async def _settle(self, ep: _Live, outcome: Outcome, failure: Superseded | None = None,
                      detail: str = "") -> None:
        """Le règlement, une fois et une seule : ``episode.ended`` — avec, pour une réponse, les messages
        qu'il laisse sans réponse pour de bon (``unanswered``)."""
        if ep.settled:
            return
        ep.settled = True
        ep.report.outcome = outcome
        ep.report.detail = str(failure) if failure else detail
        self.mind.untrack(ep.id)
        req = ep.req
        unanswered = None
        if req.reply_to is not None:
            unanswered = unanswered_at_end(self.mind.root.slices[RUNTIME.name], req.reply_to, outcome.value)
        draft = EPISODE_ENDED.draft(
            kind=req.kind, outcome=outcome.value, target=req.target, reply_to=req.reply_to,
            detail=detail or (failure.reason if failure else ""),
            guard=failure.guard if failure else None, changed=failure.changed if failure else (),
            unanswered=unanswered,
        )
        await acall(
            lambda: self.mind.append([draft], emitter="runtime", correlation=ep.id, origin=Origin.KERNEL),
            label="régler l'épisode",
        )


def _turn_guard(req: EpisodeRequest) -> Guard | None:
    """La garde du tour : une réponse vaut tant que ``reply_to`` est le dernier message sans réponse de la
    personne, à cet endroit. Un nouveau message la supplante (elle sera recomposée en le lisant) ; une
    question déjà réglée ou abandonnée ne reçoit pas de réponse."""
    if req.reply_to is None or not req.target:
        return None
    key, reply_to = (req.target, req.room), req.reply_to

    def latest(view: FactView) -> bool:
        turn = view.get(rt.TURN(key))
        return bool(turn) and turn[-1] == reply_to

    return Guard("tour", predicate=latest)


def _follows(main: _Live, guard: Guard) -> Guard:
    """La garde d'un prélude : celle de son épisode principal (ce qu'il a lu, son prédicat), ses baux
    toujours tenus par lui, et lui-même ni devancé ni désigné pour céder la place."""
    pred, leases = guard.predicate, guard.leases

    def holds(view: FactView) -> bool:
        if main.cancel is not None or main.settled:
            return False
        if pred is not None and not pred(view):
            return False
        for res in leases:
            lease = view.get(LEASE(res))
            if lease is None or lease.holder != main.id:
                return False
        return True

    return Guard(f"prélude de {main.id}", reads=guard.reads, predicate=holds)


def _scope(root: Any, req: EpisodeRequest, eid: str) -> str:
    """La portée du dédoublonnage des écritures d'outils : pour une réponse, son tour (le premier message
    sans réponse) — recomposée après une supplantation ou une panne, elle ne refait pas ce qui est fait ;
    sinon, l'épisode."""
    if req.reply_to is None or not req.target:
        return eid
    turn = turn_upto(root.slices[RUNTIME.name], req.reply_to)
    first = turn[0] if turn else req.reply_to
    return f"tour:{req.target}:{req.room or ''}:{first}"


def _defers(gateway: LLMGateway | None, role: str) -> bool:
    """Le fournisseur de ce rôle sait-il différer des outils ? (``tools.defers_tools``)"""
    return defers_tools(gateway, role)


def _in_hand(policy: EpisodePolicy, req: EpisodeRequest) -> frozenset[str] | None:
    """Les lots en main : ceux de la politique ; tous ceux qu'offre un candidat qui a choisi ses lots
    (``bundles`` : un pas sur un but, une exécution de projet — il les a choisis pour cette séance)."""
    if req.selected is not None and req.selected.args.get("bundles"):
        return None
    return policy.core_bundles


def _composition(req: EpisodeRequest, audience: Audience, role: str | None, message: str, trace: ComposeTrace,
                 enrich: Mapping[str, Any]) -> dict[str, Any]:
    """Ce qui a décidé du prompt : le déclencheur, l'audience, la composition."""
    return {
        "trigger": req.trigger, "reason": req.reason, "reply_to": req.reply_to, "subject": req.subject,
        "channel": req.channel or audience.channel, "room": req.room or audience.room,
        "audience": {"level": audience.level, "witness_level": audience.witness_level},
        "role": role, "message": message, "enrichments": sorted(enrich),
        "compose": to_plain(trace),
    }


def _request(llm_req: LLMRequest) -> dict[str, Any]:
    """Exactement ce qui part au modèle au premier tour."""
    persona = llm_req.persona
    return {
        STABLE_KEY: llm_req.system_stable,
        "system_volatile": llm_req.system_volatile,
        "messages": [{"role": m.role, "content": m.content} for m in llm_req.messages],
        "tools": [d.name for d in llm_req.tools],
        "persona": {"hash": persona.hash, "depth": persona.depth} if persona is not None else None,
        "call_id": llm_req.call_id, "max_tokens": llm_req.max_tokens, "lane": llm_req.lane,
        "priority": llm_req.priority,
    }


def _results(loop: LoopResult) -> dict[str, Any]:
    """Ce que la boucle a fait : les appels de modèle, les outils avec leurs
    arguments et résultats (déjà bornés), le texte final s'il y en a un."""
    return {
        "llm_calls": loop.call_ids,
        "responses": [
            {"call_id": cid, "model": r.model, "stop": r.stop, "text": r.text,
             "tool_calls": [{"id": c.id, "name": c.name} for c in r.tool_calls],
             "usage": {"input": r.usage.input_tokens, "output": r.usage.output_tokens,
                       "cache_read": r.usage.cache_read, "cache_write": r.usage.cache_write}}
            for cid, r in loop.exchanges
        ],
        "tool_calls": [
            {"call_id": t.call_id, "name": t.name, "args": t.args_json, "ok": t.ok, "result": t.result,
             "duration_us": t.duration_us, "executed": t.executed}
            for t in loop.records
        ],
        # le texte final quand la boucle est allée au bout — même s'il n'a pas
        # été livré (supplanté, préempté) : ce qu'elle allait dire
        "reply": loop.text if loop.responses and loop.stop != "running" else None,
        "stop": loop.stop if loop.responses else None,
    }


def _reserved(persona: PersonaRender | None, more: str, tools: Sequence[ToolDecl]) -> int:
    """Les caractères qui partent au modèle hors du composeur : la persona, le
    catalogue, les déclarations d'outils — toutes, un fournisseur qui ne sait
    pas différer les envoie."""
    return (len(persona.text) + 2 if persona else 0) + (len(more) + 2 if more else 0) + sum(
        len(d.name) + len(d.description) + len(canonical_json(d.schema)) for d in tools)


def _describe(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}"[:500]


class _Preempted(Exception):
    """Préempté avant d'appeler le modèle (la demande est arrivée pendant qu'il se préparait)."""


class _Busy(Exception):
    def __init__(self, resource: str) -> None:
        self.resource = resource
        super().__init__(resource)
