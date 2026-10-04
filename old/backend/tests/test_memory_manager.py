"""Tests for MemoryManager — short-term buffer, ORM operations, vector search."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from asgiref.sync import sync_to_async


def _make_manager(max_limit=10, initialized=False):
    from old.backend.memory.manager import MemoryManager
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
        # `divulgation` porte le niveau du tour jusqu'au rappel : sous le
        # seuil, `--- TES SOUVENIRS ---` ne doit pas servir les confidences
        # d'un tiers alors que le bloc « ce que tu sais de cette personne »
        # vient d'être fermé pour la même raison. Sans niveau : sa mémoire
        # entière (un appelant interne).
        from old.backend.identity.divulgation import TOUT
        mock_r.retrieve.assert_called_once_with(
            "parle-moi de ton chat", person_id="alice", divulgation=TOUT,
        )

    @pytest.mark.asyncio
    async def test_transmet_la_porte_de_divulgation_au_rappel(self):
        m = _make_manager()
        mock_r = MagicMock()
        mock_r.retrieve = AsyncMock(return_value="")
        m.retriever = mock_r
        from old.backend.identity.divulgation import FERME
        await m.get_memory_context("sante", person_id="web_inconnu",
                                   divulgation=FERME)
        assert mock_r.retrieve.call_args.kwargs["divulgation"] is FERME

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
        from old.backend.utils.degradation import degradations
        degradations.reset()
        yield
        degradations.reset()

    @pytest.mark.asyncio
    async def test_simple_recall_failure_is_counted_and_flagged(self):
        from old.backend.utils.degradation import degradations
        m = _make_manager()
        m.retriever = MagicMock()
        m.retriever.retrieve = AsyncMock(side_effect=Exception("chroma down"))

        assert await m.get_memory_context("test") == ""
        assert degradations.count_for("rappel memoire simple") == 1
        assert m.recall_unavailable is True

    @pytest.mark.asyncio
    async def test_multi_recall_failure_is_counted_and_flagged(self):
        from old.backend.utils.degradation import degradations
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
        from old.backend.utils.degradation import degradations
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
        from old.backend.memory.models import Souvenir
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
        from old.backend.memory.models import Souvenir
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
        from old.backend.memory.models import Souvenir
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
        from old.backend.memory.models import Souvenir
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
        from old.backend.memory.models import Connaissance
        c = await sync_to_async(Connaissance.objects.create)(content="Thomas aime les chats", confidence=0.9)
        m = _make_manager(initialized=True)
        await m.invalidate_connaissance(c.pk, reason="Contredit")
        updated = await sync_to_async(Connaissance.objects.get)(pk=c.pk)
        assert updated.is_valid is False

    @pytest.mark.asyncio
    async def test_reinforce_connaissance(self):
        from old.backend.memory.models import Connaissance
        c = await sync_to_async(Connaissance.objects.create)(content="Thomas aime le café", confidence=0.6)
        m = _make_manager(initialized=True)
        await m.reinforce_connaissance(c.pk, boost=0.2)
        updated = await sync_to_async(Connaissance.objects.get)(pk=c.pk)
        assert updated.confidence == pytest.approx(0.8)

    @pytest.mark.asyncio
    async def test_reinforce_capped_at_1(self):
        from old.backend.memory.models import Connaissance
        c = await sync_to_async(Connaissance.objects.create)(content="test", confidence=0.95)
        m = _make_manager(initialized=True)
        await m.reinforce_connaissance(c.pk, boost=0.2)
        updated = await sync_to_async(Connaissance.objects.get)(pk=c.pk)
        assert updated.confidence == 1.0

    @pytest.mark.asyncio
    async def test_update_confidence(self):
        from old.backend.memory.models import Connaissance
        c = await sync_to_async(Connaissance.objects.create)(content="test", confidence=0.5)
        m = _make_manager(initialized=True)
        await m.update_connaissance_confidence(c.pk, 0.75)
        updated = await sync_to_async(Connaissance.objects.get)(pk=c.pk)
        assert updated.confidence == pytest.approx(0.75)

    @pytest.mark.asyncio
    async def test_get_valid_connaissance(self):
        from old.backend.memory.models import Connaissance
        c = await sync_to_async(Connaissance.objects.create)(content="valid fact", confidence=0.8, is_valid=True)
        m = _make_manager(initialized=True)
        result = await m.get_valid_connaissance(c.pk)
        assert result is not None
        assert result.content == "valid fact"

    @pytest.mark.asyncio
    async def test_get_valid_connaissance_returns_none_if_invalid(self):
        from old.backend.memory.models import Connaissance
        c = await sync_to_async(Connaissance.objects.create)(content="stale fact", confidence=0.8, is_valid=False)
        m = _make_manager(initialized=True)
        result = await m.get_valid_connaissance(c.pk)
        assert result is None


# ===================================================================
# Arrêt : la boucle AVANT la passe finale
# ===================================================================

class TestArretDuConsolidateur:

    @pytest.mark.asyncio
    async def test_la_boucle_est_arretee_avant_la_passe_finale(self):
        """`stop()` attend un tick en cours ; la passe forcée ne trouve alors
        que ce qui est arrivé depuis. Dans l'autre ordre, elle relisait la
        fenêtre que le tick était en train d'extraire."""
        m = _make_manager(initialized=True)
        m.compactor = None
        m.episodic = None
        ordre = []
        m.consolidator = MagicMock()
        m.consolidator.stop = AsyncMock(side_effect=lambda: ordre.append("stop"))
        m.consolidator.force_consolidate = AsyncMock(
            side_effect=lambda: ordre.append("force"))

        await m.shutdown()

        assert ordre == ["stop", "force"]


# ===================================================================
# Ré-index après écriture d'importance — la métadonnée ChromaDB est le
# filtre du rappel, et seule la passe de décroissance la maintenait.
# ===================================================================

class _MagasinSimule:
    """Un ChromaDB de poche : mémorise les métadonnées et applique le même
    pré-filtre ``importance >= min_importance`` que ``search_souvenirs``."""

    def __init__(self):
        self.meta: dict[int, dict] = {}
        self.contenus: dict[int, str] = {}

    def add_souvenir(self, souvenir_id, content, metadata=None):
        self.meta[int(souvenir_id)] = dict(metadata or {})
        self.contenus[int(souvenir_id)] = content

    def add_souvenirs(self, entries):
        for e in entries:
            self.add_souvenir(e["souvenir_id"], e["content"], e.get("metadata"))

    def remove_souvenir(self, souvenir_id):
        self.meta.pop(int(souvenir_id), None)
        self.contenus.pop(int(souvenir_id), None)

    def search_souvenirs(self, query, n=5, min_importance=0.3):
        return [
            {"id": str(pk), "content": self.contenus[pk], "distance": 0.1,
             "metadata": dict(meta)}
            for pk, meta in self.meta.items()
            if meta.get("importance", 0.0) >= min_importance
        ][:n]

    def search_connaissances(self, query, n=10):
        return []


@pytest.mark.django_db(transaction=True)
class TestReindexApresEcritureDImportance:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from old.backend.memory.models import Souvenir, Theme
        Souvenir.objects.all().delete()
        Theme.objects.all().delete()
        yield

    _CFG = {
        "memory.retrieval_souvenirs": 5,
        "memory.retrieval_connaissances": 5,
        "memory.min_importance": 0.3,
        "memory.retrieval_fetch_multiplier": 3,
        "memory.retrieval_exchanges": 0,
        "memory.assoc_expansion_enabled": False,
        "memory.intrusion_enabled": False,
    }

    async def _endormi(self, magasin, content="Thomas m'a annoncé qu'il se marie"):
        from django.utils import timezone

        from old.backend.memory.models import Souvenir
        s = await Souvenir.objects.acreate(
            content=content, emotion="happy", importance=0.02,
            occurred_at=timezone.now(),
        )
        magasin.add_souvenir(s.pk, s.content, {"importance": 0.02, "emotion": "happy"})
        return s

    @staticmethod
    def _manager(magasin):
        from old.backend.memory.retrieval.retriever import MemoryRetriever
        m = _make_manager(initialized=True)
        m.vector_store = magasin
        m.retriever = MemoryRetriever(magasin)
        return m

    async def _rappel(self, m, question="mariage"):
        with patch("configs.service.config_service.get",
                   lambda k, *a, **kw: self._CFG.get(k, kw.get("default", 0))):
            return await m.get_memory_context(question)

    @pytest.mark.asyncio
    async def test_un_souvenir_endormi_ranime_par_la_conscience_revient_au_rappel(self):
        """Le boost n'écrivait que la ligne ORM : le vecteur gardait 0.02 et
        le souvenir restait invisible au rappel spontané — précisément ce que
        le boost promettait de défaire."""
        magasin = _MagasinSimule()
        s = await self._endormi(magasin)
        m = self._manager(magasin)
        assert "marie" not in await self._rappel(m)   # endormi : hors rappel

        await m.boost_souvenir(s.pk, 0.6)

        assert magasin.meta[s.pk]["importance"] == pytest.approx(0.62)
        assert "marie" in await self._rappel(m)

    @pytest.mark.asyncio
    async def test_le_reindex_garde_emotion_et_themes(self):
        """Un upsert remplace les métadonnées EN ENTIER : ré-indexer sans
        `emotion` ni `themes` les effacerait."""
        from old.backend.memory.models import Theme
        magasin = _MagasinSimule()
        s = await self._endormi(magasin)
        theme = await Theme.objects.acreate(name="mariage")
        await sync_to_async(s.themes.add)(theme)
        m = self._manager(magasin)

        await m.boost_souvenir(s.pk, 0.5)

        assert magasin.meta[s.pk]["emotion"] == "happy"
        assert magasin.meta[s.pk]["themes"] == "mariage"

    @pytest.mark.asyncio
    async def test_la_reduction_et_le_boost_par_theme_reindexent_aussi(self):
        from old.backend.memory.models import Theme
        magasin = _MagasinSimule()
        s = await self._endormi(magasin)
        theme = await Theme.objects.acreate(name="mariage")
        await sync_to_async(s.themes.add)(theme)
        m = self._manager(magasin)

        assert await m.boost_souvenirs_by_themes(["mariage"], boost=0.5) == 1
        assert magasin.meta[s.pk]["importance"] == pytest.approx(0.52)

        await m.reduce_souvenir(s.pk, 0.3)
        assert magasin.meta[s.pk]["importance"] == pytest.approx(0.22)

    @pytest.mark.asyncio
    async def test_un_magasin_en_panne_ne_coute_que_le_reindex(self):
        """Best-effort : la ligne ORM reste la vérité, la panne est comptée."""
        from old.backend.memory.models import Souvenir
        from old.backend.utils.degradation import degradations

        degradations.reset()
        magasin = _MagasinSimule()
        s = await self._endormi(magasin)
        magasin.add_souvenirs = MagicMock(side_effect=RuntimeError("chroma"))
        m = self._manager(magasin)

        await m.boost_souvenir(s.pk, 0.5)

        assert (await Souvenir.objects.aget(pk=s.pk)).importance == pytest.approx(0.52)
        assert degradations.count_for("memoire: reindex apres ecriture d'importance") == 1
        degradations.reset()

    @pytest.mark.asyncio
    async def test_la_fusion_nocturne_reindexe_le_gagnant(self, monkeypatch):
        """Le gagnant prend max + 0.05 ; son vecteur doit le savoir."""
        from datetime import date

        from django.utils import timezone

        import old.backend.memory.manager as manager_mod
        from old.backend.memory.models import Souvenir
        from old.backend.memory.reorg import NightlyReorg

        a = await Souvenir.objects.acreate(
            content="Thomas adore son chat", importance=0.8, occurred_at=timezone.now())
        b = await Souvenir.objects.acreate(
            content="Thomas aime beaucoup son chat", importance=0.2,
            occurred_at=timezone.now())

        class Magasin(_MagasinSimule):
            def search_souvenirs(self, content, n=3, min_importance=0.0):
                return [{"id": str(a.pk), "distance": 0.0},
                        {"id": str(b.pk), "distance": 0.05}]

        magasin = Magasin()
        magasin.add_souvenir(a.pk, a.content, {"importance": 0.8})
        magasin.add_souvenir(b.pk, b.content, {"importance": 0.2})
        monkeypatch.setattr(manager_mod.memory_manager, "vector_store", magasin)

        assert await NightlyReorg()._dedup_souvenirs(date.today()) == 1

        assert b.pk not in magasin.meta
        assert magasin.meta[a.pk]["importance"] == pytest.approx(0.85)
