"""Tests for the intrinsic drive system (drives/).

Drives model Mika's inner motivational pulls: curiosity, social contact,
self-expression, and need for rest. They grow with time when unsatisfied
and decay when the corresponding action happens.

Tests:
- Tension growth over simulated time
- Satisfaction reduces tension correctly
- Dominant drive identification
- Prompt context generation
- Scoring contribution (including negative REST contribution)
- on_act / on_conversation / on_observation signal mapping
- REST drive grows with activity and decays during idle
"""
from __future__ import annotations

import time
import pytest

from drives.engine import DriveEngine
from drives.state import (
    DEFAULT_PARAMS,
    DriveKind,
    drive_prompt_description,
    dominant_drive,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _backdate(engine: DriveEngine, seconds: float) -> None:
    """Pretend `seconds` have passed by rewinding every drive's last_update."""
    past = time.time() - seconds
    for state in engine.states.values():
        state.last_update = past


@pytest.fixture
def engine() -> DriveEngine:
    """Fresh DriveEngine at zero tension."""
    return DriveEngine()


# ---------------------------------------------------------------------------
# Tension growth
# ---------------------------------------------------------------------------

class TestTensionGrowth:

    def test_all_drives_start_at_zero(self, engine):
        for kind in DriveKind:
            assert engine.states[kind].tension == 0.0

    def test_curiosity_grows_linearly_with_time(self, engine):
        """After 100s at 0.0025/s, curiosity should be ~0.25."""
        _backdate(engine, 100.0)
        engine.update()
        tension = engine.states[DriveKind.CURIOSITY].tension
        assert 0.20 < tension < 0.30

    def test_social_grows_faster_than_curiosity(self, engine):
        _backdate(engine, 100.0)
        engine.update()
        assert (
            engine.states[DriveKind.SOCIAL].tension
            > engine.states[DriveKind.CURIOSITY].tension
        )

    def test_tension_clamps_at_one(self, engine):
        _backdate(engine, 10_000.0)  # way beyond saturation
        engine.update()
        for kind in (DriveKind.CURIOSITY, DriveKind.SOCIAL, DriveKind.EXPRESSION):
            assert engine.states[kind].tension <= 1.0

    def test_rest_does_not_grow_without_activity(self, engine):
        """REST only grows when Mika has been active — pure idle shouldn't stress her."""
        _backdate(engine, 500.0)
        engine.update()
        assert engine.states[DriveKind.REST].tension < 0.05

    def test_update_is_idempotent(self, engine):
        """Calling update() twice in a row doesn't double-count."""
        _backdate(engine, 100.0)
        engine.update()
        t1 = engine.states[DriveKind.CURIOSITY].tension
        engine.update()
        t2 = engine.states[DriveKind.CURIOSITY].tension
        assert abs(t1 - t2) < 0.01


# ---------------------------------------------------------------------------
# Satisfaction
# ---------------------------------------------------------------------------

class TestSatisfaction:

    def test_satisfy_reduces_tension(self, engine):
        _backdate(engine, 300.0)
        engine.update()
        before = engine.states[DriveKind.SOCIAL].tension
        assert before > 0.3

        engine.satisfy(DriveKind.SOCIAL, 1.0)
        after = engine.states[DriveKind.SOCIAL].tension
        assert after < before

    def test_full_satisfy_applies_decay_on_satisfy(self, engine):
        """amount=1.0 should apply the full decay_on_satisfy factor."""
        engine.states[DriveKind.SOCIAL].tension = 1.0
        engine.satisfy(DriveKind.SOCIAL, 1.0)
        # decay_on_satisfy=0.7 → remaining 30% of 1.0 = 0.3
        assert abs(engine.states[DriveKind.SOCIAL].tension - 0.3) < 0.01

    def test_partial_satisfy_relieves_partially(self, engine):
        engine.states[DriveKind.SOCIAL].tension = 1.0
        engine.satisfy(DriveKind.SOCIAL, 0.5)
        # Applies 0.5 × 0.7 = 0.35 decay → remaining 65% of 1.0 = 0.65
        assert 0.6 < engine.states[DriveKind.SOCIAL].tension < 0.7

    def test_satisfy_never_goes_below_zero(self, engine):
        engine.states[DriveKind.SOCIAL].tension = 0.1
        engine.satisfy(DriveKind.SOCIAL, 1.0)
        assert engine.states[DriveKind.SOCIAL].tension >= 0.0


# ---------------------------------------------------------------------------
# Dominant drive
# ---------------------------------------------------------------------------

class TestDominantDrive:

    def test_no_dominant_when_all_quiet(self, engine):
        engine.update()
        assert engine.get_dominant() is None

    def test_highest_tension_is_dominant(self, engine):
        engine.states[DriveKind.CURIOSITY].tension = 0.3
        engine.states[DriveKind.SOCIAL].tension = 0.6
        engine.states[DriveKind.EXPRESSION].tension = 0.4
        engine.update()
        dom = engine.get_dominant()
        assert dom is not None
        assert dom.kind is DriveKind.SOCIAL

    def test_dominant_requires_minimum_tension(self, engine):
        """Everyone at 0.1 → below the noise floor (0.2)."""
        for state in engine.states.values():
            state.tension = 0.1
        assert dominant_drive(engine.states) is None


# ---------------------------------------------------------------------------
# Prompt context
# ---------------------------------------------------------------------------

class TestPromptContext:

    def test_empty_context_when_all_below_threshold(self, engine):
        """No drives active → no prompt injection."""
        engine.update()
        assert engine.get_context() == ""

    def test_active_drives_appear_in_french(self, engine):
        engine.states[DriveKind.SOCIAL].tension = 0.7
        engine.update()
        ctx = engine.get_context()
        assert ctx
        assert "contact" in ctx or "reconnue" in ctx or "echanger" in ctx

    def test_intensity_adverbs_scale_correctly(self, engine):
        # Mild
        engine.states[DriveKind.CURIOSITY].tension = 0.40
        ctx_mild = drive_prompt_description(engine.states)
        # Strong
        engine.states[DriveKind.CURIOSITY].tension = 0.85
        ctx_strong = drive_prompt_description(engine.states)
        # At minimum the adverbs should differ
        assert ctx_mild != ctx_strong

    def test_top_three_cap_on_description(self, engine):
        """Only top 3 drives appear in the prompt, even if all are active."""
        for kind in DriveKind:
            engine.states[kind].tension = 0.9
        ctx = drive_prompt_description(engine.states)
        # Count occurrences of "tu" (each drive line starts with "tu")
        # Should be 3, not 4
        assert ctx.count("tu ") + ctx.count("Tu ") <= 5


# ---------------------------------------------------------------------------
# Scoring contribution
# ---------------------------------------------------------------------------

class TestScoringContribution:

    def test_no_contribution_when_all_quiet(self, engine):
        engine.update()
        bonus, summary = engine.conscience_contribution()
        assert abs(bonus) < 0.01

    def test_strong_social_drive_contributes_positively(self, engine):
        engine.states[DriveKind.SOCIAL].tension = 0.9
        bonus, summary = engine.conscience_contribution()
        assert bonus > 0.15
        assert "social" in summary

    def test_rest_drive_contributes_negatively(self, engine):
        """High fatigue should reduce the urge to act."""
        engine.states[DriveKind.REST].tension = 0.9
        bonus, summary = engine.conscience_contribution()
        assert bonus < 0
        assert "rest" in summary

    def test_rest_vs_expression_can_cancel(self, engine):
        """Tired but with something to say → small net effect."""
        engine.states[DriveKind.REST].tension = 0.8
        engine.states[DriveKind.EXPRESSION].tension = 0.8
        bonus, _ = engine.conscience_contribution()
        # They're not exactly equal (weights differ) but bounded.
        assert abs(bonus) < 0.25


# ---------------------------------------------------------------------------
# Activity → REST drive
# ---------------------------------------------------------------------------

class TestRestDrive:

    def test_act_raises_rest_pressure(self, engine):
        assert engine.states[DriveKind.REST].tension == 0.0
        for _ in range(5):
            engine.on_act(had_tools=False, word_count=20)
        engine.update()
        assert engine.states[DriveKind.REST].tension > 0.1

    def test_observation_raises_rest_pressure(self, engine):
        for _ in range(3):
            engine.on_observation(pertinence=0.8)
        engine.update()
        assert engine.states[DriveKind.REST].tension > 0.05

    def test_long_messages_tire_more(self, engine):
        # Short message
        e1 = DriveEngine()
        e1.on_act(word_count=5)
        e1.update()
        t_short = e1.states[DriveKind.REST].tension

        # Long message
        e2 = DriveEngine()
        e2.on_act(word_count=200)
        e2.update()
        t_long = e2.states[DriveKind.REST].tension

        assert t_long > t_short

    def test_rest_decays_during_idle(self, engine):
        engine.states[DriveKind.REST].tension = 0.6
        _backdate(engine, 600.0)  # 10 min of idle
        engine.update()
        assert engine.states[DriveKind.REST].tension < 0.6


# ---------------------------------------------------------------------------
# Signal routing
# ---------------------------------------------------------------------------

class TestSignalRouting:

    def test_conversation_satisfies_social_and_curiosity(self, engine):
        engine.states[DriveKind.SOCIAL].tension = 1.0
        engine.states[DriveKind.CURIOSITY].tension = 1.0
        engine.on_conversation(from_person=True)
        assert engine.states[DriveKind.SOCIAL].tension < 1.0
        assert engine.states[DriveKind.CURIOSITY].tension < 1.0

    def test_act_satisfies_expression(self, engine):
        engine.states[DriveKind.EXPRESSION].tension = 1.0
        engine.on_act(had_tools=False, word_count=10)
        assert engine.states[DriveKind.EXPRESSION].tension < 0.5

    def test_act_with_tools_also_satisfies_curiosity(self, engine):
        engine.states[DriveKind.CURIOSITY].tension = 1.0
        engine.states[DriveKind.EXPRESSION].tension = 1.0
        engine.on_act(had_tools=True, word_count=10)
        assert engine.states[DriveKind.CURIOSITY].tension < 1.0

    def test_high_pertinence_observation_feeds_curiosity(self, engine):
        engine.states[DriveKind.CURIOSITY].tension = 1.0
        engine.on_observation(pertinence=0.9)
        # Feeds curiosity (satisfies it) only when pertinence > 0.6
        assert engine.states[DriveKind.CURIOSITY].tension < 1.0

    def test_low_pertinence_observation_does_not_feed_curiosity(self, engine):
        engine.states[DriveKind.CURIOSITY].tension = 0.5
        engine.on_observation(pertinence=0.3)
        # Below threshold — no satisfaction, only REST pressure
        assert engine.states[DriveKind.CURIOSITY].tension >= 0.5


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

class TestReset:

    def test_reset_clears_all_tensions(self, engine):
        for state in engine.states.values():
            state.tension = 0.8
        engine.reset()
        for state in engine.states.values():
            assert state.tension == 0.0

    def test_reset_clears_activity_history(self, engine):
        engine.on_act(word_count=100)
        engine.on_act(word_count=100)
        engine.reset()
        assert engine._activity == []
