"""Percevoir — recevoir un événement, l'interpréter, le filtrer, le ranger.

Le premier étage du moteur (« 1. OBSERVE »), sorti de ``engine.py`` sur le
modèle de ``travaux.py`` : des fonctions de module prenant le moteur, jamais
une classe collaboratrice, parce que les tests construisent le moteur par
``__new__`` et patchent SES méthodes. ``observe`` orchestre donc à travers
la surface du moteur (``moteur._habituer``, ``moteur._store_observation``,
``moteur._spawn_decision``…) pour qu'un patch posé là continue de porter.

L'entrée est perçue AVEC son état — le déficit transversal du dossier
psychologique : l'affect colorait la sortie (prompt, voix, rappel) mais
jamais l'ENTRÉE. Chez l'humain, l'émotion est un filtre de perception avant
d'être une couleur d'expression — et le répété s'efface (habituation),
l'apprentissage le plus élémentaire. Constantes de la famille des ancres PAD.
"""

from __future__ import annotations

import logging
import time

from asgiref.sync import sync_to_async

from configs.runtime import cfg_float
from conscience.scoring import SLEEP_WAKE_PERTINENCE
from conscience.types import InterpretedSignal
from drives.engine import drive_engine
from emotion.engine import emotion_engine
from modules.types import ModuleEvent
from utils.degradation import degradations

logger = logging.getLogger(__name__)

#: Fenêtre de l'habituation : le même type d'événement de la même source,
#: répété dans cette fenêtre, pèse de moins en moins.
_HABITUATION_FENETRE_S = 600.0
#: Amortissement par répétition (0.85^n), et plancher — le quarantième
#: titre n'est pas rien, il est juste devenu du fond sonore.
_HABITUATION_AMORTISSEMENT = 0.85
_HABITUATION_PLANCHER = 0.4
#: Bornes RAM du mémo.
_HABITUATION_MAX_OCCURRENCES = 20
_HABITUATION_MAX_CLES = 200

#: Congruence d'humeur à l'entrée : un signal dont la réaction
#: émotionnelle va dans le sens de l'humeur courante pèse un peu plus —
#: la vigilance anxieuse, l'élargissement joyeux. Borné petit (±15 %) et
#: **amorti ×0.5 quand l'humeur est négative** : le même anti-spirale que
#: le rappel congruent, sans quoi « sombre → signaux sombres plus
#: pertinents → plus sombre » s'auto-entretient.
_MOOD_ENTREE_POIDS = 0.15
_MOOD_ENTREE_AMORTI_NEGATIF = 0.5

#: Budget d'affect par SOURCE et par fenêtre : la somme des intensités
#: qu'une source peut injecter dans l'humeur en dix minutes. L'habituation
#: amortit chaque impulsion (plancher 0,4), mais quinze impulsions amorties
#: font encore ~1,9 d'intensité cumulée — de quoi franchir la porte de
#: débordement. Un budget dit : un flux, une boîte mail, c'est UNE source
#: d'émotion, pas quinze.
_AFFECT_BUDGET_PAR_SOURCE = 0.6
_AFFECT_FENETRE_S = 600.0
_AFFECT_MAX_CLES = 200


async def observe(moteur, event: ModuleEvent) -> None:
    """Receive a module event, interpret it, store it.

    Called by the event bus (ModuleManager.emit_event callback).
    If the signal is important enough, immediately creates a souvenir.
    Emotional reactions from interpreted signals feed into the EmotionEngine
    so the VTuber actually *feels* what she observes.
    """
    signal = await moteur.interpreter.interpret(event)

    # Percevoir AVEC son état, avant tout le reste : l'habituation
    # (le répété s'efface) puis la congruence d'humeur (bornée,
    # anti-spirale). Placées ici, elles gatent tout l'aval — souvenir
    # immédiat, urgence accumulée, fast-path, graines de chantier —
    # exactement comme un filtre d'attention humain.
    pertinence_brute = signal.pertinence
    signal.pertinence = moteur._habituer(
        event.source_module, event.event_type, signal.pertinence,
    )
    # Le facteur d'habituation vaut pour l'AFFECT aussi : il n'amortissait
    # que la pertinence, et `_feed_emotion` injectait l'intensité brute —
    # quinze titres RSS appariés à `curious 0.25` faisaient déborder
    # l'humeur (mesuré : dix impulsions → 0,82, au-dessus de la porte
    # 0,7), donc une prise de parole « parce que je suis curieuse », et
    # la congruence d'entrée renchérissait sur les titres suivants.
    facteur_habituation = (
        signal.pertinence / pertinence_brute if pertinence_brute > 1e-9 else 1.0
    )
    signal.pertinence = moteur._colorer_par_l_humeur(
        signal.pertinence, signal.emotional_reaction,
    )

    observation = await moteur._store_observation(event, signal)

    # Feed emotional reaction into the EmotionEngine — habituée, puis
    # dosée par source : une source ne peut pas mouvoir l'humeur de plus
    # d'un budget par fenêtre, quel que soit le nombre d'événements.
    if signal.emotional_reaction and signal.emotional_intensity > 0.1:
        signal.emotional_intensity = moteur._doser_l_affect(
            event.source_module,
            signal.emotional_intensity * facteur_habituation,
        )
        if signal.emotional_intensity > 0.05:
            moteur._feed_emotion(signal)

    # Immediate memory action for high-pertinence signals
    if signal.should_remember and signal.pertinence > 0.5:
        souvenir = await moteur.memory.create_souvenir_from_signal(signal)
        if souvenir and observation:
            observation.souvenir = souvenir
            await sync_to_async(observation.save)(update_fields=["souvenir"])

    # Track activity for idle detection
    if event.event_type in ("chat.message", "telegram.message"):
        moteur.note_activity()
        # L'assouvissement de SOCIAL/CURIOSITY par un message n'est plus
        # décidé ici : c'est une politique des pulsions, déclarée dans
        # drives/apps.py sur `_turn.completed`, donc valable pour tout
        # canal d'entrée et non pour les seuls noms d'événements listés
        # ci-dessus.
    else:
        # External signal (email, RSS, schedule) — feeds curiosity
        # proportionally to pertinence.
        drive_engine.on_observation(signal.pertinence)

    logger.debug(
        "Observed: %s/%s → %s (p=%.1f)",
        event.source_module, event.event_type,
        signal.category, signal.pertinence,
    )

    # Fast-path: critical signals trigger an immediate decision cycle.
    # Scheduled, not awaited: observe() is called from inside
    # ModuleManager.emit_event, which the email/RSS pollers await. Running
    # the decision inline blocked the emitting module's loop for the two
    # LLM calls (_act's recipient selection + the full pipeline) that a
    # pertinent signal triggers.
    # Même barre que le veto de sommeil du scoring, et **une seule clé**
    # pour les deux : la faire diverger produirait une conscience qui se
    # réveille pour un signal qu'elle refusera ensuite de traiter.
    # `>=` et non `>` : `scoring.py` compare la même clé avec `>=`, si bien
    # qu'une pertinence pile sur la barre réveillait la décision sans que
    # le fast-path la déclenche, et inversement selon le chemin emprunté.
    if signal.pertinence >= cfg_float(
        "conscience.sleep_wake_pertinence", SLEEP_WAKE_PERTINENCE,
    ):
        logger.info(
            "High-pertinence signal (%.2f), triggering immediate decision",
            signal.pertinence,
        )
        moteur._spawn_decision()


def habituer(moteur, source: str, event_type: str, pertinence: float) -> float:
    """Amortit la pertinence d'un signal répété. Ne lève jamais.

    Le mémo est en RAM (perdre l'habituation au redémarrage coûte au
    pire un signal compté plein une fois de trop) et posé par ``getattr``
    — les tests construisent le moteur par ``__new__``.
    """
    try:
        memo = getattr(moteur, "_habituation", None)
        if memo is None:
            memo = {}
            moteur._habituation = memo
        cle = (str(source), str(event_type))
        maintenant = time.monotonic()
        recents = [
            t for t in memo.get(cle, ())
            if maintenant - t < _HABITUATION_FENETRE_S
        ]
        deja = len(recents)
        recents.append(maintenant)
        memo[cle] = recents[-_HABITUATION_MAX_OCCURRENCES:]
        if len(memo) > _HABITUATION_MAX_CLES:
            memo.pop(next(iter(memo)))
        if deja == 0:
            return pertinence
        facteur = max(
            _HABITUATION_PLANCHER,
            _HABITUATION_AMORTISSEMENT ** deja,
        )
        return pertinence * facteur
    except Exception as exc:
        degradations.record("conscience: habituation", exc)
        return pertinence


def doser_l_affect(moteur, source: str, intensite: float) -> float:
    """Rogne l'intensité au budget restant de la source. Ne lève jamais.

    Mémo RAM posé par ``getattr`` (moteurs construits par ``__new__``).
    Le dosage est enregistré sur ce qui est *réellement* injecté, jamais
    sur la demande : une demande refusée ne consomme rien.
    """
    try:
        intensite = max(0.0, float(intensite))
        if intensite <= 0.0:
            return 0.0
        memo = getattr(moteur, "_affect_par_source", None)
        if memo is None:
            memo = {}
            moteur._affect_par_source = memo
        cle = str(source)
        maintenant = time.monotonic()
        recents = [
            (t, i) for t, i in memo.get(cle, ())
            if maintenant - t < _AFFECT_FENETRE_S
        ]
        consomme = sum(i for _, i in recents)
        reste = max(0.0, _AFFECT_BUDGET_PAR_SOURCE - consomme)
        dose = min(intensite, reste)
        if dose > 0.0:
            recents.append((maintenant, dose))
        memo[cle] = recents
        if len(memo) > _AFFECT_MAX_CLES:
            memo.pop(next(iter(memo)))
        return dose
    except Exception as exc:
        degradations.record("conscience: dosage de l'affect", exc)
        return intensite


def colorer_par_l_humeur(pertinence: float, reaction: str) -> float:
    """Module légèrement la pertinence par la congruence avec l'humeur.

    Ne touche que les signaux émotionnellement typés (la plupart des
    heuristiques ne le sont pas — modulation conservatrice par
    construction), n'amplifie jamais de plus de ±15 %, et jamais
    au-dessus de 1.0. Ne lève jamais.
    """
    if not reaction:
        return pertinence
    try:
        from emotion import pad
        from emotion.types import Emotion

        ancre = pad.EMOTION_ANCHORS.get(Emotion(reaction))
        humeur = emotion_engine.global_mood.dynamic.position
        # L'écart au repos, quand le repos est connu : au repos, la
        # position absolue est positive (la teinte de l'heure) et tout
        # signal positif pesait +15 % sans qu'elle ressente rien.
        repos = getattr(emotion_engine.global_mood, "home", None)
        if repos is not None:
            humeur = pad.sub(humeur, repos)
        if not ancre:
            return pertinence
        na, nh = pad.norm(ancre), pad.norm(humeur)
        if na < 1e-6 or nh < 1e-6:
            return pertinence
        cos = pad.dot(ancre, humeur) / (na * nh)
        if cos <= 0.0:
            return pertinence
        poids = _MOOD_ENTREE_POIDS
        if humeur[0] < 0:
            poids *= _MOOD_ENTREE_AMORTI_NEGATIF
        return min(1.0, pertinence * (1.0 + poids * cos))
    except Exception as exc:
        degradations.record("conscience: congruence d'entree", exc)
        return pertinence


def feed_emotion(signal: InterpretedSignal) -> None:
    """Inject an interpreted signal's emotional reaction into the EmotionEngine.

    Uses person_id "conscience_mika" — the VTuber feeling something
    from her own observation, not from a conversation partner.
    """
    from emotion.types import Emotion, EmotionData

    try:
        emotion = Emotion(signal.emotional_reaction)
    except ValueError:
        logger.debug(
            "Unknown emotion from signal: %s", signal.emotional_reaction
        )
        return

    data = EmotionData(emotion=emotion, intensity=signal.emotional_intensity)
    emotion_engine.process_emotion(data, "conscience_mika")
    logger.debug(
        "Fed emotion %s:%.2f from observation into EmotionEngine",
        emotion.value, signal.emotional_intensity,
    )


async def store_observation(event, signal):
    """Persist an observation to DB."""
    from conscience.models import Observation

    try:
        # Les thèmes ont leur champ (migration conscience/0013) ET
        # restent recopiés dans raw_data : les lignes d'avant migration
        # n'ont que raw_data, et `themes_de` lit les deux dans cet
        # ordre — le champ d'abord, la convention en repli.
        raw_data = dict(event.data or {})
        raw_data["themes"] = signal.themes
        # Les entités nommées par l'interprétation mouraient à la
        # frontière (produites, jamais persistées) alors qu'elles sont
        # exactement ce qu'un rappel dirigé ou un routage par personne
        # peut exploiter plus tard.
        raw_data["entities"] = [str(e) for e in (signal.entities or []) if e]

        return await sync_to_async(Observation.objects.create)(
            source=event.source_module,
            event_type=event.event_type,
            raw_data=raw_data,
            themes=list(signal.themes or []),
            summary=signal.summary,
            category=signal.category,
            pertinence=signal.pertinence,
            emotional_reaction=signal.emotional_reaction,
            emotional_intensity=signal.emotional_intensity,
        )
    except Exception:
        logger.exception("Failed to store observation")
        return None
