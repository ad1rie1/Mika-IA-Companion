"""Broadcast and event emission — side-effects after AI processing."""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING

from channels.layers import get_channel_layer

from identity.trust import is_identifiable_person
from memory.manager import memory_manager
from modules.manager import module_manager
from modules.types import ModuleEvent
from pipeline import voice
from utils.degradation import degradations

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
            # Synchronisation cursors. `message_id` is this reply's row;
            # a client stores the highest one it has seen and asks for
            # everything after it when the socket comes back, which is the
            # only way a frame emitted while it was disconnected is ever
            # recovered — a WebSocket send to an empty group is silently
            # lost, and nothing replayed it before.
            "message_id": getattr(output, "message_id", None),
            "user_message_id": getattr(output, "user_message_id", None),
            "client_msg_id": getattr(output, "client_msg_id", None),
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
    # An error fallback ("j'ai eu un bug", quota, timeout) is shown as text
    # but never voiced: hearing Mika speak her own error messages out loud
    # reads as broken, while a silent chat line reads as informative.
    if getattr(output, "ai_failed", False):
        payload["data"]["speak"] = False
        payload["data"]["voice_reason"] = "error_fallback_muted"
    payload["data"]["voice_persona"] = persona
    payload["data"]["voice_profile"] = {
        "pitch": profile.pitch, "rate": profile.rate, "gain": profile.gain,
    }

    if not targets:
        # Nobody reachable *right now*. Two very different cases hide here,
        # and treating them alike leaked one person's context to another.
        #
        # An identifiable person who is simply not connected must NOT be
        # broadcast: the payload carries their inner_state — profile,
        # commitments, per-person affect — so a proactive message composed
        # for Adrien while he is offline landed in every other open browser.
        # The rule three lines below ("never dumped on the global group as a
        # consolation prize") was already stated for the failed-delivery
        # branch and simply not applied here. Nothing is lost by staying
        # silent: the turn is persisted, and their client pulls it by cursor
        # on reconnect (communication/history.py).
        #
        # The global group remains right for everything that belongs to no
        # one — an anonymous socket, `conscience_mika` thinking out loud —
        # where "whoever is watching" IS the intended audience.
        if person_id and is_identifiable_person(person_id):
            logger.info(
                "No live client for %s — reply persisted, will be delivered "
                "on reconnect rather than broadcast to everyone",
                person_id,
            )
            return
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
        can_deliver, deliver_voice, get_channel, voice_sink_of,
    )

    channel = get_channel(target.channel)
    if not channel or not channel.is_running:
        logger.warning(
            "Cannot deliver to %s: channel '%s' unavailable",
            target.person_id, target.channel,
        )
        return False
    if not can_deliver(channel):
        # Resolved to something that cannot initiate contact — a module,
        # typically. Said plainly rather than surfacing later as an
        # AttributeError inside a handler that reports "deliver() failed".
        logger.warning(
            "Cannot deliver to %s: channel '%s' has no outbound delivery",
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
    except Exception as exc:
        degradations.record("voice: sleep phase lookup", exc)

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

    Every current caller passes nothing, which is what "Mika's own state
    changed" means, and that goes to the global group. A ``person_id``
    makes ``_collect_inner_state`` add that person's profile and
    commitments — so it must go to *their* group, not to everyone's. The
    parameter has always existed and the send was always global: unused,
    but a loaded gun pointing at the same leak ``broadcast_to_websocket``
    was fixed for.
    """
    channel_layer = get_channel_layer()
    inner_state = await _collect_inner_state(person_id)
    group = (
        _person_group(person_id)
        if person_id and is_identifiable_person(person_id)
        else BROADCAST_GROUP
    )
    try:
        await channel_layer.group_send(
            group,
            {
                "type": "communication.broadcast",
                "data": {
                    "type": "inner_state_update",
                    "inner_state": inner_state,
                },
            },
        )
    except Exception as exc:
        degradations.record("broadcast: inner state push", exc)


async def broadcast_emotion_update(person_id: str, group: str = "") -> None:
    """Push a standalone ``emotion_update`` frame to one person's client(s).

    Same emotion fields a ``speech`` frame carries, minus everything else:
    no text, no inner state, no voice decision — the client applies the
    face/gaze/hand mood and refreshes the readout without speaking. This is
    what makes the avatar's expression follow the oscillator between turns
    instead of freezing on the last reply (see ``emotion.sync``).

    Targeted at the person's own group, never the global one: the emotion
    here is Mika's stance *toward this person*, so it is theirs to see.
    """
    from emotion.engine import emotion_engine

    msg = emotion_engine.compute_message_emotion(person_id)
    payload = {
        "type": "communication.broadcast",
        "data": {
            "type": "emotion_update",
            "person_id": person_id,
            "emotion": msg.emotion.value,
            "emotion_intensity": msg.intensity,
            "emotion_blend": [
                {"emotion": e.value, "weight": round(w, 2)} for e, w in msg.blend
            ],
            "emotion_state": emotion_engine.get_state_dict(person_id),
        },
    }
    try:
        channel_layer = get_channel_layer()
        await channel_layer.group_send(group or _person_group(person_id), payload)
    except Exception as exc:
        degradations.record("broadcast: emotion update push", exc)


async def _collect_inner_state(person_id: str | None) -> dict:
    """Assemble a JSON-safe snapshot of Mika's inner life for the frontend.

    Each section is gathered independently and merged in: if a sub-system
    fails (DB unavailable, model not migrated yet, ...), that field is
    omitted rather than breaking the whole broadcast. The isolation used to
    be ten hand-written ``try/except`` blocks that differed only in the log
    message — which meant a new section silently inherited "all or nothing"
    the day someone forgot the wrapper.
    """
    state: dict = {}
    for label, loader in (
        ("drives", _snapshot_drives),
        ("sleep phase", _snapshot_sleep_phase),
        ("daily journal", _snapshot_today_journal),
        ("dream", _snapshot_last_dream),
        ("circadian", _snapshot_circadian),
        ("self-narrative", _snapshot_self_narrative),
        ("ruminations", _snapshot_ruminations),
        ("projects", _snapshot_projects),
        ("pending actions", _snapshot_pending_actions),
    ):
        await _merge_section(state, label, loader)

    # Per-person material: only for an id that can belong to someone (not
    # Mika's own plumbing, not a throwaway socket). The panel is a window
    # onto the same private memory the prompt gates, so it answers to the
    # same rule — see identity.trust.may_disclose_private_context.
    #
    # ``person_scope`` states which question this payload answers, because
    # the client cannot tell otherwise: a section with nothing to report is
    # *omitted*, so "she knows nothing about you" and "this frame is not
    # about anyone" arrived identically. The panel clears a section it is
    # handed nothing for — correct for the first reading, and it meant every
    # sleep-phase transition wiped the identity block from every open
    # browser until the next reply.
    state["person_scope"] = bool(is_identifiable_person(person_id))
    if state["person_scope"]:
        await _merge_section(
            state, "person profile", lambda: _snapshot_person(person_id),
        )
    return state


async def _merge_section(state: dict, label: str, loader) -> None:
    """Run one snapshot loader and merge its keys, swallowing failures.

    ``loader`` may be sync or async and returns a dict of keys to merge (or
    an empty one when it has nothing to say).
    """
    try:
        result = loader()
        if inspect.isawaitable(result):
            result = await result
        if result:
            state.update(result)
    except Exception as exc:
        # Counted per section, not just logged: this handler covers ten
        # loaders, so a single broken one produced a panel silently missing
        # one card — indistinguishable from a card with nothing to show.
        degradations.record(f"inner state: {label}", exc)


# ── Snapshot sections ─────────────────────────────────────────────
# Each returns the keys it contributes, or {} for "nothing to report".
# None of them handle their own errors: _merge_section owns that, so a new
# section cannot forget to be isolated.


def _snapshot_drives() -> dict:
    """In-RAM, cheap, always available."""
    from drives.engine import drive_engine

    return {
        "drives": drive_engine.to_dict(),
        "energy": round(drive_engine.energy_level(), 3),
    }


def _snapshot_sleep_phase() -> dict:
    """Whether Mika is asleep (journaling / dreaming / digesting) or awake.

    Drives avatar + scene visuals on the frontend.
    """
    from memory.sleep import sleep_cycle

    return {"sleep_phase": sleep_cycle.phase}


async def _snapshot_today_journal() -> dict:
    """The recap written at the previous light-sleep phase.

    "Most recent", not "yesterday's": a journal is dated the day it COVERS,
    so matching strictly on today left the panel blank from midnight to 23h.
    The prompt asks the other question — see memory.read.
    """
    from memory import read

    journal = await read.latest_journal()
    if not journal or not journal.narrative:
        return {}
    return {
        "today_journal": {
            "date": journal.date.isoformat(),
            "narrative": journal.narrative,
            "dominant_emotion": journal.dominant_emotion,
            "persons_interacted": list(journal.persons_interacted or []),
        }
    }


async def _snapshot_last_dream() -> dict:
    """Last night's dream, with vividness for UI opacity scaling.

    Surfaced regardless of ``recalled_at`` so the panel keeps showing it
    after Mika has mentioned it in conversation.
    """
    from memory import read

    dream = await read.dream_of_last_night()
    if not dream or not dream.content:
        return {}
    return {
        "last_dream": {
            "content": dream.content,
            "dream_type": dream.dream_type,
            "vividness": round(dream.vividness, 2),
            "emotion": dream.emotion,
            "night_of": dream.night_of.isoformat(),
            "recalled": dream.recalled_at is not None,
        }
    }


def _snapshot_circadian() -> dict:
    """Pure function, no IO."""
    from emotion import circadian

    try:
        from config.personality import personality
        profile = personality.circadian_profile
    except Exception:
        # A missing personality file must not cost the circadian block; the
        # module's own defaults describe a plain diurnal rhythm.
        profile = None

    cstate = circadian.current_state(profile=profile)
    return {
        "circadian": {
            "phase": cstate.phase.value,
            "hour": cstate.hour,
            "energy": round(cstate.energy, 3),
            "bias_emotion": cstate.bias_anchor.value,
        }
    }


async def _snapshot_self_narrative() -> dict:
    """One row, the most recent."""
    from memory import read

    narrative = await read.latest_self_narrative()
    if not narrative or not narrative.content:
        return {}
    return {
        "self_narrative": {
            "content": narrative.content,
            "key_themes": narrative.key_themes,
            "key_people": narrative.key_people,
            "dominant_mood": narrative.dominant_mood,
            "created_at": narrative.created_at.isoformat(),
        }
    }


async def _snapshot_ruminations() -> dict:
    """Top-5 active. Always present, empty list included."""
    from conscience import read

    rows = await read.active_ruminations(limit=5)
    return {
        "ruminations": [
            {
                "summary": r.summary,
                "intensity": round(r.intensity, 2),
                "emotion": r.emotion,
            }
            for r in rows
        ]
    }


async def _snapshot_projects() -> dict:
    """Condensed active-project view for the InnerLifePanel.

    Task counts are annotated, not looped: this runs on every reply before
    the text reaches the user, and three COUNT queries per project (each its
    own sync_to_async round-trip) put ~30 queries on the critical path for a
    panel nobody is watching mid-sentence.
    """
    from asgiref.sync import sync_to_async
    from django.db.models import Count, Q
    from projects.models import Project, ProjectTask

    active = await sync_to_async(
        lambda: list(
            Project.objects.filter(status=Project.Status.ACTIVE)
            .annotate(
                tasks_total=Count("tasks", distinct=True),
                tasks_done=Count(
                    "tasks", distinct=True,
                    filter=Q(tasks__status=ProjectTask.Status.DONE),
                ),
                tasks_blocked=Count(
                    "tasks", distinct=True,
                    filter=Q(tasks__status=ProjectTask.Status.BLOCKED),
                ),
            )
            .order_by("-priority", "-updated_at")[:10]
        )
    )()
    if not active:
        return {}
    return {
        "projects": [
            {
                "id": p.id,
                "title": p.title,
                "status": p.status,
                "priority": p.priority,
                "origin": p.origin,
                "emotion_policy": p.emotion_policy,
                "schedule_rule": p.schedule_rule,
                "next_run_at": p.next_run_at.isoformat() if p.next_run_at else None,
                "tasks_total": p.tasks_total,
                "tasks_done": p.tasks_done,
                "tasks_blocked": p.tasks_blocked,
            }
            for p in active
        ]
    }


async def _snapshot_pending_actions() -> dict:
    """The user-actionable approval queue."""
    from asgiref.sync import sync_to_async
    from projects.models import ProjectPendingAction

    pending = await sync_to_async(
        lambda: list(
            ProjectPendingAction.objects
            .filter(status=ProjectPendingAction.Status.PENDING)
            .select_related("project")
            .order_by("-created_at")[:20]
        )
    )()
    if not pending:
        return {}
    return {
        "pending_project_actions": [
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
    }


async def _snapshot_person(person_id: str) -> dict:
    """Who Mika thinks this is, and — only if she may — what she knows of them.

    ``identity`` is always reported (it is about the connection, not about
    the person's private life); the profile and commitments are gated on
    ``may_disclose``, exactly as the prompt is.
    """
    from identity.resolver import identity_resolver
    from memory import read

    ident = await identity_resolver.resolve_context(person_id)
    out: dict = {
        "identity": {
            "known_as": ident.known_as,
            "certainty": round(ident.certainty, 3),
            "level": ident.description,
            "trust": ident.trust.value,
            "pending_claims": ident.pending_claims,
        }
    }
    if not ident.may_disclose:
        return out

    entity = await identity_resolver.entity_for_person(person_id)
    if entity is None:
        return out

    profile = await read.person_profile_for(entity)
    if profile is None:
        return out

    out["person_profile"] = {
        "name": profile.entity.name,
        "summary": profile.summary,
        "closeness": profile.closeness,
        "preferred_tone": profile.preferred_tone,
        "topics_of_interest": profile.topics_of_interest,
        "sensitive_topics": profile.sensitive_topics,
        "interaction_count": profile.interaction_count,
    }
    out["pending_commitments"] = await read.pending_commitments_for(entity)
    return out



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
    response_is_internal: bool = False,
) -> tuple[int | None, int | None]:
    """Save a whole exchange at once — question then reply.

    Kept for callers that genuinely have both halves in hand. The
    conversation pipeline does **not**: it writes the question before the
    AI call and the reply after (see :func:`persist_user_message`), because
    the interval between the two is where the process is most likely to
    die.

    Returns ``(user_message_id, assistant_message_id)``.
    """
    user_id = await persist_user_message(
        message=message, source=source, person_id=person_id,
        attachments_meta=attachments_meta,
        is_internal=user_is_internal,
        awaiting_reply=False,
    )
    assistant_id = await persist_assistant_message(
        response=response, person_id=person_id,
        is_internal=response_is_internal,
        replying_to=user_id,
    )
    return user_id, assistant_id


async def persist_user_message(
    *,
    message: str,
    source: str,
    person_id: str,
    attachments_meta: list[dict] | None = None,
    is_internal: bool = False,
    awaiting_reply: bool = True,
) -> int | None:
    """Write down what was said, before trying to answer it.

    Order matters and it is the whole point. The AI call is the long,
    fragile part of a turn — up to ``ai.call_timeout_seconds``, on a local
    model often all of it. Persisting afterwards meant a restart during
    that window erased the question itself: the client had been told
    "received", showed the message as sent, and the server had no record
    that anyone had spoken. Writing first turns that into a question that
    is merely unanswered, which ``awaiting_reply`` makes recoverable.

    ``attachments_meta`` rides on the user Message only, so retrieval can
    see what came with the turn without keeping bytes in the conversation
    store.

    ``is_internal`` marks scaffolding Mika wrote to herself (a greeting
    brief, a module's notify_ai prompt) rather than something a person
    said. The consolidator skips those so instructions never become
    souvenirs; her reply stays a real memory.
    """
    return await memory_manager.add_message(
        "user", message, source=source, person_id=person_id,
        attachments_meta=attachments_meta or [],
        is_internal=is_internal,
        awaiting_reply=awaiting_reply,
    )


async def persist_assistant_message(
    *,
    response: str,
    person_id: str,
    is_internal: bool = False,
    replying_to: int | None = None,
) -> int | None:
    """Write down the answer, and close the question it answers.

    ``is_internal`` marks the *reply* as machinery rather than speech —
    the fallback text a failed turn returns. What the person said is a real
    fact and is kept as one; "Hmm, je réfléchis plus lentement que prévu"
    is the engine talking about itself, and it must reach neither the
    extractor nor the rehydrated history.

    ``replying_to`` clears that question's ``awaiting_reply`` flag. A
    failed turn still clears it: it produced a fallback, so it is answered
    — badly, but answered. Re-queuing it at every boot would replay the
    same failure forever.
    """
    assistant_id = await memory_manager.add_message(
        "assistant", response, person_id=person_id,
        is_internal=is_internal,
    )
    # `int` and not just "not None": a caller whose memory layer is stubbed
    # hands back whatever the stub returns, and filtering a pk on it raises
    # inside a handler that would then report a real persistence failure.
    if isinstance(replying_to, int):
        try:
            from memory.models import Message

            await Message.objects.filter(pk=replying_to).aupdate(
                awaiting_reply=False,
            )
        except Exception as exc:
            # A flag left set costs one redundant re-queue at the next
            # boot; failing the turn over it would cost the answer.
            degradations.record("persist: clear awaiting_reply", exc)
    return assistant_id
