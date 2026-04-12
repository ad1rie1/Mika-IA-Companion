"""Broadcast and event emission — side-effects after AI processing."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from channels.layers import get_channel_layer

if TYPE_CHECKING:
    from pipeline.processor import SpeechOutput

logger = logging.getLogger(__name__)

BROADCAST_GROUP = "vtuber_broadcast"


async def broadcast_to_websocket(output: SpeechOutput, source: str) -> None:
    """Broadcast the response to all connected WebSocket clients."""
    channel_layer = get_channel_layer()
    await channel_layer.group_send(
        BROADCAST_GROUP,
        {
            "type": "communication.broadcast",
            "data": {
                "type": "speech",
                "text": output.text,
                "emotion": output.emotion_name,
                "emotion_intensity": output.emotion_intensity,
                "emotion_state": output.emotion_state,
                "source": source,
            },
        },
    )


async def emit_communication_event(source: str, person_id: str) -> None:
    """Emit a module event for the conversation turn."""
    from modules.manager import module_manager
    from modules.types import ModuleEvent

    await module_manager.emit_event(
        ModuleEvent(
            event_type="chat.message",
            source_module=source,
            data={"person_id": person_id, "source": source},
        )
    )


async def persist_to_memory(
    message: str, response: str, source: str, person_id: str
) -> None:
    """Save user message and assistant response to memory."""
    from memory.manager import memory_manager

    await memory_manager.add_message(
        "user", message, source=source, person_id=person_id
    )
    await memory_manager.add_message(
        "assistant", response, person_id=person_id
    )
