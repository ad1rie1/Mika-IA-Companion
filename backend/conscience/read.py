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

from datetime import datetime

from asgiref.sync import sync_to_async
from django.conf import settings


def debut_du_jour_local() -> datetime:
    """Minuit, à l'horloge à laquelle le reste du moteur date ses journées.

    `timezone.now().replace(hour=0, …)` rend **minuit UTC** sous `USE_TZ=True`
    — deux heures d'écart l'été à Paris. `_introspect` comptait donc les actes
    d'une journée commençant à 02 h locales : une initiative prise entre minuit
    et 02 h était imputée à la veille, puis jamais décomptée du jour qui
    s'ouvrait, si bien que le frein quotidien (`acts_today >= 5`) et le
    compteur affiché ne parlaient pas du même jour que tout le reste.

    Or `scoring.check_time_trigger` et `memory.sleep` datent l'un et l'autre
    depuis `datetime.now()` naïf local. Une seule horloge, et c'est celle-là.

    Ce n'est pas une requête, et cette couche n'en héberge d'ordinaire pas
    d'autres — mais c'est bien une question de lecture (« quand commence
    aujourd'hui ? ») dont trois appelants ont besoin de la *même* réponse ;
    la garder dans `engine.py` en referait une arithmétique locale, ce qui est
    exactement la forme du bug.

    Le retour est *aware* parce qu'il borne `created_at` (`auto_now_add`,
    stocké aware sous `USE_TZ=True`) : `.astimezone()` sans argument attache
    le décalage local du système, celui-là même que `datetime.now()` a lu.
    """
    minuit = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return minuit.astimezone() if settings.USE_TZ else minuit


async def active_ruminations(*, limit: int = 5, min_intensity: float = 0.0) -> list:
    """Unresolved thoughts still on Mika's mind, strongest first."""
    from conscience.models import Rumination

    def _query():
        qs = Rumination.objects.filter(status="active")
        if min_intensity > 0:
            qs = qs.filter(intensity__gte=min_intensity)
        return list(qs.order_by("-intensity")[:limit])

    return await sync_to_async(_query)()
