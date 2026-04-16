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
) -> str:
    """Assemble the full system prompt from personality + contextual layers.

    Order matters for the model's attention:
      personality        (who she is from the start)
      → self-concept      (who she is becoming, from her own memories)
      → person-context    (who she's talking to, what she knows about them)
      → modules           (available tools/context)
      → emotion           (current affective state)
      → memory            (retrieved relevant memories)

    Self-concept + person-context sit right after personality because
    they're stable over a session. Modules / emotion / memory are
    recomputed every turn and appear last so recency biases recall.
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
