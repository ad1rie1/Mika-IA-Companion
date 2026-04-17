"""Prompt construction — system prompt assembly and conversation formatting.

Extracted from ai/client.py. This is orchestration logic, not AI infra.
"""

from config.personality import personality


def build_system_prompt(
    emotion_context: str = "",
    memory_context: str = "",
    module_context: str = "",
    self_concept: str = "",
    person_context: str = "",
    circadian_context: str = "",
    fatigue_fog: str = "",
    rumination_context: str = "",
    user_mood_hint: str = "",
) -> str:
    """Assemble the full system prompt from personality + contextual layers.

    Order matters for the model's attention:
      personality        (who she is from the start)
      → self-concept      (who she is becoming, from her own memories)
      → person-context    (who she's talking to, what she knows about them)
      → user-mood         (how the interlocutor seems to feel right now)
      → circadian        (what time of day / how tired she is)
      → fatigue-fog       (cognitive blur when energy is low — shapes tone)
      → ruminations       (unresolved thoughts still on Mika's mind)
      → modules           (available tools/context)
      → emotion           (current affective state)
      → memory            (retrieved relevant memories)

    Self-concept + person-context sit right after personality because
    they're stable over a session. Circadian is also a "slow" layer so
    it sits alongside them. Modules / emotion / memory are recomputed
    every turn and appear last so recency biases recall.
    """
    system = personality.to_system_prompt()

    if self_concept:
        system += (
            "\n\n--- QUI TU ES DEVENUE ---\n"
            + self_concept
            + "\n--- FIN ---"
        )
    if person_context:
        system += (
            "\n\n--- CE QUE TU SAIS DE CETTE PERSONNE ---\n"
            + person_context
            + "\n--- FIN ---"
        )
    if user_mood_hint:
        system += (
            "\n\n--- CE QUE TU PERCOIS DE SON ETAT ---\n"
            + user_mood_hint
            + "\n--- FIN ---"
        )
    if circadian_context:
        system += (
            "\n\n--- TON RYTHME ---\n"
            + circadian_context
            + "\n--- FIN ---"
        )
    if fatigue_fog:
        system += (
            "\n\n--- ETAT COGNITIF ---\n"
            + fatigue_fog
            + "\n--- FIN ---"
        )
    if rumination_context:
        system += (
            "\n\n--- CE QUI TE TROTTE DANS LA TETE ---\n"
            + rumination_context
            + "\n--- FIN ---"
        )
    if module_context:
        system += (
            "\n\n--- CONTEXTE MODULES ---\n"
            + module_context
            + "\n--- FIN CONTEXTE MODULES ---"
        )
    if emotion_context:
        system += (
            "\n\n--- TON ETAT EMOTIONNEL ACTUEL ---\n"
            + emotion_context
            + "\n--- FIN ETAT EMOTIONNEL ---"
        )
    if memory_context:
        system += "\n\n" + memory_context

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
