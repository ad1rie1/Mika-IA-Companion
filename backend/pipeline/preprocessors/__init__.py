"""Modality preprocessors — turn non-text Parts into text Parts.

The router calls `run_preprocessors(perception)` before the AI step so
the LLM always sees a text prompt. Each preprocessor is responsible for
one modality: vision (image), audio (voice), files (documents).

Stubs for now — they produce placeholder descriptions so the full
pipeline works end-to-end without real LLM-based analysis. Replace
the `process()` body of each preprocessor when wiring a real provider.

Design notes:
  - Preprocessors MUTATE `perception.parts` in place: the non-text part
    is replaced with a `Part(kind="text", content="[description]")` and
    the original part's metadata is preserved via `metadata["original_kind"]`.
  - A preprocessor that fails must never raise into the router: it
    should log, leave the part untouched, and return. The AI will get
    an explicit "[image non disponible]" marker so it can apologize.
"""
from __future__ import annotations

import logging

from pipeline.perception import Part, Perception

logger = logging.getLogger(__name__)


async def run_preprocessors(perception: Perception) -> None:
    """Run modality-specific preprocessors on a perception.

    Walks the parts list; for each non-text Part, calls the matching
    preprocessor and replaces the Part with the resulting text Part.
    Mutates `perception.parts` in place.
    """
    from pipeline.preprocessors import audio, files, vision

    dispatch: dict[str, callable] = {
        "image": vision.process,
        "video": vision.process,  # frames reduce to images for now
        "audio": audio.process,
        "file": files.process,
    }

    new_parts: list[Part] = []
    for part in perception.parts:
        if part.kind == "text":
            new_parts.append(part)
            continue

        handler = dispatch.get(part.kind)
        if handler is None:
            logger.debug("No preprocessor for kind=%s, keeping raw part", part.kind)
            new_parts.append(part)
            continue

        try:
            replacement = await handler(part)
        except Exception:
            logger.exception("Preprocessor %s failed", part.kind)
            replacement = Part(
                kind="text",
                content=f"[{part.kind} non disponible]",
                metadata={"original_kind": part.kind, "error": True},
            )

        new_parts.append(replacement)

    perception.parts = new_parts
