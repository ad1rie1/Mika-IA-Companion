"""Audio preprocessor — voice → transcript.

Stub: returns a placeholder with a duration hint if available. Real
implementation should call a speech-to-text provider (Whisper, local
model, cloud API) and set the Part content to the transcript.
"""
from __future__ import annotations

import logging

from pipeline.perception import Part

logger = logging.getLogger(__name__)


async def process(part: Part) -> Part:
    """Convert an audio Part into a text transcript Part."""
    duration = part.metadata.get("duration_seconds")
    mime = part.mime_type or "audio"
    label = f"audio {mime}"
    if duration:
        label += f", ~{int(duration)}s"

    # Stub placeholder. Real transcription goes here.
    transcript = f"[{label}: transcription non disponible pour le moment]"

    logger.debug("Audio stub processed mime=%s duration=%s", mime, duration)

    return Part(
        kind="text",
        content=transcript,
        metadata={
            **part.metadata,
            "original_kind": part.kind,
            "original_mime_type": part.mime_type,
            "preprocessor": "audio-stub",
        },
    )
