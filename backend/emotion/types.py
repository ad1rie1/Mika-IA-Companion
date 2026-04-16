import re
from enum import Enum
from dataclasses import dataclass


class Emotion(str, Enum):
    # --- Neutral ---
    NEUTRAL = "neutral"

    # --- Positive ---
    HAPPY = "happy"
    EXCITED = "excited"
    LOVE = "love"
    PROUD = "proud"
    GRATEFUL = "grateful"
    PLAYFUL = "playful"
    AMUSED = "amused"
    HOPEFUL = "hopeful"
    RELIEVED = "relieved"

    # --- Negative ---
    SAD = "sad"
    ANGRY = "angry"
    SCARED = "scared"
    DISGUSTED = "disgusted"
    FRUSTRATED = "frustrated"
    LONELY = "lonely"
    ANXIOUS = "anxious"
    BORED = "bored"
    JEALOUS = "jealous"

    # --- Complex ---
    SURPRISED = "surprised"
    THINKING = "thinking"
    CONFUSED = "confused"
    EMBARRASSED = "embarrassed"
    NOSTALGIC = "nostalgic"
    DREAMY = "dreamy"
    DETERMINED = "determined"
    MISCHIEVOUS = "mischievous"
    CURIOUS = "curious"
    MELANCHOLIC = "melancholic"


# Regex for [EMOTION:name:intensity] or [EMOTION:name]
EMOTION_PATTERN = re.compile(r"\[EMOTION:(\w+)(?::(\d+\.?\d*))?\]")


@dataclass(frozen=True)
class EmotionData:
    """Immutable result from parsing an emotion tag."""
    emotion: Emotion
    intensity: float  # 0.0 to 1.0

    @staticmethod
    def default() -> "EmotionData":
        return EmotionData(emotion=Emotion.NEUTRAL, intensity=0.5)


def extract_emotion(text: str) -> tuple[str, EmotionData]:
    """Extract emotion tag from Claude's response.

    Supports:
    - [EMOTION:happy] (legacy, defaults to intensity 0.7)
    - [EMOTION:happy:0.8] (new format with explicit intensity)

    Returns (clean_text, EmotionData).
    """
    match = EMOTION_PATTERN.search(text)
    if match:
        emotion_str = match.group(1).lower()
        intensity_str = match.group(2)
        clean_text = EMOTION_PATTERN.sub("", text).strip()

        try:
            emotion = Emotion(emotion_str)
        except ValueError:
            emotion = Emotion.NEUTRAL

        intensity = float(intensity_str) if intensity_str else 0.7
        intensity = max(0.0, min(1.0, intensity))

        return clean_text, EmotionData(emotion=emotion, intensity=intensity)

    return text.strip(), EmotionData.default()
