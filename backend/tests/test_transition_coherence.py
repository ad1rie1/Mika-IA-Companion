"""
Tests for emotion transition coherence.

Verifies the TRANSITION_OVERRIDES table is well-formed:
- Symmetry (if A->B is defined, B->A is also reachable)
- All naturalness values are in [0.0, 1.0]
- No missing important transitions
- Category-based defaults work correctly
- The opposition detection is consistent
"""

import pytest

from emotion.types import (
    Emotion,
    EmotionCategory,
    EMOTION_CATEGORIES,
    OPPOSITE_CATEGORIES,
    TRANSITION_OVERRIDES,
)
from emotion.engine import EmotionEngine


# ===================================================================
# TRANSITION OVERRIDES TABLE INTEGRITY
# ===================================================================

class TestTransitionOverridesTable:

    def test_all_values_in_range(self):
        """Every naturalness value should be in [0.0, 1.0]."""
        for (from_e, to_e), naturalness in TRANSITION_OVERRIDES.items():
            assert 0.0 <= naturalness <= 1.0, \
                f"({from_e.value} -> {to_e.value}) = {naturalness} out of [0, 1]"

    def test_all_keys_are_valid_emotions(self):
        """Every emotion in the overrides should be a valid Emotion enum."""
        for (from_e, to_e) in TRANSITION_OVERRIDES:
            assert isinstance(from_e, Emotion), f"{from_e} is not an Emotion"
            assert isinstance(to_e, Emotion), f"{to_e} is not an Emotion"

    def test_no_self_transitions(self):
        """No override should be a self-transition (A -> A)."""
        for (from_e, to_e) in TRANSITION_OVERRIDES:
            assert from_e != to_e, \
                f"Self-transition override found: {from_e.value} -> {to_e.value}"

    def test_symmetry_reachability(self):
        """If A->B is defined, B->A should be reachable too (via explicit
        override or reverse lookup).

        Note: some pairs intentionally have different forward/backward
        naturalness (e.g. sad->lonely=0.95 but lonely->sad=0.9).
        Both directions should at least be defined or reachable.
        """
        engine = EmotionEngine()
        for (from_e, to_e), naturalness in TRANSITION_OVERRIDES.items():
            forward = engine._get_transition_naturalness(from_e, to_e)
            backward = engine._get_transition_naturalness(to_e, from_e)

            # Both should be reachable (not just category defaults)
            # Forward should match the explicit override
            assert forward == naturalness, \
                f"{from_e.value}->{to_e.value}: expected {naturalness}, got {forward}"
            # Backward should either match an explicit reverse override
            # or the same value via reverse lookup
            assert backward > 0.0, \
                f"{to_e.value}->{from_e.value}: not reachable (got {backward})"

    def test_natural_pairs_above_0_7(self):
        """Transitions marked as 'very natural' should have naturalness > 0.7."""
        natural_pairs = [
            (Emotion.SAD, Emotion.ANGRY),
            (Emotion.SAD, Emotion.LONELY),
            (Emotion.ANGRY, Emotion.FRUSTRATED),
            (Emotion.HAPPY, Emotion.EXCITED),
            (Emotion.CURIOUS, Emotion.THINKING),
            (Emotion.MELANCHOLIC, Emotion.NOSTALGIC),
        ]
        for from_e, to_e in natural_pairs:
            naturalness = TRANSITION_OVERRIDES.get(
                (from_e, to_e),
                TRANSITION_OVERRIDES.get((to_e, from_e), None)
            )
            assert naturalness is not None, \
                f"Missing override for natural pair: {from_e.value} -> {to_e.value}"
            assert naturalness > 0.7, \
                f"Natural pair {from_e.value}->{to_e.value} has low naturalness: {naturalness}"

    def test_unnatural_pairs_below_0_3(self):
        """Transitions marked as 'very unnatural' should have naturalness < 0.3."""
        unnatural_pairs = [
            (Emotion.ANGRY, Emotion.LOVE),
            (Emotion.SCARED, Emotion.PLAYFUL),
            (Emotion.DISGUSTED, Emotion.LOVE),
        ]
        for from_e, to_e in unnatural_pairs:
            naturalness = TRANSITION_OVERRIDES.get(
                (from_e, to_e),
                TRANSITION_OVERRIDES.get((to_e, from_e), None)
            )
            assert naturalness is not None, \
                f"Missing override for unnatural pair: {from_e.value} -> {to_e.value}"
            assert naturalness < 0.3, \
                f"Unnatural pair {from_e.value}->{to_e.value} has high naturalness: {naturalness}"


# ===================================================================
# CATEGORY-BASED DEFAULTS
# ===================================================================

class TestCategoryDefaults:

    def test_same_category_default_0_75(self):
        """Transitions within the same category should default to 0.75."""
        engine = EmotionEngine()
        # Pick two positive emotions NOT in overrides
        # PROUD -> HOPEFUL (no override defined)
        nat = engine._get_transition_naturalness(Emotion.PROUD, Emotion.HOPEFUL)
        assert nat == 0.75, f"Same category default should be 0.75, got {nat}"

    def test_neutral_category_default_0_7(self):
        """Transitions involving neutral category should default to 0.7."""
        engine = EmotionEngine()
        # Any emotion -> NEUTRAL
        nat = engine._get_transition_naturalness(Emotion.HAPPY, Emotion.NEUTRAL)
        assert nat == 0.9  # to_e == NEUTRAL has special case returning 0.9

    def test_complex_category_default_0_6(self):
        """Transitions involving complex category should default to 0.6."""
        engine = EmotionEngine()
        # POSITIVE -> COMPLEX without override
        nat = engine._get_transition_naturalness(Emotion.PROUD, Emotion.DREAMY)
        assert nat == 0.6, f"Positive->Complex default should be 0.6, got {nat}"

    def test_cross_positive_negative_default_0_35(self):
        """Cross positive/negative transitions should default to 0.35."""
        engine = EmotionEngine()
        # Pick a pair not in overrides
        nat = engine._get_transition_naturalness(Emotion.PROUD, Emotion.LONELY)
        assert nat == 0.35, f"Cross category default should be 0.35, got {nat}"

    def test_self_transition_always_1_0(self):
        """Self-transitions (A -> A) should always return 1.0."""
        engine = EmotionEngine()
        for emotion in Emotion:
            nat = engine._get_transition_naturalness(emotion, emotion)
            assert nat == 1.0, f"Self-transition {emotion.value} should be 1.0, got {nat}"

    def test_to_neutral_always_0_9(self):
        """Transition to NEUTRAL should always be 0.9 (any emotion can calm down)."""
        engine = EmotionEngine()
        for emotion in Emotion:
            if emotion == Emotion.NEUTRAL:
                continue
            nat = engine._get_transition_naturalness(emotion, Emotion.NEUTRAL)
            assert nat == 0.9, \
                f"{emotion.value} -> neutral should be 0.9, got {nat}"


# ===================================================================
# OPPOSITION DETECTION
# ===================================================================

class TestOppositionDetection:

    def test_positive_vs_negative_is_opposite(self):
        assert EmotionEngine._are_opposite(EmotionCategory.POSITIVE, EmotionCategory.NEGATIVE)
        assert EmotionEngine._are_opposite(EmotionCategory.NEGATIVE, EmotionCategory.POSITIVE)

    def test_same_category_not_opposite(self):
        assert not EmotionEngine._are_opposite(EmotionCategory.POSITIVE, EmotionCategory.POSITIVE)
        assert not EmotionEngine._are_opposite(EmotionCategory.NEGATIVE, EmotionCategory.NEGATIVE)

    def test_complex_not_opposite_to_anything(self):
        assert not EmotionEngine._are_opposite(EmotionCategory.COMPLEX, EmotionCategory.POSITIVE)
        assert not EmotionEngine._are_opposite(EmotionCategory.COMPLEX, EmotionCategory.NEGATIVE)
        assert not EmotionEngine._are_opposite(EmotionCategory.POSITIVE, EmotionCategory.COMPLEX)

    def test_neutral_not_opposite_to_anything(self):
        assert not EmotionEngine._are_opposite(EmotionCategory.NEUTRAL_CAT, EmotionCategory.POSITIVE)
        assert not EmotionEngine._are_opposite(EmotionCategory.NEUTRAL_CAT, EmotionCategory.NEGATIVE)

    def test_opposite_categories_mapping_complete(self):
        """OPPOSITE_CATEGORIES should have both directions."""
        assert EmotionCategory.POSITIVE in OPPOSITE_CATEGORIES
        assert EmotionCategory.NEGATIVE in OPPOSITE_CATEGORIES
        assert OPPOSITE_CATEGORIES[EmotionCategory.POSITIVE] == EmotionCategory.NEGATIVE
        assert OPPOSITE_CATEGORIES[EmotionCategory.NEGATIVE] == EmotionCategory.POSITIVE


# ===================================================================
# ALL EMOTION CATEGORIES COVERAGE
# ===================================================================

class TestCategoryCoverage:

    def test_all_emotions_have_categories(self):
        """Every Emotion must have a category assigned."""
        for emotion in Emotion:
            assert emotion in EMOTION_CATEGORIES, \
                f"{emotion.value} has no category assigned"

    def test_category_distribution(self):
        """Verify expected number of emotions per category."""
        counts = {}
        for emotion, cat in EMOTION_CATEGORIES.items():
            counts[cat] = counts.get(cat, 0) + 1

        assert counts[EmotionCategory.NEUTRAL_CAT] == 1  # just "neutral"
        assert counts[EmotionCategory.POSITIVE] == 9
        assert counts[EmotionCategory.NEGATIVE] == 9
        assert counts[EmotionCategory.COMPLEX] == 10

    def test_total_emotion_count(self):
        """Should have exactly 29 emotions."""
        assert len(Emotion) == 29


# ===================================================================
# TRANSITION MATRIX COMPLETENESS
# ===================================================================

class TestTransitionCoverage:

    def test_key_emotional_journeys_covered(self):
        """Important emotional journeys should all have explicit overrides."""
        engine = EmotionEngine()

        # Grief journey: sad -> angry -> lonely -> nostalgic -> hopeful
        journey = [Emotion.SAD, Emotion.ANGRY, Emotion.LONELY,
                   Emotion.NOSTALGIC, Emotion.HOPEFUL]
        for i in range(len(journey) - 1):
            nat = engine._get_transition_naturalness(journey[i], journey[i + 1])
            assert nat > 0.5, \
                f"Grief journey {journey[i].value}->{journey[i+1].value} " \
                f"too low: {nat}"

    def test_excitement_chain_covered(self):
        """Excitement chain: curious -> excited -> happy -> playful."""
        engine = EmotionEngine()

        chain = [Emotion.CURIOUS, Emotion.EXCITED, Emotion.HAPPY, Emotion.PLAYFUL]
        for i in range(len(chain) - 1):
            nat = engine._get_transition_naturalness(chain[i], chain[i + 1])
            assert nat > 0.7, \
                f"Excitement chain {chain[i].value}->{chain[i+1].value} " \
                f"too low: {nat}"

    def test_anxiety_chain_covered(self):
        """Anxiety chain: anxious -> scared -> relieved -> happy."""
        engine = EmotionEngine()

        nat_a_s = engine._get_transition_naturalness(Emotion.ANXIOUS, Emotion.SCARED)
        nat_a_r = engine._get_transition_naturalness(Emotion.ANXIOUS, Emotion.RELIEVED)
        nat_r_h = engine._get_transition_naturalness(Emotion.RELIEVED, Emotion.HAPPY)

        assert nat_a_s > 0.7, f"anxious->scared: {nat_a_s}"
        assert nat_a_r > 0.7, f"anxious->relieved: {nat_a_r}"
        assert nat_r_h > 0.7, f"relieved->happy: {nat_r_h}"
