"""Tests for yesterday's-journal injection into the system prompt.

The nightly DailyJournal used to be write-only for the conversation:
shown in the frontend panel but never re-read. `_fetch_journal_context`
turns it into Mika's day-to-day continuity thread.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from asgiref.sync import sync_to_async

from pipeline.context import _fetch_journal_context
from pipeline.prompt import build_system_prompt


@pytest.mark.django_db(transaction=True)
class TestJournalContext:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from memory.models import DailyJournal
        DailyJournal.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_yesterday_journal_is_injected(self):
        from memory.models import DailyJournal
        await sync_to_async(DailyJournal.objects.create)(
            date=date.today() - timedelta(days=1),
            narrative="On a passe la soiree a parler de synthwave avec Thomas.",
            dominant_emotion="happy",
            persons_interacted=["Thomas"],
        )
        ctx = await _fetch_journal_context()
        assert "synthwave" in ctx
        assert "Thomas" in ctx
        assert "happy" in ctx

    @pytest.mark.asyncio
    async def test_no_journal_yields_empty(self):
        assert await _fetch_journal_context() == ""

    @pytest.mark.asyncio
    async def test_older_journal_not_used(self):
        from memory.models import DailyJournal
        await sync_to_async(DailyJournal.objects.create)(
            date=date.today() - timedelta(days=3),
            narrative="Vieille journee.",
        )
        assert await _fetch_journal_context() == ""

    @pytest.mark.asyncio
    async def test_long_narrative_capped(self):
        from memory.models import DailyJournal
        from pipeline.context import _JOURNAL_MAX_CHARS
        await sync_to_async(DailyJournal.objects.create)(
            date=date.today() - timedelta(days=1),
            narrative="tres longue journee " * 100,
        )
        ctx = await _fetch_journal_context()
        assert len(ctx) < _JOURNAL_MAX_CHARS + 400


class TestPromptBlock:

    def test_journal_block_present(self):
        system = build_system_prompt(journal_context="Ce que tu retiens d'hier : x")
        assert "--- TON FIL D'HIER ---" in system

    def test_absent_when_empty(self):
        system = build_system_prompt(journal_context="")
        assert "FIL D'HIER" not in system
