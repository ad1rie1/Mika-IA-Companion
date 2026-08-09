import re
from enum import Enum
from dataclasses import dataclass

from utils.degradation import degradations


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
        """A deliberate neutral, for a caller who wants one.

        Not what "no tag" produces — `extract_emotion` returns ``None`` there,
        and rewiring it back here would restore the bug this replaced.
        """
        return EmotionData(emotion=Emotion.NEUTRAL, intensity=0.5)


def extract_emotion(text: str) -> tuple[str, EmotionData | None]:
    """Extract emotion tag from Claude's response.

    Supports:
    - [EMOTION:happy] (legacy, defaults to intensity 0.7)
    - [EMOTION:happy:0.8] (new format with explicit intensity)

    Returns ``(clean_text, EmotionData)``, or ``(clean_text, None)`` when the
    turn declared nothing usable: no tag at all, or a name outside the 29.
    ``None`` means *apply no impulse* — a default NEUTRAL is a real target in
    PAD space, the origin, so a missing tag pulled an angry state back through
    zero and out the other side, and a parsing miss was lived as a soothing.
    An explicit ``[EMOTION:neutral:0.5]`` stays an EmotionData: "nothing was
    declared" and "she declared neutral" are two different facts.
    """
    match = EMOTION_PATTERN.search(text)
    if not match:
        return text.strip(), None

    emotion_str = match.group(1).lower()
    intensity_str = match.group(2)
    clean_text = EMOTION_PATTERN.sub("", text).strip()

    try:
        emotion = Emotion(emotion_str)
    except ValueError as exc:
        degradations.record("emotion: tag inconnu", exc)
        return clean_text, None

    intensity = float(intensity_str) if intensity_str else 0.7
    intensity = max(0.0, min(1.0, intensity))

    return clean_text, EmotionData(emotion=emotion, intensity=intensity)
