"""Tests for concern-based recipient routing (MemoryBridge.who_is_concerned)."""

from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from communication.presence import presence_registry
from conscience.memory_bridge import MemoryBridge
from identity.resolver import identity_resolver


@pytest.fixture
def clean_presence():
    presence_registry._by_key.clear()
    yield presence_registry
    presence_registry._by_key.clear()


async def _make_connaissance_about(name: str, content: str):
    """Create a person Entity + a Connaissance referencing it."""
    from memory.models import Connaissance, Entity

    entity = await sync_to_async(Entity.objects.create)(
        name=name, entity_type="person"
    )
    conn = await sync_to_async(Connaissance.objects.create)(content=content)
    await sync_to_async(conn.entities.add)(entity)
    return conn


async def _make_souvenir_about(name: str, content: str):
    from memory.models import Entity, Souvenir

    entity, _ = await sync_to_async(Entity.objects.get_or_create)(
        name=name, entity_type="person"
    )
    souv = await sync_to_async(Souvenir.objects.create)(
        content=content, occurred_at=timezone.now()
    )
    await sync_to_async(souv.entities.add)(entity)
    return souv


@pytest.mark.django_db(transaction=True)
class TestWhoIsConcerned:

    async def test_resolves_person_with_reachable_module_handle(self, clean_presence):
        conn = await _make_connaissance_about("Bob", "Bob aime la guerre")
        # Bob is reachable on Telegram (module handle = reachable any time)
        await identity_resolver.link_handle("tg_bob", "telegram", "module", "555")
        await identity_resolver.link_entity("tg_bob", "Bob")

        bridge = MemoryBridge()
        with patch("memory.manager.memory_manager") as mm:
            mm.search_related_souvenirs = AsyncMock(return_value=[])
            mm.search_related_connaissances = AsyncMock(
                return_value=[{"id": str(conn.pk), "distance": 0.1}]
            )
            result = await bridge.who_is_concerned("nouvelle de guerre")

        assert len(result) == 1
        assert result[0]["name"] == "Bob"
        assert any(h["person_id"] == "tg_bob" for h in result[0]["handles"])

    async def test_multiple_concerned_ranked_by_relevance(self, clean_presence):
        c1 = await _make_connaissance_about("Bob", "Bob aime la guerre")
        c2 = await _make_connaissance_about("Alice", "Alice aime les news")
        await identity_resolver.link_handle("tg_bob", "telegram", "module", "1")
        await identity_resolver.link_entity("tg_bob", "Bob")
        await identity_resolver.link_handle("tg_alice", "telegram", "module", "2")
        await identity_resolver.link_entity("tg_alice", "Alice")

        bridge = MemoryBridge()
        with patch("memory.manager.memory_manager") as mm:
            mm.search_related_souvenirs = AsyncMock(return_value=[])
            mm.search_related_connaissances = AsyncMock(return_value=[
                {"id": str(c1.pk), "distance": 0.05},  # more relevant
                {"id": str(c2.pk), "distance": 0.5},
            ])
            result = await bridge.who_is_concerned("guerre dans les news")

        assert [r["name"] for r in result] == ["Bob", "Alice"]
        assert result[0]["score"] > result[1]["score"]

    async def test_concerned_but_unreachable_consumer_excluded(self, clean_presence):
        # Bob is only known via a web (consumer) handle, and he is NOT connected.
        conn = await _make_connaissance_about("Bob", "Bob aime la guerre")
        await identity_resolver.link_handle("user_bob", "web", "consumer", "grp")
        await identity_resolver.link_entity("user_bob", "Bob")

        bridge = MemoryBridge()
        with patch("memory.manager.memory_manager") as mm:
            mm.search_related_souvenirs = AsyncMock(return_value=[])
            mm.search_related_connaissances = AsyncMock(
                return_value=[{"id": str(conn.pk), "distance": 0.1}]
            )
            result = await bridge.who_is_concerned("guerre")

        assert result == []  # consumer offline → not reachable

        # ...but reachable once connected
        presence_registry.register("user_bob", "web", "consumer", "grp")
        with patch("memory.manager.memory_manager") as mm:
            mm.search_related_souvenirs = AsyncMock(return_value=[])
            mm.search_related_connaissances = AsyncMock(
                return_value=[{"id": str(conn.pk), "distance": 0.1}]
            )
            result = await bridge.who_is_concerned("guerre")
        assert len(result) == 1

    async def test_no_matches_returns_empty(self, clean_presence):
        bridge = MemoryBridge()
        with patch("memory.manager.memory_manager") as mm:
            mm.search_related_souvenirs = AsyncMock(return_value=[])
            mm.search_related_connaissances = AsyncMock(return_value=[])
            result = await bridge.who_is_concerned("rien de connu")
        assert result == []

    async def test_empty_signal_returns_empty(self, clean_presence):
        bridge = MemoryBridge()
        result = await bridge.who_is_concerned("   ")
        assert result == []
