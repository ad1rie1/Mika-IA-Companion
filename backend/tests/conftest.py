"""
Shared fixtures for the VTuber test suite.

Provides fresh EmotionEngine instances, temperament presets,
and conversation simulation helpers.
"""

import time
from unittest.mock import patch

import pytest

from emotion.types import Emotion, EmotionData
from emotion.state import Temperament, PersonMood, GlobalMood
from emotion.engine import EmotionEngine
from emotion import pad


# ---------------------------------------------------------------------------
# Temperament presets (different VTuber "personalities" for testing)
# ---------------------------------------------------------------------------

TEMPERAMENT_DEFAULT = Temperament(
    volatility=0.7,
    intensity_base=0.6,
    recovery_speed=0.5,
    default_mood=Emotion.HAPPY,
    global_bleed=0.3,
)

TEMPERAMENT_STOIC = Temperament(
    volatility=0.2,
    intensity_base=0.3,
    recovery_speed=0.8,
    default_mood=Emotion.NEUTRAL,
    global_bleed=0.1,
)

TEMPERAMENT_EXPLOSIVE = Temperament(
    volatility=0.95,
    intensity_base=0.9,
    recovery_speed=0.2,
    default_mood=Emotion.EXCITED,
    global_bleed=0.7,
)

TEMPERAMENT_MELANCHOLIC = Temperament(
    volatility=0.5,
    intensity_base=0.7,
    recovery_speed=0.3,
    default_mood=Emotion.MELANCHOLIC,
    global_bleed=0.4,
)


# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------

def _make_engine(temperament: Temperament) -> EmotionEngine:
    e = EmotionEngine()
    e.temperament = temperament
    e.global_mood = GlobalMood()
    e._recompute_params()
    e._initialized = True
    return e


@pytest.fixture
def engine() -> EmotionEngine:
    """Fresh EmotionEngine with default Mika temperament (no async init)."""
    return _make_engine(TEMPERAMENT_DEFAULT)


@pytest.fixture
def stoic_engine() -> EmotionEngine:
    """EmotionEngine with stoic temperament — hard to move emotionally."""
    return _make_engine(TEMPERAMENT_STOIC)


@pytest.fixture
def explosive_engine() -> EmotionEngine:
    """EmotionEngine with explosive temperament — reacts strongly to everything."""
    return _make_engine(TEMPERAMENT_EXPLOSIVE)


@pytest.fixture
def melancholic_engine() -> EmotionEngine:
    """EmotionEngine with melancholic temperament — defaults to sadness."""
    return _make_engine(TEMPERAMENT_MELANCHOLIC)


# ---------------------------------------------------------------------------
# Lectures de configuration sans base
# ---------------------------------------------------------------------------

@pytest.fixture
def config_hors_base():
    """``config_service.get`` servi depuis le registre, jamais depuis la base.

    Opt-in (``pytest.mark.usefixtures``), pas autouse : la majorité de la
    suite décrit justement le stockage de la configuration. C'est pour les
    tests qui décrivent autre chose et lisent des réglages en passant — le
    routeur IA lit ``ai.quota.*``, ``ai.call_timeout_seconds`` et
    ``ai.<provider>.max_concurrent_calls`` à *chaque* appel routé.

    ``ConfigService.get`` ne retombe sur le défaut de schéma qu'après avoir
    essayé la base, et cet essai devient fatal quand deux états laissés par
    des tests antérieurs se rencontrent : le cache de valeurs vidé
    (``invalidate_cache()``) et une connexion ouverte dans le thread
    ``config-db`` par un test ``django_db``. La lecture part alors hors
    boucle, où ``close_old_connections()`` précède le ``except`` de
    ``_fetch_value_row`` censé absorber une base illisible, et le blocage de
    pytest-django remonte intact jusqu'à l'appelant. D'où des tests verts
    seuls, rouges dans la suite complète — et, entre les deux, incapables de
    signaler la régression qu'ils prétendent surveiller.

    Le défaut du registre est exactement ce que rend ``get`` sans ligne en
    base, c'est-à-dire ce sur quoi tourne une installation neuve.
    """
    from configs.registry import registry
    from configs.service import config_service

    absent = object()

    def _defaut_declare(key, default=absent):
        item = registry.get(key)
        if item is not None:
            return item.default
        if default is not absent:
            return default
        raise KeyError(f"Unknown config key: {key}")

    with patch.object(config_service, "get", side_effect=_defaut_declare):
        yield


# ---------------------------------------------------------------------------
# Conversation simulation helpers
# ---------------------------------------------------------------------------

class ConversationTurn:
    """One exchange in a simulated conversation."""

    def __init__(
        self,
        user_message: str,
        ai_response: str,
        emotion: Emotion,
        intensity: float,
        delay_seconds: float = 0.0,
    ):
        self.user_message = user_message
        self.ai_response = ai_response
        self.emotion = emotion
        self.intensity = intensity
        self.delay_seconds = delay_seconds

    @property
    def emotion_data(self) -> EmotionData:
        return EmotionData(emotion=self.emotion, intensity=self.intensity)


def play_conversation(
    engine: EmotionEngine,
    person_id: str,
    turns: list[ConversationTurn],
    apply_decay_between_turns: bool = True,
) -> list[dict]:
    """
    Play through a conversation, processing each emotion through the engine.

    Returns a list of snapshots (one per turn) with the engine state after
    each turn, for assertions.
    """
    snapshots = []
    for turn in turns:
        # Simulate time passing between turns
        if turn.delay_seconds > 0 and apply_decay_between_turns:
            simulate_time_decay(engine, turn.delay_seconds)

        # Process the AI's emotion through the engine
        person_mood = engine.process_emotion(turn.emotion_data, person_id)
        msg_emotion = engine.compute_message_emotion(person_id)

        snapshots.append({
            "turn": turn,
            "person_mood": {
                "emotion": person_mood.emotion,
                "intensity": person_mood.intensity,
            },
            "global_mood": {
                "emotion": engine.global_mood.emotion,
                "intensity": engine.global_mood.intensity,
            },
            "message_emotion": {
                "emotion": msg_emotion.emotion,
                "intensity": msg_emotion.intensity,
            },
        })

    return snapshots


def simulate_time_decay(engine: EmotionEngine, seconds: float):
    """
    Simulate the passage of time by backdating last_update timestamps
    and running _apply_decay() once.

    This avoids needing async sleep in tests — we just pretend time passed.
    """
    offset = seconds
    now = time.time()
    past = now - offset

    # Backdate all person moods
    for person in engine.person_moods.values():
        person.last_update = past

    # Backdate global mood
    engine.global_mood.last_update = past

    # Run decay once (it uses time.time() internally)
    engine._apply_decay()


@pytest.fixture(autouse=True)
def _dates_d_historique_vierges():
    """Le mémo id → ``created_at`` de ``pipeline.context_history`` est de portée
    process. En production ``created_at`` ne change jamais et un id n'est
    jamais réutilisé ; sous pytest, un test transactionnel annulé rend son
    compteur d'ids, et le test suivant peut recréer le pk 3 avec une autre
    date — le mémo servirait alors un horodatage d'un autre test. Vidé avant
    chaque test ; autouse parce que le piège est invisible depuis le test
    qui le subit."""
    from pipeline import context_history

    context_history._MESSAGE_DATES.clear()
    yield
    context_history._MESSAGE_DATES.clear()


@pytest.fixture(autouse=True)
def _un_public_est_present():
    """Un acte sans destinataire ET sans navigateur connecté n'a plus lieu
    (CONS-11) : la garde `ConscienceEngine._audience_presente` retient
    l'acte. Aucun test du moteur n'enregistre de présence, et tous ceux qui
    font agir la conscience supposaient implicitement qu'on l'entendait —
    c'est cette supposition qu'on rend explicite ici. Un test qui veut le
    silence pose son propre `patch` par-dessus, et gagne."""
    from unittest.mock import patch

    with patch(
        "conscience.engine.ConscienceEngine._audience_presente", return_value=True,
    ):
        yield


@pytest.fixture(autouse=True)
def _extraction_sans_cadence():
    """Le consolidateur n'extrait plus une fenêtre dès le premier message :
    elle part mûre (≥ N messages) ou calme (rien depuis 5 min), jamais sur
    une question dont la réponse est attendue (MEM-04 / MEM-10). Les tests
    existants créent un ou deux messages « maintenant » et consolident tout
    de suite : ils mesurent la sélection, pas la cadence. Celle-ci est donc
    coupée par défaut ; les tests de la cadence la rallument sur l'instance."""
    from unittest.mock import patch

    with patch(
        "memory.storage.consolidator.MemoryConsolidator._cadence_extraction", False,
    ):
        yield
