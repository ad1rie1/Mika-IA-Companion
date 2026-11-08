"""Ce qui ne part plus.

- **Les échéances** : une réponse qui attend un accord trop longtemps ne part plus (elle le saura comme un refus) ;
  une réponse en file que l'extension n'a pas traitée à temps (Teams fermé), ou posée dans Teams et jamais envoyée,
  non plus — on ne répond pas en retard à une question dépassée.
- **Répondu autrement** (ADR 0199) : une réponse qui attend un accord dans une conversation où la personne du compte
  a répondu elle-même (``DraftSeen.answered`` : son message est parti du web, ou revenu dans le fil après celui
  auquel elle répondait) est refusée, avec la note ``ANSWERED`` — sinon elle partirait après la sienne.
"""

from __future__ import annotations

from typing import Any

from mika.contracts import runtime as rt
from mika.contracts import teams as c
from mika.kernel.events import Content
from mika.kernel.guards import Superseded
from mika.plugins.teams import (
    ANSWERED,
    FROM_PORT,
    PLACED,
    QUEUED,
    RECEIVED,
    SETTLED,
    TEAMS,
    WAITING,
    WRITTEN,
    TeamsState,
    decider,
)
from mika.vocab.phrasebook import phrase


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
                draft = rt.expiry_draft(phrase("approvals.no_answer"), proposal=d.proposal, capability=c.SEND,
                                        owner=c.OWNER, args_json=d.args_json or "{}", context=d.context)
                try:
                    commit = await ctx.emit(draft, guard=rt.still_pending(d.proposal), emitter=rt.OWNER)
                except Superseded:  # décidée entre-temps : rien à faire ; toute autre panne remonte, la santé la voit
                    continue
                if port is not None and not commit.deduped:  # dédoublonnée : décidée avant nous, peut-être acceptée
                    port.discard_draft(d.draft)  # elle ne partira plus : le brouillon est abandonné
            elif d.state in (QUEUED, PLACED) and d.queued_until and d.queued_until <= now:
                await ctx.emit(_expired(port, d.draft, now))


@TEAMS.process("teams.answered", wake_on=[RECEIVED, WRITTEN, rt.EFFECT_PROPOSED], lane="background",
               max_quantum_s=60, priority=60)
class Answered:
    """Ses réponses en attente d'accord auxquelles la personne du compte a répondu autrement : refusées en son nom
    (qui décide pour ce compte, ``decider``), avec la note ``ANSWERED`` ; elle le saura, comme d'un refus."""

    def next_due(self, s: TeamsState, frame: Any, last_run: int | None) -> int | None:
        return frame.now if any(d.state == WAITING and d.answered for d in s.drafts.values()) else None

    async def run(self, ctx: Any) -> None:
        port = ctx.ports.get("teams")
        for d in list(ctx.state.drafts.values()):
            if d.state != WAITING or not d.answered:
                continue
            draft = rt.EFFECT_RESOLVED.draft(
                proposal=d.proposal, approved=False, by=decider(ctx.frame, d.account), note=Content.of(ANSWERED),
                capability=c.SEND, owner=c.OWNER, args_json=d.args_json or "{}", context=d.context,
                dedupe_key=f"décision:{d.proposal}")
            try:
                commit = await ctx.emit(draft, guard=rt.still_pending(d.proposal), emitter=rt.OWNER)
            except Superseded:  # décidée entre-temps (son échéance, ou quelqu'un) : rien à faire
                continue
            if port is not None and not commit.deduped:  # dédoublonnée : décidée avant nous, peut-être acceptée
                port.discard_draft(d.draft)  # elle ne partira plus : le brouillon est abandonné


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
