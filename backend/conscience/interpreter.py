"""Signal interpreter — classifies and scores module events.

Uses heuristic fast-path for known event types, and a configurable
AI provider for rich/unknown events (emails, RSS, etc.).
Follows the same pattern as memory/extractor.py.
"""

from __future__ import annotations

import asyncio
import json
import logging

from ai.router import AIRole, UnconfiguredRoleError, ai_router
from utils.degradation import degradations
from utils.parsing import strip_markdown_json
from conscience.types import InterpretedSignal
from modules.types import ModuleEvent

logger = logging.getLogger(__name__)

INTERPRETATION_TIMEOUT = 15  # seconds

# fmt: off
INTERPRETATION_SYSTEM_PROMPT = """\
Tu es le module d'interpretation sensorielle de {name}. \
Tu ne reponds PAS a la conversation. Tu ANALYSES un signal entrant \
et tu retournes UNIQUEMENT du JSON valide.

{name} est: {description}. Ses interets: {interests}.

RETOURNE ce JSON (rien d'autre):
{{
  "summary": "Resume en 1 phrase de ce signal",
  "category": "communication|emotional|memory|temporal|external|system",
  "pertinence": 0.5,
  "emotional_reaction": "emotion_name ou vide",
  "emotional_intensity": 0.0,
  "themes": ["theme1"],
  "entities": ["entity1"],
  "should_remember": false
}}

REGLES:
- pertinence: 0.0=bruit total, 0.5=normal, 0.8=important, 1.0=critique
- emotional_reaction: l'emotion que {name} ressentirait en voyant ca (ou vide si neutre)
- should_remember: true si ce signal merite un souvenir durable
- Sois concise et precise
"""
# fmt: on


def _extract_themes_from_text(text: str) -> list[str]:
    """Extract basic themes from message text via keyword matching.

    Cheap heuristic so that heuristic-path signals can still trigger
    memory boosting (which relies on themes).
    """
    if not text:
        return []
    text_lower = text.lower()
    theme_keywords = {
        "gaming": ["jeu", "jouer", "game", "gaming", "zelda", "minecraft", "steam"],
        "musique": ["musique", "chanson", "chanter", "music", "playlist"],
        "cuisine": ["cuisine", "manger", "recette", "plat", "cook"],
        "tech": ["code", "programmer", "python", "javascript", "dev", "tech"],
        "anime": ["anime", "manga", "otaku", "vtuber"],
        "art": ["dessin", "dessiner", "art", "peindre", "peinture"],
        "sport": ["sport", "foot", "velo", "courir", "gym"],
    }
    return [
        theme for theme, keywords in theme_keywords.items()
        if any(kw in text_lower for kw in keywords)
    ]


def _heuristic_chat_message(data: dict) -> InterpretedSignal:
    person = data.get("person_id", "?")
    source = data.get("source", "frontend")
    text = data.get("text", "")
    return InterpretedSignal(
        summary=f"Message de {person} via {source}",
        category="communication",
        pertinence=0.3,
        emotional_reaction="",
        emotional_intensity=0.0,
        themes=_extract_themes_from_text(text),
        entities=[person] if person != "?" else [],
        should_remember=False,
    )


def _heuristic_chat_connect(data: dict) -> InterpretedSignal:
    return InterpretedSignal(
        summary="Un utilisateur s'est connecte",
        category="system",
        pertinence=0.1,
        emotional_reaction="",
        emotional_intensity=0.0,
        themes=[],
        entities=[],
        should_remember=False,
    )


def _heuristic_chat_disconnect(data: dict) -> InterpretedSignal:
    return InterpretedSignal(
        summary="Un utilisateur s'est deconnecte",
        category="system",
        pertinence=0.1,
        emotional_reaction="",
        emotional_intensity=0.0,
        themes=[],
        entities=[],
        should_remember=False,
    )


def _heuristic_telegram_message(data: dict) -> InterpretedSignal:
    """Telegram messages are already handled by notify_ai for direct reply.
    The Conscience just observes them for context accumulation."""
    user = data.get("user_name", data.get("person_id", "?"))
    text = data.get("text", "")
    return InterpretedSignal(
        summary=f"Message Telegram de {user}: {text[:80]}",
        category="communication",
        pertinence=0.4,
        emotional_reaction="",
        emotional_intensity=0.0,
        themes=_extract_themes_from_text(text),
        entities=[user] if user != "?" else [],
        should_remember=False,
    )


def _heuristic_rss_entry(data: dict) -> InterpretedSignal:
    """A news headline is not worth an LLM call.

    The RSS poller emits one event per *new entry* — up to 15 per feed, and a
    first poll across a handful of feeds produces dozens at once. Each one
    took a Haiku call (15s timeout) and, because ``emit_event`` awaits the
    conscience, they ran strictly in series. That was minutes of frozen
    scheduler and a stack of LLM calls to decide that a headline is mildly
    interesting.

    Pertinence is scored from the feed's own signal: title keywords matched
    against what Mika is curious about. Anything that scores high enough to
    matter still reaches her — the conscience decides whether to act, and a
    genuinely pertinent item can be read in full through the RSS tools.
    """
    title = data.get("title", "") or ""
    summary = data.get("summary", "") or ""
    feed = data.get("feed_name", "") or "un flux"
    themes = _extract_themes_from_text(f"{title} {summary}")

    # Matching a theme Mika cares about is the whole signal here; without one
    # this is background noise she happens to subscribe to.
    pertinence = 0.45 if themes else 0.2
    return InterpretedSignal(
        summary=f"[{feed}] {title[:120]}",
        category="information",
        pertinence=pertinence,
        emotional_reaction="curious" if themes else "",
        emotional_intensity=0.25 if themes else 0.0,
        themes=themes,
        entities=[],
        should_remember=False,
    )


def _heuristic_forge_event(data: dict) -> InterpretedSignal:
    """Signals Mika's own forged modules emit about themselves.

    She wrote the module and chose what it reports, so paying for an LLM to
    tell her what her own code just said is circular. Low pertinence by
    default: a forged module that wants attention says so through
    ``api.notify_ai``, which is a different path entirely.
    """
    return InterpretedSignal(
        summary=f"Un de tes modules a signale: {str(data)[:160]}",
        category="system",
        pertinence=0.2,
        emotional_reaction="",
        emotional_intensity=0.0,
        themes=[],
        entities=[],
        should_remember=False,
    )


# email.received goes through LLM path: an email is genuinely rich content
# whose importance cannot be read off a keyword table, and there are few
# enough of them that the call is worth it.

#: Heuristic fast-path for common events (no LLM call needed).
HEURISTIC_EVENTS: dict[str, callable] = {
    "chat.message": _heuristic_chat_message,
    "chat.connect": _heuristic_chat_connect,
    "chat.disconnect": _heuristic_chat_disconnect,
    "telegram.message": _heuristic_telegram_message,
    "rss.new_entry": _heuristic_rss_entry,
}

#: Event-type prefixes routed to a heuristic. Forged modules emit
#: ``forge.<module>.<type>``, so they cannot be listed exhaustively.
HEURISTIC_PREFIXES: tuple[tuple[str, callable], ...] = (
    ("forge.", _heuristic_forge_event),
)


def heuristic_for(event_type: str):
    """Return the heuristic handling ``event_type``, or None for the LLM path."""
    handler = HEURISTIC_EVENTS.get(event_type)
    if handler is not None:
        return handler
    for prefix, prefix_handler in HEURISTIC_PREFIXES:
        if event_type.startswith(prefix):
            return prefix_handler
    return None


class SignalInterpreter:
    """Interprets raw module events into structured signals.

    Uses heuristic fast-path for known events, falls back to
    Claude Haiku for rich or unknown events.
    """

    def __init__(self):
        self._system_prompt: str | None = None

    async def interpret(self, event: ModuleEvent) -> InterpretedSignal:
        """Interpret a module event into a structured signal."""

        # Fast-path: known event types (exact match or prefix)
        heuristic = heuristic_for(event.event_type)
        if heuristic:
            signal = heuristic(event.data)
            logger.debug(
                "Interpreted (heuristic): %s → %s (p=%.1f)",
                event.event_type, signal.category, signal.pertinence,
            )
            return signal

        # LLM path: unknown or rich events
        try:
            signal = await asyncio.wait_for(
                self._interpret_with_llm(event),
                timeout=INTERPRETATION_TIMEOUT,
            )
            logger.info(
                "Interpreted (LLM): %s → %s (p=%.1f, emotion=%s)",
                event.event_type, signal.category, signal.pertinence,
                signal.emotional_reaction or "none",
            )
            return signal
        except asyncio.TimeoutError:
            logger.warning("Interpretation timed out for %s", event.event_type)
            return self._fallback_signal(event)
        except UnconfiguredRoleError as exc:
            logger.warning(
                "Interprétation heuristique pour %s — IA non configurée: %s",
                event.event_type, exc,
            )
            return self._fallback_signal(event)
        except Exception:
            logger.exception("Interpretation error for %s", event.event_type)
            return self._fallback_signal(event)

    async def _interpret_with_llm(self, event: ModuleEvent) -> InterpretedSignal:
        """Use configured AI provider to interpret an event."""
        prompt = self._build_prompt(event)

        raw_text = await ai_router.complete(
            role=AIRole.SIGNAL_INTERPRETATION,
            system_prompt=self._get_system_prompt(),
            user_prompt=prompt,
        )

        raw = raw_text.strip()
        if not raw:
            return self._fallback_signal(event)

        return self._parse_response(raw, event)

    def _get_system_prompt(self) -> str:
        """Build interpretation system prompt with personality context."""
        if self._system_prompt is None:
            from config.personality import personality

            interests = ", ".join(personality.interests) if personality.interests else ""
            self._system_prompt = INTERPRETATION_SYSTEM_PROMPT.format(
                name=personality.name,
                description=personality.description,
                interests=interests,
            )
        return self._system_prompt

    def _build_prompt(self, event: ModuleEvent) -> str:
        """Build the user prompt for Haiku interpretation with actual event data."""
        content = json.dumps(event.data, ensure_ascii=False, default=str)[:1000]
        return (
            f"SIGNAL A INTERPRETER:\n"
            f"Source: {event.source_module}\n"
            f"Type: {event.event_type}\n"
            f"Contenu: {content}"
        )

    def _parse_response(self, raw: str, event: ModuleEvent) -> InterpretedSignal:
        """Parse JSON response from the model."""
        text = strip_markdown_json(raw)

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("Interpretation JSON parse failed: %.200s", repr(raw))
            # L'appel Haiku est paye, mais la pertinence retombe au defaut :
            # le signal est traite comme s'il n'avait jamais ete interprete.
            degradations.record("conscience: JSON d'interpretation illisible", exc)
            return self._fallback_signal(event)

        return InterpretedSignal(
            summary=data.get("summary", ""),
            category=data.get("category", "system"),
            pertinence=max(0.0, min(1.0, float(data.get("pertinence", 0.5)))),
            emotional_reaction=data.get("emotional_reaction", ""),
            emotional_intensity=max(
                0.0, min(1.0, float(data.get("emotional_intensity", 0.0)))
            ),
            themes=data.get("themes", []),
            entities=data.get("entities", []),
            should_remember=bool(data.get("should_remember", False)),
        )

    @staticmethod
    def _fallback_signal(event: ModuleEvent) -> InterpretedSignal:
        """Minimal signal when interpretation fails."""
        return InterpretedSignal(
            summary=f"Signal non interprete: {event.event_type}",
            category="system",
            pertinence=0.3,
            emotional_reaction="",
            emotional_intensity=0.0,
            should_remember=False,
        )
