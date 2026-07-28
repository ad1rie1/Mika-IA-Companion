"""The notify_ai bridge — a module asking for Mika's attention.

Distinct from the event bus, and the distinction is the whole point:

  ``emit_event``   "this happened."  Fan-out, no reply, nobody obliged to
                   care. The conscience may decide it is worth a thought,
                   later, or never.
  ``notify_ai``    "answer this."    A single perception through the full
                   pipeline, returning what she said.

Modules reach it through the callback injected by the manager
(``self._notify_ai``) so they never import the pipeline — which keeps the
dependency pointing one way and lets a forged module use it through the
Forge's rate-limited wrapper without a way around the limit.
"""

from __future__ import annotations

import logging

from modules.types import AIDecision, ModuleNotification

logger = logging.getLogger(__name__)


async def notify_ai(notification: ModuleNotification) -> AIDecision:
    """Wake Mika with a module notification and return her decision.

    Builds an ``INTERNAL_TRIGGER`` Perception and routes it, so a module
    initiative flows through exactly the same pipeline as a chat message
    rather than a private path with its own rules.
    """
    from pipeline.perception import Perception
    from pipeline.router import perceive

    prompt = (
        f"[NOTIFICATION du module '{notification.source_module}']\n"
        f"Resume: {notification.summary}\n"
        f"Details: {notification.details}\n"
        f"Urgence: {notification.urgency}\n"
    )
    if notification.suggested_action:
        prompt += f"Action suggeree: {notification.suggested_action}\n"

    # Person id — a module may override it (e.g. the Telegram user the
    # notification is about); otherwise the module itself is the "person".
    person_id = notification.metadata.get(
        "person_id", f"module_{notification.source_module}",
    )

    logger.info(
        "[notify_ai/%s] person=%s | %s",
        notification.source_module, person_id, notification.summary,
    )

    perception = Perception.from_internal_trigger(
        prompt,
        source=notification.source_module,
        person_id=person_id,
        metadata={
            "urgency": notification.urgency,
            "suggested_action": notification.suggested_action,
            **notification.metadata,
        },
    )

    output = await perceive(perception)
    if output is None:
        # The router always returns a SpeechOutput for INTERNAL_TRIGGER
        # today; stay defensive so a future routing change degrades to
        # "she said nothing" rather than an AttributeError in a module.
        return AIDecision(response_text="", emotion=None, tool_calls_made=[])

    return AIDecision(
        response_text=output.text,
        emotion=output.emotion_data,
        tool_calls_made=output.tool_calls,
    )
