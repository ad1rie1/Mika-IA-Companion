"""Regressions for the runtime audit fixes.

Four independent problems, all of which cost real time or real money on an
install nobody is even talking to:

  - SQLite running in DELETE journal mode under six concurrent write loops
  - the shared module scheduler blocking on whichever module was slowest
  - one LLM call per RSS entry, in series, inside that same scheduler
  - memory decay re-subtracting its whole elapsed total on every tick
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone


class TestDatabaseConcurrency:
    """WAL is what lets a conversation read while the loops write."""

    @pytest.mark.django_db
    def test_busy_timeout_applies_at_runtime(self):
        """The test database is in-memory (WAL is a no-op there), but the
        busy timeout comes from the same OPTIONS block and does apply — so it
        proves the options actually reach the connection."""
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("PRAGMA busy_timeout")
            busy = cursor.fetchone()[0]

        assert busy >= 10_000, "5s par defaut se traduit par 'database is locked'"

    def test_settings_declare_the_pragmas(self):
        """The real guard: an in-memory test DB can never exercise WAL, so
        the declaration is what a regression would have to get past."""
        from django.conf import settings

        options = settings.DATABASES["default"]["OPTIONS"]
        assert "journal_mode=WAL" in options["init_command"], (
            "en journal_mode=delete un seul writer bloque tous les readers"
        )
        assert options["timeout"] >= 10


def _scheduler():
    """A CronScheduler over an empty registry.

    These used to build a ``ModuleManager.__new__`` shell and hand-set the
    one attribute the scheduler needed — which worked only because the
    manager was a bag of unrelated state. The scheduler is now its own
    object, so the test constructs the real thing.
    """
    from modules.registry import ModuleRegistry
    from modules.scheduler import CronScheduler

    return CronScheduler(ModuleRegistry())


@pytest.mark.asyncio
class TestSchedulerIsolation:
    """One slow module must not hold up every other module."""

    async def test_a_slow_module_does_not_block_the_tick(self):
        scheduler = _scheduler()
        started = asyncio.Event()

        class _Slow:
            name = "slow"

            async def worker_cron(self):
                started.set()
                await asyncio.sleep(30)

        scheduler._spawn(_Slow())
        # The scheduler returned immediately; the tick is still running.
        await asyncio.wait_for(started.wait(), timeout=1)
        assert not scheduler._ticks["slow"].done()

        scheduler._ticks["slow"].cancel()
        await asyncio.gather(*scheduler._ticks.values(), return_exceptions=True)

    async def test_a_failing_tick_is_logged_not_propagated(self):
        from modules.scheduler import CronScheduler

        class _Boom:
            name = "boom"

            async def worker_cron(self):
                raise RuntimeError("boom")

        # Must not raise: the scheduler survives a broken module.
        await CronScheduler._run_once(_Boom())

    async def test_overlapping_ticks_are_skipped_not_queued(self):
        """A module slower than its interval degrades gracefully."""
        scheduler = _scheduler()
        calls = []

        class _Slow:
            name = "slow"

            async def worker_cron(self):
                calls.append(1)
                await asyncio.sleep(5)

        scheduler._spawn(_Slow())
        await asyncio.sleep(0)

        running = scheduler._ticks.get("slow")
        assert running is not None and not running.done()
        # This is the scheduler's guard condition.
        assert len(calls) == 1

        running.cancel()
        await asyncio.gather(running, return_exceptions=True)

    async def test_finished_ticks_do_not_leak(self):
        scheduler = _scheduler()

        class _Quick:
            name = "quick"

            async def worker_cron(self):
                return None

        scheduler._spawn(_Quick())
        await asyncio.sleep(0.05)
        assert "quick" not in scheduler._ticks


class TestSignalInterpretationCost:
    """Every event outside the fast-path costs a Haiku call, in series."""

    def test_rss_entries_never_reach_the_llm(self):
        from conscience.interpreter import heuristic_for

        assert heuristic_for("rss.new_entry") is not None, (
            "un poll de 5 flux = ~75 appels LLM en serie dans le scheduler"
        )

    def test_forged_module_events_never_reach_the_llm(self):
        from conscience.interpreter import heuristic_for

        assert heuristic_for("forge.meteo.alerte") is not None
        assert heuristic_for("forge.anything.at.all") is not None

    def test_emails_still_go_through_the_llm(self):
        """Rich content whose importance can't be read off a keyword table."""
        from conscience.interpreter import heuristic_for

        assert heuristic_for("email.received") is None

    def test_rss_heuristic_scores_on_theme_match(self):
        from conscience.interpreter import heuristic_for

        handler = heuristic_for("rss.new_entry")
        on_topic = handler({
            "feed_name": "Tech", "title": "Nouveau framework python",
            "summary": "pour les devs",
        })
        off_topic = handler({
            "feed_name": "Divers", "title": "Communique municipal",
            "summary": "reunion du conseil",
        })
        assert on_topic.pertinence > off_topic.pertinence
        assert "tech" in on_topic.themes
        assert off_topic.themes == []

    def test_rss_heuristic_never_claims_to_remember(self):
        from conscience.interpreter import heuristic_for

        signal = heuristic_for("rss.new_entry")({"title": "x", "feed_name": "f"})
        assert signal.should_remember is False


@pytest.mark.django_db(transaction=True)
class TestMemoryDecayAnchoring:
    """Decay must be relative to its anchor, and idempotent within the hour."""

    @pytest.fixture(autouse=True)
    def _clean(self):
        from memory.models import Connaissance, Souvenir
        Connaissance.objects.all().delete()
        Souvenir.objects.all().delete()
        yield

    @staticmethod
    def _consolidator():
        from memory.storage.consolidator import MemoryConsolidator
        return MemoryConsolidator.__new__(MemoryConsolidator)

    @pytest.mark.asyncio
    async def test_connaissance_decay_does_not_compound_each_tick(self):
        """The bug: `save(update_fields=["confidence"])` never advances an
        auto_now field, so `updated_at` stayed frozen and every pass
        re-subtracted the entire elapsed decay. A month-old fact lost ~0.086
        per 60s tick and hit the floor in about ten minutes.
        """
        from memory.models import Connaissance

        conn = await sync_to_async(Connaissance.objects.create)(
            content="Thomas habite a Toulouse", confidence=1.0,
        )
        await sync_to_async(
            lambda: Connaissance.objects.filter(pk=conn.pk).update(
                updated_at=timezone.now() - timedelta(days=30),
            )
        )()

        consolidator = self._consolidator()
        await consolidator._decay_connaissances()
        after_first = await sync_to_async(
            lambda: Connaissance.objects.get(pk=conn.pk).confidence
        )()

        for _ in range(4):
            await consolidator._decay_connaissances()
        after_many = await sync_to_async(
            lambda: Connaissance.objects.get(pk=conn.pk).confidence
        )()

        assert after_first < 1.0, "le rattrapage doit s'appliquer une fois"
        assert after_many == after_first, (
            "les passes suivantes doivent etre des no-op tant que l'ancre est fraiche"
        )

    @pytest.mark.asyncio
    async def test_recently_reinforced_knowledge_is_untouched(self):
        from memory.models import Connaissance

        conn = await sync_to_async(Connaissance.objects.create)(
            content="fait tout frais", confidence=1.0,
        )
        await self._consolidator()._decay_connaissances()
        assert await sync_to_async(
            lambda: Connaissance.objects.get(pk=conn.pk).confidence
        )() == 1.0

    @pytest.mark.asyncio
    async def test_freshly_decayed_rows_are_not_re_read(self):
        """A souvenir touched minutes ago cannot move, so it must not be read.

        The sweep used to load every souvenir above the prune threshold into
        RAM on each pass — 1440 full-table reads a day — only to skip almost
        all of them in Python. Narrowing it in SQL is what made the pass
        cheap enough to stop being the dominant query load on an idle
        install. Nothing is lost: the anchor keeps accumulating elapsed time.
        """
        from memory.models import Souvenir

        now = timezone.now()
        for i in range(10):
            souvenir = await sync_to_async(Souvenir.objects.create)(
                content=f"souvenir {i}", importance=1.0, occurred_at=now,
            )
            await sync_to_async(
                lambda pk=souvenir.pk: Souvenir.objects.filter(pk=pk).update(
                    decayed_at=now,
                )
            )()
        # One row whose anchor is old enough to actually move.
        stale = await sync_to_async(Souvenir.objects.create)(
            content="ancien", importance=1.0,
            occurred_at=now - timedelta(days=5),
        )
        await sync_to_async(
            lambda: Souvenir.objects.filter(pk=stale.pk).update(
                decayed_at=now - timedelta(days=2),
            )
        )()

        consolidator = self._consolidator()
        consolidator.vector_store = _NullVectorStore()
        await consolidator._decay_souvenirs()

        untouched = await sync_to_async(
            lambda: list(
                Souvenir.objects.filter(content__startswith="souvenir")
                .values_list("importance", flat=True)
            )
        )()
        moved = await sync_to_async(
            lambda: Souvenir.objects.get(pk=stale.pk).importance
        )()

        assert set(untouched) == {1.0}, "les lignes fraiches ne doivent pas bouger"
        assert moved < 1.0, "la ligne eligible doit avoir decru"

    @pytest.mark.asyncio
    async def test_conscience_boost_survives_decay(self):
        """Relative decay is what keeps a boosted souvenir boosted."""
        from memory.models import Souvenir

        souvenir = await sync_to_async(Souvenir.objects.create)(
            content="moment important", importance=0.9,
            occurred_at=timezone.now() - timedelta(days=10),
        )
        await sync_to_async(
            lambda: Souvenir.objects.filter(pk=souvenir.pk).update(
                decayed_at=timezone.now() - timedelta(days=1),
            )
        )()

        consolidator = self._consolidator()
        consolidator.vector_store = _NullVectorStore()
        await consolidator._decay_souvenirs()

        importance = await sync_to_async(
            lambda: Souvenir.objects.get(pk=souvenir.pk).importance
        )()
        # One day at 0.95/day off 0.9, not a recompute from the 10-day age.
        assert 0.84 < importance < 0.87


class TestDecayThrottling:

    @pytest.mark.asyncio
    async def test_apply_decay_is_throttled_between_sweeps(self):
        """Decay is measured in days; sweeping every 60s was pure load."""
        from unittest.mock import AsyncMock
        from memory.storage.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator.__new__(MemoryConsolidator)
        consolidator._decay_souvenirs = AsyncMock()
        consolidator._decay_connaissances = AsyncMock()
        consolidator._expire_commitments = AsyncMock()
        consolidator._sweep_retention = AsyncMock()

        await consolidator._apply_decay()
        await consolidator._apply_decay()
        await consolidator._apply_decay()

        assert consolidator._decay_souvenirs.await_count == 1
        # Commitment expiry is cheap indexed UPDATEs and keeps its own cadence:
        # it is what stops a stale promise being re-asserted in every prompt.
        assert consolidator._expire_commitments.await_count == 3


class _NullVectorStore:
    """ChromaDB stand-in — the decay path re-indexes on every write."""

    def add_souvenir(self, **kwargs):
        return None

    def add_souvenirs(self, entries):
        return None

    def remove_souvenir(self, souvenir_id):
        return None
