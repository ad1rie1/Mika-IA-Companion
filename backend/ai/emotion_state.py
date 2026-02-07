import time
from collections import deque
from dataclasses import dataclass, field

from ai.emotion_types import Emotion, EmotionCategory, EMOTION_CATEGORIES


@dataclass(frozen=True)
class Temperament:
    """Personality-driven parameters that affect emotional behavior."""
    volatility: float = 0.7       # 0.0=very stable, 1.0=very volatile
    intensity_base: float = 0.6   # amplifies or dampens reactions
    recovery_speed: float = 0.5   # how fast emotions decay back to default mood
    default_mood: Emotion = Emotion.HAPPY
    global_bleed: float = 0.3     # how much individual interactions bleed into global mood


@dataclass
class EmotionHistoryEntry:
    """Single entry in an emotion timeline."""
    timestamp: float
    emotion: Emotion
    intensity: float
    source: str  # "claude", "decay", "opposition", "reinforcement"


@dataclass
class PersonMood:
    """Per-person emotional state. Tracks how the VTuber feels about one specific person."""
    person_id: str
    emotion: Emotion = Emotion.NEUTRAL
    intensity: float = 0.0
    momentum: float = 0.0  # resistance to change, builds with reinforcement
    last_interaction: float = field(default_factory=time.time)
    last_update: float = field(default_factory=time.time)
    history: deque[EmotionHistoryEntry] = field(
        default_factory=lambda: deque(maxlen=100)
    )

    def to_dict(self) -> dict:
        return {
            "emotion": self.emotion.value,
            "intensity": round(self.intensity, 2),
            "momentum": round(self.momentum, 2),
        }

    def to_prompt_description(self) -> str:
        if self.intensity < 0.1:
            return "Tu n'as pas de sentiment particulier envers cette personne."

        intensity_word = _intensity_label(self.intensity)
        return (
            f"Envers cette personne, tu te sens {intensity_word} "
            f"{self.emotion.value} (intensite: {self.intensity:.1f})."
        )


@dataclass
class GlobalMood:
    """Global emotional state, independent of who is talking."""
    emotion: Emotion = Emotion.NEUTRAL
    intensity: float = 0.0
    momentum: float = 0.0
    last_update: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "emotion": self.emotion.value,
            "intensity": round(self.intensity, 2),
        }

    def to_prompt_description(self, default_mood: Emotion) -> str:
        if self.intensity < 0.1 or self.emotion == default_mood:
            return f"Ton humeur generale est {default_mood.value}, comme d'habitude."

        intensity_word = _intensity_label(self.intensity)
        return (
            f"Ton humeur generale en ce moment est {intensity_word} "
            f"{self.emotion.value} (intensite: {self.intensity:.1f}), "
            f"alors que normalement tu es plutot {default_mood.value}."
        )


@dataclass(frozen=True)
class MessageEmotion:
    """Computed emotion for a specific message: blend of person + global + context."""
    emotion: Emotion
    intensity: float
    person_emotion: Emotion
    person_intensity: float
    global_emotion: Emotion
    global_intensity: float

    def to_dict(self) -> dict:
        return {
            "emotion": self.emotion.value,
            "intensity": round(self.intensity, 2),
        }


def _intensity_label(intensity: float) -> str:
    if intensity >= 0.8:
        return "tres"
    elif intensity >= 0.5:
        return "assez"
    elif intensity >= 0.3:
        return "legerement"
    else:
        return "a peine"
