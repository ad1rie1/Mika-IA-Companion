"""Recipient selection for proactive speech.

When Mika decides to speak on her own, she also decides *to whom*. The choice is
driven by who the triggering signal concerns (memory-grounded), then confirmed by
Mika via a ``[TO:person_id]`` tag — mirroring the existing ``[EMOTION:...]`` idiom.

This module holds the pure, side-effect-free parsing so it is trivially testable;
the orchestration (candidate gathering + AI call) lives on the engine.
"""

from __future__ import annotations

import re

_TO_RE = re.compile(r"\[TO:\s*([A-Za-z0-9_-]+)\s*\]", re.IGNORECASE)


def parse_to_tag(text: str, allowed: list[str]) -> str | None:
    """Extract the chosen recipient from a ``[TO:person_id]`` tag.

    Returns the person_id only if it is one of ``allowed`` (prevents the model
    from inventing or leaking an id). ``[TO:none]`` (or no tag / unknown id)
    means "address no one" → returns None.
    """
    if not text:
        return None
    match = _TO_RE.search(text)
    if not match:
        return None
    person_id = match.group(1)
    if person_id.lower() == "none":
        return None
    return person_id if person_id in allowed else None


def strip_to_tag(text: str) -> str:
    """Remove the ``[TO:...]`` tag from a message body before delivery."""
    return _TO_RE.sub("", text).strip()
