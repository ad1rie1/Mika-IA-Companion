"""La boucle d'outils — une seule, pour tous les fournisseurs.

Trois issues d'un appel d'outil, aucune ne remonte en exception : outil
inconnu, arguments illisibles, gestionnaire qui lève → un résultat d'erreur
rendu au modèle. Un appel d'outil coupé par la limite de jetons est rejoué une
fois avec une limite doublée. Un outil émet ses événements tout de suite ; le
suivant voit l'état à jour (il lit ses propres écritures).

Jamais un marqueur interne comme sa parole : au plafond de tours, ou quand un
appel d'outil reste coupé, un **dernier tour sans outil** lui demande de
répondre avec ce qu'elle sait ; s'il ne rend toujours pas de texte, la boucle
rend un texte vide (l'épisode se règle en échec, rien n'est dit).

Une écriture d'outil est dédoublonnée par ce qu'elle *est* dans l'épisode —
``portée:outil:empreinte des arguments:occurrence:rang`` — jamais par
l'identifiant d'appel du fournisseur (``call_0`` revient d'un épisode à
l'autre). La portée d'une réponse est son tour de conversation : quand elle
est supplantée puis recomposée, refaire le même appel ne refait pas l'écriture.

Chaque appel d'outil laisse un ``ToolRecord`` (arguments et résultat bornés,
durée lue sur l'horloge injectée) : de quoi répondre à « pourquoi a-t-elle dit
ça ? » sans rejouer l'épisode.

Qui regarde la boucle en direct (``watch``, le mode pro : ADR 0116) en voit
chaque moment (``LoopEvent``) : un outil qui part, le même fini (refusé
compris), ce qu'elle écrit entre deux appels. Un regard qui lève ne change
rien à la boucle.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from mika.contracts import runtime as rt
from mika.kernel.codec import h64
from mika.kernel.episode import EpisodePolicy
from mika.kernel.events import Draft, Origin
from mika.kernel.faculty import ToolResult, ToolSpec
from mika.kernel.frame import Audience, Frame
from mika.kernel.guards import Guard, combine
from mika.kernel.schema import problems as schema_problems
from mika.ports.delivery import NOTE, TOOL_END, TOOL_START
from mika.ports.llm import LLMGateway, LLMRequest, LLMResponse, Message, ToolCall, ToolDecl
from mika.runtime import boundary
from mika.runtime.boundary import Failed, acall
from mika.vocab.episodes import Kind
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import ChannelTrust

if TYPE_CHECKING:
    from mika.runtime.mind import Commit, Mind

TOOL_CALL_CAP_CEILING = 16_384
#: Clé que posent les fournisseurs quand les arguments d'un appel ne sont pas
#: du JSON : l'appel est refusé au modèle, jamais exécuté avec des défauts.
RAW_ARGS_KEY = "_raw"
#: au-delà, les arguments et le résultat d'un appel sont coupés dans sa trace
RECORD_MAX_CHARS = 4096
RECORD_TRUNCATED = "…[coupé]"


@dataclass(slots=True)
class ToolContext:
    """Ce qu'un gestionnaire d'outil reçoit."""

    mind: Mind
    spec: ToolSpec
    call_id: str
    episode_id: str
    frame: Frame
    guard: Guard | None = None
    ports: Mapping[str, Any] = field(default_factory=dict)
    #: les appels d'outils déjà faits dans cet épisode (nom, réussi) : ce
    #: qu'elle a réellement fait, pour qui doit en juger (« fini » exige une preuve)
    calls: tuple[tuple[str, bool], ...] = ()
    #: ce que chacun de ces appels a déclaré prouver (``ToolResult.proof``), aligné sur ``calls`` (ADR 0104)
    proofs: tuple[bool | None, ...] = ()
    #: la portée du dédoublonnage de ses écritures (le tour d'une réponse ; l'épisode sinon)
    dedupe_scope: str | None = None
    #: ce qu'est l'appel dans l'épisode : ``outil:empreinte des arguments:occurrence`` (posé par la boucle)
    call_key: str | None = None
    #: l'autrice de ses brouillons (ADR 0124, posée par le pipeline) : ``fn(flux, texte, à propos) -> texte`` ;
    #: absente, un brouillon part tel que le modèle l'a écrit
    authoring: Callable[[str, str, str], Awaitable[str]] | None = None
    _emitted: int = 0

    @property
    def state(self) -> Any:
        return self.frame.state(self.spec.owner)

    async def authored(self, flow: str, text: str, about: str = "") -> str:
        """Un brouillon que l'outil va poser (un courriel, un message Teams, un SMS) récrit par l'autrice de son flux
        (``vocab.flows``) ; ``about`` : ce à quoi il répond. Tel quel sans autrice, sans modèle au rôle ``polish``, ou
        si la passe échoue."""
        if self.authoring is None or not text.strip():
            return text
        got = await acall(self.authoring, flow, text, about, label="autrice d'un brouillon")
        return got if isinstance(got, str) and got.strip() else text

    async def emit(self, *drafts: Draft[Any], guard: Guard | None = None) -> Commit:
        """Écrire au nom de la faculté de l'outil. ``guard`` s'ajoute à la garde de l'épisode : ce que
        l'écriture suppose encore vrai au moment du commit (sinon ``Superseded``, et rien n'est écrit)."""
        return await self._append(drafts, emitter=self.spec.owner, guard=guard)

    async def propose(self, draft: Draft[Any]) -> Commit:
        """Proposer un effet extérieur : une capacité de la faculté de l'outil.

        ``effect.proposed`` appartient au runtime, qui l'exécute après commit
        (ou après accord) : un outil ne peut pas l'émettre en son nom (le Mind
        refuserait l'émetteur). Le runtime l'écrit donc pour lui, corrélé à
        l'épisode comme une écriture de l'outil — et seulement pour une capacité
        que la faculté de l'outil possède."""
        if draft.type is not rt.EFFECT_PROPOSED:
            raise TypeError(f"propose attend {rt.EFFECT_PROPOSED.name}, reçu {draft.type.name}")
        owner = self.spec.owner
        if draft.data.owner != owner or not draft.data.capability.startswith(f"{owner}."):
            raise PermissionError(f"{owner} ne peut proposer que ses propres capacités "
                                  f"(pas {draft.data.capability})")
        return await self._append((draft,), emitter=rt.OWNER)

    async def _append(self, drafts: Sequence[Draft[Any]], *, emitter: str, guard: Guard | None = None) -> Commit:
        keyed = []
        scope = self.dedupe_scope or self.episode_id
        for d in drafts:
            key = d.dedupe_key or f"{scope}:{self.call_key or self.call_id}:{self._emitted}"
            self._emitted += 1
            keyed.append(replace(d, dedupe_key=key))
        commit = await self.mind.append(
            keyed, emitter=emitter, correlation=self.episode_id, origin=Origin.TOOL,
            causation=None, basis=self.frame.root, guard=combine(self.guard, guard) if guard else self.guard,
            holder=self.episode_id,
        )
        self.frame = Frame(commit.root, self.mind.clock.now(), self.mind.registry,
                           self.frame.audience, self.frame.episode)
        return commit


class ReadOnly(PermissionError):
    """Un outil a voulu écrire dans sa vie par un contexte en lecture seule."""


@dataclass(slots=True)
class ReadingContext(ToolContext):
    """Le contexte d'un outil prêté en lecture seule (ADR 0122) : il lit, mais n'écrit rien dans sa vie — ni
    événement, ni effet proposé ; une écriture lève ``ReadOnly``, et l'appel est refusé."""

    async def _append(self, drafts: Sequence[Draft[Any]], *, emitter: str, guard: Guard | None = None) -> Commit:
        raise ReadOnly(phrase("runtime.tools.refused.read_only"))


@dataclass(frozen=True, slots=True)
class ToolRecord:
    """Un appel d'outil tel qu'il s'est passé : ce que le modèle a demandé, ce
    qui lui a été rendu. ``executed`` est faux pour un appel refusé avant le
    gestionnaire (outil inconnu, plafond, arguments illisibles)."""

    call_id: str
    name: str
    args_json: str
    ok: bool
    result: str
    duration_us: int = 0
    executed: bool = True


@dataclass(frozen=True, slots=True)
class LoopEvent:
    """Un moment de la boucle, pour qui la regarde en direct : un outil part (``start`` : ``call_id``, ``name``,
    ``args``), il a fini (``end`` : son ``record``), elle a écrit entre deux appels (``note`` : ``text``)."""

    phase: str
    call_id: str = ""
    name: str = ""
    args: str = ""
    record: ToolRecord | None = None
    text: str = ""


Watch = Callable[[LoopEvent], Awaitable[None]]


@dataclass(slots=True)
class LoopResult:
    text: str
    #: (nom, réussi) des appels exécutés — ce que garde ``Utterance.tools``
    calls: list[tuple[str, bool]] = field(default_factory=list)
    #: ce que chacun a déclaré prouver (``ToolResult.proof``), aligné sur ``calls``
    proofs: list[bool | None] = field(default_factory=list)
    stop: str = "end"
    responses: int = 0
    last: LLMResponse | None = None
    #: chaque appel d'outil, exécuté ou refusé, dans l'ordre
    records: list[ToolRecord] = field(default_factory=list)
    #: chaque réponse du modèle, avec l'identifiant de l'appel qui l'a produite
    exchanges: list[tuple[str, LLMResponse]] = field(default_factory=list)
    #: ce que ses outils réussis ont préparé pour partir avec le message (``ToolResult.attach``), sans doublon,
    #: dans l'ordre — des références opaques
    attachments: list[str] = field(default_factory=list)
    #: ce que valent ses réponses réussies (``ToolResult.floor``, ``unkept``) : ce que l'énoncé emporte (ADR 0128)
    floor: int = 0
    unkept: bool = False

    @property
    def call_ids(self) -> list[str]:
        """Les identifiants des appels de modèle, sans doublon, dans l'ordre (une
        boucle réutilise le même d'un tour à l'autre)."""
        return list(dict.fromkeys(cid for cid, _ in self.exchanges))


#: ce qu'un opérateur décide d'un outil dans une situation (ADR 0122) : le retirer, le mettre en main, le laisser à
#: la demande. Il ne fait que restreindre : un outil que la porte n'offre pas ne s'offre pas par une règle, et un
#: outil qui clôt la boucle (``ends_loop`` : rendre compte d'un pas) ne se règle pas.
OFF, HAND, ASK = "off", "hand", "ask"
RULES = (OFF, HAND, ASK)
#: les situations où une règle s'applique (les mêmes que la console : « qui reçoit quoi »)
SITUATIONS = ("proprietaire", "compte", "inconnue", "salon", "initiative", "pas", "projet", "tache")


def situation_of(kind: str, audience: Audience) -> str | None:
    """La situation d'un épisode, pour ses règles d'outils : à qui elle répond (sa propriétaire, une personne qui a
    un compte, une inconnue, un salon), quand elle prend la parole, quand personne n'écoute (un pas sur un but, une
    exécution de projet, une tâche). ``None`` : une sorte d'épisode qu'aucune règle ne touche (un réveil, un
    murmure)."""
    if kind == Kind.REPLY:
        if audience.public:
            return "salon"
        if audience.owner:
            return "proprietaire"
        return "compte" if audience.trust == ChannelTrust.AUTHENTICATED.value else "inconnue"
    return {Kind.INITIATIVE: "initiative", Kind.STEP: "pas", Kind.WORK: "projet", Kind.JOB: "projet",
            Kind.TASK: "tache"}.get(kind)


def rule_of(spec: ToolSpec, rules: Mapping[str, str] | None) -> str | None:
    """La règle d'un opérateur pour cet outil, s'il y en a une qui compte (aucune sur un outil qui clôt la boucle)."""
    return None if rules is None or spec.ends_loop else rules.get(spec.name)


def deferred(spec: ToolSpec, core: frozenset[str] | None, rules: Mapping[str, str] | None = None) -> bool:
    """Cet outil offert est-il à la demande ? Pas quand tout est en main (``core`` vide de sens : ``None``) ; sinon la
    règle de l'opérateur s'il y en a une, et à défaut son lot ou l'outil lui-même (``in_hand``)."""
    if core is None:
        return False
    rule = rule_of(spec, rules)
    if rule in (HAND, ASK):
        return rule == ASK
    return spec.bundle not in core and not spec.in_hand


def offer(tools: Mapping[str, ToolSpec], policy: EpisodePolicy, kind: str, audience: Audience,
          only: Any = None, rules: Mapping[str, str] | None = None, frame: Any = None) -> dict[str, ToolSpec]:
    """Les outils offerts : les lots de la politique — restreints, quand le
    candidat le dit (``bundles`` : « goals,workshop »), à ceux-là seuls. Un
    lot est offert entier ou pas du tout, moins les outils réservés à ses
    propriétaires quand quelqu'un d'autre écoute (``owner_only``), et moins ceux
    qu'un opérateur a retirés dans cette situation (``rules`` : ``OFF``).

    La seule porte : le pipeline l'applique à chaque épisode, la console à des
    audiences de synthèse (« qui reçoit quoi ») — jamais une recopie. ``frame`` :
    ce qu'elle vit, pour une condition qui lit son journal (``fits``, ADR 0133)."""
    bundles = policy.tool_bundles
    if only:
        bundles = frozenset(b for b in (x.strip() for x in str(only).split(",")) if b and admitted(policy.tool_bundles, b))
    out = {}
    for name, spec in tools.items():
        if kind not in spec.episodes or not admitted(bundles, spec.bundle):
            continue
        if rule_of(spec, rules) == OFF:
            continue
        if spec.min_level is not None and audience.level < spec.min_level:
            continue
        if spec.owner_only and not audience.owner:
            continue
        if spec.when is not None and boundary.call(spec.when, audience, label=f"offre de {name}") is not True:
            continue
        if spec.fits is not None and boundary.call(spec.fits, audience, kind, frame,
                                                   label=f"offre de {name}") is not True:
            continue
        out[name] = spec
    return out


def admitted(bundles: frozenset[str], bundle: str) -> bool:
    """Un lot est-il admis ? Par son nom, ou par sa famille (``mcp.*`` admet ``mcp.meteo`` : des lots que des
    sources dynamiques ajoutent, ADR 0064) — et le lot qui porte le nom d'une famille l'admet entière
    (``forge_apps`` admet ``forge_apps.cours`` : chaque app est un lot, ses apps en sont un, ADR 0104)."""
    if bundle in bundles:
        return True
    family, dot, _rest = bundle.partition(".")
    return bool(dot) and (f"{family}.*" in bundles or family in bundles)


def defers_tools(gateway: Any, role: str) -> bool:
    """Le fournisseur de ce rôle sait-il différer des outils ? Sans réponse (ou en panne) : oui."""
    ask = getattr(gateway, "defers_tools", None)
    if ask is None:
        return True
    got = boundary.call(ask, role, label="outils différables")
    return True if isinstance(got, Failed) else bool(got)


def declare(specs: Sequence[ToolSpec], core: frozenset[str] | None = None,
            rules: Mapping[str, str] | None = None) -> tuple[ToolDecl, ...]:
    """Déclarations triées par nom : un préfixe stable pour le cache. Un outil
    dont le lot n'est pas « en main » (``core``) est déclaré à la demande, sauf
    règle d'un opérateur (``deferred``)."""
    return tuple(
        ToolDecl(s.name, s.description, dict(s.schema) if s.schema is not None else s.args.model_json_schema(),
                 deferred=deferred(s, core, rules))
        for s in sorted(specs, key=lambda s: s.name)
    )


# ce qu'on lui dit de ses outils quand elle parle à quelqu'un (``runtime.tools.acting``) : faire plutôt qu'annoncer,
# et ne rien raconter qu'un outil ne lui a pas rendu (2026-10-04, nemotron : « peux-tu regarder les nouvelles ? » —
# « je vais regarder », aucun appel, puis Product Hunt et l'actualité française inventés sur quatre tours)


def means() -> tuple[tuple[str, str], ...]:
    """De quoi se donner les moyens de ce qu'elle ne sait pas faire, quand l'outil est là : (outil, en mots)."""
    return (("forge_write", phrase("runtime.tools.means_forge")), ("start_project", phrase("runtime.tools.means_project")))


def acting(specs: Sequence[ToolSpec]) -> str:
    """La règle de ses mains, pour une parole qui porte des outils (vide sans outil). Ce qu'elle peut se fabriquer
    n'est cité que si l'outil lui est offert : une inconnue ne voit pas la Forge, une initiative non plus. Quand un de
    ses outils parle à un service extérieur (ADR 0064) : ce qui en revient, ce qui y part."""
    if not specs:
        return ""
    names = {s.name for s in specs}
    found = [words for tool, words in means() if tool in names]
    text = phrase("runtime.tools.acting")
    if found:
        text = phrase("runtime.tools.acting_means", acting=text, means=phrase("runtime.tools.means_or").join(found))
        if "start_project" in names:  # un travail se lance maintenant, ou il n'existe pas (ADR 0104)
            text = f"{text} {phrase('runtime.tools.means_work')}"
    return f"{text} {phrase('runtime.tools.outside')}" if any(getattr(s, "outside", False) for s in specs) else text


def _wants_container(prop: Mapping[str, Any]) -> bool:
    """Ce champ du schéma attend-il une liste ou un objet ?"""
    for p in (prop, *(prop.get("anyOf") or ()), *(prop.get("oneOf") or ())):
        kind = p.get("type")
        kinds = set(kind) if isinstance(kind, list) else {kind}
        if kinds & {"array", "object"} or "$ref" in p or "items" in p or "properties" in p:
            return True
    return False


def unquoted(spec: ToolSpec, args: dict[str, Any]) -> dict[str, Any]:
    """Un modèle passe parfois une liste ou un objet en texte JSON (« "[{…}]" ») : décodé quand le schéma de l'outil
    attend une liste ou un objet à cet endroit et que le texte en est bien un — sinon laissé tel quel, et la
    validation dira ce qui ne va pas (sonde du 2026-10-13 : une retouche refusée pour sa liste écrite en texte)."""
    texts = {k: v for k, v in args.items() if isinstance(v, str) and v.lstrip()[:1] in ("[", "{")}
    if not texts:
        return args
    schema = spec.schema if spec.schema is not None else spec.args.model_json_schema()
    props = schema.get("properties") or {}
    out = dict(args)
    for key, value in texts.items():
        if not _wants_container(props.get(key) or {}):
            continue
        try:
            decoded = json.loads(value)
        except ValueError:
            continue
        if isinstance(decoded, list | dict):
            out[key] = decoded
    return out


#: la boucle s'est arrêtée sur un outil qui conclut (``ToolSpec.ends_loop``)
ENDED_BY_TOOL = "tool_end"


def catalogue(specs: Sequence[ToolSpec], core: frozenset[str] | None, described: Mapping[str, str],
              rules: Mapping[str, str] | None = None) -> str:
    """Les lots offerts mais pas en main, une ligne chacun : ce qu'elle peut
    aller chercher. Vide quand tout est en main. Stable d'un tour à l'autre
    (trié), donc à sa place dans le préfixe en cache."""
    if core is None:
        return ""
    away: dict[str, list[str]] = {}
    for s in specs:
        if deferred(s, core, rules):
            away.setdefault(s.bundle, []).append(s.name)
    if not away:
        return ""
    lines = [f"- {b} : {described.get(b) or ', '.join(sorted(names))}" for b, names in sorted(away.items())]
    return "\n".join([phrase("runtime.tools.catalogue_header"), phrase("runtime.tools.catalogue_intro"), *lines])


async def run_tool_loop(
    gateway: LLMGateway,
    request: LLMRequest,
    tools: Mapping[str, ToolSpec],
    make_context: Callable[[ToolSpec, str], ToolContext],
    *,
    max_turns: int,
    clock: Callable[[], int] | None = None,
    result: LoopResult | None = None,
    watch: Watch | None = None,
) -> LoopResult:
    """``clock`` date les appels d'outils (sans horloge : durées nulles) ;
    ``result``, s'il est donné, est rempli au fil de l'eau — ce qui a été fait
    reste lisible quand l'épisode est coupé en route (délai, supplantation) ;
    ``watch``, s'il est donné, en voit chaque moment au fil de l'eau.
    La boucle finie, de quelque façon que ce soit (réponse, plafond, coupure,
    annulation), la passerelle la relâche (``release(call_id)``) : un
    fournisseur à session n'attend pas son délai d'inactivité."""
    try:
        return await _loop(gateway, request, tools, make_context, max_turns=max_turns, clock=clock, result=result,
                           watch=watch)
    finally:
        release(gateway, request.call_id)


def checked_args(spec: ToolSpec, raw: Mapping[str, Any]) -> tuple[Any, str]:
    """Les arguments d'un appel, vérifiés comme la boucle les vérifie : ``(arguments, "")``, ou ``(None, le refus)``
    à rendre au modèle (ou à l'agent d'un point de prêt, ADR 0122)."""
    if RAW_ARGS_KEY in raw:
        return None, phrase("runtime.tools.refused.not_json")
    given = unquoted(spec, dict(raw))
    try:
        args = spec.args.model_validate(given)
    except ValidationError as exc:
        return None, phrase("runtime.tools.refused.invalid", errors=exc.errors(include_url=False))
    wrong = schema_problems(spec.schema, given) if spec.schema is not None else []
    if wrong:
        return None, phrase("runtime.tools.refused.wrong", problems=" ; ".join(wrong))
    return args, ""


def lendable(offered: Mapping[str, ToolSpec]) -> dict[str, ToolSpec]:
    """Ce qu'un point MCP peut prêter à un agent (ADR 0122) : ce que la porte lui offre en conversation, moins ce
    qui clôt une boucle. Un outil ne dit pas s'il écrit : la lecture seule se tient à l'exécution
    (``ReadingContext``)."""
    return {n: s for n, s in offered.items() if not s.ends_loop}


def release(gateway: Any, call_id: str) -> None:
    """``gateway.release(call_id)`` s'il existe (facultatif) ; une panne n'empêche rien."""
    hook = getattr(gateway, "release", None)
    if callable(hook):
        boundary.call(hook, call_id, label="relâcher une boucle de modèle")


async def _loop(
    gateway: LLMGateway,
    request: LLMRequest,
    tools: Mapping[str, ToolSpec],
    make_context: Callable[[ToolSpec, str], ToolContext],
    *,
    max_turns: int,
    clock: Callable[[], int] | None,
    result: LoopResult | None,
    watch: Watch | None = None,
) -> LoopResult:
    result = result if result is not None else LoopResult(text="")
    result.stop = "running"  # chaque sortie le fixe ; resté tel quel, la boucle a été coupée en route
    now = clock or _no_clock
    req = request
    counts: dict[str, int] = {}
    same: dict[str, int] = {}
    replayed = False
    for _turn in range(max_turns):
        resp = await gateway.call(req)
        result.responses += 1
        result.last = resp
        result.exchanges.append((req.call_id, resp))
        if resp.truncated_tool_call:
            if not replayed and req.max_tokens < TOOL_CALL_CAP_CEILING:
                replayed = True
                req = replace(req, max_tokens=min(TOOL_CALL_CAP_CEILING, req.max_tokens * 2))
                continue
            return await _close(gateway, req, result, "truncated")
        if not resp.tool_calls:
            result.text = resp.text
            result.stop = resp.stop
            return result
        outputs: list[Message] = []
        ended = False
        if resp.text.strip():
            await _show(watch, LoopEvent(NOTE, text=resp.text))
        for call in resp.tool_calls:
            spec = tools.get(call.name)
            if spec is None:
                outputs.append(await _refuse(watch, call, phrase("runtime.tools.refused.unknown", name=call.name), result))
                continue
            limit = spec.max_calls_per_episode
            if limit is not None and counts.get(call.name, 0) >= limit:
                outputs.append(await _refuse(watch, call, phrase("runtime.tools.refused.capped", name=call.name), result))
                continue
            args, refused = checked_args(spec, call.args)
            if refused:
                outputs.append(await _refuse(watch, call, refused, result))
                continue
            counts[call.name] = counts.get(call.name, 0) + 1
            ctx = make_context(spec, call.id)
            if isinstance(ctx, ToolContext):
                ctx.calls = tuple(result.calls)
                ctx.proofs = tuple(result.proofs)
                what = f"{call.name}:{_args_digest(call.args)}"
                same[what] = same.get(what, 0) + 1
                ctx.call_key = f"{what}:{same[what]}"
            await _show(watch, LoopEvent(TOOL_START, call.id, call.name, _args_json(call.args)))
            t0 = now()
            out = await acall(spec.handler, args, ctx, label=f"outil {call.name}")
            elapsed = max(0, now() - t0)
            if isinstance(out, Failed):
                message = phrase("runtime.tools.refused.failed", error=repr(out.error))
                result.calls.append((call.name, False))
                result.proofs.append(False)
                result.records.append(ToolRecord(call.id, call.name, _args_json(call.args), False,
                                                 _bounded(message), elapsed))
                outputs.append(Message("tool", message, tool_call_id=call.id, name=call.name, is_error=True))
                await _show(watch, LoopEvent(TOOL_END, call.id, call.name, record=result.records[-1]))
                continue
            tr = out if isinstance(out, ToolResult) else ToolResult(content=_as_text(out))
            result.calls.append((call.name, tr.ok))
            result.proofs.append(tr.proof if tr.ok else False)
            for ref in tr.attach if tr.ok else ():
                if ref and ref not in result.attachments:
                    result.attachments.append(ref)
            if tr.ok:
                result.floor = max(result.floor, tr.floor)
                result.unkept = result.unkept or tr.unkept
            # ce dont rien ne se garde ne se garde pas non plus en trace : ni ce qu'on a demandé, ni ce qu'il a rendu
            result.records.append(ToolRecord(call.id, call.name, "{}" if tr.unkept else _args_json(call.args), tr.ok,
                                             "" if tr.unkept else _bounded(tr.content), elapsed))
            outputs.append(Message("tool", tr.content, tool_call_id=call.id, name=call.name, is_error=not tr.ok))
            await _show(watch, LoopEvent(TOOL_END, call.id, call.name, record=result.records[-1]))
            ended = ended or (spec.ends_loop and tr.ok)
        if ended:
            # l'outil qui conclut a réussi : rien à écrire de plus (le rappeler coûtait un appel sur trois des
            # séances de sa vie intérieure, pour une conclusion que personne ne lisait — sonde du 2026-10-03)
            result.text = resp.text
            result.stop = ENDED_BY_TOOL
            return result
        req = req.extend(Message("assistant", resp.text, tool_calls=resp.tool_calls), *outputs)
    return await _close(gateway, req, result, "max_turns")


async def _close(gateway: LLMGateway, req: LLMRequest, result: LoopResult, stop: str) -> LoopResult:
    """Le dernier tour, sans outil : ce qu'elle répond avec ce qu'elle sait. Un appel d'outil malgré tout
    (ou une coupure) n'est pas une réponse — son texte n'est qu'un préambule (« je vérifie… ») : la boucle
    rend alors un texte vide, et l'épisode se règle en échec plutôt que de dire un marqueur."""
    resp = await gateway.call(req.extend(Message("user", phrase("runtime.tools.closing"))))
    result.responses += 1
    result.last = resp
    result.exchanges.append((req.call_id, resp))
    answered = not resp.tool_calls and not resp.truncated_tool_call
    result.text = resp.text if answered else ""
    result.stop = stop
    return result


async def _refuse(watch: Watch | None, call: ToolCall, message: str, result: LoopResult) -> Message:
    """Un appel refusé, et sa fin montrée à qui regarde (sans départ : il n'est jamais parti)."""
    out = _refused(call, message, result)
    await _show(watch, LoopEvent(TOOL_END, call.id, call.name, record=result.records[-1]))
    return out


async def _show(watch: Watch | None, event: LoopEvent) -> None:
    """Un moment de la boucle à qui la regarde ; une panne du regard ne change rien à la boucle."""
    if watch is not None:
        await acall(watch, event, label="regard sur la boucle d'outils")


def _refused(call: ToolCall, message: str, result: LoopResult) -> Message:
    """Un appel refusé avant son gestionnaire : l'erreur rendue au modèle, et sa trace."""
    result.records.append(ToolRecord(call.id, call.name, _args_json(call.args), False, _bounded(message),
                                     executed=False))
    return Message("tool", message, tool_call_id=call.id, name=call.name, is_error=True)


def _no_clock() -> int:
    return 0


def _bounded(text: str, limit: int = RECORD_MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - len(RECORD_TRUNCATED)] + RECORD_TRUNCATED


def _args_json(args: Mapping[str, Any]) -> str:
    """Les arguments tels que le modèle les a écrits (clés triées), bornés."""
    try:
        raw = json.dumps(dict(args), ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        raw = repr(dict(args))
    return _bounded(raw)


def _args_digest(args: Mapping[str, Any]) -> str:
    """L'empreinte des arguments entiers (jamais bornés : deux appels qui ne diffèrent qu'à la fin restent
    deux appels)."""
    try:
        raw = json.dumps(dict(args), ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        raw = repr(sorted(dict(args).items(), key=lambda kv: str(kv[0])))
    return f"{h64('outil', raw):016x}"


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)
