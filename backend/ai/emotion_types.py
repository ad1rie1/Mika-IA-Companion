import re
from enum import Enum
from dataclasses import dataclass


class EmotionCategory(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    COMPLEX = "complex"
    NEUTRAL_CAT = "neutral"


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


EMOTION_CATEGORIES: dict[Emotion, EmotionCategory] = {
    Emotion.NEUTRAL: EmotionCategory.NEUTRAL_CAT,
    # Positive
    Emotion.HAPPY: EmotionCategory.POSITIVE,
    Emotion.EXCITED: EmotionCategory.POSITIVE,
    Emotion.LOVE: EmotionCategory.POSITIVE,
    Emotion.PROUD: EmotionCategory.POSITIVE,
    Emotion.GRATEFUL: EmotionCategory.POSITIVE,
    Emotion.PLAYFUL: EmotionCategory.POSITIVE,
    Emotion.AMUSED: EmotionCategory.POSITIVE,
    Emotion.HOPEFUL: EmotionCategory.POSITIVE,
    Emotion.RELIEVED: EmotionCategory.POSITIVE,
    # Negative
    Emotion.SAD: EmotionCategory.NEGATIVE,
    Emotion.ANGRY: EmotionCategory.NEGATIVE,
    Emotion.SCARED: EmotionCategory.NEGATIVE,
    Emotion.DISGUSTED: EmotionCategory.NEGATIVE,
    Emotion.FRUSTRATED: EmotionCategory.NEGATIVE,
    Emotion.LONELY: EmotionCategory.NEGATIVE,
    Emotion.ANXIOUS: EmotionCategory.NEGATIVE,
    Emotion.BORED: EmotionCategory.NEGATIVE,
    Emotion.JEALOUS: EmotionCategory.NEGATIVE,
    # Complex
    Emotion.SURPRISED: EmotionCategory.COMPLEX,
    Emotion.THINKING: EmotionCategory.COMPLEX,
    Emotion.CONFUSED: EmotionCategory.COMPLEX,
    Emotion.EMBARRASSED: EmotionCategory.COMPLEX,
    Emotion.NOSTALGIC: EmotionCategory.COMPLEX,
    Emotion.DREAMY: EmotionCategory.COMPLEX,
    Emotion.DETERMINED: EmotionCategory.COMPLEX,
    Emotion.MISCHIEVOUS: EmotionCategory.COMPLEX,
    Emotion.CURIOUS: EmotionCategory.COMPLEX,
    Emotion.MELANCHOLIC: EmotionCategory.COMPLEX,
}

# Opposite category mapping for emotion opposition detection
OPPOSITE_CATEGORIES: dict[EmotionCategory, EmotionCategory] = {
    EmotionCategory.POSITIVE: EmotionCategory.NEGATIVE,
    EmotionCategory.NEGATIVE: EmotionCategory.POSITIVE,
}

# Transition naturalness overrides: (from, to) -> 0.0-1.0
# 1.0 = perfectly natural, 0.0 = very abrupt
# Missing pairs use category-based defaults (see EmotionEngine)
TRANSITION_OVERRIDES: dict[tuple[Emotion, Emotion], float] = {
    # Very natural pairs
    (Emotion.SAD, Emotion.ANGRY): 0.9,
    (Emotion.SAD, Emotion.LONELY): 0.95,
    (Emotion.ANGRY, Emotion.FRUSTRATED): 0.95,
    (Emotion.HAPPY, Emotion.EXCITED): 0.95,
    (Emotion.HAPPY, Emotion.PLAYFUL): 0.9,
    (Emotion.HAPPY, Emotion.LOVE): 0.85,
    (Emotion.CURIOUS, Emotion.THINKING): 0.95,
    (Emotion.CURIOUS, Emotion.EXCITED): 0.85,
    (Emotion.THINKING, Emotion.CONFUSED): 0.9,
    (Emotion.SURPRISED, Emotion.HAPPY): 0.85,
    (Emotion.SURPRISED, Emotion.SCARED): 0.85,
    (Emotion.EMBARRASSED, Emotion.SAD): 0.8,
    (Emotion.NOSTALGIC, Emotion.SAD): 0.85,
    (Emotion.NOSTALGIC, Emotion.HAPPY): 0.7,
    (Emotion.BORED, Emotion.FRUSTRATED): 0.85,
    (Emotion.ANXIOUS, Emotion.SCARED): 0.9,
    (Emotion.ANXIOUS, Emotion.RELIEVED): 0.85,
    (Emotion.DETERMINED, Emotion.PROUD): 0.85,
    (Emotion.MISCHIEVOUS, Emotion.PLAYFUL): 0.9,
    (Emotion.MISCHIEVOUS, Emotion.AMUSED): 0.85,
    (Emotion.MELANCHOLIC, Emotion.NOSTALGIC): 0.95,
    (Emotion.MELANCHOLIC, Emotion.SAD): 0.9,
    (Emotion.LONELY, Emotion.SAD): 0.9,
    (Emotion.GRATEFUL, Emotion.HAPPY): 0.9,
    (Emotion.RELIEVED, Emotion.HAPPY): 0.85,
    # Abrupt / unnatural pairs
    (Emotion.ANGRY, Emotion.LOVE): 0.2,
    (Emotion.SAD, Emotion.EXCITED): 0.25,
    (Emotion.SCARED, Emotion.PLAYFUL): 0.2,
    (Emotion.BORED, Emotion.LOVE): 0.25,
    (Emotion.DISGUSTED, Emotion.LOVE): 0.15,
    (Emotion.JEALOUS, Emotion.GRATEFUL): 0.2,
}

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
