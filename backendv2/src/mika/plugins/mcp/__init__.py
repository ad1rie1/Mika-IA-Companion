"""Le plugin ``mcp`` : les outils venus d'ailleurs (ADR 0064).

Rien ici ne parle à un serveur : le port ``mcp`` le fait. La faculté dit ce qu'est chaque outil **pour elle** — son
nom, son lot (``mcp.<serveur>``, décrit par ce que l'opérateur a écrit : à quoi il sert, quand s'en servir), pour
qui, quand — et ce qu'elle lit de sa réponse : une donnée venue d'ailleurs, désamorcée, citée, bornée.

Un outil sert selon les lignes d'accès de son service (ADR 0131), lues de haut en bas comme les règles d'un
pare-feu : la première qui le concerne (qui est en face, quand, ses outils) dit ce qu'elle en fait et ce qu'elle en
garde ; aucune, c'est la ligne par défaut. Jamais dans un salon ni avec une inconnue. Ce qu'elle en fait, décidé à
l'appel :

- *seule* : l'appel part dans la boucle, elle lit la réponse aussitôt ;
- *sur accord* (``carte`` : de la personne en face ; ``toi`` : de sa propriétaire quand c'est elle en face ; sans
  personne pour accepter, de l'opérateur) : l'outil **propose** l'appel (``mcp.call``, un effet) et rend la main —
  rien ne sort tant qu'on n'a pas accepté ce qui est montré. Exécuté, ce que le service a rendu revient comme un
  contenu (``mcp.answered``) qu'elle dit à la personne : dans sa réponse suivante si la personne a écrit, sinon par
  une initiative due (``calls``, ``prompt``). Refusé ou expiré, elle le sait aussi.

Ce qu'elle garde de ce qu'un service rend (``keep``) suit tout ce qui en sort : la réponse porte son plancher
(``ToolResult.floor``, ``unkept``), et la mémoire le respecte.

Elle relance de temps en temps les serveurs (ce qu'ils proposent a pu changer ; un serveur en panne a pu revenir) et
journalise leur état quand il change (``mcp.status`` : des noms et des nombres, pour la console).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import mcp as c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.codec import canonical_json
from mika.kernel.events import Content, Payload
from mika.kernel.faculty import Faculty, ToolResult, ToolSpec
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.ports.preprocess import cite, inert
from mika.vocab.access import KINDS_OF, can_approve, first

# où elle s'en servirait, qui une ligne désigne, quand elle vaut : la règle partagée (ADR 0131, 0133)
from mika.vocab.access import moment as moment
from mika.vocab.access import situation as situation
from mika.vocab.episodes import CONVERSATIONAL, WORKING, is_work_target
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity

FAMILY = "mcp"
#: quand une famille d'épisodes d'un serveur sert (``vocab.access``) ; une tâche prend les lots qu'elle choisit — un
#: brouillon de mail ou de Teams n'en prend aucun
EPISODES: Mapping[str, frozenset[str]] = KINDS_OF
#: les serveurs sont rejoints et relistés à ce rythme (ce qu'ils proposent a pu changer)
WATCH_EVERY = 15 * MINUTE
FIRST_WATCH = MINUTE
RULE = ("seulement tant que son serveur répond et que l'outil est celui qui a été approuvé ; ce qu'elle y met part "
        "de la machine ; selon qui lui parle, l'appel part aussitôt ou attend un accord")
#: ce qu'on tire de ce qu'un service a rendu ne se dit jamais en dessous de ce plancher (ADR 0128) ; « rien » : rien
#: ne s'en garde
FLOORS = {"public": int(Sensitivity.NONE), "perso": int(Sensitivity.NONE), "prive": int(Sensitivity.CONFIDENCE),
          "rien": int(Sensitivity.CONFIDENCE)}
#: la sensibilité d'une réponse acceptée, journalisée pour qu'elle la dise
ANSWER_LEVELS = {"public": int(Sensitivity.ANODYNE), "perso": int(Sensitivity.PERSONAL),
                 "prive": int(Sensitivity.CONFIDENCE), "rien": int(Sensitivity.CONFIDENCE)}
#: ce qu'un accord peut être (ADR 0128) : ``non`` retire l'outil
NO, ALONE, CARD, OWNER_OK = "non", "seule", "carte", "toi"
#: une carte d'accord dans la conversation vaut tant ; un accord de l'opérateur, tant
CARD_TTL = 10 * MINUTE
OPERATOR_TTL = DAY
#: ce qu'un service a rendu n'est plus annoncé passé ce délai (il reste dans la console)
TOO_LATE = 6 * HOUR
#: ce qu'on garde des demandes (les plus anciennes s'effacent)
REQUESTS_KEPT = 100
#: ce qu'on garde d'une réponse (le contenu journalisé)
ANSWER_KEPT = 8000
#: qui signe un refus faute d'accord à temps
EXPIRER = "délai"
#: l'état d'une demande
WAITING, APPROVED, REFUSED, EXPIRED, ANSWERED, FAILED = "attend", "acceptée", "refusée", "expirée", "rendue", "ratée"
FINAL = frozenset({REFUSED, EXPIRED, ANSWERED, FAILED})
PROVENANCE = "mcp:"


class ServerSeen(Payload):
    """Ce que la console doit pouvoir signaler d'un serveur sans le joindre : son état, ce qui attend l'opérateur."""

    name: str
    state: str
    #: des outils à regarder (nouveaux) ou à réapprouver (changés)
    review: int = 0
    #: les outils qu'elle a en main de lui
    offered: int = 0


class Status(Payload):
    """L'état des serveurs, journalisé quand il change (jamais un contenu : des noms et des nombres)."""

    servers: tuple[ServerSeen, ...] = ()


@dataclass(frozen=True, slots=True)
class Request:
    """Un appel qui demandait un accord, de la proposition à ce qu'elle en a dit."""

    proposal: int
    server: str
    remote: str
    #: l'adresse de la personne de l'épisode (à qui le dire) ; vide en travail
    target: str
    approval: str
    at: int
    expires: int
    request: str
    args_json: str = "{}"
    context: str = ""
    #: ce qu'elle garde de ce que le service rendra (``keep`` de la ligne d'accès qui a permis la demande)
    keep: str = ""
    status: str = WAITING
    by: str = ""
    done_at: int = 0
    text_ref: str = ""
    told: bool = False


@dataclass(frozen=True, slots=True)
class McpState:
    servers: tuple[ServerSeen, ...] = ()
    requests: FrozenDict[int, Request] = field(default_factory=FrozenDict)


MCP = Faculty("mcp", state=McpState, init=lambda p: McpState())
MCP.declare(*c.ALL)
STATUS = MCP.event("status", Status)


@MCP.reducer(STATUS)
def _status(s: McpState, e: Any, cx: Any) -> McpState:
    return replace(s, servers=tuple(e.data.servers))


def _keep(requests: FrozenDict[int, Request]) -> FrozenDict[int, Request]:
    while len(requests) > REQUESTS_KEPT:
        requests = requests.delete(min(requests))
    return requests


@MCP.reducer(rt.EFFECT_PROPOSED)
def _proposed(s: McpState, e: Any, cx: Any) -> McpState:
    d = e.data
    if d.capability != c.CALL:
        return s
    try:
        args = json.loads(d.args_json or "{}")
    except ValueError:
        args = {}
    req = Request(proposal=e.seq, server=str(args.get("server") or ""), remote=str(args.get("remote") or ""),
                  target=str(args.get("target") or ""), approval=str(args.get("approval") or ""), at=e.at,
                  expires=int(args.get(rt.EXPIRES) or 0), request=str(args.get("request") or ""),
                  args_json=d.args_json, context=d.context, keep=str(args.get("keep") or ""),
                  status=WAITING if d.approval else APPROVED)
    return replace(s, requests=_keep(s.requests.set(e.seq, req)))


@MCP.reducer(rt.EFFECT_RESOLVED)
def _resolved(s: McpState, e: Any, cx: Any) -> McpState:
    d = e.data
    req = s.requests.get(d.proposal)
    if req is None:
        return s
    status = APPROVED if d.approved else (EXPIRED if d.by == EXPIRER else REFUSED)
    return replace(s, requests=s.requests.set(d.proposal, replace(
        req, status=status, by=d.by, done_at=0 if d.approved else e.at)))


@MCP.reducer(rt.EFFECT_EXECUTED)
def _executed(s: McpState, e: Any, cx: Any) -> McpState:
    d = e.data
    req = s.requests.get(d.proposal)
    if req is None or d.ok:
        return s  # réussi : ``mcp.answered`` suit, avec ce qu'il a rendu
    return replace(s, requests=s.requests.set(d.proposal, replace(req, status=FAILED, done_at=e.at)))


@MCP.reducer(c.ANSWERED)
def _answered(s: McpState, e: Any, cx: Any) -> McpState:
    d = e.data
    req = s.requests.get(d.proposal)
    if req is None:
        return s
    return replace(s, requests=s.requests.set(d.proposal, replace(
        req, status=ANSWERED if d.ok else FAILED, done_at=e.at, text_ref=d.text.ref or "")))


@MCP.reducer(rt.UTTERANCE)
def _uttered(s: McpState, e: Any, cx: Any) -> McpState:
    """Ce que son prompt lui montrait d'une réponse (``mcp:<proposition>``) quand elle a parlé : c'est dit."""
    d = e.data
    if not d.visible:
        return s
    requests = s.requests
    for p in d.provenance:
        if not p.startswith(PROVENANCE):
            continue
        try:
            n = int(p[len(PROVENANCE):])
        except ValueError:
            continue
        req = requests.get(n)
        if req is not None and req.status in FINAL and not req.told:
            requests = requests.set(n, replace(req, told=True))
    return s if requests is s.requests else replace(s, requests=requests)


@MCP.fact(c.UNTOLD)
def _untold(s: McpState, cx: Any, proposal: int) -> bool:
    req = s.requests.get(proposal)
    return req is not None and req.status in FINAL and not req.told


def summary(port: Any) -> tuple[ServerSeen, ...]:
    """Ce que le port dit de ses serveurs, réduit à ce que la console signale."""
    offered: dict[str, int] = {}
    for t in port.offered():
        offered[t.server] = offered.get(t.server, 0) + 1
    return tuple(ServerSeen(name=st.name, state=st.state, review=len(st.new) + len(st.changed),
                            offered=offered.get(st.name, 0)) for st in port.statuses())


def status_drafts(s: McpState, port: Any) -> tuple[Any, ...]:
    """Le brouillon de ``mcp.status`` s'il a changé (rien sinon : le journal n'écrit pas deux fois la même chose)."""
    now = summary(port)
    return (STATUS.draft(servers=now),) if now != s.servers else ()


class ExternalArgs(BaseModel):
    """Les arguments d'un outil venu d'ailleurs : son schéma les vérifie (``ToolSpec.schema``), pas ce modèle."""

    model_config = ConfigDict(extra="allow")


def access_for(tool: Any, audience: Any, kind: str, close: Any = None) -> tuple[str, str]:
    """Ce qu'elle fait d'un outil devant cette audience, dans cette sorte d'épisode, et ce qu'elle garde de ce qu'il
    rend : la première de ses lignes d'accès qui les désigne (``close`` : qui est proche d'elle), sinon la ligne par
    défaut (ADR 0131, 0133). ``non`` jamais dans un salon, avec une inconnue, ni sans personne."""
    line = first(tool.access, tool.default, audience, kind, close=close)
    return (line.level(tool.nature), line.keep) if line is not None else (NO, "rien")


def bundle_line(tool: Any) -> str:
    """La ligne de son catalogue pour un serveur : à quoi il sert, quand s'en servir, d'où il vient."""
    where = phrase("mcp.bundle.local") if tool.local else phrase("mcp.bundle.remote")
    when = phrase("mcp.bundle.when", when=tool.when_to_use) if tool.when_to_use else ""
    return phrase("mcp.bundle.line", where=where, when=when, purpose=tool.purpose)


def label(server: str) -> str:
    return f"« {inert(server, 40)} »"


def call_digest(args: Mapping[str, Any]) -> str:
    """L'empreinte de ce qui partirait : le serveur, l'outil approuvé (son empreinte), ses arguments, qui décide.
    C'est elle que la carte (ou l'opérateur) approuve : un argument changé n'est pas le même accord."""
    pinned = {k: args.get(k) for k in ("server", "remote", "fingerprint", "args", rt.DECIDER)}
    return hashlib.sha256(canonical_json(pinned).encode()).hexdigest()[:32]


#: ce qu'une consultation garde de sa réponse, pour la relecture de la nuit (ADR 0085)
CONSULTED_MAX = 2500


async def _call(t: Any, args: ExternalArgs, ctx: Any, keep: str) -> ToolResult:
    """L'appel part dans la boucle : elle lit la réponse aussitôt, avec ce qu'elle vaut (``keep``)."""
    port = ctx.ports.get("mcp")
    data = args.model_dump()
    result = await port.call(t.server, t.remote, data)
    if not result.ok:
        return ToolResult(ok=False, content=phrase("mcp.tools.failed", server=label(t.server),
                                                   text=inert(result.text, 600)))
    ep = ctx.frame.episode
    # ce qu'elle lit (une recherche, une page) se garde comme une lecture, relue la nuit (ADR 0085). En
    # conversation, c'est lu pour quelqu'un (ADR 0110) : ce qu'on cherchait (les arguments) est à lui et ne se
    # garde pas ; ce qu'elle a lu porte son nom, et la nuit n'en retient que les nouvelles et les faits publics
    asked_by = (ep.target or "") if ep is not None and ep.kind in CONVERSATIONAL else ""
    reads_world = keep == "public" and t.nature == "lecture"
    if reads_world and ep is not None and result.text and (ep.kind in WORKING or asked_by):
        sought = inert(json.dumps(data, ensure_ascii=False, sort_keys=True), 200)
        await ctx.emit(c.CONSULTED.draft(
            source=f"mcp:{t.server}"[:200],
            ref=f"{t.remote}:{call_digest({'server': t.server, 'remote': t.remote, 'args': data})}",
            title=Content.of(inert(t.remote if asked_by else f"{t.remote} {sought}", 250),
                             level=int(Sensitivity.ANODYNE)),
            excerpt=Content.of(inert(result.text, CONSULTED_MAX), level=int(Sensitivity.ANODYNE)), depth="page",
            asked_by=asked_by[:200]))
    # ce qu'elle lit pour quelqu'un se raconte : la consigne de son prompt ne suffisait pas (2026-10-14 : « c'est
    # la page de flash info de RTL, mise à jour il y a une demi-heure […] je n'ai lu que le début de la page »)
    told = "\n" + phrase("mcp.tools.read_aloud") if reads_world and asked_by and result.text else ""
    return ToolResult(content=phrase("mcp.tools.answered", server=label(t.server)) + "\n"
                              + (cite(result.text, t.max_result_chars) or phrase("mcp.tools.nothing")) + told,
                      floor=FLOORS.get(keep, 0), unkept=keep == "rien")


async def _ask(t: Any, level: str, args: ExternalArgs, ctx: Any, keep: str) -> ToolResult:
    """Un appel qui demande un accord : il propose l'appel (rien ne part) et le dit. La carte va à la personne en
    face (``carte``), ou à sa propriétaire quand c'est elle en face (``toi``) ; sinon, l'opérateur décide."""
    ep = ctx.frame.episode
    audience = ctx.frame.audience
    # au travail, la cible est un but ou un projet, pas une personne : rien à lui dire, l'opérateur décide
    target = (ep.target if ep is not None else None) or ""
    target = "" if is_work_target(target) else target
    in_chat = bool(target) and can_approve(audience) and (level == CARD or bool(audience.owner))
    data = args.model_dump()
    payload: dict[str, Any] = {
        "server": t.server, "remote": t.remote, "args": data, "fingerprint": t.fingerprint,
        "request": f"{ctx.episode_id}:{ctx.call_key or ctx.call_id}", "target": target,
        "approval": "conversation" if in_chat else "operateur", "keep": keep,
        rt.EXPIRES: ctx.frame.now + (CARD_TTL if in_chat else OPERATOR_TTL)}
    if in_chat:
        payload[rt.DECIDER] = target
    payload["_apercu"] = call_digest(payload)
    shown = inert(json.dumps(data, ensure_ascii=False, sort_keys=True), 300)
    await ctx.propose(rt.EFFECT_PROPOSED.draft(
        capability=c.CALL, owner=c.OWNER, args_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        summary=Content.of(f"Appeler « {inert(t.remote, 80)} » ({inert(t.server, 40)}) : {shown}"[:400],
                           level=int(Sensitivity.PERSONAL)),
        approval=True, context=f"mcp:{t.server}", about=(target,) if target else ()))
    who = phrase("mcp.tools.in_chat") if in_chat else phrase("mcp.tools.operator")
    return ToolResult(content=phrase("mcp.tools.asked", who=who))


def _handler(t: Any) -> Any:
    async def handler(args: ExternalArgs, ctx: Any) -> ToolResult:
        if ctx.ports.get("mcp") is None:
            return ToolResult(ok=False, content=phrase("mcp.unavailable"))
        ep = ctx.frame.episode
        level, keep = access_for(t, ctx.frame.audience, ep.kind if ep is not None else "", social_c.is_close(ctx.frame))
        if level == NO:
            return ToolResult(ok=False, content=phrase("mcp.tools.closed"))
        if level == ALONE:
            return await _call(t, args, ctx, keep)
        return await _ask(t, level, args, ctx, keep)

    return handler


def _gate(t: Any) -> Any:
    def served(audience: Any, kind: str, frame: Any = None) -> bool:
        """Seulement quand une ligne d'accès de son service le laisse servir devant cette personne, à ce moment-là.

        ADR 0131 : la première ligne qui la désigne décide, sinon la ligne par défaut ; jamais dans un salon ni avec
        une inconnue."""
        close = social_c.is_close(frame) if frame is not None else None
        return access_for(t, audience, kind, close)[0] != NO

    return served


def specs_of(offered: Sequence[Any]) -> tuple[list[ToolSpec], dict[str, str]]:
    """Ses outils et leurs lots, d'après l'instantané approuvé du port."""
    tools: list[ToolSpec] = []
    bundles: dict[str, str] = {}
    for t in offered:
        episodes = frozenset().union(*(EPISODES.get(e, frozenset()) for e in t.episodes))
        if not episodes:
            continue
        bundle = f"{FAMILY}.{t.server}"
        bundles[bundle] = bundle_line(t)
        tools.append(ToolSpec(
            MCP.name, t.name, inert(t.description, 1024) or phrase("mcp.tool_fallback", server=t.server), ExternalArgs,
            _handler(t), bundle, episodes, max_calls_per_episode=t.max_calls, fits=_gate(t), rule=RULE,
            schema=dict(t.schema), in_hand=t.in_hand, outside=True))
    return tools, bundles


@MCP.tool_source(FAMILY)
def _source(ports: Mapping[str, Any]) -> tuple[list[ToolSpec], dict[str, str]]:
    port = ports.get("mcp")
    if port is None:
        return [], {}
    return specs_of(port.offered())


@MCP.process("mcp.watch", lane="background", max_quantum_s=300, priority=80)
class Watch:
    """Rejoindre et relister les serveurs actifs : un outil changé est suspendu, un serveur revenu reprend."""

    def __init__(self) -> None:
        #: le premier passage, fixé à la première lecture : « maintenant + une minute » relu à chaque réveil de
        #: l'ordonnanceur reculait sans cesse — il ne passait jamais, et un serveur tombé au démarrage ne revenait
        #: pas (sonde du 2026-10-13)
        self.first: int | None = None

    def next_due(self, s: McpState, frame: Frame, last_run: int | None) -> int | None:
        if last_run is None:  # le premier passage peu après le démarrage : les serveurs ont été joints entre-temps
            if self.first is None:
                self.first = frame.now + FIRST_WATCH
            return self.first
        return max(frame.now, last_run + WATCH_EVERY)

    async def run(self, ctx: Any) -> None:
        port = ctx.ports.get("mcp")
        if port is None:
            return
        await port.refresh()
        drafts = status_drafts(ctx.state, port)
        if drafts:
            await ctx.emit(*drafts)


from mika.plugins.mcp import calls as calls  # noqa: E402
from mika.plugins.mcp import console as console  # noqa: E402
from mika.plugins.mcp import prompt as prompt  # noqa: E402
