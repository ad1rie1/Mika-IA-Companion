"""
Tests for the Conscience decision scoring system.

The scoring function is pure (no DB, no async) so we can
test it directly with synthetic DecisionContext values.

Tests various decision scenarios:
- Cooldown suppression
- High pertinence triggering action
- Accumulated urgency
- Mood overflow
- Idle time
- Scheduled actions
- Accumulation pressure
- Self-regulation (ignored acts penalty)
- Hard cap suppression
"""

import pytest
from datetime import datetime, date

from conscience.types import DecisionContext
from conscience.scoring import (
    compute_decision_score,
    check_time_trigger,
    urgency_from_context,
)


# ---------------------------------------------------------------------------
# Helper to build DecisionContext quickly
# ---------------------------------------------------------------------------

def make_context(
    max_pertinence=0.0,
    weighted_urgency=0.0,
    global_mood="happy",
    global_intensity=0.0,
    idle_seconds=0.0,
    in_cooldown=False,
    scheduled_actions=None,
    consecutive_waits=0,
    acts_today=0,
    consecutive_ignored_acts=0,
    pending_observations=None,
) -> DecisionContext:
    return DecisionContext(
        pending_observations=pending_observations or [],
        global_mood=global_mood,
        global_intensity=global_intensity,
        idle_seconds=idle_seconds,
        in_cooldown=in_cooldown,
        max_pertinence=max_pertinence,
        weighted_urgency=weighted_urgency,
        scheduled_actions=scheduled_actions or [],
        consecutive_waits=consecutive_waits,
        acts_today=acts_today,
        consecutive_ignored_acts=consecutive_ignored_acts,
    )


class FakeScheduledAction:
    """Minimal mock for ScheduledAction with just priority."""
    def __init__(self, priority: float = 0.5):
        self.priority = priority


# All greeting periods pre-marked to isolate scoring tests from wall-clock:
# otherwise tests run between 7-10h / 18-20h / 23-24h would get a +0.35
# nudge from `check_time_trigger` that shifts all score assertions.
_ALL_GREETED = frozenset({"morning", "evening", "night"})


def _score(ctx, threshold: float = 0.5):
    """Wrap compute_decision_score with time-of-day isolation."""
    greeted = set(_ALL_GREETED)
    today = date.today()
    return compute_decision_score(ctx, threshold, greeted, today)


# ===================================================================
# COOLDOWN
# ===================================================================

class TestCooldown:

    def test_cooldown_returns_zero(self):
        """When in cooldown, score should always be 0."""
        ctx = make_context(
            max_pertinence=0.95,
            weighted_urgency=0.9,
            global_intensity=0.9,
            idle_seconds=3600,
            in_cooldown=True,
        )
        score, reason, _, _ = _score(ctx)

        assert score == 0.0
        assert reason == "cooldown"

    def test_not_in_cooldown_allows_scoring(self):
        ctx = make_context(max_pertinence=0.8, in_cooldown=False)
        score, reason, _, _ = _score(ctx)

        assert score > 0.0
        assert "cooldown" not in reason


# ===================================================================
# PERTINENCE
# ===================================================================

class TestPertinence:

    def test_high_pertinence_contributes_to_score(self):
        """max_pertinence > 0.7 should add pertinence * 0.4 to score."""
        ctx = make_context(max_pertinence=0.9)
        score, reason, _, _ = _score(ctx)

        expected_contribution = 0.9 * 0.4  # 0.36
        assert score >= expected_contribution - 0.01
        assert "pertinence" in reason

    def test_low_pertinence_no_contribution(self):
        """max_pertinence <= 0.7 should not contribute."""
        ctx = make_context(max_pertinence=0.5)
        score, reason, _, _ = _score(ctx)

        assert "pertinence" not in reason

    def test_pertinence_exactly_at_threshold(self):
        """max_pertinence == 0.7 should not trigger (>0.7 required)."""
        ctx = make_context(max_pertinence=0.7)
        score, reason, _, _ = _score(ctx)

        assert "pertinence" not in reason


# ===================================================================
# ACCUMULATED URGENCY
# ===================================================================

class TestAccumulatedUrgency:

    def test_high_urgency_contributes(self):
        ctx = make_context(weighted_urgency=0.8)
        score, reason, _, _ = _score(ctx)

        assert "accumulated" in reason
        assert score > 0.0

    def test_urgency_capped_at_0_3(self):
        """Urgency contribution should never exceed 0.3."""
        ctx = make_context(weighted_urgency=10.0)  # absurdly high
        score, reason, _, _ = _score(ctx)

        # Without other factors, score should be at most 0.3 from urgency
        assert score <= 0.31  # tiny float tolerance

    def test_low_urgency_no_contribution(self):
        ctx = make_context(weighted_urgency=0.3)
        score, reason, _, _ = _score(ctx)

        assert "accumulated" not in reason


# ===================================================================
# MOOD OVERFLOW
# ===================================================================

class TestMoodOverflow:

    def test_high_mood_intensity_triggers(self):
        """Global intensity > 0.7 should add 0.25."""
        ctx = make_context(global_mood="angry", global_intensity=0.85)
        score, reason, _, _ = _score(ctx)

        assert "mood" in reason
        assert score >= 0.25

    def test_normal_mood_no_trigger(self):
        ctx = make_context(global_mood="happy", global_intensity=0.5)
        score, reason, _, _ = _score(ctx)

        assert "mood" not in reason


# ===================================================================
# IDLE TIME
# ===================================================================

class TestIdleTime:

    def test_long_idle_contributes(self):
        """Idle > 10 minutes should contribute to score."""
        ctx = make_context(idle_seconds=1200)  # 20 minutes
        score, reason, _, _ = _score(ctx)

        assert "idle" in reason
        assert score > 0.0

    def test_short_idle_no_contribution(self):
        """Idle < 10 minutes should not contribute."""
        ctx = make_context(idle_seconds=300)  # 5 minutes
        score, reason, _, _ = _score(ctx)

        assert "idle" not in reason

    def test_idle_capped_at_0_3(self):
        """Idle contribution should cap at 0.3."""
        ctx = make_context(idle_seconds=7200)  # 2 hours
        score, reason, _, _ = _score(ctx)

        # Just idle should give max 0.3
        assert score <= 0.31


# ===================================================================
# SCHEDULED ACTIONS
# ===================================================================

class TestScheduledActions:

    def test_scheduled_action_contributes(self):
        """Due scheduled actions should contribute priority * 0.5."""
        actions = [FakeScheduledAction(priority=0.8)]
        ctx = make_context(scheduled_actions=actions)
        score, reason, _, _ = _score(ctx)

        assert "scheduled" in reason
        assert score >= 0.4 - 0.01  # 0.8 * 0.5

    def test_multiple_scheduled_uses_max_priority(self):
        """Multiple actions should use the highest priority."""
        actions = [
            FakeScheduledAction(priority=0.3),
            FakeScheduledAction(priority=0.9),
            FakeScheduledAction(priority=0.5),
        ]
        ctx = make_context(scheduled_actions=actions)
        score, reason, _, _ = _score(ctx)

        assert score >= 0.45 - 0.01  # 0.9 * 0.5


# ===================================================================
# ACCUMULATION PRESSURE
# ===================================================================

class TestAccumulationPressure:

    def test_pressure_builds_after_3_waits(self):
        """Consecutive waits >= 3 with pending obs should add pressure."""
        ctx = make_context(
            consecutive_waits=5,
            pending_observations=["obs1", "obs2"],
        )
        score, reason, _, _ = _score(ctx)

        assert "pressure" in reason

    def test_no_pressure_without_pending_observations(self):
        """Pressure should not apply without pending observations."""
        ctx = make_context(consecutive_waits=10, pending_observations=[])
        score, reason, _, _ = _score(ctx)

        assert "pressure" not in reason

    def test_no_pressure_under_3_waits(self):
        ctx = make_context(
            consecutive_waits=2,
            pending_observations=["obs"],
        )
        score, reason, _, _ = _score(ctx)

        assert "pressure" not in reason


# ===================================================================
# SELF-REGULATION (ignored acts penalty)
# ===================================================================

class TestSelfRegulation:

    def test_ignored_acts_reduce_score(self):
        """Consecutive ignored acts should reduce score."""
        ctx_no_ignore = make_context(max_pertinence=0.8)
        score_normal, _, _, _ = compute_decision_score(ctx_no_ignore, 0.5, set(), None)

        ctx_ignored = make_context(max_pertinence=0.8, consecutive_ignored_acts=3)
        score_penalized, reason, _, _ = compute_decision_score(ctx_ignored, 0.5, set(), None)

        assert score_penalized < score_normal, "Ignored acts should reduce score"
        assert "ignored" in reason

    def test_hard_cap_suppresses_when_too_many_ignored(self):
        """5+ acts today + 3+ ignored should hard-cap score at 0.1."""
        ctx = make_context(
            max_pertinence=0.95,
            weighted_urgency=0.9,
            global_intensity=0.9,
            idle_seconds=3600,
            acts_today=5,
            consecutive_ignored_acts=3,
        )
        score, reason, _, _ = _score(ctx)

        assert score <= 0.1, f"Hard cap should suppress to <=0.1, got {score}"
        assert "suppressed" in reason


# ===================================================================
# COMBINED SCENARIOS
# ===================================================================

class TestCombinedScenarios:

    def test_all_factors_high_exceeds_threshold(self):
        """When all factors are high, score should exceed threshold."""
        actions = [FakeScheduledAction(priority=0.8)]
        ctx = make_context(
            max_pertinence=0.9,
            weighted_urgency=0.8,
            global_intensity=0.8,
            idle_seconds=1800,
            scheduled_actions=actions,
            consecutive_waits=5,
            pending_observations=["obs1"],
        )
        score, reason, _, _ = _score(ctx)

        assert score > 0.5, f"All factors high should exceed threshold: {score}"

    def test_minimal_signal_stays_below_threshold(self):
        """With minimal signals, score should stay below threshold."""
        ctx = make_context(
            max_pertinence=0.3,
            weighted_urgency=0.2,
            global_intensity=0.3,
            idle_seconds=60,
        )
        score, reason, _, _ = _score(ctx)

        assert score < 0.5, f"Minimal signals should not trigger: {score}"

    def test_only_pertinence_can_trigger_alone(self):
        """Very high pertinence alone should nearly trigger."""
        ctx = make_context(max_pertinence=0.95)
        score, _, _, _ = _score(ctx)

        # 0.95 * 0.4 = 0.38 — close but not enough alone
        assert 0.3 < score < 0.5


# ===================================================================
# TIME TRIGGERS
# ===================================================================

class TestTimeTrigger:

    def test_morning_trigger(self):
        """Morning trigger should fire between 7-10."""
        # This depends on current time — we test the function directly
        trigger, periods, gdate = check_time_trigger(set(), None)

        now = datetime.now()
        if 7 <= now.hour < 10:
            assert trigger == "morning"
            assert "morning" in periods
        # Otherwise trigger depends on actual time

    def test_no_double_greeting(self):
        """Same period should not trigger twice."""
        today = date.today()
        already_greeted = {"morning", "evening"}

        trigger, periods, gdate = check_time_trigger(already_greeted, today)

        now = datetime.now()
        if 7 <= now.hour < 10:
            assert trigger is None, "Morning already greeted"
        if 18 <= now.hour < 20:
            assert trigger is None, "Evening already greeted"

    def test_new_day_resets_greetings(self):
        """A new day should clear the greeted periods set."""
        import datetime as dt
        yesterday = dt.date(2025, 1, 1)
        greeted = {"morning", "evening", "night"}

        trigger, periods, gdate = check_time_trigger(greeted, yesterday)

        # Greeted set should be reset (it's a new day)
        # Whether trigger fires depends on current time
        assert gdate == date.today()


# ===================================================================
# URGENCY CLASSIFICATION
# ===================================================================

class TestUrgencyClassification:

    def test_high_urgency(self):
        ctx = make_context(max_pertinence=0.95)
        assert urgency_from_context(ctx) == "high"

    def test_normal_urgency(self):
        ctx = make_context(max_pertinence=0.8)
        assert urgency_from_context(ctx) == "normal"

    def test_low_urgency(self):
        ctx = make_context(max_pertinence=0.5)
        assert urgency_from_context(ctx) == "low"
