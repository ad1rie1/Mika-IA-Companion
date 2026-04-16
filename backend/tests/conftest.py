"""
Shared fixtures for the VTuber test suite.

Provides fresh EmotionEngine instances, temperament presets,
and conversation simulation helpers.
"""

import time
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
