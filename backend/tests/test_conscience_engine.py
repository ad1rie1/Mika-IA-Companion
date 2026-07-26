"""Tests for ConscienceEngine — feed_emotion, pick_relevant_modules, observe, compute_score."""

import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

from conscience.types import DecisionContext


def _make_engine():
    from conscience.engine import ConscienceEngine
    e = ConscienceEngine.__new__(ConscienceEngine)
    e._last_activity = time.time()
    e._last_action_time = 0.0
    e._greeted_periods = set()
    e._greeted_date = None
    e._threshold = 0.5
    e._consecutive_waits = 0
    e.interpreter = MagicMock()
    e.memory = MagicMock()
    return e


def _make_ctx(sources=None, has_scheduled=False, high_pertinence=False):
    obs = []
    for src in (sources or []):
        o = MagicMock()
        o.source = src
        o.pertinence = 0.7 if high_pertinence else 0.3
        obs.append(o)
    return DecisionContext(
        pending_observations=obs,
        global_mood="happy",
        global_intensity=0.5,
        idle_seconds=60,
        in_cooldown=False,
        max_pertinence=0.7 if high_pertinence else 0.3,
        weighted_urgency=0.5,
        scheduled_actions=[MagicMock()] if has_scheduled else [],
        consecutive_waits=0,
        acts_today=0,
        consecutive_ignored_acts=0,
    )


# ===================================================================
# _feed_emotion
# ===================================================================

class TestFeedEmotion:

    def test_valid_emotion_processed(self):
        from conscience.engine import ConscienceEngine
        from conscience.types import InterpretedSignal
        from emotion.types import Emotion

        signal = InterpretedSignal(
            summary="test", category="communication", pertinence=0.7,
            emotional_reaction="happy", emotional_intensity=0.8,
            themes=[], entities=[], should_remember=False,
        )
        mock_ee = MagicMock()
        with patch("conscience.engine.emotion_engine", mock_ee):
            ConscienceEngine._feed_emotion(signal)

        mock_ee.process_emotion.assert_called_once()
        ed, pid = mock_ee.process_emotion.call_args[0]
        assert ed.emotion == Emotion.HAPPY
        assert ed.intensity == pytest.approx(0.8)
        assert pid == "conscience_mika"

    def test_invalid_emotion_name_ignored(self):
        from conscience.engine import ConscienceEngine
        from conscience.types import InterpretedSignal

        signal = InterpretedSignal(
            summary="test", category="system", pertinence=0.5,
            emotional_reaction="unicorn_emotion", emotional_intensity=0.5,
            themes=[], entities=[], should_remember=False,
        )
        mock_ee = MagicMock()
        with patch("conscience.engine.emotion_engine", mock_ee):
            ConscienceEngine._feed_emotion(signal)  # should not raise

        mock_ee.process_emotion.assert_not_called()


# ===================================================================
# _pick_relevant_modules
# ===================================================================

class TestPickRelevantModules:

    def test_sources_included(self):
        e = _make_engine()
        ctx = _make_ctx(sources=["email", "telegram"])
        result = e._pick_relevant_modules(ctx)
        assert "email" in result
        assert "telegram" in result

    def test_wake_added_for_scheduled(self):
        e = _make_engine()
        ctx = _make_ctx(sources=["email"], has_scheduled=True)
        assert "wake" in e._pick_relevant_modules(ctx)

    def test_wake_added_for_high_pertinence(self):
        e = _make_engine()
        ctx = _make_ctx(sources=["email"], high_pertinence=True)
        assert "wake" in e._pick_relevant_modules(ctx)

    def test_wake_not_duplicated(self):
        e = _make_engine()
        ctx = _make_ctx(sources=["wake"], has_scheduled=True)
        result = e._pick_relevant_modules(ctx)
        assert result.count("wake") == 1

    def test_no_obs_returns_empty(self):
        e = _make_engine()
        assert e._pick_relevant_modules(_make_ctx()) == []


# ===================================================================
# get_idle_seconds
# ===================================================================

class TestGetIdleSeconds:

    def test_returns_time_since_last_activity(self):
        e = _make_engine()
        e._last_activity = time.time() - 120
        idle = e.get_idle_seconds()
        assert 115 < idle < 125


# ===================================================================
# observe — activity tracking
# ===================================================================

class TestObserve:

    @pytest.mark.asyncio
    async def test_chat_message_updates_last_activity(self):
        from modules.types import ModuleEvent
        e = _make_engine()
        e._last_activity = time.time() - 3600

        signal = MagicMock()
        signal.emotional_reaction = ""
        signal.emotional_intensity = 0.0
        signal.should_remember = False
        signal.pertinence = 0.3
        e.interpreter.interpret = AsyncMock(return_value=signal)
        e._store_observation = AsyncMock(return_value=None)

        await e.observe(ModuleEvent(event_type="chat.message", source_module="frontend", data={}))
        assert time.time() - e._last_activity < 5

    @pytest.mark.asyncio
    async def test_non_chat_does_not_update_activity(self):
        from modules.types import ModuleEvent
        e = _make_engine()
        past = time.time() - 3600
        e._last_activity = past

        signal = MagicMock()
        signal.emotional_reaction = ""
        signal.emotional_intensity = 0.0
        signal.should_remember = False
        signal.pertinence = 0.3
        e.interpreter.interpret = AsyncMock(return_value=signal)
        e._store_observation = AsyncMock(return_value=None)

        await e.observe(ModuleEvent(event_type="email.received", source_module="email", data={}))
        assert e._last_activity == past


# ===================================================================
# _compute_score
# ===================================================================

class TestComputeScore:

    def test_delegates_to_scoring_module(self):
        e = _make_engine()
        ctx = _make_ctx()
        with patch("conscience.engine.compute_decision_score", return_value=(0.3, "idle", set(), None)) as mock_score:
            score, reason = e._compute_score(ctx)
        mock_score.assert_called_once()
        assert score == pytest.approx(0.3)
        assert reason == "idle"

    def test_greeting_not_committed_when_deciding_to_wait(self):
        # Scoring marks the period greeted, but a "wait" decision must not
        # spend it — otherwise the day's greeting is consumed silently.
        e = _make_engine()
        ctx = _make_ctx()
        with patch("conscience.engine.compute_decision_score",
                   return_value=(0.35, "time(morning)", {"morning"}, "2026-07-26")):
            e._compute_score(ctx)
        assert e._greeted_periods == set()
        assert e._greeted_date is None

    def test_greeting_committed_on_act(self):
        e = _make_engine()
        ctx = _make_ctx()
        with patch("conscience.engine.compute_decision_score",
                   return_value=(0.8, "time(morning)", {"morning"}, "2026-07-26")):
            e._compute_score(ctx)
        e._commit_greeting()
        assert e._greeted_periods == {"morning"}
        assert e._greeted_date == "2026-07-26"

    def test_commit_is_idempotent(self):
        e = _make_engine()
        ctx = _make_ctx()
        with patch("conscience.engine.compute_decision_score",
                   return_value=(0.8, "time(morning)", {"morning"}, "2026-07-26")):
            e._compute_score(ctx)
        e._commit_greeting()
        e._greeted_periods = {"morning", "evening"}
        e._commit_greeting()  # nothing pending → must not roll back
        assert e._greeted_periods == {"morning", "evening"}
