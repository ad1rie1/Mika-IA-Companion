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

    async def test_replaces_image_with_text_part(self):
        part = Part(
            kind="image",
            content=b"\x89PNG\r\n\x1a\n",
            mime_type="image/png",
            metadata={"name": "cat.png"},
        )
        result = await vision.process(part)
        assert result.kind == "text"
        assert "cat.png" in result.content
        assert result.metadata["original_kind"] == "image"
        assert result.metadata["preprocessor"] == "vision-stub"

    async def test_preserves_original_metadata(self):
        part = Part(
            kind="image", content=b"x", mime_type="image/jpeg",
            metadata={"name": "pic.jpg", "custom": 42},
        )
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
        p = Perception.from_mixed(
            text="regarde",
            attachments=[
                {"kind": "image", "content": b"\x00", "mime_type": "image/png",
                 "name": "img.png"},
            ],
            source="frontend", person_id="u",
        )
        await run_preprocessors(p)
        assert all(part.kind == "text" for part in p.parts)
        # The descriptive text includes the file name
        joined = " ".join(p.text for p in p.parts) if False else p.text
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
