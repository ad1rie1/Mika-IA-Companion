"""Les affects de la vie intérieure — ce que le vide, l'attente, l'échec
social et le futur font à son humeur.

Sorti de ``engine.py`` sur le modèle de ``travaux.py`` : des fonctions de
module prenant le moteur. L'état qu'elles mutent (``_dernier_ennui``,
``_detresse_depuis``, ``_ignores_vus``, ``_dernier_espoir``, le mémo du
manque) reste un attribut de CLASSE du moteur — les tests le construisent
par ``__new__`` et un état posé seulement dans ``__init__`` tomberait sur un
``AttributeError``. Les constantes, elles, sont de la famille des ancres PAD
(la physique du personnage) et vivent ici, au niveau du module, où la garde
AST de ``test_config_rapatriement`` confronte chaque repli au défaut déclaré.
"""

from __future__ import annotations

import logging
import time

from configs.runtime import cfg_float, cfg_int
from conscience import estime
from conscience.reglages import ignored_reply_window_minutes
from conscience.types import DecisionContext
from drives.engine import drive_engine
from emotion.engine import emotion_engine
from utils.degradation import degradations

logger = logging.getLogger(__name__)

#: Replis de l'ennui — clés `conscience.ennui.*`.
_ENNUI_IDLE_MINUTES = 120
#: L'ennui est un ÉTAT TENU, dosé comme un plateau : 0,2 toutes les dix
#: minutes, et non 0,4 par demi-heure. Sous τ_global = 23 min, une dose
#: demi-horaire retombait de 0,36 à 0,10 d'écart entre deux impulsions —
#: une dent de scie où le prompt alternait « comme d'habitude » et
#: « lasse ». À 0,2 / 10 min le régime permanent est un écart de ~0,25
#: (« légèrement lasse ») qui ne bouge plus.
_ENNUI_INTENSITE = 0.2
#: Espacement des glissements (RAM). L'ennui teinte, il ne matraque pas :
#: sans cet espacement, la boucle enverrait une impulsion toutes les 30 s
#: pendant toute l'après-midi vide — même leçon que la saignée des
#: ruminations.
_ENNUI_INTERVAL_S = 600.0
#: Le manque de QUELQU'UN (``who_misses_contact``) n'est vérifié qu'à cet
#: espacement pendant le vide — trois requêtes bornées, une fois par
#: demi-heure, jamais à chaque cycle.
_MANQUE_INTERVAL_S = 1800.0
#: Tension SOCIAL à partir de laquelle le vide se ressent comme de la
#: SOLITUDE plutôt que de l'ennui. `lonely` n'était produit nulle part
#: par la vie interne : SOCIAL débordait en *score* (elle agissait),
#: jamais en *ressenti* — le parallèle exact de l'ennui d'avant son
#: correctif. S'ennuyer, c'est ne rien avoir à faire ; se sentir seule,
#: c'est vouloir quelqu'un. Alignée sur la porte d'élargissement de la
#: trousse (0.50 la saillance « réelle ») + une marge : la solitude est
#: un sentiment plus rare que l'envie de compagnie.
_SOLITUDE_PORTE_SOCIAL = 0.6

#: La détresse — quand ça va mal, on va vers quelqu'un. Les seuils : une
#: valence franchement négative (l'ancre PAD de l'humeur), une intensité
#: qui se sent, et de la DURÉE — un pic de contrariété n'est pas une
#: détresse, un quart d'heure sombre en est une. Constantes de la famille
#: des ancres PAD, pas des clés.
_DETRESSE_VALENCE_MAX = -0.35
_DETRESSE_INTENSITE_MIN = 0.55
_DETRESSE_DUREE_MIN_S = 900.0

#: L'anticipation — la moitié manquante de la vie émotionnelle : elle
#: avait un passé riche (souvenirs, journal, rêves) et aucun futur vécu.
#: Un rendez-vous proche et prioritaire, ou un chantier à un pas du bout,
#: glisse l'humeur vers l'espoir. Mêmes principes que l'ennui : une
#: teinte espacée, jamais un matraquage, et des constantes de la famille
#: des ancres PAD.
_ESPOIR_INTERVAL_S = 1800.0
_ESPOIR_INTENSITE = 0.25
#: Un rendez-vous « proche » : dans l'heure, et qui compte vraiment.
_ESPOIR_FENETRE_MIN = 60
#: 0,5 et non 0,6 : `schedule_action` pose 0,5 par défaut, si bien qu'à
#: 0,6 un rendez-vous ordinaire — « rappelle-moi de… » — ne faisait
#: jamais espérer. Un rendez-vous qu'elle s'est donné compte ; seul un
#: « tiède » (< 0,5, fixé explicitement) ne compte pas.
_ESPOIR_PRIORITE_MIN = 0.5


# ── L'ennui, ou la solitude ───────────────────────────────────────


def le_vide_est_la(moteur, ctx: DecisionContext, travaux: list) -> float:
    """L'intensité du glissement d'ennui dû maintenant, ou 0.

    Quatre conditions, toutes nécessaires : éveillée (dormir n'est pas
    s'ennuyer), rien à observer, aucun chantier en cours (travailler
    n'est pas s'ennuyer), et un long silence — puis l'espacement. Pure
    RAM, ne lève jamais ; marque l'espacement quand elle répond oui.
    """
    try:
        if ctx.sleep_phase != "awake":
            return 0.0
        if ctx.pending_observations or travaux:
            return 0.0
        porte_s = cfg_int(
            "conscience.ennui.idle_minutes", _ENNUI_IDLE_MINUTES,
            mini=1,
        ) * 60
        if ctx.idle_seconds < porte_s:
            return 0.0
        intensite = cfg_float(
            "conscience.ennui.intensite", _ENNUI_INTENSITE,
            mini=0.0, maxi=1.0,
        )
        if intensite <= 0.0:
            return 0.0
        maintenant = time.monotonic()
        if (
            moteur._dernier_ennui
            and maintenant - moteur._dernier_ennui < _ENNUI_INTERVAL_S
        ):
            return 0.0
        moteur._dernier_ennui = maintenant
        return intensite
    except Exception as exc:
        degradations.record("conscience: portes de l'ennui", exc)
        return 0.0


async def quelquun_lui_manque(moteur) -> bool:
    """Y a-t-il UNE personne dont le silence dépasse le rythme du lien ?

    La solitude tenait à une tension globale (SOCIAL ≥ 0,6 ≈ 18 h de
    silence) : long pour quelqu'un qui a un ami quotidien, et aveugle à
    qui manque. ``who_misses_contact`` mesure déjà le manque au rythme de
    chaque relation pour choisir un destinataire ; ici il colore
    l'affect. Vérifié au plus toutes les ``_MANQUE_INTERVAL_S`` (le verdict
    est mis en cache), jamais à chaque cycle. Ne lève jamais.
    """
    maintenant = time.monotonic()
    if (
        moteur._manque_verifie_le
        and maintenant - moteur._manque_verifie_le < _MANQUE_INTERVAL_S
    ):
        return moteur._manque_present
    moteur._manque_verifie_le = maintenant
    try:
        memoire = getattr(moteur, "memory", None)
        if memoire is None:
            moteur._manque_present = False
        else:
            candidats = await memoire.who_misses_contact(n=1)
            moteur._manque_present = bool(candidats)
    except Exception as exc:
        degradations.record("conscience: manque pour la solitude", exc)
        moteur._manque_present = False
    return moteur._manque_present


async def peut_etre_s_ennuyer(
    moteur, ctx: DecisionContext, travaux: list,
) -> None:
    """Le vide prolongé glisse l'humeur vers l'ennui — ou la solitude.

    L'intensité reste sous la porte de débordement d'humeur : l'ennui
    colore le visage, le murmure et le vécu — il ne force jamais une
    prise de parole à lui seul, mais il donne à « ouvrir un chantier » la
    raison lisible qui manquait. Ne lève jamais.
    """
    intensite = le_vide_est_la(moteur, ctx, travaux)
    if intensite <= 0.0:
        return
    try:
        from emotion.types import Emotion, EmotionData

        # Le même vide n'a pas la même couleur selon ce qui manque :
        # rien à faire → ennui ; quelqu'un → solitude. Quelqu'un manque
        # quand une relation a dépassé son propre rythme de silence
        # (``quelquun_lui_manque``), ou, à défaut de relation lisible,
        # quand SOCIAL est haut pendant une longue absence — « je veux
        # de la compagnie », pas « je veux de l'occupation ».
        emotion = Emotion.BORED
        try:
            from drives.state import DriveKind

            social = float(drive_engine.states[DriveKind.SOCIAL].tension)
        except Exception as exc:
            degradations.record("conscience: tension sociale illisible", exc)
            social = 0.0
        if social >= _SOLITUDE_PORTE_SOCIAL or await quelquun_lui_manque(moteur):
            emotion = Emotion.LONELY

        emotion_engine.process_emotion(
            EmotionData(emotion, intensite), "conscience_mika",
        )
        logger.debug(
            "Vide prolongé: glissement vers %s (%.2f)",
            emotion.value, intensite,
        )
    except Exception as exc:
        degradations.record("conscience: glissement d'ennui", exc)


# ── La détresse ───────────────────────────────────────────────────


def suivre_la_detresse(moteur, ctx: DecisionContext) -> None:
    """Suivre si l'humeur sombre DURE. Appelé à chaque cycle, mutation
    pure-RAM, ne lève jamais. La détection et la lecture sont séparées :
    celle-ci doit tourner même les tours où elle ne parle pas, sinon la
    durée ne se mesure jamais."""
    try:
        from emotion import pad
        from emotion.types import Emotion

        sombre = (
            pad.valence(Emotion(ctx.global_mood)) <= _DETRESSE_VALENCE_MAX
            and ctx.global_intensity >= _DETRESSE_INTENSITE_MIN
        )
    except Exception:
        sombre = False
    if sombre:
        if not moteur._detresse_depuis:
            moteur._detresse_depuis = time.monotonic()
    else:
        moteur._detresse_depuis = 0.0


def detresse_soutenue(moteur) -> bool:
    """L'humeur est-elle sombre depuis assez longtemps pour chercher du
    réconfort ?"""
    return bool(
        moteur._detresse_depuis
        and time.monotonic() - moteur._detresse_depuis
        >= _DETRESSE_DUREE_MIN_S
    )


# ── L'estime sociale ──────────────────────────────────────────────


async def suivre_l_estime_sociale(moteur, ctx: DecisionContext) -> None:
    """Être ignorée entame la valeur propre ; une réponse qui rompt la
    série la répare — un peu plus qu'un coup, le soulagement de « je
    compte encore ».

    Le jugement attend que la fenêtre de réponse du dernier acte soit
    écoulée : `introspect` compte « ignoré » tout acte encore sans
    réponse, y compris celui d'il y a une minute — juger pendant la
    fenêtre prendrait un coup d'estime à CHAQUE initiative, réponse ou
    pas. Ne lève jamais.
    """
    try:
        fenetre_s = ignored_reply_window_minutes() * 60
        if (
            moteur._last_action_time
            and time.time() - moteur._last_action_time < fenetre_s
        ):
            return  # le verdict du dernier acte n'est pas encore tombé
        vus = moteur._ignores_vus
        courant = ctx.consecutive_ignored_acts
        moteur._ignores_vus = courant
        if courant > vus:
            await estime.ressentir(
                estime.COUP_INITIATIVE_IGNOREE, "initiative ignorée",
            )
        elif vus > 0 and courant == 0:
            await estime.ressentir(
                estime.COUP_SERIE_ROMPUE, "on m'a répondu",
            )
    except Exception as exc:
        degradations.record("conscience: estime sociale", exc)


# ── L'espoir ──────────────────────────────────────────────────────


async def peut_etre_esperer(moteur, ctx: DecisionContext, travaux: list) -> None:
    """Quelque chose de bien approche : l'humeur glisse vers l'espoir.

    Deux sources, la moins chère d'abord : un **chantier à un pas du
    bout** (gratuit — la liste est déjà en main), sinon un **rendez-vous
    dans l'heure** assez prioritaire (une requête bornée, payée seulement
    après l'étranglement). Peut cohabiter avec l'ennui dans le même
    cycle : une après-midi vide où on attend quelqu'un est exactement ce
    mélange-là. Ne lève jamais.
    """
    try:
        if ctx.sleep_phase != "awake":
            return
        maintenant = time.monotonic()
        if (
            moteur._dernier_espoir
            and maintenant - moteur._dernier_espoir < _ESPOIR_INTERVAL_S
        ):
            return
        # Marqué à la TENTATIVE, pas au succès — la leçon du murmure :
        # sans ça, chaque cycle sans espoir repaye la requête des
        # rendez-vous à venir, 2 880 fois par jour.
        moteur._dernier_espoir = maintenant

        presque_fini = any(
            t.pas_max
            and t.pas_effectues >= t.pas_max - 1
            and not t.en_attente_de_reponse
            for t in (travaux or ())
        )
        rendez_vous_proche = False
        if not presque_fini:
            for action, minutes in await moteur._get_upcoming_actions():
                if (
                    minutes <= _ESPOIR_FENETRE_MIN
                    and getattr(action, "priority", 0.0)
                    >= _ESPOIR_PRIORITE_MIN
                ):
                    rendez_vous_proche = True
                    break
        if not (presque_fini or rendez_vous_proche):
            return

        from emotion.types import Emotion, EmotionData

        emotion_engine.process_emotion(
            EmotionData(Emotion.HOPEFUL, _ESPOIR_INTENSITE),
            "conscience_mika",
        )
        logger.debug(
            "Anticipation: glissement vers hopeful (%s)",
            "chantier presque au bout" if presque_fini else "rendez-vous proche",
        )
    except Exception as exc:
        degradations.record("conscience: glissement d'espoir", exc)
