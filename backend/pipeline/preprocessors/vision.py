"""Vision preprocessor — image → text description.

Stub: returns a placeholder description. Real implementation should
call a vision-capable model (Claude with images, GPT-4V, local VLM)
and replace the placeholder with an actual caption/description.

The replacement Part keeps the original metadata so downstream code
(memory retriever, consolidator) still knows an image was attached.
"""
from __future__ import annotations

import logging

from pipeline.perception import Part

logger = logging.getLogger(__name__)


async def process(part: Part) -> Part:
    """Convert an image Part into a text Part describing it."""
    name = part.metadata.get("name") or "image"
    mime = part.mime_type or "image"
    size_hint = _size_hint(part)

    # Stub placeholder. When a real vision model is wired in, replace
    # the `description` below with its output.
    description = (
        f"[image jointe: {name} ({mime}{size_hint}) — "
        "description visuelle non disponible pour le moment]"
    )

    logger.debug("Vision stub processed part name=%s mime=%s", name, mime)

    return Part(
        kind="text",
        content=description,
        metadata={
            **part.metadata,
            "original_kind": part.kind,
            "original_mime_type": part.mime_type,
            "preprocessor": "vision-stub",
        },
    )


def _size_hint(part: Part) -> str:
    """Best-effort size indicator for logs/prompts."""
    content = part.content
    if isinstance(content, (bytes, bytearray)):
        return f", {len(content)} bytes"
    if isinstance(content, str) and content:
        return f", ~{len(content)} chars"
    return ""
