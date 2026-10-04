"""Le murmure : entendre l'intention se former.

``pipeline.inner_voice.generate_inner_thought`` produit la pensée que Mika
marmonne pendant qu'elle travaille — *« oh tiens, si j'écrivais à Alice… »*.
Elle n'a qu'un seul appelant, ``projects.runner._murmur``, et cet appelant
rend la main quand ``emotion_policy == "off"``. Or OFF est le **défaut** d'un
projet. Résultat mesurable : le murmure n'est jamais sorti une seule fois.

Ce module est le second appelant, celui de la conscience — le lieu où une
intention se forme sans qu'un projet existe. Il ne génère rien lui-même : il
**décide**, puis délègue la génération à ``inner_voice`` et la diffusion à
``pipeline.broadcast``.

Deux propriétés structurent tout le fichier.

**Les six gardes passent AVANT l'appel LLM.** La boucle de conscience tourne
toutes les 30 s, soit 2 880 tours par jour ; un murmure coûte un appel de
modèle. Une garde placée après l'appel ne protège rien du tout — elle jette
un jeton déjà payé. C'est aussi pourquoi le quota et le délai ne comptent pas
la même chose : le **délai** espace les *tentatives* (il borne la dépense), le
**quota** compte les murmures *réellement émis* (il borne ce qu'on entend).
Un modèle qui rend ``None`` a coûté un appel et n'a rien produit : il consomme
le délai, jamais le quota.

**Un murmure part sans ``person_id``, toujours.** C'est un piège réel, pas une
précaution de style : ``broadcast_to_websocket`` résout le ``person_id`` dans
le registre de présence, et un ``target`` non vide fait passer
``voice.persona_for_source(..., addressed=True)`` en persona **SPEAKING**.
Sur un canal qui porte un ``VOICE_SINK`` — Telegram — SPEAKING signifie *note
vocale envoyée sur le téléphone de quelqu'un*. Une pensée murmurée n'est
adressée à personne ; expédiée, elle devient une intrusion. Sans ``person_id``
la diffusion tombe sur le groupe global, la persona reste INNER (« conscience »
appartient à ``voice.INNER_SOURCES``), et le frontend applique le profil
murmuré (plus bas, plus lent, deux fois moins fort).

Le module ne lit **aucune configuration** : ses réglages vivent dans une
dataclasse gelée sur le modèle de ``conscience.scoring.ScoringTuning``, dont
les défauts *sont* les constantes. La résolution depuis le registre se fera au
bord, à l'intégration.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date

from old.backend.utils.degradation import degradations

logger = logging.getLogger(__name__)


# ``source`` de la trame diffusée. La valeur n'est pas décorative :
# ``pipeline.voice.INNER_SOURCES`` la contient, et c'est *elle* qui décide de
# la persona. La changer pour un nom plus parlant (« murmure ») rendrait la
# pensée SPEAKING sans qu'aucun test de ce fichier ne bouge — celui de
# ``test_murmure_conscience.py`` qui épingle l'appartenance existe pour ça.
SOURCE_MURMURE = "conscience"

# L'émotion portée par la trame. Un murmure est une pensée en cours de
# formation, pas une déclaration affective : `thinking` à basse intensité
# donne au frontend de quoi animer sans déclencher un geste one-shot.
EMOTION_MURMURE = "thinking"
INTENSITE_MURMURE = 0.3


# ── Les réplis, au niveau module ─────────────────────────────────
#
# Écrits ici et non en défauts littéraux de la dataclasse pour la même raison
# que ``SLEEP_WAKE_PERTINENCE`` dans ``conscience.scoring`` : quand la
# résolution au bord arrivera, elle s'écrira
# ``cfg_int("conscience.murmure.quota_quotidien", MURMURE_QUOTA_QUOTIDIEN)`` —
# un repli ``ast.Name`` que la garde de ``test_config_rapatriement`` sait
# résoudre en attribut de module, là où un ``MurmureTuning().quota_quotidien``
# serait ignoré en silence et laisserait le défaut déclaré libre de dériver.

#: Murmures effectivement émis dans une journée locale. Huit, parce qu'un
#: murmure est un événement rare par nature : au-delà, ce n'est plus une
#: pensée surprise en passant, c'est un commentaire continu.
MURMURE_QUOTA_QUOTIDIEN = 8

#: Secondes entre deux **tentatives**. C'est la borne de dépense : à 600 s la
#: conscience peut au pire dépenser 144 appels par jour, et le quota en laisse
#: passer 8 à l'oreille.
MURMURE_DELAI_MIN_SECONDES = 600.0

#: Coupe de sécurité côté sortie.
MURMURE_LONGUEUR_MAX = 160

#: Fenêtre de la garde d'anti-répétition.
MURMURE_FENETRE_REPETITION_SECONDES = 3600.0

#: Murmurer pendant le sommeil.
MURMURE_ENDORMIE = False


@dataclass(frozen=True)
class MurmureTuning:
    """Les bornes du murmure, avec les valeurs d'origine pour défauts.

    Gelée et sans lecture de registre, comme ``ScoringTuning`` : les tests
    doivent mesurer la calibration *déclarée*, pas la base de la machine qui
    les exécute. Un ``MurmureTuning()`` sans argument est le comportement de
    référence.
    """

    #: Murmures effectivement émis dans une journée locale.
    quota_quotidien: int = MURMURE_QUOTA_QUOTIDIEN

    #: Secondes entre deux **tentatives**. Le délai s'applique même quand le
    #: modèle a rendu None — sinon un modèle en échec serait rappelé à chacun
    #: des tours de conscience, toutes les 30 s.
    delai_min_secondes: float = MURMURE_DELAI_MIN_SECONDES

    #: Coupe de sécurité côté sortie. ``inner_voice`` plafonne déjà, mais il
    #: le fait depuis *sa* configuration : le murmure ne doit pas grandir
    #: parce qu'un autre réglage a bougé.
    longueur_max: int = MURMURE_LONGUEUR_MAX

    #: Fenêtre de la garde d'anti-répétition (voir ``decider_murmure``).
    fenetre_repetition_secondes: float = MURMURE_FENETRE_REPETITION_SECONDES

    #: Murmurer pendant le sommeil. Faux par défaut — et ce n'est **pas** un
    #: doublon de ``voice.decide_voice`` : la branche SCREEN y laisse
    #: délibérément passer une pensée INNER même endormie (c'est ce qui rend
    #: la nuit habitée plutôt que muette), elle ne refuse que la parole
    #: *adressée*. Le silence nocturne, si on le veut, ne peut donc être
    #: décidé qu'ici — et il doit l'être ici de toute façon, puisque c'est le
    #: seul endroit qui précède la dépense. Passer à ``True`` rend la nuit
    #: bavarde sans toucher à la politique vocale.
    murmurer_endormie: bool = MURMURE_ENDORMIE


#: Réglage par défaut partagé : le construire une fois évite de rebâtir la
#: dataclasse à chaque tour de la boucle.
DEFAULT_TUNING = MurmureTuning()


@dataclass(frozen=True)
class DecisionMurmure:
    """Murmurer ou non, et pourquoi.

    La raison est journalisée et lisible depuis ``etat_murmure()`` : un
    silence dont on ne sait pas s'il est voulu ou cassé est exactement le
    défaut que ce moteur passe son temps à produire.
    """

    murmure: bool
    raison: str


# ── La décision, pure ────────────────────────────────────────────


def decider_murmure(
    *,
    intention: str,
    mode_professionnel: bool = False,
    phase_sommeil: str = "awake",
    audience: bool = True,
    emis_ce_jour: int = 0,
    secondes_depuis_tentative: float | None = None,
    intention_precedente: str = "",
    secondes_depuis_intention: float | None = None,
    tuning: MurmureTuning = DEFAULT_TUNING,
) -> DecisionMurmure:
    """Faut-il murmurer maintenant ? Fonction **pure**, tout entre par
    paramètre — la politique entière se teste sans moteur qui tourne, comme
    ``voice.decide_voice`` et ``conscience.scoring``.

    ``secondes_depuis_tentative`` / ``secondes_depuis_intention`` valent
    ``None`` quand l'événement n'a jamais eu lieu (premier murmure du
    process) : ``None`` veut dire *il y a une éternité*, pas *à l'instant*.

    Les six gardes, dans l'ordre où elles tombent :

    1. **mode professionnel** — un projet en ``emotion_policy=off`` déclare
       « aucun raisonnement affectif » ; un marmonnement affectif au milieu
       en est un. C'est la garde que ``projects.runner`` appliquait déjà, et
       qui, faute de second appelant, tenait le murmure muet à elle seule.
    2. **sommeil** — voir ``MurmureTuning.murmurer_endormie``.
    3. **audience** — un murmure sans public n'est pas émis. Ce n'est pas de
       la pudeur, c'est la garde de coût la plus rentable : la trame part sur
       le groupe global, et un ``group_send`` vers un groupe vide est perdu
       en silence. Payer un appel de modèle pour l'alimenter, c'est payer
       pour rien.
    4. **délai minimal** entre deux tentatives — borne la dépense.
    5. **quota quotidien** de murmures émis — borne ce qu'on entend.
    6. **anti-répétition** (celle de conception, justifiée ci-dessous).

    La sixième existe parce que la conscience re-score *le même* contexte
    accumulé à chaque tour : tant que rien ne consomme les observations en
    attente, l'intention qu'elles produisent est identique d'un cycle au
    suivant. Sans cette garde, le quota se dépense en huit exemplaires de la
    même pensée et le délai ne fait que les espacer — on entend un bégaiement
    plutôt qu'une intention. Elle compare l'intention *normalisée*, pas la
    pensée générée : deux formulations différentes de la même intention
    doivent être refusées, et c'est l'intention qu'on connaît avant l'appel.
    """
    if not (intention or "").strip():
        # Pré-contrôle de validité plutôt qu'une garde : ``inner_voice``
        # rendrait None de toute façon, mais après avoir été awaité.
        return DecisionMurmure(False, "no_intention")

    if mode_professionnel:
        return DecisionMurmure(False, "professional_mode")

    if phase_sommeil != "awake" and not tuning.murmurer_endormie:
        return DecisionMurmure(False, f"asleep({phase_sommeil})")

    if not audience:
        return DecisionMurmure(False, "no_audience")

    if (
        secondes_depuis_tentative is not None
        and secondes_depuis_tentative < tuning.delai_min_secondes
    ):
        return DecisionMurmure(False, "too_soon")

    if emis_ce_jour >= tuning.quota_quotidien:
        return DecisionMurmure(False, "daily_quota_exhausted")

    if (
        intention_precedente
        and _normaliser(intention) == _normaliser(intention_precedente)
        and secondes_depuis_intention is not None
        and secondes_depuis_intention < tuning.fenetre_repetition_secondes
    ):
        return DecisionMurmure(False, "same_intention")

    return DecisionMurmure(True, "murmur_ok")


def _normaliser(texte: str) -> str:
    """Forme comparable d'une intention : casse et espacement ne distinguent
    pas deux intentions, ils distinguent deux façons de l'écrire."""
    return " ".join((texte or "").casefold().split())


# ── L'état, en RAM et volontairement ─────────────────────────────


@dataclass
class _EtatMurmure:
    """Ce que le process a déjà murmuré. En RAM, comme les pulsions : un
    redémarrage remet le compteur à zéro, et c'est le bon comportement — le
    quota borne le bavardage d'une journée qui tourne, pas une dette."""

    jour: date | None = None
    emis_ce_jour: int = 0
    #: Horloge **monotone** : le délai mesure une durée écoulée, il ne doit
    #: pas sauter avec un changement d'heure ni avec un ajustement NTP.
    derniere_tentative: float | None = None
    derniere_intention: str = ""
    derniere_intention_at: float | None = None
    derniere_raison: str = ""


_ETAT = _EtatMurmure()


def reinitialiser_etat() -> None:
    """Remet le compteur à neuf (tests, et rien d'autre)."""
    global _ETAT
    _ETAT = _EtatMurmure()


def etat_murmure() -> dict:
    """Vue JSON-safe de l'état, pour un panneau ou un test.

    Rend aussi la dernière raison : « elle n'a pas murmuré » et « elle n'a
    pas pu murmurer » sont deux faits différents, et seul le second se
    répare.
    """
    return {
        "jour": _ETAT.jour.isoformat() if _ETAT.jour else None,
        "emis_ce_jour": _ETAT.emis_ce_jour,
        "derniere_intention": _ETAT.derniere_intention,
        "derniere_raison": _ETAT.derniere_raison,
    }


def _jour_courant() -> date:
    """La journée locale, à l'horloge dont tout le reste du moteur date ses
    journées (``conscience.read.debut_du_jour_local``). Pas ``localdate()`` :
    entre minuit et l'aube il décale d'un jour, et le quota se rouvrirait au
    mauvais moment."""
    from old.backend.conscience.read import debut_du_jour_local

    return debut_du_jour_local().date()


def _rouler_le_jour() -> None:
    """Ouvre une nouvelle journée si l'horloge a passé minuit local."""
    try:
        jour = _jour_courant()
    except Exception as exc:
        # Sans horloge lisible on garde la journée en cours : le quota reste
        # fermé plutôt que de se rouvrir en boucle sur une lecture cassée.
        degradations.record("murmure: bornes du jour", exc)
        return
    if _ETAT.jour != jour:
        _ETAT.jour = jour
        _ETAT.emis_ce_jour = 0


# ── Les lectures de contexte vivant ──────────────────────────────


def _phase_sommeil() -> str:
    """Phase courante, ``awake`` si le cycle est illisible.

    Repli **ouvert** : un sous-système absent ne doit pas rendre Mika muette
    pour la vie du process. Ce qui borne la dépense, ce sont le délai et le
    quota, qui ne dépendent d'aucun sous-système. ``pipeline.broadcast``
    retombe déjà sur ``awake`` de la même façon."""
    try:
        from old.backend.memory.sleep import sleep_cycle

        return str(sleep_cycle.phase)
    except Exception as exc:
        degradations.record("murmure: lecture de phase de sommeil", exc)
        return "awake"


def _audience_presente() -> bool:
    """Y a-t-il un client connecté pour entendre ?

    Repli **fermé**, à l'inverse du précédent : ne pas savoir s'il y a un
    public n'est pas une raison de payer un appel pour un groupe vide. Les
    cibles module (Telegram) ne comptent pas — un murmure ne part jamais sur
    un canal push, c'est précisément ce que la persona INNER interdit.
    """
    try:
        from old.backend.communication.presence import presence_registry

        return any(cible.is_consumer for cible in presence_registry.reachable())
    except Exception as exc:
        degradations.record("murmure: lecture de presence", exc)
        return False


# ── Les deux délégations (seams de test) ─────────────────────────


async def _generer_pensee(intention: str, resultat: str, *, mood: str) -> str | None:
    """Délègue à ``inner_voice``. Import tardif : ce module est importé par la
    conscience, qui n'a aucune raison de tirer le routeur IA au chargement."""
    from old.backend.pipeline.inner_voice import generate_inner_thought

    return await generate_inner_thought(intention, resultat, mood=mood)


async def _diffuser(pensee: str) -> None:
    """Pousse le murmure par la route de parole normale.

    **Aucun ``person_id``** — voir l'en-tête du module. L'appel est écrit
    sans le paramètre plutôt qu'avec ``person_id=None`` : un ``None`` se
    remplace d'un caractère, une absence se remarque.
    """
    from old.backend.emotion.types import Emotion, EmotionData
    from old.backend.pipeline.broadcast import broadcast_to_websocket
    from old.backend.pipeline.processor import SpeechOutput

    await broadcast_to_websocket(
        SpeechOutput(
            text=pensee,
            emotion_data=EmotionData(Emotion.THINKING, INTENSITE_MURMURE),
            emotion_name=EMOTION_MURMURE,
            emotion_intensity=INTENSITE_MURMURE,
            emotion_state={},
            tool_calls=[],
        ),
        source=SOURCE_MURMURE,
    )


# ── Le point d'entrée ────────────────────────────────────────────


async def murmurer(
    intention: str,
    resultat: str = "",
    *,
    mood: str = "neutral",
    mode_professionnel: bool = False,
    tuning: MurmureTuning = DEFAULT_TUNING,
    maintenant: float | None = None,
) -> str | None:
    """Décide, génère et diffuse le murmure. Rend le texte émis, ou ``None``.

    ``intention`` est ce qu'elle s'apprête à faire, ``resultat`` ce qui vient
    d'en revenir. ``mode_professionnel`` est fourni par l'appelant (le runner
    le tient dans ``ctx.emotion_policy``, la conscience dans le contexte de
    projet qu'elle a déjà assemblé) : lire les projets ici coûterait une
    requête à chacun des 2 880 tours quotidiens pour une garde qui, presque
    toujours, ne se déclenche pas.

    **Le silence est une sortie valide** et il ne lève jamais. Cette fonction
    est appelée depuis des boucles que personne ne supervise : une exception
    qui s'échappe tue la boucle pour la vie du process. Un échec n'est pas
    non plus transformé en contenu — on ne diffuse jamais un message d'erreur
    déguisé en pensée.
    """
    try:
        return await _murmurer(
            intention, resultat, mood=mood,
            mode_professionnel=mode_professionnel,
            tuning=tuning, maintenant=maintenant,
        )
    except Exception as exc:
        # Tout ce qui n'a pas déjà été rattrapé plus bas : le murmure est un
        # ornement, il ne fait tomber ni la conscience ni le runner.
        degradations.record("murmure: tour de murmure", exc)
        return None


async def _murmurer(
    intention: str,
    resultat: str,
    *,
    mood: str,
    mode_professionnel: bool,
    tuning: MurmureTuning,
    maintenant: float | None,
) -> str | None:
    horloge = time.monotonic() if maintenant is None else maintenant

    _rouler_le_jour()

    decision = decider_murmure(
        intention=intention,
        mode_professionnel=mode_professionnel,
        phase_sommeil=_phase_sommeil(),
        audience=_audience_presente(),
        emis_ce_jour=_ETAT.emis_ce_jour,
        secondes_depuis_tentative=_ecart(_ETAT.derniere_tentative, horloge),
        intention_precedente=_ETAT.derniere_intention,
        secondes_depuis_intention=_ecart(_ETAT.derniere_intention_at, horloge),
        tuning=tuning,
    )
    _ETAT.derniere_raison = decision.raison
    if not decision.murmure:
        logger.debug("Pas de murmure: %s", decision.raison)
        return None

    # Marqué AVANT l'appel : la tentative est ce qui coûte, et elle a lieu
    # même si le modèle rend None ou lève. La marquer après laisserait deux
    # tours de conscience concurrents partir ensemble sur un modèle lent.
    _ETAT.derniere_tentative = horloge

    pensee = await _generer_pensee(intention, resultat, mood=mood)
    if not pensee:
        # Le modèle n'a rien eu à dire, ou l'appel a échoué (``inner_voice``
        # rend None dans les deux cas et ne lève pas). Le quota compte des
        # murmures entendus : un appel sans sortie l'aurait dépensé pour du
        # silence.
        logger.debug("Murmure généré vide — silence")
        return None

    pensee = pensee.strip()[: max(1, tuning.longueur_max)].strip()
    if not pensee:
        return None

    # Consommé ici, avant la diffusion : la pensée existe et a été payée.
    # Un échec de diffusion est une question de livraison, pas une raison de
    # rendre un jeton et de refaire l'appel au tour suivant.
    _ETAT.emis_ce_jour += 1
    _ETAT.derniere_intention = intention
    _ETAT.derniere_intention_at = horloge

    try:
        await _diffuser(pensee)
    except Exception as exc:
        # Un murmure non livré est perdu — personne ne le redemandera par
        # curseur, il n'est pas persisté. Il se compte plutôt que de finir
        # dans un log que personne ne suit.
        degradations.record("murmure: diffusion", exc)
        return None

    logger.info("Murmure: %s", pensee)
    return pensee


def _ecart(depuis: float | None, horloge: float) -> float | None:
    """Durée écoulée, ou ``None`` quand l'événement n'a jamais eu lieu."""
    if depuis is None:
        return None
    return max(0.0, horloge - depuis)
