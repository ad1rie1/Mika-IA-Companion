"""WebSocket channel — direct browser/frontend connection."""

import json
import logging
import uuid

from channels.generic.websocket import AsyncWebsocketConsumer

from emotion.engine import emotion_engine
from emotion.types import Emotion
from config.personality import personality
from pipeline.media import validate_attachments

logger = logging.getLogger(__name__)

BROADCAST_GROUP = "vtuber_broadcast"
MAX_MESSAGE_LENGTH = 2000


class WebSocketConsumer(AsyncWebsocketConsumer):
    """WebSocket channel — handles browser/frontend connections to the VTuber."""

    async def connect(self):
        await self.channel_layer.group_add(BROADCAST_GROUP, self.channel_name)
        await self.accept()

        # Generate a unique person_id for this connection
        self.person_id = str(uuid.uuid4())[:8]

        # Send greeting with current emotional state
        msg_emotion = emotion_engine.compute_message_emotion(self.person_id)
        await self.send(text_data=json.dumps(
            {
                "type": "speech",
                "text": personality.greeting,
                "emotion": Emotion.HAPPY.value,
                "emotion_intensity": 0.7,
                "emotion_state": emotion_engine.get_state_dict(self.person_id),
            },
            ensure_ascii=False,
        ))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(BROADCAST_GROUP, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        try:
            data = json.loads(text_data)
        except (json.JSONDecodeError, TypeError):
            return

        if data.get("type") == "chat":
            message = data.get("message", "")
            raw_attachments = data.get("attachments", [])

            # Allow message-only (attachment without text) or text-only
            if not isinstance(message, str):
                message = ""
            has_attachments = isinstance(raw_attachments, list) and len(raw_attachments) > 0
            if not message.strip() and not has_attachments:
                return

            # Allow client to provide a person_id, otherwise use connection-generated one
            person_id = data.get("person_id", getattr(self, "person_id", "anonymous"))

            attachments = validate_attachments(raw_attachments) if has_attachments else None

            from communication.handler import handle_message

            await handle_message(
                message.strip()[:MAX_MESSAGE_LENGTH],
                source="frontend",
                person_id=person_id,
                attachments=attachments,
            )

    # --- Group message handler ---

    async def communication_broadcast(self, event):
        """Called when the broadcast group sends a message."""
        await self.send(text_data=json.dumps(event["data"], ensure_ascii=False))
