"""L'entretien — ce que la conscience fait à chaque cycle sans parler.

Le troisième étage du moteur (« 3. MEMORY MAINTENANCE »), sorti de
``engine.py`` sur le modèle de ``travaux.py`` : des fonctions de module
prenant le moteur pour l'état qu'elles étranglent (``_last_stale_sweep``,
``_last_cleanup``) et pour orchestrer à travers sa surface
(``moteur._promote_stale_to_ruminations``, ``moteur._decay_ruminations``…),
si bien qu'un patch posé sur le moteur continue de porter.

Les portes de pertinence vivent au niveau du module : la garde AST de
``test_config_rapatriement`` résout un repli ``ast.Name`` en attribut du
module et confronte ainsi chaque repli au défaut déclaré.
"""

from __future__ import annotations

import logging
import time

from asgiref.sync import sync_to_async

from configs.runtime import cfg_float, cfg_int
from conscience.reglages import pending_window_minutes
from conscience.types import DecisionContext
from utils.degradation import degradations

logger = logging.getLogger(__name__)

#: Pertinence à partir de laquelle un signal ravive les souvenirs de ses thèmes.
BOOST_PERTINENCE = 0.50
#: Pertinence à partir de laquelle on vérifie qu'un signal ne contredit rien.
#:
#: Volontairement **laissée en haut** alors que tout le reste descend : cette
#: branche coûte jusqu'à cinq appels IA, et seuls `chat` et `telegram` la
#: visent. La déclarer sans la bouger la rend réglable sans la banaliser.
CONTRADICTION_PERTINENCE = 0.80

# Marque posee dans raw_data une fois l'observation passee par la
# maintenance. Observation n'a pas de champ dedie, et raw_data porte
# deja les themes de l'interpretation (voir perception.store_observation) :
# la meme convention evite une migration pour un drapeau interne.
_MAINTENANCE_FLAG = "maintenance_done"

# Meme decalage d'echelle que la purge, en plus court : le seuil est a 30
# minutes et le seul lecteur du statut "skipped" est la promotion en
# rumination, qui lit une fenetre de 2h. Une granularite de 5 minutes ne
# change donc rien d'observable — le scoring, lui, ne voit jamais ces
# lignes, `_build_context` bornant sa selection aux 30 dernieres minutes.
_STALE_SWEEP_INTERVAL_S = 300
_STALE_SWEEP_BATCH = 1000

# Cadence et taille de lot de la purge. La donnee visee a 48h, le cycle de
# decision tourne toutes les 30s : un passage par heure suffit, sur la
# forme deja retenue par `_apply_decay` du consolidateur. Le lot borne la
# transaction d'ecriture — `Rumination.observation` est une FK SET_NULL,
# donc chaque suppression traine ses UPDATE, et sur SQLite un ecrivain
# bloque tous les lecteurs le temps de la transaction.
_CLEANUP_INTERVAL_S = 3600
_CLEANUP_BATCH = 1000
#: Âge des observations closes avant purge.
_OBSERVATION_RETENTION_H: int = 48


def themes_de(obs) -> list:
    """Les thèmes d'une observation — le champ, puis la convention.

    Le champ (migration conscience/0013) d'abord ; ``raw_data["themes"]``
    en repli pour les lignes d'avant. Ne lève jamais : boucle sans
    superviseur.
    """
    try:
        champ = getattr(obs, "themes", None)
        if champ:
            return list(champ)
        return list(obs.raw_data.get("themes", []) or [])
    except Exception as exc:
        degradations.record("conscience: themes d'une observation", exc)
        return []


async def memory_maintenance(moteur, ctx: DecisionContext) -> list[str]:
    """Modify memory based on accumulated observations.

    Runs every decision cycle — the Conscience can reshape memory
    even without speaking.

    Une observation n'est maintenue **qu'une fois**. Elle reste
    `pending` jusqu'a un acte ou sa peremption (30 min), et
    `_build_context` la reselectionne a chaque cycle : sans cette
    marque, un signal pertinent repayait a chaque tour une recherche
    vectorielle plus jusqu'a cinq appels IA de validation — soit une
    soixantaine de fois a l'intervalle par defaut, en serie et
    `_decision_lock` tenu, ce qui court-circuitait aussi bien les
    ticks periodiques que le fast-path haute pertinence. Le boost
    d'importance, lui, se cumulait a chaque passage.
    """
    actions = []

    for obs in ctx.pending_observations:
        if obs.raw_data.get(_MAINTENANCE_FLAG):
            continue

        # Marquee avant le travail, pas apres : la marque dit "cette
        # observation est passee par la maintenance", pas "la
        # maintenance a reussi". La poser apres laisserait une panne
        # transitoire rejouer exactement la boucle qu'on supprime ici.
        await mark_maintained(obs)

        # Boost related souvenirs for pertinent signals
        if obs.pertinence >= cfg_float(
            "conscience.maintenance.boost_pertinence", BOOST_PERTINENCE,
        ):
            themes = themes_de(obs)
            if themes:
                count = await moteur.memory.boost_related_souvenirs(themes, 0.1)
                if count:
                    actions.append(f"boosted {count} souvenirs (themes: {themes})")

        # Check contradictions for high-pertinence communication signals
        if obs.pertinence >= cfg_float(
            "conscience.maintenance.contradiction_pertinence",
            CONTRADICTION_PERTINENCE,
        ) and obs.category == "communication":
            contradictions = await moteur.memory.check_contradictions(obs.summary)
            for c in contradictions:
                if not c["still_valid"]:
                    actions.append(
                        f"invalidated connaissance #{c['connaissance_id']}"
                    )

    return actions


async def mark_maintained(obs) -> None:
    """Poser durablement la marque de maintenance sur une observation.

    En base, pas en RAM : les observations sont relues a chaque cycle
    et un redemarrage relancerait sinon la meme maintenance. Si
    l'ecriture echoue, la marque n'existe pas et l'observation
    repassera au cycle suivant — degradation comptee, pas de blocage.
    """
    try:
        obs.raw_data[_MAINTENANCE_FLAG] = True
        await sync_to_async(obs.save)(update_fields=["raw_data"])
    except Exception as exc:
        degradations.record("conscience: mark observation maintained", exc)


async def mark_stale_observations(moteur) -> None:
    """Mark pending observations older than 30 min as skipped.

    Pertinent stale observations are promoted to Ruminations — Mika
    keeps thinking about them even after the short-term buffer empties.

    L'UPDATE est etrangle a `_STALE_SWEEP_INTERVAL_S` et borne a
    `_STALE_SWEEP_BATCH` lignes ; la promotion et la decroissance des
    ruminations, elles, restent a chaque cycle (5% par cycle est leur
    definition).
    """
    from conscience.models import Observation
    from django.utils import timezone as tz
    from datetime import timedelta

    now = time.monotonic()
    cadence = cfg_int(
        "conscience.stale_sweep_interval_seconds",
        _STALE_SWEEP_INTERVAL_S, mini=1,
    )
    if (not moteur._last_stale_sweep
            or (now - moteur._last_stale_sweep) >= cadence):
        moteur._last_stale_sweep = now
        cutoff = tz.now() - timedelta(minutes=pending_window_minutes())

        def _perimer() -> int:
            ids = list(
                Observation.objects.filter(
                    status="pending",
                    created_at__lt=cutoff,
                ).values_list("pk", flat=True)[:_STALE_SWEEP_BATCH]
            )
            if not ids:
                return 0
            return Observation.objects.filter(pk__in=ids).update(
                status="skipped")

        try:
            count = await sync_to_async(_perimer)()
            if count:
                logger.debug("Marked %d stale observations as skipped", count)
            if count >= _STALE_SWEEP_BATCH:
                moteur._last_stale_sweep = 0.0
        except Exception as exc:
            degradations.record("conscience: mark stale observations", exc)

    # Promote pertinent skipped observations to ruminations.
    await moteur._promote_stale_to_ruminations()
    # Decay existing ruminations over each cycle.
    await moteur._decay_ruminations()
    # Le retour d'un absent se ressent — l'autre moitié de l'embryon du
    # modèle d'attentes.
    await moteur._le_retour_d_un_absent()


async def cleanup_old_observations(moteur) -> None:
    """Delete observations older than 48h that are no longer pending.

    Etranglee a `_CLEANUP_INTERVAL_S` et bornee a `_CLEANUP_BATCH` lignes
    par passage. Rien n'est perdu : ce qui deborde du lot reste eligible,
    et un lot plein reprogramme le passage suivant au cycle d'apres plutot
    que dans une heure — sans quoi un pic (premier polling RSS, module
    forge bavard) mettrait des heures a se resorber.
    """
    from conscience.models import Observation
    from django.utils import timezone as tz
    from datetime import timedelta

    now = time.monotonic()
    cadence = cfg_int(
        "conscience.cleanup_interval_seconds", _CLEANUP_INTERVAL_S, mini=1,
    )
    if moteur._last_cleanup and (now - moteur._last_cleanup) < cadence:
        return
    moteur._last_cleanup = now

    cutoff = tz.now() - timedelta(hours=cfg_int(
        "conscience.observation_retention_hours",
        _OBSERVATION_RETENTION_H, mini=1,
    ))
    # `status__in` plutot que `exclude(status="pending")` : l'index
    # ["status", "-created_at"] a sa colonne de tete filtree par `!=`
    # dans la seconde forme, donc inexploitable — c'etait un balayage
    # complet de la table a chaque passage. La liste est derivee des
    # choix du modele, pour ne pas oublier un statut ajoute plus tard.
    closed = [s for s in Observation.Status.values
              if s != Observation.Status.PENDING]

    def _purger() -> int:
        # Suppression par liste de pk (motif de memory/retention.py) :
        # `.delete()` sur un queryset tranche n'est pas portable, et cela
        # garde l'instruction bornee.
        ids = list(
            Observation.objects.filter(
                status__in=closed,
                created_at__lt=cutoff,
            ).values_list("pk", flat=True)[:_CLEANUP_BATCH]
        )
        if not ids:
            return 0
        # .delete() returns (total, {model: count}) tuple
        return Observation.objects.filter(pk__in=ids).delete()[0]

    try:
        count = await sync_to_async(_purger)()
    except Exception as exc:
        degradations.record("conscience: observation cleanup", exc)
        return

    if count:
        logger.info("Cleaned up %d old observations", count)
    if count >= _CLEANUP_BATCH:
        moteur._last_cleanup = 0.0
