"""L'échéance (ADR 0120) : une réponse proposée sur le téléphone sans geste à temps ne part plus — la notification
disparaît d'elle-même au même moment (``exp``). On ne répond pas en retard à une conversation qui a avancé."""

from __future__ import annotations

from typing import Any

from mika.contracts import phone as c
from mika.contracts import runtime as rt
from mika.plugins.phone import PHONE, UNDER_WAY, PhoneState


@PHONE.process("phone.expire", wake_on=[c.DRAFTED, c.SETTLED, rt.EFFECT_EXECUTED], lane="background",
               max_quantum_s=60, priority=60)
class Expire:
    def next_due(self, s: PhoneState, frame: Any, last_run: int | None) -> int | None:
        due = [o.expires for o in s.offers.values() if o.state in UNDER_WAY and o.expires]
        return max(frame.now, min(due)) if due else None

    async def run(self, ctx: Any) -> None:
        now = ctx.frame.now
        late = [o for o in ctx.state.offers.values() if o.state in UNDER_WAY and o.expires and o.expires <= now]
        if late:
            await ctx.emit(*(c.SETTLED.draft(draft=o.seq, result=c.EXPIRED, dedupe_key=f"phone-echeance:{o.seq}")
                             for o in late))
