"""Un appel qui attendait un accord (ADR 0064) : ce qui est montré, ce qui part, ce qui revient, ce qui expire.

- *L'aperçu* (``preview``) montre exactement ce qui partira — le service, l'outil, les arguments — et l'empreinte
  de tout cela : c'est elle que la carte (ou l'opérateur) approuve. Un outil que le serveur a changé depuis la
  demande, ou qui n'est plus servi, bloque l'accord ; une demande expirée aussi.
- *La capacité* ``mcp.call`` appelle, garde la réponse en mémoire le temps qu'elle soit journalisée, et ne rend au
  runtime qu'un résumé (le résultat d'un effet n'est pas effaçable ; ce que rend un service peut parler de quelqu'un).
- *Le retour* : quand l'appel a été exécuté, ``mcp.answered`` journalise ce qu'il a rendu comme un contenu (l'oubli
  l'atteint) — la section et l'initiative due (``prompt``) le lui disent.
- *L'expiration* : une carte sans réponse à temps (10 min dans le chat, un jour pour l'opérateur) est refusée au nom
  du délai — elle le saura comme un refus.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from mika.contracts import mcp as c
from mika.contracts import runtime as rt
from mika.kernel.events import Content
from mika.kernel.guards import Guard
from mika.kernel.operate import Preview
from mika.plugins.mcp import ANSWER_KEPT, EXPIRER, MCP, WAITING, McpState, call_digest
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity


def preview(args: Mapping[str, Any], ports: Mapping[str, Any]) -> Preview:
    """Exactement ce qui partirait, et ce qui l'empêcherait de partir tel quel."""
    server, remote = str(args.get("server") or ""), str(args.get("remote") or "")
    shown = json.dumps(args.get("args") or {}, ensure_ascii=False, indent=1, sort_keys=True)
    text = f"Service : {server}\nOutil : {remote}\nCe qui partira :\n{shown}"
    digest = call_digest(args)
    port, frame_of = ports.get("mcp"), ports.get("frame")
    blocked = ""
    if port is None:
        blocked = "les outils extérieurs ne sont pas branchés"
    else:
        tool = next((t for t in port.offered() if t.server == server and t.remote == remote), None)
        if tool is None:
            blocked = "cet outil n'est plus servi (serveur injoignable, outil désactivé ou suspendu)"
        elif tool.fingerprint != args.get("fingerprint"):
            blocked = "le serveur a changé cet outil depuis la demande"
    expires = int(args.get(rt.EXPIRES) or 0)
    if not blocked and expires and frame_of is not None and frame_of().now > expires:
        blocked = "la demande a expiré"
    return Preview(text, digest, blocked)


@MCP.capability("call", description="Appeler un outil d'un service extérieur (après accord).", preview=preview)
async def call(args: Mapping[str, Any], context: str, ports: Mapping[str, Any]) -> tuple[bool, str]:
    port = ports.get("mcp")
    if port is None:
        return False, phrase("mcp.unavailable")
    result = await port.call(str(args.get("server") or ""), str(args.get("remote") or ""),
                             dict(args.get("args") or {}))
    port.keep(str(args.get("request") or ""), result.text)
    return result.ok, f"{'rendu' if result.ok else 'échec'} ({len(result.text)} caractères)"


@MCP.effect(rt.EFFECT_EXECUTED)
async def _came_back(ev: Any, ports: Mapping[str, Any]) -> list[Any] | None:
    """L'appel est fait : ce qu'il a rendu devient un contenu journalisé (effaçable), pour qu'elle le dise."""
    frame_of = ports.get("frame")
    if frame_of is None:
        return None
    req = frame_of().state(MCP.name).requests.get(ev.data.proposal)
    if req is None:
        return None
    port = ports.get("mcp")
    text = port.take(req.request) if port is not None else None
    if text is None:
        text = phrase("mcp.lost") if ev.data.ok else ev.data.result
    return [c.ANSWERED.draft(proposal=req.proposal, ok=ev.data.ok,
                             text=Content.of(text[:ANSWER_KEPT], level=int(Sensitivity.PERSONAL)),
                             about=(req.target,) if req.target else (), dedupe_key=f"mcp-rendu:{req.proposal}")]


def _still_pending(proposal: int) -> Guard:
    """Le refus au nom du délai ne vaut que si personne n'a décidé entre-temps."""
    return Guard("encore en attente", reads=(rt.PENDING_EFFECTS,),
                 predicate=lambda view, n=proposal: any(p.proposal == n for p in view.get(rt.PENDING_EFFECTS)))


@MCP.process("mcp.expire", wake_on=[rt.EFFECT_PROPOSED, rt.EFFECT_RESOLVED], lane="background", max_quantum_s=60,
             priority=60)
class Expire:
    """Une demande sans accord à temps est refusée au nom du délai (elle le saura comme un refus)."""

    def next_due(self, s: McpState, frame: Any, last_run: int | None) -> int | None:
        waiting = [r.expires for r in s.requests.values() if r.status == WAITING and r.expires]
        return max(frame.now, min(waiting)) if waiting else None

    async def run(self, ctx: Any) -> None:
        now = ctx.frame.now
        for r in [r for r in ctx.state.requests.values() if r.status == WAITING and r.expires and r.expires <= now]:
            draft = rt.EFFECT_RESOLVED.draft(
                proposal=r.proposal, approved=False, by=EXPIRER, note=Content.of("pas d'accord dans le délai"),
                capability=c.CALL, owner=c.OWNER, args_json=r.args_json, context=r.context,
                about=(r.target,) if r.target else (), dedupe_key=f"décision:{r.proposal}")
            try:
                await ctx.emit(draft, guard=_still_pending(r.proposal), emitter=rt.OWNER)
            except Exception:  # noqa: BLE001 — décidée entre-temps : rien à faire
                continue

