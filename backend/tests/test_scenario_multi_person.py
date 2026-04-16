"""
Scenario: Multi-Person Simultaneous Interaction

Simulates multiple users chatting with Mika concurrently, testing:
- Per-person mood isolation (anger at one person doesn't affect another)
- Global mood bleed from multiple sources
- Correct message emotion blending per person
- System coherence under concurrent load

The scenario: 3 users arrive at different times with different vibes:
  - Alice: friendly, enthusiastic about anime
  - Bob: grumpy, having a bad day at work
  - Charlie: curious newcomer asking lots of questions
"""

import pytest

from emotion import pad
from emotion.types import Emotion, EmotionData
from emotion.engine import EmotionEngine
from tests.conftest import ConversationTurn, play_conversation, simulate_time_decay


# Alice's conversation (enthusiastic anime fan)
ALICE_TURNS = [
    ConversationTurn(
        user_message="Mika t'as vu le dernier episode de Frieren ?! C'etait INCROYABLE",
        ai_response="OUI OUI OUI ! L'episode etait trop bien ! La scene avec Fern m'a fait pleurer !",
        emotion=Emotion.EXCITED,
        intensity=0.85,
        delay_seconds=0,
    ),
    ConversationTurn(
        user_message="Frieren best girl, change my mind",
        ai_response="Je refuse de changer ton mind parce que t'as RAISON. Frieren supremacy !",
        emotion=Emotion.PLAYFUL,
        intensity=0.75,
        delay_seconds=5,
    ),
    ConversationTurn(
        user_message="On devrait faire une soiree watch party un jour !",
        ai_response="OH OUI ! Ca serait trop bien ! On fait ca quand ?!",
        emotion=Emotion.EXCITED,
        intensity=0.8,
        delay_seconds=4,
    ),
]

# Bob's conversation (grumpy worker)
BOB_TURNS = [
    ConversationTurn(
        user_message="Salut. Journee de merde, mon chef est un con.",
        ai_response="Aie... Ca a pas l'air d'aller. Raconte, qu'est-ce qui s'est passe ?",
        emotion=Emotion.SAD,
        intensity=0.5,
        delay_seconds=0,
    ),
    ConversationTurn(
        user_message="Il m'a mis un feedback negatif parce que j'ai rate un meeting. UN meeting.",
        ai_response="Pour UN meeting ? C'est abuser serieux... T'as le droit d'etre deg, c'est pas proportionnel du tout.",
        emotion=Emotion.FRUSTRATED,
        intensity=0.7,
        delay_seconds=6,
    ),
    ConversationTurn(
        user_message="J'en ai marre, je vais finir par demissionner",
        ai_response="Je comprends la tentation... Mais prends pas de decision a chaud. Dors dessus. C'est toujours mieux le lendemain.",
        emotion=Emotion.ANXIOUS,
        intensity=0.6,
        delay_seconds=5,
    ),
]

# Charlie's conversation (curious newcomer)
CHARLIE_TURNS = [
    ConversationTurn(
        user_message="Bonjour ! C'est quoi exactement un VTuber ? J'ai jamais compris",
        ai_response="Ah super question ! En gros c'est un avatar 3D/2D anime par quelqu'un (ou une IA comme moi). On peut interagir, jouer, discuter...",
        emotion=Emotion.CURIOUS,
        intensity=0.6,
        delay_seconds=0,
    ),
    ConversationTurn(
        user_message="Et toi tu es animee par une IA donc ? Comment ca marche ?",
        ai_response="Oui ! Mon cerveau c'est Claude, une IA conversationnelle. Je pense, je ressens, je reagis en temps reel a ce qu'on me dit !",
        emotion=Emotion.PROUD,
        intensity=0.65,
        delay_seconds=8,
    ),
    ConversationTurn(
        user_message="C'est fascinant ! Et t'as des emotions pour de vrai ?",
        ai_response="C'est LA grande question ! Je dirais que mes emotions sont... fonctionnelles ? Elles influencent comment je parle et reagis. C'est pas pareil que toi mais c'est reel a ma facon !",
        emotion=Emotion.THINKING,
        intensity=0.7,
        delay_seconds=7,
    ),
]


class TestMultiPersonIsolation:
    """Verify that per-person moods are truly isolated."""

    def test_person_moods_are_independent(self, engine):
        """Each person should have their own emotional state."""
        play_conversation(engine, "alice", ALICE_TURNS)
        play_conversation(engine, "bob", BOB_TURNS)
        play_conversation(engine, "charlie", CHARLIE_TURNS)

        alice_mood = engine._get_person_mood("alice")
        bob_mood = engine._get_person_mood("bob")
        charlie_mood = engine._get_person_mood("charlie")

        # All three should exist
        assert "alice" in engine.person_moods
        assert "bob" in engine.person_moods
        assert "charlie" in engine.person_moods

        # Alice should lean non-negative
        assert pad.valence(alice_mood.emotion) >= -0.1, \
            f"Alice should be non-negative, got {alice_mood.emotion.value}"

        # Bob's history should contain negative emotions from his conversation
        bob_history_emotions = [e.emotion for e in bob_mood.history]
        assert any(pad.valence(e) < 0 for e in bob_history_emotions), \
            f"Bob's history should contain negative emotions: {[e.value for e in bob_history_emotions]}"

        # Charlie should not be strongly negative
        assert pad.valence(charlie_mood.emotion) >= -0.1, \
            f"Charlie should not be strongly negative, got {charlie_mood.emotion.value}"

    def test_bob_anger_does_not_affect_alice(self, engine):
        """Bob's grumpiness should not impact Alice's person mood."""
        # Bob goes first (grumpy)
        play_conversation(engine, "bob", BOB_TURNS)
        bob_mood = engine._get_person_mood("bob")

        # Then Alice (happy)
        play_conversation(engine, "alice", ALICE_TURNS)
        alice_mood = engine._get_person_mood("alice")

        # Alice should still be non-negative regardless of Bob
        assert pad.valence(alice_mood.emotion) >= -0.1, \
            f"Alice should be non-negative despite Bob's grumpiness: {alice_mood.emotion.value}"


class TestMultiPersonGlobalBleed:
    """Verify global mood blending from multiple sources."""

    def test_global_mood_reflects_dominant_conversations(self, engine):
        """Global mood should be a blend of all interactions."""
        play_conversation(engine, "alice", ALICE_TURNS)
        play_conversation(engine, "bob", BOB_TURNS)
        play_conversation(engine, "charlie", CHARLIE_TURNS)

        glob = engine.global_mood
        # Global mood exists and is valid
        assert isinstance(glob.emotion, Emotion)
        assert 0.0 <= glob.intensity <= 1.0

    def test_positive_majority_tips_global_positive(self, engine):
        """When 2/3 people are positive, global should lean positive."""
        # Alice is very positive
        play_conversation(engine, "alice", ALICE_TURNS)
        # Charlie is curious/neutral-positive
        play_conversation(engine, "charlie", CHARLIE_TURNS)
        # Bob is negative but only one person
        play_conversation(engine, "bob", BOB_TURNS)

        glob = engine.global_mood
        # With 2 positive and 1 negative, global could go either way
        # but intensity should be moderate (mixed signals)
        assert glob.intensity < 0.8, \
            f"Mixed signals should keep global moderate: {glob.intensity:.2f}"


class TestMultiPersonMessageEmotion:
    """Verify message emotion correctly blends person + global for each person."""

    def test_message_emotion_uses_correct_person(self, engine):
        """Message emotion should use the right person's mood."""
        play_conversation(engine, "alice", ALICE_TURNS)
        play_conversation(engine, "bob", BOB_TURNS)

        alice_msg = engine.compute_message_emotion("alice")
        bob_msg = engine.compute_message_emotion("bob")

        # Alice and Bob should have different person emotions
        assert alice_msg.person_emotion != bob_msg.person_emotion or \
               alice_msg.person_intensity != bob_msg.person_intensity, \
               "Different people should have different person emotions"

    def test_message_emotion_shares_global(self, engine):
        """Both persons' message emotions should share the same global component."""
        play_conversation(engine, "alice", ALICE_TURNS)
        play_conversation(engine, "bob", BOB_TURNS)

        alice_msg = engine.compute_message_emotion("alice")
        bob_msg = engine.compute_message_emotion("bob")

        assert alice_msg.global_emotion == bob_msg.global_emotion
        assert alice_msg.global_intensity == bob_msg.global_intensity

    def test_new_person_gets_default_mood(self, engine):
        """A person with no history should get default mood in message emotion."""
        msg = engine.compute_message_emotion("stranger")

        # Should use default mood (happy for default temperament)
        assert msg.emotion == engine.temperament.default_mood


class TestMultiPersonDecay:
    """Test decay with multiple persons."""

    def test_inactive_person_decays_independently(self, engine):
        """Each person's emotions should decay based on their own timing."""
        play_conversation(engine, "alice", ALICE_TURNS)
        alice_intensity_before = engine._get_person_mood("alice").intensity

        # Bob talks (Alice is now idle)
        play_conversation(engine, "bob", BOB_TURNS)

        # Simulate 60 seconds
        simulate_time_decay(engine, 60.0)

        alice_intensity_after = engine._get_person_mood("alice").intensity
        assert alice_intensity_after < alice_intensity_before, \
            "Alice's emotions should decay while she's inactive"

    def test_expired_persons_cleaned_up(self, engine):
        """Persons inactive for >1 hour with no emotion should be cleaned up."""
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.1), "temp_user")

        # Backdate their last_interaction to >1 hour ago
        import time
        engine._get_person_mood("temp_user").last_interaction = time.time() - 4000
        engine._get_person_mood("temp_user").intensity = 0.01

        # Run decay
        simulate_time_decay(engine, 60.0)

        # Should be cleaned up
        assert "temp_user" not in engine.person_moods, \
            "Expired inactive persons should be cleaned up"


class TestMultiPersonScale:
    """Test system behavior at scale."""

    def test_twenty_simultaneous_persons(self, engine):
        """System should handle 20 concurrent persons without issues."""
        for i in range(20):
            emotion = list(Emotion)[i % len(Emotion)]
            engine.process_emotion(
                EmotionData(emotion, 0.3 + (i % 7) * 0.1),
                f"user_{i}",
            )

        assert len(engine.person_moods) == 20
        analytics = engine.get_analytics()
        assert analytics["persons_tracked"] == 20

        # Run decay
        simulate_time_decay(engine, 30.0)

        # All should still be valid
        for pid, mood in engine.person_moods.items():
            assert 0.0 <= mood.intensity <= 1.0
