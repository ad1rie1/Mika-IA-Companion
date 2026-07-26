"""Continuity across a restart.

Mika's mood toward a person survives a restart (EmotionSnapshot) and her
long-term memory lives on disk (ChromaDB) — but the short-term buffer that
feeds the LLM its conversation history was never read back from the DB, so a
restart mid-chat was total conversational amnesia. These tests pin the
rehydration and the conversation-resume window.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone


def _make_manager(limit=10, resume_minutes=120):
    from memory.manager import MemoryManager
    m = MemoryManager.__new__(MemoryManager)
    m.short_term = []
    m.max_short_term = limit
    m.resume_window_minutes = resume_minutes
    m.conversation = None
    m._initialized = False
    m.vector_store = None
    m.extractor = None
    m.consolidator = None
    m.retriever = None
    return m


async def _seed(*messages, age_minutes=1):
    """Create a conversation with (role, content) messages, aged in the past."""
    from memory.models import Conversation, Message

    conv = await sync_to_async(Conversation.objects.create)()
    stamp = timezone.now() - timedelta(minutes=age_minutes)
    for role, content, *rest in messages:
        internal = bool(rest and rest[0])
        m = await sync_to_async(Message.objects.create)(
            conversation=conv, role=role, content=content,
            source="frontend", is_internal=internal,
        )
        # auto_now_add ignores assignment; force the stamp.
        await sync_to_async(
            lambda pk=m.pk: type(m).objects.filter(pk=pk).update(created_at=stamp)
        )()
    return conv


@pytest.mark.django_db(transaction=True)
class TestRestartContinuity:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from memory.models import Conversation, Message
        Message.objects.all().delete()
        Conversation.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_recent_conversation_is_resumed(self):
        conv = await _seed(("user", "salut"), ("assistant", "coucou"))
        m = _make_manager()
        await m._resume_or_open_conversation()
        assert m.conversation.pk == conv.pk

    @pytest.mark.asyncio
    async def test_stale_conversation_starts_a_fresh_one(self):
        conv = await _seed(("user", "vieux message"), age_minutes=600)
        m = _make_manager()
        await m._resume_or_open_conversation()
        assert m.conversation.pk != conv.pk

    @pytest.mark.asyncio
    async def test_empty_db_opens_a_new_conversation(self):
        m = _make_manager()
        await m._resume_or_open_conversation()
        assert m.conversation is not None

    @pytest.mark.asyncio
    async def test_history_is_rehydrated_in_chronological_order(self):
        await _seed(
            ("user", "j'ai deux chats"),
            ("assistant", "ah oui ? comment ils s'appellent ?"),
            ("user", "et le deuxième s'appelle Mochi"),
        )
        m = _make_manager()
        await m._resume_or_open_conversation()
        await m._rehydrate_short_term()

        contents = [x["content"] for x in m.short_term]
        assert contents == [
            "j'ai deux chats",
            "ah oui ? comment ils s'appellent ?",
            "et le deuxième s'appelle Mochi",
        ]
        assert m.get_conversation_context() == m.short_term

    @pytest.mark.asyncio
    async def test_internal_scaffolding_is_not_rehydrated(self):
        await _seed(
            ("user", "Un visiteur vient de se connecter. Accueille-le.", True),
            ("assistant", "Oh, salut toi !"),
            ("user", "salut Mika"),
        )
        m = _make_manager()
        await m._resume_or_open_conversation()
        await m._rehydrate_short_term()

        contents = [x["content"] for x in m.short_term]
        assert "Oh, salut toi !" in contents
        assert "salut Mika" in contents
        assert not any("Accueille-le" in c for c in contents)

    @pytest.mark.asyncio
    async def test_rehydration_respects_the_short_term_limit(self):
        await _seed(*[("user", f"message {i}") for i in range(20)])
        m = _make_manager(limit=5)
        await m._resume_or_open_conversation()
        await m._rehydrate_short_term()

        assert len(m.short_term) == 5
        # The *tail* is what matters — the most recent turns.
        assert m.short_term[-1]["content"] == "message 19"

    @pytest.mark.asyncio
    async def test_fresh_conversation_rehydrates_to_empty(self):
        await _seed(("user", "vieux"), age_minutes=600)
        m = _make_manager()
        await m._resume_or_open_conversation()
        await m._rehydrate_short_term()
        assert m.short_term == []
