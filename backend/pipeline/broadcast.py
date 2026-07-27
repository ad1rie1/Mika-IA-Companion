"""Broadcast and event emission — side-effects after AI processing."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from channels.layers import get_channel_layer

from memory.manager import memory_manager
from modules.manager import module_manager
from modules.types import ModuleEvent
from pipeline import voice

if TYPE_CHECKING:
    from pipeline.processor import SpeechOutput

logger = logging.getLogger(__name__)

BROADCAST_GROUP = "vtuber_broadcast"


async def broadcast_to_websocket(
    output: SpeechOutput, source: str, person_id: str | None = None,
) -> None:
    """Deliver the response (per-recipient) + a snapshot of Mika's inner life.

    The ``inner_state`` payload gives the frontend a compact view of:
      - current drives (tension per kind)
      - latest self-narrative (who she thinks she is becoming)
      - active ruminations (unresolved thoughts tinting her mood)
      - person profile for the current interlocutor (if any)
      - pending commitments toward that person

    Routing, by recipient reachability (presence registry):
    - **consumer** target  → the person's own WebSocket group (no cross-client leak)
    - **module** target    → the module's ``deliver()`` (external API push), but
      only when the message did NOT originate from that same module — a reactive
      reply is already echoed by the channel itself, so we avoid double-sending.
    - **unresolved** (proactive with no recipient yet, anonymous, ``conscience_*``)
      → fall back to the legacy global broadcast so existing clients still hear it.
    """
    channel_layer = get_channel_layer()

    inner_state = await _collect_inner_state(person_id)

    payload = {
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
    }

    targets = []
    if person_id:
        from communication.presence import presence_registry

        targets = presence_registry.resolve(person_id)

    # The frontend is the SCREEN voice sink: it runs its own TTS, so instead
    # of a clip it gets the policy decision + the voice identity, and honours
    # both. This keeps "speak" a routing choice rather than a hardcoded
    # frontend habit, and gives Mika's thinking-aloud its own murmured voice.
    persona = voice.persona_for_source(source, addressed=bool(targets))
    screen = await _voice_decision(
        voice.VoiceSink.SCREEN, _first_consumer(targets), persona,
    )
    profile = voice.profile_for(persona)
    payload["data"]["speak"] = screen.speak
    payload["data"]["voice_reason"] = screen.reason
    payload["data"]["voice_persona"] = persona
    payload["data"]["voice_profile"] = {
        "pitch": profile.pitch, "rate": profile.rate, "gain": profile.gain,
    }

    if not targets:
        # No known recipient → legacy broadcast to all connected clients.
        await channel_layer.group_send(BROADCAST_GROUP, payload)
        return

    delivered = False
    for target in targets:
        if target.is_consumer:
            group = target.delivery_ref or _person_group(person_id)
            await channel_layer.group_send(group, payload)
            delivered = True
        elif target.is_module:
            # Skip the originating module on a reactive turn (it echoes itself).
            if target.channel == source:
                delivered = True
                continue
            delivered = (
                await _deliver_via_module(target, output, source) or delivered
            )

    if not delivered:
        # A message composed for a specific person must never be dumped on the
        # global group as a consolation prize: it carries that person's context.
        # Failing to deliver is the correct outcome — it is logged and dropped.
        logger.warning(
            "Undeliverable message for %s (targets: %s) — dropped rather than "
            "broadcast to everyone",
            person_id, ", ".join(t.channel for t in targets),
        )


def _first_consumer(targets):
    """The WebSocket target a SCREEN decision applies to, if any.

    Without one we still answer the question (for the legacy global
    broadcast) using a permissive stand-in: a client is listening, it just
    isn't bound to this person yet.
    """
    for target in targets:
        if target.is_consumer:
            return target
    return _AnyClient()


class _AnyClient:
    """Stand-in target: reachable, no voice mute, no delivery handle."""
    reachable = True
    meta: dict = {}


def _person_group(person_id: str | None) -> str:
    from communication.presence import person_group

    return person_group(person_id or "")


async def _deliver_via_module(target, output, source: str = "") -> bool:
    """Route an outbound message to a channel's external-API delivery.

    The deliverer may be a module OR a communication channel (Telegram) —
    ``get_channel`` covers both. When the channel speaks (declares a
    ``VOICE_SINK``) and the context allows it, the reply goes out as audio;
    text delivery is always the fallback so nothing is ever dropped for
    want of a synthesizer.
    """
    from communication.delivery import (
        deliver_voice, get_channel, voice_sink_of,
    )

    channel = get_channel(target.channel)
    if not channel or not channel.is_running:
        logger.warning(
            "Cannot deliver to %s: channel '%s' unavailable",
            target.person_id, target.channel,
        )
        return False

    sink = voice_sink_of(channel)
    if sink:
        # A module target means Mika picked this person deliberately, so this
        # is addressed speech even when the turn came from her own initiative.
        persona = voice.persona_for_source(source, addressed=True)
        decision = await _voice_decision(sink, target, persona)
        if decision.speak:
            clip = await voice.synthesize(
                output.text,
                emotion=output.emotion_name,
                intensity=output.emotion_intensity,
                persona=persona,
            )
            if clip and await deliver_voice(channel, clip, output, target):
                return True
            # No synthesizer, or the channel refused the clip → text.
        else:
            logger.debug(
                "Voice suppressed on %s for %s: %s",
                sink, target.person_id, decision.reason,
            )

    try:
        return await channel.deliver(output, target)
    except Exception:
        logger.exception("Channel '%s' deliver() failed", target.channel)
        return False


async def _voice_decision(
    sink: str, target, persona: str = voice.VoicePersona.SPEAKING,
) -> "voice.VoiceDecision":
    """Gather the live context the voice policy needs, then decide."""
    from datetime import datetime

    sleep_phase = "awake"
    try:
        from memory.sleep import sleep_cycle
        sleep_phase = sleep_cycle.phase
    except Exception:
        logger.debug("sleep phase unavailable for voice decision", exc_info=True)

    return voice.decide_voice(
        sink,
        hour=datetime.now().hour,
        sleep_phase=sleep_phase,
        person_present=bool(getattr(target, "reachable", True)),
        muted=bool(getattr(target, "meta", {}).get("voice_muted", False)),
        persona=persona,
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
        from datetime import date, timedelta
        from memory.models import DailyJournal
        # The journal written tonight is dated the day it COVERS (the day
        # that just ended). Matching strictly on today's date left the
        # panel blank from midnight to the next 23h — show the most
        # recent of {today, yesterday} instead.
        journal = await sync_to_async(
            lambda: DailyJournal.objects
            .filter(date__gte=date.today() - timedelta(days=1))
            .order_by("-date")
            .first()
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
    user_is_internal: bool = False,
) -> None:
    """Save the user message (with any attachment descriptors) and the
    assistant response to memory.

    ``attachments_meta`` is attached to the user Message only, so later
    retrieval can see what was sent without keeping binary bytes in the
    conversation store.

    ``user_is_internal`` marks the "user" message as scaffolding Mika wrote
    to herself (greeting brief, module notify_ai prompt) rather than
    something a person said. The consolidator skips those so instructions
    never become souvenirs; her reply stays a real memory.
    """
    await memory_manager.add_message(
        "user", message, source=source, person_id=person_id,
        attachments_meta=attachments_meta or [],
        is_internal=user_is_internal,
    )
    await memory_manager.add_message(
        "assistant", response, person_id=person_id,
    )
