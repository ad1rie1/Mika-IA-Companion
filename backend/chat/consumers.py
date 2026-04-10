import json
import logging
import uuid

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.layers import get_channel_layer

from ai.client import claude_client
from ai.emotion_engine import emotion_engine
from ai.emotion_types import Emotion, EmotionData
from config.personality import personality
from memory.manager import memory_manager

logger = logging.getLogger(__name__)

BROADCAST_GROUP = "vtuber_broadcast"
MAX_MESSAGE_LENGTH = 2000


class ChatConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for the VTuber chat."""

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

            await handle_chat(
                message.strip()[:MAX_MESSAGE_LENGTH],
                source="frontend",
                person_id=person_id,
            )

    # --- Group message handler ---

    async def chat_broadcast(self, event):
        """Called when the broadcast group sends a message."""
        await self.send(text_data=json.dumps(event["data"], ensure_ascii=False))


async def handle_chat(
    message: str,
    source: str = "frontend",
    person_id: str = "anonymous",
):
    """Process a chat message from any source and broadcast to all clients."""
    from modules.manager import module_manager

    try:
        # Get memory context (boosted for this person)
        memory_context = await memory_manager.get_memory_context(message, person_id=person_id)

        # Get emotion context for this person
        emotion_context = emotion_engine.get_emotion_context(person_id)

        # Get module context for system prompt
        module_context = module_manager.collect_context()

        history = memory_manager.get_conversation_context()

        # Use tool-enabled path if modules expose tools
        mcp_server = module_manager.get_mcp_server()
        tool_names = module_manager.get_tool_names()

        if mcp_server and tool_names:
            response_text, emotion_data, _ = await claude_client.chat_with_tools(
                message, history,
                memory_context=memory_context,
                emotion_context=emotion_context,
                module_context=module_context,
                mcp_server=mcp_server,
                tool_names=tool_names,
            )
        else:
            response_text, emotion_data = await claude_client.chat(
                message, history,
                memory_context=memory_context,
                emotion_context=emotion_context,
            )

        # Process through EmotionEngine (transitions, momentum, opposition, bleed)
        updated_person = emotion_engine.process_emotion(emotion_data, person_id)

    except Exception:
        logger.exception("Claude API error while processing message")
        response_text = "Oups, j'ai eu un petit bug... Tu peux réessayer ?"
        emotion_data = EmotionData(emotion=Emotion.SAD, intensity=0.6)
        updated_person = emotion_engine.process_emotion(emotion_data, person_id)

    await memory_manager.add_message("user", message, source=source, person_id=person_id)
    await memory_manager.add_message("assistant", response_text, person_id=person_id)

    # Notify modules + Conscience of chat activity (idle tracking, observation)
    from modules.types import ModuleEvent

    await module_manager.emit_event(
        ModuleEvent(
            event_type="chat.message",
            source_module="chat",
            data={"person_id": person_id, "source": source},
        )
    )

    # Compute final message emotion (blend of person + global)
    msg_emotion = emotion_engine.compute_message_emotion(person_id)

    logger.info(
        "[%s/%s] %s -> %s (emotion=%s intensity=%.2f)",
        source, person_id,
        message[:60], response_text[:80],
        msg_emotion.emotion.value, msg_emotion.intensity,
    )

    channel_layer = get_channel_layer()
    await channel_layer.group_send(
        BROADCAST_GROUP,
        {
            "type": "chat.broadcast",
            "data": {
                "type": "speech",
                "text": response_text,
                "emotion": msg_emotion.emotion.value,
                "emotion_intensity": msg_emotion.intensity,
                "emotion_state": emotion_engine.get_state_dict(person_id),
                "source": source,
            },
        },
    )

    return response_text, emotion_data
