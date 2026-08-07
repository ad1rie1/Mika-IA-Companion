"""Tests for communication layer — WebSocket consumer + HTTP views.

The new entry point is ``pipeline.router.perceive(Perception)``. The
WebSocket consumer builds a Perception from incoming chat messages and
routes it; it no longer calls a legacy ``handle_message`` tuple-returning
wrapper.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from communication.channels import web_frontend
from pipeline.perception import Intent, Modality


# ===================================================================
# WebSocketConsumer.receive  →  builds Perception  →  submits it to the
# turn queue. It no longer awaits the pipeline: Channels dispatches a
# consumer's frames one at a time, so running a turn inline left the
# connection unable to answer anything — a ping, a catch-up, the next
# message — for the whole call.
# ===================================================================

class TestWebSocketReceive:

    def _make_consumer(self):
        from communication.channels.web_frontend import WebSocketConsumer
        c = WebSocketConsumer.__new__(WebSocketConsumer)
        c.person_id = "test_pid"
        c.display_name = None
        # Mark as already greeted so `chat` tests don't fire the greeting
        # perception (which would be an unrelated side-effect).
        c._greeted = True
        c.channel_name = "test_ch"
        c.channel_layer = MagicMock()
        c.send = AsyncMock()
        return c

    @pytest.mark.asyncio
    async def test_valid_chat_calls_perceive(self):
        c = self._make_consumer()
        data = json.dumps({"type": "chat", "message": "Hello"})
        with patch.object(web_frontend.turn_queue, "submit",
                   return_value=True) as mock_perceive:
            await c.receive(text_data=data)
        mock_perceive.assert_called_once()
        perception = mock_perceive.call_args[0][0]
        assert perception.text == "Hello"
        assert perception.modality is Modality.TEXT
        assert perception.intent is Intent.REQUEST_RESPONSE
        assert perception.source == "frontend"
        assert perception.person_id == "test_pid"

    @pytest.mark.asyncio
    async def test_invalid_json_ignored(self):
        c = self._make_consumer()
        with patch.object(web_frontend.turn_queue, "submit",
                   return_value=True) as mock_perceive:
            await c.receive(text_data="not{json")
        mock_perceive.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_chat_type_ignored(self):
        c = self._make_consumer()
        data = json.dumps({"type": "ping"})
        with patch.object(web_frontend.turn_queue, "submit",
                   return_value=True) as mock_perceive:
            await c.receive(text_data=data)
        mock_perceive.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_message_no_attachments_ignored(self):
        c = self._make_consumer()
        data = json.dumps({"type": "chat", "message": "   "})
        with patch.object(web_frontend.turn_queue, "submit",
                   return_value=True) as mock_perceive:
            await c.receive(text_data=data)
        mock_perceive.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_over_long_message_is_refused_rather_than_truncated(self):
        """Cutting it silently left the two sides holding different text.

        The browser goes on showing the bubble it painted itself, marked
        delivered; the server holds a shortened version and answers that.
        Nothing ever reconciles them, and the sender has no way to know.
        Refusing lets them edit what they actually wrote — see
        ``test_ws_delivery_hardening`` for the ack that says so.
        """
        from communication.channels.web_frontend import MAX_MESSAGE_LENGTH
        c = self._make_consumer()
        data = json.dumps({"type": "chat", "message": "a" * (MAX_MESSAGE_LENGTH + 500)})
        with patch.object(web_frontend.turn_queue, "submit",
                   return_value=True) as mock_perceive:
            await c.receive(text_data=data)
        mock_perceive.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_message_at_the_limit_still_goes_through(self):
        """The refusal is for what exceeds the cap, not for reaching it."""
        from communication.channels.web_frontend import MAX_MESSAGE_LENGTH
        c = self._make_consumer()
        data = json.dumps({"type": "chat", "message": "a" * MAX_MESSAGE_LENGTH})
        with patch.object(web_frontend.turn_queue, "submit",
                   return_value=True) as mock_perceive:
            await c.receive(text_data=data)
        perception = mock_perceive.call_args[0][0]
        assert len(perception.text) == MAX_MESSAGE_LENGTH

    @pytest.mark.asyncio
    async def test_chat_person_id_claim_is_ignored(self):
        # Identity is bound at connect/identify time; a person_id smuggled in a
        # chat frame must NOT override the connection's bound identity.
        c = self._make_consumer()
        data = json.dumps({
            "type": "chat", "message": "Hi", "person_id": "custom_pid",
        })
        with patch.object(web_frontend.turn_queue, "submit",
                   return_value=True) as mock_perceive:
            await c.receive(text_data=data)
        perception = mock_perceive.call_args[0][0]
        assert perception.person_id == c.person_id
        assert perception.person_id != "custom_pid"

    @pytest.mark.asyncio
    async def test_attachments_produce_mixed_perception(self):
        c = self._make_consumer()
        data = json.dumps({
            "type": "chat",
            "message": "regarde",
            "attachments": [
                {"kind": "image", "content": "b64data", "mime_type": "image/png"},
            ],
        })
        with patch.object(
            web_frontend.turn_queue, "submit", return_value=True,
        ) as mock_perceive, patch(
            "communication.channels.web_frontend.validate_attachments",
            side_effect=lambda x: (x, []),
        ):
            await c.receive(text_data=data)
        perception = mock_perceive.call_args[0][0]
        assert perception.modality is Modality.MIXED
        assert perception.has_non_text() is True


# ===================================================================
# HTTP Views
# ===================================================================

class TestViews:

    def test_health_returns_ok(self):
        mock_personality = MagicMock()
        mock_personality.name = "Mika"
        with patch("communication.views.personality", mock_personality):
            from communication.views import health
            response = health(MagicMock())
        data = json.loads(response.content)
        assert data["status"] == "ok"
        assert data["vtuber"] == "Mika"

    def test_get_personality_returns_fields(self):
        mock_personality = MagicMock()
        mock_personality.name = "Mika"
        mock_personality.description = "VTubeuse sympa"
        mock_personality.greeting = "Bienvenue !"
        with patch("communication.views.personality", mock_personality):
            from communication.views import get_personality
            response = get_personality(MagicMock())
        data = json.loads(response.content)
        assert data["name"] == "Mika"
        assert data["description"] == "VTubeuse sympa"
        assert data["greeting"] == "Bienvenue !"
