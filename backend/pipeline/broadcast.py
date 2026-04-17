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


async def broadcast_inner_state_update(person_id: str | None = None) -> None:
    """Push a standalone ``inner_state_update`` event to the frontend.

    Unlike ``broadcast_to_websocket``, this does NOT carry a speech
    payload — it is a pure state refresh used when Mika's internal state
    changes outside of a conversation turn (e.g. sleep phase transitions
    during the night). The frontend merges this into its InnerLifePanel +
    scene/animation state without invoking TTS.
    """
    channel_layer = get_channel_layer()
    inner_state = await _collect_inner_state(person_id)
    try:
        await channel_layer.group_send(
            BROADCAST_GROUP,
            {
                "type": "communication.broadcast",
                "data": {
                    "type": "inner_state_update",
                    "inner_state": inner_state,
                },
            },
        )
    except Exception:
        logger.debug("Inner state broadcast failed", exc_info=True)


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
        state["energy"] = round(drive_engine.energy_level(), 3)
    except Exception:
        logger.debug("drives snapshot failed", exc_info=True)

    # Sleep phase — whether Mika is currently asleep (journaling / dreaming
    # / digesting) or awake. Drives avatar + scene visuals on the frontend.
    try:
        from memory.sleep import sleep_cycle
        state["sleep_phase"] = sleep_cycle.phase
    except Exception:
        logger.debug("sleep phase snapshot failed", exc_info=True)

    # Today's daily journal — recap written at the previous light-sleep
    # phase. Exposed so the panel can show "aujourd'hui" narratively.
    try:
        from datetime import date
        from memory.models import DailyJournal
        journal = await sync_to_async(
            lambda: DailyJournal.objects.filter(date=date.today()).first()
        )()
        if journal and journal.narrative:
            state["today_journal"] = {
                "date": journal.date.isoformat(),
                "narrative": journal.narrative,
                "dominant_emotion": journal.dominant_emotion,
                "persons_interacted": list(journal.persons_interacted or []),
            }
    except Exception:
        logger.debug("daily journal snapshot failed", exc_info=True)

    # Last night's dream — if any, with vividness for UI opacity scaling.
    # We surface it regardless of `recalled_at` so the panel can show it
    # even after Mika has mentioned it in a conversation.
    try:
        from datetime import date, timedelta
        from memory.models import Dream
        last_night = date.today() - timedelta(days=1)
        dream = await sync_to_async(
            lambda: Dream.objects
            .filter(night_of=last_night)
            .order_by("-vividness")
            .first()
        )()
        if dream and dream.content:
            state["last_dream"] = {
                "content": dream.content,
                "dream_type": dream.dream_type,
                "vividness": round(dream.vividness, 2),
                "emotion": dream.emotion,
                "night_of": dream.night_of.isoformat(),
                "recalled": dream.recalled_at is not None,
            }
    except Exception:
        logger.debug("dream snapshot failed", exc_info=True)

    # Circadian — pure function, no IO
    try:
        from emotion import circadian
        try:
            from config.personality import personality
            profile = personality.circadian_profile
        except Exception:
            profile = None
        cstate = circadian.current_state(profile=profile)
        state["circadian"] = {
            "phase": cstate.phase.value,
            "hour": cstate.hour,
            "energy": round(cstate.energy, 3),
            "bias_emotion": cstate.bias_anchor.value,
        }
    except Exception:
        logger.debug("circadian snapshot failed", exc_info=True)

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

    # Active projects — a condensed view for the InnerLifePanel
    try:
        from projects.models import Project, ProjectTask
        active = await sync_to_async(
            lambda: list(
                Project.objects.filter(status=Project.Status.ACTIVE)
                .order_by("-priority", "-updated_at")[:10]
            )
        )()
        if active:
            projects_summary = []
            for p in active:
                counts = await sync_to_async(
                    lambda pk=p.id: {
                        "total": ProjectTask.objects.filter(project_id=pk).count(),
                        "done": ProjectTask.objects.filter(
                            project_id=pk, status=ProjectTask.Status.DONE,
                        ).count(),
                        "blocked": ProjectTask.objects.filter(
                            project_id=pk, status=ProjectTask.Status.BLOCKED,
                        ).count(),
                    }
                )()
                projects_summary.append({
                    "id": p.id,
                    "title": p.title,
                    "status": p.status,
                    "priority": p.priority,
                    "origin": p.origin,
                    "emotion_policy": p.emotion_policy,
                    "schedule_rule": p.schedule_rule,
                    "next_run_at": p.next_run_at.isoformat() if p.next_run_at else None,
                    "tasks_total": counts["total"],
                    "tasks_done": counts["done"],
                    "tasks_blocked": counts["blocked"],
                })
            state["projects"] = projects_summary
    except Exception:
        logger.debug("projects snapshot failed", exc_info=True)

    # Pending actions — user-actionable queue
    try:
        from projects.models import ProjectPendingAction
        pending = await sync_to_async(
            lambda: list(
                ProjectPendingAction.objects
                .filter(status=ProjectPendingAction.Status.PENDING)
                .select_related("project")
                .order_by("-created_at")[:20]
            )
        )()
        if pending:
            state["pending_project_actions"] = [
                {
                    "id": a.id,
                    "project_id": a.project_id,
                    "project_title": a.project.title,
                    "proposal": a.proposal,
                    "payload_kind": (a.payload or {}).get("kind", ""),
                    "created_at": a.created_at.isoformat(),
                }
                for a in pending
            ]
    except Exception:
        logger.debug("pending actions snapshot failed", exc_info=True)

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
