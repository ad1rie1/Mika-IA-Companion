"""Retention sweep — every append-only table has a ceiling.

The important case is ConscienceLog: one row per decision cycle regardless
of outcome, so at a 30s interval it grows by ~2 880 rows/day on an install
nobody ever talks to. These tests pin both policy shapes (age, row count),
the protect filter, and the fact that a broken policy can't take the
consolidator tick down.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone


async def _make_logs(n, *, age_days=0, decision="skip"):
    from conscience.models import ConscienceLog

    stamp = timezone.now() - timedelta(days=age_days)
    for i in range(n):
        row = await sync_to_async(ConscienceLog.objects.create)(
            decision=decision, reason=f"r{i}",
        )
        await sync_to_async(
            lambda pk=row.pk: ConscienceLog.objects.filter(pk=pk).update(
                created_at=stamp)
        )()


@pytest.mark.django_db(transaction=True)
class TestRetentionSweep:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from conscience.models import ConscienceLog, Rumination
        ConscienceLog.objects.all().delete()
        Rumination.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_old_conscience_logs_are_deleted(self):
        from conscience.models import ConscienceLog
        from memory.retention import run_sweep

        await _make_logs(3, age_days=60)
        await _make_logs(2, age_days=1)

        await run_sweep()

        remaining = await sync_to_async(ConscienceLog.objects.count)()
        assert remaining == 2

    @pytest.mark.asyncio
    async def test_recent_logs_are_untouched(self):
        from conscience.models import ConscienceLog
        from memory.retention import run_sweep

        await _make_logs(5, age_days=2)
        await run_sweep()
        assert await sync_to_async(ConscienceLog.objects.count)() == 5

    @pytest.mark.asyncio
    async def test_row_ceiling_applies_inside_the_age_window(self):
        from conscience.models import ConscienceLog
        from memory.retention import Policy, _sweep_one

        await _make_logs(10, age_days=1)
        # Same table, tiny ceiling — the age filter alone would keep all 10.
        policy = Policy("conscience", "ConscienceLog", keep_rows=4)
        removed = await _sweep_one(policy)

        assert removed == 6
        assert await sync_to_async(ConscienceLog.objects.count)() == 4

    @pytest.mark.asyncio
    async def test_protect_filter_shields_rows(self):
        from conscience.models import Rumination
        from memory.retention import run_sweep

        old = timezone.now() - timedelta(days=200)
        for status in ("active", "resolved", "faded"):
            r = await sync_to_async(Rumination.objects.create)(
                summary=f"pensée {status}", status=status,
            )
            await sync_to_async(
                lambda pk=r.pk: Rumination.objects.filter(pk=pk).update(
                    created_at=old)
            )()

        await run_sweep()

        statuses = set(await sync_to_async(
            lambda: list(Rumination.objects.values_list("status", flat=True)))())
        # Active and resolved thoughts are still referenced; faded ones aren't.
        assert statuses == {"active", "resolved"}

    @pytest.mark.asyncio
    async def test_empty_tables_are_a_noop(self):
        from memory.retention import run_sweep
        assert await run_sweep() == {}

    @pytest.mark.asyncio
    async def test_broken_policy_does_not_abort_the_sweep(self):
        from unittest.mock import patch

        from conscience.models import ConscienceLog
        from memory.retention import POLICIES, Policy, run_sweep

        await _make_logs(2, age_days=60)
        bogus = (Policy("nope", "NotAModel", keep_days=1),) + POLICIES

        with patch("memory.retention.POLICIES", bogus):
            await run_sweep()

        # The real policy still ran despite the bogus one raising.
        assert await sync_to_async(ConscienceLog.objects.count)() == 0

    @pytest.mark.asyncio
    async def test_every_policy_targets_a_real_model_and_field(self):
        from django.apps import apps

        from memory.retention import POLICIES

        assert POLICIES, "the sweep must actually cover something"
        for policy in POLICIES:
            model = apps.get_model(policy.app_label, policy.model_name)
            names = {f.name for f in model._meta.get_fields()}
            assert policy.date_field in names, (
                f"{policy.model_name}.{policy.date_field} does not exist")
            assert policy.keep_days or policy.keep_rows, (
                f"{policy.model_name} has no ceiling at all")


@pytest.mark.django_db(transaction=True)
class TestSweepThrottle:

    @pytest.mark.asyncio
    async def test_sweep_runs_at_most_once_per_interval(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from memory.storage.consolidator import MemoryConsolidator

        c = MemoryConsolidator.__new__(MemoryConsolidator)
        c.vector_store = MagicMock()

        with patch("memory.retention.run_sweep", new_callable=AsyncMock) as sweep:
            await c._sweep_retention()
            await c._sweep_retention()
            await c._sweep_retention()

        sweep.assert_awaited_once()
