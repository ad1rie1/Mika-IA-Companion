"""Les échéances : une réponse qui attend un accord trop longtemps ne part plus (elle le saura comme un refus) ; une
réponse en file que l'extension n'a pas traitée à temps (Teams fermé), ou posée dans Teams et jamais envoyée, non
plus — on ne répond pas en retard à une question dépassée."""

from __future__ import annotations

from typing import Any

from mika.contracts import runtime as rt
from mika.contracts import teams as c
from mika.kernel.events import Content
from mika.kernel.guards import Guard
from mika.plugins.teams import EXPIRER, FROM_PORT, PLACED, QUEUED, SETTLED, TEAMS, WAITING, TeamsState


def _still_pending(proposal: int) -> Guard:
    """Le refus au nom du délai ne vaut que si personne n'a décidé entre-temps."""
    return Guard("encore en attente", reads=(rt.PENDING_EFFECTS,),
                 predicate=lambda view, n=proposal: any(p.proposal == n for p in view.get(rt.PENDING_EFFECTS)))


@TEAMS.process("teams.expire", wake_on=[rt.EFFECT_PROPOSED, rt.EFFECT_RESOLVED, rt.EFFECT_EXECUTED, SETTLED],
               lane="background", max_quantum_s=60, priority=60)
class Expire:
    def next_due(self, s: TeamsState, frame: Any, last_run: int | None) -> int | None:
        due = [d.expires for d in s.drafts.values() if d.state == WAITING and d.expires]
        due += [d.queued_until for d in s.drafts.values() if d.state in (QUEUED, PLACED) and d.queued_until]
        return max(frame.now, min(due)) if due else None

    async def run(self, ctx: Any) -> None:
        now = ctx.frame.now
        port = ctx.ports.get("teams")
        for d in list(ctx.state.drafts.values()):
            if d.state == WAITING and d.expires and d.expires <= now:
                draft = rt.EFFECT_RESOLVED.draft(
                    proposal=d.proposal, approved=False, by=EXPIRER, note=Content.of("pas d'accord dans le délai"),
                    capability=c.SEND, owner=c.OWNER, args_json=d.args_json or "{}", context=d.context,
                    dedupe_key=f"décision:{d.proposal}")
                try:
                    await ctx.emit(draft, guard=_still_pending(d.proposal), emitter=rt.OWNER)
                except Exception:  # noqa: BLE001 — décidée entre-temps : rien à faire
                    continue
                if port is not None:
                    port.discard_draft(d.draft)  # elle ne partira plus : le brouillon est abandonné
            elif d.state in (QUEUED, PLACED) and d.queued_until and d.queued_until <= now:
                await ctx.emit(_expired(port, d.draft, now))


def _expired(port: Any, draft_id: str, now: int) -> Any:
    """L'échéance d'une réponse en file : ce que l'adaptateur en dit (déjà réglée sans qu'on le sache : son état à
    lui ; perdue : un échec) — jamais rien, sinon l'échéance repasserait sans fin."""
    done = port.settle(draft_id, "expired", now=now)[1] if port is not None else None
    if done is None:
        found = port.draft(draft_id) if port is not None else None
        if found is not None and found.state in FROM_PORT:
            return SETTLED.draft(draft=draft_id, state=found.state, edited=found.edited, reason=found.reason,
                                 dedupe_key=f"echeance:{draft_id}")
        return SETTLED.draft(draft=draft_id, state="echec", reason="cette réponse n'est plus dans la file",
                             dedupe_key=f"echeance:{draft_id}")
    return SETTLED.draft(draft=draft_id, state=done.state, reason=done.reason, dedupe_key=f"echeance:{draft_id}")
