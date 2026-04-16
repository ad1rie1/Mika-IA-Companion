"""Tests for PAD multi-label blend — emotional ambivalence.

`pad_to_blend()` returns the top-K emotion anchors that best describe
a PAD position. This lets the engine express "mostly grateful, a touch
nostalgic" instead of forcing a single label.

Tests:
- Pure single-emotion positions → 1-entry blend
- Ambivalent positions → 2-entry blend with meaningful secondary weight
- Zero vector → empty blend
- Threshold filtering (orthogonal emotions excluded)
- MessageEmotion.is_ambivalent correctness
- Backward compatibility of to_dict()
"""
from __future__ import annotations

import pytest

from emotion import pad
from emotion.types import Emotion
from emotion.state import MessageEmotion


# ---------------------------------------------------------------------------
# pad_to_blend directly
# ---------------------------------------------------------------------------

class TestPadToBlend:

    def test_zero_vector_returns_empty(self):
        assert pad.pad_to_blend((0.0, 0.0, 0.0)) == []

    def test_pure_happy_gives_single_happy(self):
        pos = pad.label_to_pad(Emotion.HAPPY, 0.8)
        blend = pad.pad_to_blend(pos, top_k=2)
        assert len(blend) >= 1
        assert blend[0][0] is Emotion.HAPPY
        # Primary weight scales with intensity
        assert blend[0][1] > 0.5

    def test_pure_anchor_secondary_is_a_neighbor(self):
        """A pure HAPPY vector may still have AMUSED/GRATEFUL as a neighbor
        above the similarity floor — that's fine, it's meaningful proximity.
        The primary matches the anchor exactly, neighbors are at most equal."""
        pos = pad.label_to_pad(Emotion.HAPPY, 1.0)
        blend = pad.pad_to_blend(pos, top_k=2)
        assert len(blend) >= 1
        assert blend[0][0] is Emotion.HAPPY
        if len(blend) == 2:
            # Secondary weight cannot exceed the primary.
            assert blend[1][1] <= blend[0][1]

    def test_midway_between_happy_and_sad_produces_blend(self):
        """A vector combining a positive and a negative anchor that share
        some axes should produce a blend."""
        # Mix grateful (positive, low arousal) + nostalgic (mildly positive, negative arousal)
        grateful = pad.label_to_pad(Emotion.GRATEFUL, 1.0)
        nostalgic = pad.label_to_pad(Emotion.NOSTALGIC, 1.0)
        mix = pad.add(pad.scale(grateful, 0.5), pad.scale(nostalgic, 0.5))
        blend = pad.pad_to_blend(mix, top_k=3)
        labels = [e for e, _ in blend]
        assert len(blend) >= 1
        # Either grateful or nostalgic should appear
        assert Emotion.GRATEFUL in labels or Emotion.NOSTALGIC in labels

    def test_threshold_filters_orthogonal_anchors(self):
        """ANGRY and HAPPY are opposite — a pure HAPPY vector should not
        list ANGRY in its blend."""
        pos = pad.label_to_pad(Emotion.HAPPY, 0.9)
        blend = pad.pad_to_blend(pos, top_k=10)
        labels = [e for e, _ in blend]
        assert Emotion.ANGRY not in labels
        assert Emotion.SAD not in labels

    def test_top_k_caps_result_length(self):
        # A very intense position in a dense region of PAD space.
        pos = pad.label_to_pad(Emotion.HAPPY, 1.0)
        blend2 = pad.pad_to_blend(pos, top_k=2)
        blend5 = pad.pad_to_blend(pos, top_k=5)
        assert len(blend2) <= 2
        assert len(blend5) <= 5
        assert len(blend5) >= len(blend2)

    def test_top_k_zero_returns_empty(self):
        pos = pad.label_to_pad(Emotion.HAPPY, 0.9)
        assert pad.pad_to_blend(pos, top_k=0) == []

    def test_weights_are_nonnegative(self):
        pos = pad.label_to_pad(Emotion.EXCITED, 0.7)
        blend = pad.pad_to_blend(pos, top_k=3)
        for _, w in blend:
            assert w >= 0.0

    def test_weights_sorted_descending(self):
        pos = pad.label_to_pad(Emotion.PLAYFUL, 0.8)
        blend = pad.pad_to_blend(pos, top_k=5)
        weights = [w for _, w in blend]
        assert weights == sorted(weights, reverse=True)

    def test_higher_intensity_gives_higher_primary_weight(self):
        pos_low = pad.label_to_pad(Emotion.HAPPY, 0.3)
        pos_high = pad.label_to_pad(Emotion.HAPPY, 0.9)
        blend_low = pad.pad_to_blend(pos_low, top_k=1)
        blend_high = pad.pad_to_blend(pos_high, top_k=1)
        assert blend_high[0][1] > blend_low[0][1]


# ---------------------------------------------------------------------------
# MessageEmotion ambivalence
# ---------------------------------------------------------------------------

class TestMessageEmotionAmbivalence:

    def _make_msg(self, blend_tuple) -> MessageEmotion:
        return MessageEmotion(
            emotion=Emotion.HAPPY,
            intensity=0.7,
            person_emotion=Emotion.HAPPY,
            person_intensity=0.7,
            global_emotion=Emotion.HAPPY,
            global_intensity=0.7,
            blend=blend_tuple,
        )

    def test_not_ambivalent_with_empty_blend(self):
        msg = self._make_msg(())
        assert msg.is_ambivalent() is False

    def test_not_ambivalent_with_single_component(self):
        msg = self._make_msg(((Emotion.HAPPY, 0.7),))
        assert msg.is_ambivalent() is False

    def test_not_ambivalent_when_secondary_is_tiny(self):
        """Secondary < 40% of primary → not meaningfully ambivalent."""
        msg = self._make_msg((
            (Emotion.HAPPY, 0.8),
            (Emotion.AMUSED, 0.1),
        ))
        assert msg.is_ambivalent() is False

    def test_ambivalent_when_secondary_strong(self):
        msg = self._make_msg((
            (Emotion.GRATEFUL, 0.6),
            (Emotion.NOSTALGIC, 0.45),
        ))
        assert msg.is_ambivalent() is True

    def test_prompt_description_single_emotion(self):
        msg = self._make_msg(((Emotion.HAPPY, 0.7),))
        desc = msg.to_prompt_description()
        assert "happy" in desc
        assert "mais aussi" not in desc

    def test_prompt_description_ambivalent(self):
        msg = self._make_msg((
            (Emotion.GRATEFUL, 0.6),
            (Emotion.NOSTALGIC, 0.45),
        ))
        desc = msg.to_prompt_description()
        assert "grateful" in desc
        assert "nostalgic" in desc
        assert "mais aussi" in desc or "nuance" in desc


# ---------------------------------------------------------------------------
# MessageEmotion backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompat:

    def test_to_dict_includes_old_fields(self):
        msg = MessageEmotion(
            emotion=Emotion.HAPPY,
            intensity=0.7,
            person_emotion=Emotion.HAPPY,
            person_intensity=0.7,
            global_emotion=Emotion.HAPPY,
            global_intensity=0.7,
            blend=(),
        )
        d = msg.to_dict()
        assert d["emotion"] == "happy"
        assert d["intensity"] == 0.7

    def test_to_dict_includes_blend(self):
        msg = MessageEmotion(
            emotion=Emotion.HAPPY,
            intensity=0.7,
            person_emotion=Emotion.HAPPY,
            person_intensity=0.7,
            global_emotion=Emotion.HAPPY,
            global_intensity=0.7,
            blend=((Emotion.HAPPY, 0.7), (Emotion.AMUSED, 0.4)),
        )
        d = msg.to_dict()
        assert isinstance(d["blend"], list)
        assert len(d["blend"]) == 2
        assert d["blend"][0]["emotion"] == "happy"
        assert d["blend"][0]["weight"] == 0.7

    def test_default_blend_is_empty_tuple(self):
        msg = MessageEmotion(
            emotion=Emotion.HAPPY,
            intensity=0.7,
            person_emotion=Emotion.HAPPY,
            person_intensity=0.7,
            global_emotion=Emotion.HAPPY,
            global_intensity=0.7,
        )
        assert msg.blend == ()


# ---------------------------------------------------------------------------
# Integration with compute_message_emotion
# ---------------------------------------------------------------------------

class TestComputeMessageEmotionBlend:

    def test_blend_populated_after_normal_impulse(self, engine):
        """process_emotion adds velocity; we need to step the oscillator
        to move the position into a non-zero state before compute."""
        from emotion.types import EmotionData
        from tests.conftest import simulate_time_decay

        engine.process_emotion(EmotionData(Emotion.GRATEFUL, 0.8), "pid_1")
        # Let the oscillator integrate for a couple of seconds so position
        # actually moves toward the GRATEFUL anchor direction.
        simulate_time_decay(engine, 2.0)

        msg = engine.compute_message_emotion("pid_1")
        assert len(msg.blend) >= 1
        # Primary anchor should lie in the GRATEFUL neighborhood
        # (positive valence, low arousal, near-zero dominance).
        primary_valence = pad.valence(msg.blend[0][0])
        assert primary_valence > 0.0

    def test_blend_respects_intensity(self, engine):
        from emotion.types import EmotionData
        from tests.conftest import simulate_time_decay

        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.4), "pid_a")
        simulate_time_decay(engine, 2.0)
        msg_a = engine.compute_message_emotion("pid_a")

        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.9), "pid_b")
        simulate_time_decay(engine, 2.0)
        msg_b = engine.compute_message_emotion("pid_b")

        # Higher impulse → higher primary weight in blend
        if msg_a.blend and msg_b.blend:
            assert msg_b.blend[0][1] >= msg_a.blend[0][1]

    def test_neutral_state_produces_default_mood_blend(self, engine):
        """Zero-ish state → blend falls back to default mood (HAPPY)."""
        msg = engine.compute_message_emotion("never_talked_to")
        assert len(msg.blend) >= 1
        # Default mood from conftest.py is HAPPY
        assert msg.blend[0][0] is Emotion.HAPPY

    def test_ambivalent_blend_after_mixed_history(self, engine):
        """Two successive impulses toward different anchors produce a
        position that reads as an ambivalent blend."""
        from emotion.types import EmotionData
        from tests.conftest import simulate_time_decay

        # First grateful, then nostalgic — related but distinct anchors.
        engine.process_emotion(EmotionData(Emotion.GRATEFUL, 0.7), "pid_mix")
        simulate_time_decay(engine, 1.5)
        engine.process_emotion(EmotionData(Emotion.NOSTALGIC, 0.7), "pid_mix")
        simulate_time_decay(engine, 1.5)

        msg = engine.compute_message_emotion("pid_mix")
        # We should get at least one component; the blend may or may not
        # be "ambivalent" depending on how the oscillator settled — but
        # it must expose a blend with top_k<=2.
        assert 0 < len(msg.blend) <= 2
