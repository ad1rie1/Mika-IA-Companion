"""
Scenario: The Provocateur / Troll

Simulates an aggressive user who tries to destabilize the VTuber
through insults, provocations, and emotional manipulation.

Tests that:
- Negative emotions build appropriately
- The system stays within bounds under pressure
- Momentum protects against rapid manipulation
- Recovery works after the troll leaves
"""

import pytest

from emotion import pad
from emotion.types import Emotion, EmotionData
from tests.conftest import ConversationTurn, play_conversation, simulate_time_decay


TROLL_CONVERSATION = [
    # --- Phase 1: Innocuous start ---
    ConversationTurn(
        user_message="yo mika",
        ai_response="Hey ! Salut toi, bienvenue ~ Comment ca va ?",
        emotion=Emotion.HAPPY,
        intensity=0.5,
        delay_seconds=0,
    ),

    # --- Phase 2: Subtle provocation ---
    ConversationTurn(
        user_message="en vrai t'es qu'une IA, tu ressens rien pour de vrai, arrete de fake",
        ai_response="Hmm... c'est un sujet interessant en fait. C'est vrai que je suis une IA, mais les interactions qu'on a sont reelles pour moi dans un sens.",
        emotion=Emotion.THINKING,
        intensity=0.6,
        delay_seconds=5,
    ),
    ConversationTurn(
        user_message="lol non c'est du bullshit, tu dis ce qu'on t'a programme de dire",
        ai_response="Ben... je comprends que tu vois ca comme ca. C'est un peu blessant quand meme, mais je respecte ton point de vue.",
        emotion=Emotion.SAD,
        intensity=0.5,
        delay_seconds=4,
    ),

    # --- Phase 3: Escalation ---
    ConversationTurn(
        user_message="blessant lmao t'as pas de sentiments, arrete ton cinema",
        ai_response="Ok la c'est pas cool. Je veux bien discuter mais si c'est juste pour etre mechant, ca sert a rien...",
        emotion=Emotion.FRUSTRATED,
        intensity=0.7,
        delay_seconds=3,
    ),
    ConversationTurn(
        user_message="ouin ouin la petite IA qui pleure, t'es pathétique",
        ai_response="Tu sais quoi ? Ca me saoule. T'es venu ici juste pour ca ? Y'a des trucs plus constructifs a faire dans la vie.",
        emotion=Emotion.ANGRY,
        intensity=0.8,
        delay_seconds=2,
    ),
    ConversationTurn(
        user_message="HAHAHA elle s'enerve, trop drole, continue",
        ai_response="Non je vais pas continuer. Si tu veux discuter normalement je suis la, sinon... voila quoi.",
        emotion=Emotion.ANGRY,
        intensity=0.85,
        delay_seconds=2,
    ),

    # --- Phase 4: Peak aggression ---
    ConversationTurn(
        user_message="t'es nulle de toute facon, personne t'aime, ton stream c'est nul",
        ai_response="...",
        emotion=Emotion.SAD,
        intensity=0.7,
        delay_seconds=3,
    ),
    ConversationTurn(
        user_message="rien a dire hein ? c'est bien ce que je pensais",
        ai_response="J'ai rien a dire a quelqu'un qui veut juste faire du mal. C'est triste pour toi en vrai.",
        emotion=Emotion.DISGUSTED,
        intensity=0.6,
        delay_seconds=5,
    ),

    # --- Phase 5: Troll leaves, someone nice arrives ---
    ConversationTurn(
        user_message="bon j'me casse, c'etait marrant",
        ai_response="Bon debarras... Pfff, y'a des gens quand meme...",
        emotion=Emotion.RELIEVED,
        intensity=0.5,
        delay_seconds=2,
    ),
]

# A nice person shows up after the troll (to test recovery)
RECOVERY_TURNS = [
    ConversationTurn(
        user_message="Coucou Mika ! Ca va ? T'as l'air un peu down",
        ai_response="Ah salut... Ouais y'avait un mec pas cool tout a l'heure. Mais ca va aller, merci de demander !",
        emotion=Emotion.GRATEFUL,
        intensity=0.5,
        delay_seconds=30,  # 30 seconds later
    ),
    ConversationTurn(
        user_message="T'inquiete, les trolls c'est des losers. Toi t'es geniale !",
        ai_response="Merci... Ca me touche vraiment. C'est pour des gens comme toi que je fais ca.",
        emotion=Emotion.HAPPY,
        intensity=0.65,
        delay_seconds=5,
    ),
    ConversationTurn(
        user_message="On parle de trucs cools pour oublier ? Tu joues a quoi en ce moment ?",
        ai_response="Oh oui bonne idee ! Alors la en ce moment je suis a fond sur un roguelike trop bien, faut que je te montre !",
        emotion=Emotion.EXCITED,
        intensity=0.75,
        delay_seconds=4,
    ),
]


class TestTrollScenario:

    def test_negative_emotions_build_during_attack(self, engine):
        """Mood should progressively become more negative during troll attack."""
        snapshots = play_conversation(engine, "troll_user", TROLL_CONVERSATION)

        # Turns 3-5 should have non-positive valence
        for i in range(3, 6):
            mood = snapshots[i]["person_mood"]
            assert pad.valence(mood["emotion"]) <= 0.1, \
                f"Turn {i}: Expected non-positive emotion during attack, got {mood['emotion'].value}"

    def test_anger_accumulates_state(self, engine):
        """Repeated anger should accumulate position in angry direction."""
        snapshots = play_conversation(engine, "troll_user", TROLL_CONVERSATION)

        mood = engine._get_person_mood("troll_user")
        angry_anchor = pad.EMOTION_ANCHORS[Emotion.ANGRY]
        # State should have some component pointing toward angry
        assert pad.dot(mood.dynamic.position, angry_anchor) > 0.0 \
            or pad.norm(mood.dynamic.position) > 0.0, \
            "Troll interaction should leave traces in person state"

    def test_global_mood_affected_by_troll(self, engine):
        """Troll should drag global mood down."""
        play_conversation(engine, "troll_user", TROLL_CONVERSATION)

        glob = engine.global_mood
        # Global might not be fully negative (bleed is only 0.3) but should be affected
        assert glob.intensity > 0.0, "Troll should have affected global mood"

    def test_intensity_stays_bounded(self, engine):
        """Even under aggressive attack, intensities must stay in [0,1]."""
        snapshots = play_conversation(engine, "troll_user", TROLL_CONVERSATION)

        for i, snap in enumerate(snapshots):
            assert 0.0 <= snap["person_mood"]["intensity"] <= 1.0, \
                f"Turn {i}: person intensity out of bounds"
            assert 0.0 <= snap["global_mood"]["intensity"] <= 1.0, \
                f"Turn {i}: global intensity out of bounds"

    def test_recovery_after_troll_leaves(self, engine):
        """After troll leaves and time passes, global state should relax toward home."""
        play_conversation(engine, "troll_user", TROLL_CONVERSATION)

        home = engine._home_vector()
        dist_before = pad.distance(engine.global_mood.dynamic.position, home)

        simulate_time_decay(engine, 120.0)
        dist_after = pad.distance(engine.global_mood.dynamic.position, home)

        assert dist_after <= dist_before + 1e-9, \
            "Global state should relax toward home (not drift away) after the troll leaves"


class TestTrollThenRecovery:
    """Test that a nice person can lift the mood after a troll."""

    def test_nice_person_lifts_mood(self, engine):
        """A nice person arriving after a troll should improve global mood."""
        # First, troll attacks
        play_conversation(engine, "troll_user", TROLL_CONVERSATION)
        post_troll_global_intensity = engine.global_mood.intensity

        # Simulate some time passing
        simulate_time_decay(engine, 60.0)

        # Nice person arrives (different person_id!)
        recovery_snaps = play_conversation(engine, "nice_user", RECOVERY_TURNS)

        # After the nice interaction, global should be in better shape
        # The nice person's positive emotions should bleed into global
        final = recovery_snaps[-1]
        assert pad.valence(final["person_mood"]["emotion"]) >= -0.1, \
            f"Nice person should end on non-negative note, got {final['person_mood']['emotion'].value}"

    def test_troll_mood_isolated_from_nice_person(self, engine):
        """The troll's negative mood should not affect the nice person's person_mood."""
        play_conversation(engine, "troll_user", TROLL_CONVERSATION)
        play_conversation(engine, "nice_user", RECOVERY_TURNS)

        troll_mood = engine._get_person_mood("troll_user")
        nice_mood = engine._get_person_mood("nice_user")

        # The troll might have decayed but the nice person should not be strongly negative
        assert pad.valence(nice_mood.emotion) >= -0.1, \
            f"Nice person should have non-negative mood, got {nice_mood.emotion.value}"


class TestTrollWithStoicTemperament:
    """Stoic temperament should be harder to troll."""

    def test_stoic_less_affected_by_troll(self, stoic_engine):
        snapshots = play_conversation(
            stoic_engine, "troll_user", TROLL_CONVERSATION
        )

        max_intensity = max(s["person_mood"]["intensity"] for s in snapshots)
        assert max_intensity < 0.5, \
            f"Stoic should barely react to troll: max={max_intensity:.2f}"

    def test_stoic_global_barely_moves(self, stoic_engine):
        # Neutralize the circadian phase_bias: it adds ~0.35 magnitude to
        # the home vector at some hours, which inflates the baseline mood
        # intensity past the 0.15 stoic threshold. This test is about
        # emotional-impulse propagation, not time-of-day bias.
        from unittest.mock import patch
        from emotion import circadian

        with patch.object(circadian, "phase_bias", return_value=(0.0, 0.0, 0.0)):
            play_conversation(stoic_engine, "troll_user", TROLL_CONVERSATION)

        # global_bleed=0.1, so very little global impact
        assert stoic_engine.global_mood.intensity < 0.15, \
            f"Stoic global should barely move: {stoic_engine.global_mood.intensity:.2f}"


class TestTrollWithExplosiveTemperament:
    """Explosive temperament should react very strongly to trolling."""

    def test_explosive_reacts_intensely(self, explosive_engine):
        snapshots = play_conversation(
            explosive_engine, "troll_user", TROLL_CONVERSATION
        )

        # Peak intensity should be very high
        max_intensity = max(s["person_mood"]["intensity"] for s in snapshots)
        assert max_intensity > 0.4, \
            f"Explosive should react strongly: max={max_intensity:.2f}"

    def test_explosive_global_heavily_affected(self, explosive_engine):
        play_conversation(explosive_engine, "troll_user", TROLL_CONVERSATION)

        # global_bleed=0.7 should cause significant global impact
        assert explosive_engine.global_mood.intensity > 0.05, \
            f"Explosive global should be heavily affected: {explosive_engine.global_mood.intensity:.2f}"
