"""Tests for modality preprocessors.

Preprocessors replace non-text Parts with text Parts carrying a
description / transcript / extract. They must never raise into the
router — a failing preprocessor emits a placeholder Part with
``metadata['error']=True``.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pipeline.perception import Intent, Modality, Part, Perception
from pipeline.preprocessors import run_preprocessors
from pipeline.preprocessors import audio, files, vision


@pytest.mark.asyncio
class TestVisionPreprocessor:

    async def test_calls_llm_and_wraps_response(self):
        """Vision should call ai_router with the image and return a text Part."""
        part = Part(
            kind="image",
            content="aGVsbG8=",  # base64 of "hello" — shape only matters
            mime_type="image/png",
            metadata={"name": "cat.png"},
        )
        with patch("pipeline.preprocessors.vision.ai_router") as router:
            router.complete = AsyncMock(
                return_value="[image: un chat roux sur un canape gris.]"
            )
            result = await vision.process(part)

        assert result.kind == "text"
        assert "chat roux" in result.content
        assert result.metadata["original_kind"] == "image"
        assert result.metadata["preprocessor"] == "vision"
        # Router must have received an image attachment
        kw = router.complete.call_args.kwargs
        attachments = kw["attachments"]
        assert len(attachments) == 1
        att = attachments[0]
        assert att.category == "image"
        assert att.media_type == "image/png"
        assert att.data == "aGVsbG8="
        assert att.name == "cat.png"

    async def test_accepts_raw_bytes_content(self):
        """A Part whose content is raw bytes is base64-encoded before the call."""
        import base64
        raw = b"\x89PNG\r\n\x1a\nfake"
        part = Part(
            kind="image", content=raw, mime_type="image/png",
            metadata={"name": "x.png"},
        )
        with patch("pipeline.preprocessors.vision.ai_router") as router:
            router.complete = AsyncMock(return_value="[image: descr]")
            await vision.process(part)

        attachments = router.complete.call_args.kwargs["attachments"]
        assert attachments[0].data == base64.b64encode(raw).decode("ascii")

    async def test_llm_failure_returns_placeholder(self):
        """On LLM error the preprocessor returns a safe placeholder Part."""
        part = Part(
            kind="image", content="b64", mime_type="image/png",
            metadata={"name": "oops.png"},
        )
        with patch("pipeline.preprocessors.vision.ai_router") as router:
            router.complete = AsyncMock(side_effect=RuntimeError("provider down"))
            result = await vision.process(part)

        assert result.kind == "text"
        assert "oops.png" in result.content
        assert "indisponible" in result.content.lower()

    async def test_llm_timeout_returns_placeholder(self):
        import asyncio
        part = Part(
            kind="image", content="b64", mime_type="image/png",
            metadata={"name": "slow.png"},
        )

        async def hang(*a, **k):
            await asyncio.sleep(10)

        with patch("pipeline.preprocessors.vision.ai_router") as router, \
             patch("pipeline.preprocessors.vision.VISION_TIMEOUT_SECONDS", 0.05):
            router.complete = hang  # so wait_for times out
            result = await vision.process(part)

        assert result.kind == "text"
        assert "indisponible" in result.content.lower()

    async def test_empty_content_short_circuits(self):
        """No base64 and no bytes → skip the LLM call."""
        part = Part(kind="image", content="", mime_type="image/png",
                    metadata={"name": "empty.png"})
        with patch("pipeline.preprocessors.vision.ai_router") as router:
            router.complete = AsyncMock()
            result = await vision.process(part)

        router.complete.assert_not_called()
        assert "indisponible" in result.content.lower()

    async def test_caption_length_capped(self):
        """Runaway captions are truncated to MAX_CAPTION_CHARS."""
        from pipeline.preprocessors.vision import MAX_CAPTION_CHARS
        long_caption = "[image: " + ("très long " * 1000) + "]"
        part = Part(
            kind="image", content="b64", mime_type="image/png",
            metadata={"name": "long.png"},
        )
        with patch("pipeline.preprocessors.vision.ai_router") as router:
            router.complete = AsyncMock(return_value=long_caption)
            result = await vision.process(part)

        assert len(result.content) <= MAX_CAPTION_CHARS + 5

    async def test_caption_missing_prefix_gets_wrapped(self):
        """If the LLM forgets the '[image:' marker, we wrap it in."""
        part = Part(
            kind="image", content="b64", mime_type="image/png",
            metadata={"name": "shy.png"},
        )
        with patch("pipeline.preprocessors.vision.ai_router") as router:
            router.complete = AsyncMock(return_value="un tableau abstrait rouge")
            result = await vision.process(part)

        assert result.content.startswith("[image:")
        assert "abstrait" in result.content
        assert "shy.png" in result.content

    async def test_preserves_original_metadata(self):
        part = Part(
            kind="image", content="b64", mime_type="image/jpeg",
            metadata={"name": "pic.jpg", "custom": 42},
        )
        with patch("pipeline.preprocessors.vision.ai_router") as router:
            router.complete = AsyncMock(return_value="[image: scene]")
            result = await vision.process(part)

        assert result.metadata["custom"] == 42
        assert result.metadata["original_mime_type"] == "image/jpeg"


@pytest.mark.asyncio
class TestAudioPreprocessor:

    async def test_replaces_audio_with_text(self):
        part = Part(kind="audio", content=b"\x00", mime_type="audio/mpeg")
        result = await audio.process(part)
        assert result.kind == "text"
        assert "transcription" in result.content

    async def test_duration_included_in_description(self):
        part = Part(
            kind="audio", content=b"\x00", mime_type="audio/wav",
            metadata={"duration_seconds": 12},
        )
        result = await audio.process(part)
        assert "12s" in result.content


@pytest.mark.asyncio
class TestFilesPreprocessor:

    async def test_extractable_hint_for_pdf(self):
        part = Part(
            kind="file", content=b"\x00", mime_type="application/pdf",
            metadata={"name": "report.pdf"},
        )
        result = await files.process(part)
        assert result.kind == "text"
        assert "report.pdf" in result.content
        assert "extractable" in result.content

    async def test_unknown_extension_marked_non_extractable(self):
        part = Part(
            kind="file", content=b"\x00", mime_type="application/x-7z-compressed",
            metadata={"name": "archive.7z"},
        )
        result = await files.process(part)
        assert "non extractable" in result.content


@pytest.mark.asyncio
class TestRunPreprocessors:

    async def test_text_only_perception_unchanged(self):
        p = Perception.from_text("hello", source="test", person_id="u")
        original = list(p.parts)
        await run_preprocessors(p)
        # Same length, same kind (text), same content
        assert len(p.parts) == len(original)
        assert p.parts[0].kind == "text"
        assert p.parts[0].content == "hello"

    async def test_image_perception_becomes_all_text(self):
        """Even when the LLM is unavailable, the preprocessor must leave the
        perception in an all-text state (placeholder replaces the image)."""
        p = Perception.from_mixed(
            text="regarde",
            attachments=[
                {"kind": "image", "content": b"\x00", "mime_type": "image/png",
                 "name": "img.png"},
            ],
            source="frontend", person_id="u",
        )
        with patch("pipeline.preprocessors.vision.ai_router") as router:
            router.complete = AsyncMock(side_effect=RuntimeError("no provider"))
            await run_preprocessors(p)

        assert all(part.kind == "text" for part in p.parts)
        assert "img.png" in p.text

    async def test_handler_failure_yields_error_placeholder(self):
        p = Perception.from_mixed(
            text="",
            attachments=[{"kind": "image", "content": b"\x00", "mime_type": "image/x"}],
            source="frontend", person_id="u",
        )
        with patch.object(vision, "process",
                          new=AsyncMock(side_effect=RuntimeError("vision broke"))):
            await run_preprocessors(p)

        # Must not have raised; the part must be a text error placeholder
        error_parts = [x for x in p.parts if x.metadata.get("error")]
        assert error_parts
        assert "non disponible" in error_parts[0].content

    async def test_image_perception_becomes_all_text_via_llm(self):
        """Full path: image Part → vision LLM called → text Part inserted."""
        p = Perception.from_mixed(
            text="regarde",
            attachments=[
                {"kind": "image", "content": "b64data", "mime_type": "image/png",
                 "name": "img.png"},
            ],
            source="frontend", person_id="u",
        )
        with patch("pipeline.preprocessors.vision.ai_router") as router:
            router.complete = AsyncMock(return_value="[image: un ciel etoile]")
            await run_preprocessors(p)

        assert all(part.kind == "text" for part in p.parts)
        assert "ciel etoile" in p.text

    async def test_unknown_kind_is_left_untouched(self):
        """Extensible: if a new modality ships without a preprocessor,
        we keep the original Part rather than dropping it silently."""
        p = Perception(
            modality=Modality.SENSOR,
            intent=Intent.OBSERVATION,
            parts=[
                Part(kind="text", content="context"),
                Part(kind="ultrasound", content=b"\x00"),  # not in dispatch
            ],
            source="sensor", person_id="anon",
        )
        await run_preprocessors(p)
        # Ultrasound part kept as-is
        kinds = [x.kind for x in p.parts]
        assert "ultrasound" in kinds
