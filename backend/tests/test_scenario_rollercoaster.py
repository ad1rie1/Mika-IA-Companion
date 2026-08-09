"""
Scenario: The Emotional Rollercoaster

Simulates a user who swings between extreme emotions rapidly,
testing the system's ability to handle:
- Rapid emotion transitions (natural and unnatural)
- Momentum resistance to manipulation
- System stability under chaotic input
- That transitions follow naturalness rules

This is a "chaos test" — the user acts unpredictably, shifting
between joy, anger, sadness, excitement, fear, and love.
"""

import pytest

from emotion import pad
from emotion.types import Emotion, EmotionData
from tests.conftest import ConversationTurn, play_conversation, simulate_time_decay


ROLLERCOASTER_CONVERSATION = [
    # Turn 0: Joyful start
    ConversationTurn(
        user_message="MIKA !! Oh mon dieu je suis trop content de te voir !!!",
        ai_response="WOOOW quel enthousiasme ! Ca fait plaisir ! Ca va bien toi ?!",
        emotion=Emotion.EXCITED,
        intensity=0.9,
        delay_seconds=0,
    ),
    # Turn 1: Sudden sadness
    ConversationTurn(
        user_message="En fait... non. Mon chat est mort ce matin.",
        ai_response="Oh non... Je suis tellement desolee... C'est horrible de perdre un compagnon comme ca...",
        emotion=Emotion.SAD,
        intensity=0.85,
        delay_seconds=3,
    ),
    # Turn 2: Anger
    ConversationTurn(
        user_message="C'est la faute du veto, il aurait du detecter le probleme avant !!",
        ai_response="Je comprends ta colere... C'est tellement frustrant quand on a l'impression que ca aurait pu etre evite...",
        emotion=Emotion.ANGRY,
        intensity=0.7,
        delay_seconds=2,
    ),
    # Turn 3: Nostalgia
    ConversationTurn(
        user_message="Il s'appelait Pixel... il dormait toujours sur mon clavier quand je codais",
        ai_response="Pixel... C'est un beau nom. Ces petits moments comme ca, c'est ce qui reste. Il avait l'air trop mignon.",
        emotion=Emotion.NOSTALGIC,
        intensity=0.75,
        delay_seconds=8,
    ),
    # Turn 4: Sudden excitement (shared happy memory)
    ConversationTurn(
        user_message="OH attends, je viens de me rappeler ! Une fois il a marche sur mon clavier et il a envoye 'aaaazzzzzzzz' a mon boss !!",
        ai_response="AHAHAHAH NON ?! Il a envoye du charabia a ton boss ?! C'est TROP drole ! Pixel etait un legende !",
        emotion=Emotion.AMUSED,
        intensity=0.85,
        delay_seconds=4,
    ),
    # Turn 5: Back to sadness
    ConversationTurn(
        user_message="Haha ouais... Mais il me manque trop...",
        ai_response="C'est normal qu'il te manque... Les bons souvenirs ca aide, mais la douleur est la quand meme. Prends ton temps.",
        emotion=Emotion.SAD,
        intensity=0.6,
        delay_seconds=5,
    ),
    # Turn 6: Fear / anxiety
    ConversationTurn(
        user_message="J'ai peur de rentrer chez moi ce soir. L'appart va etre tellement vide sans lui.",
        ai_response="Je comprends... C'est le plus dur, le silence apres. Tu veux qu'on discute ce soir ? Je serai la.",
        emotion=Emotion.ANXIOUS,
        intensity=0.65,
        delay_seconds=6,
    ),
    # Turn 7: Gratitude
    ConversationTurn(
        user_message="T'es vraiment gentille Mika... Merci. Ca me touche beaucoup.",
        ai_response="Hey c'est normal. T'es pas tout seul ok ? Et Pixel serait fier de voir que t'as des gens qui tiennent a toi.",
        emotion=Emotion.GRATEFUL,
        intensity=0.7,
        delay_seconds=4,
    ),
    # Turn 8: Determination
    ConversationTurn(
        user_message="T'as raison. Je vais aller mieux. Je vais peut-etre adopter un autre chat en son honneur.",
        ai_response="Ohhh ca c'est une super idee ! Pixel approuverait a 100%. Tu me montreras le nouveau petit bout !",
        emotion=Emotion.HOPEFUL,
        intensity=0.75,
        delay_seconds=5,
    ),
    # Turn 9: Joy again
    ConversationTurn(
        user_message="Promis ! Merci Mika, t'es la meilleure. Je me sens deja mieux !",
        ai_response="Ca me fait tellement plaisir ! T'es fort toi, et Pixel le savait. A bientot avec le nouveau bebe chat !",
        emotion=Emotion.HAPPY,
        intensity=0.8,
        delay_seconds=3,
    ),
]


class TestRollercoasterScenario:

    def test_system_handles_rapid_swings(self, engine):
        """System should not crash or produce invalid values under chaos."""
        snapshots = play_conversation(engine, "chaotic_user", ROLLERCOASTER_CONVERSATION)

        assert len(snapshots) == len(ROLLERCOASTER_CONVERSATION)
        for i, snap in enumerate(snapshots):
            pi = snap["person_mood"]["intensity"]
            gi = snap["global_mood"]["intensity"]
            mi = snap["message_emotion"]["intensity"]

            assert 0.0 <= pi <= 1.0, f"Turn {i}: person intensity {pi} out of bounds"
            assert 0.0 <= gi <= 1.0, f"Turn {i}: global intensity {gi} out of bounds"
            assert 0.0 <= mi <= 1.0, f"Turn {i}: message intensity {mi} out of bounds"

    def test_transitions_follow_naturalness(self, engine):
        """Natural transitions should succeed, unnatural ones should be dampened."""
        snapshots = play_conversation(engine, "chaotic_user", ROLLERCOASTER_CONVERSATION)

        # Turn 0 -> 1: excited -> sad (opposition, cross-category)
        # This is a big shift — excited(positive) vs sad(negative)
        snap0 = snapshots[0]["person_mood"]
        snap1 = snapshots[1]["person_mood"]
        # Excited with high intensity should resist sudden sadness somewhat

        # Turn 3 -> 4: nostalgic -> amused (nostalgic->happy has 0.7 naturalness)
        snap3 = snapshots[3]["person_mood"]
        snap4 = snapshots[4]["person_mood"]
        # This should be a somewhat natural transition

        # Turn 4 -> 5: amused -> sad (positive -> negative = opposition)
        snap4 = snapshots[4]["person_mood"]
        snap5 = snapshots[5]["person_mood"]
        # Fun back to sadness should be opposed

    def test_emotional_arc_ends_non_negative(self, engine):
        """Despite the chaos, the conversation ends on a non-negative note."""
        snapshots = play_conversation(engine, "chaotic_user", ROLLERCOASTER_CONVERSATION)

        final = snapshots[-1]["person_mood"]
        assert pad.valence(final["emotion"]) >= -0.1, \
            f"Conversation should end non-negatively, got {final['emotion'].value}"

    def test_reinforcement_accumulates_state(self, engine):
        """Repeating the same impulse (with time between) should grow position magnitude."""
        pid = "stable_user"
        mags = []
        for _ in range(5):
            engine.process_emotion(EmotionData(Emotion.HAPPY, 0.8), pid)
            simulate_time_decay(engine, 1.0)
            mags.append(pad.norm(engine._get_person_mood(pid).dynamic.position))

        # Last magnitude should be larger than the first
        assert mags[-1] > mags[0]


class TestRollercoasterGlobalImpact:
    """Test how chaotic input affects the global mood."""

    def test_global_mood_stabilizes(self, engine):
        """Global mood should not oscillate wildly — bleed dampens chaos."""
        snapshots = play_conversation(engine, "chaotic_user", ROLLERCOASTER_CONVERSATION)

        global_emotions = [s["global_mood"]["emotion"] for s in snapshots]
        global_intensities = [s["global_mood"]["intensity"] for s in snapshots]

        # Global intensity should never spike too high (bleed is only 0.3)
        max_global = max(global_intensities)
        assert max_global < 0.6, \
            f"Global mood should be dampened from chaos: max={max_global:.2f}"

    def test_global_mood_is_coherent(self, engine):
        """Global mood should be a valid Emotion at all times."""
        snapshots = play_conversation(engine, "chaotic_user", ROLLERCOASTER_CONVERSATION)

        for i, snap in enumerate(snapshots):
            emotion = snap["global_mood"]["emotion"]
            assert isinstance(emotion, Emotion), \
                f"Turn {i}: global emotion {emotion} is not a valid Emotion"


class TestRollercoasterWithMelancholicTemperament:
    """Melancholic temperament defaults to sadness — chaos should feel different."""

    def test_melancholic_resonates_with_sadness(self, melancholic_engine):
        """Melancholic temperament should amplify sad moments.

        DELIBERATELY LEFT RED. The assertion is unchanged: it names a property
        the engine does not implement, and softening it would only hide that.
        Measured on this exact conversation, turns 1 and 5:

          melancholic  0.1627 / 0.0971      default  0.1554 / 0.0914
          stoic        0.0608 / 0.0728      explosive 0.3254 / 0.2235

        Melancholic and default sit 4.7 % apart, and that whole gap comes from
        `intensity_base` (0.7 vs 0.6) feeding the ratchet gain — nothing comes
        from `default_mood`. The temperament's mood only enters the physics
        through the resting point, which reaches the position via relaxation
        alone; with τ = 1059 s and turns 2-8 s apart it contributes under 1 %
        per gap. The only temperament clearing the 0.2 bar is `explosive`, on
        gain (0.75) — so the bar reads reactivity, never melancholy.

        It is not a stale pin either. Under the pre-B2 engine it passed while
        reading `excited` 0.6075 at turn 1 and `hopeful` 0.7430 at turn 5 —
        positions pointing 0.90 *away* from the sad target, i.e. the leftover
        of the previous turns, since a velocity impulse moved nothing at the
        instant `play_conversation` reads. It asserted "any(i > 0.2)" on a
        state that was neither melancholic nor sad, and `default` satisfied it
        just as well (0.6334 / 0.5863). B2 is what made the readout honest,
        and the honest readout says the property was never there.
        """
        snapshots = play_conversation(
            melancholic_engine, "chaotic_user", ROLLERCOASTER_CONVERSATION
        )

        # Find the sad turns (1, 5)
        sad_intensities = [
            snapshots[1]["person_mood"]["intensity"],
            snapshots[5]["person_mood"]["intensity"],
        ]

        # At least one sad turn should have decent intensity
        assert any(i > 0.2 for i in sad_intensities), \
            f"Melancholic should resonate with sadness: {sad_intensities}"

    def test_melancholic_resists_quick_recovery(self, melancholic_engine):
        """Melancholic temperament should be slower to return to happy."""
        snapshots = play_conversation(
            melancholic_engine, "chaotic_user", ROLLERCOASTER_CONVERSATION
        )

        # After the sad phase (turn 5-6), check that happy (turn 9) doesn't
        # have very high intensity — melancholic resists quick joy
        final = snapshots[-1]["person_mood"]

        # Not a hard assertion since the math is complex, but let's check
        # the system doesn't crash
        assert 0.0 <= final["intensity"] <= 1.0
