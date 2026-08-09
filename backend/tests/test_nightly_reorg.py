"""Réorganisation nocturne — clustering, extraction par thème, dédoublonnage."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from memory.reorg import NightlyReorg, _cluster_greedy


def _chunk(cid, embedding, ts=0.0, content="Lui: x\nMika: y", handle="web_a",
           first=1, last=2):
    return {
        "id": cid,
        "content": content,
        "embedding": embedding,
        "metadata": {
            "ts": ts, "handle": handle, "conversation_id": 1,
            "first_message_id": first, "last_message_id": last,
        },
    }


class TestClustering:

    def test_similar_chunks_join_the_same_cluster(self):
        clusters = _cluster_greedy([
            _chunk("1", [1.0, 0.0, 0.0], ts=1),
            _chunk("2", [0.99, 0.05, 0.0], ts=2),
            _chunk("3", [0.0, 1.0, 0.0], ts=3),
        ], threshold=0.8)
        sizes = sorted(len(c) for c in clusters)
        assert sizes == [1, 2]

    def test_deterministic_by_ts_order(self):
        chunks = [
            _chunk("b", [0.0, 1.0], ts=2),
            _chunk("a", [1.0, 0.0], ts=1),
        ]
        clusters = _cluster_greedy(chunks, threshold=0.8)
        # Premier cluster = premier chunk chronologique.
        assert clusters[0][0]["id"] == "a"

    def test_chunks_without_embedding_are_skipped(self):
        clusters = _cluster_greedy([_chunk("1", None)], threshold=0.5)
        assert clusters == []


@pytest.mark.django_db(transaction=True)
class TestDedup:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from conscience.models import Observation
        from memory.models import Commitment, Souvenir
        Observation.objects.all().delete()
        Commitment.objects.all().delete()
        Souvenir.objects.all().delete()
        yield

    async def test_merge_keeps_the_important_one_and_repoints(self):
        from django.utils import timezone

        from conscience.models import Observation
        from memory.models import Souvenir

        keeper = await Souvenir.objects.acreate(
            content="Thomas adore son chat", importance=0.9,
            occurred_at=timezone.now(),
        )
        loser = await Souvenir.objects.acreate(
            content="Thomas aime beaucoup son chat", importance=0.4,
            occurred_at=timezone.now(),
        )
        obs = await Observation.objects.acreate(
            source="web", event_type="chat.message", summary="s",
            souvenir=loser,
        )

        reorg = NightlyReorg()
        removed = await reorg._merge_pair(keeper.pk, loser.pk)
        assert removed == loser.pk
        assert not await Souvenir.objects.filter(pk=loser.pk).aexists()
        await obs.arefresh_from_db()
        assert obs.souvenir_id == keeper.pk
        await keeper.arefresh_from_db()
        assert keeper.importance == pytest.approx(0.95)

    async def test_dedup_pass_merges_close_pairs_and_prunes_chroma(self, monkeypatch):
        from django.utils import timezone

        from memory.models import Souvenir

        a = await Souvenir.objects.acreate(
            content="a", importance=0.8, occurred_at=timezone.now())
        b = await Souvenir.objects.acreate(
            content="b", importance=0.2, occurred_at=timezone.now())

        removed_from_chroma = []

        class FakeStore:
            def search_souvenirs(self, content, n=3, min_importance=0.0):
                return [
                    {"id": str(a.pk), "distance": 0.0},
                    {"id": str(b.pk), "distance": 0.05},
                ]

            def remove_souvenir(self, pk):
                removed_from_chroma.append(pk)

        import memory.manager as manager_mod
        monkeypatch.setattr(manager_mod.memory_manager, "vector_store", FakeStore())

        reorg = NightlyReorg()
        merges = await reorg._dedup_souvenirs(date.today())
        assert merges == 1
        assert removed_from_chroma == [b.pk]
        assert not await Souvenir.objects.filter(pk=b.pk).aexists()

        # Idempotence : une seconde passe ne trouve plus de paire.
        class FakeStore2(FakeStore):
            def search_souvenirs(self, content, n=3, min_importance=0.0):
                return [{"id": str(a.pk), "distance": 0.0}]

        monkeypatch.setattr(manager_mod.memory_manager, "vector_store", FakeStore2())
        assert await reorg._dedup_souvenirs(date.today()) == 0

    async def test_la_dedup_voit_les_souvenirs_ecrits_par_la_nuit_elle_meme(self, monkeypatch):
        """La passe tourne à 3 h et couvre la veille : ce qu'elle vient
        d'écrire porte ``created_at`` = nuit+1, et lui échappait donc."""
        from datetime import timedelta

        from django.utils import timezone

        from memory.models import Souvenir

        s = await Souvenir.objects.acreate(
            content="écrit par la passe de cette nuit", importance=0.5,
            occurred_at=timezone.now() - timedelta(days=1),
        )
        interroges = []

        class FakeStore:
            def search_souvenirs(self, content, n=3, min_importance=0.0):
                interroges.append(content)
                return []

        import memory.manager as manager_mod
        monkeypatch.setattr(manager_mod.memory_manager, "vector_store", FakeStore())

        hier = date.today() - timedelta(days=1)
        await NightlyReorg()._dedup_souvenirs(hier)

        assert s.content in interroges


@pytest.mark.django_db(transaction=True)
class TestExtractByTheme:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from memory.models import (
            ConsolidationLog, Conversation, Message, Souvenir,
        )
        Message.objects.all().delete()
        ConsolidationLog.objects.all().delete()
        Souvenir.objects.all().delete()
        Conversation.objects.all().delete()
        yield

    async def test_each_cluster_gets_its_own_extraction_call(self, monkeypatch):
        # Aucun ConsolidationLog ici : c'est le cas BACKLOG, celui que la nuit
        # doit encore rattraper (le fil de l'eau n'a rien extrait).
        import memory.manager as manager_mod
        from memory.models import Conversation, Message

        conv = await Conversation.objects.acreate()
        m1 = await Message.objects.acreate(
            conversation=conv, role="user", content="parlons du projet fusée",
            person_id="web_a")
        m2 = await Message.objects.acreate(
            conversation=conv, role="assistant", content="oui ! où en es-tu ?",
            person_id="web_a")

        class FakeStore:
            def get_exchanges_between(self, since, until, include_embeddings=False):
                return [
                    _chunk("10", [1.0, 0.0], ts=since + 60, content="x" * 300,
                           first=m1.pk, last=m2.pk),
                    _chunk("20", [0.0, 1.0], ts=since + 120, content="y" * 300,
                           first=m1.pk, last=m2.pk),
                ]

        fake_extractor = type("X", (), {})()
        fake_extractor.analyze_messages = AsyncMock(return_value=[])
        fake_consolidator = type("C", (), {})()
        fake_consolidator.store_extractions = AsyncMock(
            return_value={"souvenirs": 1, "connaissances": 0, "commitments": 0})

        monkeypatch.setattr(manager_mod.memory_manager, "vector_store", FakeStore())
        monkeypatch.setattr(manager_mod.memory_manager, "extractor", fake_extractor)
        monkeypatch.setattr(manager_mod.memory_manager, "consolidator", fake_consolidator)

        reorg = NightlyReorg()
        stats = await reorg._extract_by_theme(date.today())
        # Deux clusters orthogonaux → deux appels d'extraction distincts.
        assert stats["clusters"] == 2
        assert fake_extractor.analyze_messages.call_count == 2
        assert stats["extracted"] == 2

    async def _monter_la_nuit(self, monkeypatch, *, checkpoint, created_at=None):
        """Deux messages, un cluster qui les couvre, un checkpoint donné."""
        import memory.manager as manager_mod
        from memory.models import ConsolidationLog, Conversation, Message

        conv = await Conversation.objects.acreate()
        m1 = await Message.objects.acreate(
            conversation=conv, role="user", content="parlons du projet fusée",
            person_id="web_a")
        m2 = await Message.objects.acreate(
            conversation=conv, role="assistant", content="oui ! où en es-tu ?",
            person_id="web_a")
        if created_at is not None:
            await Message.objects.filter(pk__in=[m1.pk, m2.pk]).aupdate(
                created_at=created_at)
        await ConsolidationLog.objects.acreate(
            messages_processed=2,
            last_message_id=checkpoint if checkpoint is not None else m2.pk,
        )

        class FakeStore:
            def get_exchanges_between(self, since, until, include_embeddings=False):
                return [
                    _chunk("10", [1.0, 0.0], ts=since + 60, content="x" * 300,
                           first=m1.pk, last=m2.pk),
                ]

        monkeypatch.setattr(manager_mod.memory_manager, "vector_store", FakeStore())
        return m1, m2

    async def test_la_nuit_ne_reextrait_pas_ce_que_le_jour_a_deja_extrait(self, monkeypatch):
        """Sinon chaque journée est extraite deux fois, et la copie nocturne
        — mieux datée que l'originale — la surclasse au rappel."""
        import memory.manager as manager_mod
        from memory.models import Souvenir

        _, m2 = await self._monter_la_nuit(monkeypatch, checkpoint=None)

        fake_extractor = type("X", (), {})()
        fake_extractor.analyze_messages = AsyncMock(return_value=[])
        fake_consolidator = type("C", (), {})()
        fake_consolidator.store_extractions = AsyncMock(return_value={})
        monkeypatch.setattr(manager_mod.memory_manager, "extractor", fake_extractor)
        monkeypatch.setattr(manager_mod.memory_manager, "consolidator", fake_consolidator)

        stats = await NightlyReorg()._extract_by_theme(date.today())

        assert fake_extractor.analyze_messages.call_count == 0
        assert stats["extracted"] == 0
        assert not await Souvenir.objects.aexists()

    async def test_la_nuit_rattrape_ce_que_le_jour_n_a_pas_pu_extraire(self, monkeypatch):
        """Le chemin par thème reste vivant : c'est exactement ce que laisse
        derrière lui un provider mort tout l'après-midi."""
        import memory.manager as manager_mod

        m1, _ = await self._monter_la_nuit(monkeypatch, checkpoint=0)

        fake_extractor = type("X", (), {})()
        fake_extractor.analyze_messages = AsyncMock(return_value=[])
        fake_consolidator = type("C", (), {})()
        fake_consolidator.store_extractions = AsyncMock(
            return_value={"souvenirs": 1})
        monkeypatch.setattr(manager_mod.memory_manager, "extractor", fake_extractor)
        monkeypatch.setattr(manager_mod.memory_manager, "consolidator", fake_consolidator)

        stats = await NightlyReorg()._extract_by_theme(date.today())

        assert fake_extractor.analyze_messages.call_count == 1
        assert stats["extracted"] == 1

    async def test_un_souvenir_de_la_reorg_est_date_de_la_nuit_couverte(self, monkeypatch):
        from datetime import timedelta
        from unittest.mock import MagicMock

        from django.utils import timezone

        import memory.manager as manager_mod
        from memory.models import Souvenir
        from memory.storage.consolidator import MemoryConsolidator

        hier_20h = timezone.now() - timedelta(days=1)
        await self._monter_la_nuit(monkeypatch, checkpoint=0, created_at=hier_20h)

        fake_extractor = type("X", (), {})()
        fake_extractor.analyze_messages = AsyncMock(return_value=[
            {"type": "souvenir", "store": True,
             "content": "On a parlé du projet fusée", "emotion": "excited"},
        ])
        vrai_consolidateur = MemoryConsolidator.__new__(MemoryConsolidator)
        vrai_consolidateur.vector_store = MagicMock()
        monkeypatch.setattr(manager_mod.memory_manager, "extractor", fake_extractor)
        monkeypatch.setattr(manager_mod.memory_manager, "consolidator", vrai_consolidateur)

        await NightlyReorg()._extract_by_theme(date.today())

        s = await Souvenir.objects.aget()
        assert abs((s.occurred_at - hier_20h).total_seconds()) < 1


class TestBatchSplit:

    def test_backlog_is_split_on_message_boundaries(self):
        from memory.storage.consolidator import _split_batches

        messages = [{"content": "x" * 3000} for _ in range(5)]
        batches = _split_batches(messages, 8000)
        assert [len(b) for b in batches] == [2, 2, 1]

    def test_one_giant_message_travels_alone(self):
        from memory.storage.consolidator import _split_batches

        batches = _split_batches(
            [{"content": "a"}, {"content": "x" * 20000}, {"content": "b"}], 8000,
        )
        assert [len(b) for b in batches] == [1, 1, 1]
