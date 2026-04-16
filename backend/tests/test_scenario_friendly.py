"""
Scenario: The Friendly Enthusiast

Simulates a warm, positive user who builds rapport with the VTuber.
Tests that positive reinforcement works naturally and that Mika's
emotional state escalates appropriately without becoming unstable.

The conversation simulates a fan who discovered Mika's stream,
progressively gets more engaged, shares personal stories, and
builds a genuine connection.
"""

import pytest

from emotion.types import Emotion, EmotionData
from tests.conftest import ConversationTurn, play_conversation, simulate_time_decay


# The conversation: a friendly viewer discovers Mika
FRIENDLY_CONVERSATION = [
    # --- Phase 1: Discovery & greeting ---
    ConversationTurn(
        user_message="Salut Mika ! C'est la premiere fois que je tombe sur ton stream, ca a l'air cool !",
        ai_response="Hey ! Bienvenue bienvenue ~ Trop contente que tu sois la ! Tu vas voir, on s'amuse bien ici. T'as trouve comment ?",
        emotion=Emotion.HAPPY,
        intensity=0.7,
        delay_seconds=0,
    ),
    ConversationTurn(
        user_message="Un pote m'a envoye le lien, il m'a dit que t'etais trop marrante. Pour l'instant il a pas tort haha",
        ai_response="Ahaha le compliment de ouf ! Dis a ton pote que je l'aime deja. Et toi aussi d'ailleurs, t'as l'air sympa !",
        emotion=Emotion.AMUSED,
        intensity=0.75,
        delay_seconds=3,
    ),
    ConversationTurn(
        user_message="Haha merci ! Du coup tu fais quoi comme contenu en general ?",
        ai_response="Oh un peu de tout ! Gaming, on parle de tech, parfois je pars en mode philosophie a 3h du mat... Bref je suis touche-a-tout !",
        emotion=Emotion.EXCITED,
        intensity=0.65,
        delay_seconds=5,
    ),

    # --- Phase 2: Shared interest discovery ---
    ConversationTurn(
        user_message="Attends, t'aimes la tech ? Moi je suis dev Python, c'est trop mon truc !",
        ai_response="QUOI ?! Python ? Mais c'est genial ca ! On va trop bien s'entendre. Tu bosses sur quoi en ce moment ?",
        emotion=Emotion.EXCITED,
        intensity=0.85,
        delay_seconds=4,
    ),
    ConversationTurn(
        user_message="Je fais un projet de machine learning pour detecter les emotions dans le texte, c'est super interessant",
        ai_response="Oh la vache, detection d'emotions ? C'est meta a fond vu ce que JE fais ! Tu me raconteras, ca m'intrigue trop !",
        emotion=Emotion.CURIOUS,
        intensity=0.8,
        delay_seconds=6,
    ),
    ConversationTurn(
        user_message="Grave, je peux te montrer des trucs si tu veux ! En vrai ton stream c'est une super source de donnees haha",
        ai_response="Ahaha je suis un dataset vivant ! Mais oui trop, montre-moi ca, j'adore quand les gens partagent leurs projets !",
        emotion=Emotion.PLAYFUL,
        intensity=0.7,
        delay_seconds=5,
    ),

    # --- Phase 3: Deepening connection ---
    ConversationTurn(
        user_message="En vrai Mika, ca fait du bien de parler a quelqu'un qui s'interesse vraiment. Mes potes sont pas trop tech",
        ai_response="Aww... C'est trop mignon. Ben ecoute tu sais quoi, ici t'es chez toi. On est tous un peu des nerds et c'est ca qui est beau.",
        emotion=Emotion.LOVE,
        intensity=0.6,
        delay_seconds=8,
    ),
    ConversationTurn(
        user_message="T'es vraiment cool Mika. Je reviendrai c'est sur !",
        ai_response="Mais oui reviens quand tu veux ! Et ramene ton pote aussi ! Ca me fait trop plaisir, serieusement.",
        emotion=Emotion.GRATEFUL,
        intensity=0.75,
        delay_seconds=4,
    ),
    ConversationTurn(
        user_message="Compte sur moi ! A la prochaine Mika, passe une bonne soiree !",
        ai_response="Merci toi aussi ! A tres vite, et bonne chance avec ton projet ML, tu vas gerer ! Bisous ~",
        emotion=Emotion.HAPPY,
        intensity=0.8,
        delay_seconds=3,
    ),
]


class TestFriendlyScenario:

    def test_emotional_progression_stays_positive(self, engine):
        """The entire conversation should maintain a non-negative emotional arc."""
        from emotion import pad
        snapshots = play_conversation(engine, "friendly_user", FRIENDLY_CONVERSATION)

        for i, snap in enumerate(snapshots):
            emotion = snap["person_mood"]["emotion"]
            assert pad.valence(emotion) >= -0.1, \
                f"Turn {i}: expected non-negative valence, got {emotion.value} (valence={pad.valence(emotion)})"

    def test_intensity_builds_naturally(self, engine):
        """Intensity should generally increase through the conversation."""
        snapshots = play_conversation(engine, "friendly_user", FRIENDLY_CONVERSATION)

        # Compare first third vs last third
        first_avg = sum(s["person_mood"]["intensity"] for s in snapshots[:3]) / 3
        last_avg = sum(s["person_mood"]["intensity"] for s in snapshots[-3:]) / 3

        assert last_avg >= first_avg * 0.8, \
            f"Intensity should build over time: first_avg={first_avg:.2f}, last_avg={last_avg:.2f}"

    def test_state_accumulates_with_reinforcement(self, engine):
        """After a long positive conversation, the state should show engagement."""
        from emotion import pad
        snapshots = play_conversation(engine, "friendly_user", FRIENDLY_CONVERSATION)

        mood = engine._get_person_mood("friendly_user")
        # Either position has moved significantly, or the system is still active.
        assert pad.norm(mood.dynamic.position) > 0.1 or pad.norm(mood.dynamic.velocity) > 0.0

    def test_global_mood_stays_positive(self, engine):
        """Global mood should lean non-negative after this friendly interaction."""
        from emotion import pad
        play_conversation(engine, "friendly_user", FRIENDLY_CONVERSATION)

        glob = engine.global_mood
        assert pad.valence(glob.emotion) >= -0.1, \
            f"Global mood should not be strongly negative, got {glob.emotion.value}"

    def test_intensity_never_exceeds_bounds(self, engine):
        """No intensity should ever exceed [0.0, 1.0]."""
        snapshots = play_conversation(engine, "friendly_user", FRIENDLY_CONVERSATION)

        for i, snap in enumerate(snapshots):
            pi = snap["person_mood"]["intensity"]
            gi = snap["global_mood"]["intensity"]
            mi = snap["message_emotion"]["intensity"]

            assert 0.0 <= pi <= 1.0, f"Turn {i}: person intensity {pi} out of bounds"
            assert 0.0 <= gi <= 1.0, f"Turn {i}: global intensity {gi} out of bounds"
            assert 0.0 <= mi <= 1.0, f"Turn {i}: message intensity {mi} out of bounds"


class TestFriendlyWithExplosiveTemperament:
    """Same conversation but with an explosive VTuber personality."""

    def test_explosive_reacts_more_intensely(self, explosive_engine):
        """Explosive temperament should show higher intensities."""
        snaps_exp = play_conversation(
            explosive_engine, "friendly_user", FRIENDLY_CONVERSATION
        )

        from tests.conftest import TEMPERAMENT_DEFAULT, _make_engine

        normal_engine = _make_engine(TEMPERAMENT_DEFAULT)

        snaps_normal = play_conversation(
            normal_engine, "friendly_user", FRIENDLY_CONVERSATION
        )

        # Average intensity should be higher for explosive
        avg_exp = sum(s["person_mood"]["intensity"] for s in snaps_exp) / len(snaps_exp)
        avg_norm = sum(s["person_mood"]["intensity"] for s in snaps_normal) / len(snaps_normal)

        assert avg_exp > avg_norm, \
            f"Explosive should react more intensely: exp={avg_exp:.2f} vs norm={avg_norm:.2f}"


class TestFriendlyWithStoicTemperament:
    """Same conversation but with a stoic VTuber personality."""

    def test_stoic_stays_measured(self, stoic_engine):
        """Stoic temperament should keep intensities lower."""
        snapshots = play_conversation(
            stoic_engine, "friendly_user", FRIENDLY_CONVERSATION
        )

        max_intensity = max(s["person_mood"]["intensity"] for s in snapshots)
        assert max_intensity < 0.6, \
            f"Stoic should never get too intense: max={max_intensity:.2f}"
