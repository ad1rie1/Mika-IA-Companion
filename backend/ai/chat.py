"""ChatPrompt — the structured form of a conversation turn.

Historically the pipeline flattened everything into two strings: one system
prompt rebuilt from scratch every turn, and one user prompt containing the
whole conversation history as ``User: …\\n\\nAssistant: …`` text. That shape
made provider-side prompt caching impossible (the prefix changed every turn),
lost role fidelity (a user typing ``Assistant:`` forged a turn), and re-billed
the entire context on every call.

``ChatPrompt`` splits the same content along its real volatility boundaries:

- ``system_stable``   — personality + self-concept + identity. Changes rarely
  (self-narrative regenerates ~daily, identity on a claim). This is the
  cacheable prefix a hosted API can serve at ~0.1× the input price.
- ``system_volatile`` — everything recomputed per turn (mood, circadian,
  ruminations, modules, memory retrieval, …). Deliberately kept *out* of the
  cacheable prefix.
- ``history``         — the short-term buffer as real ``{role, content}``
  messages, so providers with a messages API get actual turns.
- ``message``         — the current user message, alone.

Providers choose their optimal rendering:

- Chat-native providers (Claude, OpenAI-compatibles, Ollama) send
  ``system_stable`` as system, the history as real messages, and embed
  ``system_volatile`` inside the *final* user turn — after the cache
  boundary, so per-turn state never invalidates the reusable prefix
  (server-side prompt cache for Claude, automatic prefix caching for
  OpenAI-compatibles, KV-cache reuse for Ollama).
- Providers without a chat method (GLM, Gemini) get the legacy two-string
  shape via :meth:`legacy_pair` — same rendering as the old pipeline, with
  one deliberate divergence: history messages are clipped at
  ``HISTORY_MSG_MAX_CHARS`` on every path.

This module lives in ``ai/`` because providers consume the type; it must not
import anything from ``pipeline`` (the dependency points the other way).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Markers wrapping the volatile state when it rides inside the final user
# turn. Named so the model reads it as ambient system state, not as something
# the person in front of her actually typed.
CONTEXT_HEADER = "--- ETAT INTERNE (contexte fourni par le systeme, pas par l'utilisateur) ---"
CONTEXT_FOOTER = "--- FIN ETAT INTERNE ---"

# Injected when the buffer opens on an assistant turn (Mika spoke first —
# greeting, conscience initiative): the Messages API requires the first
# message to be a user turn.
_RESUME_MARKER = "[Reprise de la conversation.]"

# Per-message ceiling on history entries. The RAM buffer caps the *count*
# (20 messages) but not the size: a 50 kB paste enters verbatim and is
# re-sent on every turn until it rotates out — ~10 turns of dead weight.
# 4 000 chars (~1 000 tokens) keeps any real conversational message intact.
HISTORY_MSG_MAX_CHARS = 4000
_TRUNCATION_MARK = " …[tronqué]"

# En-tête du résumé roulant (compaction du fil). Rendu comme PREMIER message
# user du tableau : il vit dans la zone cacheable des messages et ne change
# qu'à chaque passe de compaction (rare par hystérésis).
SUMMARY_HEADER = "[Fil de la conversation jusqu'ici — résumé]"
# Ceinture : le compactor vise bien plus court, mais le résumé ne doit
# jamais pouvoir manger la part du fil vivant.
SUMMARY_MAX_CHARS = 8000


def _clip_msg(content: str) -> str:
    if len(content) <= HISTORY_MSG_MAX_CHARS:
        return content
    return content[: HISTORY_MSG_MAX_CHARS - len(_TRUNCATION_MARK)].rstrip() + _TRUNCATION_MARK


@dataclass
class ChatPrompt:
    """A conversation turn, split along volatility boundaries."""

    system_stable: str
    system_volatile: str = ""
    history: list[dict] = field(default_factory=list)
    message: str = ""
    # Résumé roulant des segments déjà compactés du fil ("" = aucun).
    conversation_summary: str = ""

    # ── Full-fidelity views ─────────────────────────────────────

    def system_full(self) -> str:
        """Stable + volatile as one system string (legacy rendering)."""
        if self.system_volatile:
            return f"{self.system_stable}\n\n{self.system_volatile}"
        return self.system_stable

    def chat_messages(self) -> list[dict]:
        """History + current message as a proper messages array.

        - Roles other than user/assistant and empty contents are dropped
          (the flattener silently dropped them too).
        - A leading assistant turn gets a neutral user marker prepended,
          because the API requires ``messages[0]`` to be a user turn.
        - The volatile state block is embedded at the top of the *final*
          user turn: it sits after the cacheable prefix (system + history),
          so per-turn state never invalidates what is already cached.
        """
        msgs: list[dict] = []
        for m in self.history or []:
            role = m.get("role")
            content = (m.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                msgs.append({"role": role, "content": _clip_msg(content)})
        if self.conversation_summary:
            # Avant le garde premier-message : le résumé EST un tour user
            # valide, donc un historique qui s'ouvrait sur Mika n'a plus
            # besoin du marqueur de reprise.
            msgs.insert(0, {
                "role": "user",
                "content": f"{SUMMARY_HEADER}\n{self.conversation_summary[:SUMMARY_MAX_CHARS]}",
            })
        if msgs and msgs[0]["role"] == "assistant":
            msgs.insert(0, {"role": "user", "content": _RESUME_MARKER})

        final = self.message
        if self.system_volatile:
            final = (
                f"{CONTEXT_HEADER}\n{self.system_volatile}\n{CONTEXT_FOOTER}"
                f"\n\n{self.message}"
            )
        msgs.append({"role": "user", "content": final})
        return msgs

    # ── Legacy view (fallback providers) ────────────────────────

    def legacy_pair(self) -> tuple[str, str]:
        """(system_prompt, user_prompt) as the old pipeline built them.

        Same rendering as ``build_system_prompt`` + ``format_conversation``,
        with one deliberate divergence: history messages beyond
        ``HISTORY_MSG_MAX_CHARS`` are clipped (the old flattener resent a
        50 kB paste verbatim on every turn until it rotated out).
        """
        flat = ""
        if self.conversation_summary:
            flat += (
                f"User: {SUMMARY_HEADER}\n"
                f"{self.conversation_summary[:SUMMARY_MAX_CHARS]}\n\n"
            )
        for m in self.history or []:
            role = m.get("role")
            content = m.get("content")
            if isinstance(content, str):
                content = _clip_msg(content)
            if role == "user":
                flat += f"User: {content}\n\n"
            elif role == "assistant":
                flat += f"Assistant: {content}\n\n"
        flat += f"User: {self.message}"
        return self.system_full(), flat
