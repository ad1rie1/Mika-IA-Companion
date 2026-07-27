"""Perception router — the single entry point for any stimulus.

Every channel (web frontend, Telegram, modules, conscience, drives, cron)
builds a `Perception` and calls `perceive(perception)`. The router
decides what to do:

  - REQUEST_RESPONSE → full pipeline (process_message) → broadcast answer
  - OBSERVATION      → save media + emit module event → let the conscience
                       decide if/when Mika should react
  - INTERNAL_TRIGGER → full pipeline but as Mika's own initiative
                       (typically broadcast=True, persist=True, emit_event=False
                       because the conscience already produced this)

Non-text modalities get preprocessed first: image → description, audio →
transcript, file → extracted text. Preprocessors replace/augment the
Perception's parts in place, then the router proceeds with the enriched
perception.

Why this indirection matters:
  - Adding a new channel = write an adapter that builds Perception, done.
  - Adding a new modality = write a preprocessor, done.
  - Conscience can intercept observations and choose silence — not every
    stimulus forces a response. That's the biggest win over the old
    `handle_message()` which always produced speech.
"""
from __future__ import annotations

import logging

from pipeline.perception import Intent, Modality, Perception

logger = logging.getLogger(__name__)


async def perceive(perception: Perception):
    """Route a Perception to the appropriate handler.

    Returns the `SpeechOutput` for REQUEST_RESPONSE / INTERNAL_TRIGGER,
    or None for OBSERVATION (no response produced).
    """
    logger.debug(
        "Perception received: modality=%s intent=%s source=%s person=%s parts=%d",
        perception.modality.value, perception.intent.value,
        perception.source, perception.person_id, len(perception.parts),
    )

    # 1. Save any raw media + detach heavy payloads. Non-fatal — failures
    #    in media handling must not break the AI loop.
    if perception.has_non_text():
        try:
            await _save_raw_media(perception)
        except Exception:
            logger.exception("Raw media save failed (continuing)")

    # 2. Preprocess non-text parts (vision/audio/files → text descriptions).
    #    Preprocessors mutate `perception.parts` in place so the downstream
    #    pipeline sees enriched text.
    if perception.has_non_text():
        try:
            await _preprocess(perception)
        except Exception:
            logger.exception("Preprocessing failed (continuing with raw perception)")

    # 3. Dispatch on intent.
    if perception.intent is Intent.OBSERVATION:
        return await _route_observation(perception)
    if perception.intent is Intent.INTERNAL_TRIGGER:
        return await _route_internal(perception)
    # default: REQUEST_RESPONSE
    return await _route_request_response(perception)


# ── Intent handlers ──────────────────────────────────────────────


async def _route_request_response(perception: Perception):
    """User-facing message expecting an answer. Full pipeline, broadcast."""
    from pipeline.processor import process_message

    return await process_message(
        perception,
        broadcast=True,
        persist=True,
        emit_event=True,
    )


async def _route_internal(perception: Perception):
    """Mika's own initiative (conscience act, drive overflow, rumination, cron).

    - broadcast=True: clients still see her speak (it's a real utterance).
    - persist=True: her own speech matters for future consolidation.
    - emit_event=False: the conscience already decided to speak, no need
      to loop the event back to itself.
    """
    from pipeline.processor import process_message

    return await process_message(
        perception,
        broadcast=True,
        persist=True,
        emit_event=False,
    )


async def _route_observation(perception: Perception):
    """Passive stimulus. No AI call forced — the conscience observes it and
    will decide later (in its decision loop) whether to act.

    We do:
      - emit a module event so subscribers (conscience) see the stimulus
      - skip persist_to_memory (observations don't become user/assistant
        messages; they may be promoted to Souvenir later by the consolidator
        if the conscience deems them memory-worthy)
    """
    from modules.manager import module_manager
    from modules.types import ModuleEvent

    event_type = f"perception.{perception.modality.value}"
    await module_manager.emit_event(
        ModuleEvent(
            event_type=event_type,
            source_module=perception.source,
            data={
                "person_id": perception.person_id,
                "text": perception.text,
                "modality": perception.modality.value,
                "parts_count": len(perception.parts),
                **perception.metadata,
            },
        )
    )
    return None


# ── Media + preprocessing helpers ────────────────────────────────


_PART_KIND_TO_CATEGORY: dict[str, str] = {
    "image": "image",
    "audio": "audio",
    "video": "video",
    "file": "unknown",
}


async def _save_raw_media(perception: Perception) -> None:
    """Persist binary attachments to disk + DB via the existing media helper.

    Only non-text Parts are processed. Each one becomes a
    ``MediaAttachment`` (disk + BDD + FilesModule registration).
    """
    media_parts = [p for p in perception.parts if p.kind != "text"]
    if not media_parts:
        return
    try:
        from pipeline.media import MediaAttachment, save_attachments
    except ImportError:
        logger.debug("pipeline.media not available, skipping raw media save")
        return

    attachments: list[MediaAttachment] = []
    for p in media_parts:
        data = p.content if isinstance(p.content, str) else ""
        attachments.append(
            MediaAttachment(
                name=str(p.metadata.get("name", "fichier")),
                media_type=p.mime_type or "application/octet-stream",
                data=data,
                category=_PART_KIND_TO_CATEGORY.get(p.kind, "unknown"),
            )
        )
    await save_attachments(attachments, person_id=perception.person_id)


async def _preprocess(perception: Perception) -> None:
    """Replace non-text Parts with text via modality-specific preprocessors:
    image → vision caption, audio → Whisper transcript, file → extracted
    text. Each degrades to a safe placeholder on failure.
    """
    try:
        from pipeline.preprocessors import run_preprocessors
    except ImportError:
        logger.debug("No preprocessors package yet — leaving parts untouched")
        return

    await run_preprocessors(perception)
