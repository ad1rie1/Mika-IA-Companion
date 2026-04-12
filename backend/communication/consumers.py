import json
import logging
import uuid

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.layers import get_channel_layer

from emotion.engine import emotion_engine
from emotion.types import Emotion
from config.personality import personality

logger = logging.getLogger(__name__)

BROADCAST_GROUP = "vtuber_broadcast"
MAX_MESSAGE_LENGTH = 2000


class CommunicationConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer — one of the communication channels to the VTuber."""

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
            if not isinstance(message, str) or not message.strip():
                return

            # Allow client to provide a person_id, otherwise use connection-generated one
            person_id = data.get("person_id", getattr(self, "person_id", "anonymous"))

            await handle_message(
                message.strip()[:MAX_MESSAGE_LENGTH],
                source="frontend",
                person_id=person_id,
            )

    # --- Group message handler ---

    async def communication_broadcast(self, event):
        """Called when the broadcast group sends a message."""
        await self.send(text_data=json.dumps(event["data"], ensure_ascii=False))


async def handle_message(
    message: str,
    source: str = "frontend",
    person_id: str = "anonymous",
):
    """Process an incoming message from any communication channel via the pipeline."""
    from pipeline.processor import process_message

    output = await process_message(
        message=message,
        source=source,
        person_id=person_id,
    )
    return output.text, output.emotion_data
