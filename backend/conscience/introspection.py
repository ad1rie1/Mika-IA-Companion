"""Ce qu'elle relit de sa propre trace — à chaque cycle, et au réveil.

`ConscienceLog` et `Message` sont ce que le moteur écrit ; ceci est ce
qu'il en relit : combien de fois elle a parlé aujourd'hui et depuis quand
on l'ignore (chaque cycle), et, au démarrage, le cooldown en cours, depuis
quand personne ne lui a parlé, quelles périodes elle a déjà saluées. Sorti
de ``engine.py`` sur le modèle de ``travaux.py`` : des fonctions de module
prenant le moteur pour l'état qu'elles restaurent (``_last_action_time``,
``_last_activity``, ``_greeted_periods``), le moteur gardant un délégué du
même nom pour celles que les tests appellent.
"""

from __future__ import annotations

import logging
import time

from asgiref.sync import sync_to_async

from configs.runtime import cfg_float, cfg_int
from conscience.reglages import (
    _IGNORED_TELEGRAM_FACTOR,
    ignored_reply_window_minutes,
)
from utils.degradation import degradations, degraded

logger = logging.getLogger(__name__)

#: Plafond de l'inactivité restaurée au démarrage. Au-delà, la mesure ne
#: dit plus rien d'utile : trois jours ou trois mois de silence produisent
#: le même facteur, déjà à son plafond.
_INACTIVITE_RESTAUREE_MAX_S = 72 * 3600


async def introspect(moteur) -> tuple[int, int]:
    """Query recent ConscienceLogs for self-awareness.

    Returns:
        (acts_today, consecutive_ignored_acts)
    """
    from conscience.models import ConscienceLog, Observation
    from conscience.read import debut_du_jour_local
    from datetime import timedelta

    today_start = debut_du_jour_local()
    # Lu ici, hors du thread d'exécuteur, et une seule fois : les deux
    # usages ci-dessous doivent parler de la même fenêtre, sinon un acte
    # peut être « répondu » pour la sélection des réponses et « ignoré »
    # pour le comptage.
    fenetre = timedelta(minutes=ignored_reply_window_minutes())
    # La fenêtre dépend du CANAL de l'acte : un message Telegram se lit
    # quand on y pense, pas quand il arrive. Compter « ignorée » une
    # relance Telegram après vingt minutes, c'est se vexer d'un téléphone
    # posé sur une table.
    facteur_tg = cfg_float(
        "conscience.ignored_reply_window_telegram_factor",
        _IGNORED_TELEGRAM_FACTOR, mini=1.0,
    )

    def _fenetre_de(person_id: str) -> timedelta:
        if str(person_id or "").startswith("tg_"):
            return fenetre * facteur_tg
        return fenetre

    def _query() -> tuple[int, int]:
        # One round-trip for the whole introspection. This runs on every
        # decision cycle (30s by default, forever, whether or not anyone
        # is talking), and the old shape was 2 queries plus one
        # `.exists()` per recent act — each its own sync_to_async thread
        # hop — to answer a question about at most 5 rows.
        acts_today = ConscienceLog.objects.filter(
            decision="act", created_at__gte=today_start,
        ).count()

        recent_acts = list(
            ConscienceLog.objects.filter(decision="act")
            .order_by("-created_at")
            .values_list("created_at", "person_id")[:5]
        )
        if not recent_acts:
            return acts_today, 0

        # Fetch every user reply since the oldest act in the window once,
        # then answer "was this act followed by a reply within the
        # window?" in Python. The window is bounded by definition — 5 acts.
        oldest = recent_acts[-1][0]
        newest_window_end = max(t + _fenetre_de(pid) for t, pid in recent_acts)
        replies = list(
            Observation.objects.filter(
                event_type__in=("chat.message", "telegram.message"),
                created_at__gt=oldest,
                created_at__lte=newest_window_end,
            ).values_list("created_at", flat=True)
        )

        consecutive_ignored = 0
        for act_time, pid in recent_acts:
            deadline = act_time + _fenetre_de(pid)
            if any(act_time < reply <= deadline for reply in replies):
                break
            consecutive_ignored += 1
        return acts_today, consecutive_ignored

    try:
        return await sync_to_async(_query)()
    except Exception as exc:
        degradations.record("conscience: introspection", exc)
        return 0, 0


async def restore_cooldown(moteur) -> None:
    """Restore _last_action_time from the most recent 'act' ConscienceLog.

    This ensures the cooldown survives process restarts — without it,
    the conscience would act immediately after every restart.
    """
    from conscience.models import ConscienceLog

    try:
        last_act = await sync_to_async(
            lambda: ConscienceLog.objects.filter(decision="act")
            .order_by("-created_at")
            .first()
        )()
        if last_act:
            moteur._last_action_time = last_act.created_at.timestamp()
            elapsed = time.time() - moteur._last_action_time
            if elapsed < moteur._cooldown_seconds:
                logger.info(
                    "Conscience cooldown restored: %ds remaining",
                    int(moteur._cooldown_seconds - elapsed),
                )
            else:
                logger.debug("Last conscience action was %ds ago (cooldown expired)", int(elapsed))
    except Exception as exc:
        degradations.record("conscience: could not restore cooldown", exc)


async def restaurer_inactivite(moteur) -> None:
    """Retrouver depuis quand personne ne lui a parlé, après un redémarrage.

    `_last_activity` repartait de `time.time()` à la construction : au boot,
    elle croyait qu'on venait de lui parler. Or les pulsions, elles,
    **rejouent le temps écoulé** depuis leur instantané — si bien que SOCIAL
    se souvenait de trois jours d'absence pendant que le Facteur 4 lisait
    zéro. Deux mesures du même silence qui se contredisaient pendant toute
    l'heure suivant chaque démarrage, et rien ne le signalait.

    On lit le dernier message d'une **vraie personne** : ni ses propres
    répliques, ni la tuyauterie interne. `ConscienceLog` serait le pire
    choix possible — il date ses propres monologues, donc elle conclurait
    que le silence vient d'être rompu par elle-même.
    """
    from identity.trust import is_internal_person
    from memory.models import Message

    def _dernier() -> float | None:
        for msg in (
            Message.objects
            .filter(role="user")
            .exclude(is_internal=True)
            .order_by("-id")[:20]
        ):
            if not is_internal_person(msg.person_id):
                return msg.created_at.timestamp()
        return None

    with degraded("conscience: restauration de l'inactivite"):
        horodatage = await sync_to_async(_dernier, thread_sensitive=True)()
        if horodatage is None:
            return
        plafond = cfg_int(
            "conscience.inactivite_restauree_max_seconds",
            _INACTIVITE_RESTAUREE_MAX_S, mini=0,
        )
        moteur._last_activity = max(horodatage, time.time() - plafond)
        logger.info(
            "Inactivité restaurée : %d s depuis le dernier message",
            int(moteur.get_idle_seconds()),
        )


async def restaurer_salutations(moteur) -> None:
    """Retrouver quelles périodes ont déjà été saluées aujourd'hui.

    `_greeted_periods` vivait en RAM seulement : un redémarrage entre 7 h
    et 10 h refaisait dire bonjour (+0,35 au score, la moitié du seuil).
    La trace existe déjà — `ConscienceLog.reason` porte `time(morning)`
    sur l'acte qui a salué — donc on la relit plutôt que d'ajouter une
    table. Ne lève jamais.
    """
    import re
    from datetime import date

    from conscience.models import ConscienceLog
    from conscience.read import debut_du_jour_local

    motif = re.compile(r"time\((morning|evening|night)\)")

    def _lire() -> set[str]:
        raisons = ConscienceLog.objects.filter(
            decision="act",
            created_at__gte=debut_du_jour_local(),
            reason__contains="time(",
        ).values_list("reason", flat=True)
        return {m.group(1) for r in raisons for m in motif.finditer(r or "")}

    with degraded("conscience: restauration des salutations"):
        periodes = await sync_to_async(_lire, thread_sensitive=True)()
        if periodes:
            moteur._greeted_periods = periodes
            moteur._greeted_date = date.today()
            logger.info("Salutations déjà faites aujourd'hui : %s", sorted(periodes))
