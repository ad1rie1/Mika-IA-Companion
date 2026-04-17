"""Tests for the WebSocket identify handshake.

When a client connects, the consumer gets an ``anon_*`` fallback ID.
The frontend's IdentityService sends ``{"type": "identify", "person_id":
"web_abc", "display_name": "Alice"}`` as its first message to rebind
the consumer to a persistent identity. Subsequent ``chat`` messages
use that ID, which lets PersonProfile / Commitment accumulate across
sessions.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_consumer():
    from communication.channels.web_frontend import WebSocketConsumer
    c = WebSocketConsumer.__new__(WebSocketConsumer)
    c.person_id = "anon_deadbeef"
    c.display_name = None
    c._greeted = False
    c.channel_name = "test_ch"
    c.channel_layer = MagicMock()
    c.send = AsyncMock()
    return c


@pytest.mark.asyncio
class TestIdentifyHandshake:

    async def test_identify_rebinds_person_id(self):
        c = _make_consumer()
        payload = json.dumps({
            "type": "identify",
            "person_id": "web_abc123",
            "display_name": "Alice",
        })
        with patch("communication.channels.web_frontend.perceive",
                   new_callable=AsyncMock), \
             patch.object(c, "_ensure_entity", new=AsyncMock()):
            await c.receive(text_data=payload)

        assert c.person_id == "web_abc123"
        assert c.display_name == "Alice"

    async def test_identify_without_display_name_still_binds(self):
        c = _make_consumer()
        payload = json.dumps({"type": "identify", "person_id": "web_xyz"})
        with patch("communication.channels.web_frontend.perceive",
                   new_callable=AsyncMock), \
             patch.object(c, "_ensure_entity", new=AsyncMock()):
            await c.receive(text_data=payload)
        assert c.person_id == "web_xyz"
        assert c.display_name is None

    async def test_identify_does_not_override_with_empty_id(self):
        c = _make_consumer()
        c.person_id = "anon_orig"
        payload = json.dumps({"type": "identify", "person_id": "   "})
        with patch("communication.channels.web_frontend.perceive",
                   new_callable=AsyncMock), \
             patch.object(c, "_ensure_entity", new=AsyncMock()):
            await c.receive(text_data=payload)
        assert c.person_id == "anon_orig"

    async def test_identify_triggers_greeting_once(self):
        c = _make_consumer()
        payload = json.dumps({"type": "identify", "person_id": "web_1"})
        with patch("communication.channels.web_frontend.perceive",
                   new_callable=AsyncMock) as mock_perceive, \
             patch.object(c, "_ensure_entity", new=AsyncMock()):
            await c.receive(text_data=payload)
            await c.receive(text_data=payload)  # second identify must not re-greet
        # First identify → greeting perception; second is a no-op on greeting.
        assert mock_perceive.call_count == 1

    async def test_identify_always_ensures_entity_by_person_id(self):
        """Entity must be keyed by person_id (stable) regardless of display_name,
        because _fetch_person_context looks up via entity__name=person_id."""
        c = _make_consumer()
        payload = json.dumps({
            "type": "identify", "person_id": "web_1", "display_name": "Bob",
        })
        with patch("communication.channels.web_frontend.perceive",
                   new_callable=AsyncMock), \
             patch.object(c, "_ensure_entity", new=AsyncMock()) as mock_entity:
            await c.receive(text_data=payload)
        mock_entity.assert_called_once_with("web_1")

    async def test_identify_ensures_entity_for_person_id_when_no_display(self):
        c = _make_consumer()
        payload = json.dumps({"type": "identify", "person_id": "web_nodisplay"})
        with patch("communication.channels.web_frontend.perceive",
                   new_callable=AsyncMock), \
             patch.object(c, "_ensure_entity", new=AsyncMock()) as mock_entity:
            await c.receive(text_data=payload)
        mock_entity.assert_called_once_with("web_nodisplay")


@pytest.mark.asyncio
class TestChatBeforeIdentify:
    """Defensive: if a client sends `chat` before `identify`, the greeting
    still fires (once), using the anon_ fallback person_id."""

    async def test_first_chat_without_identify_greets_with_anon_id(self):
        c = _make_consumer()
        payload = json.dumps({"type": "chat", "message": "coucou"})

        greeted_with: list[str] = []

        async def fake_perceive(perception):
            greeted_with.append(perception.source)

        with patch("communication.channels.web_frontend.perceive",
                   new=fake_perceive), \
             patch("communication.channels.web_frontend.validate_attachments",
                   side_effect=lambda x: x):
            await c.receive(text_data=payload)

        # First source is the greeting, second is the actual chat.
        assert "web_connect" in greeted_with
        # Anon fallback is used since no identify happened.
        assert c.person_id.startswith("anon_")


@pytest.mark.django_db(transaction=True)
class TestEnsureEntity:

    @pytest.mark.asyncio
    async def test_creates_person_entity(self):
        from asgiref.sync import sync_to_async
        from communication.channels.web_frontend import WebSocketConsumer
        from memory.models import Entity

        await WebSocketConsumer._ensure_entity("Alice")

        exists = await sync_to_async(
            lambda: Entity.objects.filter(
                name="Alice", entity_type="person",
            ).exists()
        )()
        assert exists

    @pytest.mark.asyncio
    async def test_idempotent(self):
        from asgiref.sync import sync_to_async
        from communication.channels.web_frontend import WebSocketConsumer
        from memory.models import Entity

        await WebSocketConsumer._ensure_entity("Bob")
        await WebSocketConsumer._ensure_entity("Bob")

        count = await sync_to_async(
            lambda: Entity.objects.filter(name="Bob", entity_type="person").count()
        )()
        assert count == 1
