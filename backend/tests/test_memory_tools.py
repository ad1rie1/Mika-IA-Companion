"""Tests for the memory_tools module — Mika's active recall surface.

Search goes through memory_manager (mocked — no ChromaDB in tests);
journal and commitment tools hit the ORM directly.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from memory.module import MemoryToolsModule


def _tools():
    return {t.name: t for t in MemoryToolsModule().return_tools()}


class TestToolSurface:

    def test_expected_tools_exposed(self):
        names = set(_tools())
        assert names == {
            "memory_search",
            "memory_recent_souvenirs",
            "memory_read_journal",
            "memory_list_commitments",
            "memory_resolve_commitment",
        }

    def test_module_is_system(self):
        assert MemoryToolsModule.SYSTEM is True


@pytest.mark.asyncio
class TestSearch:

    async def test_searches_both_kinds_by_default(self):
        tool = _tools()["memory_search"]
        with patch("memory.manager.memory_manager") as mm:
            mm.search_related_souvenirs = AsyncMock(return_value=[
                {"content": "On a joue a Zelda", "metadata": {"emotion": "happy"}},
            ])
            mm.search_related_connaissances = AsyncMock(return_value=[
                {"content": "Thomas aime les jeux retro", "metadata": {}},
            ])
            result = await tool.handler({"query": "zelda"})

        assert result["souvenirs"][0]["content"] == "On a joue a Zelda"
        assert result["souvenirs"][0]["emotion"] == "happy"
        assert result["connaissances"][0]["content"] == "Thomas aime les jeux retro"

    async def test_kind_filter_souvenirs_only(self):
        tool = _tools()["memory_search"]
        with patch("memory.manager.memory_manager") as mm:
            mm.search_related_souvenirs = AsyncMock(return_value=[])
            mm.search_related_connaissances = AsyncMock(return_value=[])
            await tool.handler({"query": "x", "kind": "souvenirs"})

            mm.search_related_souvenirs.assert_awaited_once()
            mm.search_related_connaissances.assert_not_awaited()

    async def test_empty_query_rejected(self):
        tool = _tools()["memory_search"]
        result = await tool.handler({"query": "  "})
        assert "error" in result

    async def test_no_results_message(self):
        tool = _tools()["memory_search"]
        with patch("memory.manager.memory_manager") as mm:
            mm.search_related_souvenirs = AsyncMock(return_value=[])
            mm.search_related_connaissances = AsyncMock(return_value=[])
            result = await tool.handler({"query": "introuvable"})
        assert "message" in result


@pytest.mark.django_db(transaction=True)
class TestJournalTool:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from memory.models import DailyJournal
        DailyJournal.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_reads_recent_journals(self):
        from memory.models import DailyJournal
        await sync_to_async(DailyJournal.objects.create)(
            date=date.today() - timedelta(days=1),
            narrative="Hier on a beaucoup parle de musique.",
            dominant_emotion="happy",
            persons_interacted=["Thomas"],
        )
        tool = _tools()["memory_read_journal"]
        result = await tool.handler({})
        assert len(result["journaux"]) == 1
        assert "musique" in result["journaux"][0]["recit"]

    @pytest.mark.asyncio
    async def test_specific_date(self):
        from memory.models import DailyJournal
        target = date.today() - timedelta(days=3)
        await sync_to_async(DailyJournal.objects.create)(
            date=target, narrative="Journee calme.",
        )
        tool = _tools()["memory_read_journal"]
        result = await tool.handler({"date": target.isoformat()})
        assert result["journaux"][0]["date"] == target.isoformat()

    @pytest.mark.asyncio
    async def test_missing_date_message(self):
        tool = _tools()["memory_read_journal"]
        result = await tool.handler({"date": "1999-01-01"})
        assert "message" in result


@pytest.mark.django_db(transaction=True)
class TestCommitmentTools:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from memory.models import Commitment
        Commitment.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_list_pending_only_by_default(self):
        from memory.models import Commitment
        await sync_to_async(Commitment.objects.create)(
            description="Envoyer la playlist", status="pending",
        )
        await sync_to_async(Commitment.objects.create)(
            description="Vieux truc", status="honored",
        )
        tool = _tools()["memory_list_commitments"]
        result = await tool.handler({})
        descriptions = [c["description"] for c in result["engagements"]]
        assert descriptions == ["Envoyer la playlist"]

    @pytest.mark.asyncio
    async def test_resolve_marks_honored(self):
        from memory.models import Commitment
        c = await sync_to_async(Commitment.objects.create)(
            description="Envoyer la playlist", status="pending",
        )
        tool = _tools()["memory_resolve_commitment"]
        result = await tool.handler({"commitment_id": c.pk})
        assert result.get("success") is True

        refreshed = await sync_to_async(Commitment.objects.get)(pk=c.pk)
        assert refreshed.status == "honored"
        assert refreshed.resolved_at is not None

    @pytest.mark.asyncio
    async def test_resolve_dropped(self):
        from memory.models import Commitment
        c = await sync_to_async(Commitment.objects.create)(
            description="Truc annule", status="pending",
        )
        tool = _tools()["memory_resolve_commitment"]
        await tool.handler({"commitment_id": c.pk, "status": "dropped"})
        refreshed = await sync_to_async(Commitment.objects.get)(pk=c.pk)
        assert refreshed.status == "dropped"

    @pytest.mark.asyncio
    async def test_resolve_unknown_id(self):
        tool = _tools()["memory_resolve_commitment"]
        result = await tool.handler({"commitment_id": 424242})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_resolve_invalid_status(self):
        tool = _tools()["memory_resolve_commitment"]
        result = await tool.handler({"commitment_id": 1, "status": "peut-etre"})
        assert "error" in result
