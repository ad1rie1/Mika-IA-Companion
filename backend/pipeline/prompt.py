"""Prompt construction — system prompt assembly and conversation formatting.

Extracted from ai/client.py. This is orchestration logic, not AI infra.

The layer list below used to be thirteen keyword parameters and twelve
copies of ``if x: system += "\\n\\n--- TITRE ---\\n" + x + "\\n--- FIN ---"``,
fed by a caller that transcribed a thirteen-field dataclass into thirteen
identically-named arguments. Adding one prompt block meant editing four
places (the dataclass, the gather, the transcription, the builder) and the
docstring that claimed to describe the order had already drifted away from
the code — it still listed modules → emotion → memory while dream, journal
and project had been inserted in between.

Now the order *is* the table. `_LAYERS` is the documentation, and it is the
thing that runs.
"""

from __future__ import annotations

from dataclasses import dataclass

from config.personality import personality
from pipeline.context import ConversationContext


@dataclass(frozen=True)
class _Layer:
    """One optional block of the system prompt.

    ``field`` names the ``ConversationContext`` attribute holding the text;
    an empty value means the block is skipped entirely. ``header`` of
    ``None`` appends the value raw (memory context brings its own markup).
    """

    field: str
    header: str | None = None
    footer: str = "--- FIN ---"
    # Suppressed when an active project runs in professional mode.
    muted_by_project: bool = False


# Order matters for the model's attention. Personality, self-concept,
# identity and person-context are the "slow" layers — stable across a
# session — so they lead. Circadian and fatigue shift by the hour. Modules,
# project, emotion and memory are recomputed every turn and come last, where
# recency biases recall.
#
# The footers are deliberately inconsistent (`--- FIN ---` for most,
# `--- FIN PROJET ---` and friends for three others). That is reproduced
# verbatim rather than tidied: this refactor is byte-for-byte output-
# preserving, and unifying them is a change to what the model reads, which
# belongs in its own commit with its own reasoning.
_LAYERS: tuple[_Layer, ...] = (
    _Layer("self_concept", "--- QUI TU ES DEVENUE ---"),
    # Identity sits immediately before what she knows about them, because it
    # qualifies that block: "here is Thomas's history" reads very differently
    # after "someone *claims* to be Thomas". The context layer already
    # withholds private material when certainty is too low; this says why.
    _Layer("identity_context", "--- QUI TU AS EN FACE ---"),
    _Layer("person_context", "--- CE QUE TU SAIS DE CETTE PERSONNE ---"),
    _Layer("user_mood_hint", "--- CE QUE TU PERCOIS DE SON ETAT ---"),
    _Layer("circadian_context", "--- TON RYTHME ---"),
    _Layer("fatigue_fog", "--- ETAT COGNITIF ---"),
    _Layer("rumination_context", "--- CE QUI TE TROTTE DANS LA TETE ---"),
    _Layer("dream_context", "--- CE QUE TU AS REVE CETTE NUIT ---"),
    _Layer("journal_context", "--- TON FIL D'HIER ---"),
    _Layer("module_context", "--- CONTEXTE MODULES ---", "--- FIN CONTEXTE MODULES ---"),
    # Last of the "slow" zone but before the emotional state: when a project
    # is active its tone directive must dominate the emotional expression,
    # not the other way around.
    _Layer("project_context", "--- PROJET EN COURS ---", "--- FIN PROJET ---"),
    # Suppressed in professional mode, so the prompt cannot say "tu te sens
    # excited" three lines after the project said "langage neutre". Drives
    # ride along in the same string and go quiet with it.
    _Layer(
        "emotion_context", "--- TON ETAT EMOTIONNEL ACTUEL ---",
        "--- FIN ETAT EMOTIONNEL ---", muted_by_project=True,
    ),
    # Retrieved memories arrive pre-formatted by the retriever.
    _Layer("memory_context", None),
)


def build_system_prompt(context: ConversationContext) -> str:
    """Assemble the full system prompt from personality + contextual layers.

    Takes the context object rather than unpacking it: the caller held a
    ``ConversationContext`` whose fields matched these parameters one for
    one, so the unpacking was pure transcription — and the kind that stays
    silently wrong when a field is added and one of the four places is
    missed.
    """
    suppress_emotion = context.project_suppresses_emotion

    # Personality bases itself on whether a project is active and what its
    # emotion policy says: in professional mode it drops the variability
    # block and the mandatory [EMOTION:...] tag instruction.
    system = personality.to_system_prompt(
        project_active=bool(context.project_context),
        project_suppresses_emotion=suppress_emotion,
    )

    for layer in _LAYERS:
        # Strict getattr, no default: a typo in a layer's field name would
        # otherwise read as "this block is empty" and drop it from every
        # prompt, forever, without a single error. The table trades four
        # edit sites for one, and this is the price of that trade.
        value = getattr(context, layer.field)
        if not value:
            continue
        if layer.muted_by_project and suppress_emotion:
            continue
        if layer.header is None:
            system += "\n\n" + value
        else:
            system += f"\n\n{layer.header}\n{value}\n{layer.footer}"

    return system


def format_conversation(
    message: str,
    conversation_history: list[dict] | None = None,
) -> str:
    """Format conversation history + current message into a single prompt string."""
    full_prompt = ""
    if conversation_history:
        for msg in conversation_history:
            role = msg["role"]
            content = msg["content"]
            if role == "user":
                full_prompt += f"User: {content}\n\n"
            elif role == "assistant":
                full_prompt += f"Assistant: {content}\n\n"
    full_prompt += f"User: {message}"
    return full_prompt
