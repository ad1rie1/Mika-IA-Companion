"""Broadcast and event emission — side-effects after AI processing."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from channels.layers import get_channel_layer

from memory.manager import memory_manager
from modules.manager import module_manager
from modules.types import ModuleEvent

if TYPE_CHECKING:
    from pipeline.processor import SpeechOutput

logger = logging.getLogger(__name__)

BROADCAST_GROUP = "vtuber_broadcast"


async def broadcast_to_websocket(
    output: SpeechOutput, source: str, person_id: str | None = None,
) -> None:
    """Broadcast the response + a snapshot of Mika's inner life.

    The ``inner_state`` payload gives the frontend a compact view of:
      - current drives (tension per kind)
      - latest self-narrative (who she thinks she is becoming)
      - active ruminations (unresolved thoughts tinting her mood)
      - person profile for the current interlocutor (if any)
      - pending commitments toward that person

    This is broadcast alongside each ``speech`` event so UI panels can
    refresh without polling HTTP endpoints.
    """
    channel_layer = get_channel_layer()

    inner_state = await _collect_inner_state(person_id)

    await channel_layer.group_send(
        BROADCAST_GROUP,
        {
            "type": "communication.broadcast",
            "data": {
                "type": "speech",
                "text": output.text,
                "emotion": output.emotion_name,
                "emotion_intensity": output.emotion_intensity,
                "emotion_state": output.emotion_state,
                "emotion_blend": output.emotion_blend or [],
                "source": source,
                "person_id": person_id,
                "inner_state": inner_state,
            },
        },
    )


async def _collect_inner_state(person_id: str | None) -> dict:
    """Assemble a JSON-safe snapshot of Mika's inner life for the frontend.

    Kept resilient: if a sub-system fails (DB unavailable, model not
    migrated yet, ...), the corresponding field is omitted rather than
    breaking the whole broadcast.
    """
    from asgiref.sync import sync_to_async

    from drives.engine import drive_engine

    state: dict = {}

    # Drives — in-RAM, cheap, always available
    try:
        state["drives"] = drive_engine.to_dict()
    except Exception:
        logger.debug("drives snapshot failed", exc_info=True)

    # Self-narrative — one row, most recent
    try:
        from memory.models import SelfNarrative
        narrative = await sync_to_async(
            lambda: SelfNarrative.objects.order_by("-created_at").first()
        )()
        if narrative and narrative.content:
            state["self_narrative"] = {
                "content": narrative.content,
                "key_themes": narrative.key_themes,
                "key_people": narrative.key_people,
                "dominant_mood": narrative.dominant_mood,
                "created_at": narrative.created_at.isoformat(),
            }
    except Exception:
        logger.debug("self-narrative snapshot failed", exc_info=True)

    # Ruminations — top-5 active
    try:
        from conscience.models import Rumination
        rows = await sync_to_async(
            lambda: list(
                Rumination.objects.filter(status="active")
                .order_by("-intensity")[:5]
                .values("summary", "intensity", "emotion")
            )
        )()
        state["ruminations"] = [
            {
                "summary": r["summary"],
                "intensity": round(r["intensity"], 2),
                "emotion": r["emotion"],
            }
            for r in rows
        ]
    except Exception:
        logger.debug("ruminations snapshot failed", exc_info=True)

    # Person profile + commitments — only when a non-internal person_id
    if person_id and person_id not in (
        "", "anonymous", "conscience_mika", "__global__",
    ) and not person_id.startswith("anon_"):
        try:
            from memory.models import Commitment, PersonProfile
            profile = await sync_to_async(
                lambda: PersonProfile.objects
                .select_related("entity")
                .filter(entity__name=person_id, entity__entity_type="person")
                .first()
            )()
            if profile:
                state["person_profile"] = {
                    "name": profile.entity.name,
                    "summary": profile.summary,
                    "closeness": profile.closeness,
                    "preferred_tone": profile.preferred_tone,
                    "topics_of_interest": profile.topics_of_interest,
                    "sensitive_topics": profile.sensitive_topics,
                    "interaction_count": profile.interaction_count,
                }
                commitments = await sync_to_async(
                    lambda: list(
                        Commitment.objects
                        .filter(person=profile.entity, status="pending")
                        .order_by("-created_at")
                        .values_list("description", flat=True)[:5]
                    )
                )()
                state["pending_commitments"] = list(commitments)
        except Exception:
            logger.debug("person profile snapshot failed", exc_info=True)

    return state


async def emit_communication_event(source: str, person_id: str) -> None:
    """Emit a module event for the conversation turn."""
    await module_manager.emit_event(
        ModuleEvent(
            event_type="chat.message",
            source_module=source,
            data={"person_id": person_id, "source": source},
        )
    )


async def persist_to_memory(
    *,
    message: str,
    response: str,
    source: str,
    person_id: str,
    attachments_meta: list[dict] | None = None,
) -> None:
    """Save the user message (with any attachment descriptors) and the
    assistant response to memory.

    ``attachments_meta`` is attached to the user Message only, so later
    retrieval can see what was sent without keeping binary bytes in the
    conversation store.
    """
    await memory_manager.add_message(
        "user", message, source=source, person_id=person_id,
        attachments_meta=attachments_meta or [],
    )
    await memory_manager.add_message(
        "assistant", response, person_id=person_id,
    )
