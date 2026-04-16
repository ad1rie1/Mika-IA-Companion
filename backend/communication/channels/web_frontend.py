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

        # Per-connection anonymous fallback ID. A client that uses the
        # IdentityService on the frontend will replace this via the
        # `identify` handshake before any chat is sent, so PersonProfile
        # / Commitment / EmotionalSummary lookups hit a stable entity.
        self.person_id = "anon_" + str(uuid.uuid4())[:8]
        self.display_name: str | None = None
        self._greeted = False

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(BROADCAST_GROUP, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        try:
            data = json.loads(text_data)
        except (json.JSONDecodeError, TypeError):
            return

        msg_type = data.get("type")

        if msg_type == "identify":
            # Handshake: client declares its persistent identity. We bind
            # it to the consumer and only NOW emit the greeting, so the
            # INTERNAL_TRIGGER Perception uses the stable person_id.
            await self._handle_identify(data)
            return

        if msg_type != "chat":
            return

        # Defensive: if the client never sent identify, still produce the
        # greeting once on the first chat turn. The anon_ ID will be used.
        if not self._greeted:
            await self._send_greeting()

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

    async def _handle_identify(self, data: dict) -> None:
        """Bind the consumer to the client's persistent identity + greet."""
        claimed_id = data.get("person_id")
        display = data.get("display_name")

        if isinstance(claimed_id, str) and claimed_id.strip():
            self.person_id = claimed_id.strip()[:100]
        if isinstance(display, str) and display.strip():
            self.display_name = display.strip()[:80]
            # Ensure the corresponding Entity exists so PersonProfile lookups
            # resolve. Uses the display name as the Entity.name if provided,
            # otherwise the person_id itself so profiles still accumulate.
            await self._ensure_entity(self.display_name)
        else:
            await self._ensure_entity(self.person_id)

        logger.info(
            "WS identify: person_id=%s display=%s channel=%s",
            self.person_id, self.display_name, self.channel_name,
        )

        if not self._greeted:
            await self._send_greeting()

    async def _send_greeting(self) -> None:
        """Produce the initial greeting as an INTERNAL_TRIGGER Perception."""
        from config.personality import personality

        self._greeted = True

        recognized = (
            f" Tu reconnais cette personne: {self.display_name}."
            if self.display_name
            else ""
        )
        greeting_perception = Perception.from_internal_trigger(
            prompt=(
                f"Un visiteur vient de se connecter.{recognized} "
                f"Accueille-le avec ta phrase habituelle: {personality.greeting}"
            ),
            source="web_connect",
            person_id=self.person_id,
            metadata={
                "channel": self.channel_name,
                "display_name": self.display_name,
            },
        )
        await perceive(greeting_perception)

    @staticmethod
    async def _ensure_entity(name: str) -> None:
        """Make sure a person-Entity exists with this name so theory-of-mind
        lookups (PersonProfile via entity__name=person_id) succeed.

        A first-time visitor won't have a profile yet, but the Entity row
        is what lets the consolidator and conscience accumulate material
        around them from the first exchange on.
        """
        if not name:
            return
        try:
            from asgiref.sync import sync_to_async
            from memory.models import Entity

            await sync_to_async(Entity.objects.get_or_create)(
                name=name, entity_type="person",
            )
        except Exception:
            logger.debug("ensure_entity failed for %s", name, exc_info=True)

    # --- Group message handler ---

    async def communication_broadcast(self, event):
        """Called when the broadcast group sends a message."""
        await self.send(text_data=json.dumps(event["data"], ensure_ascii=False))
