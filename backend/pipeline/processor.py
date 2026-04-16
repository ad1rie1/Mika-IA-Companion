"""Conversation processor — the full pipeline from Perception to broadcast.

Orchestrates: context -> response -> emotion -> persist -> broadcast.
Each step lives in its own module for readability and testability.

Entry point takes a ``Perception`` built by the router. Multimodal and
multi-part content flows through without string serialization: preprocessors
upstream enrich non-text parts with text descriptions that end up in
``perception.text`` when we need a prompt, but the structured parts are
preserved in the persisted ``Message.attachments_meta``.
"""

import asyncio
import logging
from dataclasses import dataclass

from django.conf import settings

from emotion.engine import emotion_engine
from emotion.types import Emotion, EmotionData
from pipeline.broadcast import broadcast_to_websocket, emit_communication_event, persist_to_memory
from pipeline.context import ConversationContext, gather_context
from pipeline.perception import Perception
from pipeline.response import call_ai_and_parse
from pipeline.tracing import set_new_request_id

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
    request_id: str = "-"
    # Top-K emotion components for ambivalence display on the frontend.
    # List of {"emotion": str, "weight": float}.
    emotion_blend: list | None = None


# -- Main entry point ---------------------------------------------------------


async def process_message(
    perception: Perception,
    *,
    context: ConversationContext | None = None,
    broadcast: bool = True,
    persist: bool = True,
    emit_event: bool = True,
) -> SpeechOutput:
    """Full conversation pipeline: context -> AI -> emotion -> persist -> broadcast.

    Args:
        perception: The input stimulus. Carries source, person_id, parts, etc.
        context: Pre-built context (if None, gathered from the perception).
        broadcast: Whether to broadcast the response via WebSocket.
        persist: Whether to save the exchange in memory.
        emit_event: Whether to emit a ``chat.message`` module event after.
    """
    request_id = set_new_request_id()
    tool_calls = []

    source = perception.source
    person_id = perception.person_id
    # text property concatenates all text Parts. Preprocessors have
    # already serialized images/audio/files into text descriptions.
    message = perception.text

    # Hydrate person mood from DB if evicted from RAM since last interaction
    await emotion_engine.ensure_person_loaded(person_id)

    ai_failed = False
    timeout_seconds = getattr(settings, "AI_CALL_TIMEOUT", 60)

    try:
        # 1. Assemble context (memory, emotion, modules, self-concept, ...)
        if context is None:
            context = await gather_context(message, person_id)

        # 2. Prompt -> AI call -> emotion extraction (bounded by timeout)
        response_text, emotion_data, tool_calls = await asyncio.wait_for(
            call_ai_and_parse(context, message),
            timeout=timeout_seconds,
        )

        # 3. Process emotion (only on success — a crashed AI is not the
        #    user's fault and should not color Mika's mood toward them)
        emotion_engine.process_emotion(emotion_data, person_id)
        await emotion_engine._maybe_save_snapshot(person_id)

    except asyncio.TimeoutError:
        logger.warning(
            "AI call timed out after %ds (person=%s, source=%s)",
            timeout_seconds, person_id, source,
        )
        ai_failed = True
        response_text = "Hmm, je reflechis plus lentement que prevu... Laisse-moi un instant."
        emotion_data = EmotionData(emotion=Emotion.NEUTRAL, intensity=0.0)
    except Exception:
        logger.exception(
            "AI error while processing message (person=%s, source=%s)",
            person_id, source,
        )
        ai_failed = True
        response_text = "Oups, j'ai eu un petit bug... Tu peux reessayer ?"
        emotion_data = EmotionData(emotion=Emotion.NEUTRAL, intensity=0.0)
        # A light global-mood perturbation reflects Mika's own frustration
        # at her technical failure — not a relational emotion toward the user.
        emotion_engine.process_emotion(
            EmotionData(Emotion.ANXIOUS, 0.1), "conscience_mika",
        )

    # 4. Persist to memory — skip on failure to avoid pollution.
    if persist and not ai_failed:
        attachments_meta = _serialize_attachments_meta(perception)
        await persist_to_memory(
            message=message,
            response=response_text,
            source=source,
            person_id=person_id,
            attachments_meta=attachments_meta,
        )

    # 5. Emit module event — also skipped on failure.
    if emit_event and not ai_failed:
        await emit_communication_event(source, person_id)

    # 6. Compute final blended emotion for the reply's display.
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
        request_id=request_id,
        emotion_blend=[
            {"emotion": e.value, "weight": round(w, 2)}
            for e, w in msg_emotion.blend
        ],
    )

    # 7. Broadcast to WebSocket
    if broadcast:
        await broadcast_to_websocket(output, source)

    return output


def _serialize_attachments_meta(perception: Perception) -> list[dict]:
    """Extract a JSON-friendly descriptor for each non-text part.

    Binary content is not stored here — the router has already saved
    raw media to disk/DB via pipeline.media. This is purely structural
    metadata (kind, mime_type, name, ...) that lives alongside the
    persisted user Message so later retrieval knows what was attached.
    """
    meta: list[dict] = []
    for p in perception.parts:
        if p.kind == "text":
            continue
        meta.append({
            "kind": p.kind,
            "mime_type": p.mime_type,
            **p.metadata,
        })
    return meta
