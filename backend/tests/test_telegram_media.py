"""Tests for inbound Telegram media handling.

Photos, voice notes and documents are downloaded, lifted into a MIXED
Perception and routed through the standard pipeline — the preprocessors
(vision / audio / files) do the actual content work downstream.
"""
from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from communication.channels.telegram import TelegramChannel


def _fake_tg_file(payload: bytes):
    f = SimpleNamespace()
    f.download_as_bytearray = AsyncMock(return_value=bytearray(payload))
    return f


def _fake_media(payload: bytes, *, mime=None, file_name=None, file_size=None):
    media = SimpleNamespace()
    media.mime_type = mime
    media.file_name = file_name
    media.file_size = file_size if file_size is not None else len(payload)
    media.get_file = AsyncMock(return_value=_fake_tg_file(payload))
    return media


def _fake_message(
    *, voice=None, audio=None, photo=None, document=None, caption=None,
):
    msg = SimpleNamespace()
    msg.voice = voice
    msg.audio = audio
    msg.photo = photo
    msg.document = document
    msg.caption = caption
    msg.text = None
    msg.chat_id = 4242
    msg.from_user = SimpleNamespace(id=99, full_name="Alice Test")
    msg.reply_text = AsyncMock()
    return msg


@pytest.mark.asyncio
class TestDownloadMedia:

    async def test_voice_note(self):
        payload = b"OggS\x00opus-data"
        msg = _fake_message(voice=_fake_media(payload, mime="audio/ogg"))
        att = await TelegramChannel()._download_media(msg)

        assert att is not None
        assert att.category == "audio"
        assert att.media_type == "audio/ogg"
        assert att.name == "note_vocale.ogg"
        assert base64.b64decode(att.data) == payload

    async def test_photo_takes_largest_resolution(self):
        small = _fake_media(b"small-jpg")
        large = _fake_media(b"large-jpg")
        msg = _fake_message(photo=[small, large])
        att = await TelegramChannel()._download_media(msg)

        assert att is not None
        assert att.category == "image"
        assert att.media_type == "image/jpeg"
        assert base64.b64decode(att.data) == b"large-jpg"
        large.get_file.assert_awaited()
        small.get_file.assert_not_awaited()

    async def test_document_keeps_name_and_mime(self):
        msg = _fake_message(
            document=_fake_media(
                b"contenu txt", mime="text/plain", file_name="notes.txt"
            )
        )
        att = await TelegramChannel()._download_media(msg)

        assert att is not None
        assert att.name == "notes.txt"
        assert att.category == "text"

    async def test_unknown_binary_document_still_accepted(self):
        msg = _fake_message(
            document=_fake_media(
                b"%PDF-1.4", mime="application/pdf", file_name="doc.pdf"
            )
        )
        att = await TelegramChannel()._download_media(msg)
        assert att is not None
        assert att.category == "unknown"  # → Part kind "file" → files preprocessor

    async def test_oversized_media_rejected_with_notice(self):
        from pipeline.media import MAX_FILE_SIZE_BYTES
        msg = _fake_message(
            document=_fake_media(
                b"x", mime="application/pdf", file_name="enorme.pdf",
                file_size=MAX_FILE_SIZE_BYTES + 1,
            )
        )
        att = await TelegramChannel()._download_media(msg)
        assert att is None
        msg.reply_text.assert_awaited()

    async def test_download_failure_returns_none(self):
        media = _fake_media(b"x", mime="audio/ogg")
        media.get_file = AsyncMock(side_effect=RuntimeError("network"))
        msg = _fake_message(voice=media)
        att = await TelegramChannel()._download_media(msg)
        assert att is None

    async def test_message_without_media_returns_none(self):
        msg = _fake_message()
        att = await TelegramChannel()._download_media(msg)
        assert att is None


@pytest.mark.asyncio
class TestHandleMedia:

    async def test_routes_mixed_perception_with_caption(self):
        channel = TelegramChannel()
        payload = b"fake-jpeg"
        msg = _fake_message(
            photo=[_fake_media(payload)], caption="regarde ça !"
        )
        update = SimpleNamespace(message=msg)

        captured = {}

        def fake_submit(perception):
            captured["p"] = perception
            return True

        with patch.object(
            TelegramChannel, "_register_interlocutor",
            new=AsyncMock(return_value=("tg_99", False)),
        ), patch("pipeline.turns.turn_queue.submit", new=fake_submit):
            await channel._handle_media(update, context=None)

        p = captured["p"]
        assert p.source == "telegram"
        assert p.person_id == "tg_99"
        kinds = {part.kind for part in p.parts}
        assert kinds == {"text", "image"}
        assert "regarde ça !" in p.text
        # La réponse revient par broadcast_to_websocket → deliver(), pas ici.
        msg.reply_text.assert_not_awaited()

    async def test_a_full_queue_is_refused_out_loud(self):
        channel = TelegramChannel()
        msg = _fake_message(voice=_fake_media(b"OggS", mime="audio/ogg"))
        update = SimpleNamespace(message=msg)

        with patch.object(
            TelegramChannel, "_register_interlocutor",
            new=AsyncMock(return_value=("tg_99", False)),
        ), patch("pipeline.turns.turn_queue.submit", return_value=False):
            await channel._handle_media(update, context=None)

        msg.reply_text.assert_awaited()
