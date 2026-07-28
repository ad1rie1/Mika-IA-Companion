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
    c.authenticated = False
    c._group = "vtuber_person_anon_deadbeef"
    c.channel_name = "test_ch"
    c.channel_layer = AsyncMock()
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
             patch.object(c, "_refresh_handle", new=AsyncMock()):
            await c.receive(text_data=payload)

        assert c.person_id == "web_abc123"
        assert c.display_name == "Alice"

    async def test_identify_without_display_name_still_binds(self):
        c = _make_consumer()
        payload = json.dumps({"type": "identify", "person_id": "web_xyz"})
        with patch("communication.channels.web_frontend.perceive",
                   new_callable=AsyncMock), \
             patch.object(c, "_refresh_handle", new=AsyncMock()):
            await c.receive(text_data=payload)
        assert c.person_id == "web_xyz"
        assert c.display_name is None

    async def test_identify_does_not_override_with_empty_id(self):
        c = _make_consumer()
        c.person_id = "anon_orig"
        payload = json.dumps({"type": "identify", "person_id": "   "})
        with patch("communication.channels.web_frontend.perceive",
                   new_callable=AsyncMock), \
             patch.object(c, "_refresh_handle", new=AsyncMock()):
            await c.receive(text_data=payload)
        assert c.person_id == "anon_orig"

    async def test_identify_triggers_greeting_once(self):
        c = _make_consumer()
        payload = json.dumps({"type": "identify", "person_id": "web_1"})
        with patch("communication.channels.web_frontend.perceive",
                   new_callable=AsyncMock) as mock_perceive, \
             patch.object(c, "_refresh_handle", new=AsyncMock()):
            await c.receive(text_data=payload)
            await c.receive(text_data=payload)  # second identify must not re-greet
        # First identify → greeting perception; second is a no-op on greeting.
        assert mock_perceive.call_count == 1

    async def test_identify_refreshes_the_persisted_handle(self):
        """Identify re-persists the handle (picking up the display name).

        It deliberately does NOT create a memory Entity: a person-Entity means
        "someone Mika knows", and minting one per connection is what left the
        table full of web_* rows that no souvenir ever referenced.
        """
        c = _make_consumer()
        payload = json.dumps({
            "type": "identify", "person_id": "web_1", "display_name": "Bob",
        })
        with patch("communication.channels.web_frontend.perceive",
                   new_callable=AsyncMock), \
             patch.object(c, "_refresh_handle", new=AsyncMock()) as mock_handle:
            await c.receive(text_data=payload)
        mock_handle.assert_awaited_once()

    async def test_identify_refreshes_handle_without_display_name(self):
        c = _make_consumer()
        payload = json.dumps({"type": "identify", "person_id": "web_nodisplay"})
        with patch("communication.channels.web_frontend.perceive",
                   new_callable=AsyncMock), \
             patch.object(c, "_refresh_handle", new=AsyncMock()) as mock_handle:
            await c.receive(text_data=payload)
        assert c.person_id == "web_nodisplay"
        mock_handle.assert_awaited_once()


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
class TestHandleRegistration:
    """What connecting persists, and — just as importantly — what it doesn't.

    An anonymous socket is bookkeeping. It gets a handle so replies can be
    routed back, flagged ephemeral so retention can reclaim it, and no memory
    Entity at all. Only authentication turns a connection into a person.
    """

    @pytest.mark.asyncio
    async def test_anonymous_connection_creates_no_entity(self):
        from asgiref.sync import sync_to_async
        from memory.models import Entity

        c = _make_consumer()
        c.person_id = "anon_cafe1234"
        c.authenticated = False
        c._group = "vtuber_person_anon_cafe1234"
        await c._register_presence()

        count = await sync_to_async(Entity.objects.count)()
        assert count == 0, "une socket anonyme n'est pas une personne"

    @pytest.mark.asyncio
    async def test_anonymous_handle_is_marked_ephemeral(self):
        from asgiref.sync import sync_to_async
        from identity.models import IdentityHandle

        c = _make_consumer()
        c.person_id = "anon_beef5678"
        c.authenticated = False
        c._group = "vtuber_person_anon_beef5678"
        await c._register_presence()

        handle = await sync_to_async(
            lambda: IdentityHandle.objects.get(person_id="anon_beef5678")
        )()
        assert handle.is_ephemeral is True
        assert handle.trust == "public"

    @pytest.mark.asyncio
    async def test_authenticated_connection_binds_entity_with_certainty(self):
        from asgiref.sync import sync_to_async
        from identity.models import Identity
        from memory.models import Entity

        c = _make_consumer()
        c.person_id = "user_7"
        c.display_name = "Alice"
        c.authenticated = True
        c._group = "vtuber_person_user_7"
        await c._register_presence()

        entity = await sync_to_async(
            lambda: Entity.objects.filter(
                name="Alice", entity_type="person",
            ).first()
        )()
        assert entity is not None, "une session authentifiée EST une personne connue"

        identity = await sync_to_async(
            lambda: Identity.objects.filter(entity=entity).first()
        )()
        assert identity is not None
        assert identity.certainty == 1.0
        assert identity.bound_at is not None

    @pytest.mark.asyncio
    async def test_reconnect_reuses_the_same_handle(self):
        """Reconnecting must not mint a second Identity for the same id.

        The backoff loop in the frontend reconnects freely; before the upsert
        was keyed properly an install with zero messages had already collected
        68 orphan handles.
        """
        from asgiref.sync import sync_to_async
        from identity.models import Identity, IdentityHandle

        for _ in range(3):
            c = _make_consumer()
            c.person_id = "web_stable"
            c.authenticated = False
            c._group = "vtuber_person_web_stable"
            await c._register_presence()

        handles = await sync_to_async(
            lambda: IdentityHandle.objects.filter(person_id="web_stable").count()
        )()
        identities = await sync_to_async(Identity.objects.count)()
        assert handles == 1
        assert identities == 1
