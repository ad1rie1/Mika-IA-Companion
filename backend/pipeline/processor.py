"""Conversation processor — the full pipeline from input to broadcast.

Orchestrates: context → prompt → AI call → emotion → persist → broadcast.
Each step is a named function for readability and testability.
"""

import logging
from dataclasses import dataclass

from channels.layers import get_channel_layer

from ai.client import ai_client
from emotion.engine import emotion_engine
from emotion.types import Emotion, EmotionData, extract_emotion
from memory.manager import memory_manager
from pipeline.context import ConversationContext, gather_context
from pipeline.prompt import build_system_prompt, format_conversation

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


# ── Step helpers ─────────────────────────────────────────────────


async def _call_ai(
    context: ConversationContext, message: str
) -> tuple[str, EmotionData, list[str]]:
    """Build prompt, call AI, extract emotion from response."""
    system = build_system_prompt(
        context.emotion_context, context.memory_context, context.module_context
    )
    user_prompt = format_conversation(message, context.history)

    if context.mcp_server and context.tool_names:
        raw_text, tool_calls = await ai_client.complete_with_tools(
            system_prompt=system,
            user_prompt=user_prompt,
            mcp_server=context.mcp_server,
            tool_names=context.tool_names,
        )
    else:
        raw_text = await ai_client.complete(
            system_prompt=system,
            user_prompt=user_prompt,
        )
        tool_calls = []

    clean_text, emotion_data = extract_emotion(raw_text)
    return clean_text, emotion_data, tool_calls


async def _persist_to_memory(
    message: str, response: str, source: str, person_id: str
) -> None:
    """Save user message and assistant response to memory."""
    await memory_manager.add_message(
        "user", message, source=source, person_id=person_id
    )
    await memory_manager.add_message(
        "assistant", response, person_id=person_id
    )


async def _emit_chat_event(source: str, person_id: str) -> None:
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


async def _broadcast_to_websocket(output: SpeechOutput, source: str) -> None:
    """Broadcast the response to all connected WebSocket clients."""
    channel_layer = get_channel_layer()
    await channel_layer.group_send(
        BROADCAST_GROUP,
        {
            "type": "chat.broadcast",
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


# ── Main entry point ─────────────────────────────────────────────


async def process_message(
    message: str,
    source: str = "frontend",
    person_id: str = "anonymous",
    context: ConversationContext | None = None,
    broadcast: bool = True,
    persist: bool = True,
    emit_event: bool = True,
) -> SpeechOutput:
    """Full conversation pipeline: context → prompt → AI → emotion → persist → broadcast.

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

        # 2. Prompt → AI call → emotion extraction
        response_text, emotion_data, tool_calls = await _call_ai(context, message)

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
        await _persist_to_memory(message, response_text, source, person_id)

    # 5. Emit module event
    if emit_event:
        await _emit_chat_event(source, person_id)

    # 6. Compute final blended emotion
    msg_emotion = emotion_engine.compute_message_emotion(person_id)

    logger.info(
        "[%s/%s] %s -> %s (emotion=%s intensity=%.2f)",
        source, person_id,
        message[:60], response_text[:80],
        msg_emotion.emotion.value, msg_emotion.intensity,
    )

    output = SpeechOutput(
        text=response_text,
        emotion_data=emotion_data,
        emotion_name=msg_emotion.emotion.value,
        emotion_intensity=msg_emotion.intensity,
        emotion_state=emotion_engine.get_state_dict(person_id),
        tool_calls=tool_calls,
    )

    # 7. Broadcast to WebSocket
    if broadcast:
        await _broadcast_to_websocket(output, source)

    return output
