"""Audio preprocessor — voice → transcript.

Turns an audio Part (voice note, clip) into a text Part carrying the
transcript. Speech-to-text goes through the OpenAI provider's Whisper
endpoint — the only provider exposing a mature STT API today — resolved
via the AI router's cache so credential rotation keeps working.

Design mirrors vision.py:
  - transcription only, no interpretation. The downstream pipeline
    reacts to *what was said*; prosody stays out of scope.
  - every failure path (no provider configured, timeout, API error,
    empty/corrupt audio) degrades to the historical placeholder so the
    pipeline keeps flowing. An error is never surfaced as content.
"""
from __future__ import annotations

import asyncio
import base64
import logging

from old.backend.configs.runtime import cfg_int
from old.backend.pipeline.perception import Part

logger = logging.getLogger(__name__)

# Whisper handles long clips, but an inline chat voice note is capped at
# 5 MB upstream — 45s covers the upload + inference round-trip.
# Repli de ``pipeline.audio.transcribe_timeout_seconds``, que
# ``files_service.op_transcribe`` lit aussi.
TRANSCRIBE_TIMEOUT_SECONDS = 45


def transcribe_timeout_seconds() -> int:
    """Échéance d'une transcription, telle que configurée.

    Exposée plutôt qu'inlinée : l'outil ``files_transcribe`` fait le même
    appel STT et se borne pareil, sans redéclarer la valeur.
    """
    return cfg_int("pipeline.audio.transcribe_timeout_seconds",
                   TRANSCRIBE_TIMEOUT_SECONDS, mini=1)

# Ceiling on the transcript injected into the prompt. A voice note that
# transcribes longer than this is truncated, not dropped.
# Repli de ``pipeline.audio.max_transcript_chars``.
MAX_TRANSCRIPT_CHARS = 2000


async def process(part: Part) -> Part:
    """Convert an audio Part into a text transcript Part."""
    duration = part.metadata.get("duration_seconds")
    mime = part.mime_type or "audio"
    label = f"audio {mime}"
    if duration:
        label += f", ~{int(duration)}s"

    transcript = await _transcribe(part, mime=mime)

    if transcript:
        content = f"[message vocal transcrit ({label})] « {transcript} »"
        preprocessor = "audio-whisper"
    else:
        content = f"[{label}: transcription non disponible pour le moment]"
        preprocessor = "audio-stub"

    return Part(
        kind="text",
        content=content,
        metadata={
            **part.metadata,
            "original_kind": part.kind,
            "original_mime_type": part.mime_type,
            "preprocessor": preprocessor,
        },
    )


# ── Internals ─────────────────────────────────────────────────


async def _transcribe(part: Part, *, mime: str) -> str:
    """Run speech-to-text on the Part's payload. Returns '' on any failure."""
    data = _decode_bytes(part.content)
    if not data:
        logger.debug("Audio: part has no usable content, skipping transcription")
        return ""

    provider = _transcription_provider()
    if provider is None:
        return ""

    filename = _filename_for(part, mime=mime)
    try:
        raw = await asyncio.wait_for(
            provider.transcribe_audio(data, filename),
            timeout=transcribe_timeout_seconds(),
        )
    except asyncio.TimeoutError:
        logger.warning("Audio transcription timed out (mime=%s, %d bytes)", mime, len(data))
        return ""
    except Exception:
        logger.exception("Audio transcription failed (mime=%s)", mime)
        return ""

    plafond = cfg_int("pipeline.audio.max_transcript_chars",
                      MAX_TRANSCRIPT_CHARS, mini=4)
    cleaned = (raw or "").strip()
    if len(cleaned) > plafond:
        cleaned = cleaned[: plafond - 3].rstrip() + "..."
    return cleaned


def _transcription_provider():
    """The provider exposing speech-to-text, or None when unconfigured.

    Resolved through the router's provider cache rather than instantiated
    fresh: a credential rotation in the dashboard evicts the instance, so
    the next voice note authenticates with the new key.
    """
    try:
        from old.backend.ai.router import ai_router
        provider = ai_router.provider_by_name("openai")
    except Exception:
        logger.debug("No transcription provider available", exc_info=True)
        return None
    return provider if hasattr(provider, "transcribe_audio") else None


def _filename_for(part: Part, *, mime: str) -> str:
    """Whisper sniffs the container format from the filename extension."""
    name = str(part.metadata.get("name") or "")
    if "." in name:
        return name
    try:
        from old.backend.pipeline.media import _ext_for
        return f"voice{_ext_for(mime, name)}"
    except Exception:
        return "voice.ogg"


def _decode_bytes(content) -> bytes:
    """Part content arrives as raw bytes or a base64 string."""
    if isinstance(content, bytes):
        return content
    if isinstance(content, str) and content:
        try:
            padding = 4 - len(content) % 4
            return base64.b64decode(content + "=" * (padding % 4))
        except Exception:
            logger.debug("Audio: content is neither bytes nor valid base64")
            return b""
    return b""
