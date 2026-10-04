"""Compaction conversationnelle — watermarks, checkpoint, repli sans perte.

Les propriétés défendues : on ne replie jamais ce qui n'a pas été extrait
(checkpoint du consolidateur), jamais les N derniers messages (plancher de
récence), jamais sur un échec LLM (no-op, retry) ; et le trim du buffer ne
suit qu'une écriture réussie du résumé.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from old.backend.ai.chat import SUMMARY_HEADER, SUMMARY_MAX_CHARS, ChatPrompt
from old.backend.memory.compaction import ConversationCompactor


def _compactor():
    c = ConversationCompactor.__new__(ConversationCompactor)
    c.interval = 120
    return c


def _buffer(n, size=200, start_id=1):
    return [
        {"id": start_id + i, "role": "user" if i % 2 == 0 else "assistant",
         "content": "x" * size}
        for i in range(n)
    ]


class TestSelectFoldSlice:

    def test_folds_oldest_until_the_low_watermark(self):
        c = _compactor()
        buf = _buffer(40, size=1000)
        fold = c._select_fold_slice(
            buf, checkpoint=10_000, keep_last=10,
            measured=40_000, low=20_000,
        )
        assert fold  # replie au moins les plus anciens
        assert fold[0]["id"] == 1
        assert len(fold) < 30  # jamais dans le plancher de récence

    def test_never_beyond_the_extraction_checkpoint(self):
        c = _compactor()
        buf = _buffer(40, size=1000)
        fold = c._select_fold_slice(
            buf, checkpoint=5, keep_last=10, measured=40_000, low=0,
        )
        assert [m["id"] for m in fold] == [1, 2, 3, 4, 5]

    def test_an_entry_without_id_stops_the_slice(self):
        c = _compactor()
        buf = _buffer(10, size=1000)
        del buf[3]["id"]
        fold = c._select_fold_slice(
            buf, checkpoint=10_000, keep_last=2, measured=10_000, low=0,
        )
        assert [m["id"] for m in fold] == [1, 2, 3]

    def test_checkpoint_lag_folds_nothing(self):
        c = _compactor()
        fold = c._select_fold_slice(
            _buffer(40), checkpoint=0, keep_last=10, measured=99_999, low=0,
        )
        assert fold == []


class TestPlancherDeSanite:
    """Un refus d'une phrase remplaçait des semaines de contexte compressé —
    et comme le curseur avance dans la foulée, la matière repliée n'était
    jamais re-résumée."""

    def test_le_plancher_est_calcule_sur_l_ancien_et_sur_la_matiere(self):
        floor = ConversationCompactor._summary_floor
        assert floor("x" * 4000, 0) == 1400          # 35 % de l'ancien
        assert floor("", 10_000) == 200              # 2 % de la matière repliée
        assert floor("", 0) == 120                   # plancher absolu

    async def test_un_resume_honnete_passe(self):
        c = _compactor()
        fold = _buffer(40, size=2000)
        with patch("ai.router.ai_router.complete",
                   new_callable=AsyncMock, return_value="r" * 2500):
            assert await c._summarize("a" * 4000, fold) == "r" * 2500

    async def test_le_premier_repli_sans_ancien_resume_reste_possible(self):
        c = _compactor()
        fold = _buffer(5, size=200)
        with patch("ai.router.ai_router.complete",
                   new_callable=AsyncMock, return_value="s" * 800):
            assert await c._summarize("", fold) == "s" * 800


class TestCompactIfNeeded:

    def _manager_stub(self, buffer, summary=""):
        stub = MagicMock()
        stub.conversation = object()
        stub.get_conversation_context = MagicMock(return_value=buffer)
        stub.get_conversation_summary = MagicMock(return_value=summary)
        stub.fold_into_summary = AsyncMock(return_value=True)
        return stub

    async def test_un_refus_d_une_phrase_ne_remplace_pas_le_resume(self, monkeypatch):
        import old.backend.memory.manager as manager_mod
        from old.backend.utils.degradation import degradations

        degradations.reset()
        c = _compactor()
        stub = self._manager_stub(_buffer(50, size=2000), summary="a" * 4000)
        monkeypatch.setattr(manager_mod, "memory_manager", stub)
        monkeypatch.setattr(c, "_high_watermark_chars", lambda: 10_000)
        monkeypatch.setattr(c, "_keep_last", lambda: 10)
        c._extraction_checkpoint = AsyncMock(return_value=10_000)

        with patch("ai.router.ai_router.complete", new_callable=AsyncMock,
                   return_value="Je ne peux pas resumer cela."):
            assert await c.compact_if_needed() is False

        stub.fold_into_summary.assert_not_called()
        assert degradations.count_for("compaction: resume degenere") == 1
        degradations.reset()

    async def test_a_full_pass_folds_and_reports(self, monkeypatch):
        import old.backend.memory.manager as manager_mod

        c = _compactor()
        buf = _buffer(50, size=2000)
        stub = self._manager_stub(buf)
        monkeypatch.setattr(manager_mod, "memory_manager", stub)
        monkeypatch.setattr(c, "_high_watermark_chars", lambda: 10_000)
        monkeypatch.setattr(c, "_keep_last", lambda: 10)
        c._extraction_checkpoint = AsyncMock(return_value=10_000)
        c._summarize = AsyncMock(return_value="le fil résumé")

        assert await c.compact_if_needed() is True
        args = stub.fold_into_summary.call_args.args
        assert args[0] == "le fil résumé"
        assert isinstance(args[1], int) and args[1] >= 1

    async def test_under_the_watermark_does_nothing(self, monkeypatch):
        import old.backend.memory.manager as manager_mod

        c = _compactor()
        stub = self._manager_stub(_buffer(50, size=10))
        monkeypatch.setattr(manager_mod, "memory_manager", stub)
        monkeypatch.setattr(c, "_high_watermark_chars", lambda: 100_000)
        monkeypatch.setattr(c, "_keep_last", lambda: 10)
        assert await c.compact_if_needed() is False
        stub.fold_into_summary.assert_not_called()

    async def test_llm_failure_is_a_noop(self, monkeypatch):
        import old.backend.memory.manager as manager_mod

        c = _compactor()
        stub = self._manager_stub(_buffer(50, size=2000))
        monkeypatch.setattr(manager_mod, "memory_manager", stub)
        monkeypatch.setattr(c, "_high_watermark_chars", lambda: 10_000)
        monkeypatch.setattr(c, "_keep_last", lambda: 10)
        c._extraction_checkpoint = AsyncMock(return_value=10_000)
        c._summarize = AsyncMock(return_value=None)
        assert await c.compact_if_needed() is False
        stub.fold_into_summary.assert_not_called()


@pytest.mark.django_db(transaction=True)
class TestFoldIntoSummary:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from old.backend.memory.models import Conversation, ConversationSummary, Message
        Message.objects.all().delete()
        ConversationSummary.objects.all().delete()
        Conversation.objects.all().delete()
        yield

    def _manager(self, conversation):
        from old.backend.memory.manager import MemoryManager
        m = MemoryManager.__new__(MemoryManager)
        m.short_term = []
        m.max_short_term = 500
        m.conversation = conversation
        m.conversation_summary = ""
        m._initialized = True
        return m

    async def test_upserts_then_trims_only_folded_entries(self):
        from old.backend.memory.models import Conversation, ConversationSummary

        conv = await Conversation.objects.acreate()
        m = self._manager(conv)
        m.short_term = [
            {"id": 1, "role": "user", "content": "vieux"},
            {"id": 2, "role": "assistant", "content": "vieux aussi"},
            {"id": 3, "role": "user", "content": "récent"},
            {"role": "user", "content": "jamais persisté"},
        ]
        assert await m.fold_into_summary("résumé du début", 2) is True
        assert m.conversation_summary == "résumé du début"
        assert [e.get("content") for e in m.short_term] == ["récent", "jamais persisté"]
        row = await ConversationSummary.objects.aget(conversation=conv)
        assert row.last_message_id == 2

    async def test_failed_write_keeps_the_buffer_intact(self):
        from old.backend.memory.models import Conversation

        conv = await Conversation.objects.acreate()
        m = self._manager(conv)
        m.short_term = [{"id": 1, "role": "user", "content": "a"}]
        with patch("memory.models.ConversationSummary.objects.update_or_create",
                   side_effect=RuntimeError("db locked")):
            assert await m.fold_into_summary("x", 1) is False
        assert m.conversation_summary == ""
        assert len(m.short_term) == 1

    async def test_rehydration_resumes_after_the_summary(self):
        from old.backend.memory.models import Conversation, ConversationSummary, Message

        conv = await Conversation.objects.acreate()
        for content in ["a", "b", "c"]:
            await Message.objects.acreate(conversation=conv, role="user", content=content)
        last_b = await Message.objects.aget(content="b")
        await ConversationSummary.objects.acreate(
            conversation=conv, content="résumé a+b", last_message_id=last_b.pk,
        )
        m = self._manager(conv)
        await m._rehydrate_short_term()
        assert [e["content"] for e in m.short_term] == ["c"]
        assert m.conversation_summary == "résumé a+b"


class TestSummaryRendering:

    def test_summary_is_the_first_user_message(self):
        prompt = ChatPrompt(
            system_stable="S",
            history=[{"role": "assistant", "content": "re-coucou"}],
            message="suite",
            conversation_summary="ce qui s'est dit avant",
        )
        msgs = prompt.chat_messages()
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"].startswith(SUMMARY_HEADER)
        # Le résumé EST un premier tour user : pas de marqueur de reprise.
        assert "[Reprise de la conversation.]" not in [m["content"] for m in msgs]

    def test_summary_is_clipped_by_the_belt(self):
        prompt = ChatPrompt(
            system_stable="S", message="m",
            conversation_summary="s" * (SUMMARY_MAX_CHARS * 2),
        )
        content = prompt.chat_messages()[0]["content"]
        assert len(content) <= SUMMARY_MAX_CHARS + len(SUMMARY_HEADER) + 1

    def test_legacy_pair_carries_the_summary_too(self):
        prompt = ChatPrompt(
            system_stable="S", message="m", conversation_summary="avant",
        )
        _, flat = prompt.legacy_pair()
        assert flat.startswith(f"User: {SUMMARY_HEADER}\navant")

    def test_claude_breakpoints_are_unchanged_with_a_summary(self):
        """Le résumé vit dans la zone messages cacheable ; le breakpoint
        mobile reste sur le dernier tour d'historique."""
        from old.backend.ai.providers.claude import ClaudeProvider

        provider = ClaudeProvider.__new__(ClaudeProvider)
        prompt = ChatPrompt(
            system_stable="S",
            history=[{"role": "user", "content": "a"},
                     {"role": "assistant", "content": "b"}],
            message="c",
            conversation_summary="résumé",
        )
        system, messages = provider._chat_payload(prompt)
        assert system[0]["cache_control"] == {"type": "ephemeral"}
        # messages: [résumé, a, b, final] — marker sur l'avant-dernier (b).
        assert messages[0]["content"][0]["text"].startswith(SUMMARY_HEADER)
        assert "cache_control" in messages[-2]["content"][0]
        assert "cache_control" not in messages[0]["content"][0]
        assert isinstance(messages[-1]["content"], str)
