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


class TestTargetedDeliveryNeverLeaks:
    """A message composed for one person must not fall back to everyone."""

    def _register_module_target(self, person_id, channel="telegram"):
        from communication.presence import presence_registry

        presence_registry.register(
            person_id=person_id, channel=channel, kind="module",
            delivery_ref="12345",
        )
        return lambda: presence_registry.unregister(person_id, channel)

    @pytest.mark.asyncio
    async def test_undeliverable_module_target_is_dropped_not_broadcast(self):
        mock_layer = MagicMock()
        mock_layer.group_send = AsyncMock()
        cleanup = self._register_module_target("tg_777")
        try:
            with patch("pipeline.broadcast.get_channel_layer",
                       return_value=mock_layer), \
                 patch("communication.delivery.get_channel", return_value=None):
                from pipeline.broadcast import broadcast_to_websocket
                await broadcast_to_websocket(
                    _output(text="secret pour toi"), source="conscience",
                    person_id="tg_777",
                )
        finally:
            cleanup()

        mock_layer.group_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_module_target_delivered_through_registered_channel(self):
        mock_layer = MagicMock()
        mock_layer.group_send = AsyncMock()
        deliverer = MagicMock()
        deliverer.is_running = True
        deliverer.deliver = AsyncMock(return_value=True)
        cleanup = self._register_module_target("tg_888")
        try:
            with patch("pipeline.broadcast.get_channel_layer",
                       return_value=mock_layer), \
                 patch("communication.delivery.get_channel",
                       return_value=deliverer):
                from pipeline.broadcast import broadcast_to_websocket
                await broadcast_to_websocket(
                    _output(text="coucou telegram"), source="conscience",
                    person_id="tg_888",
                )
        finally:
            cleanup()

        deliverer.deliver.assert_awaited_once()
        mock_layer.group_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_identifiable_person_offline_is_not_broadcast(self):
        """No presence entry is "they are not connected", not "no recipient".

        This used to fall through to the global group, which is the same
        mistake the branch below already refuses: the payload carries that
        person's inner_state — profile, commitments, per-person affect — so
        a proactive message composed for someone offline landed in every
        other open browser. Nothing is lost by staying silent; the turn is
        persisted and their client pulls it by cursor on reconnect.
        """
        mock_layer = MagicMock()
        mock_layer.group_send = AsyncMock()
        with patch("pipeline.broadcast.get_channel_layer", return_value=mock_layer):
            from pipeline.broadcast import broadcast_to_websocket
            await broadcast_to_websocket(
                _output(), source="conscience", person_id="nobody_here",
            )
        mock_layer.group_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_message_belonging_to_no_one_still_broadcasts(self):
        """Mika thinking out loud has no recipient to be private from.

        For `conscience_mika` — and for a throwaway `anon_*` socket, which
        has no durable thread to be caught up from — "whoever is watching"
        IS the intended audience.
        """
        mock_layer = MagicMock()
        mock_layer.group_send = AsyncMock()
        with patch("pipeline.broadcast.get_channel_layer", return_value=mock_layer):
            from pipeline.broadcast import broadcast_to_websocket
            await broadcast_to_websocket(
                _output(), source="conscience", person_id="conscience_mika",
            )
        mock_layer.group_send.assert_called_once()


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
            await persist_to_memory(
                message="Salut", response="Hey !",
                source="frontend", person_id="user1",
            )

        assert mock_mem.add_message.call_count == 2
        user_call = mock_mem.add_message.call_args_list[0]
        assert user_call[0][0] == "user"
        assert user_call[0][1] == "Salut"
        assert user_call[1]["source"] == "frontend"
        asst_call = mock_mem.add_message.call_args_list[1]
        assert asst_call[0][0] == "assistant"
        assert asst_call[0][1] == "Hey !"

    @pytest.mark.asyncio
    async def test_attachments_meta_attached_to_user_message(self):
        mock_mem = MagicMock()
        mock_mem.add_message = AsyncMock()

        with patch("pipeline.broadcast.memory_manager", mock_mem):
            from pipeline.broadcast import persist_to_memory
            await persist_to_memory(
                message="regarde", response="chouette",
                source="frontend", person_id="u1",
                attachments_meta=[{"kind": "image", "name": "cat.png"}],
            )

        user_call = mock_mem.add_message.call_args_list[0]
        assert user_call[1]["attachments_meta"] == [{"kind": "image", "name": "cat.png"}]
        # Assistant message does not carry the attachments
        asst_call = mock_mem.add_message.call_args_list[1]
        assert "attachments_meta" not in asst_call[1] or not asst_call[1]["attachments_meta"]
