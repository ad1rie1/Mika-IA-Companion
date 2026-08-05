"""Conversation processor — the full pipeline from Perception to broadcast.

Orchestrates: context -> response -> emotion -> persist -> broadcast.
Each step lives in its own module for readability and testability.

Entry point takes a ``Perception`` built by the router. Multimodal and
multi-part content flows through without string serialization: preprocessors
upstream enrich non-text parts with text descriptions that end up in
``perception.text`` when we need a prompt, but the structured parts are
preserved in the persisted ``Message.attachments_meta``.
"""

import asyncio
import logging
import random
from dataclasses import dataclass

from django.conf import settings

from ai.quota import QuotaExceeded
from ai.router import UnconfiguredRoleError
from emotion.engine import emotion_engine
from emotion.types import Emotion, EmotionData
from identity.resolver import identity_resolver
from pipeline.broadcast import (
    broadcast_to_websocket,
    emit_communication_event,
    persist_assistant_message,
    persist_user_message,
)
from pipeline.context import ConversationContext, gather_context
from pipeline.perception import Intent, Perception
from pipeline.response import call_ai_and_parse
from pipeline.signals import publish_turn_completed
from pipeline.tracing import set_current_person_id, set_new_request_id
from utils.degradation import degradations

logger = logging.getLogger(__name__)


def _compute_thinking_delay(
    response_text: str, energy: float, source: str
) -> float:
    """Return the seconds of simulated "thinking" to insert before broadcast.

    Purely cosmetic — the LLM call latency is already the bulk of the
    wait. This adds a human-sized floor so short responses ("ouais",
    "mdr") don't pop back instantly, which feels bot-like.

    Scaling:
      - Base: 250-600ms random jitter (always)
      - + ~8ms per word, capped at 1500ms
      - × (1.6 if tired, energy < 0.3)
      - × (0.7 if energetic, energy > 0.75)
      - Skipped entirely for internal triggers (conscience acted
        deliberately — shouldn't hesitate on top of her own decision)

    Total cap: 2000ms. We never want to make the user wait on us.
    """
    if source == "conscience":
        return 0.0
    if not response_text.strip():
        return 0.0

    word_count = len(response_text.split())
    jitter = 0.25 + random.random() * 0.35            # 250-600ms
    per_word = min(1.5, 0.008 * word_count)           # max 1500ms
    raw = jitter + per_word

    if energy < 0.3:
        raw *= 1.6
    elif energy > 0.75:
        raw *= 0.7

    return min(2.0, raw)


@dataclass
class SpeechOutput:
    """Result of processing a message through the pipeline."""
    text: str
    emotion_data: EmotionData
    emotion_name: str
    emotion_intensity: float
    emotion_state: dict
    tool_calls: list[str]
    request_id: str = "-"
    # Top-K emotion components for ambivalence display on the frontend.
    # List of {"emotion": str, "weight": float}.
    emotion_blend: list | None = None
    # True when the text is an error fallback, not a real AI answer.
    # Downstream: never spoken via TTS, and callers (conscience) must not
    # count it as a successful act.
    ai_failed: bool = False
    # Persistence cursors, carried into the broadcast so a client can tell
    # "this is the reply I was waiting for" from "this is a message I have
    # already displayed", and can ask for everything after it on reconnect.
    # None when the turn was not persisted (persist=False, or a write that
    # failed — a message the server did not record must not advance the
    # client's cursor past it).
    message_id: int | None = None
    user_message_id: int | None = None
    # Echo of the client-generated id the browser attached to its own bubble,
    # so a locally-painted message can be reconciled with its server row
    # instead of appearing twice after a history merge.
    client_msg_id: str | None = None


# -- Main entry point ---------------------------------------------------------


async def process_message(
    perception: Perception,
    *,
    context: ConversationContext | None = None,
    broadcast: bool = True,
    persist: bool = True,
    emit_event: bool = True,
) -> SpeechOutput:
    """Full conversation pipeline: context -> AI -> emotion -> persist -> broadcast.

    Args:
        perception: The input stimulus. Carries source, person_id, parts, etc.
        context: Pre-built context (if None, gathered from the perception).
        broadcast: Whether to broadcast the response via WebSocket.
        persist: Whether to save the exchange in memory.
        emit_event: Whether to emit a ``chat.message`` module event after.
    """
    request_id = set_new_request_id()
    tool_calls = []

    source = perception.source
    person_id = perception.person_id
    # text property concatenates all text Parts. Preprocessors have
    # already serialized images/audio/files into text descriptions.
    message = perception.text

    # Bind the turn's person for the whole async context, so tool handlers
    # ("who am I talking to?") don't need the model to repeat an id it never
    # sees. Inherited by every coroutine awaited below.
    set_current_person_id(person_id)

    # What the transport itself proves about this turn. Absent metadata means
    # "no proof", which is the safe reading for any adapter that hasn't been
    # taught to say otherwise.
    authenticated = bool(perception.metadata.get("authenticated", False))
    is_public = bool(perception.metadata.get("is_public", False))

    # Passive identification: read the turn for "moi c'est Thomas" and file a
    # claim. This never binds anything on its own — it only gives Mika
    # something to notice and decide on. Failures are non-fatal by design:
    # not knowing who someone is must never cost them their answer.
    try:
        await identity_resolver.ingest_message(
            person_id, message, channel=source, authenticated=authenticated,
        )
    except Exception as exc:
        degradations.record("turn: passive identification", exc)

    # Hydrate person mood from DB if evicted from RAM since last interaction
    await emotion_engine.ensure_person_loaded(person_id)

    ai_failed = False
    user_message_id: int | None = None
    assistant_message_id: int | None = None
    from configs.service import config_service
    timeout_seconds = config_service.get("ai.call_timeout_seconds")

    try:
        # 1. Assemble context (memory, emotion, modules, self-concept, ...)
        if context is None:
            context = await gather_context(
                message, person_id, channel=source,
                authenticated=authenticated, is_public=is_public,
            )

        # 1b. Write the question down, before attempting to answer it.
        #
        #     Deliberately *after* gather_context and *before* the AI call.
        #     After, because add_message also appends to the short-term
        #     buffer that gather_context just read — persisting first would
        #     hand the model the current message twice, once as history and
        #     once as the prompt. Before, because the AI call is the long
        #     fragile part: a restart during it used to erase the question
        #     itself, leaving someone with a bubble marked delivered and no
        #     trace on the server that they had spoken at all.
        if persist:
            # A turn replayed after a restart already has its question in the
            # database — that row is precisely how it was found (see
            # pipeline/turns.py::resume_interrupted_turns). Writing it again
            # produced a second row with the same text: duplicated in the
            # person's fiche, duplicated for the consolidator, and displayed
            # twice in the browser, since the merge only adopts bubbles that
            # have no id yet and the original already had one.
            #
            # The rehydrated short-term buffer still holds that question, so
            # the replayed turn shows it to the model once as history and
            # once as the prompt. That is the cheaper of the two artefacts:
            # dropping it from the buffer would leave the answer standing
            # alone, without the question, for every turn that follows.
            replayed_id = perception.metadata.get("original_message_id")
            if isinstance(replayed_id, int):
                user_message_id = replayed_id
            else:
                user_message_id = await persist_user_message(
                    message=message,
                    source=source,
                    person_id=person_id,
                    attachments_meta=_serialize_attachments_meta(perception),
                    # The "user" side of an internal trigger is scaffolding
                    # Mika wrote to herself, not something anyone said.
                    is_internal=perception.intent is Intent.INTERNAL_TRIGGER,
                )

        # 2. Prompt -> AI call -> emotion extraction (bounded by timeout)
        response_text, emotion_data, tool_calls = await asyncio.wait_for(
            call_ai_and_parse(context, message),
            timeout=timeout_seconds,
        )

    except asyncio.TimeoutError:
        logger.warning(
            "AI call timed out after %ds (person=%s, source=%s)",
            timeout_seconds, person_id, source,
        )
        ai_failed = True
        response_text = "Hmm, je reflechis plus lentement que prevu... Laisse-moi un instant."
        emotion_data = EmotionData(emotion=Emotion.NEUTRAL, intensity=0.0)
    except UnconfiguredRoleError as ure:
        # Configuration error, not a runtime bug: no model is mapped to the
        # role. One concise line — a traceback adds nothing actionable here.
        logger.warning(
            "IA non configurée (person=%s, source=%s): %s",
            person_id, source, ure,
        )
        ai_failed = True
        response_text = (
            "Je ne suis pas encore configurée pour repondre... "
            "Mon IA n'a pas de modele associe (Configuration > IA · Roles)."
        )
        emotion_data = EmotionData(emotion=Emotion.NEUTRAL, intensity=0.0)
    except QuotaExceeded as qe:
        # Hit a daily/monthly LLM quota. Return a truthful short message
        # instead of the generic "bug" fallback so the user knows why.
        logger.warning(
            "AI quota exceeded (person=%s, source=%s): %s",
            person_id, source, qe,
        )
        ai_failed = True
        response_text = (
            "Desolee, j'ai atteint la limite d'usage IA pour le moment. "
            "Reessaie un peu plus tard."
        )
        emotion_data = EmotionData(emotion=Emotion.NEUTRAL, intensity=0.0)
    except Exception:
        logger.exception(
            "AI error while processing message (person=%s, source=%s)",
            person_id, source,
        )
        ai_failed = True
        response_text = "Oups, j'ai eu un petit bug... Tu peux reessayer ?"
        emotion_data = EmotionData(emotion=Emotion.NEUTRAL, intensity=0.0)
        # A light global-mood perturbation reflects Mika's own frustration
        # at her technical failure — not a relational emotion toward the user.
        emotion_engine.process_emotion(
            EmotionData(Emotion.ANXIOUS, 0.1), "conscience_mika",
        )

    # 3. Process emotion (only on success — a crashed AI is not the user's
    #    fault and should not color Mika's mood toward them).
    #    Skipped entirely when a project with emotion_policy=OFF is active:
    #    we don't want work-mode replies coloring relational state (e.g.
    #    replying to a tense client email should not make Mika "anxious"
    #    toward the person the next time they chat).
    #    Deliberately OUTSIDE the AI try-block and non-fatal: a bookkeeping
    #    error here must not turn a real, already-received answer into the
    #    "j'ai eu un petit bug" fallback and drop it from memory.
    if not ai_failed and not getattr(context, "project_suppresses_emotion", False):
        try:
            emotion_engine.process_emotion(emotion_data, person_id)
            await emotion_engine._maybe_save_snapshot(person_id)
        except Exception:
            logger.exception(
                "Emotion post-processing failed (person=%s) — the reply itself "
                "is unaffected", person_id,
            )

    # 4. Persist the reply — including a failed turn's fallback.
    #
    #    A failure used to drop the whole exchange, on the grounds that a
    #    fallback is not a real answer. True of the *answer*; false of the
    #    question. What someone actually said to Mika happened whether or not
    #    the model replied in time, and losing it means the message exists
    #    nowhere — not in the history, not on the person's fiche, not for the
    #    consolidator — which reads as "you never wrote to me". The question
    #    is therefore already written down, at step 1b.
    #
    #    Only the *reply* is demoted: marked internal, so the extractor never
    #    turns "j'ai eu un petit bug" into a souvenir and a restart doesn't
    #    rehydrate it as something Mika said. Everything else a failure
    #    withholds still is: no emotional impulse, no chat.message event, no
    #    turn signal. She keeps the trace without pretending she answered.
    if persist:
        assistant_message_id = await persist_assistant_message(
            response=response_text,
            person_id=person_id,
            is_internal=ai_failed,
            # Closes the question: answered, well or badly. A fallback still
            # counts, or every boot would replay the same failing turn.
            replying_to=user_message_id,
        )

    # 5. Emit module event — also skipped on failure.
    if emit_event and not ai_failed:
        await emit_communication_event(source, person_id)

    # 5b. Announce the turn. Everything that merely wants to *know* a turn
    #     happened — the drives relieving EXPRESSION, the conscience filing
    #     a "did I say that right?" rumination — subscribes to this instead
    #     of being called from here. Each of those used to be an inline hook
    #     with its own try/except and its own idea of when to skip, which
    #     made this function the place every new subsystem had to edit.
    #
    #     Note what is NOT announced: the emotional impulse above and the
    #     identity ingest at the top are pipeline *steps*, not listeners —
    #     their effects are read further down this same function. See
    #     pipeline/signals.py.
    if not ai_failed:
        await publish_turn_completed(
            person_id=person_id,
            source=source,
            intent=perception.intent.name,
            text=response_text,
            emotion_name=emotion_data.emotion.value,
            emotion_intensity=emotion_data.intensity,
            project_suppresses_emotion=bool(
                getattr(context, "project_suppresses_emotion", False)
            ),
        )

    # 6. Compute final blended emotion for the reply's display.
    msg_emotion = emotion_engine.compute_message_emotion(person_id)

    logger.info(
        "[%s/%s] %s -> %s (emotion=%s intensity=%.2f)",
        source, person_id,
        message[:60], response_text[:80],
        msg_emotion.emotion.value, msg_emotion.intensity,
    )

    output = SpeechOutput(
        text=response_text,
        emotion_data=emotion_data,
        emotion_name=msg_emotion.emotion.value,
        emotion_intensity=msg_emotion.intensity,
        emotion_state=emotion_engine.get_state_dict(person_id),
        tool_calls=tool_calls,
        request_id=request_id,
        emotion_blend=[
            {"emotion": e.value, "weight": round(w, 2)}
            for e, w in msg_emotion.blend
        ],
        ai_failed=ai_failed,
        message_id=assistant_message_id,
        user_message_id=user_message_id,
        client_msg_id=_client_msg_id(perception),
    )

    # 7. Broadcast to WebSocket (inner state attached so UI panels refresh).
    #    Before broadcasting, insert a short "thinking" delay so responses
    #    don't pop back instantly — feels human, especially for short
    #    replies. Skipped for internal triggers (Mika already decided
    #    deliberately; adding hesitation on top would be doubled latency)
    #    and for AI errors (fallback messages should come back fast).
    #    An internal trigger that failed is NOT broadcast at all: nobody
    #    asked a question, so an error fallback greeting/murmur would be
    #    pure noise — silence is the valid outcome.
    if ai_failed and perception.intent is Intent.INTERNAL_TRIGGER:
        broadcast = False
    if broadcast:
        if not ai_failed:
            try:
                from drives.engine import drive_engine
                energy = drive_engine.energy_level()
            except Exception:
                energy = 0.5
            thinking_delay = _compute_thinking_delay(
                response_text=response_text, energy=energy, source=source,
            )
            if thinking_delay > 0:
                logger.debug(
                    "Thinking delay: %.2fs (words=%d, energy=%.2f)",
                    thinking_delay, len(response_text.split()), energy,
                )
                await asyncio.sleep(thinking_delay)
        # Le verdict d'identite du tour part avec la reponse : la diffusion
        # embarque la fiche et les engagements, gardes par la meme regle que
        # le prompt, et elle ne connait ni le canal ni le caractere public du
        # tour pour le rendre elle-meme. `getattr` parce que `context` reste
        # None quand `gather_context` a echoue — meme lecture defensive que
        # `project_suppresses_emotion` plus haut.
        await broadcast_to_websocket(
            output, source, person_id=person_id,
            identity=getattr(context, "identity", None),
        )

    return output


def _client_msg_id(perception: Perception) -> str | None:
    """The browser-generated id of the message that triggered this turn.

    Opaque to the pipeline — it is minted by the client and only ever
    handed back, so it is length-capped and coerced to str rather than
    validated: it indexes nothing server-side, and the one thing it must
    not do is grow a payload without bound.
    """
    raw = perception.metadata.get("client_msg_id")
    if not isinstance(raw, str) or not raw:
        return None
    return raw[:64]


def _serialize_attachments_meta(perception: Perception) -> list[dict]:
    """Extract a JSON-friendly descriptor for each attached, non-text part.

    Binary content is not stored here — the router has already saved
    raw media to disk/DB via pipeline.media. This is purely structural
    metadata (kind, mime_type, name, ...) that lives alongside the
    persisted user Message so later retrieval knows what was attached.

    The subtlety is that by the time this runs there are **no non-text
    parts left**. Preprocessing happens in the router, before the
    processor is ever called, and it does not annotate a part — it
    *replaces* it: an image Part becomes ``Part(kind="text",
    content="[image: un chat roux dort sur un canapé]")``. So a filter on
    ``kind != "text"`` matched nothing and every upload was persisted with
    an empty ``attachments_meta``, which is the field the history frame
    ships as ``attachments``. A reloaded thread had no idea a file had
    ever been sent, and the documented promise that "the structured parts
    are preserved" was never once true for a web upload.

    What survives the substitution is ``metadata["original_kind"]``, which
    every preprocessor sets (including on its failure placeholder). That
    is what identifies a part as an attachment here.
    """
    meta: list[dict] = []
    for p in perception.parts:
        original_kind = p.metadata.get("original_kind")
        if p.kind == "text" and not original_kind:
            continue
        meta.append({
            "kind": original_kind or p.kind,
            "mime_type": p.metadata.get("original_mime_type") or p.mime_type,
            **{k: v for k, v in p.metadata.items()
               if k not in ("original_kind", "original_mime_type")},
        })
    return meta
