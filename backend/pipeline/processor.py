"""Conversation processor — the full pipeline from input to broadcast.

Orchestrates: context -> response -> emotion -> persist -> broadcast.
Each step lives in its own module for readability and testability.
"""

import logging
from dataclasses import dataclass

from emotion.engine import emotion_engine
from emotion.types import Emotion, EmotionData
from pipeline.broadcast import broadcast_to_websocket, emit_communication_event, persist_to_memory
from pipeline.context import ConversationContext, gather_context
from pipeline.response import call_ai_and_parse

logger = logging.getLogger(__name__)


@dataclass
class SpeechOutput:
    """Result of processing a message through the pipeline."""
    text: str
    emotion_data: EmotionData
    emotion_name: str
    emotion_intensity: float
    emotion_state: dict
    tool_calls: list[str]


# -- Main entry point ---------------------------------------------------------


async def process_message(
    message: str,
    source: str = "frontend",
    person_id: str = "anonymous",
    context: ConversationContext | None = None,
    broadcast: bool = True,
    persist: bool = True,
    emit_event: bool = True,
) -> SpeechOutput:
    """Full conversation pipeline: context -> AI -> emotion -> persist -> broadcast.

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

    # Hydrate person mood from DB if evicted from RAM since last interaction
    await emotion_engine.ensure_person_loaded(person_id)

    try:
        # 1. Assemble context
        if context is None:
            context = await gather_context(message, person_id)

        # 2. Prompt -> AI call -> emotion extraction
        response_text, emotion_data, tool_calls = await call_ai_and_parse(context, message)

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
        await persist_to_memory(message, response_text, source, person_id)

    # 5. Emit module event
    if emit_event:
        await emit_communication_event(source, person_id)

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
        await broadcast_to_websocket(output, source)

    return output
