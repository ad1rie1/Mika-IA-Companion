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

**Un mode** (``EpisodeRequest.mode``, le mode pro : ADR 0116) est choisi par
la personne pour un message : il plie la politique de l'épisode (son rôle, sa
persona, ses étiquettes coupées, ses limites), peut taire la relecture et la
seconde passe, ajoute sa consigne ; ``live`` : chaque moment de sa boucle
d'outils est montré en direct à la personne (le port ``activity``), puis la
fin de l'épisode. Rien de ce qui se montre n'est gardé.
"""

from __future__ import annotations

import asyncio
import difflib
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from mika.contracts import runtime as rt
from mika.contracts.runtime import EPISODE_ENDED, EPISODE_STARTED, UTTERANCE, ToolOutcome
from mika.kernel.arbitration import Row
from mika.kernel.builtin import LEASE, LEASE_ACQUIRED, LEASE_RELEASED
from mika.kernel.codec import canonical_json, to_plain
from mika.kernel.episode import EpisodeMode, EpisodePolicy, Outcome, Prelude
from mika.kernel.events import Content, Origin, VoiceProvenance
from mika.kernel.facts import FactView
from mika.kernel.frame import CLOSED, Audience, EpisodeRef, Frame
from mika.kernel.guards import Guard, Superseded, combine, floor
from mika.kernel.prompt import CONTEXT_FOOTER, Budget, Composer, ComposeTrace, SectionBody
from mika.kernel.state import FrozenDict
from mika.ports.delivery import DONE, NOTE, Activity
from mika.ports.llm import PREEMPTED, Held, LLMGateway, LLMRequest, Message, PersonaRender, ToolDecl
from mika.runtime.boundary import Failed, acall, call
from mika.runtime.state import RUNTIME, turn_upto, unanswered_at_end
from mika.runtime.tools import (
    LoopEvent,
    LoopResult,
    ToolContext,
    acting,
    catalogue,
    declare,
    defers_tools,
    offer,
    run_tool_loop,
    situation_of,
)
from mika.runtime.traces import STABLE_KEY, EpisodeTraces
from mika.vocab import flows
from mika.vocab.episodes import Role
from mika.vocab.flows import Author

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
#: La relecture d'une parole : (sa réponse, ses derniers messages, ce que la personne vient de dire, sa persona telle
#: que le modèle l'a lue) → une remarque à glisser en fin d'état interne pour qu'elle la réécrive une fois, ou ``None``.
Reviewer = Callable[[str, Sequence[str], str, str], "str | None"]
#: La seconde passe sur une parole : (sa réponse, les messages de son appel, ce que la personne vient de dire, sa persona
#: rendue, l'autrice du chat) → (consigne, message, ce qu'on garde de ce que l'appel a écrit) d'un appel qui récrit sa
#: réponse, ou ``None`` : rien à reprendre.
Polisher = Callable[[str, Sequence[Message], str, "PersonaRender | None", "Author | None"],
                    "tuple[str, str, Callable[[str], str]] | None"]
#: La passe d'une autrice sur un brouillon d'outil (ADR 0124) : (son flux, le premier jet, ce à quoi il répond,
#: l'autrice) → (consigne, message) d'un appel qui le récrit, ou ``None`` : cette forme ne se récrit pas.
DraftPolisher = Callable[[str, str, str, Author], "tuple[str, str] | None"]
#: l'autrice d'un flux (``vocab.flows``), ou ``None`` : aucune n'y écrit
AuthorOf = Callable[[str], "Author | None"]
#: Les annotations d'une parole récrite par la seconde passe : (son premier jet, ses annotations, le texte récrit) →
#: celles du texte récrit (ce qui décrit la forme du texte — une question, un passage — suit le message envoyé).
Reannotator = Callable[[str, Mapping[str, str], str], Mapping[str, str]]
#: une réponse récrite plus longue que ``_POLISH_GROWTH`` fois le premier jet (plus ``_POLISH_SLACK`` caractères) a
#: dérivé : on garde le premier jet (l'autrice peut envoyer en plusieurs bulles ce qu'un « ah merde. » disait seul)
_POLISH_GROWTH, _POLISH_SLACK = 2.0, 120
#: … pour un brouillon (un courriel a sa formule d'appel et sa formule de politesse) : plus de marge
_DRAFT_SLACK = 400
#: sans réglage des autrices, le chat garde l'autrice d'avant elles : le cadre seul, ni codes ni exemple (ADR 0124)
_CHAT_AUTHOR = Author(flows.CHAT, "")
#: un brouillon que le modèle a mis entre trois accents graves
_FENCED = re.compile(r"^```[\w-]*\n(.*)\n```$", re.S)
#: ce qu'une passe de plus (relecture, seconde passe) laisse de l'échéance de l'épisode, en secondes, pour écrire la
#: réponse : passé ce point, elle s'arrête et le premier jet part
_PASS_SPARE_S = 5.0


def _no_tools(spec: Any, call_id: str) -> ToolContext:
    """Le contexte d'outil d'une passe qui n'en offre aucun : jamais demandé."""
    raise RuntimeError("une passe sans outil n'appelle pas d'outil")


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
    #: la façon de répondre que la personne a demandée (``EpisodeRunner.modes``) ; ``""`` : l'ordinaire
    mode: str = ""


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
    #: le mode qui plie sa politique (``None`` : l'ordinaire)
    mode: EpisodeMode | None = None
    #: l'échéance de l'épisode (``policy.deadline_s``), posée à son départ : une passe de plus s'y range
    deadline: asyncio.Timeout | None = None


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
        reviewers: Sequence[Reviewer] = (),
        reviewed: Sequence[str] = (),
        polishers: Sequence[Polisher] = (),
        polished: Sequence[str] = (),
        reannotators: Sequence[Reannotator] = (),
        modes: Mapping[str, EpisodeMode] | None = None,
        composer: Composer | None = None,
        budget: Budget | None = None,
        lease_margin_s: float = 30.0,
        ports: Mapping[str, Any] | None = None,
        traces: EpisodeTraces | None = None,
        tool_rules: Callable[[str], Mapping[str, str]] | None = None,
        authors: AuthorOf | None = None,
        draft_polishers: Sequence[DraftPolisher] = (),
    ) -> None:
        self.mind = mind
        self.ports = dict(ports or {})
        self.traces = traces
        self.gateway = gateway
        self.policies = dict(policies)
        self.persona = persona
        self.audience_of = audience_of
        self.parsers = list(parsers)
        self.reviewers = list(reviewers)
        #: les sortes d'épisode dont la parole se relit (``reviewers``)
        self.reviewed = frozenset(reviewed)
        self.polishers = list(polishers)
        #: les sortes d'épisode dont la parole passe une seconde fois, pour être rendue naturelle (``polishers``)
        self.polished = frozenset(polished)
        #: ce qui recalcule les annotations d'une parole récrite par la seconde passe (``Reannotator``)
        self.reannotators = list(reannotators)
        #: l'autrice de chaque flux (ADR 0124) ; ``None`` : le chat garde son autrice d'avant elles, un brouillon n'en a
        #: pas
        self.authors = authors
        #: ce qui écrit la passe d'une autrice sur un brouillon d'outil (``DraftPolisher``)
        self.draft_polishers = list(draft_polishers)
        #: les façons de répondre qu'un message peut demander, par nom (``EpisodeRequest.mode``)
        self.modes = dict(modes or {})
        self.composer = composer or Composer()
        self.budget = budget
        #: les règles d'outils d'un opérateur, par situation (``tools.situation_of``, ADR 0122) : retirer un outil, le
        #: mettre en main ou à la demande ; ``None`` : aucune
        self.tool_rules = tool_rules
        self.lease_margin_us = int(lease_margin_s * 1_000_000)
        #: ce que les facultés tirent d'un énoncé, journalisé juste après lui (``Bootstrap.interpret``) : ce que le
        #: modèle qui a répondu a lu de la personne (ADR 0093) ; ``None`` : personne n'interprète
        self.interpret: Callable[[int, str], Awaitable[None]] | None = None
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
        # un mode inconnu, ou qui ne concerne pas cette sorte d'épisode : l'ordinaire
        mode = self.modes.get(req.mode) if req.mode else None
        if mode is not None and req.kind not in mode.kinds:
            mode = None
        if mode is not None:
            policy = mode.applied(policy)
        mind = self.mind
        eid = mind.ids.new(mind.clock.now())
        ep = _Live(eid, req, policy, mind.frame(), EpisodeReport(eid, req.kind, Outcome.DONE),
                   asyncio.current_task(), parent=parent, mode=mode)
        self._live[eid] = ep
        try:
            got = await acall(self._run, ep, label=f"épisode {req.kind}")
            if isinstance(got, Failed):
                # une exception imprévue : l'épisode est réglé quand même (jamais laissé ouvert)
                await self._settle(ep, _failed(got.error), detail=_describe(got.error))
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
            async with asyncio.timeout(policy.deadline_s) as deadline:
                ep.deadline = deadline
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
                if ep.mode is not None:
                    attrs["mode"] = req.mode
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
                rules = self.rules_of(req.kind, audience)
                tools = self._tools(policy, req.kind, audience,
                                    req.selected.args.get("bundles") if req.selected is not None else None, rules)
                offered = list(tools.values())
                core = _in_hand(policy, req)
                if core is not None and policy.role is not None and not _defers(self.gateway, policy.role):
                    # un fournisseur sans recherche d'outils reçoit tout : le prompt ne parle pas d'outils à chercher
                    core = None
                # une parole que quelqu'un lira : ses outils sont ses mains (faire, pas annoncer ni inventer)
                more = "\n\n".join(filter(None, (acting(offered) if policy.visible else "",
                                                 catalogue(offered, core, mind.registry.bundles, rules),
                                                 self._instruction(ep.mode))))
                declared = declare(offered, core, rules)
                provider_budget = getattr(self.gateway, "budget", None)
                budget = self.budget or (provider_budget(policy.role, policy.max_tokens) if (
                    provider_budget is not None and policy.role is not None) else Budget(max_tokens=24_000))
                budget = replace(budget, message_overhead=round(16 * budget.chars_per_token))
                envelope = round((64 + 16 * 2) * budget.chars_per_token)
                prompt, trace = self.composer.compose(
                    blocks, kind=req.kind, audience_level=audience.level, witness_level=audience.witness_level,
                    tied_level=audience.tied_level, veiled_level=audience.veiled_level, muted_tags=policy.muted_tags,
                    message=message, budget=budget,
                    reserved=_reserved(persona, more, declared) + envelope if policy.role is not None else 0,
                    typed_chars=req.typed_chars if message == req.message else None,
                )
                report.trace = trace
                ep.seen.update(_composition(req, audience, policy.role, message, trace, enrich),
                               at=mind.clock.now())
                if ep.mode is not None:
                    ep.seen["mode"] = req.mode
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

                def author_draft(flow: str, text: str, about: str) -> Awaitable[str]:
                    return self._author_draft(ep, eid, llm_req, flow, text, about)

                def make_ctx(spec: Any, call_id: str) -> ToolContext:
                    return ToolContext(mind, spec, call_id, eid, Frame(mind.root, mind.clock.now(),
                                       mind.registry, audience, episode), guard=None, ports=self.ports,
                                       dedupe_scope=scope, authoring=author_draft)

                assert self.gateway is not None, "pas de passerelle LLM"
                gateway = self.gateway
                self._check_preempted(ep)  # désigné avant d'arriver au modèle : il ne l'appelle pas
                ep.preemptible = True
                watch = self._watcher(ep, persona.name if persona is not None else "")
                loop = await acall(
                    lambda: run_tool_loop(gateway, llm_req, tools, make_ctx, max_turns=policy.max_tool_turns,
                                          clock=mind.clock.now, result=ep.loop, watch=watch),
                    label=f"appel du modèle ({policy.role})",
                )
                ep.preemptible = False
                if isinstance(loop, Failed):
                    await self._settle(ep, _failed(loop.error), detail=_describe(loop.error))
                    return
                report.tools = loop.calls
                text, annotations = self._parse(loop.text, persona.name if persona is not None else "",
                                                markdown=ep.mode is not None and ep.mode.markdown)
                if policy.max_paragraphs:
                    text = first_paragraphs(text, policy.max_paragraphs)
                if not text.strip() or is_silence(text):
                    if loop.stop in _UNFINISHED and not loop.text.strip():
                        # elle n'a pas pu finir (trop d'appels d'outils) : ce n'est pas un silence choisi
                        await self._settle(ep, Outcome.FAILED, detail=f"pas de réponse au bout des outils "
                                                                      f"({loop.stop})")
                    elif not policy.delivered and any(ok for _name, ok in loop.calls):
                        # un travail pour elle seule fait par ses outils (le tri d'une file, un verdict) : c'est fait,
                        # pas un silence choisi — il n'y avait rien à dire à personne
                        await self._settle(ep, Outcome.DONE)
                    else:
                        await self._settle(ep, Outcome.ABSTAINED)
                    return
                # la relecture : un tic du modèle repéré dans sa réponse (une question à options, la même ouverture
                # qu'avant, sa phrase redite…) la fait réécrire une fois, la remarque en fin d'état interne. Jamais
                # après des outils : un nouvel appel les referait (une recherche, un envoi)
                # … sauf quand l'autrice la réécrit derrière (ADR 0115) : elle repartirait de toute façon du sens,
                # pas des mots, et la relecture coûtait un appel de plus. Un mode peut taire l'une et l'autre (le mode
                # pro, ADR 0116)
                authored = (self._authored(req.kind) and policy.delivered
                            and (ep.mode is None or ep.mode.polished))
                if (self.reviewers and req.kind in self.reviewed and policy.delivered and not loop.calls
                        and not authored and (ep.mode is None or ep.mode.reviewed)):
                    revised = await self._revise(ep, eid, llm_req, text, message or "", make_ctx, persona)
                    if revised is not None:
                        loop, text, annotations, llm_req = revised
                # la seconde passe : le texte seul, rendu naturel au vu du fil, sans rien y ajouter ; ses balises
                # restent celles du premier jet (ce qu'elle ressent ne change pas), et ses outils ne se refont pas —
                # mais ce qui décrit la forme du texte (une question posée, le passage faux) suit le message envoyé
                if authored:
                    # ce que la personne vient d'écrire : la consigne d'une initiative (« personne ne vient de
                    # t'écrire… ») n'est pas une ligne du fil
                    polished = await self._polish(ep, eid, llm_req, text, req.message or "", make_ctx, persona)
                    if polished != text:
                        annotations = self._reannotate(text, annotations, polished)
                    text = polished
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
                        mode=req.mode if ep.mode is not None else "",
                        floor=max(loop.floor, trace.floor), unkept=loop.unkept or trace.unkept,
                    )],
                    emitter="runtime", correlation=eid, origin=Origin.KERNEL, basis=basis,
                    guard=guard, holder=eid,
                )
                report.text = text
                report.utterance_seq = commit.seqs[-1]
                mind.untrack(eid)
                if self.interpret is not None:
                    await self.interpret(commit.seqs[-1], eid)
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

    def _tools(self, policy: EpisodePolicy, kind: str, audience: Audience, only: Any = None,
               rules: Mapping[str, str] | None = None) -> dict[str, Any]:
        """Les outils offerts (``tools.offer``, la seule porte)."""
        return offer(self.mind.registry.tools, policy, kind, audience, only, rules)

    def rules_of(self, kind: str, audience: Audience) -> Mapping[str, str] | None:
        """Les règles d'outils d'un opérateur pour la situation de cet épisode ; une lecture qui échoue n'en
        applique aucune (la panne est au journal)."""
        situation = situation_of(kind, audience)
        if situation is None or self.tool_rules is None:
            return None
        got = call(self.tool_rules, situation, label="règles d'outils")
        return None if isinstance(got, Failed) else got

    async def _revise(self, ep: _Live, eid: str, llm_req: LLMRequest, text: str, heard: str,
                      make_ctx: Callable[[Any, str], ToolContext], persona: PersonaRender | None
                      ) -> tuple[Any, str, dict[str, str], LLMRequest] | None:
        """Sa réponse relue (``reviewers``) : à la première remarque, un second appel, la remarque glissée juste avant
        la fin de son état interne ; sa nouvelle réponse remplace la première si elle dit quelque chose. Banc de
        conversation du 2026-10-14 : une consigne dans le prompt ne retenait pas les tics du modèle (une réplique
        sur deux finissait par « ceci, ou cela ? ») ; relus, ils se voient sur le brouillon même."""
        mine = [m.content for m in llm_req.messages if m.role == "assistant"]
        note = None
        for reviewer in self.reviewers:
            got = call(reviewer, text, mine, heard, persona.text if persona is not None else "",
                       label="relecture de la réponse")
            if isinstance(got, str) and got.strip():
                note = got.strip()
                break
        if note is None or not llm_req.messages:
            return None
        last = llm_req.messages[-1]
        content = (last.content.replace(CONTEXT_FOOTER, f"{note}\n{CONTEXT_FOOTER}", 1) if CONTEXT_FOOTER in last.content
                   else f"{last.content}\n\n{note}")
        again_req = replace(llm_req, call_id=f"{eid}#relu", tools=(),
                            messages=(*llm_req.messages[:-1], replace(last, content=content)))
        gateway = self.gateway
        assert gateway is not None
        again = await self._extra_pass(ep, lambda: run_tool_loop(gateway, again_req, {}, make_ctx, max_turns=1,
                                                                 clock=self.mind.clock.now),
                                       label="relecture : nouvel appel du modèle")
        if isinstance(again, Failed):
            return None
        text2, annotations2 = self._parse(again.text, persona.name if persona is not None else "")
        if not text2.strip() or is_silence(text2):
            return None
        ep.seen["relecture"] = {"premier_jet": text, "remarque": note}
        return again, text2, annotations2, again_req

    @staticmethod
    async def _extra_pass(ep: _Live, fn: Callable[[], Awaitable[LoopResult]], *, label: str) -> LoopResult | Failed:
        """Un appel de plus sur une réponse déjà prête (relecture, seconde passe), rangé dans l'échéance de l'épisode
        moins de quoi écrire la réponse (``_PASS_SPARE_S``) : s'il n'y tient pas, c'est une panne comme une autre et le
        premier jet part — jamais l'échéance de l'épisode qui tomberait pendant lui et jetterait la réponse prête."""
        if ep.deadline is None or (when := ep.deadline.when()) is None:
            return await acall(fn, label=label)
        try:
            async with asyncio.timeout_at(when - _PASS_SPARE_S):
                return await acall(fn, label=label)
        except TimeoutError as exc:
            return Failed(exc)

    def _authored(self, kind: str) -> bool:
        """Sa parole de cette sorte passe par l'autrice : un polisseur, cette sorte, une autrice au chat, et un modèle
        au rôle ``polish``."""
        serving = getattr(self.gateway, "serving", None)
        return (bool(self.polishers) and kind in self.polished and callable(serving)
                and bool(serving(str(Role.POLISH))) and self._author(flows.CHAT) is not None)

    def _author(self, flow: str) -> Author | None:
        """L'autrice d'un flux (``authors``). Sans réglage des autrices, le chat garde la sienne d'avant elles (le
        cadre seul) et un brouillon n'en a pas."""
        if self.authors is None:
            return _CHAT_AUTHOR if flow == flows.CHAT else None
        got = call(self.authors, flow, label="l'autrice d'un flux")
        return got if isinstance(got, Author) else None

    async def _polish(self, ep: _Live, eid: str, llm_req: LLMRequest, text: str, heard: str,
                      make_ctx: Callable[[Any, str], ToolContext], persona: PersonaRender | None) -> str:
        """Sa réponse récrite (``polishers``) par le modèle du rôle ``polish`` — seulement si l'opératrice lui en a
        donné un : sans repli, une installation ne paie pas un second appel de sa voix sans l'avoir choisi. Le
        polisseur dit ce qu'on garde de ce que l'appel a écrit (l'autrice écrit aussi la réponse de l'autre, ADR 0114).
        Une panne, rien gardé, un silence, ou une réponse qui dérive en longueur : le premier jet part tel quel."""
        gateway = self.gateway
        serving = getattr(gateway, "serving", None)
        if gateway is None or not callable(serving) or not serving(str(Role.POLISH)):
            return text
        name = persona.name if persona is not None else ""
        author = self._author(flows.CHAT)
        if author is None:
            return text
        asked = None
        for polisher in self.polishers:
            got = call(polisher, text, llm_req.messages, heard, persona, author, label="seconde passe sur la réponse")
            if isinstance(got, tuple):
                asked = got
                break
        if asked is None:
            return text
        system, message, keep = asked
        req = LLMRequest(role=str(Role.POLISH), call_id=f"{eid}#naturel", system_stable=system,
                         messages=(Message("user", message),), max_tokens=llm_req.max_tokens, lane=llm_req.lane,
                         priority=llm_req.priority, meta={**dict(llm_req.meta), "passe": "naturel"})
        again = await self._extra_pass(
            ep, lambda: run_tool_loop(gateway, req, {}, make_ctx, max_turns=1, clock=self.mind.clock.now),
            label="seconde passe : appel du modèle")
        if isinstance(again, Failed):
            return text
        kept = call(keep, again.text, label="seconde passe : ses messages")
        if isinstance(kept, Failed):
            return text
        polished, _annotations = self._parse(kept, name)
        polished = polished.strip()
        if not polished or is_silence(polished) or len(polished) > len(text) * _POLISH_GROWTH + _POLISH_SLACK:
            return text
        ep.seen["naturel"] = {"premier_jet": text, "autrice": author.key}
        return polished

    async def _author_draft(self, ep: _Live, eid: str, llm_req: LLMRequest, flow: str, text: str, about: str) -> str:
        """Un brouillon d'outil (un courriel, un message Teams, un SMS à la place de la personne) récrit par l'autrice
        de son flux (ADR 0124), comme la seconde passe de sa parole : par le modèle du rôle ``polish`` seulement, sans
        outil, en un tour. Pas d'autrice, pas de modèle, une panne, rien rendu, un silence, ou un texte qui dérive en
        longueur : le premier jet est posé tel quel."""
        gateway = self.gateway
        serving = getattr(gateway, "serving", None)
        author = self._author(flow)
        if gateway is None or author is None or not callable(serving) or not serving(str(Role.POLISH)):
            return text
        asked = None
        for polisher in self.draft_polishers:
            got = call(polisher, flow, text, about, author, label="autrice d'un brouillon")
            if isinstance(got, tuple):
                asked = got
                break
        if asked is None:
            return text
        system, message = asked
        done = ep.seen.setdefault("autrice", [])
        req = LLMRequest(role=str(Role.POLISH), call_id=f"{eid}#autrice{len(done)}", system_stable=system,
                         messages=(Message("user", message),), max_tokens=llm_req.max_tokens, lane=llm_req.lane,
                         priority=llm_req.priority, meta={**dict(llm_req.meta), "passe": "autrice", "flux": flow})
        again = await self._extra_pass(
            ep, lambda: run_tool_loop(gateway, req, {}, _no_tools, max_turns=1, clock=self.mind.clock.now),
            label="autrice d'un brouillon : appel du modèle")
        if isinstance(again, Failed):
            return text
        written = again.text.strip()
        fenced = _FENCED.match(written)
        written = fenced.group(1).strip() if fenced else written
        if not written or is_silence(written) or len(written) > len(text) * _POLISH_GROWTH + _DRAFT_SLACK:
            return text
        done.append({"flux": flow, "autrice": author.key, "premier_jet": text})
        return written

    def _reannotate(self, draft: str, annotations: Mapping[str, str], text: str) -> dict[str, str]:
        """Les annotations du texte récrit (``reannotators``) ; une panne garde celles qu'on avait."""
        out = dict(annotations)
        for reannotator in self.reannotators:
            got = call(reannotator, draft, out, text, label="annotations de la réponse récrite")
            if not isinstance(got, Failed):
                out = dict(got)
        return out

    @staticmethod
    def _instruction(mode: EpisodeMode | None) -> str:
        """La consigne du mode (vide sans mode, ou sans consigne) ; une panne la tait."""
        if mode is None or mode.instruction is None:
            return ""
        got = call(mode.instruction, label="consigne du mode")
        return "" if isinstance(got, Failed) else str(got or "")

    def _watcher(self, ep: _Live, speaker: str) -> Callable[[LoopEvent], Awaitable[None]] | None:
        """Le regard sur sa boucle d'outils, pour un mode qui la montre en direct à la personne (``live``) : chaque
        moment part au port ``activity`` — ce qu'elle écrit entre deux appels, sans ses balises. ``None`` : rien à
        montrer (pas de mode en direct, personne à qui le montrer, pas de port)."""
        port = self.ports.get("activity")
        target = ep.req.target
        if ep.mode is None or not ep.mode.live or port is None or not target:
            return None

        async def watch(event: LoopEvent) -> None:
            now = self.mind.clock.now()
            if event.phase == NOTE:
                text = self._parse(event.text, speaker, markdown=ep.mode is not None and ep.mode.markdown)[0].strip()
                if text:
                    await port.activity(Activity(target, ep.id, NOTE, now, ep.req.reply_to, text=text))
                return
            rec = event.record
            await port.activity(Activity(
                target, ep.id, event.phase, now, ep.req.reply_to, call_id=event.call_id, name=event.name,
                args=rec.args_json if rec is not None else event.args, ok=rec.ok if rec is not None else None,
                result=rec.result if rec is not None else "", duration_us=rec.duration_us if rec is not None else 0,
            ))

        return watch

    async def _show_done(self, ep: _Live, outcome: Outcome) -> None:
        """La fin de l'épisode, montrée à qui le regardait travailler (``live``) : plus rien ne tourne."""
        port = self.ports.get("activity")
        if ep.mode is None or not ep.mode.live or port is None or not ep.req.target:
            return
        await acall(port.activity, Activity(ep.req.target, ep.id, DONE, self.mind.clock.now(), ep.req.reply_to,
                                            outcome=outcome.value), label="fin de l'activité en direct")

    def _parse(self, text: str, speaker: str = "", *, markdown: bool = False) -> tuple[str, dict[str, str]]:
        """Le texte livrable et ce que les analyseurs en tirent. ``markdown`` : ses blocs de code, son code en ligne
        et l'indentation de ses lignes passent à l'abri (``_shield``)."""
        if markdown:
            shielded, kept = _shield(text)
            out, annotations = self._parse(shielded, speaker)
            return _unshield(out, kept), annotations
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
        await self._show_done(ep, outcome)


#: ce qu'une réponse en Markdown garde tel quel (``EpisodeMode.markdown``) : un bloc de code (fermé ou non), du code
#: en ligne, l'indentation d'une ligne — les analyseurs rangent une parole de chat (espaces resserrés, indentation
#: ôtée, ``[ARR]`` pris pour un jeton)
_SHIELDED = re.compile(r"```.*?(?:```|\Z)|`[^`\n]+`|^[ \t]{2,}(?=\S)", re.DOTALL | re.MULTILINE)
_SHIELD = re.compile("\ue000(\\d+)\ue001")


def _shield(text: str) -> tuple[str, list[str]]:
    """Le texte où chaque passage à garder tel quel est remplacé par un repère (des caractères à usage privé), et
    ces passages dans l'ordre."""
    kept: list[str] = []

    def keep(m: re.Match[str]) -> str:
        kept.append(m.group(0))
        return f"\ue000{len(kept) - 1}\ue001"

    return _SHIELDED.sub(keep, text), kept


def _unshield(text: str, kept: Sequence[str]) -> str:
    """Les passages gardés remis à leur repère (un repère inconnu se retire)."""
    return _SHIELD.sub(lambda m: kept[int(m.group(1))] if int(m.group(1)) < len(kept) else "", text)


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


def first_paragraphs(text: str, n: int) -> str:
    """Les ``n`` premiers paragraphes d'un texte (séparés par une ligne vide)."""
    kept = [part.strip() for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]
    return "\n\n".join(kept[:n])


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


def _failed(error: BaseException) -> Outcome:
    """L'issue d'un épisode arrêté par une erreur : un appel de fond refusé d'avance pour garder la réserve de la
    conversation (``Held``, le quota d'un abonnement) n'a rien tenté — le premier plan est passé devant, comme une
    préemption ; ce n'est pas une panne, qu'un but compterait jusqu'à se clore « en échec » (ADR 0127)."""
    return Outcome.PREEMPTED if isinstance(error, Held) else Outcome.FAILED


class _Preempted(Exception):
    """Préempté avant d'appeler le modèle (la demande est arrivée pendant qu'il se préparait)."""


class _Busy(Exception):
    def __init__(self, resource: str) -> None:
        self.resource = resource
        super().__init__(resource)
