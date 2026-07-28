"""Pipeline lifecycle signals — what the processor announces about a turn.

``process_message`` had grown a tail of hardcoded reactions: after the answer
existed it called ``drive_engine.on_reply``, then later
``conscience_engine.post_action_audit``, each behind its own
``try/except: logger.debug`` and its own function-local import. Every new
subsystem that wanted to know a turn had happened added another one, which
made the processor the carrefour obligé of the whole engine and buried the
actual pipeline under bookkeeping.

They are now one announcement on the event bus, and the two subsystems
subscribe themselves (``drives/apps.py``, ``ConscienceEngine.initialize``).

**What deliberately did NOT move.** The emotional impulse
(``emotion_engine.process_emotion``) and passive identification
(``identity_resolver.ingest_message``) stay inline in the processor, because
they are not listeners — they are *steps*. Their effects are read later in
the same turn: the impulse is what ``compute_message_emotion`` reports, and
the identity claim shapes the prompt of the very turn that filed it. Moving
them behind a subscription would hide a hard ordering requirement inside a
priority number. The rule this file encodes is the distinction: a step
changes the turn, a listener merely learns about it.

The signal is internal (``_`` prefix, see ``utils.eventbus``), so it reaches
neither the conscience's signal interpreter nor the wildcard-subscribed
forged modules. "Mika answered someone" is not a signal about the world —
routing it as one would mean interpreting her own reply as an external
stimulus, once per turn, forever.
"""

from __future__ import annotations

import logging

from modules.types import ModuleEvent

logger = logging.getLogger(__name__)

# A conversation turn completed successfully. Never emitted for a failed
# exchange: a fallback message is not something Mika said, and the engine
# already refuses to persist it, colour her mood with it, or count it as an
# act. A listener therefore never has to ask.
TURN_COMPLETED = "_turn.completed"


async def publish_turn_completed(
    *,
    person_id: str,
    source: str,
    intent: str,
    text: str,
    emotion_name: str,
    emotion_intensity: float,
    project_suppresses_emotion: bool,
) -> None:
    """Announce a completed turn. Never raises, never blocks on a listener.

    The payload carries the *facts* of the turn, not permissions: whether a
    professional-mode project should suppress a reaction, or whether an
    internal trigger counts as "answering someone", is each subsystem's own
    policy and belongs with the subsystem — which is precisely what the
    inline hooks got wrong by encoding both rules in the processor.
    """
    from utils.eventbus import event_bus

    try:
        await event_bus.emit(ModuleEvent(
            event_type=TURN_COMPLETED,
            source_module="pipeline",
            data={
                "person_id": person_id,
                "source": source,
                "intent": intent,
                "text": text,
                "word_count": len(text.split()),
                "emotion_name": emotion_name,
                "emotion_intensity": emotion_intensity,
                "project_suppresses_emotion": project_suppresses_emotion,
            },
        ))
    except Exception:
        # emit() already isolates subscriber failures; this guards the
        # emission itself. A reply that reached the user must never be
        # undone by bookkeeping about it.
        logger.debug("publish_turn_completed failed", exc_info=True)
