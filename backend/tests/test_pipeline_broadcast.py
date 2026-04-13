"""Tests for pipeline broadcast — WebSocket send, event emission, persistence."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from emotion.types import Emotion, EmotionData
from pipeline.processor import SpeechOutput


def _output(text="Salut !", emotion="happy", intensity=0.7):
    return SpeechOutput(
        text=text,
        emotion_data=EmotionData(Emotion.HAPPY, intensity),
        emotion_name=emotion,
        emotion_intensity=intensity,
        emotion_state={"person": {}, "global": {}, "message": {}},
        tool_calls=[],
    )


class TestBroadcastToWebSocket:

    @pytest.mark.asyncio
    async def test_sends_speech_event_to_group(self):
        mock_layer = MagicMock()
        mock_layer.group_send = AsyncMock()

        with patch("pipeline.broadcast.get_channel_layer", return_value=mock_layer):
            from pipeline.broadcast import broadcast_to_websocket
            await broadcast_to_websocket(_output(text="Coucou !", emotion="excited"), source="frontend")

        mock_layer.group_send.assert_called_once()
        group, payload = mock_layer.group_send.call_args[0]
        assert group == "vtuber_broadcast"
        assert payload["type"] == "communication.broadcast"
        data = payload["data"]
        assert data["type"] == "speech"
        assert data["text"] == "Coucou !"
        assert data["emotion"] == "excited"
        assert data["source"] == "frontend"
        assert "emotion_state" in data

    @pytest.mark.asyncio
    async def test_source_propagated(self):
        mock_layer = MagicMock()
        mock_layer.group_send = AsyncMock()

        with patch("pipeline.broadcast.get_channel_layer", return_value=mock_layer):
            from pipeline.broadcast import broadcast_to_websocket
            await broadcast_to_websocket(_output(), source="conscience")

        data = mock_layer.group_send.call_args[0][1]["data"]
        assert data["source"] == "conscience"


class TestEmitCommunicationEvent:

    @pytest.mark.asyncio
    async def test_emits_chat_message_event(self):
        mock_mm = MagicMock()
        mock_mm.emit_event = AsyncMock()

        with patch("pipeline.broadcast.module_manager", mock_mm):
            from pipeline.broadcast import emit_communication_event
            await emit_communication_event(source="frontend", person_id="user1")

        mock_mm.emit_event.assert_called_once()
        event = mock_mm.emit_event.call_args[0][0]
        assert event.event_type == "chat.message"
        assert event.source_module == "frontend"
        assert event.data["person_id"] == "user1"


class TestPersistToMemory:

    @pytest.mark.asyncio
    async def test_saves_user_then_assistant(self):
        mock_mem = MagicMock()
        mock_mem.add_message = AsyncMock()

        with patch("pipeline.broadcast.memory_manager", mock_mem):
            from pipeline.broadcast import persist_to_memory
            await persist_to_memory("Salut", "Hey !", "frontend", "user1")

        assert mock_mem.add_message.call_count == 2
        user_call = mock_mem.add_message.call_args_list[0]
        assert user_call[0][0] == "user"
        assert user_call[0][1] == "Salut"
        assert user_call[1]["source"] == "frontend"
        asst_call = mock_mem.add_message.call_args_list[1]
        assert asst_call[0][0] == "assistant"
        assert asst_call[0][1] == "Hey !"
