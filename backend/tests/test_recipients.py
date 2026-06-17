"""Tests for proactive recipient selection ([TO:] parsing + _select_recipient)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from conscience.recipients import parse_to_tag, strip_to_tag


class TestParseToTag:

    def test_valid_in_allowed(self):
        assert parse_to_tag("[TO:tg_bob] coucou", ["tg_bob"]) == "tg_bob"

    def test_not_in_allowed_rejected(self):
        assert parse_to_tag("[TO:hacker] hi", ["tg_bob"]) is None

    def test_none_means_no_one(self):
        assert parse_to_tag("[TO:none]", ["tg_bob"]) is None

    def test_no_tag(self):
        assert parse_to_tag("just text", ["tg_bob"]) is None

    def test_case_insensitive_tag_and_spacing(self):
        assert parse_to_tag("[to: tg_bob ]", ["tg_bob"]) == "tg_bob"

    def test_empty_text(self):
        assert parse_to_tag("", ["tg_bob"]) is None

    def test_strip_tag(self):
        assert strip_to_tag("[TO:tg_bob] Salut !") == "Salut !"


def _ctx(*summaries):
    obs = [SimpleNamespace(summary=s, pertinence=0.9) for s in summaries]
    return SimpleNamespace(pending_observations=obs, scheduled_actions=[])


class TestSelectRecipient:

    @pytest.fixture
    def engine(self):
        from conscience.engine import ConscienceEngine
        return ConscienceEngine()

    async def test_picks_concerned_person(self, engine):
        engine.memory.who_is_concerned = AsyncMock(return_value=[
            {"name": "Bob", "score": 0.9,
             "handles": [{"person_id": "tg_bob", "channel": "telegram"}]},
        ])
        with patch("ai.client.ai_client.complete", new=AsyncMock(return_value="[TO:tg_bob] coucou")):
            target = await engine._select_recipient(_ctx("nouvelle de guerre"))
        assert target == "tg_bob"

    async def test_none_when_mika_declines(self, engine):
        engine.memory.who_is_concerned = AsyncMock(return_value=[
            {"name": "Bob", "score": 0.9,
             "handles": [{"person_id": "tg_bob", "channel": "telegram"}]},
        ])
        with patch("ai.client.ai_client.complete", new=AsyncMock(return_value="[TO:none]")):
            target = await engine._select_recipient(_ctx("news"))
        assert target is None

    async def test_no_candidates_returns_none(self, engine):
        engine.memory.who_is_concerned = AsyncMock(return_value=[])
        target = await engine._select_recipient(_ctx("rien"))
        assert target is None

    async def test_empty_signal_skips_ai(self, engine):
        engine.memory.who_is_concerned = AsyncMock(return_value=[])
        obs = [SimpleNamespace(summary="x", pertinence=0.1)]  # below 0.3 threshold
        ctx = SimpleNamespace(pending_observations=obs, scheduled_actions=[])
        target = await engine._select_recipient(ctx)
        assert target is None
        engine.memory.who_is_concerned.assert_not_awaited()

    async def test_invalid_tag_does_not_leak(self, engine):
        engine.memory.who_is_concerned = AsyncMock(return_value=[
            {"name": "Bob", "score": 0.9,
             "handles": [{"person_id": "tg_bob", "channel": "telegram"}]},
        ])
        with patch("ai.client.ai_client.complete", new=AsyncMock(return_value="[TO:tg_eve] hi")):
            target = await engine._select_recipient(_ctx("news"))
        assert target is None
