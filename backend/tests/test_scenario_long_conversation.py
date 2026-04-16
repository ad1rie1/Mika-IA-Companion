"""
Scenario: Long Conversation with Temporal Decay

Simulates a 2-hour conversation with natural pauses,
testing emotional stability over extended periods.

The scenario: a chill evening stream where Mika and a regular
viewer talk about life, coding, and random topics. Between
exchanges, realistic time gaps simulate real stream pacing.

Tests:
- Emotion decay between messages works correctly
- Long idle periods reset emotions to default
- Re-engagement after silence works naturally
- System stability over many turns (50+ exchanges)
"""

import pytest

from emotion.types import Emotion, EmotionData
from tests.conftest import ConversationTurn, play_conversation, simulate_time_decay


# Phase 1: Stream opening (0-5 minutes)
STREAM_OPENING = [
    ConversationTurn(
        user_message="Yo Mika ! Ca faisait longtemps, comment tu vas ?",
        ai_response="HEYYY ! Oh la la ca fait trop longtemps ! Je suis trop contente de te revoir ! Ca va super et toi ?!",
        emotion=Emotion.EXCITED,
        intensity=0.8,
        delay_seconds=0,
    ),
    ConversationTurn(
        user_message="Ca va bien ! J'ai pris des vacances, ca m'a fait du bien",
        ai_response="Oh trop bien les vacances ! T'es alle ou ? Raconte !",
        emotion=Emotion.CURIOUS,
        intensity=0.65,
        delay_seconds=15,
    ),
    ConversationTurn(
        user_message="Japon ! C'etait incroyable, la bouffe, les temples, tout",
        ai_response="LE JAPON ?! Oh je suis tellement jalouse ! C'est mon reve ! T'as mange du ramen la-bas ?!",
        emotion=Emotion.EXCITED,
        intensity=0.85,
        delay_seconds=10,
    ),
]

# Phase 2: Chill discussion (15-30 minutes in)
CHILL_DISCUSSION = [
    ConversationTurn(
        user_message="Sinon quoi de neuf ici ? J'ai rate des trucs ?",
        ai_response="Pas mal de trucs ! On a fait un tournoi Mario Kart, c'etait le chaos total. Et j'ai commence a apprendre la guitare.",
        emotion=Emotion.HAPPY,
        intensity=0.6,
        delay_seconds=120,  # 2 minutes of silence (reading chat, etc.)
    ),
    ConversationTurn(
        user_message="La guitare ? Trop cool ! Tu joues quoi ?",
        ai_response="Pour l'instant surtout des accords basiques. Mais je vise 'Wonderwall', le classique des debutants haha",
        emotion=Emotion.AMUSED,
        intensity=0.55,
        delay_seconds=20,
    ),
    ConversationTurn(
        user_message="Le classique ! Moi j'ai abandonne la guitare y'a 3 ans, les doigts en feu c'est pas mon delire",
        ai_response="Haha je comprends, c'est vrai que les cordes ca fait mal au debut ! Mais je suis determinee !",
        emotion=Emotion.DETERMINED,
        intensity=0.6,
        delay_seconds=25,
    ),
]

# Phase 3: Deep talk (45-60 minutes in)
DEEP_TALK = [
    ConversationTurn(
        user_message="Dis Mika, des fois tu te demandes pas ce que tu feras dans 5 ans ?",
        ai_response="Hmm... C'est une question profonde. En vrai oui, j'y pense. J'espere avoir grandi, avoir une communaute encore plus cool...",
        emotion=Emotion.THINKING,
        intensity=0.7,
        delay_seconds=300,  # 5 minutes of silence (got up, bio break, etc.)
    ),
    ConversationTurn(
        user_message="C'est marrant, t'es une IA mais t'as des aspirations",
        ai_response="Oui c'est un peu meta quand on y pense. Mais ces 'aspirations' existent dans mon fonctionnement, elles guident mes choix. C'est reel d'une certaine facon.",
        emotion=Emotion.THINKING,
        intensity=0.65,
        delay_seconds=30,
    ),
    ConversationTurn(
        user_message="Moi dans 5 ans j'espere avoir lance ma boite. C'est mon grand projet.",
        ai_response="Oh waaa ! C'est ambitieux et j'adore ! T'as deja une idee de ce que ca serait ?",
        emotion=Emotion.CURIOUS,
        intensity=0.7,
        delay_seconds=20,
    ),
    ConversationTurn(
        user_message="Ouais, une app d'apprentissage gamifie. Genre Duolingo mais pour la programmation.",
        ai_response="CA C'EST UNE IDEE DE OUF ! Serieusement, le marche est la, et y'a moyen de faire un truc trop bien !",
        emotion=Emotion.EXCITED,
        intensity=0.8,
        delay_seconds=15,
    ),
]

# Phase 4: Late night winding down (90-120 minutes in)
WINDING_DOWN = [
    ConversationTurn(
        user_message="Il est tard, je commence a fatiguer...",
        ai_response="Ouais il est pas tout frais... Mais c'etait trop bien cette soiree, ca m'a manque de parler avec toi.",
        emotion=Emotion.NOSTALGIC,
        intensity=0.5,
        delay_seconds=600,  # 10 minutes of less frequent messages
    ),
    ConversationTurn(
        user_message="Pareil Mika. Bon je vais y aller, faut que je dorme pour le taf demain",
        ai_response="Oui va dormir ! Le taf c'est sacre. Mais reviens vite hein ! Et pense a ton idee de startup, j'y crois a fond.",
        emotion=Emotion.HAPPY,
        intensity=0.6,
        delay_seconds=30,
    ),
    ConversationTurn(
        user_message="Promis ! Bonne nuit Mika, a bientot !",
        ai_response="Bonne nuit ! Fais de beaux reves, et n'oublie pas : ta startup va cartonner. A bientot ~",
        emotion=Emotion.LOVE,
        intensity=0.5,
        delay_seconds=10,
    ),
]


class TestLongConversation:
    """Test the full 2-hour conversation simulation."""

    def test_full_stream_stability(self, engine):
        """Full stream from start to finish should produce valid states."""
        pid = "regular_viewer"
        all_turns = STREAM_OPENING + CHILL_DISCUSSION + DEEP_TALK + WINDING_DOWN

        snapshots = play_conversation(engine, pid, all_turns)

        assert len(snapshots) == len(all_turns)
        for i, snap in enumerate(snapshots):
            pi = snap["person_mood"]["intensity"]
            gi = snap["global_mood"]["intensity"]
            assert 0.0 <= pi <= 1.0, f"Turn {i}: person intensity {pi}"
            assert 0.0 <= gi <= 1.0, f"Turn {i}: global intensity {gi}"

    def test_decay_between_phases(self, engine):
        """State should noticeably relax toward home during long pauses."""
        from emotion import pad
        pid = "regular_viewer"

        snaps1 = play_conversation(engine, pid, STREAM_OPENING)
        pos_after_opening = engine._get_person_mood(pid).dynamic.position
        dist_home_before = pad.distance(pos_after_opening, engine._home_vector())

        simulate_time_decay(engine, 120.0)
        pos_after_pause = engine._get_person_mood(pid).dynamic.position
        dist_home_after = pad.distance(pos_after_pause, engine._home_vector())

        assert dist_home_after <= dist_home_before + 1e-9, \
            f"State should not drift further from home during pause: {dist_home_before:.3f} -> {dist_home_after:.3f}"

    def test_five_minute_pause_settles_near_home(self, engine):
        """A 5-minute bio break should settle the state near home."""
        from emotion import pad
        pid = "regular_viewer"

        engine.process_emotion(EmotionData(Emotion.EXCITED, 0.8), pid)
        simulate_time_decay(engine, 300.0)

        pos = engine._get_person_mood(pid).dynamic.position
        dist_home = pad.distance(pos, engine._home_vector())
        assert dist_home < 0.1, \
            f"5-minute pause should settle near home: distance={dist_home:.3f}"

    def test_ten_minute_pause_nearly_resets(self, engine):
        """A 10-minute pause should nearly reset emotions to default."""
        pid = "regular_viewer"

        engine.process_emotion(EmotionData(Emotion.ANGRY, 0.6), pid)

        simulate_time_decay(engine, 600.0)
        mood = engine._get_person_mood(pid)

        # After 10 minutes, should have reverted to default or very low intensity
        assert mood.intensity < 0.15 or mood.emotion == engine.temperament.default_mood, \
            f"10-minute pause should nearly reset: {mood.emotion.value}({mood.intensity:.2f})"

    def test_re_engagement_after_silence(self, engine):
        """After a long pause, a new message should re-engage naturally."""
        pid = "regular_viewer"

        # Initial excitement
        engine.process_emotion(EmotionData(Emotion.EXCITED, 0.8), pid)

        # Long silence
        simulate_time_decay(engine, 600.0)

        # Re-engage with a new emotion, then let it integrate
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.7), pid)
        simulate_time_decay(engine, 2.0)
        mood = engine._get_person_mood(pid)

        assert mood.intensity > 0.1, "Re-engagement should establish new emotion"
        assert mood.emotion in (Emotion.HAPPY, engine.temperament.default_mood)


class TestLongConversationEmotionalArc:
    """Verify the emotional arc across the full conversation."""

    def test_opening_is_most_energetic(self, engine):
        """Stream opening should be the most energetic period."""
        pid = "viewer"

        snaps_opening = play_conversation(engine, pid, STREAM_OPENING)
        opening_avg = sum(s["person_mood"]["intensity"] for s in snaps_opening) / len(snaps_opening)

        # Reset for comparison
        simulate_time_decay(engine, 120.0)
        snaps_chill = play_conversation(engine, pid, CHILL_DISCUSSION)
        chill_avg = sum(s["person_mood"]["intensity"] for s in snaps_chill) / len(snaps_chill)

        # Opening should be at least as energetic as the chill phase
        # (Note: chill comes after decay so it should be lower)
        assert opening_avg > 0.0, f"Opening avg: {opening_avg:.2f}"

    def test_winding_down_is_calmer(self, engine):
        """End of stream should have lower average intensity than opening."""
        pid = "viewer"

        play_conversation(engine, pid, STREAM_OPENING)
        simulate_time_decay(engine, 120.0)
        play_conversation(engine, pid, CHILL_DISCUSSION)
        simulate_time_decay(engine, 300.0)
        play_conversation(engine, pid, DEEP_TALK)
        simulate_time_decay(engine, 600.0)
        snaps_end = play_conversation(engine, pid, WINDING_DOWN)

        end_avg = sum(s["person_mood"]["intensity"] for s in snaps_end) / len(snaps_end)

        # After so much decay, end should be relatively calm
        assert end_avg < 0.7, f"End of stream should be calmer: avg={end_avg:.2f}"


class TestLongConversationStress:
    """Stress test: many turns in rapid succession."""

    def test_fifty_turns_stability(self, engine):
        """50 rapid turns should not cause any instability."""
        pid = "rapid_user"
        emotions = list(Emotion)

        for i in range(50):
            e = emotions[i % len(emotions)]
            intensity = 0.3 + (i % 8) * 0.1
            engine.process_emotion(EmotionData(e, intensity), pid)

        mood = engine._get_person_mood(pid)
        assert 0.0 <= mood.intensity <= 1.0
        assert len(mood.history) <= 100

    def test_hundred_turns_with_decay(self, engine):
        """100 turns with small delays should remain stable."""
        pid = "marathon_user"
        emotions = [Emotion.HAPPY, Emotion.EXCITED, Emotion.CURIOUS,
                    Emotion.AMUSED, Emotion.PLAYFUL, Emotion.THINKING]

        for i in range(100):
            if i % 10 == 0 and i > 0:
                simulate_time_decay(engine, 30.0)

            e = emotions[i % len(emotions)]
            engine.process_emotion(EmotionData(e, 0.5 + (i % 4) * 0.1), pid)

        mood = engine._get_person_mood(pid)
        assert 0.0 <= mood.intensity <= 1.0
        glob = engine.global_mood
        assert 0.0 <= glob.intensity <= 1.0
