"""Tests for MemoryRetriever — reranking, formatting, time helpers."""

import pytest
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.utils import timezone


def _make_retriever():
    from memory.retrieval.retriever import MemoryRetriever
    return MemoryRetriever(MagicMock())


# ===================================================================
# _rerank_souvenirs
# ===================================================================

class TestRerankSouvenirs:

    def test_last_hour_gets_recency_boost(self):
        r = _make_retriever()
        s = {"content": "x", "relevance": 0.5, "occurred_at": timezone.now() - timedelta(minutes=30), "entities": []}
        result = r._rerank_souvenirs([s], "")
        assert result[0]["_score"] > 0.5  # 0.5 * 1.5

    def test_old_souvenir_no_boost(self):
        r = _make_retriever()
        s = {"content": "x", "relevance": 0.5, "occurred_at": timezone.now() - timedelta(days=30), "entities": []}
        result = r._rerank_souvenirs([s], "")
        assert result[0]["_score"] == pytest.approx(0.5)

    def test_person_id_boost(self):
        r = _make_retriever()
        s = {"content": "x", "relevance": 0.5, "occurred_at": None, "entities": ["alice"]}
        result = r._rerank_souvenirs([s], "alice")
        assert result[0]["_score"] == pytest.approx(0.7)  # 0.5 * 1.4

    def test_person_id_case_insensitive(self):
        r = _make_retriever()
        s = {"content": "x", "relevance": 0.5, "occurred_at": None, "entities": ["ALICE"]}
        result = r._rerank_souvenirs([s], "alice")
        assert result[0]["_score"] > 0.5

    def test_person_id_no_partial_match(self):
        r = _make_retriever()
        s = {"content": "x", "relevance": 0.5, "occurred_at": None, "entities": ["alicia"]}
        result = r._rerank_souvenirs([s], "alice")
        assert result[0]["_score"] == pytest.approx(0.5)  # No boost — exact match only

    def test_sorted_descending(self):
        r = _make_retriever()
        souvenirs = [
            {"content": "a", "relevance": 0.2, "occurred_at": None, "entities": []},
            {"content": "b", "relevance": 0.8, "occurred_at": None, "entities": []},
            {"content": "c", "relevance": 0.5, "occurred_at": None, "entities": []},
        ]
        result = r._rerank_souvenirs(souvenirs, "")
        scores = [s["_score"] for s in result]
        assert scores == sorted(scores, reverse=True)

    def test_score_capped_at_1(self):
        r = _make_retriever()
        # high relevance + recent + person match could exceed 1 without cap
        s = {"content": "x", "relevance": 0.9, "occurred_at": timezone.now() - timedelta(minutes=5), "entities": ["alice"]}
        result = r._rerank_souvenirs([s], "alice")
        assert result[0]["_score"] <= 1.0


# ===================================================================
# _time_ago
# ===================================================================

class TestTimeAgo:

    def _t(self, dt):
        from memory.retrieval.retriever import MemoryRetriever
        return MemoryRetriever._time_ago(dt)

    def test_none(self):
        assert self._t(None) == "?"

    def test_minutes(self):
        assert self._t(timezone.now() - timedelta(minutes=20)) == "il y a quelques minutes"

    def test_hours(self):
        assert "5h" in self._t(timezone.now() - timedelta(hours=5))

    def test_yesterday(self):
        assert self._t(timezone.now() - timedelta(days=1)) == "hier"

    def test_days(self):
        assert "3 jours" in self._t(timezone.now() - timedelta(days=3))

    def test_weeks(self):
        result = self._t(timezone.now() - timedelta(days=14))
        assert "semaine" in result

    def test_months(self):
        assert "mois" in self._t(timezone.now() - timedelta(days=60))


# ===================================================================
# _confidence_label
# ===================================================================

class TestConfidenceLabel:

    def _l(self, c):
        from memory.retrieval.retriever import MemoryRetriever
        return MemoryRetriever._confidence_label(c)

    def test_certain(self):
        assert self._l(0.9) == "certain"
        assert self._l(0.8) == "certain"

    def test_probable(self):
        assert self._l(0.7) == "probable"
        assert self._l(0.5) == "probable"

    def test_incertain(self):
        assert self._l(0.3) == "incertain"
        assert self._l(0.0) == "incertain"


# ===================================================================
# _format_context
# ===================================================================

class TestFormatContext:

    def test_always_has_header_footer(self):
        r = _make_retriever()
        result = r._format_context([], [])
        assert "--- TES SOUVENIRS ---" in result
        assert "--- FIN SOUVENIRS ---" in result

    def test_connaissance_in_output(self):
        r = _make_retriever()
        result = r._format_context(
            [{"content": "Thomas aime le café", "confidence": 0.9, "entities": [], "themes": []}],
            []
        )
        assert "Thomas aime le café" in result
        assert "certain" in result

    def test_souvenir_in_output(self):
        r = _make_retriever()
        result = r._format_context([], [{
            "content": "On a joué à Zelda",
            "emotion": "happy",
            "occurred_at": timezone.now() - timedelta(hours=2),
            "entities": [], "themes": [], "importance": 0.8,
        }])
        assert "Zelda" in result
        assert "happy" in result

    def test_output_respects_max_chars(self):
        r = _make_retriever()
        souvenirs = [
            {"content": "x" * 300, "emotion": "neutral", "occurred_at": None,
             "entities": [], "themes": [], "importance": 0.8}
            for _ in range(50)
        ]
        result = r._format_context([], souvenirs)
        assert len(result) <= r.MAX_CONTEXT_CHARS + 200


# ===================================================================
# retrieve — empty store
# ===================================================================

class TestRetrieve:

    @pytest.mark.asyncio
    async def test_empty_store_returns_empty_string(self):
        from memory.retrieval.retriever import MemoryRetriever
        mock_store = MagicMock()
        mock_store.search_souvenirs = MagicMock(return_value=[])
        mock_store.search_connaissances = MagicMock(return_value=[])

        with patch("memory.retrieval.retriever.settings") as ms:
            ms.MEMORY_RETRIEVAL_SOUVENIRS = 5
            ms.MEMORY_RETRIEVAL_CONNAISSANCES = 5
            ms.MEMORY_MIN_IMPORTANCE = 0.3
            r = MemoryRetriever(mock_store)
            result = await r.retrieve("quelque chose", person_id="u1")

        assert result == ""
