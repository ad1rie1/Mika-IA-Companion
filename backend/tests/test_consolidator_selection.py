"""Tests for which messages the consolidator feeds to the extractor.

Two invariants:
  - Internal scaffolding ("Un visiteur vient de se connecter, accueille-le...")
    is never mined for souvenirs — Mika never heard those words from anyone.
    Her *reply* to it is a genuine memory and stays included.
  - The checkpoint never advances past a message that was not extracted.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from asgiref.sync import sync_to_async


def _make_consolidator(last_id=0):
    from memory.storage.consolidator import MemoryConsolidator
    c = MemoryConsolidator.__new__(MemoryConsolidator)
    c.vector_store = MagicMock()
    c.extractor = MagicMock()
    c.extractor.analyze_messages = AsyncMock(return_value=[])
    c._last_processed_id = last_id
    return c


async def _make_conversation():
    from memory.models import Conversation
    return await sync_to_async(Conversation.objects.create)()


@pytest.mark.django_db(transaction=True)
class TestMessageSelection:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from memory.models import Conversation, Message
        Message.objects.all().delete()
        Conversation.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_internal_user_prompt_excluded_reply_kept(self):
        from memory.models import Message

        conv = await _make_conversation()
        await sync_to_async(Message.objects.create)(
            conversation=conv, role="user", source="web_connect",
            content="Un visiteur vient de se connecter. Accueille-le.",
            is_internal=True,
        )
        await sync_to_async(Message.objects.create)(
            conversation=conv, role="assistant", source="web_connect",
            content="Oh, salut toi !",
        )

        c = _make_consolidator()
        await c._consolidate()

        c.extractor.analyze_messages.assert_awaited_once()
        sent = c.extractor.analyze_messages.await_args[0][0]
        contents = [m["content"] for m in sent]
        assert "Oh, salut toi !" in contents
        assert not any("Accueille-le" in x for x in contents)

    @pytest.mark.asyncio
    async def test_ordinary_user_message_still_included(self):
        from memory.models import Message

        conv = await _make_conversation()
        await sync_to_async(Message.objects.create)(
            conversation=conv, role="user", source="frontend",
            content="J'ai adopté un chat aujourd'hui",
        )

        c = _make_consolidator()
        await c._consolidate()

        sent = c.extractor.analyze_messages.await_args[0][0]
        assert any("chat" in m["content"] for m in sent)


@pytest.mark.django_db(transaction=True)
class TestCheckpointNeverSkips:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from memory.models import ConsolidationLog, Conversation, Message
        Message.objects.all().delete()
        ConsolidationLog.objects.all().delete()
        Conversation.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_message_arriving_mid_pass_is_not_skipped(self):
        """A turn persisted while consolidation runs must be picked up next time.

        The ceiling is read before the messages, so a row created after that
        read stays above the checkpoint instead of being counted by it.
        """
        from memory.models import Message

        conv = await _make_conversation()
        first = await sync_to_async(Message.objects.create)(
            conversation=conv, role="user", source="frontend",
            content="premier message",
        )

        c = _make_consolidator()

        # Simulate a chat turn landing between the ceiling query and the
        # message query by inserting from inside the extractor call.
        late_id = {}

        async def _insert_then_return(msgs):
            m = await sync_to_async(Message.objects.create)(
                conversation=conv, role="user", source="frontend",
                content="message arrivé pendant la passe",
            )
            late_id["pk"] = m.pk
            return []

        c.extractor.analyze_messages = AsyncMock(side_effect=_insert_then_return)
        await c._consolidate()

        assert c._last_processed_id == first.pk
        assert c._last_processed_id < late_id["pk"]

        # Next pass picks the late message up.
        c.extractor.analyze_messages = AsyncMock(return_value=[])
        await c._consolidate()
        sent = c.extractor.analyze_messages.await_args[0][0]
        assert any("pendant la passe" in m["content"] for m in sent)
