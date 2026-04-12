"""Backward-compatibility shim. Real implementation is in conscience.emotion_types."""
from conscience.emotion_types import (
    Emotion,
    EmotionData,
    extract_emotion,
    EMOTION_PATTERN,
)

__all__ = ["Emotion", "EmotionData", "extract_emotion", "EMOTION_PATTERN"]
