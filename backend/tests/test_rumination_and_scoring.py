"""Tests for rumination + scoring additions (drives, rumination factors).

The new scoring factors added to compute_decision_score:
  - Factor 9: drive_bonus (signed, from drive_engine.conscience_contribution)
  - Factor 10: rumination_pressure (sum of active rumination intensities)

Rumination is Mika's short-term persistent thought buffer — observations
that were pertinent but went unheard get promoted to ruminations, which
decay slowly, bleed emotional color into the global mood, and can push
the conscience to eventually speak up about them.

Note: scoring tests are pure (no DB) — DB-level rumination creation is
tested separately via pytest.mark.django_db.
"""
from __future__ import annotations

import pytest

from conscience.types import DecisionContext
from conscience.scoring import compute_decision_score


# ---------------------------------------------------------------------------
# Helpers
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
    drive_bonus=0.0,
    drive_summary="",
    rumination_pressure=0.0,
    rumination_count=0,
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
        drive_bonus=drive_bonus,
        drive_summary=drive_summary,
        rumination_pressure=rumination_pressure,
        rumination_count=rumination_count,
    )


# ---------------------------------------------------------------------------
# Drive scoring factor
# ---------------------------------------------------------------------------

class TestDriveScoring:

    def test_zero_drives_no_effect(self):
        ctx = make_context(drive_bonus=0.0)
        score, reason, _, _ = compute_decision_score(ctx, 0.5, set(), None)
        assert "drives" not in reason

    def test_small_drives_ignored_below_noise(self):
        """Tiny drive bonus (< 0.02) doesn't appear in the reason."""
        ctx = make_context(drive_bonus=0.01)
        score, reason, _, _ = compute_decision_score(ctx, 0.5, set(), None)
        assert "drives" not in reason

    def test_strong_positive_drives_increase_score(self):
        base = make_context()
        with_drives = make_context(drive_bonus=0.3, drive_summary="social:0.9")
        s1, _, _, _ = compute_decision_score(base, 0.5, set(), None)
        s2, r2, _, _ = compute_decision_score(with_drives, 0.5, set(), None)
        assert s2 > s1
        assert "drives" in r2
        assert "social" in r2

    def test_rest_drive_decreases_score(self):
        ctx = make_context(
            max_pertinence=0.8,
            drive_bonus=-0.3,
            drive_summary="rest:0.9",
        )
        ctx_alert = make_context(max_pertinence=0.8)
        s_tired, _, _, _ = compute_decision_score(ctx, 0.5, set(), None)
        s_fresh, _, _, _ = compute_decision_score(ctx_alert, 0.5, set(), None)
        assert s_tired < s_fresh

    def test_drive_contribution_clamped_positive(self):
        """Even absurd drive_bonus is capped at +0.5."""
        ctx = make_context(drive_bonus=10.0)
        score, _, _, _ = compute_decision_score(ctx, 0.5, set(), None)
        assert score <= 0.5 + 0.01  # small float margin

    def test_drive_contribution_clamped_negative(self):
        """Even absurd negative drive_bonus is floored at -0.4."""
        ctx = make_context(drive_bonus=-10.0)
        score, _, _, _ = compute_decision_score(ctx, 0.5, set(), None)
        assert score >= -0.4 - 0.01

    def test_cooldown_ignores_drives(self):
        ctx = make_context(drive_bonus=0.5, in_cooldown=True)
        score, reason, _, _ = compute_decision_score(ctx, 0.5, set(), None)
        assert score == 0.0
        assert reason == "cooldown"


# ---------------------------------------------------------------------------
# Rumination scoring factor
# ---------------------------------------------------------------------------

class TestRuminationScoring:

    def test_no_rumination_no_contribution(self):
        ctx = make_context(rumination_pressure=0.0)
        _, reason, _, _ = compute_decision_score(ctx, 0.5, set(), None)
        assert "rumination" not in reason

    def test_low_pressure_below_threshold_ignored(self):
        ctx = make_context(rumination_pressure=0.1)
        _, reason, _, _ = compute_decision_score(ctx, 0.5, set(), None)
        assert "rumination" not in reason

    def test_moderate_rumination_adds_to_score(self):
        base = make_context()
        with_rum = make_context(rumination_pressure=0.5, rumination_count=2)
        s1, _, _, _ = compute_decision_score(base, 0.5, set(), None)
        s2, r2, _, _ = compute_decision_score(with_rum, 0.5, set(), None)
        assert s2 > s1
        assert "rumination" in r2

    def test_rumination_score_capped_at_03(self):
        """Even very high rumination pressure is capped at +0.3."""
        ctx = make_context(rumination_pressure=1.0, rumination_count=10)
        score, _, _, _ = compute_decision_score(ctx, 0.5, set(), None)
        # 0.3 cap is the rumination contribution
        assert score <= 0.3 + 0.01

    def test_rumination_reason_includes_count(self):
        ctx = make_context(rumination_pressure=0.5, rumination_count=3)
        _, reason, _, _ = compute_decision_score(ctx, 0.5, set(), None)
        assert "3" in reason

    def test_rumination_alone_cannot_force_action(self):
        """The threshold is 0.5; rumination max contribution is 0.3."""
        ctx = make_context(rumination_pressure=1.0, rumination_count=10)
        score, _, _, _ = compute_decision_score(ctx, 0.5, set(), None)
        assert score < 0.5


# ---------------------------------------------------------------------------
# Combined factors
# ---------------------------------------------------------------------------

class TestCombined:

    def test_drives_plus_rumination_push_over_threshold(self):
        """Together, strong drives + lingering ruminations can act."""
        ctx = make_context(
            drive_bonus=0.35,
            drive_summary="social:0.9,expression:0.8",
            rumination_pressure=0.5,
            rumination_count=2,
            pending_observations=[],  # no immediate signals
        )
        score, reason, _, _ = compute_decision_score(ctx, 0.5, set(), None)
        assert score >= 0.5
        assert "drives" in reason
        assert "rumination" in reason

    def test_rest_cancels_rumination(self):
        """Tired Mika is less likely to act on ruminations."""
        tired = make_context(
            drive_bonus=-0.3,
            drive_summary="rest:0.9",
            rumination_pressure=0.5,
            rumination_count=2,
        )
        fresh = make_context(
            drive_bonus=0.0,
            rumination_pressure=0.5,
            rumination_count=2,
        )
        s_tired, _, _, _ = compute_decision_score(tired, 0.5, set(), None)
        s_fresh, _, _, _ = compute_decision_score(fresh, 0.5, set(), None)
        assert s_tired < s_fresh


# ---------------------------------------------------------------------------
# DB-level: Rumination model CRUD
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestRuminationModel:

    def test_create_rumination(self):
        from conscience.models import Rumination
        r = Rumination.objects.create(
            summary="User seemed upset about the deadline",
            intensity=0.7,
            emotion="sad",
            themes=["work", "stress"],
        )
        assert r.id is not None
        assert r.status == "active"
        assert r.intensity == 0.7

    def test_rumination_status_transitions(self):
        from conscience.models import Rumination
        r = Rumination.objects.create(summary="test", intensity=0.5)
        r.status = "resolved"
        r.save()
        assert Rumination.objects.filter(status="resolved").count() == 1

    def test_linked_observation(self):
        from conscience.models import Rumination, Observation
        obs = Observation.objects.create(
            source="chat",
            event_type="chat.message",
            summary="You promised me X",
            pertinence=0.8,
            emotional_reaction="frustrated",
        )
        r = Rumination.objects.create(
            summary=obs.summary,
            intensity=obs.pertinence,
            emotion=obs.emotional_reaction,
            observation=obs,
        )
        assert r.observation_id == obs.id
        # Reverse relation
        assert obs.ruminations.count() == 1

    def test_observation_deleted_nulls_fk(self):
        from conscience.models import Rumination, Observation
        obs = Observation.objects.create(
            source="chat",
            event_type="chat.message",
            summary="tmp",
            pertinence=0.5,
        )
        r = Rumination.objects.create(
            summary="tmp", intensity=0.5, observation=obs
        )
        obs.delete()
        r.refresh_from_db()
        assert r.observation_id is None


# ---------------------------------------------------------------------------
# DB-level: Conscience engine rumination helpers
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
class TestConscienceRuminationHelpers:

    @pytest.mark.asyncio
    async def test_rumination_snapshot_with_empty_db(self):
        from conscience.engine import ConscienceEngine
        engine = ConscienceEngine()
        pressure, count = await engine._rumination_snapshot()
        assert pressure == 0.0
        assert count == 0

    @pytest.mark.asyncio
    async def test_rumination_snapshot_aggregates_active(self):
        from asgiref.sync import sync_to_async
        from conscience.engine import ConscienceEngine
        from conscience.models import Rumination

        await sync_to_async(Rumination.objects.create)(
            summary="a", intensity=0.4, status="active"
        )
        await sync_to_async(Rumination.objects.create)(
            summary="b", intensity=0.3, status="active"
        )
        await sync_to_async(Rumination.objects.create)(
            summary="c_faded", intensity=0.5, status="faded"
        )

        engine = ConscienceEngine()
        pressure, count = await engine._rumination_snapshot()
        # Only active ones counted: 0.4 + 0.3 = 0.7 (clamped <= 1.0)
        assert abs(pressure - 0.7) < 0.01
        assert count == 2

    @pytest.mark.asyncio
    async def test_resolve_ruminations_halves_intensity(self):
        from asgiref.sync import sync_to_async
        from conscience.engine import ConscienceEngine
        from conscience.models import Rumination

        r = await sync_to_async(Rumination.objects.create)(
            summary="still bothered", intensity=0.8, status="active"
        )

        engine = ConscienceEngine()
        await engine._resolve_ruminations_after_act("j'ai parle")

        await sync_to_async(r.refresh_from_db)()
        assert abs(r.intensity - 0.4) < 0.01
        assert r.status == "active"  # 0.4 is still above 0.1 threshold

    @pytest.mark.asyncio
    async def test_resolve_ruminations_marks_tiny_as_resolved(self):
        from asgiref.sync import sync_to_async
        from conscience.engine import ConscienceEngine
        from conscience.models import Rumination

        r = await sync_to_async(Rumination.objects.create)(
            summary="almost gone", intensity=0.15, status="active"
        )

        engine = ConscienceEngine()
        await engine._resolve_ruminations_after_act("")

        await sync_to_async(r.refresh_from_db)()
        # 0.15 × 0.5 = 0.075 < 0.1 → resolved
        assert r.status == "resolved"

    @pytest.mark.asyncio
    async def test_decay_ruminations_fades_low_intensity(self):
        from asgiref.sync import sync_to_async
        from conscience.engine import ConscienceEngine
        from conscience.models import Rumination

        r = await sync_to_async(Rumination.objects.create)(
            summary="very weak", intensity=0.105, status="active"
        )

        engine = ConscienceEngine()
        await engine._decay_ruminations()

        await sync_to_async(r.refresh_from_db)()
        # 0.105 × 0.95 = 0.0998 < 0.1 → faded
        assert r.status == "faded"
