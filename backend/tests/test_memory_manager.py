"""Tests for MemoryManager — short-term buffer, ORM operations, vector search."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from asgiref.sync import sync_to_async


def _make_manager(max_limit=10, initialized=False):
    from memory.manager import MemoryManager
    m = MemoryManager.__new__(MemoryManager)
    m.short_term = []
    m.max_short_term = max_limit
    m.conversation = None
    m._initialized = initialized
    m.vector_store = None
    m.extractor = None
    m.consolidator = None
    m.retriever = None
    m.recall_unavailable = False
    return m


# ===================================================================
# Short-term buffer (no DB)
# ===================================================================

class TestShortTermBuffer:

    @pytest.mark.asyncio
    async def test_add_message_appends(self):
        m = _make_manager()
        await m.add_message("user", "Salut !")
        assert m.short_term == [
            {"role": "user", "content": "Salut !", "person_id": ""}
        ]

    @pytest.mark.asyncio
    async def test_add_message_caps_at_max(self):
        m = _make_manager(max_limit=3)
        for i in range(5):
            await m.add_message("user", f"msg {i}")
        assert len(m.short_term) == 3
        assert m.short_term[-1]["content"] == "msg 4"

    def test_get_conversation_context_returns_copy(self):
        m = _make_manager()
        m.short_term = [{"role": "user", "content": "hi"}]
        result = m.get_conversation_context()
        assert result == [{"role": "user", "content": "hi"}]
        result.append({"role": "assistant", "content": "hey"})
        assert len(m.short_term) == 1  # original not affected

    def test_clear_short_term(self):
        m = _make_manager()
        m.short_term = [{"role": "user", "content": "x"}]
        m.clear_short_term()
        assert m.short_term == []


# ===================================================================
# get_memory_context
# ===================================================================

class TestGetMemoryContext:

    @pytest.mark.asyncio
    async def test_no_retriever_returns_empty(self):
        m = _make_manager()
        assert await m.get_memory_context("test") == ""

    @pytest.mark.asyncio
    async def test_calls_retriever(self):
        m = _make_manager()
        mock_r = MagicMock()
        mock_r.retrieve = AsyncMock(return_value="Souvenir: chats")
        m.retriever = mock_r
        result = await m.get_memory_context("parle-moi de ton chat", person_id="alice")
        assert result == "Souvenir: chats"
        # `disclose_others` porte la porte de divulgation jusqu'au rappel : sous
        # le seuil, `--- TES SOUVENIRS ---` ne doit pas servir les confidences
        # d'un tiers alors que le bloc « ce que tu sais de cette personne »
        # vient d'être fermé pour la même raison. Par défaut, ouverte.
        mock_r.retrieve.assert_called_once_with(
            "parle-moi de ton chat", person_id="alice", disclose_others=True,
        )

    @pytest.mark.asyncio
    async def test_transmet_la_porte_de_divulgation_au_rappel(self):
        m = _make_manager()
        mock_r = MagicMock()
        mock_r.retrieve = AsyncMock(return_value="")
        m.retriever = mock_r
        await m.get_memory_context("sante", person_id="web_inconnu",
                                   disclose_others=False)
        assert mock_r.retrieve.call_args.kwargs["disclose_others"] is False

    @pytest.mark.asyncio
    async def test_retriever_error_returns_empty(self):
        m = _make_manager()
        mock_r = MagicMock()
        mock_r.retrieve = AsyncMock(side_effect=Exception("DB error"))
        m.retriever = mock_r
        assert await m.get_memory_context("test") == ""


# ===================================================================
# Une mémoire longue en panne rend un bloc vide, indistinguable de « rien à
# dire » : la panne était donc invisible, indéfiniment, avec la page santé au
# vert. On compte, et on expose un drapeau lisible par la couche prompt — sans
# changer le flux : un rappel raté ne coûte toujours sa réponse à personne.
# ===================================================================

class TestRappelIndisponible:

    @pytest.fixture(autouse=True)
    def _ledger(self):
        from utils.degradation import degradations
        degradations.reset()
        yield
        degradations.reset()

    @pytest.mark.asyncio
    async def test_simple_recall_failure_is_counted_and_flagged(self):
        from utils.degradation import degradations
        m = _make_manager()
        m.retriever = MagicMock()
        m.retriever.retrieve = AsyncMock(side_effect=Exception("chroma down"))

        assert await m.get_memory_context("test") == ""
        assert degradations.count_for("rappel memoire simple") == 1
        assert m.recall_unavailable is True

    @pytest.mark.asyncio
    async def test_multi_recall_failure_is_counted_and_flagged(self):
        from utils.degradation import degradations
        m = _make_manager()
        m.retriever = MagicMock()
        m.retriever.retrieve_multi = AsyncMock(side_effect=Exception("chroma down"))

        assert await m.get_memory_context_multi(["test"]) == ""
        assert degradations.count_for("rappel memoire multi") == 1
        assert m.recall_unavailable is True

    @pytest.mark.asyncio
    async def test_a_successful_recall_clears_the_flag(self):
        """Sinon le drapeau est un cliquet et la ligne de prompt reste à vie."""
        m = _make_manager()
        m.retriever = MagicMock()
        m.retriever.retrieve = AsyncMock(side_effect=Exception("chroma down"))
        await m.get_memory_context("test")
        assert m.recall_unavailable is True

        m.retriever.retrieve = AsyncMock(return_value="Souvenir: chats")
        assert await m.get_memory_context("test") == "Souvenir: chats"
        assert m.recall_unavailable is False

    @pytest.mark.asyncio
    async def test_no_retriever_is_an_absence_not_a_failure(self):
        from utils.degradation import degradations
        m = _make_manager()
        assert await m.get_memory_context("test") == ""
        assert m.recall_unavailable is True
        assert degradations.total() == 0


# ===================================================================
# Vector search (no vector_store = [])
# ===================================================================

class TestVectorSearch:

    @pytest.mark.asyncio
    async def test_search_souvenirs_no_store(self):
        m = _make_manager()
        assert await m.search_related_souvenirs("test") == []

    @pytest.mark.asyncio
    async def test_search_connaissances_no_store(self):
        m = _make_manager()
        assert await m.search_related_connaissances("test") == []


# ===================================================================
# Souvenir ORM operations (Django DB)
# ===================================================================

@pytest.mark.django_db
class TestSouvenirORM:

    @pytest.mark.asyncio
    async def test_boost_souvenir_increases_importance(self):
        from memory.models import Souvenir
        from django.utils import timezone
        s = await sync_to_async(Souvenir.objects.create)(
            content="test", emotion="happy", importance=0.5, occurred_at=timezone.now()
        )
        m = _make_manager(initialized=True)
        await m.boost_souvenir(s.pk, 0.2)
        updated = await sync_to_async(Souvenir.objects.get)(pk=s.pk)
        assert updated.importance == pytest.approx(0.7)

    @pytest.mark.asyncio
    async def test_boost_souvenir_capped_at_1(self):
        from memory.models import Souvenir
        from django.utils import timezone
        s = await sync_to_async(Souvenir.objects.create)(
            content="test", emotion="happy", importance=0.9, occurred_at=timezone.now()
        )
        m = _make_manager(initialized=True)
        await m.boost_souvenir(s.pk, 0.5)
        updated = await sync_to_async(Souvenir.objects.get)(pk=s.pk)
        assert updated.importance == 1.0

    @pytest.mark.asyncio
    async def test_reduce_souvenir_decreases_importance(self):
        from memory.models import Souvenir
        from django.utils import timezone
        s = await sync_to_async(Souvenir.objects.create)(
            content="test", emotion="happy", importance=0.5, occurred_at=timezone.now()
        )
        m = _make_manager(initialized=True)
        await m.reduce_souvenir(s.pk, 0.2)
        updated = await sync_to_async(Souvenir.objects.get)(pk=s.pk)
        assert updated.importance == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_reduce_souvenir_floored_at_0(self):
        from memory.models import Souvenir
        from django.utils import timezone
        s = await sync_to_async(Souvenir.objects.create)(
            content="test", emotion="happy", importance=0.1, occurred_at=timezone.now()
        )
        m = _make_manager(initialized=True)
        await m.reduce_souvenir(s.pk, 0.5)
        updated = await sync_to_async(Souvenir.objects.get)(pk=s.pk)
        assert updated.importance == 0.0

    @pytest.mark.asyncio
    async def test_boost_nonexistent_souvenir_no_exception(self):
        m = _make_manager(initialized=True)
        await m.boost_souvenir(99999, 0.1)  # should not raise


# ===================================================================
# Connaissance ORM operations (Django DB)
# ===================================================================

@pytest.mark.django_db
class TestConnaissanceORM:

    @pytest.mark.asyncio
    async def test_invalidate_connaissance(self):
        from memory.models import Connaissance
        c = await sync_to_async(Connaissance.objects.create)(content="Thomas aime les chats", confidence=0.9)
        m = _make_manager(initialized=True)
        await m.invalidate_connaissance(c.pk, reason="Contredit")
        updated = await sync_to_async(Connaissance.objects.get)(pk=c.pk)
        assert updated.is_valid is False

    @pytest.mark.asyncio
    async def test_reinforce_connaissance(self):
        from memory.models import Connaissance
        c = await sync_to_async(Connaissance.objects.create)(content="Thomas aime le café", confidence=0.6)
        m = _make_manager(initialized=True)
        await m.reinforce_connaissance(c.pk, boost=0.2)
        updated = await sync_to_async(Connaissance.objects.get)(pk=c.pk)
        assert updated.confidence == pytest.approx(0.8)

    @pytest.mark.asyncio
    async def test_reinforce_capped_at_1(self):
        from memory.models import Connaissance
        c = await sync_to_async(Connaissance.objects.create)(content="test", confidence=0.95)
        m = _make_manager(initialized=True)
        await m.reinforce_connaissance(c.pk, boost=0.2)
        updated = await sync_to_async(Connaissance.objects.get)(pk=c.pk)
        assert updated.confidence == 1.0

    @pytest.mark.asyncio
    async def test_update_confidence(self):
        from memory.models import Connaissance
        c = await sync_to_async(Connaissance.objects.create)(content="test", confidence=0.5)
        m = _make_manager(initialized=True)
        await m.update_connaissance_confidence(c.pk, 0.75)
        updated = await sync_to_async(Connaissance.objects.get)(pk=c.pk)
        assert updated.confidence == pytest.approx(0.75)

    @pytest.mark.asyncio
    async def test_get_valid_connaissance(self):
        from memory.models import Connaissance
        c = await sync_to_async(Connaissance.objects.create)(content="valid fact", confidence=0.8, is_valid=True)
        m = _make_manager(initialized=True)
        result = await m.get_valid_connaissance(c.pk)
        assert result is not None
        assert result.content == "valid fact"

    @pytest.mark.asyncio
    async def test_get_valid_connaissance_returns_none_if_invalid(self):
        from memory.models import Connaissance
        c = await sync_to_async(Connaissance.objects.create)(content="stale fact", confidence=0.8, is_valid=False)
        m = _make_manager(initialized=True)
        result = await m.get_valid_connaissance(c.pk)
        assert result is None
