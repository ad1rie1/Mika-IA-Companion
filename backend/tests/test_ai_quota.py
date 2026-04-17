"""Tests for the AI quota tracker + limiter + router integration."""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from django.test import override_settings

from ai.quota import (
    QuotaExceeded,
    QuotaTracker,
    _lookup_pricing,
    current_project_id,
    estimate_tokens_from_chars,
    quota_tracker,
    set_usage,
)
from ai.router import AIRole, AIRouter


@pytest.fixture(autouse=True)
def reset_tracker():
    """Each test starts with a clean tracker."""
    quota_tracker.reset()
    yield
    quota_tracker.reset()


# ── Pricing table ────────────────────────────────────────────────


class TestPricingLookup:

    def test_exact_match(self):
        in_rate, out_rate = _lookup_pricing("claude", "claude-opus-4-7")
        assert in_rate == pytest.approx(15 / 1_000_000)
        assert out_rate == pytest.approx(75 / 1_000_000)

    def test_prefix_match_picks_longest(self):
        # "claude-opus-4-99" is unknown, but "claude-opus-4" prefix matches
        in_rate, out_rate = _lookup_pricing("claude", "claude-opus-4-99")
        assert in_rate == pytest.approx(15 / 1_000_000)

    def test_ollama_is_free(self):
        in_rate, out_rate = _lookup_pricing("ollama", "llama3")
        assert in_rate == 0
        assert out_rate == 0

    def test_unknown_family_is_free(self):
        in_rate, out_rate = _lookup_pricing("openai", "totally-made-up-model")
        assert in_rate == 0
        assert out_rate == 0

    def test_case_insensitive(self):
        a = _lookup_pricing("claude", "Claude-Opus-4-7")
        b = _lookup_pricing("claude", "claude-opus-4-7")
        assert a == b


class TestTokenEstimate:

    def test_char_estimate(self):
        # "hello world" (11 chars) ≈ 2 tokens
        assert estimate_tokens_from_chars(11) == 2

    def test_minimum_one(self):
        # Even 1 char counts as at least 1 token
        assert estimate_tokens_from_chars(1) == 1

    def test_zero_is_zero(self):
        assert estimate_tokens_from_chars(0) == 0


# ── QuotaTracker core ────────────────────────────────────────────


class TestQuotaTrackerCheck:

    def test_no_limits_never_raises(self):
        tracker = QuotaTracker()
        # All env vars default to 0 (unlimited)
        tracker.check(role="conversation", project_id=None, expected_tokens=1_000_000)

    @override_settings(AI_QUOTA_DAILY_TOKENS=1000)
    def test_global_daily_limit_raises(self):
        tracker = QuotaTracker()
        tracker.record(
            role="conversation", provider="claude", model="claude-opus-4-7",
            tokens_in=500, tokens_out=400,
        )
        # Next call budgeting 200 would push to 1100 > 1000 → raise
        with pytest.raises(QuotaExceeded) as exc:
            tracker.check(role="conversation", expected_tokens=200)
        assert exc.value.scope == "global:daily"

    @override_settings(AI_QUOTA_ROLE_MEMORY_EXTRACTION_DAILY=500)
    def test_role_daily_limit_raises(self):
        tracker = QuotaTracker()
        tracker.record(
            role="memory_extraction", provider="claude", model="claude-haiku-4-5",
            tokens_in=400, tokens_out=50,
        )
        # At 450; a 100-token call would push to 550 → over 500
        with pytest.raises(QuotaExceeded) as exc:
            tracker.check(role="memory_extraction", expected_tokens=100)
        assert exc.value.scope == "role:memory_extraction:daily"

    @override_settings(AI_QUOTA_ROLE_MEMORY_EXTRACTION_DAILY=500)
    def test_other_role_unaffected_by_role_limit(self):
        tracker = QuotaTracker()
        tracker.record(
            role="memory_extraction", provider="claude", model="claude-haiku-4-5",
            tokens_in=400, tokens_out=400,
        )
        # "conversation" has no cap — should not raise
        tracker.check(role="conversation", expected_tokens=10_000)


class TestQuotaTrackerRecord:

    def test_record_returns_cost(self):
        tracker = QuotaTracker()
        cost = tracker.record(
            role="conversation", provider="claude", model="claude-opus-4-7",
            tokens_in=1000, tokens_out=1000,
        )
        # 1000 * 15/1M + 1000 * 75/1M = 0.015 + 0.075 = 0.09
        assert cost == pytest.approx(0.09)

    def test_record_aggregates_across_calls(self):
        tracker = QuotaTracker()
        tracker.record(
            role="conversation", provider="claude", model="claude-haiku-4-5",
            tokens_in=100, tokens_out=50,
        )
        tracker.record(
            role="conversation", provider="claude", model="claude-haiku-4-5",
            tokens_in=200, tokens_out=80,
        )
        snap = tracker.snapshot()
        assert snap.roles["conversation"]["tokens_day"] == 430
        assert snap.roles["conversation"]["calls_day"] == 2

    def test_record_splits_per_project(self):
        tracker = QuotaTracker()
        tracker.record(
            role="memory_extraction", provider="claude", model="claude-haiku-4-5",
            tokens_in=100, tokens_out=50, project_id=None,
        )
        tracker.record(
            role="memory_extraction", provider="claude", model="claude-haiku-4-5",
            tokens_in=300, tokens_out=100, project_id=7,
        )
        snap = tracker.snapshot()
        assert snap.roles["memory_extraction"]["tokens_day"] == 550
        assert snap.projects["7"]["tokens_day"] == 400
        # The null-project call should NOT appear in projects
        assert "None" not in snap.projects


class TestQuotaTrackerSnapshot:

    def test_snapshot_includes_today_and_month(self):
        tracker = QuotaTracker()
        snap = tracker.snapshot()
        assert len(snap.today) == 10  # YYYY-MM-DD
        assert len(snap.month) == 7   # YYYY-MM
        assert snap.roles == {}
        assert snap.projects == {}

    @override_settings(AI_QUOTA_DAILY_TOKENS=5000)
    def test_snapshot_exposes_limits(self):
        tracker = QuotaTracker()
        snap = tracker.snapshot()
        assert snap.limits["global_daily"] == 5000


# ── AIRouter integration ────────────────────────────────────────


class TestRouterRecords:

    @pytest.mark.asyncio
    async def test_router_records_from_char_estimate(self):
        router = AIRouter()
        mock_provider = MagicMock()
        mock_provider.complete = AsyncMock(return_value="réponse de quarante caractères mille douze")
        router._providers["claude"] = mock_provider
        router._role_config[AIRole.CONVERSATION] = ("claude", "claude-opus-4-7")

        await router.complete(AIRole.CONVERSATION, "sys prompt", "user prompt")

        snap = quota_tracker.snapshot()
        assert "conversation" in snap.roles
        assert snap.roles["conversation"]["calls_day"] == 1
        assert snap.roles["conversation"]["tokens_day"] > 0

    @pytest.mark.asyncio
    async def test_router_uses_provider_usage_when_available(self):
        router = AIRouter()

        async def fake_complete(*, system_prompt, user_prompt, model, **kw):
            # Simulate what ClaudeProvider does after the API call.
            set_usage(input_tokens=1234, output_tokens=567)
            return "ok"

        mock_provider = MagicMock()
        mock_provider.complete = fake_complete
        router._providers["claude"] = mock_provider
        router._role_config[AIRole.CONVERSATION] = ("claude", "claude-opus-4-7")

        await router.complete(AIRole.CONVERSATION, "sys", "user")

        snap = quota_tracker.snapshot()
        # Real token counts (not the char estimate)
        assert snap.roles["conversation"]["tokens_day"] == 1234 + 567

    @pytest.mark.asyncio
    @override_settings(AI_QUOTA_ROLE_CONVERSATION_DAILY=100)
    async def test_router_refuses_when_over_role_limit(self):
        router = AIRouter()
        mock_provider = MagicMock()
        mock_provider.complete = AsyncMock(return_value="should not be called")
        router._providers["claude"] = mock_provider
        router._role_config[AIRole.CONVERSATION] = ("claude", "claude-haiku-4-5")

        # Pre-burn the daily budget
        quota_tracker.record(
            role="conversation", provider="claude", model="claude-haiku-4-5",
            tokens_in=80, tokens_out=30,
        )
        with pytest.raises(QuotaExceeded):
            # Prompt of "xxx" → ~1 token + reply room 512 → well past 100
            await router.complete(AIRole.CONVERSATION, "xxx", "yyy")
        mock_provider.complete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_router_attributes_call_to_project(self):
        router = AIRouter()

        async def fake(*, system_prompt, user_prompt, model, **kw):
            set_usage(input_tokens=100, output_tokens=50)
            return "x"

        mock_provider = MagicMock()
        mock_provider.complete = fake
        router._providers["claude"] = mock_provider
        router._role_config[AIRole.MEMORY_EXTRACTION] = ("claude", "claude-haiku-4-5")

        token = current_project_id.set(42)
        try:
            await router.complete(AIRole.MEMORY_EXTRACTION, "s", "u")
        finally:
            current_project_id.reset(token)

        snap = quota_tracker.snapshot()
        assert snap.projects["42"]["tokens_day"] == 150
        assert snap.roles["memory_extraction"]["tokens_day"] == 150


# ── Project budget ────────────────────────────────────────────────


class TestProjectBudget:

    @pytest.mark.django_db(transaction=True)
    def test_project_monthly_budget_enforced(self):
        from projects.models import Project
        project = Project.objects.create(
            title="Test",
            status=Project.Status.ACTIVE,
            monthly_token_budget=500,
        )
        tracker = QuotaTracker()
        tracker.record(
            role="memory_extraction", provider="claude", model="claude-haiku-4-5",
            tokens_in=300, tokens_out=150, project_id=project.id,
        )
        # At 450, next call of ~100 tokens → 550 > 500
        with pytest.raises(QuotaExceeded) as exc:
            tracker.check(
                role="memory_extraction",
                project_id=project.id,
                expected_tokens=100,
            )
        assert exc.value.scope == f"project:{project.id}:monthly"

    @pytest.mark.django_db(transaction=True)
    def test_project_with_zero_budget_is_unlimited(self):
        from projects.models import Project
        project = Project.objects.create(
            title="Test",
            status=Project.Status.ACTIVE,
            monthly_token_budget=0,
        )
        tracker = QuotaTracker()
        # Even a huge pre-load doesn't raise
        tracker.record(
            role="memory_extraction", provider="claude", model="claude-haiku-4-5",
            tokens_in=100_000, tokens_out=50_000, project_id=project.id,
        )
        tracker.check(
            role="memory_extraction",
            project_id=project.id,
            expected_tokens=1_000_000,
        )


# ── DB persistence ────────────────────────────────────────────────


class TestQuotaPersistence:

    @pytest.mark.django_db(transaction=True)
    def test_record_writes_to_db(self):
        from ai.models import AIQuotaUsage
        tracker = QuotaTracker()
        tracker.record(
            role="conversation", provider="claude", model="claude-opus-4-7",
            tokens_in=100, tokens_out=50,
        )
        row = AIQuotaUsage.objects.get(role="conversation", project_id__isnull=True)
        assert row.tokens_in == 100
        assert row.tokens_out == 50
        assert row.call_count == 1

    @pytest.mark.django_db(transaction=True)
    def test_record_increments_existing_row(self):
        from ai.models import AIQuotaUsage
        tracker = QuotaTracker()
        tracker.record(
            role="conversation", provider="claude", model="claude-opus-4-7",
            tokens_in=100, tokens_out=50,
        )
        tracker.record(
            role="conversation", provider="claude", model="claude-opus-4-7",
            tokens_in=200, tokens_out=80,
        )
        rows = AIQuotaUsage.objects.filter(role="conversation")
        assert rows.count() == 1
        row = rows.first()
        assert row.tokens_in == 300
        assert row.tokens_out == 130
        assert row.call_count == 2
