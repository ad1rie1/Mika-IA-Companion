"""Prompt construction — system prompt assembly and conversation formatting.

Extracted from ai/client.py. This is orchestration logic, not AI infra.
"""

from config.personality import personality


def build_system_prompt(
    emotion_context: str = "",
    memory_context: str = "",
    module_context: str = "",
    self_concept: str = "",
) -> str:
    """Assemble the full system prompt from personality + contextual layers.

    Order matters for the model's attention: personality (who she is from
    the start) → self-concept (who she is becoming, an evolving paragraph
    fed from her own memories) → modules → current emotional state → memory.
    The self-concept sits between the static personality and the dynamic
    layers so the model reads "this is your baseline, this is how you've
    drifted, and here's what's happening now."
    """
    system = personality.to_system_prompt()

    if self_concept:
        system += (
            "\n\n--- QUI TU ES DEVENUE ---\n"
            + self_concept
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
