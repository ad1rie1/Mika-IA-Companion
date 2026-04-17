"""
Property-based invariant tests (fuzzing).

Generates random sequences of emotions, intensities, and person IDs,
then verifies that system invariants ALWAYS hold regardless of input.

Invariants:
- intensity is always in [0.0, 1.0]
- emotion is always a valid Enum member
- global mood is always valid
- message emotion is always valid
- history never exceeds 100 entries
- no exceptions are raised
"""

import random
import time
import pytest

from emotion.types import Emotion, EmotionData
from emotion.state import PersonMood, GlobalMood, Temperament
from emotion.engine import EmotionEngine
from tests.conftest import simulate_time_decay


ALL_EMOTIONS = list(Emotion)
TEMPERAMENTS = [
    Temperament(0.1, 0.1, 0.9, Emotion.NEUTRAL, 0.0),   # minimal
    Temperament(0.5, 0.5, 0.5, Emotion.HAPPY, 0.3),      # balanced
    Temperament(0.7, 0.6, 0.5, Emotion.HAPPY, 0.3),      # default Mika
    Temperament(1.0, 1.0, 0.1, Emotion.EXCITED, 1.0),    # extreme
    Temperament(0.0, 0.0, 1.0, Emotion.SAD, 0.0),        # zero reactivity
    Temperament(1.0, 1.0, 1.0, Emotion.ANGRY, 1.0),      # max everything
]

# Seed for reproducibility (but still pseudo-random)
random.seed(42)


def make_engine(temperament: Temperament) -> EmotionEngine:
    engine = EmotionEngine()
    engine.temperament = temperament
    engine.global_mood = GlobalMood()
    engine._recompute_params()
    engine._initialized = True
    return engine


def assert_invariants(engine: EmotionEngine, label: str = ""):
    """Check all system invariants hold."""
    prefix = f"[{label}] " if label else ""

    # Global mood invariants
    assert isinstance(engine.global_mood.emotion, Emotion), \
        f"{prefix}Global emotion is not a valid Emotion"
    assert 0.0 <= engine.global_mood.intensity <= 1.0, \
        f"{prefix}Global intensity out of bounds: {engine.global_mood.intensity}"

    # Person mood invariants
    for pid, mood in engine.person_moods.items():
        assert isinstance(mood.emotion, Emotion), \
            f"{prefix}Person {pid} emotion is not valid"
        assert 0.0 <= mood.intensity <= 1.0, \
            f"{prefix}Person {pid} intensity: {mood.intensity}"
        assert len(mood.history) <= 100, \
            f"{prefix}Person {pid} history too long: {len(mood.history)}"

    # Message emotion invariants for each person
    for pid in engine.person_moods:
        msg = engine.compute_message_emotion(pid)
        assert isinstance(msg.emotion, Emotion), \
            f"{prefix}Message emotion for {pid} invalid"
        assert 0.0 <= msg.intensity <= 1.0, \
            f"{prefix}Message intensity for {pid}: {msg.intensity}"
        assert isinstance(msg.person_emotion, Emotion)
        assert isinstance(msg.global_emotion, Emotion)
        assert 0.0 <= msg.person_intensity <= 1.0
        assert 0.0 <= msg.global_intensity <= 1.0


# ===================================================================
# RANDOM SEQUENCE TESTS
# ===================================================================

class TestRandomSequences:

    @pytest.mark.parametrize("temperament", TEMPERAMENTS, ids=[
        "minimal", "balanced", "mika", "extreme", "zero", "max_all"
    ])
    def test_100_random_emotions(self, temperament):
        """100 random emotions should never break invariants."""
        engine = make_engine(temperament)

        for i in range(100):
            emotion = random.choice(ALL_EMOTIONS)
            intensity = random.random()  # [0.0, 1.0)
            person = f"user_{random.randint(0, 4)}"

            engine.process_emotion(EmotionData(emotion, intensity), person)
            assert_invariants(engine, f"turn_{i}")

    @pytest.mark.parametrize("temperament", TEMPERAMENTS, ids=[
        "minimal", "balanced", "mika", "extreme", "zero", "max_all"
    ])
    def test_100_random_with_decay(self, temperament):
        """100 random emotions with random decay intervals."""
        engine = make_engine(temperament)

        for i in range(100):
            # Random decay
            if random.random() > 0.7:
                decay_time = random.uniform(1.0, 600.0)
                simulate_time_decay(engine, decay_time)

            emotion = random.choice(ALL_EMOTIONS)
            intensity = random.random()
            person = f"user_{random.randint(0, 9)}"

            engine.process_emotion(EmotionData(emotion, intensity), person)
            assert_invariants(engine, f"turn_{i}")

    def test_500_rapid_fire_single_person(self):
        """500 rapid-fire emotions for one person across all temperaments."""
        for temp in TEMPERAMENTS:
            engine = make_engine(temp)
            for i in range(500):
                emotion = ALL_EMOTIONS[i % len(ALL_EMOTIONS)]
                intensity = (i % 11) / 10.0  # 0.0, 0.1, ..., 1.0
                engine.process_emotion(EmotionData(emotion, intensity), "rapid_user")

            assert_invariants(engine, f"500_rapid_{temp.default_mood.value}")


# ===================================================================
# EDGE CASE SEQUENCES
# ===================================================================

class TestEdgeCaseSequences:

    def test_all_zero_intensity(self):
        """All emotions at intensity 0.0 should never break."""
        engine = make_engine(TEMPERAMENTS[2])  # Mika default
        for emotion in ALL_EMOTIONS:
            engine.process_emotion(EmotionData(emotion, 0.0), "user")
        assert_invariants(engine)

    def test_all_max_intensity(self):
        """All emotions at intensity 1.0 should never break."""
        engine = make_engine(TEMPERAMENTS[2])
        for emotion in ALL_EMOTIONS:
            engine.process_emotion(EmotionData(emotion, 1.0), "user")
        assert_invariants(engine)

    def test_same_emotion_1000_times(self):
        """Same emotion 1000 times should accumulate but stay bounded."""
        engine = make_engine(TEMPERAMENTS[2])
        for _ in range(1000):
            engine.process_emotion(EmotionData(Emotion.ANGRY, 0.9), "user")

        mood = engine._get_person_mood("user")
        assert mood.intensity <= 1.0
        assert_invariants(engine)

    def test_alternating_opposites(self):
        """Rapidly alternating between opposite emotions."""
        engine = make_engine(TEMPERAMENTS[2])
        for i in range(200):
            if i % 2 == 0:
                engine.process_emotion(EmotionData(Emotion.HAPPY, 0.9), "user")
            else:
                engine.process_emotion(EmotionData(Emotion.ANGRY, 0.9), "user")

        assert_invariants(engine)

    def test_extreme_temperament_with_extreme_input(self):
        """Maximum temperament + maximum intensity input."""
        engine = make_engine(TEMPERAMENTS[5])  # max everything
        for _ in range(100):
            engine.process_emotion(EmotionData(Emotion.ANGRY, 1.0), "user")

        assert_invariants(engine)

    def test_zero_temperament_with_extreme_input(self):
        """Zero reactivity temperament + maximum intensity input."""
        engine = make_engine(TEMPERAMENTS[4])  # zero reactivity
        for _ in range(100):
            engine.process_emotion(EmotionData(Emotion.ANGRY, 1.0), "user")

        assert_invariants(engine)


# ===================================================================
# MULTI-PERSON FUZZING
# ===================================================================

class TestMultiPersonFuzzing:

    def test_50_persons_random_emotions(self):
        """50 different persons with random emotions should all stay valid."""
        engine = make_engine(TEMPERAMENTS[2])

        for _ in range(500):
            person = f"user_{random.randint(0, 49)}"
            emotion = random.choice(ALL_EMOTIONS)
            intensity = random.random()
            engine.process_emotion(EmotionData(emotion, intensity), person)

        assert_invariants(engine)
        assert len(engine.person_moods) <= 50

    def test_persons_interleaved_with_decay(self):
        """Multiple persons with interleaved decay should maintain isolation."""
        engine = make_engine(TEMPERAMENTS[2])

        for i in range(200):
            if i % 20 == 0:
                simulate_time_decay(engine, random.uniform(10.0, 300.0))

            person = f"user_{i % 10}"
            emotion = random.choice(ALL_EMOTIONS)
            intensity = random.random()
            engine.process_emotion(EmotionData(emotion, intensity), person)

        assert_invariants(engine)


# ===================================================================
# DECAY INVARIANTS
# ===================================================================

class TestDecayInvariants:

    def test_decay_never_produces_negative_intensity(self):
        """Decay should never produce negative intensity."""
        for temp in TEMPERAMENTS:
            engine = make_engine(temp)
            engine.process_emotion(EmotionData(Emotion.HAPPY, 0.01), "user")

            # Extreme decay
            simulate_time_decay(engine, 10000.0)

            mood = engine._get_person_mood("user")
            assert mood.intensity >= 0.0
            assert engine.global_mood.intensity >= 0.0

    def test_repeated_decay_converges(self):
        """Repeated decay should converge to the home vector, not oscillate.

        Since circadian.py was introduced, home = default_mood × 0.15 +
        phase_bias × 0.35, so the oscillator settles near the biased home,
        not pure default. We only check that the *angry* impulse has fully
        dissipated — velocity is near zero and intensity is bounded by the
        home magnitude (~0.4 max).
        """
        engine = make_engine(TEMPERAMENTS[2])
        engine.process_emotion(EmotionData(Emotion.ANGRY, 0.9), "user")

        for _ in range(50):
            simulate_time_decay(engine, 10.0)

        mood = engine._get_person_mood("user")
        # Settled: velocity near zero (no residual anger impulse)
        from emotion import pad
        assert pad.norm(mood.dynamic.velocity) < 0.05
        # Intensity bounded by home magnitude (default × 0.15 + bias × 0.35)
        assert mood.intensity < 0.5
        # And no longer anger-flavored (valence should be non-negative)
        assert pad.valence(mood.emotion) >= 0.0


# ===================================================================
# ANALYTICS INVARIANTS
# ===================================================================

class TestAnalyticsInvariants:

    def test_analytics_always_valid(self):
        """Analytics should always produce valid output."""
        for temp in TEMPERAMENTS:
            engine = make_engine(temp)

            # Empty
            analytics = engine.get_analytics()
            assert analytics["total_interactions"] >= 0
            assert analytics["persons_tracked"] >= 0

            # After some interactions
            for i in range(20):
                engine.process_emotion(
                    EmotionData(random.choice(ALL_EMOTIONS), random.random()),
                    f"user_{i % 3}",
                )

            analytics = engine.get_analytics()
            assert analytics["total_interactions"] == 20
            assert analytics["persons_tracked"] == 3
            assert analytics["dominant_emotion"] in [e.value for e in Emotion]

            total = sum(analytics["distribution"].values())
            assert abs(total - 1.0) < 0.01, \
                f"Distribution should sum to ~1.0, got {total}"
