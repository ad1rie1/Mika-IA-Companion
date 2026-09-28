"""Les pensées qui restent — ce que la conscience fait de ses `Rumination`.

Naissance (promotion d'une observation écartée, audit d'après-coup), vie
(pression sur le score, saignée dans l'humeur, dérive émotionnelle,
décroissance en temps réel), soulagement (parler, le retour d'un absent).
Sorti de ``engine.py`` sur le modèle de ``travaux.py`` : des fonctions de
module prenant le moteur pour l'état qu'elles espacent
(``_rumination_bleed_at``, ``_dernier_retour_scan``, le mémo des audits)
et pour orchestrer à travers sa surface (``moteur._bleed_ruminations``,
``moteur._audit_trop_recent``), si bien qu'un patch posé sur le moteur
continue de porter.

Lecture, calcul et écriture tiennent dans **un seul callable synchrone**
partout ici : ``sync_to_async(thread_sensitive=True)`` les sérialise sur le
même thread d'exécuteur que la digestion du sommeil, et un ``status`` lu
avant elle ne peut plus être réécrit après.
"""

from __future__ import annotations

import logging
import time

from asgiref.sync import sync_to_async
from django.db.models import F

from configs.runtime import cfg_float, cfg_int
from conscience import estime
from conscience.entretien import themes_de
from conscience.reglages import (
    pending_window_minutes,
    rumination_tuning,
    vecu_tuning,
)
from conscience.vecu import cible_de_derive, phrase_de_rejeu
from emotion.engine import emotion_engine
from utils.degradation import degradations, degraded

logger = logging.getLogger(__name__)

# ── Portes de pertinence ──────────────────────────────────────────────
#
# Elles vivent au niveau module, et pas en attribut de classe comme leurs
# aînées : la garde AST de `test_config_rapatriement` résout un repli
# `ast.Name` en attribut **du module**, et ignore silencieusement un
# `self._X`. Un repli en attribut de classe n'est donc jamais confronté au
# défaut déclaré — exactement la divergence que la garde existe pour
# empêcher.
#
# Toutes se lisaient en dur, et toutes étaient hors d'atteinte : le chemin
# heuristique de l'interpréteur ne produit au mieux que 0.55 (RSS apparié),
# le reste étant à 0.40 et moins. Une promotion à 0.5, un boost à 0.7 et un
# fast-path à 0.85 ne pouvaient donc être franchis que par `email.received`,
# seul signal payant un appel LLM. Sur une installation sans compte mail —
# celle par défaut — six mécanismes ne se déclenchaient jamais.

#: Pertinence à partir de laquelle une observation périmée devient une pensée.
PROMOTION_PERTINENCE = 0.45
#: Au-delà, on ne promeut plus : une pensée de plus ne se pense pas mieux.
#:
#: Descendre la porte sans ce plafond installe une pression permanente sur le
#: Facteur 10 (jusqu'à +0.30) et annule la moitié du gain de désaturation.
PROMOTION_ACTIVES_MAX = 6
#: Somme d'intensités valant une pression de rumination pleine (1.0).
#:
#: La somme était comparée à 1.0 : deux pensées à 0.5 saturaient déjà le
#: Facteur 10. Avec une promotion plus ouverte, la saturation deviendrait
#: l'état normal et le facteur cesserait d'informer.
RUMINATION_PRESSION_PLEINE = 2.5

# Emotional drift map for aging ruminations. A thought doesn't stay
# the same shape forever — frustration that lingers becomes anxiety,
# an unresolved excitement fades into melancholy, etc. Keyed by the
# initial emotion, value is the label the rumination drifts toward
# once it's been "turning over" long enough (cycle count threshold).
_RUMINATION_DRIFT: dict[str, str] = {
    "frustrated": "anxious",
    "angry": "melancholic",
    "excited": "nostalgic",
    "happy": "nostalgic",
    "grateful": "nostalgic",
    "sad": "melancholic",
    "scared": "anxious",
    "jealous": "sad",
    "hopeful": "anxious",
    "curious": "confused",
    "surprised": "thinking",
    "embarrassed": "anxious",
    "lonely": "melancholic",
}
# En deçà, on ne réécrit pas la ligne : le temps s'accumule sur
# `decayed_at` au lieu d'être perdu (cf. la décroissance des souvenirs).
_RUMINATION_WRITE_DELTA: float = 0.005
# Une pensée teinte l'humeur, elle ne la matraque pas. Sans cette borne,
# une rumination qui vit désormais des heures enverrait une impulsion
# toutes les 30 s dans l'humeur globale — l'ancienne cadence n'était
# tolérable que parce que la pensée mourait en 22 minutes.
_RUMINATION_BLEED_INTERVAL_S: float = 600.0
#: Part de l'intensité d'une pensée effectivement versée dans l'humeur.
#: Elle teinte, elle n'impose pas.
#: 0,35 et non 0,15 : à 0,15, « Je bloque sur… » (0,35) versait
#: ``frustrated 0.05`` toutes les dix minutes — régime permanent à 7 % de
#: l'écart au repos, sous la tolérance de 0,1 : le mécanisme existait et
#: ne se voyait jamais, ni dans le prompt ni dans les portes. À 0,35 le
#: régime permanent est ~0,16 d'écart, « à peine frustrée » — visible,
#: pas envahissant.
_RUMINATION_BLEED_INTENSITY: float = 0.35

#: Joie du retour de quelqu'un qui manquait, et cadence du balayage.
#: La pensée « j'aimerais avoir des nouvelles de X » ne faisait que se
#: faner ; quand X redonne signe, elle se RÉSOUT — avec de la joie, pas
#: par le temps. C'est une prédiction tenue par le système (le manque)
#: qui se réalise et qui, enfin, se ressent.
_RETOUR_ABSENT_JOIE = 0.4
_RETOUR_SCAN_INTERVAL_S = 300.0

# Emotions that trigger a post-action micro-rumination. Strong
# expressions — positive or negative — are the ones that leave a
# trace: after saying something bold or anxious, a human replays it
# mentally. Neutral mid-range responses don't need an audit.
# `_AUDIT_EMOTIONS` a été supprimée : neuf gabarits littéraux pour
# vingt-neuf émotions, donc vingt tours ne se rejouaient jamais.
# `vecu.cible_de_derive` + `vecu.phrase_de_rejeu` les couvrent toutes en
# dérivant registre et cible de l'ancre PAD déjà déclarée.

#: Espacement minimal entre deux audits d'après-coup pour une même personne,
#: et plafond des micro-ruminations d'audit actives. Sans l'un ni l'autre,
#: chaque réponse chargée (intensité ≥ 0.55, n'importe quelle émotion non
#: neutre) écrivait sa rumination : douze tours de conversation animée, et le
#: Facteur 10 restait cloué à +0.30 pendant les ~9 h que met la demi-vie à
#: les dissoudre. Se rejouer une réponse est un battement, pas un régime.
_AUDIT_ESPACEMENT_S = 1800
_AUDIT_ACTIVES_MAX = 3
#: Barre au-dessous de laquelle une réponse ne se rejoue pas mentalement,
#: puis la rampe qui en tire l'intensité de la micro-rumination. Replis :
#: les mêmes valeurs qu'avant le rapatriement en configuration.
_AUDIT_MIN_INTENSITY: float = 0.55
#: Pente de la modulation par l'estime : à 0.95 d'estime le seuil monte
#: de ~0.135 (on se rejoue moins), à 0.05 il descend d'autant.
_AUDIT_ESTIME_PENTE: float = 0.3
_AUDIT_BASE_INTENSITY: float = 0.2
_AUDIT_SLOPE: float = 0.5
_AUDIT_MAX_INTENSITY: float = 0.45
#: Borne RAM du mémo « dernier audit par personne » — même idiome que
#: `perception.habituer` : perdre le mémo au redémarrage coûte au pire un
#: audit de trop, jamais un de moins.
_AUDIT_MEMO_MAX_CLES = 200


# ── Lecture ───────────────────────────────────────────────────────


async def rumination_snapshot() -> tuple[float, int, list[dict]]:
    """Pression des pensées actives, leur nombre, et les pensées elles-mêmes.

    Renvoie ``(pression_bornée_01, nombre, lignes)``. Tolérant : si le
    modèle n'est pas encore migré, ``(0.0, 0, [])``.

    Les lignes sont rendues **dès maintenant**, alors qu'aucun appelant ne
    les lit encore : c'est la même requête, le troisième élément ne coûte
    rien, et le lot qui branchera le contenu des ruminations sur le choix
    du sujet n'aura pas à revenir réécrire cette fonction — la classe de
    collision que la revue a le plus souvent relevée.

    La pression n'est plus la somme brute comparée à 1.0 : deux pensées à
    0.5 saturaient le Facteur 10, et une promotion plus ouverte aurait fait
    de la saturation l'état permanent.
    """
    try:
        from conscience.models import Rumination
    except ImportError:
        return 0.0, 0, []

    try:
        lignes = await sync_to_async(
            lambda: list(
                Rumination.objects
                .filter(status="active")
                .order_by("-intensity")
                .values("id", "summary", "themes", "intensity", "emotion")[:20]
            )
        )()
    except Exception as exc:
        # Table may not exist yet (migration pending) — silencieux, mais
        # compté : sans ça le Facteur 10 du scoring tombe a 0.0 et une
        # panne totale ressemble a "elle n'a rien qui lui trotte en tete".
        degradations.record("conscience: rumination pressure snapshot", exc)
        return 0.0, 0, []

    if not lignes:
        return 0.0, 0, []
    total = sum(ligne["intensity"] for ligne in lignes)
    pleine = cfg_float(
        "conscience.rumination_pressure_full", RUMINATION_PRESSION_PLEINE,
        mini=0.01,
    )
    return min(1.0, total / pleine), len(lignes), lignes


# ── Soulagement ───────────────────────────────────────────────────


async def resolve_ruminations_after_act(*, themes=()) -> None:
    """Soulager uniquement les préoccupations abordées par cet acte."""
    themes = {str(t).casefold().strip() for t in themes if str(t).strip()}
    if not themes:
        return
    try:
        from conscience.models import Rumination
    except ImportError:
        return

    def _passe() -> int:
        """Halve puis résout — **un seul callable synchrone**, sans lecture.

        L'ancienne forme lisait le lot, le divisait en RAM, puis le
        réécrivait par `bulk_update` : deux `await` entre lesquels la
        digestion nocturne (ou `decay_ruminations`) pouvait faner une
        ligne que la réécriture ressuscitait en `active` — la course
        exacte que `decay_ruminations` et `sleep._digerer_ligne`
        documentent. Deux UPDATE filtrés sur `status="active"` ne
        touchent jamais une ligne qu'un autre écrivain vient de fermer.
        """
        from django.db import transaction

        with transaction.atomic():
            ids = [r.pk for r in Rumination.objects.filter(status="active")
                   if themes.intersection(str(t).casefold().strip() for t in (r.themes or []))]
            n = Rumination.objects.filter(pk__in=ids, status="active").update(
                intensity=F("intensity") * 0.5,
            )
            Rumination.objects.filter(
                pk__in=ids, status="active", intensity__lt=0.1,
            ).update(status="resolved")
        return n

    try:
        await sync_to_async(_passe, thread_sensitive=True)()
    except Exception as exc:
        degradations.record("conscience: rumination relief write", exc)


# ── Vieillissement ────────────────────────────────────────────────


async def decay_ruminations(moteur) -> None:
    """Fait vieillir les pensées en cours, en TEMPS RÉEL.

    Une pensée s'estompe parce que des heures passent, pas parce qu'une
    boucle a tourné. L'ancienne formule (`*= 0.95` à chaque cycle de 30 s)
    liait la durée de vie d'une rumination à la cadence de la boucle : une
    pensée « persistante » mourait en 22 minutes, et la moitié de ses
    lecteurs — la digestion nocturne à 120 minutes d'âge, le journal du
    soir, le fragment de rêve — ne pouvait structurellement jamais la voir.
    La demi-vie est maintenant une durée (`conscience.rumination_half_life_hours`,
    6 h par défaut) : une contrariété du soir est encore là au coucher, et
    c'est bien la nuit qui la digère.

    Dérive émotionnelle : au bout de `rumination_drift_hours`, une pensée
    change de forme — la frustration devient de l'inquiétude. Elle aussi se
    compte en heures.

    **Lecture, calcul et écriture tiennent dans un seul appel synchrone.**
    `sync_to_async(thread_sensitive=True)` les sérialise donc sur le même
    thread d'exécuteur que la digestion du sommeil : un `status` lu avant
    elle ne peut plus être réécrit après, ce qui ressuscitait en `active`
    une pensée que la nuit venait de faner.
    """
    try:
        from conscience.models import Rumination
    except ImportError:
        return

    demi_vie_h, derive_h = rumination_tuning()

    def _passe() -> list[tuple[str, float]]:
        """Vieillit le lot et rend ce qui doit teinter l'humeur."""
        from django.utils import timezone as tz

        maintenant = tz.now()
        lot = list(Rumination.objects.filter(status="active")[:30])
        if not lot:
            return []

        a_ecrire: list = []
        derives: list = []
        saignees: list[tuple[str, float]] = []

        for r in lot:
            ancre = r.decayed_at or r.created_at
            heures = max(0.0, (maintenant - ancre).total_seconds() / 3600.0)
            nouvelle = r.intensity * (0.5 ** (heures / demi_vie_h))

            # Sous le seuil d'écriture on ne touche à rien : `decayed_at`
            # reste en arrière et le temps écoulé s'accumule au lieu d'être
            # perdu. C'est ce qui rend la décroissance indépendante de la
            # cadence de la boucle qui l'applique.
            if r.intensity - nouvelle > _RUMINATION_WRITE_DELTA:
                r.intensity = round(nouvelle, 4)
                r.decayed_at = maintenant
                if r.intensity < 0.1:
                    r.status = "faded"
                a_ecrire.append(r)

            if r.emotion and r.status == "active":
                age_h = (maintenant - r.created_at).total_seconds() / 3600.0
                cible = _RUMINATION_DRIFT.get(r.emotion)
                if cible and cible != r.emotion and age_h >= derive_h:
                    logger.debug(
                        "Rumination #%s drift: %s -> %s", r.pk, r.emotion, cible,
                    )
                    r.emotion = cible
                    derives.append(r)
                if r.intensity > 0.3:
                    saignees.append((r.emotion, r.intensity))

        if a_ecrire:
            Rumination.objects.bulk_update(
                a_ecrire, ["intensity", "status", "decayed_at"], batch_size=50,
            )
        if derives:
            Rumination.objects.bulk_update(derives, ["emotion"], batch_size=50)
        return saignees

    try:
        saignees = await sync_to_async(_passe)()
    except Exception as exc:
        degradations.record("conscience: ruminations to decay", exc)
        return

    moteur._bleed_ruminations(saignees)


def bleed_ruminations(moteur, saignees: list[tuple[str, float]]) -> None:
    """Laisse les pensées en cours teinter l'humeur globale — par à-coups.

    Une pensée colore l'humeur, elle ne la matraque pas. Tant qu'une
    rumination mourait en 22 minutes, saigner à chaque cycle de 30 s était
    auto-limité ; maintenant qu'elle vit des heures, la même cadence
    clouerait l'humeur globale sur l'émotion de la rumination pour la
    soirée entière. On espace donc à un versement par ``_RUMINATION_BLEED_INTERVAL_S``.
    """
    if not saignees:
        return
    from emotion.types import Emotion, EmotionData

    espacement = cfg_float(
        "conscience.rumination_bleed_interval_seconds",
        _RUMINATION_BLEED_INTERVAL_S, mini=0.0,
    )
    part = cfg_float(
        "conscience.rumination_bleed_intensity",
        _RUMINATION_BLEED_INTENSITY, mini=0.0, maxi=1.0,
    )
    maintenant = time.monotonic()
    for etiquette, intensite in saignees:
        dernier = moteur._rumination_bleed_at.get(etiquette, 0.0)
        if maintenant - dernier < espacement:
            continue
        try:
            emo = Emotion(etiquette)
        except ValueError:
            continue  # étiquette inconnue sur une vieille ligne
        try:
            emotion_engine.process_emotion(
                EmotionData(emotion=emo, intensity=intensite * part),
                "conscience_mika",
            )
            moteur._rumination_bleed_at[etiquette] = maintenant
        except Exception as exc:
            degradations.record("conscience: rumination emotional bleed", exc)


# ── Naissance ─────────────────────────────────────────────────────


async def promote_stale_to_ruminations() -> None:
    """Convert recent skipped/stale pertinent observations into ruminations.

    Called from `entretien.mark_stale_observations` when observations age
    out. An observation with pertinence >= 0.5 that was never acted upon
    becomes a Rumination — Mika keeps thinking about it.
    """
    try:
        from conscience.models import Observation, Rumination
    except ImportError:
        return

    from django.utils import timezone as tz
    from datetime import timedelta

    cutoff = tz.now() - timedelta(minutes=pending_window_minutes())
    window_start = tz.now() - timedelta(hours=2)

    porte = cfg_float(
        "conscience.promotion.rumination_pertinence", PROMOTION_PERTINENCE,
    )
    actives_max = cfg_int(
        "conscience.promotion.rumination_actives_max", PROMOTION_ACTIVES_MAX,
        mini=1,
    )

    # Garde de volume, dans le **même** callable synchrone que la sélection
    # qui suit : une pensée de plus n'est pas une pensée mieux pensée, et
    # sans plafond l'ouverture de la porte installerait une pression
    # permanente sur le Facteur 10.
    try:
        deja_actives = await sync_to_async(
            lambda: Rumination.objects.filter(status="active").count()
        )()
    except Exception as exc:
        degradations.record("conscience: comptage des ruminations actives", exc)
        return
    if deja_actives >= actives_max:
        return

    try:
        pertinent_stale = await sync_to_async(
            lambda: list(
                Observation.objects.filter(
                    status="skipped",
                    pertinence__gte=porte,
                    created_at__gte=window_start,
                    created_at__lt=cutoff,
                ).exclude(
                    id__in=Rumination.objects.filter(
                        observation__isnull=False
                    ).values_list("observation_id", flat=True)
                )[:5]
            )
        )()
    except Exception as exc:
        degradations.record("conscience: stale observations to promote", exc)
        return

    for obs in pertinent_stale:
        try:
            await sync_to_async(Rumination.objects.create)(
                summary=obs.summary,
                themes=themes_de(obs),
                intensity=min(1.0, obs.pertinence),
                emotion=obs.emotional_reaction or "",
                observation=obs,
                status="active",
                origine=Rumination.Origine.OBSERVATION,
            )
            logger.debug(
                "Promoted observation %d to rumination (p=%.2f)",
                obs.id, obs.pertinence,
            )
        except Exception as exc:
            degradations.record("conscience: rumination creation", exc)


# ── Le retour d'un absent ─────────────────────────────────────────


async def le_retour_d_un_absent(moteur) -> None:
    """Résout avec joie les pensées d'absents dont la personne a réécrit.

    Balayage étranglé (5 min) et payé seulement s'il existe des pensées
    nostalgiques à thème nominal — jamais sur le chemin chaud d'un
    message entrant. Le nom se résout par la couche identité au moment du
    scan, jamais à l'écriture ; le brief interne d'un acte est exclu, ou
    son propre message vers X compterait comme le retour de X. Ne lève
    jamais.
    """
    try:
        maintenant = time.monotonic()
        if (
            moteur._dernier_retour_scan
            and maintenant - moteur._dernier_retour_scan
            < _RETOUR_SCAN_INTERVAL_S
        ):
            return
        moteur._dernier_retour_scan = maintenant

        from conscience.models import Rumination

        def _pensees() -> list[dict]:
            from django.db.models import Q

            # Les pensées de MANQUE, par origine — une pensée d'audit
            # dérivée vers `nostalgic` dont le premier thème est un
            # prénom n'est pas quelqu'un qui manque. Le repli sur
            # l'émotion ne vaut que pour les lignes sans origine.
            return list(
                Rumination.objects.filter(status="active")
                .filter(
                    Q(origine=Rumination.Origine.MANQUE)
                    | Q(origine="", emotion="nostalgic")
                )
                .exclude(themes=[])
                .values("id", "themes", "created_at")[:5]
            )

        pensees = await sync_to_async(_pensees)()
        pensees = [p for p in pensees if p.get("themes")]
        if not pensees:
            return

        from identity.resolver import identity_resolver

        noms = sorted({str(p["themes"][0]) for p in pensees})
        handle_map = await identity_resolver.handles_for_entity_names(noms)

        revenus = 0
        for pensee in pensees:
            nom = str(pensee["themes"][0])
            pids = {h["person_id"] for h in handle_map.get(nom, [])}
            if not pids:
                continue

            def _reecrit(pids=tuple(pids), depuis=pensee["created_at"]):
                from memory.models import Message

                return (
                    Message.objects.filter(
                        person_id__in=list(pids), role="user",
                        created_at__gt=depuis,
                    )
                    .exclude(is_internal=True)
                    .exists()
                )

            if not await sync_to_async(_reecrit)():
                continue
            fait = await sync_to_async(
                lambda pk=pensee["id"]: Rumination.objects.filter(
                    pk=pk, status="active",
                ).update(status="resolved"),
                thread_sensitive=True,
            )()
            if fait:
                revenus += 1
                logger.info("Retour d'un absent : %s a redonné signe", nom)

        if revenus:
            from emotion.types import Emotion, EmotionData

            emotion_engine.process_emotion(
                EmotionData(Emotion.HAPPY, _RETOUR_ABSENT_JOIE),
                "conscience_mika",
            )
    except Exception as exc:
        degradations.record("conscience: retour d'un absent", exc)


# ── L'audit d'après-coup ──────────────────────────────────────────


def audit_trop_recent(moteur, person_id: str) -> bool:
    """Vrai si cette personne a déjà eu son audit dans la fenêtre.

    Un audit par personne et par demi-heure : se rejouer une phrase est
    un battement, pas un régime. Douze tours chargés d'affilée
    écrivaient douze pensées, et le Facteur 10 restait cloué à +0.30
    pendant les ~9 h que met la demi-vie à les dissoudre. Mémo posé par
    ``getattr`` — les tests construisent le moteur par ``__new__``.
    """
    memo = getattr(moteur, "_audits_recents", None)
    if not memo:
        return False
    fenetre = cfg_int(
        "conscience.audit.espacement_s", _AUDIT_ESPACEMENT_S, mini=0,
    )
    dernier = memo.get(str(person_id))
    return dernier is not None and (time.monotonic() - dernier) < fenetre


def noter_audit(moteur, person_id: str) -> None:
    """Marque l'audit de cette personne — à la TENTATIVE d'écriture, pas
    au succès (la leçon du murmure) : une base illisible ne doit pas
    relancer l'audit à chaque tour."""
    memo = getattr(moteur, "_audits_recents", None)
    if memo is None:
        memo = {}
        moteur._audits_recents = memo
    memo[str(person_id)] = time.monotonic()
    while len(memo) > _AUDIT_MEMO_MAX_CLES:
        memo.pop(next(iter(memo)))


async def post_action_audit(
    moteur,
    response_text: str,
    emotion_name: str,
    intensity: float,
    person_id: str,
) -> None:
    """After Mika speaks, maybe create a micro-rumination capturing
    self-evaluation of what she just said.

    Fires only for emotionally marked responses (in _AUDIT_EMOTIONS)
    with intensity >= 0.55. Creates a low-intensity Rumination that
    will decay over the next few cycles — a brief "did I say that
    right?" beat. Cheap, heuristic, no LLM call.

    Skipped for internal-trigger speech (conscience already acted,
    would cause a feedback loop of self-ruminations).

    Deux bornes, parce qu'une conversation animée en produisait une par
    tour : **un audit par personne par fenêtre** (`audit_trop_recent`,
    mémo RAM) et **un plafond de micro-ruminations d'audit actives**
    (`conscience.audit.actives_max`) — au-delà, la plus faible se fane
    avant que la nouvelle ne s'écrive, dans le même callable synchrone.
    """
    if person_id == "conscience_mika":
        return
    if moteur._audit_trop_recent(person_id):
        return
    seuil = cfg_float(
        "conscience.audit.min_intensity", _AUDIT_MIN_INTENSITY,
        mini=0.0, maxi=1.0,
    )
    # L'estime module l'auto-critique : quand elle doute d'elle, elle se
    # rejoue plus facilement ; sûre d'elle, moins. C'est le premier effet
    # comportemental de la valeur propre — et il ne touche pas le score.
    with degraded("conscience: estime dans l'audit"):
        seuil += (
            await estime.lire() - estime.BASELINE
        ) * _AUDIT_ESTIME_PENTE
    if intensity < seuil:
        return
    # Les 29 émotions, pas neuf. La table de gabarits en couvrait neuf, si
    # bien qu'un tour `melancholic` à 0.9 ne se rejouait JAMAIS pendant
    # qu'un tour `proud` à 0.56 se rejouait toujours avec la même phrase.
    # La cible et le registre se dérivent maintenant de l'ancre PAD que
    # `emotion/pad.py` déclare déjà.
    #
    # `Emotion(...)` sous garde : `emotion_name` vient du bus, donc d'une
    # sortie de modèle, et un nom inventé ne doit pas tuer le tour.
    from emotion.types import Emotion

    try:
        emotion = Emotion(emotion_name)
    except ValueError:
        return

    tuning = vecu_tuning()
    cible = cible_de_derive(emotion, tuning)
    if cible is Emotion.NEUTRAL:
        # Un tour trop tiède pour laisser une trace : ne rien écrire est la
        # bonne réponse, pas écrire une rumination neutre.
        return

    excerpt = response_text.strip()[:80].replace("\n", " ")
    if not excerpt:
        return
    summary = phrase_de_rejeu(emotion, excerpt, tuning=tuning)
    if not summary:
        return
    rumination_emotion = cible.value
    # Intensity starts modest — a normal person doesn't obsess, just
    # replays once or twice. Scales with how emotional the reply was.
    rumination_intensity = round(min(
        cfg_float("conscience.audit.max_intensity",
                  _AUDIT_MAX_INTENSITY, mini=0.0, maxi=1.0),
        cfg_float("conscience.audit.base_intensity",
                  _AUDIT_BASE_INTENSITY, mini=0.0, maxi=1.0)
        + (intensity - seuil) * cfg_float(
            "conscience.audit.slope", _AUDIT_SLOPE, mini=0.0),
    ), 3)

    try:
        from conscience.models import Rumination
    except ImportError:
        return

    plafond = cfg_int(
        "conscience.audit.actives_max", _AUDIT_ACTIVES_MAX, mini=1,
    )

    def _ecrire() -> int:
        """Plafonne PUIS écrit — un seul callable synchrone.

        Les pensées d'audit se reconnaissent à leur forme : sans
        observation source et sans thème. Quand le plafond est atteint,
        la plus faible se fane (jamais supprimée : la nuit la relit) pour
        que la nouvelle prenne sa place — la dernière réponse est celle
        qu'on se rejoue, pas la douzième d'avant.
        """
        from django.db.models import Q

        # L'origine d'abord ; la forme (sans observation, sans thème) ne
        # vaut que pour les lignes d'avant la migration, qui n'ont pas
        # d'origine. Une pensée promue dont l'observation a été purgée
        # n'est plus prise pour un audit.
        audits = Rumination.objects.filter(status="active").filter(
            Q(origine=Rumination.Origine.AUDIT)
            | Q(origine="", observation__isnull=True, themes=[])
        )
        fanees = 0
        surplus = audits.count() - (plafond - 1)
        if surplus > 0:
            faibles = list(
                audits.order_by("intensity", "pk")
                .values_list("pk", flat=True)[:surplus]
            )
            fanees = Rumination.objects.filter(
                pk__in=faibles, status="active",
            ).update(status="faded")
        Rumination.objects.create(
            summary=summary,
            themes=[],
            intensity=rumination_intensity,
            emotion=rumination_emotion,
            observation=None,
            status="active",
            origine=Rumination.Origine.AUDIT,
        )
        return fanees

    noter_audit(moteur, person_id)
    try:
        fanees = await sync_to_async(_ecrire, thread_sensitive=True)()
        logger.debug(
            "Post-action audit created rumination (%s, %.2f, %d fanée(s)): %s",
            rumination_emotion, rumination_intensity, fanees, excerpt[:40],
        )
    except Exception as exc:
        degradations.record("conscience: post-action audit", exc)
