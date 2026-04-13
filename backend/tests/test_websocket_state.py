"""
Tests for WebSocket state protocol conformity.

Verifies that get_state_dict() and related methods always produce
JSON-serializable output matching the protocol expected by the frontend.

Frontend expects:
{
  "type": "speech",
  "text": "...",
  "emotion": "happy",
  "emotion_intensity": 0.75,
  "emotion_state": {
    "person": {"emotion": "happy", "intensity": 0.7, "momentum": 0.0},
    "global": {"emotion": "happy", "intensity": 0.1},
    "message": {"emotion": "happy", "intensity": 0.7}
  },
  "source": "frontend"
}
"""

import json
import pytest

from emotion.types import Emotion, EmotionData
from emotion.state import PersonMood, GlobalMood, MessageEmotion
from tests.conftest import simulate_time_decay


# ===================================================================
# STATE DICT STRUCTURE
# ===================================================================

class TestStateDictStructure:

    def test_has_required_keys(self, engine):
        """State dict must have person, global, and message keys."""
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.7), "user1")
        state = engine.get_state_dict("user1")

        assert "person" in state
        assert "global" in state
        assert "message" in state

    def test_person_dict_structure(self, engine):
        engine.process_emotion(EmotionData(Emotion.EXCITED, 0.8), "user1")
        state = engine.get_state_dict("user1")

        person = state["person"]
        assert "emotion" in person
        assert "intensity" in person
        assert "momentum" in person
        assert isinstance(person["emotion"], str)
        assert isinstance(person["intensity"], (int, float))
        assert isinstance(person["momentum"], (int, float))

    def test_global_dict_structure(self, engine):
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.7), "user1")
        state = engine.get_state_dict("user1")

        glob = state["global"]
        assert "emotion" in glob
        assert "intensity" in glob
        assert isinstance(glob["emotion"], str)
        assert isinstance(glob["intensity"], (int, float))

    def test_message_dict_structure(self, engine):
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.7), "user1")
        state = engine.get_state_dict("user1")

        msg = state["message"]
        assert "emotion" in msg
        assert "intensity" in msg
        assert isinstance(msg["emotion"], str)
        assert isinstance(msg["intensity"], (int, float))


# ===================================================================
# JSON SERIALIZATION
# ===================================================================

class TestJsonSerialization:

    def test_state_dict_is_json_serializable(self, engine):
        """State dict must be fully JSON-serializable for WebSocket."""
        engine.process_emotion(EmotionData(Emotion.ANGRY, 0.9), "user1")
        state = engine.get_state_dict("user1")

        # This must not raise
        json_str = json.dumps(state)
        assert isinstance(json_str, str)
        assert len(json_str) > 10

    def test_roundtrip_json(self, engine):
        """State dict should survive JSON encode/decode roundtrip."""
        engine.process_emotion(EmotionData(Emotion.CURIOUS, 0.6), "user1")
        state = engine.get_state_dict("user1")

        roundtrip = json.loads(json.dumps(state))
        assert roundtrip["person"]["emotion"] == state["person"]["emotion"]
        assert roundtrip["global"]["emotion"] == state["global"]["emotion"]
        assert roundtrip["message"]["emotion"] == state["message"]["emotion"]

    def test_all_emotions_produce_serializable_state(self, engine):
        """Every emotion should produce a valid JSON-serializable state."""
        for emotion in Emotion:
            engine.process_emotion(EmotionData(emotion, 0.7), "json_test")
            state = engine.get_state_dict("json_test")
            json_str = json.dumps(state)
            assert isinstance(json_str, str)


# ===================================================================
# EMOTION VALUES MATCH FRONTEND EXPECTATIONS
# ===================================================================

class TestEmotionValueFormat:

    def test_emotion_is_lowercase_string(self, engine):
        """Frontend expects lowercase emotion names (matching Emotion enum values)."""
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.7), "user1")
        state = engine.get_state_dict("user1")

        assert state["person"]["emotion"].islower() or state["person"]["emotion"] == "neutral"
        assert state["message"]["emotion"].islower() or state["message"]["emotion"] == "neutral"

    def test_emotion_is_valid_enum_value(self, engine):
        """Emotion string should be a valid Emotion enum value."""
        valid_values = {e.value for e in Emotion}

        for emotion in [Emotion.HAPPY, Emotion.SAD, Emotion.MISCHIEVOUS,
                        Emotion.MELANCHOLIC, Emotion.NEUTRAL]:
            engine.process_emotion(EmotionData(emotion, 0.7), "user1")
            state = engine.get_state_dict("user1")

            assert state["person"]["emotion"] in valid_values
            assert state["global"]["emotion"] in valid_values
            assert state["message"]["emotion"] in valid_values

    def test_intensity_is_rounded(self, engine):
        """Intensities should be rounded to 2 decimal places."""
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.777777), "user1")
        state = engine.get_state_dict("user1")

        person_i = state["person"]["intensity"]
        assert person_i == round(person_i, 2)

    def test_intensity_range(self, engine):
        """All intensities should be in [0.0, 1.0]."""
        engine.process_emotion(EmotionData(Emotion.ANGRY, 1.0), "user1")
        state = engine.get_state_dict("user1")

        assert 0.0 <= state["person"]["intensity"] <= 1.0
        assert 0.0 <= state["global"]["intensity"] <= 1.0
        assert 0.0 <= state["message"]["intensity"] <= 1.0


# ===================================================================
# STATE CONSISTENCY ACROSS TIME
# ===================================================================

class TestStateConsistencyOverTime:

    def test_state_valid_after_decay(self, engine):
        """State dict should remain valid after emotion decay."""
        engine.process_emotion(EmotionData(Emotion.EXCITED, 0.9), "user1")
        simulate_time_decay(engine, 120.0)

        state = engine.get_state_dict("user1")
        json.dumps(state)  # should not raise

        assert 0.0 <= state["person"]["intensity"] <= 1.0
        assert state["person"]["emotion"] in {e.value for e in Emotion}

    def test_state_valid_for_unknown_person(self, engine):
        """State dict for an untracked person should be valid."""
        state = engine.get_state_dict("never_seen")
        json.dumps(state)  # should not raise

        assert state["person"]["emotion"] in {e.value for e in Emotion}
        assert 0.0 <= state["person"]["intensity"] <= 1.0

    def test_state_consistent_after_opposition(self, engine):
        """State dict should reflect opposition correctly."""
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.8), "user1")
        engine.process_emotion(EmotionData(Emotion.ANGRY, 0.9), "user1")

        state = engine.get_state_dict("user1")
        json.dumps(state)

        assert state["person"]["emotion"] in {e.value for e in Emotion}

    def test_state_after_multi_person(self, engine):
        """State dicts for different persons should have independent states."""
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.9), "alice")
        engine.process_emotion(EmotionData(Emotion.SAD, 0.8), "bob")

        state_alice = engine.get_state_dict("alice")
        state_bob = engine.get_state_dict("bob")

        # Person emotions should differ
        assert state_alice["person"]["emotion"] != state_bob["person"]["emotion"] or \
               state_alice["person"]["intensity"] != state_bob["person"]["intensity"]

        # Global should be the same for both
        assert state_alice["global"] == state_bob["global"]


# ===================================================================
# TO_DICT METHODS
# ===================================================================

class TestToDictMethods:

    def test_person_mood_to_dict(self):
        mood = PersonMood(person_id="test", emotion=Emotion.HAPPY,
                         intensity=0.756, momentum=0.312)
        d = mood.to_dict()

        assert d["emotion"] == "happy"
        assert d["intensity"] == 0.76  # rounded
        assert d["momentum"] == 0.31  # rounded

    def test_global_mood_to_dict(self):
        mood = GlobalMood(emotion=Emotion.ANGRY, intensity=0.823)
        d = mood.to_dict()

        assert d["emotion"] == "angry"
        assert d["intensity"] == 0.82

    def test_message_emotion_to_dict(self):
        msg = MessageEmotion(
            emotion=Emotion.CURIOUS,
            intensity=0.654,
            person_emotion=Emotion.CURIOUS,
            person_intensity=0.7,
            global_emotion=Emotion.HAPPY,
            global_intensity=0.3,
        )
        d = msg.to_dict()

        assert d["emotion"] == "curious"
        assert d["intensity"] == 0.65
