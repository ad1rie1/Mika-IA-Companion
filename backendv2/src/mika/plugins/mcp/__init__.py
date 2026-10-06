"""Le plugin ``mcp`` : les outils venus d'ailleurs (ADR 0064).

Rien ici ne parle à un serveur : le port ``mcp`` le fait. La faculté dit ce qu'est chaque outil **pour elle** — son
nom, son lot (``mcp.<serveur>``, décrit par ce que l'opérateur a écrit : à quoi il sert, quand s'en servir), pour
qui, quand — et ce qu'elle lit de sa réponse : une donnée venue d'ailleurs, désamorcée, citée, bornée.

Deux sortes d'outils, selon l'accord que l'opérateur a choisi :

- *sans accord* : l'appel part dans la boucle, elle lit la réponse aussitôt ;
- *avec accord* (de la personne, dans la conversation ; ou de l'opérateur) : l'outil **propose** l'appel
  (``mcp.call``, un effet) et rend la main — rien ne sort tant qu'on n'a pas accepté ce qui est montré. Exécuté,
  ce que le service a rendu revient comme un contenu (``mcp.answered``) qu'elle dit à la personne : dans sa réponse
  suivante si la personne a écrit, sinon par une initiative due (``calls``, ``prompt``). Refusé ou expiré, elle le
  sait aussi.

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
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.codec import canonical_json
from mika.kernel.events import Content, Payload
from mika.kernel.faculty import Faculty, ToolResult, ToolSpec
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.ports.preprocess import cite, inert
from mika.vocab.episodes import Kind
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import ChannelTrust, Sensitivity

FAMILY = "mcp"
#: quand une famille d'épisodes d'un serveur sert
EPISODES: Mapping[str, frozenset[str]] = {
    "conversation": frozenset({Kind.REPLY}),
    "initiative": frozenset({Kind.INITIATIVE}),
    "travail": frozenset({Kind.STEP, Kind.WORK, Kind.JOB, Kind.WAKE, Kind.WAKE_JOB}),
}
#: les serveurs sont rejoints et relistés à ce rythme (ce qu'ils proposent a pu changer)
WATCH_EVERY = 15 * MINUTE
FIRST_WATCH = MINUTE
RULE = ("seulement tant que son serveur répond et que l'outil est celui qui a été approuvé ; ce qu'elle y met part "
        "de la machine")
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
                  args_json=d.args_json, context=d.context, status=WAITING if d.approval else APPROVED)
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


def for_accounts(audience: Any) -> bool:
    """En tête-à-tête, à sa propriétaire ou à une personne authentifiée — jamais dans un salon ; et quand elle
    travaille (personne n'écoute)."""
    if audience is None:
        return False
    if audience.trust == ChannelTrust.INTERNAL.value:
        return True
    return can_approve(audience)


def can_approve(audience: Any) -> bool:
    """Quelqu'un en face qui peut accepter une carte : en tête-à-tête, sa propriétaire ou une personne
    authentifiée — jamais dans un salon, jamais personne."""
    if audience is None or not audience.persons or audience.public or audience.room:
        return False
    return bool(audience.owner) or audience.trust == ChannelTrust.AUTHENTICATED.value


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


def _direct(server: str, remote: str, limit: int) -> Any:
    async def handler(args: ExternalArgs, ctx: Any) -> ToolResult:
        port = ctx.ports.get("mcp")
        if port is None:
            return ToolResult(ok=False, content=phrase("mcp.unavailable"))
        result = await port.call(server, remote, args.model_dump())
        if not result.ok:
            return ToolResult(ok=False, content=phrase("mcp.tools.failed", server=label(server),
                                                       text=inert(result.text, 600)))
        return ToolResult(content=phrase("mcp.tools.answered", server=label(server)) + "\n"
                                  + (cite(result.text, limit) or phrase("mcp.tools.nothing")))

    return handler


def _asker(t: Any) -> Any:
    """Un outil qui demande un accord : il propose l'appel (rien ne part) et le dit."""
    in_chat = t.approval == "conversation"

    async def handler(args: ExternalArgs, ctx: Any) -> ToolResult:
        if ctx.ports.get("mcp") is None:
            return ToolResult(ok=False, content=phrase("mcp.unavailable"))
        ep = ctx.frame.episode
        target = (ep.target if ep is not None else None) or ""
        if in_chat and not target:
            return ToolResult(ok=False, content=phrase("mcp.tools.nobody"))
        data = args.model_dump()
        payload: dict[str, Any] = {
            "server": t.server, "remote": t.remote, "args": data, "fingerprint": t.fingerprint,
            "request": f"{ctx.episode_id}:{ctx.call_key or ctx.call_id}", "target": target, "approval": t.approval,
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

    return handler


def specs_of(offered: Sequence[Any]) -> tuple[list[ToolSpec], dict[str, str]]:
    """Ses outils et leurs lots, d'après l'instantané approuvé du port."""
    tools: list[ToolSpec] = []
    bundles: dict[str, str] = {}
    for t in offered:
        episodes = frozenset().union(*(EPISODES.get(e, frozenset()) for e in t.episodes))
        when = None if t.audience != "comptes" else for_accounts
        if t.approval == "conversation":
            episodes &= EPISODES["conversation"]  # quelqu'un en face pour accepter : en répondant seulement
            when = can_approve
        if not episodes:
            continue
        bundle = f"{FAMILY}.{t.server}"
        bundles[bundle] = bundle_line(t)
        handler = _direct(t.server, t.remote, t.max_result_chars) if t.approval == "aucun" else _asker(t)
        rule = RULE if t.approval == "aucun" else (
            f"{RULE} ; l'appel ne part qu'après l'accord "
            + ("de la personne, dans la conversation" if t.approval == "conversation" else "de l'opérateur"))
        tools.append(ToolSpec(
            MCP.name, t.name, inert(t.description, 1024) or phrase("mcp.tool_fallback", server=t.server), ExternalArgs,
            handler, bundle,
            episodes, max_calls_per_episode=t.max_calls, owner_only=t.audience != "comptes", when=when, rule=rule,
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

    def next_due(self, s: McpState, frame: Frame, last_run: int | None) -> int | None:
        if last_run is None:  # le premier passage peu après le démarrage : les serveurs ont été joints entre-temps
            return frame.now + FIRST_WATCH
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
