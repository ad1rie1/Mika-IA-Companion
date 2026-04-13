"""Tests for VectorStore — add, remove, search, parse_results."""

import pytest
from unittest.mock import MagicMock, patch


def _make_store():
    """VectorStore with fully mocked ChromaDB."""
    mock_coll = MagicMock()
    mock_coll.count = MagicMock(return_value=0)
    mock_client = MagicMock()
    mock_client.get_or_create_collection = MagicMock(return_value=mock_coll)

    with patch("memory.storage.vector_store.chromadb.PersistentClient", return_value=mock_client), \
         patch("memory.storage.vector_store.SentenceTransformerEmbeddingFunction"), \
         patch("memory.storage.vector_store.settings") as ms:
        ms.CHROMA_PERSIST_DIR = "/tmp/test_chroma"
        ms.EMBEDDING_MODEL = "all-MiniLM-L6-v2"
        from memory.storage.vector_store import VectorStore
        store = VectorStore()

    return store, mock_coll


# ===================================================================
# Write operations
# ===================================================================

class TestAddOperations:

    def test_add_souvenir_upserts(self):
        store, coll = _make_store()
        store._souvenirs = coll
        store.add_souvenir(42, "J'ai joué à Zelda", {"importance": 0.8})
        coll.upsert.assert_called_once_with(
            ids=["42"], documents=["J'ai joué à Zelda"], metadatas=[{"importance": 0.8}]
        )

    def test_add_souvenir_no_metadata(self):
        store, coll = _make_store()
        store._souvenirs = coll
        store.add_souvenir(1, "content")
        coll.upsert.assert_called_once_with(ids=["1"], documents=["content"], metadatas=[{}])

    def test_add_connaissance_upserts(self):
        store, coll = _make_store()
        store._connaissances = coll
        store.add_connaissance(10, "Thomas aime les chats", {"confidence": 0.9})
        coll.upsert.assert_called_once_with(
            ids=["10"], documents=["Thomas aime les chats"], metadatas=[{"confidence": 0.9}]
        )


# ===================================================================
# Remove operations
# ===================================================================

class TestRemoveOperations:

    def test_remove_souvenir_deletes(self):
        store, coll = _make_store()
        store._souvenirs = coll
        store.remove_souvenir(42)
        coll.delete.assert_called_once_with(ids=["42"])

    def test_remove_connaissance_deletes(self):
        store, coll = _make_store()
        store._connaissances = coll
        store.remove_connaissance(10)
        coll.delete.assert_called_once_with(ids=["10"])

    def test_remove_not_found_no_exception(self):
        store, coll = _make_store()
        coll.delete = MagicMock(side_effect=Exception("not found"))
        store._souvenirs = coll
        store.remove_souvenir(999)  # should not raise


# ===================================================================
# Search operations
# ===================================================================

class TestSearchOperations:

    def test_search_souvenirs_empty_returns_empty(self):
        store, coll = _make_store()
        coll.count = MagicMock(return_value=0)
        store._souvenirs = coll
        assert store.search_souvenirs("query") == []
        coll.query.assert_not_called()

    def test_search_connaissances_empty_returns_empty(self):
        store, coll = _make_store()
        coll.count = MagicMock(return_value=0)
        store._connaissances = coll
        assert store.search_connaissances("query") == []

    def test_search_souvenirs_returns_parsed_results(self):
        store, coll = _make_store()
        coll.count = MagicMock(return_value=5)
        coll.query = MagicMock(return_value={
            "ids": [["1", "2"]],
            "documents": [["doc1", "doc2"]],
            "metadatas": [[{"importance": 0.8}, {"importance": 0.5}]],
            "distances": [[0.1, 0.4]],
        })
        store._souvenirs = coll
        results = store.search_souvenirs("query", n=2)
        assert len(results) == 2
        assert results[0]["id"] == "1"
        assert results[0]["content"] == "doc1"
        assert results[0]["distance"] == 0.1


# ===================================================================
# _parse_results
# ===================================================================

class TestParseResults:

    def _p(self, raw):
        from memory.storage.vector_store import VectorStore
        return VectorStore._parse_results(raw)

    def test_empty_dict(self):
        assert self._p({}) == []

    def test_empty_ids_list(self):
        assert self._p({"ids": [[]]}) == []

    def test_parses_correctly(self):
        raw = {
            "ids": [["1", "2"]],
            "documents": [["doc1", "doc2"]],
            "metadatas": [[{"k": "v"}, {"k": "w"}]],
            "distances": [[0.1, 0.2]],
        }
        result = self._p(raw)
        assert len(result) == 2
        assert result[0] == {"id": "1", "content": "doc1", "metadata": {"k": "v"}, "distance": 0.1}

    def test_no_distances(self):
        raw = {"ids": [["1"]], "documents": [["doc1"]], "metadatas": [[{}]]}
        result = self._p(raw)
        assert result[0]["distance"] is None
