"""Tests for the commitment lifecycle.

A promise used to be born "pending" and stay pending forever — injected
into every prompt as "tu lui avais dit que...". The lifecycle now closes
three ways:
  - the consolidator's extraction call notices it was honored in the
    conversation window (``commitment_resolved`` extraction),
  - Mika resolves it explicitly via the memory_resolve_commitment tool,
  - it ages out (past ``due_at``, or pending > COMMITMENT_MAX_AGE_DAYS)
    and is dropped by ``_expire_commitments``.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone


def _make_consolidator(extractions=None):
    from memory.storage.consolidator import MemoryConsolidator
    c = MemoryConsolidator.__new__(MemoryConsolidator)
    c.vector_store = MagicMock()
    c.extractor = MagicMock()
    c.extractor.analyze_messages = AsyncMock(return_value=extractions or [])
    c._last_processed_id = 0
    return c


async def _add_message(content="on discute"):
    from memory.models import Conversation, Message
    conv = await sync_to_async(Conversation.objects.create)()
    await sync_to_async(Message.objects.create)(
        conversation=conv, role="user", source="frontend", content=content,
    )


async def _make_commitment(description="Envoyer la playlist a Thomas", **kw):
    from memory.models import Commitment
    return await sync_to_async(Commitment.objects.create)(
        description=description, status="pending", **kw
    )


@pytest.mark.django_db(transaction=True)
class TestConsolidatorResolution:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from memory.models import Commitment, ConsolidationLog, Conversation, Message
        Message.objects.all().delete()
        Commitment.objects.all().delete()
        ConsolidationLog.objects.all().delete()
        Conversation.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_pending_commitments_are_fed_to_extractor(self):
        from memory.models import Commitment
        c1 = await _make_commitment("Envoyer la playlist")
        await _add_message()

        cons = _make_consolidator()
        await cons._consolidate()

        kwargs = cons.extractor.analyze_messages.await_args.kwargs
        pending = kwargs["pending_commitments"]
        assert {"id": c1.pk, "description": "Envoyer la playlist"} in pending

    @pytest.mark.asyncio
    async def test_commitment_resolved_extraction_marks_honored(self):
        from memory.models import Commitment
        commitment = await _make_commitment()
        await _add_message("voila la playlist !")

        cons = _make_consolidator([
            {"type": "commitment_resolved", "store": True,
             "commitment_id": commitment.pk, "resolution": "honored"},
        ])
        await cons._consolidate()

        refreshed = await sync_to_async(Commitment.objects.get)(pk=commitment.pk)
        assert refreshed.status == "honored"
        assert refreshed.resolved_at is not None

    @pytest.mark.asyncio
    async def test_dropped_resolution(self):
        from memory.models import Commitment
        commitment = await _make_commitment()
        await _add_message("laisse tomber la playlist")

        cons = _make_consolidator([
            {"type": "commitment_resolved", "store": True,
             "commitment_id": commitment.pk, "resolution": "dropped"},
        ])
        await cons._consolidate()

        refreshed = await sync_to_async(Commitment.objects.get)(pk=commitment.pk)
        assert refreshed.status == "dropped"

    @pytest.mark.asyncio
    async def test_unknown_id_is_harmless(self):
        await _add_message()
        cons = _make_consolidator([
            {"type": "commitment_resolved", "store": True,
             "commitment_id": 999999, "resolution": "honored"},
        ])
        await cons._consolidate()  # must not raise


@pytest.mark.django_db(transaction=True)
class TestExpiry:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from memory.models import Commitment
        Commitment.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_past_due_at_is_dropped(self):
        from memory.models import Commitment
        commitment = await _make_commitment(
            due_at=timezone.now() - timedelta(hours=1)
        )
        cons = _make_consolidator()
        await cons._expire_commitments()

        refreshed = await sync_to_async(Commitment.objects.get)(pk=commitment.pk)
        assert refreshed.status == "dropped"

    @pytest.mark.asyncio
    async def test_old_pending_is_dropped(self):
        from memory.models import Commitment
        from memory.storage.consolidator import COMMITMENT_MAX_AGE_DAYS

        commitment = await _make_commitment()
        old = timezone.now() - timedelta(days=COMMITMENT_MAX_AGE_DAYS + 1)
        await sync_to_async(
            lambda: Commitment.objects.filter(pk=commitment.pk).update(created_at=old)
        )()

        cons = _make_consolidator()
        await cons._expire_commitments()

        refreshed = await sync_to_async(Commitment.objects.get)(pk=commitment.pk)
        assert refreshed.status == "dropped"

    @pytest.mark.asyncio
    async def test_fresh_pending_stays(self):
        from memory.models import Commitment
        commitment = await _make_commitment()
        cons = _make_consolidator()
        await cons._expire_commitments()

        refreshed = await sync_to_async(Commitment.objects.get)(pk=commitment.pk)
        assert refreshed.status == "pending"

    @pytest.mark.asyncio
    async def test_honored_is_untouched_by_age(self):
        from memory.models import Commitment
        commitment = await _make_commitment()
        past = timezone.now() - timedelta(days=90)
        await sync_to_async(
            lambda: Commitment.objects.filter(pk=commitment.pk).update(
                status="honored", created_at=past,
            )
        )()

        cons = _make_consolidator()
        await cons._expire_commitments()
        refreshed = await sync_to_async(Commitment.objects.get)(pk=commitment.pk)
        assert refreshed.status == "honored"


class TestExtractorPrompt:

    @pytest.mark.asyncio
    async def test_pending_block_appended_to_prompt(self):
        from memory.extraction.extractor import MemoryExtractor

        extractor = MemoryExtractor()
        captured = {}

        async def fake_complete(*, role, system_prompt, user_prompt, **kw):
            captured["user_prompt"] = user_prompt
            return '{"extractions": []}'

        with patch("memory.extraction.extractor.ai_router") as router:
            router.complete = AsyncMock(side_effect=fake_complete)
            await extractor.analyze_messages(
                [{"role": "user", "content": "salut"}],
                pending_commitments=[{"id": 7, "description": "Envoyer la playlist"}],
            )

        assert "ENGAGEMENTS EN COURS" in captured["user_prompt"]
        assert "[7] Envoyer la playlist" in captured["user_prompt"]

    @pytest.mark.asyncio
    async def test_no_block_without_commitments(self):
        from memory.extraction.extractor import MemoryExtractor

        extractor = MemoryExtractor()
        captured = {}

        async def fake_complete(*, role, system_prompt, user_prompt, **kw):
            captured["user_prompt"] = user_prompt
            return '{"extractions": []}'

        with patch("memory.extraction.extractor.ai_router") as router:
            router.complete = AsyncMock(side_effect=fake_complete)
            await extractor.analyze_messages([{"role": "user", "content": "salut"}])

        assert "ENGAGEMENTS EN COURS" not in captured["user_prompt"]
