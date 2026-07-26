"""Tests for souvenir importance decay.

The decay pass must be *relative* (multiply the stored importance by
rate^elapsed) and not *absolute* (recompute rate^age from scratch): the
conscience boosts souvenirs it finds pertinent, the sleep cycle writes
reflective souvenirs with a hand-set importance, and both must survive the
next consolidator tick.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone


def _make_consolidator():
    from memory.storage.consolidator import MemoryConsolidator
    c = MemoryConsolidator.__new__(MemoryConsolidator)
    c.vector_store = MagicMock()
    return c


async def _run_decay():
    await _make_consolidator()._decay_souvenirs()


@pytest.mark.django_db(transaction=True)
class TestSouvenirDecay:

    @pytest.mark.asyncio
    async def test_boost_is_not_wiped_by_next_pass(self):
        from memory.models import Souvenir

        now = timezone.now()
        s = await sync_to_async(Souvenir.objects.create)(
            content="quelque chose d'important",
            importance=0.9,          # boosted by the conscience
            occurred_at=now - timedelta(days=3),
            decayed_at=now,          # just decayed
        )
        await _run_decay()
        await sync_to_async(s.refresh_from_db)()
        # No elapsed time since the anchor → importance untouched, and in
        # particular NOT recomputed down to rate**3.
        assert s.importance == pytest.approx(0.9, abs=0.01)

    @pytest.mark.asyncio
    async def test_fresh_low_importance_is_not_inflated(self):
        from memory.models import Souvenir

        now = timezone.now()
        s = await sync_to_async(Souvenir.objects.create)(
            content="détail mineur",
            importance=0.3,
            occurred_at=now,
            decayed_at=now,
        )
        await _run_decay()
        await sync_to_async(s.refresh_from_db)()
        assert s.importance == pytest.approx(0.3, abs=0.01)

    @pytest.mark.asyncio
    async def test_elapsed_time_actually_decays(self):
        from memory.models import Souvenir

        now = timezone.now()
        s = await sync_to_async(Souvenir.objects.create)(
            content="souvenir vieillissant",
            importance=1.0,
            occurred_at=now - timedelta(days=10),
            decayed_at=now - timedelta(days=10),
        )
        await _run_decay()
        await sync_to_async(s.refresh_from_db)()
        assert s.importance < 1.0
        assert s.decayed_at is not None and s.decayed_at > now - timedelta(minutes=1)

    @pytest.mark.asyncio
    async def test_decay_is_not_applied_twice_for_the_same_elapsed_time(self):
        from memory.models import Souvenir

        now = timezone.now()
        s = await sync_to_async(Souvenir.objects.create)(
            content="souvenir vieillissant",
            importance=1.0,
            occurred_at=now - timedelta(days=10),
            decayed_at=now - timedelta(days=10),
        )
        await _run_decay()
        await sync_to_async(s.refresh_from_db)()
        after_first = s.importance
        await _run_decay()
        await sync_to_async(s.refresh_from_db)()
        # The anchor moved with the first pass, so an immediate second pass
        # is a no-op instead of re-applying ten days of decay.
        assert s.importance == pytest.approx(after_first, abs=0.01)

    @pytest.mark.asyncio
    async def test_missing_anchor_falls_back_to_occurred_at(self):
        from memory.models import Souvenir

        now = timezone.now()
        s = await sync_to_async(Souvenir.objects.create)(
            content="souvenir hérité sans ancre",
            importance=1.0,
            occurred_at=now - timedelta(days=5),
            decayed_at=None,
        )
        await _run_decay()
        await sync_to_async(s.refresh_from_db)()
        assert s.importance < 1.0
        assert s.decayed_at is not None

    @pytest.mark.asyncio
    async def test_souvenir_below_threshold_is_pruned(self):
        from memory.models import Souvenir

        now = timezone.now()
        s = await sync_to_async(Souvenir.objects.create)(
            content="souvenir mourant",
            importance=0.11,
            occurred_at=now - timedelta(days=400),
            decayed_at=now - timedelta(days=400),
        )
        await _run_decay()
        exists = await sync_to_async(
            Souvenir.objects.filter(pk=s.pk).exists)()
        assert not exists
