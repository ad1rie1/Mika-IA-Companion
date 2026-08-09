"""Indexeur épisodique — checkpoint, exclusions, échec du store, purge."""

from __future__ import annotations

import pytest
from django.utils import timezone

from memory.episodic.indexer import EpisodicIndexer
from memory.models import Conversation, EpisodicIndexLog, Message

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _clean_tables():
    """Les écritures async passent par une autre connexion et committent
    réellement (pattern documenté dans test_self_narrative) — on tronque ce
    que ces tests lisent."""
    Message.objects.all().delete()
    EpisodicIndexLog.objects.all().delete()
    Conversation.objects.all().delete()
    yield


class FakeStore:
    def __init__(self, fail=False):
        self.fail = fail
        self.batches: list[list[dict]] = []
        self.pruned_before: list[float] = []

    def add_exchanges(self, entries):
        if self.fail:
            raise RuntimeError("chroma down")
        self.batches.append(entries)

    def prune_exchanges_before(self, cutoff_ts):
        self.pruned_before.append(cutoff_ts)
        return 0


def _indexer(store=None):
    return EpisodicIndexer(store or FakeStore(), interval_seconds=3600)


async def _seed(conv, *rows):
    out = []
    for role, content, kwargs in rows:
        out.append(await Message.objects.acreate(
            conversation=conv, role=role, content=content, **kwargs,
        ))
    return out


class TestIndexing:

    async def test_exchange_is_indexed_and_checkpoint_advances(self):
        conv = await Conversation.objects.acreate()
        msgs = await _seed(
            conv,
            ("user", "salut", {"person_id": "web_a"}),
            ("assistant", "coucou", {"person_id": "web_a"}),
        )
        indexer = _indexer()
        await indexer._index_new_messages()

        assert len(indexer.vector_store.batches) == 1
        entry = indexer.vector_store.batches[0][0]
        assert entry["chunk_id"] == str(msgs[0].pk)
        assert entry["metadata"]["handle"] == "web_a"
        assert entry["metadata"]["last_message_id"] == msgs[1].pk
        assert indexer._last_processed_id == msgs[1].pk
        assert await EpisodicIndexLog.objects.acount() == 1

    async def test_second_run_indexes_nothing_new(self):
        conv = await Conversation.objects.acreate()
        await _seed(
            conv,
            ("user", "salut", {"person_id": "web_a"}),
            ("assistant", "coucou", {"person_id": "web_a"}),
        )
        indexer = _indexer()
        await indexer._index_new_messages()
        await indexer._index_new_messages()
        assert len(indexer.vector_store.batches) == 1

    async def test_store_failure_freezes_the_checkpoint(self):
        """Un chunk raté serait introuvable jusqu'à sa purge : on rejoue."""
        conv = await Conversation.objects.acreate()
        msgs = await _seed(
            conv,
            ("user", "salut", {"person_id": "web_a"}),
            ("assistant", "coucou", {"person_id": "web_a"}),
        )
        store = FakeStore(fail=True)
        indexer = _indexer(store)
        await indexer._index_new_messages()
        assert indexer._last_processed_id == 0
        assert await EpisodicIndexLog.objects.acount() == 0

        store.fail = False
        await indexer._index_new_messages()
        assert len(store.batches) == 1
        assert indexer._last_processed_id == msgs[1].pk

    async def test_machinery_is_excluded_but_checkpoint_still_advances(self):
        conv = await Conversation.objects.acreate()
        rows = await _seed(
            conv,
            ("user", "brief interne", {"person_id": "web_a", "is_internal": True}),
            ("user", "notif module", {"person_id": "web_a", "source": "module_email"}),
            ("user", "prompt d'action", {"person_id": "conscience_mika", "source": "conscience"}),
        )
        indexer = _indexer()
        await indexer._index_new_messages()
        assert indexer.vector_store.batches == []
        # Fenêtre entièrement technique : relue à jamais sinon.
        assert indexer._last_processed_id == rows[-1].pk

    async def test_fresh_unanswered_question_holds_the_checkpoint_back(self):
        conv = await Conversation.objects.acreate()
        done = await _seed(
            conv,
            ("user", "q1", {"person_id": "web_a"}),
            ("assistant", "r1", {"person_id": "web_a"}),
        )
        pending = await _seed(conv, ("user", "et sinon ?", {"person_id": "web_a"}))
        indexer = _indexer()
        await indexer._index_new_messages()

        assert indexer._last_processed_id == pending[0].pk - 1
        assert len(indexer.vector_store.batches) == 1

        # La réponse arrive : la paire s'indexe entière au tick suivant.
        reply = await _seed(conv, ("assistant", "dis-moi", {"person_id": "web_a"}))
        await indexer._index_new_messages()
        last = indexer.vector_store.batches[-1][-1]
        assert last["metadata"]["first_message_id"] == pending[0].pk
        assert last["metadata"]["last_message_id"] == reply[0].pk
        assert indexer._last_processed_id == reply[0].pk
        assert done[0].pk < pending[0].pk  # sanité de l'ordre

    async def test_checkpoint_resumes_from_the_latest_log_row(self):
        await EpisodicIndexLog.objects.acreate(last_message_id=41)
        await EpisodicIndexLog.objects.acreate(last_message_id=77)
        indexer = _indexer()
        await indexer._load_checkpoint()
        assert indexer._last_processed_id == 77


class TestPrune:

    async def test_prune_uses_the_configured_retention(self):
        indexer = _indexer()
        await indexer.prune_expired()
        assert len(indexer.vector_store.pruned_before) == 1
        cutoff = indexer.vector_store.pruned_before[0]
        # ~75 jours par défaut, à une heure près.
        expected = timezone.now().timestamp() - 75 * 86400
        assert abs(cutoff - expected) < 3600
