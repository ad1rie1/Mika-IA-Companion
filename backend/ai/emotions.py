"""Backward-compatibility shim. Real implementation is in ai.emotion_types."""
from ai.emotion_types import (
    Emotion,
    EmotionData,
    extract_emotion,
    EMOTION_PATTERN,
)

__all__ = ["Emotion", "EmotionData", "extract_emotion", "EMOTION_PATTERN"]
