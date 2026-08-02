"""Tests for MemoryExtractor — analyze_messages, validity check, JSON parsing."""

import json
import pytest
from unittest.mock import AsyncMock, patch


def _make_extractor():
    from memory.extraction.extractor import MemoryExtractor
    e = MemoryExtractor()
    e._system_prompt = "System: extrait les mémoires."
    return e


# ===================================================================
# analyze_messages
# ===================================================================

class TestAnalyzeMessages:

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self):
        e = _make_extractor()
        result = await e.analyze_messages([])
        assert result == []

    @pytest.mark.asyncio
    async def test_valid_extraction_returned(self):
        e = _make_extractor()
        response = json.dumps({"extractions": [
            {"type": "souvenir", "store": True, "content": "On a joué à Zelda", "emotion": "happy", "themes": [], "entities": []},
            {"type": "connaissance", "store": True, "content": "Thomas aime les chats", "themes": [], "entities": []},
        ]})
        with patch.object(e, "_query_model", new_callable=AsyncMock, return_value=response):
            result = await e.analyze_messages([{"role": "user", "content": "test"}])
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_store_false_filtered_out(self):
        e = _make_extractor()
        response = json.dumps({"extractions": [
            {"type": "souvenir", "store": False, "content": "Banal"},
            {"type": "connaissance", "store": True, "content": "Important", "themes": [], "entities": []},
        ]})
        with patch.object(e, "_query_model", new_callable=AsyncMock, return_value=response):
            result = await e.analyze_messages([{"role": "user", "content": "test"}])
        assert len(result) == 1
        assert result[0]["content"] == "Important"

    @pytest.mark.asyncio
    async def test_ai_error_returns_empty(self):
        e = _make_extractor()
        with patch.object(e, "_query_model", new_callable=AsyncMock, side_effect=Exception("AI down")):
            result = await e.analyze_messages([{"role": "user", "content": "test"}])
        assert result == []

    @pytest.mark.asyncio
    async def test_timeout_returns_empty(self):
        import asyncio
        e = _make_extractor()

        async def slow(*a, **kw):
            await asyncio.sleep(100)
            return "{}"

        with patch.object(e, "_query_model", side_effect=slow), \
             patch("memory.extraction.extractor.EXTRACTION_TIMEOUT", 0.01):
            result = await e.analyze_messages([{"role": "user", "content": "test"}])
        assert result == []


# ===================================================================
# _query_model_json
# ===================================================================

class TestQueryModelJson:

    @pytest.mark.asyncio
    async def test_valid_json_parsed(self):
        e = _make_extractor()
        with patch.object(e, "_query_model", new_callable=AsyncMock, return_value='{"extractions": []}'):
            result = await e._query_model_json("test")
        assert result == {"extractions": []}

    @pytest.mark.asyncio
    async def test_markdown_json_stripped(self):
        e = _make_extractor()
        with patch.object(e, "_query_model", new_callable=AsyncMock, return_value='```json\n{"extractions": []}\n```'):
            result = await e._query_model_json("test")
        assert result == {"extractions": []}

    @pytest.mark.asyncio
    async def test_invalid_json_returns_none(self):
        e = _make_extractor()
        with patch.object(e, "_query_model", new_callable=AsyncMock, return_value="not json"):
            result = await e._query_model_json("test")
        assert result is None

    @pytest.mark.asyncio
    async def test_none_response_returns_none(self):
        e = _make_extractor()
        with patch.object(e, "_query_model", new_callable=AsyncMock, return_value=None):
            result = await e._query_model_json("test")
        assert result is None


# ===================================================================
# check_connaissance_validity
# ===================================================================

class TestCheckConnaissanceValidity:

    @pytest.mark.asyncio
    async def test_still_valid(self):
        e = _make_extractor()
        r = json.dumps({"still_valid": True, "new_confidence": 0.9, "reason": "ok"})
        with patch.object(e, "_query_model", new_callable=AsyncMock, return_value=r):
            valid, conf = await e.check_connaissance_validity("fact", "context")
        assert valid is True
        assert conf == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_invalidated(self):
        e = _make_extractor()
        r = json.dumps({"still_valid": False, "new_confidence": 0.1, "reason": "contradiction"})
        with patch.object(e, "_query_model", new_callable=AsyncMock, return_value=r):
            valid, conf = await e.check_connaissance_validity("fact", "context")
        assert valid is False
        assert conf == pytest.approx(0.1)

    @pytest.mark.asyncio
    async def test_error_fallback_conservative(self):
        e = _make_extractor()
        with patch.object(e, "_query_model", new_callable=AsyncMock, side_effect=Exception("err")):
            valid, conf = await e.check_connaissance_validity("fact", "context")
        assert valid is True
        assert conf is None

    @pytest.mark.asyncio
    async def test_confidence_clamped(self):
        e = _make_extractor()
        r = json.dumps({"still_valid": True, "new_confidence": 2.5, "reason": "ok"})
        with patch.object(e, "_query_model", new_callable=AsyncMock, return_value=r):
            _, conf = await e.check_connaissance_validity("fact", "context")
        assert conf <= 1.0
