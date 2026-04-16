"""WebSocket channel — direct browser/frontend connection.

Builds `Perception`s and routes them through `pipeline.router.perceive()`.
No longer calls `process_message` directly.
"""
from __future__ import annotations

import json
import logging
import uuid

from channels.generic.websocket import AsyncWebsocketConsumer

from pipeline.media import validate_attachments
from pipeline.perception import Intent, Perception
from pipeline.router import perceive

logger = logging.getLogger(__name__)

BROADCAST_GROUP = "vtuber_broadcast"
MAX_MESSAGE_LENGTH = 2000


class WebSocketConsumer(AsyncWebsocketConsumer):
    """WebSocket channel — handles browser/frontend connections to the VTuber."""

    async def connect(self):
        await self.channel_layer.group_add(BROADCAST_GROUP, self.channel_name)
        await self.accept()

        # Per-connection anonymous ID. Clients that want persistent identity
        # should pass their own `person_id` in every chat message.
        self.person_id = str(uuid.uuid4())[:8]

        # Greeting routed through the pipeline as an INTERNAL_TRIGGER so
        # the conscience, memory, and emotion state see it as a real turn.
        from config.personality import personality

        greeting_perception = Perception.from_internal_trigger(
            prompt=f"Un nouveau visiteur vient de se connecter. "
                   f"Accueille-le avec ta phrase habituelle: {personality.greeting}",
            source="web_connect",
            person_id=self.person_id,
            metadata={"channel": self.channel_name},
        )
        await perceive(greeting_perception)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(BROADCAST_GROUP, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        try:
            data = json.loads(text_data)
        except (json.JSONDecodeError, TypeError):
            return

        if data.get("type") != "chat":
            return

        message = data.get("message", "")
        raw_attachments = data.get("attachments", [])

        if not isinstance(message, str):
            message = ""
        has_attachments = (
            isinstance(raw_attachments, list) and len(raw_attachments) > 0
        )
        if not message.strip() and not has_attachments:
            return

        # Client-provided person_id (persistent identity) beats the
        # per-connection UUID. Enables the theory-of-mind feature to
        # recognize returning users across sessions.
        person_id = data.get("person_id", getattr(self, "person_id", "anonymous"))

        attachments = (
            validate_attachments(raw_attachments) if has_attachments else None
        )

        clean_message = message.strip()[:MAX_MESSAGE_LENGTH]

        if attachments:
            perception = Perception.from_mixed(
                text=clean_message,
                attachments=attachments,
                source="frontend",
                person_id=person_id,
                intent=Intent.REQUEST_RESPONSE,
            )
        else:
            perception = Perception.from_text(
                clean_message,
                source="frontend",
                person_id=person_id,
                intent=Intent.REQUEST_RESPONSE,
            )

        await perceive(perception)

    # --- Group message handler ---

    async def communication_broadcast(self, event):
        """Called when the broadcast group sends a message."""
        await self.send(text_data=json.dumps(event["data"], ensure_ascii=False))
