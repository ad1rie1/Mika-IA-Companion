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
- Gemini maps the same structure onto ``system_instruction`` + ``contents``.
  No provider consumes :meth:`legacy_pair` any more: it survives for the
  router's own character estimate, and renders the old two-string shape
  with two deliberate divergences — history messages are clipped at
  ``HISTORY_MSG_MAX_CHARS``, and a turn said by someone else than the
  current interlocutor is named (see :func:`_speaker_of`).

This module lives in ``ai/`` because providers consume the type; it must not
import anything from ``pipeline`` (the dependency points the other way).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from old.backend.configs.runtime import cfg_int

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
# Configurable (``ai.chat.history_msg_max_chars``) ; la constante reste le
# repli. Lire par ``history_msg_max_chars()`` et non par la constante : un
# ``from ai.chat import HISTORY_MSG_MAX_CHARS`` fige la valeur à l'import et
# ne suivrait jamais le réglage.
HISTORY_MSG_MAX_CHARS = 4000
_TRUNCATION_MARK = " …[tronqué]"

# En-tête du résumé roulant (compaction du fil). Rendu comme PREMIER message
# user du tableau : il vit dans la zone cacheable des messages et ne change
# qu'à chaque passe de compaction (rare par hystérésis).
SUMMARY_HEADER = "[Fil de la conversation jusqu'ici — résumé]"
# Ceinture : le compactor vise bien plus court, mais le résumé ne doit
# jamais pouvoir manger la part du fil vivant.
SUMMARY_MAX_CHARS = 8000


# Borne du nom de locuteur rendu devant un tour d'historique. Le nom vient
# d'un ``display_name`` en base : un retour à la ligne y forgerait un tour.
# Garde-fou d'injection, pas un réglage.
_SPEAKER_MAX_CHARS = 40


def history_msg_max_chars() -> int:
    """Plafond courant d'un message d'historique, réglage inclus.

    Existe comme *fonction* parce que la constante est importée ailleurs
    (``pipeline/prompt.py``, qui la reprend pour sa comptabilité de poids) :
    un import lie la valeur une fois pour toutes au chargement du module, et
    le réglage ne l'atteindrait jamais.
    """
    return cfg_int(
        "ai.chat.history_msg_max_chars", HISTORY_MSG_MAX_CHARS, mini=1,
    )


def summary_max_chars() -> int:
    """Plafond courant du résumé roulant, réglage inclus."""
    return cfg_int("ai.chat.summary_max_chars", SUMMARY_MAX_CHARS, mini=1)


def _clip_msg(content: str) -> str:
    plafond = history_msg_max_chars()
    if len(content) <= plafond:
        return content
    return content[: plafond - len(_TRUNCATION_MARK)].rstrip() + _TRUNCATION_MARK


def _speaker_of(m: dict) -> str:
    """Nom du tiers ayant dit ce tour, ou "" — posé par le contexte.

    Le tampon court terme est partagé par tout le monde (« quelqu'un dans une
    pièce entend ce qui s'y dit »), donc l'historique d'un tour d'Alice arrive
    dans le prompt de Thomas. Rendu « User: », il se lit comme une phrase de
    Thomas et le modèle la lui attribue. Seuls les tours *user* sont marqués :
    les réponses de Mika sont les siennes quel que soit le destinataire.
    """
    if m.get("role") != "user":
        return ""
    raw = (m.get("speaker") or "").strip()
    if not raw:
        return ""
    return raw.replace("\n", " ").replace("\r", " ")[:_SPEAKER_MAX_CHARS].strip()


@dataclass(frozen=True)
class VolatileBlock:
    """Une couche volatile encore séparable de son en-tête.

    ``system_volatile`` est la concaténation rendue de ces blocs ; la borne
    globale du tour (``ai.budget.fit_turn``) a besoin de couper une couche
    *nommée* sans laisser un « --- CE QUE TU SAIS DE CETTE PERSONNE --- »
    sans sa fin.
    """

    field: str
    value: str
    header: str | None = None
    footer: str = "--- FIN ---"

    def render(self) -> str:
        if self.header is None:
            return self.value
        return f"{self.header}\n{self.value}\n{self.footer}"


@dataclass
class ChatPrompt:
    """A conversation turn, split along volatility boundaries."""

    system_stable: str
    system_volatile: str = ""
    history: list[dict] = field(default_factory=list)
    message: str = ""
    # Résumé roulant des segments déjà compactés du fil ("" = aucun).
    conversation_summary: str = ""
    # Décomposition de ``system_volatile``, quand le constructeur la fournit.
    # Vide = borne globale sans prise sur les couches (elle ne coupe alors que
    # le résumé et se contente de rapporter le dépassement).
    volatile_blocks: list[VolatileBlock] = field(default_factory=list)

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
        - A turn carrying a ``speaker`` is prefixed with that name.
        """
        msgs: list[dict] = []
        for m in self.history or []:
            role = m.get("role")
            content = (m.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                # Clipper PUIS nommer : le cap borne le message, pas le nom.
                content = _clip_msg(content)
                speaker = _speaker_of(m)
                if speaker:
                    content = f"{speaker}: {content}"
                msgs.append({"role": role, "content": content})
        if self.conversation_summary:
            # Avant le garde premier-message : le résumé EST un tour user
            # valide, donc un historique qui s'ouvrait sur Mika n'a plus
            # besoin du marqueur de reprise.
            msgs.insert(0, {
                "role": "user",
                "content": (
                    f"{SUMMARY_HEADER}\n"
                    f"{self.conversation_summary[:summary_max_chars()]}"
                ),
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
        speaker labelling included (``User (Alice): …``) — that is the shape
        ``format_conversation`` has always produced, and the only one in the
        repo for that fact. One deliberate divergence: history messages
        beyond ``HISTORY_MSG_MAX_CHARS`` are clipped (the old flattener
        resent a 50 kB paste verbatim on every turn until it rotated out).
        """
        flat = ""
        if self.conversation_summary:
            flat += (
                f"User: {SUMMARY_HEADER}\n"
                f"{self.conversation_summary[:summary_max_chars()]}\n\n"
            )
        for m in self.history or []:
            role = m.get("role")
            content = m.get("content")
            if isinstance(content, str):
                content = _clip_msg(content)
            if role == "user":
                speaker = _speaker_of(m)
                label = f"User ({speaker})" if speaker else "User"
                flat += f"{label}: {content}\n\n"
            elif role == "assistant":
                flat += f"Assistant: {content}\n\n"
        flat += f"User: {self.message}"
        return self.system_full(), flat
