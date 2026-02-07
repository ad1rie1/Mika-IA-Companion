import json
import logging

from channels.generic.websocket import AsyncWebSocketConsumer
from channels.layers import get_channel_layer

from ai.client import claude_client
from ai.emotions import Emotion
from config.personality import personality
from memory.manager import memory_manager

logger = logging.getLogger(__name__)

BROADCAST_GROUP = "vtuber_broadcast"
MAX_MESSAGE_LENGTH = 2000


class ChatConsumer(AsyncWebSocketConsumer):
    """WebSocket consumer for the VTuber chat."""

    async def connect(self):
        await self.channel_layer.group_add(BROADCAST_GROUP, self.channel_name)
        await self.accept()

        # Send greeting
        await self.send(text_data=json.dumps(
            {
                "type": "speech",
                "text": personality.greeting,
                "emotion": Emotion.HAPPY.value,
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
            await handle_chat(message.strip()[:MAX_MESSAGE_LENGTH], source="frontend")

    # --- Group message handler ---

    async def chat_broadcast(self, event):
        """Called when the broadcast group sends a message."""
        await self.send(text_data=json.dumps(event["data"], ensure_ascii=False))


async def handle_chat(message: str, source: str = "frontend"):
    """Process a chat message from any source and broadcast to all clients."""
    try:
        history = memory_manager.get_conversation_context()
        response_text, emotion = await claude_client.chat(message, history)
    except Exception:
        logger.exception("Claude API error while processing message")
        response_text = "Oups, j'ai eu un petit bug... Tu peux réessayer ?"
        emotion = Emotion.SAD

    await memory_manager.add_message("user", message, source=source)
    await memory_manager.add_message("assistant", response_text)

    channel_layer = get_channel_layer()
    await channel_layer.group_send(
        BROADCAST_GROUP,
        {
            "type": "chat.broadcast",
            "data": {
                "type": "speech",
                "text": response_text,
                "emotion": emotion.value,
                "source": source,
            },
        },
    )

    return response_text, emotion
