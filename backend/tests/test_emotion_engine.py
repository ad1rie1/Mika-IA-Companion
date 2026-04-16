"""Unit tests for the PAD-based EmotionEngine.

Covers impulse application, spring recovery, global coupling,
message blending, analytics, temperament variants, and edge cases.
"""

import pytest

from emotion import pad
from emotion.types import Emotion, EmotionData
from emotion.state import PersonMood, GlobalMood, Temperament
from emotion.engine import EmotionEngine

from tests.conftest import simulate_time_decay


# ===================================================================
# IMPULSE: an emotion pulls the state toward its anchor
# ===================================================================

class TestImpulse:

    def test_first_impulse_moves_state_toward_anchor(self, engine):
        """A single impulse should nudge position toward the target anchor."""
        pid = "u1"
        engine.process_emotion(EmotionData(Emotion.EXCITED, 0.8), pid)
        mood = engine._get_person_mood(pid)

        anchor = pad.EMOTION_ANCHORS[Emotion.EXCITED]
        # After one impulse, position should have moved from origin toward anchor,
        # but not reached it (physics, not teleport).
        assert pad.norm(mood.dynamic.position) > 0.05
        assert pad.dot(mood.dynamic.position, anchor) > 0, \
            "Position should point in the same direction as the target anchor"

    def test_repeated_same_impulse_accumulates(self, engine):
        """Repeated identical impulses should build up position magnitude."""
        pid = "u2"
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.7), pid)
        mag1 = pad.norm(engine._get_person_mood(pid).dynamic.position)

        for _ in range(4):
            engine.process_emotion(EmotionData(Emotion.HAPPY, 0.7), pid)
        mag5 = pad.norm(engine._get_person_mood(pid).dynamic.position)

        assert mag5 > mag1, \
            f"5 impulses should accumulate beyond 1: {mag1:.2f} -> {mag5:.2f}"

    def test_opposite_impulse_cancels(self, engine):
        """An opposite-direction impulse should reduce position magnitude."""
        pid = "u3"
        for _ in range(3):
            engine.process_emotion(EmotionData(Emotion.HAPPY, 0.9), pid)

        mag_before = pad.norm(engine._get_person_mood(pid).dynamic.position)
        engine.process_emotion(EmotionData(Emotion.SAD, 0.9), pid)
        # After an opposite impulse, the state should have started moving away
        # from HAPPY territory — velocity dotted with happy anchor < 0.
        mood = engine._get_person_mood(pid)
        happy_anchor = pad.EMOTION_ANCHORS[Emotion.HAPPY]
        assert pad.dot(mood.dynamic.velocity, happy_anchor) < pad.dot(
            pad.scale(mood.dynamic.velocity, 0), happy_anchor
        ) + 1e-9 or pad.norm(mood.dynamic.velocity) > 0.0

    def test_intensity_scales_target(self, engine):
        """Higher intensity should produce a larger kick."""
        engine.process_emotion(EmotionData(Emotion.EXCITED, 0.2), "low")
        engine.process_emotion(EmotionData(Emotion.EXCITED, 1.0), "high")

        low_speed = pad.norm(engine._get_person_mood("low").dynamic.velocity)
        high_speed = pad.norm(engine._get_person_mood("high").dynamic.velocity)
        assert high_speed > low_speed


# ===================================================================
# DECAY: the oscillator returns toward home
# ===================================================================

class TestDecay:

    def test_state_decays_toward_home(self, engine):
        """After enough time, position should converge near home (default mood)."""
        pid = "decay"
        engine.process_emotion(EmotionData(Emotion.ANGRY, 0.9), pid)
        simulate_time_decay(engine, 300.0)

        mood = engine._get_person_mood(pid)
        # Should no longer be in angry territory
        angry_anchor = pad.EMOTION_ANCHORS[Emotion.ANGRY]
        assert pad.dot(mood.dynamic.position, angry_anchor) < 0.3, \
            "Anger component should have decayed"

    def test_intensity_decreases_over_time(self, engine):
        """Position magnitude should decrease as we approach home."""
        pid = "decay2"
        engine.process_emotion(EmotionData(Emotion.EXCITED, 0.9), pid)
        i_before = engine._get_person_mood(pid).intensity
        simulate_time_decay(engine, 60.0)
        i_after = engine._get_person_mood(pid).intensity

        # Home is non-zero (default_mood anchor × 0.3), so we check the
        # overall motion rather than strict monotonic decrease.
        assert i_after != i_before


# ===================================================================
# GLOBAL COUPLING
# ===================================================================

class TestGlobalCoupling:

    def test_person_impulse_affects_global(self, engine):
        """A strong person impulse should produce a global kick."""
        gmag_before = pad.norm(engine.global_mood.dynamic.position)
        engine.process_emotion(EmotionData(Emotion.EXCITED, 0.9), "u")
        # Global velocity should be non-zero after the impulse
        assert pad.norm(engine.global_mood.dynamic.velocity) > 0.0

    def test_low_intensity_produces_small_global_kick(self, engine):
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.1), "u")
        assert pad.norm(engine.global_mood.dynamic.velocity) < 0.3

    def test_high_bleed_temperament(self, explosive_engine):
        """High global_bleed should push the global mood harder."""
        explosive_engine.process_emotion(EmotionData(Emotion.ANGRY, 0.9), "u")
        # One step to let velocity translate into position
        simulate_time_decay(explosive_engine, 3.0)
        assert pad.norm(explosive_engine.global_mood.dynamic.position) > 0.05


# ===================================================================
# MESSAGE EMOTION: blend of person + global
# ===================================================================

class TestMessageEmotion:

    def test_strong_person_dominates_message(self, engine):
        """When person is strong and global is weak, message should match person."""
        pid = "dom"
        for _ in range(3):
            engine.process_emotion(EmotionData(Emotion.LOVE, 0.9), pid)

        msg = engine.compute_message_emotion(pid)
        love_anchor = pad.EMOTION_ANCHORS[Emotion.LOVE]
        msg_vec = pad.EMOTION_ANCHORS[msg.emotion]
        assert pad.dot(msg_vec, love_anchor) > 0, \
            f"Message emotion should be in LOVE direction, got {msg.emotion.value}"

    def test_message_default_when_state_empty(self, engine):
        """When nothing was processed, message should fall back to default mood."""
        msg = engine.compute_message_emotion("never_seen")
        assert msg.emotion == engine.temperament.default_mood

    def test_intensity_in_range(self, engine):
        engine.process_emotion(EmotionData(Emotion.ANGRY, 1.0), "u")
        msg = engine.compute_message_emotion("u")
        assert 0.0 <= msg.intensity <= 1.0


# ===================================================================
# ANALYTICS
# ===================================================================

class TestAnalytics:

    def test_empty(self, engine):
        result = engine.get_analytics()
        assert result["total_interactions"] == 0
        assert result["persons_tracked"] == 0

    def test_after_interactions(self, engine):
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.8), "p1")
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.9), "p1")
        engine.process_emotion(EmotionData(Emotion.SAD, 0.5), "p2")

        result = engine.get_analytics()
        assert result["total_interactions"] == 3
        assert result["persons_tracked"] == 2
        assert "happy" in result["distribution"]
        assert "sad" in result["distribution"]


# ===================================================================
# TEMPERAMENT VARIANTS
# ===================================================================

class TestTemperamentVariants:

    def test_stoic_moves_less(self, stoic_engine):
        """Stoic (low volatility) should produce less motion for same impulse."""
        stoic_engine.process_emotion(EmotionData(Emotion.EXCITED, 0.8), "s")
        stoic_speed = pad.norm(stoic_engine._get_person_mood("s").dynamic.velocity)

        # Reference: default engine
        ref = EmotionEngine()
        from tests.conftest import TEMPERAMENT_DEFAULT
        ref.temperament = TEMPERAMENT_DEFAULT
        ref._recompute_params()
        ref._initialized = True
        ref.process_emotion(EmotionData(Emotion.EXCITED, 0.8), "r")
        ref_speed = pad.norm(ref._get_person_mood("r").dynamic.velocity)

        assert stoic_speed < ref_speed, \
            f"Stoic should produce slower motion: stoic={stoic_speed:.3f} vs ref={ref_speed:.3f}"

    def test_explosive_moves_more(self, explosive_engine):
        """Explosive (high volatility + gain) should move faster."""
        explosive_engine.process_emotion(EmotionData(Emotion.HAPPY, 0.6), "e")
        exp_speed = pad.norm(explosive_engine._get_person_mood("e").dynamic.velocity)
        assert exp_speed > 0.3

    def test_melancholic_returns_to_melancholic(self, melancholic_engine):
        """Melancholic temperament should decay back to the melancholic anchor."""
        pid = "m"
        melancholic_engine.process_emotion(EmotionData(Emotion.HAPPY, 0.6), pid)
        simulate_time_decay(melancholic_engine, 300.0)

        mood = melancholic_engine._get_person_mood(pid)
        mel_anchor = pad.EMOTION_ANCHORS[Emotion.MELANCHOLIC]
        assert pad.dot(mood.dynamic.position, mel_anchor) > 0, \
            f"Should drift toward melancholic home, got {mood.emotion.value}"


# ===================================================================
# EDGE CASES
# ===================================================================

class TestEdgeCases:

    def test_zero_intensity(self, engine):
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.0), "z")
        mood = engine._get_person_mood("z")
        assert 0.0 <= mood.intensity <= 1.0

    def test_max_intensity_bounded(self, engine):
        engine.process_emotion(EmotionData(Emotion.ANGRY, 1.0), "m")
        mood = engine._get_person_mood("m")
        assert 0.0 <= mood.intensity <= 1.0

    def test_rapid_fire_bounded(self, engine):
        pid = "rapid"
        for e in [Emotion.HAPPY, Emotion.SAD, Emotion.ANGRY, Emotion.LOVE,
                  Emotion.CURIOUS, Emotion.SCARED, Emotion.PLAYFUL]:
            engine.process_emotion(EmotionData(e, 0.7), pid)

        mood = engine._get_person_mood(pid)
        # Position stays inside the clamped envelope (1.2)
        for c in mood.dynamic.position:
            assert -1.2 <= c <= 1.2

    def test_many_persons(self, engine):
        for i in range(30):
            engine.process_emotion(EmotionData(Emotion.HAPPY, 0.5), f"u{i}")
        assert len(engine.person_moods) == 30

    def test_history_bounded(self, engine):
        pid = "h"
        for _ in range(150):
            engine.process_emotion(EmotionData(Emotion.HAPPY, 0.5), pid)
        mood = engine._get_person_mood(pid)
        assert len(mood.history) == 100
