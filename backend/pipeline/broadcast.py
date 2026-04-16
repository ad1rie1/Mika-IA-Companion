"""Broadcast and event emission — side-effects after AI processing."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from channels.layers import get_channel_layer

from memory.manager import memory_manager
from modules.manager import module_manager
from modules.types import ModuleEvent

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
                "emotion_blend": output.emotion_blend or [],
                "source": source,
            },
        },
    )


async def emit_communication_event(source: str, person_id: str) -> None:
    """Emit a module event for the conversation turn."""
    await module_manager.emit_event(
        ModuleEvent(
            event_type="chat.message",
            source_module=source,
            data={"person_id": person_id, "source": source},
        )
    )


async def persist_to_memory(
    *,
    message: str,
    response: str,
    source: str,
    person_id: str,
    attachments_meta: list[dict] | None = None,
) -> None:
    """Save the user message (with any attachment descriptors) and the
    assistant response to memory.

    ``attachments_meta`` is attached to the user Message only, so later
    retrieval can see what was sent without keeping binary bytes in the
    conversation store.
    """
    await memory_manager.add_message(
        "user", message, source=source, person_id=person_id,
        attachments_meta=attachments_meta or [],
    )
    await memory_manager.add_message(
        "assistant", response, person_id=person_id,
    )
