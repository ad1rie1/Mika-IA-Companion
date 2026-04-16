"""Vision preprocessor — image → text description via a multimodal LLM.

Takes an image `Part` (with base64 content + MIME type) and replaces it
with a text `Part` holding a natural-language description. The provider
is chosen by `AIRole.VISION_CAPTION` (defaults to Claude sonnet-light).

Design:
  - The preprocessor only *captions* — it doesn't react emotionally or
    interpret. That's the downstream pipeline's job. The caption needs
    to be neutral, factual, and compact so it slots cleanly into the
    conversation prompt alongside text.
  - Failures are caught by the caller (`run_preprocessors`) and turned
    into an error placeholder. Here we just log + raise.
  - The prompt is tuned for ~2-3 sentences of description to keep
    prompt budget reasonable when multiple images arrive at once.

Fallback:
  - Empty content → empty description (skip the LLM call entirely).
  - Non-base64 content → treated as already-decoded text description
    (tests / hand-built Parts).
"""
from __future__ import annotations

import asyncio
import logging

from ai.router import AIRole, ai_router
from pipeline.media import MediaAttachment
from pipeline.perception import Part

logger = logging.getLogger(__name__)


# Caption prompt kept short, neutral, and explicitly instructed to avoid
# inference beyond what's visible. No "the user seems..." speculation —
# the downstream AI will reason about the image once it has the facts.
VISION_SYSTEM_PROMPT = (
    "Tu decris de maniere factuelle et concise une image qui vient d'etre envoyee. "
    "2 a 3 phrases maximum, en francais. "
    "Decris ce qui est visible (sujet principal, scene, contexte), sans speculer "
    "sur les intentions ou emotions de la personne qui l'a envoyee. "
    "Commence par '[image:' et termine par ']'. "
    "Si l'image est illisible ou trop floue, ecris '[image: non interpretable]'."
)

VISION_USER_PROMPT = "Decris cette image."

# Hard ceiling on caption length so a rogue model doesn't blow up the
# downstream prompt budget.
MAX_CAPTION_CHARS = 600

# Timeout per image (seconds). A single image description shouldn't take
# anywhere near this long; caller can cap if invoking many at once.
VISION_TIMEOUT_SECONDS = 30


async def process(part: Part) -> Part:
    """Convert an image Part into a text Part describing it.

    Returns a Part(kind="text", content="[image: ...]") that the
    downstream prompt assembler treats like any other text chunk.
    """
    name = part.metadata.get("name") or "image"
    mime = part.mime_type or "image/png"

    caption_text = await _caption(part, name=name, mime=mime)
    if not caption_text:
        caption_text = f"[image: {name} — description indisponible]"

    return Part(
        kind="text",
        content=caption_text,
        metadata={
            **part.metadata,
            "original_kind": part.kind,
            "original_mime_type": part.mime_type,
            "preprocessor": "vision",
        },
    )


# ── Internals ─────────────────────────────────────────────────


async def _caption(part: Part, *, name: str, mime: str) -> str:
    """Run the multimodal captioning call. Returns '' on failure."""
    attachment = _attachment_from_part(part, name=name, mime=mime)
    if attachment is None:
        logger.debug("Vision: part has no usable content, skipping LLM")
        return ""

    try:
        raw = await asyncio.wait_for(
            ai_router.complete(
                role=AIRole.VISION_CAPTION,
                system_prompt=VISION_SYSTEM_PROMPT,
                user_prompt=VISION_USER_PROMPT,
                attachments=[attachment],
            ),
            timeout=VISION_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("Vision caption timed out (name=%s, mime=%s)", name, mime)
        return ""
    except Exception:
        logger.exception("Vision caption failed (name=%s, mime=%s)", name, mime)
        return ""

    return _clean_caption(raw, name=name)


def _attachment_from_part(part: Part, *, name: str, mime: str) -> MediaAttachment | None:
    """Build a MediaAttachment from a Part.

    The Part's content is expected to be a base64 string (what the
    WebSocket payload carries) or bytes (from a preprocessor chain).
    If neither, we give up and let the caller produce a placeholder.
    """
    content = part.content
    if isinstance(content, bytes):
        import base64
        data_b64 = base64.b64encode(content).decode("ascii")
    elif isinstance(content, str) and content:
        data_b64 = content
    else:
        return None

    return MediaAttachment(
        name=name,
        media_type=mime,
        data=data_b64,
        category="image",
    )


def _clean_caption(raw: str, *, name: str) -> str:
    """Trim, cap length, and ensure the caption fits the '[image: ...]' shape."""
    if not raw:
        return ""
    cleaned = raw.strip()
    if len(cleaned) > MAX_CAPTION_CHARS:
        cleaned = cleaned[: MAX_CAPTION_CHARS - 3].rstrip() + "...]"
    # Some models wrap in quotes or forget the opening marker — normalize.
    if not cleaned.startswith("[image"):
        cleaned = f"[image: {name} — {cleaned.lstrip('[').rstrip(']')}]"
    return cleaned
