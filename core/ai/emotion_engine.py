import re
from enum import Enum


class Emotion(str, Enum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    SURPRISED = "surprised"
    THINKING = "thinking"
    LOVE = "love"


EMOTION_PATTERN = re.compile(r"\[EMOTION:(\w+)\]")


def extract_emotion(text: str) -> tuple[str, Emotion]:
    """Extract emotion tag from Claude's response and return clean text + emotion."""
    match = EMOTION_PATTERN.search(text)
    if match:
        emotion_str = match.group(1).lower()
        clean_text = EMOTION_PATTERN.sub("", text).strip()
        try:
            emotion = Emotion(emotion_str)
        except ValueError:
            emotion = Emotion.NEUTRAL
        return clean_text, emotion
    return text.strip(), Emotion.NEUTRAL
