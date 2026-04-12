"""Conversation processor — the full pipeline from input to broadcast.

Replaces the duplicated logic in:
- chat/consumers.py (handle_chat)
- modules/manager.py (_notify_ai)
- conscience/engine.py (_act)

Each of those now calls process_message() instead of reimplementing the pipeline.
"""

import logging
from dataclasses import dataclass

from channels.layers import get_channel_layer

from ai.client import claude_client
from emotion.engine import emotion_engine
from emotion.types import Emotion, EmotionData
from memory.manager import memory_manager
from pipeline.context import ConversationContext, gather_context

logger = logging.getLogger(__name__)

BROADCAST_GROUP = "vtuber_broadcast"


@dataclass
class SpeechOutput:
    """Result of processing a message through the pipeline."""
    text: str
    emotion_data: EmotionData
    emotion_name: str
    emotion_intensity: float
    emotion_state: dict
    tool_calls: list[str]


async def process_message(
    message: str,
    source: str = "frontend",
    person_id: str = "anonymous",
    context: ConversationContext | None = None,
    broadcast: bool = True,
    persist: bool = True,
    emit_event: bool = True,
) -> SpeechOutput:
    """Full conversation pipeline: context → AI → emotion → persist → broadcast.

    Args:
        message: The input message/prompt.
        source: Origin of the message (frontend, conscience, module name...).
        person_id: Who triggered this (person UUID, conscience_mika, module_*...).
        context: Pre-built context (if None, will be gathered automatically).
        broadcast: Whether to broadcast the response via WebSocket.
        persist: Whether to save messages to memory.
        emit_event: Whether to emit a module event after processing.
    """
    tool_calls = []

    try:
        # 1. Assemble context
        if context is None:
            context = await gather_context(message, person_id)

        # 2. Call AI
        if context.mcp_server and context.tool_names:
            response_text, emotion_data, tool_calls = await claude_client.chat_with_tools(
                message=message,
                conversation_history=context.history,
                memory_context=context.memory_context,
                emotion_context=context.emotion_context,
                module_context=context.module_context,
                mcp_server=context.mcp_server,
                tool_names=context.tool_names,
            )
        else:
            response_text, emotion_data = await claude_client.chat(
                message=message,
                conversation_history=context.history,
                memory_context=context.memory_context,
                emotion_context=context.emotion_context,
            )

        # 3. Process emotion
        emotion_engine.process_emotion(emotion_data, person_id)
        await emotion_engine._maybe_save_snapshot(person_id)

    except Exception:
        logger.exception("AI error while processing message")
        response_text = "Oups, j'ai eu un petit bug... Tu peux réessayer ?"
        emotion_data = EmotionData(emotion=Emotion.SAD, intensity=0.6)
        emotion_engine.process_emotion(emotion_data, person_id)

    # 4. Persist to memory
    if persist:
        await memory_manager.add_message(
            "user", message, source=source, person_id=person_id
        )
        await memory_manager.add_message(
            "assistant", response_text, person_id=person_id
        )

    # 5. Emit module event
    if emit_event:
        from modules.manager import module_manager
        from modules.types import ModuleEvent

        await module_manager.emit_event(
            ModuleEvent(
                event_type="chat.message",
                source_module=source,
                data={"person_id": person_id, "source": source},
            )
        )

    # 6. Compute final blended emotion
    msg_emotion = emotion_engine.compute_message_emotion(person_id)

    logger.info(
        "[%s/%s] %s -> %s (emotion=%s intensity=%.2f)",
        source, person_id,
        message[:60], response_text[:80],
        msg_emotion.emotion.value, msg_emotion.intensity,
    )

    # 7. Broadcast to WebSocket
    if broadcast:
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

    return SpeechOutput(
        text=response_text,
        emotion_data=emotion_data,
        emotion_name=msg_emotion.emotion.value,
        emotion_intensity=msg_emotion.intensity,
        emotion_state=emotion_engine.get_state_dict(person_id),
        tool_calls=tool_calls,
    )
