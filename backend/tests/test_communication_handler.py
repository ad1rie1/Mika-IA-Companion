"""Tests for communication layer — handler, WebSocket consumer, HTTP views."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from emotion.types import Emotion, EmotionData


# ===================================================================
# handle_message
# ===================================================================

class TestHandleMessage:

    @pytest.mark.asyncio
    async def test_delegates_to_process_message(self):
        mock_output = MagicMock()
        mock_output.text = "Salut !"
        mock_output.emotion_data = EmotionData(emotion=Emotion.HAPPY, intensity=0.7)

        with patch("communication.handler.process_message", new_callable=AsyncMock, return_value=mock_output):
            from communication.handler import handle_message
            text, emotion_data = await handle_message("Bonjour", source="frontend", person_id="u1")

        assert text == "Salut !"
        assert emotion_data.emotion == Emotion.HAPPY

    @pytest.mark.asyncio
    async def test_passes_source_and_person_id(self):
        mock_output = MagicMock()
        mock_output.text = "ok"
        mock_output.emotion_data = MagicMock()

        with patch("communication.handler.process_message", new_callable=AsyncMock, return_value=mock_output) as mock_proc:
            from communication.handler import handle_message
            await handle_message("test", source="telegram", person_id="tg_123")

        mock_proc.assert_called_once_with(message="test", source="telegram", person_id="tg_123")

    @pytest.mark.asyncio
    async def test_defaults(self):
        mock_output = MagicMock()
        mock_output.text = "ok"
        mock_output.emotion_data = MagicMock()

        with patch("communication.handler.process_message", new_callable=AsyncMock, return_value=mock_output) as mock_proc:
            from communication.handler import handle_message
            await handle_message("test")

        kw = mock_proc.call_args[1]
        assert kw["source"] == "frontend"
        assert kw["person_id"] == "anonymous"


# ===================================================================
# WebSocketConsumer.receive
# ===================================================================

class TestWebSocketReceive:

    def _make_consumer(self):
        from communication.channels.web_frontend import WebSocketConsumer
        c = WebSocketConsumer.__new__(WebSocketConsumer)
        c.person_id = "test_pid"
        c.channel_name = "test_ch"
        c.channel_layer = MagicMock()
        c.send = AsyncMock()
        return c

    @pytest.mark.asyncio
    async def test_valid_chat_calls_handle_message(self):
        c = self._make_consumer()
        data = json.dumps({"type": "chat", "message": "Hello"})
        with patch("communication.channels.web_frontend.handle_message", new_callable=AsyncMock) as mock_h:
            await c.receive(text_data=data)
        mock_h.assert_called_once_with("Hello", source="frontend", person_id="test_pid")

    @pytest.mark.asyncio
    async def test_invalid_json_ignored(self):
        c = self._make_consumer()
        with patch("communication.channels.web_frontend.handle_message", new_callable=AsyncMock) as mock_h:
            await c.receive(text_data="not{json")
        mock_h.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_chat_type_ignored(self):
        c = self._make_consumer()
        data = json.dumps({"type": "ping"})
        with patch("communication.channels.web_frontend.handle_message", new_callable=AsyncMock) as mock_h:
            await c.receive(text_data=data)
        mock_h.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_message_ignored(self):
        c = self._make_consumer()
        data = json.dumps({"type": "chat", "message": "   "})
        with patch("communication.channels.web_frontend.handle_message", new_callable=AsyncMock) as mock_h:
            await c.receive(text_data=data)
        mock_h.assert_not_called()

    @pytest.mark.asyncio
    async def test_message_truncated_to_max_length(self):
        from communication.channels.web_frontend import MAX_MESSAGE_LENGTH
        c = self._make_consumer()
        data = json.dumps({"type": "chat", "message": "a" * (MAX_MESSAGE_LENGTH + 500)})
        with patch("communication.channels.web_frontend.handle_message", new_callable=AsyncMock) as mock_h:
            await c.receive(text_data=data)
        assert len(mock_h.call_args[0][0]) == MAX_MESSAGE_LENGTH

    @pytest.mark.asyncio
    async def test_client_provided_person_id_used(self):
        c = self._make_consumer()
        data = json.dumps({"type": "chat", "message": "Hi", "person_id": "custom_pid"})
        with patch("communication.channels.web_frontend.handle_message", new_callable=AsyncMock) as mock_h:
            await c.receive(text_data=data)
        mock_h.assert_called_once_with("Hi", source="frontend", person_id="custom_pid")


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
