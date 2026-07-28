"""Read layer for conscience-owned state.

Companion to ``memory.read`` — same rule, split by which app owns the model.
Ruminations belong to the conscience, so the query lives here rather than in
a general "inner state" bag that would have to import every app.

One question, two callers with different appetites: the prompt takes the top
3 above an intensity floor (a thought too faint to notice should not be
narrated as one), the InnerLifePanel takes the top 5 unfiltered (a fading
thought is still worth *showing*). Those are parameters of one query, not a
reason for two implementations.
"""

from __future__ import annotations

from asgiref.sync import sync_to_async


async def active_ruminations(*, limit: int = 5, min_intensity: float = 0.0) -> list:
    """Unresolved thoughts still on Mika's mind, strongest first."""
    from conscience.models import Rumination

    def _query():
        qs = Rumination.objects.filter(status="active")
        if min_intensity > 0:
            qs = qs.filter(intensity__gte=min_intensity)
        return list(qs.order_by("-intensity")[:limit])

    return await sync_to_async(_query)()
