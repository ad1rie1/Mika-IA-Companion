"""Perception — unified representation of anything that reaches Mika.

Replaces the ad-hoc `(message: str, source: str, person_id: str, attachments)`
tuple. A `Perception` carries:
  - a modality (text / image / audio / video / file / internal / sensor)
  - an intent (request a response, passive observation, internal trigger)
  - one or more `Part`s (multimodal content)
  - source / person_id / timestamp / arbitrary metadata

Why this exists:
  The current pipeline is "someone asked, Mika answers". Adding camera,
  audio streaming, or internal drive-driven initiatives doesn't fit that
  shape. A Perception lets us represent *any* stimulus — the router then
  decides if Mika responds, observes silently, or preprocesses it first.

Design constraints:
  - Dataclass only. No DB, no side effects. Serializable.
  - `Part.content` is str OR bytes — keeps binary-friendly while text
    paths stay zero-copy.
  - `text` property concatenates all text parts for legacy code paths
    that still expect a string.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class Modality(str, Enum):
    """Nature of the stimulus. Router dispatches partly on this."""
    TEXT = "text"              # chat message, typed input
    IMAGE = "image"            # single image upload or capture
    AUDIO = "audio"            # voice clip (typically needs transcription)
    VIDEO = "video"            # video clip (frames + audio)
    FILE = "file"              # document, PDF, generic binary
    MIXED = "mixed"            # text + image + ... (most common multimodal)
    INTERNAL = "internal"      # Mika's own initiative (conscience/drives/cron)
    SENSOR = "sensor"          # future: temperature, presence, etc.


class Intent(str, Enum):
    """What the source wants Mika to do about this perception."""
    REQUEST_RESPONSE = "request_response"  # explicit question → answer it
    OBSERVATION = "observation"            # passive input → maybe memorize, maybe act
    INTERNAL_TRIGGER = "internal_trigger"  # Mika-driven initiative → speak out


PartKind = str  # "text" | "image" | "audio" | "video" | "file"


@dataclass
class Part:
    """One piece of a perception's content.

    A purely-text chat message has one Part(kind="text").
    An image + caption has two Parts: text + image.
    Audio clips carry raw bytes plus optional transcript metadata.
    """
    kind: PartKind
    content: str | bytes
    mime_type: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class Perception:
    """A unified stimulus entering Mika's processing pipeline.

    Contracts:
      - `parts` is always non-empty (even an empty text message yields
        `[Part(kind="text", content="")]`), so downstream code can
        iterate without None checks.
      - `timestamp` is set at construction time unless the caller
        provides a specific value (e.g. replaying an event).
      - `metadata` is free-form per-source context: websocket channel
        name, email headers, raw module event payload, etc.
    """
    modality: Modality
    intent: Intent
    parts: list[Part]
    source: str
    person_id: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.parts:
            # Defensive: guarantee at least one part so downstream
            # assembly code never has to check for emptiness.
            self.parts = [Part(kind="text", content="")]

    @property
    def text(self) -> str:
        """Concatenated text content across all text parts.

        Non-text parts are NOT serialized here — preprocessors handle
        that (e.g. vision produces a Part(kind="text", content="[image...])").
        """
        return " ".join(
            str(p.content) for p in self.parts if p.kind == "text"
        ).strip()

    @property
    def requires_response(self) -> bool:
        """Fast path for the router: does the source explicitly want an answer?"""
        return self.intent is Intent.REQUEST_RESPONSE

    @property
    def is_internal(self) -> bool:
        """Was this perception produced by Mika herself (conscience/drives)?"""
        return self.intent is Intent.INTERNAL_TRIGGER or self.modality is Modality.INTERNAL

    def has_non_text(self) -> bool:
        """True if at least one Part is something other than text.

        Used by the router to decide whether to invoke a preprocessor
        (vision / audio / file) before handing off to the AI.
        """
        return any(p.kind != "text" for p in self.parts)

    # ── Constructors for common cases ─────────────────────────────

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        source: str,
        person_id: str,
        intent: Intent = Intent.REQUEST_RESPONSE,
        metadata: dict | None = None,
    ) -> "Perception":
        """Build a TEXT / REQUEST_RESPONSE perception from a plain string.

        This is the canonical constructor for WebSocket chat messages
        and Telegram text — the most common case.
        """
        return cls(
            modality=Modality.TEXT,
            intent=intent,
            parts=[Part(kind="text", content=text)],
            source=source,
            person_id=person_id,
            metadata=metadata or {},
        )

    @classmethod
    def from_internal_trigger(
        cls,
        prompt: str,
        *,
        source: str,
        person_id: str = "conscience_mika",
        metadata: dict | None = None,
    ) -> "Perception":
        """Build an INTERNAL_TRIGGER perception for Mika-driven initiatives
        (conscience acts, drive overflow, rumination resurfacing, cron)."""
        return cls(
            modality=Modality.INTERNAL,
            intent=Intent.INTERNAL_TRIGGER,
            parts=[Part(kind="text", content=prompt)],
            source=source,
            person_id=person_id,
            metadata=metadata or {},
        )

    @classmethod
    def from_mixed(
        cls,
        *,
        text: str,
        attachments: list,
        source: str,
        person_id: str,
        intent: Intent = Intent.REQUEST_RESPONSE,
        metadata: dict | None = None,
    ) -> "Perception":
        """Build a MIXED perception from text + attachment descriptors.

        `attachments` accepts three shapes, all normalized to ``Part``s:
          - raw WebSocket dicts: ``{"name", "type" (mime), "data" (base64)}``
          - pipeline-internal dicts: ``{"kind", "content"|"content_b64", "mime_type", ...}``
          - ``MediaAttachment`` dataclass instances (from validate_attachments())
        """
        parts: list[Part] = []
        if text.strip():
            parts.append(Part(kind="text", content=text))
        for att in attachments:
            parts.append(_part_from_attachment(att))

        modality = _dominant_modality(parts)
        return cls(
            modality=modality,
            intent=intent,
            parts=parts,
            source=source,
            person_id=person_id,
            metadata=metadata or {},
        )


def _normalize_attachment_kind(att: dict) -> str:
    raw = (att.get("kind") or "").lower()
    if raw in ("image", "img", "photo"):
        return "image"
    if raw in ("audio", "voice", "sound"):
        return "audio"
    if raw in ("video",):
        return "video"
    if raw in ("file", "document", "pdf"):
        return "file"
    # Fall back to MIME inference. "type" is also a MIME alias used by the
    # browser WebSocket payload (File.type).
    mime = (att.get("mime_type") or att.get("type") or "").lower()
    return _mime_to_kind(mime)


def _mime_to_kind(mime: str) -> str:
    mime = (mime or "").lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    return "file"


_CATEGORY_TO_KIND: dict[str, str] = {
    "image": "image",
    "audio": "audio",
    "video": "video",
    "text": "file",
    "unknown": "file",
}


def _part_from_attachment(att) -> Part:
    """Normalize an attachment (dict or MediaAttachment) into a Part."""
    # MediaAttachment duck-typing: it has `data`, `media_type`, `name`, `category`.
    if hasattr(att, "data") and hasattr(att, "media_type"):
        kind = _CATEGORY_TO_KIND.get(getattr(att, "category", "unknown"), "file")
        return Part(
            kind=kind,
            content=getattr(att, "data", ""),
            mime_type=getattr(att, "media_type", None),
            metadata={"name": getattr(att, "name", "")},
        )

    # Dict path — supports both the raw WebSocket shape and the
    # pipeline-internal shape.
    if not isinstance(att, dict):
        return Part(kind="file", content="", metadata={"unknown_attachment": repr(att)[:80]})

    kind = _normalize_attachment_kind(att)
    content = (
        att.get("content")
        or att.get("content_b64")
        or att.get("data")
        or ""
    )
    mime_type = att.get("mime_type") or att.get("type")
    metadata = {
        k: v for k, v in att.items()
        if k not in ("content", "content_b64", "data", "mime_type", "type", "kind")
    }
    return Part(kind=kind, content=content, mime_type=mime_type, metadata=metadata)


def _dominant_modality(parts: list[Part]) -> Modality:
    kinds = {p.kind for p in parts}
    if len(kinds) > 1 and "text" in kinds:
        return Modality.MIXED
    if kinds == {"text"}:
        return Modality.TEXT
    if kinds == {"image"}:
        return Modality.IMAGE
    if kinds == {"audio"}:
        return Modality.AUDIO
    if kinds == {"video"}:
        return Modality.VIDEO
    if kinds == {"file"}:
        return Modality.FILE
    return Modality.MIXED
