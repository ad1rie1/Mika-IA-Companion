"""File preprocessor — documents → extracted text.

Stub: produces a placeholder based on filename / mime type. Real
implementation should parse PDF/DOC/TXT/... and return the extracted
text (possibly truncated for prompt budget).
"""
from __future__ import annotations

import logging

from pipeline.perception import Part

logger = logging.getLogger(__name__)


# Known extensions we'd be able to parse — kept as a hint for the stub
# response. Real code would map extension → parser.
_KNOWN_EXTENSIONS = {"pdf", "txt", "md", "docx", "csv", "json"}


async def process(part: Part) -> Part:
    """Convert a file Part into a text Part with either extracted content
    (when parsing succeeds — not implemented in the stub) or a descriptor."""
    name = part.metadata.get("name") or "fichier"
    mime = part.mime_type or "application/octet-stream"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""

    parsable = ext in _KNOWN_EXTENSIONS
    hint = "extractable" if parsable else "non extractable directement"

    description = (
        f"[fichier joint: {name} ({mime}, {hint}) — "
        "extraction non implementee pour le moment]"
    )

    logger.debug("File stub processed name=%s mime=%s parsable=%s", name, mime, parsable)

    return Part(
        kind="text",
        content=description,
        metadata={
            **part.metadata,
            "original_kind": part.kind,
            "original_mime_type": part.mime_type,
            "preprocessor": "files-stub",
        },
    )
