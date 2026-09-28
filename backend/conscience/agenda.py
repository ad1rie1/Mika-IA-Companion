"""L'agenda — ce que la conscience lit et écrit des `ScheduledAction`.

Trois lectures d'une même table, sorties de ``engine.py`` sur le modèle de
``travaux.py`` : ce qui est dû maintenant (le scoring, le prompt de l'acte),
ce qui vient (l'espoir, le prompt de l'acte) et le compte des tentatives
d'un acte qui a échoué. Fonctions de module sans état ; le moteur garde
un délégué du même nom pour chacune, parce que les tests les patchent
(``patch.object(type(e), "_get_upcoming_actions")``) et que ``acte.py`` et
``affects.py`` les appellent à travers cette surface.
"""

from __future__ import annotations

import logging

from asgiref.sync import sync_to_async

from configs.runtime import cfg_bool, cfg_int
from utils.degradation import degradations

logger = logging.getLogger(__name__)


def enregistrer_tentative(action, champs) -> None:
    """Une fin tardive ne doit pas écraser la décision de l'opérateur."""
    from conscience.models import ScheduledAction

    requete = ScheduledAction.objects.filter(pk=action.pk)
    jeton = action.context_data.get("attempt_token")
    if jeton:
        requete = requete.filter(status="uncertain", context_data__attempt_token=jeton)
    requete.update(**{champ: getattr(action, champ) for champ in champs})

#: Tentatives d'une action programmée avant abandon.
_SCHEDULED_TENTATIVES_MAX = 3
#: Délai avant de retenter une action programmée qui vient d'échouer, par
#: tentative déjà faite (5 min × n). Sans lui, un rendez-vous prioritaire dont
#: l'appel IA échoue (rôle non mappé, quota, timeout) levait le cooldown ET le
#: veto de sommeil à CHAQUE cycle de 30 s — un acte, un échec, un acte —
#: pendant que `tentatives` restait à zéro parce que l'échec « propre »
#: (`output.ai_failed`) rentrait avant le compteur, réservé à l'exception.
_SCHEDULED_REESSAI_S = 300


async def poll_scheduled_actions() -> list:
    """Query scheduled actions that are due (scheduled_at <= now).

    Une action dont la dernière tentative a échoué n'est due qu'après
    `reessayer_le` : c'est ce qui rend le backoff effectif, puisque tout
    ce qui lève le cooldown ou le veto de sommeil se lit sur ce que ce
    poll remonte.
    """
    if not cfg_bool("conscience.brief.include_scheduled_action", True):
        return []
    from conscience.models import ScheduledAction
    from django.db.models import Q
    from django.utils import timezone as tz

    try:
        maintenant = tz.now()
        return await sync_to_async(
            lambda: list(
                ScheduledAction.objects.filter(
                    status="pending",
                    scheduled_at__lte=maintenant,
                ).filter(
                    Q(reessayer_le__isnull=True)
                    | Q(reessayer_le__lte=maintenant)
                ).order_by("scheduled_at")[:10]
            )
        )()
    except Exception as exc:
        degradations.record("conscience: poll scheduled actions", exc)
        return []


async def get_upcoming_actions(limit: int = 5) -> list[tuple]:
    """Get future pending actions (not yet due). Returns [(action, minutes_until), ...]."""
    from conscience.models import ScheduledAction
    from django.utils import timezone as tz

    now = tz.now()
    try:
        actions = await sync_to_async(
            lambda: list(
                ScheduledAction.objects.filter(
                    status="pending",
                    scheduled_at__gt=now,
                ).order_by("scheduled_at")[:limit]
            )
        )()
        return [(a, int((a.scheduled_at - now).total_seconds() / 60)) for a in actions]
    except Exception as exc:
        degradations.record("conscience: upcoming scheduled actions", exc)
        return []


async def compter_tentative(actions: list) -> None:
    """Une tentative de plus, l'abandon au-delà du plafond — et, entre
    les deux, un délai avant de réessayer.

    Le délai croît avec les tentatives (`conscience.scheduled.reessai_s`
    × n) et s'écrit sur `reessayer_le`, que `poll_scheduled_actions`
    respecte : une action qui vient d'échouer n'est plus « due » pendant
    ce temps, donc ne lève ni le cooldown ni le veto de sommeil — la
    sortie prioritaire du scoring ne s'applique qu'à ce que le poll
    remonte. Sans ce délai, compter la tentative ne changeait rien au
    rythme : trois échecs à 30 s d'intervalle, et l'action était perdue
    en une minute et demie pour une panne passagère du provider.
    """
    from conscience.models import ScheduledAction
    from django.utils import timezone as tz
    from datetime import timedelta

    plafond = cfg_int(
        "conscience.scheduled.tentatives_max", _SCHEDULED_TENTATIVES_MAX,
        mini=1,
    )
    pas = cfg_int(
        "conscience.scheduled.reessai_s", _SCHEDULED_REESSAI_S, mini=0,
    )
    maintenant = tz.now()

    def _ecrire() -> None:
        for action in actions:
            action.tentatives = (action.tentatives or 0) + 1
            if action.tentatives >= plafond:
                action.status = ScheduledAction.Status.FAILED
                action.raison_echec = (
                    f"abandonnée après {action.tentatives} tentatives"
                )
                action.reessayer_le = None
            else:
                action.reessayer_le = maintenant + timedelta(
                    seconds=pas * action.tentatives,
                )
            action.context_data.pop("reserved_until", None)
            enregistrer_tentative(action, [
                "tentatives", "status", "raison_echec", "reessayer_le", "context_data",
            ])

    await sync_to_async(_ecrire, thread_sensitive=True)()
