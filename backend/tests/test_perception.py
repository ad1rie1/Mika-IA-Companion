"""Tests for the Perception dataclass + constructors."""
from __future__ import annotations

import pytest

from pipeline.perception import Intent, Modality, Part, Perception


class TestPart:

    def test_text_part(self):
        p = Part(kind="text", content="hello")
        assert p.kind == "text"
        assert p.content == "hello"
        assert p.mime_type is None
        assert p.metadata == {}

    def test_image_part_with_mime(self):
        p = Part(kind="image", content=b"\x89PNG...", mime_type="image/png",
                 metadata={"name": "cat.png"})
        assert p.mime_type == "image/png"
        assert p.metadata["name"] == "cat.png"


class TestPerceptionDefaults:

    def test_empty_parts_gets_default_text_part(self):
        """Contract: parts is always non-empty so downstream code can iterate."""
        perc = Perception(
            modality=Modality.TEXT, intent=Intent.REQUEST_RESPONSE,
            parts=[], source="test", person_id="x",
        )
        assert len(perc.parts) == 1
        assert perc.parts[0].kind == "text"
        assert perc.parts[0].content == ""

    def test_timestamp_set_automatically(self):
        perc = Perception(
            modality=Modality.TEXT, intent=Intent.REQUEST_RESPONSE,
            parts=[Part("text", "hi")], source="t", person_id="x",
        )
        assert perc.timestamp > 0


class TestFromText:

    def test_text_source_person_defaults(self):
        p = Perception.from_text("hello", source="frontend", person_id="alice")
        assert p.modality is Modality.TEXT
        assert p.intent is Intent.REQUEST_RESPONSE
        assert p.text == "hello"
        assert p.source == "frontend"
        assert p.person_id == "alice"

    def test_intent_override(self):
        p = Perception.from_text("hi", source="x", person_id="y",
                                 intent=Intent.OBSERVATION)
        assert p.intent is Intent.OBSERVATION


class TestFromInternalTrigger:

    def test_defaults_to_conscience_person(self):
        p = Perception.from_internal_trigger("parle", source="conscience")
        assert p.person_id == "conscience_mika"
        assert p.modality is Modality.INTERNAL
        assert p.intent is Intent.INTERNAL_TRIGGER
        assert p.text == "parle"

    def test_is_internal_property(self):
        p = Perception.from_internal_trigger("x", source="drives")
        assert p.is_internal is True

    def test_request_response_is_not_internal(self):
        p = Perception.from_text("hi", source="frontend", person_id="x")
        assert p.is_internal is False


class TestFromMixed:

    def test_text_plus_image(self):
        p = Perception.from_mixed(
            text="regarde ce chat",
            attachments=[
                {"kind": "image", "content": "base64data", "mime_type": "image/png", "name": "cat.png"},
            ],
            source="frontend", person_id="alice",
        )
        assert p.modality is Modality.MIXED
        assert len(p.parts) == 2
        assert p.parts[0].kind == "text"
        assert p.parts[1].kind == "image"
        assert p.parts[1].metadata.get("name") == "cat.png"
        assert p.has_non_text() is True

    def test_image_only_no_text(self):
        """Empty text → only the image part is kept."""
        p = Perception.from_mixed(
            text="",
            attachments=[{"kind": "image", "content": "bytes", "mime_type": "image/jpeg"}],
            source="frontend", person_id="alice",
        )
        assert p.modality is Modality.IMAGE
        assert len(p.parts) == 1
        assert p.parts[0].kind == "image"

    def test_attachment_kind_inferred_from_mime(self):
        p = Perception.from_mixed(
            text="x",
            attachments=[{"content": "audio_bytes", "mime_type": "audio/mpeg"}],
            source="frontend", person_id="a",
        )
        # First part is text (the "x"), second is audio
        assert p.parts[1].kind == "audio"

    def test_unknown_attachment_falls_back_to_file(self):
        p = Perception.from_mixed(
            text="",
            attachments=[{"content": "bytes", "mime_type": "application/octet-stream"}],
            source="x", person_id="y",
        )
        assert p.parts[0].kind == "file"


class TestProperties:

    def test_text_concatenates_text_parts_only(self):
        p = Perception(
            modality=Modality.MIXED, intent=Intent.REQUEST_RESPONSE,
            parts=[
                Part("text", "hello"),
                Part("image", b"\x00\x01"),
                Part("text", "world"),
            ],
            source="x", person_id="y",
        )
        assert p.text == "hello world"

    def test_requires_response_only_for_request_response(self):
        for intent, expected in [
            (Intent.REQUEST_RESPONSE, True),
            (Intent.OBSERVATION, False),
            (Intent.INTERNAL_TRIGGER, False),
        ]:
            p = Perception(
                modality=Modality.TEXT, intent=intent,
                parts=[Part("text", "")], source="x", person_id="y",
            )
            assert p.requires_response is expected

    def test_has_non_text_false_for_pure_text(self):
        p = Perception.from_text("hi", source="x", person_id="y")
        assert p.has_non_text() is False

    def test_has_non_text_true_for_mixed(self):
        p = Perception.from_mixed(
            text="t", attachments=[{"kind": "image", "content": "b"}],
            source="x", person_id="y",
        )
        assert p.has_non_text() is True
