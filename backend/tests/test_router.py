"""Tests for the Perception router.

The router dispatches based on Intent:
  - REQUEST_RESPONSE  → process_message with broadcast/persist/emit_event=True
  - INTERNAL_TRIGGER  → process_message with emit_event=False (Mika's own act)
  - OBSERVATION       → module_manager.emit_event, no process_message

Non-text perceptions also trigger preprocessing + raw media save; both
are best-effort and must not bubble exceptions.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pipeline.perception import Intent, Modality, Part, Perception


@pytest.mark.asyncio
class TestRequestResponseRoute:

    async def test_calls_process_message_with_correct_flags(self):
        from pipeline.router import perceive

        p = Perception.from_text("hey", source="frontend", person_id="u1")

        with patch("pipeline.processor.process_message",
                   new_callable=AsyncMock) as mock_proc:
            mock_proc.return_value = "ok"
            await perceive(p)

        args, kwargs = mock_proc.call_args
        # First positional arg is the perception itself.
        assert args[0] is p
        assert kwargs["broadcast"] is True
        assert kwargs["persist"] is True
        assert kwargs["emit_event"] is True


@pytest.mark.asyncio
class TestInternalTriggerRoute:

    async def test_internal_trigger_does_not_emit_event(self):
        from pipeline.router import perceive

        p = Perception.from_internal_trigger(
            "parle toi", source="conscience",
        )
        with patch("pipeline.processor.process_message",
                   new_callable=AsyncMock) as mock_proc:
            mock_proc.return_value = "ok"
            await perceive(p)

        args, kwargs = mock_proc.call_args
        assert args[0] is p
        assert kwargs["emit_event"] is False
        assert kwargs["broadcast"] is True
        assert kwargs["persist"] is True


@pytest.mark.asyncio
class TestObservationRoute:

    async def test_observation_does_not_call_process_message(self):
        from pipeline.router import perceive

        p = Perception(
            modality=Modality.SENSOR,
            intent=Intent.OBSERVATION,
            parts=[Part("text", "présence détectée")],
            source="camera",
            person_id="anonymous",
        )
        with patch("pipeline.processor.process_message",
                   new_callable=AsyncMock) as mock_proc, \
             patch("modules.manager.module_manager.emit_event",
                   new_callable=AsyncMock) as mock_emit:
            result = await perceive(p)

        mock_proc.assert_not_called()
        mock_emit.assert_called_once()
        emitted = mock_emit.call_args[0][0]
        # Event type carries the modality
        assert emitted.event_type.startswith("perception.")
        assert result is None


@pytest.mark.asyncio
class TestMediaPath:

    async def test_non_text_perception_calls_save_raw_media(self):
        from pipeline.router import perceive

        p = Perception.from_mixed(
            text="look",
            attachments=[{"kind": "image", "content": b"\x00", "mime_type": "image/png"}],
            source="frontend", person_id="u1",
        )

        with patch("pipeline.router._save_raw_media",
                   new_callable=AsyncMock) as mock_save, \
             patch("pipeline.processor.process_message",
                   new_callable=AsyncMock):
            await perceive(p)

        mock_save.assert_called_once()

    async def test_media_save_failure_does_not_break_pipeline(self):
        from pipeline.router import perceive

        p = Perception.from_mixed(
            text="look",
            attachments=[{"kind": "image", "content": b"\x00", "mime_type": "image/png"}],
            source="frontend", person_id="u1",
        )

        with patch("pipeline.router._save_raw_media",
                   new_callable=AsyncMock, side_effect=RuntimeError("disk full")), \
             patch("pipeline.processor.process_message",
                   new_callable=AsyncMock) as mock_proc:
            # Must not raise
            await perceive(p)

        mock_proc.assert_called_once()

    async def test_text_only_perception_skips_media_save(self):
        from pipeline.router import perceive

        p = Perception.from_text("hi", source="frontend", person_id="u1")

        with patch("pipeline.router._save_raw_media",
                   new_callable=AsyncMock) as mock_save, \
             patch("pipeline.processor.process_message",
                   new_callable=AsyncMock):
            await perceive(p)

        mock_save.assert_not_called()
