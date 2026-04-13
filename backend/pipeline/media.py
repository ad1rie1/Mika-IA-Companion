"""Media attachment processing — validation, transcription, text extraction.

Supported categories:
  - image  → passed as vision content blocks to Claude/OpenAI
  - audio  → transcribed via OpenAI Whisper if OPENAI_API_KEY is set
  - text   → decoded and injected as text in the user prompt
  - unknown → filename only, mentioned in the prompt
"""

from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
ALLOWED_AUDIO_TYPES = {
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/ogg",
    "audio/webm", "audio/mp4", "audio/x-wav",
}
ALLOWED_TEXT_TYPES = {
    "text/plain", "text/csv", "text/markdown", "text/html",
    "application/json", "application/xml",
}

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB decoded
MAX_ATTACHMENTS = 5
MAX_TEXT_CHARS = 8_000  # injected text cap


@dataclass
class MediaAttachment:
    """A single file attachment from the client."""
    name: str
    media_type: str
    data: str       # Base64-encoded, no data-URI prefix
    category: str   # "image" | "audio" | "text" | "unknown"

    @classmethod
    def from_ws_dict(cls, raw: dict) -> "MediaAttachment":
        name = str(raw.get("name", "fichier"))
        media_type = str(raw.get("type", "application/octet-stream")).lower().split(";")[0].strip()
        data = str(raw.get("data", ""))
        if "," in data:
            data = data.split(",", 1)[1]
        category = _categorize(media_type)
        return cls(name=name, media_type=media_type, data=data, category=category)

    def decoded_bytes(self) -> bytes:
        return base64.b64decode(self.data + "==")  # padding-safe

    def size_bytes(self) -> int:
        return len(self.data) * 3 // 4


def _categorize(media_type: str) -> str:
    if media_type in ALLOWED_IMAGE_TYPES:
        return "image"
    if media_type in ALLOWED_AUDIO_TYPES:
        return "audio"
    if media_type in ALLOWED_TEXT_TYPES or media_type.startswith("text/"):
        return "text"
    return "unknown"


def validate_attachments(raw_list: list) -> list[MediaAttachment]:
    """Parse and validate attachments from the WebSocket message."""
    if not raw_list or not isinstance(raw_list, list):
        return []
    result = []
    for raw in raw_list[:MAX_ATTACHMENTS]:
        if not isinstance(raw, dict):
            continue
        try:
            att = MediaAttachment.from_ws_dict(raw)
            if att.size_bytes() > MAX_FILE_SIZE_BYTES:
                logger.warning("Pièce jointe trop grande ignorée: %s (%d bytes)", att.name, att.size_bytes())
                continue
            result.append(att)
        except Exception:
            logger.warning("Pièce jointe invalide ignorée", exc_info=True)
    return result


async def transcribe_audio(attachment: MediaAttachment) -> str | None:
    """Transcribe audio via OpenAI Whisper API. Returns text or None."""
    try:
        from django.conf import settings
        api_key = getattr(settings, "OPENAI_API_KEY", "") or None
        if not api_key:
            return None
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key)
        audio_bytes = attachment.decoded_bytes()
        ext = _audio_ext(attachment.media_type)
        buf = io.BytesIO(audio_bytes)
        buf.name = f"{attachment.name or 'audio'}{ext}"
        transcript = await client.audio.transcriptions.create(model="whisper-1", file=buf)
        return transcript.text
    except Exception:
        logger.warning("Transcription audio échouée: %s", attachment.name, exc_info=True)
        return None


def read_text_attachment(attachment: MediaAttachment) -> str | None:
    """Decode a text attachment and return its content (capped at MAX_TEXT_CHARS)."""
    try:
        text = attachment.decoded_bytes().decode("utf-8", errors="replace")
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS] + "\n[...tronqué]"
        return text
    except Exception:
        logger.warning("Lecture fichier texte échouée: %s", attachment.name)
        return None


def _audio_ext(media_type: str) -> str:
    return {
        "audio/mpeg": ".mp3", "audio/mp3": ".mp3",
        "audio/wav": ".wav", "audio/x-wav": ".wav",
        "audio/ogg": ".ogg", "audio/webm": ".webm",
        "audio/mp4": ".mp4",
    }.get(media_type, ".bin")
