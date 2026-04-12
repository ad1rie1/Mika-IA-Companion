"""
Tests for emotion tag extraction and parsing.

Verifies the [EMOTION:name:intensity] format is correctly parsed
from AI responses, including edge cases and legacy format.
"""

import pytest

from emotion.types import (
    Emotion,
    EmotionData,
    extract_emotion,
    EMOTION_CATEGORIES,
    EmotionCategory,
)


class TestExtractEmotion:

    def test_standard_format(self):
        """Standard [EMOTION:name:intensity] should parse correctly."""
        text = "Salut ! Ca va super bien ! [EMOTION:happy:0.8]"
        clean, data = extract_emotion(text)

        assert clean == "Salut ! Ca va super bien !"
        assert data.emotion == Emotion.HAPPY
        assert data.intensity == 0.8

    def test_legacy_format_no_intensity(self):
        """Legacy [EMOTION:name] should default to intensity 0.7."""
        text = "Oh non... [EMOTION:sad]"
        clean, data = extract_emotion(text)

        assert clean == "Oh non..."
        assert data.emotion == Emotion.SAD
        assert data.intensity == 0.7

    def test_all_29_emotions_parse(self):
        """Every valid emotion name should parse correctly."""
        for emotion in Emotion:
            text = f"test [EMOTION:{emotion.value}:0.5]"
            clean, data = extract_emotion(text)
            assert data.emotion == emotion, f"Failed to parse {emotion.value}"
            assert data.intensity == 0.5

    def test_unknown_emotion_defaults_to_neutral(self):
        """Unknown emotion names should fall back to neutral."""
        text = "hmm [EMOTION:spaghetti:0.9]"
        clean, data = extract_emotion(text)

        assert data.emotion == Emotion.NEUTRAL
        assert data.intensity == 0.9

    def test_no_emotion_tag(self):
        """Text without an emotion tag should return default."""
        text = "Salut comment tu vas ?"
        clean, data = extract_emotion(text)

        assert clean == "Salut comment tu vas ?"
        assert data.emotion == Emotion.NEUTRAL
        assert data.intensity == 0.5

    def test_intensity_clamped_above_1(self):
        """Intensity > 1.0 should be clamped to 1.0."""
        text = "WOW [EMOTION:excited:1.5]"
        clean, data = extract_emotion(text)

        assert data.intensity == 1.0

    def test_intensity_clamped_below_0(self):
        """Intensity < 0.0 should be clamped to 0.0."""
        text = "hmm [EMOTION:sad:0.0]"
        clean, data = extract_emotion(text)

        assert data.intensity == 0.0

    def test_tag_at_beginning(self):
        """Tag at the start of text should be stripped cleanly."""
        text = "[EMOTION:excited:0.9] Oh la la c'est trop bien !"
        clean, data = extract_emotion(text)

        assert clean == "Oh la la c'est trop bien !"
        assert data.emotion == Emotion.EXCITED

    def test_tag_in_middle(self):
        """Tag in the middle of text should be stripped."""
        text = "Donc oui [EMOTION:thinking:0.6] je pense que c'est correct"
        clean, data = extract_emotion(text)

        assert clean == "Donc oui  je pense que c'est correct"
        assert data.emotion == Emotion.THINKING

    def test_integer_intensity(self):
        """Integer intensity (like 1) should be parsed as float."""
        text = "ok [EMOTION:angry:1]"
        clean, data = extract_emotion(text)

        assert data.intensity == 1.0
        assert data.emotion == Emotion.ANGRY

    def test_case_insensitive_emotion_name(self):
        """Emotion names should be lowercased before matching."""
        text = "wow [EMOTION:HAPPY:0.8]"
        clean, data = extract_emotion(text)

        assert data.emotion == Emotion.HAPPY

    def test_multiple_tags_first_wins(self):
        """Only the first emotion tag should be extracted."""
        text = "[EMOTION:happy:0.8] text [EMOTION:sad:0.3]"
        clean, data = extract_emotion(text)

        assert data.emotion == Emotion.HAPPY
        assert data.intensity == 0.8

    def test_empty_string(self):
        """Empty string should return default."""
        clean, data = extract_emotion("")

        assert clean == ""
        assert data.emotion == Emotion.NEUTRAL
        assert data.intensity == 0.5


class TestEmotionData:

    def test_default_factory(self):
        data = EmotionData.default()
        assert data.emotion == Emotion.NEUTRAL
        assert data.intensity == 0.5

    def test_frozen(self):
        """EmotionData should be immutable."""
        data = EmotionData(Emotion.HAPPY, 0.8)
        with pytest.raises(AttributeError):
            data.intensity = 0.5


class TestEmotionCategories:

    def test_all_emotions_categorized(self):
        """Every Emotion enum value should have a category."""
        for emotion in Emotion:
            assert emotion in EMOTION_CATEGORIES, \
                f"{emotion.value} missing from EMOTION_CATEGORIES"

    def test_positive_emotions(self):
        positives = [
            Emotion.HAPPY, Emotion.EXCITED, Emotion.LOVE, Emotion.PROUD,
            Emotion.GRATEFUL, Emotion.PLAYFUL, Emotion.AMUSED,
            Emotion.HOPEFUL, Emotion.RELIEVED,
        ]
        for e in positives:
            assert EMOTION_CATEGORIES[e] == EmotionCategory.POSITIVE, \
                f"{e.value} should be POSITIVE"

    def test_negative_emotions(self):
        negatives = [
            Emotion.SAD, Emotion.ANGRY, Emotion.SCARED, Emotion.DISGUSTED,
            Emotion.FRUSTRATED, Emotion.LONELY, Emotion.ANXIOUS,
            Emotion.BORED, Emotion.JEALOUS,
        ]
        for e in negatives:
            assert EMOTION_CATEGORIES[e] == EmotionCategory.NEGATIVE, \
                f"{e.value} should be NEGATIVE"

    def test_complex_emotions(self):
        complexes = [
            Emotion.SURPRISED, Emotion.THINKING, Emotion.CONFUSED,
            Emotion.EMBARRASSED, Emotion.NOSTALGIC, Emotion.DREAMY,
            Emotion.DETERMINED, Emotion.MISCHIEVOUS, Emotion.CURIOUS,
            Emotion.MELANCHOLIC,
        ]
        for e in complexes:
            assert EMOTION_CATEGORIES[e] == EmotionCategory.COMPLEX, \
                f"{e.value} should be COMPLEX"
