"""Tests for the `inner_state` payload attached to each `speech` broadcast.

The broadcast carries a snapshot of Mika's inner life so the frontend
can refresh its panels without polling:
  - drives (always present — in-RAM)
  - self_narrative (if a SelfNarrative row exists)
  - ruminations (top-5 active)
  - person_profile + pending_commitments (when person_id resolves to an
    Entity with a profile)

Internal / anonymous person_ids (``anonymous``, ``conscience_mika``,
``__global__``, ``anon_*``) must never leak into person_profile.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import sync_to_async

from pipeline.broadcast import _collect_inner_state, broadcast_to_websocket
from pipeline.processor import SpeechOutput


def _output(text: str = "salut") -> SpeechOutput:
    from emotion.types import Emotion, EmotionData
    return SpeechOutput(
        text=text,
        emotion_data=EmotionData(Emotion.HAPPY, 0.6),
        emotion_name="happy",
        emotion_intensity=0.6,
        emotion_state={},
        tool_calls=[],
        emotion_blend=[{"emotion": "happy", "weight": 0.6}],
    )


class TestInnerStateDrives:
    """Drives are in-RAM, always available, always present in the payload."""

    @pytest.mark.asyncio
    async def test_drives_always_present(self):
        state = await _collect_inner_state(person_id=None)
        assert "drives" in state
        # All 4 drives must appear
        for kind in ("curiosity", "social", "expression", "rest"):
            assert kind in state["drives"]
            assert "tension" in state["drives"][kind]


@pytest.mark.django_db(transaction=True)
class TestInnerStateSelfNarrative:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from memory.models import SelfNarrative
        SelfNarrative.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_absent_when_no_narrative_row(self):
        state = await _collect_inner_state(person_id=None)
        assert "self_narrative" not in state

    @pytest.mark.asyncio
    async def test_latest_narrative_serialized(self):
        from memory.models import SelfNarrative
        await sync_to_async(SelfNarrative.objects.create)(
            content="Je suis quelqu'un qui code trop tard le soir.",
            key_themes=["code", "nuit"],
            key_people=["Thomas"],
            dominant_mood="happy",
        )
        state = await _collect_inner_state(person_id=None)
        assert state["self_narrative"]["content"].startswith("Je suis")
        assert state["self_narrative"]["key_themes"] == ["code", "nuit"]
        assert state["self_narrative"]["key_people"] == ["Thomas"]
        assert state["self_narrative"]["dominant_mood"] == "happy"


@pytest.mark.django_db(transaction=True)
class TestInnerStateRuminations:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from conscience.models import Rumination
        Rumination.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_empty_list_when_none(self):
        state = await _collect_inner_state(person_id=None)
        assert state.get("ruminations") == []

    @pytest.mark.asyncio
    async def test_only_active_included(self):
        from conscience.models import Rumination
        await sync_to_async(Rumination.objects.create)(
            summary="l'email de Thomas", intensity=0.7, status="active",
        )
        await sync_to_async(Rumination.objects.create)(
            summary="ancien oubli", intensity=0.5, status="faded",
        )
        state = await _collect_inner_state(person_id=None)
        assert len(state["ruminations"]) == 1
        assert state["ruminations"][0]["summary"] == "l'email de Thomas"

    @pytest.mark.asyncio
    async def test_ordered_by_intensity_desc(self):
        from conscience.models import Rumination
        await sync_to_async(Rumination.objects.create)(
            summary="faible", intensity=0.3, status="active",
        )
        await sync_to_async(Rumination.objects.create)(
            summary="forte", intensity=0.9, status="active",
        )
        state = await _collect_inner_state(person_id=None)
        assert state["ruminations"][0]["summary"] == "forte"
        assert state["ruminations"][1]["summary"] == "faible"

    @pytest.mark.asyncio
    async def test_capped_at_five(self):
        from conscience.models import Rumination
        for i in range(8):
            await sync_to_async(Rumination.objects.create)(
                summary=f"r{i}", intensity=0.1 * (i + 1), status="active",
            )
        state = await _collect_inner_state(person_id=None)
        assert len(state["ruminations"]) == 5


@pytest.mark.django_db(transaction=True)
class TestInnerStatePersonProfile:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from memory.models import Commitment, Entity, PersonProfile
        Commitment.objects.all().delete()
        PersonProfile.objects.all().delete()
        Entity.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_internal_person_id_never_exposes_profile(self):
        for pid in ("anonymous", "conscience_mika", "__global__", "", None):
            state = await _collect_inner_state(person_id=pid)
            assert "person_profile" not in state
            assert "pending_commitments" not in state

    @pytest.mark.asyncio
    async def test_anon_prefix_never_exposes_profile(self):
        """anon_* IDs are per-connection fallbacks — never a real entity."""
        from memory.models import Entity, PersonProfile
        ent = await sync_to_async(Entity.objects.create)(
            name="anon_deadbeef", entity_type="person",
        )
        await sync_to_async(PersonProfile.objects.create)(
            entity=ent, summary="should not leak",
        )
        state = await _collect_inner_state(person_id="anon_deadbeef")
        assert "person_profile" not in state

    @pytest.mark.asyncio
    async def test_profile_serialized_for_known_person(self):
        from memory.models import Entity, PersonProfile
        ent = await sync_to_async(Entity.objects.create)(
            name="web_abc123", entity_type="person",
        )
        await sync_to_async(PersonProfile.objects.create)(
            entity=ent,
            summary="Thomas est passionne de retro gaming.",
            closeness="friend",
            preferred_tone="playful",
            topics_of_interest=["gaming", "retro"],
            sensitive_topics=["travail"],
            interaction_count=12,
        )

        state = await _collect_inner_state(person_id="web_abc123")
        assert state["person_profile"]["name"] == "web_abc123"
        assert state["person_profile"]["closeness"] == "friend"
        assert "gaming" in state["person_profile"]["topics_of_interest"]
        assert state["person_profile"]["interaction_count"] == 12

    @pytest.mark.asyncio
    async def test_pending_commitments_included(self):
        from memory.models import Commitment, Entity, PersonProfile
        ent = await sync_to_async(Entity.objects.create)(
            name="web_claire", entity_type="person",
        )
        await sync_to_async(PersonProfile.objects.create)(
            entity=ent, summary="Claire.",
        )
        await sync_to_async(Commitment.objects.create)(
            description="Lui envoyer la playlist",
            person=ent, status="pending",
        )
        await sync_to_async(Commitment.objects.create)(
            description="ancienne promesse tenue", person=ent, status="honored",
        )
        state = await _collect_inner_state(person_id="web_claire")
        assert "Lui envoyer la playlist" in state["pending_commitments"]
        assert "ancienne promesse tenue" not in state["pending_commitments"]


@pytest.mark.asyncio
class TestBroadcastCarriesInnerState:

    async def test_broadcast_payload_shape(self):
        mock_layer = MagicMock()
        mock_layer.group_send = AsyncMock()

        with patch("pipeline.broadcast.get_channel_layer", return_value=mock_layer), \
             patch("pipeline.broadcast._collect_inner_state",
                   new_callable=AsyncMock, return_value={"drives": {}, "ruminations": []}):
            await broadcast_to_websocket(_output("coucou"), source="frontend", person_id="web_u1")

        payload = mock_layer.group_send.call_args[0][1]
        data = payload["data"]
        assert data["type"] == "speech"
        assert data["text"] == "coucou"
        assert data["source"] == "frontend"
        assert data["person_id"] == "web_u1"
        assert "inner_state" in data
        assert "drives" in data["inner_state"]
