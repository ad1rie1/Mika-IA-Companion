"""
Tests for the SignalInterpreter's heuristic fast-path.

The heuristic functions are pure (no LLM, no async) so they
can be tested directly with synthetic event data.
"""

import pytest

from conscience.interpreter import (
    _heuristic_chat_message,
    _heuristic_chat_connect,
    _heuristic_chat_disconnect,
    _heuristic_telegram_message,
    _extract_themes_from_text,
    HEURISTIC_EVENTS,
    SignalInterpreter,
)
from conscience.types import InterpretedSignal
from modules.types import ModuleEvent


# ===================================================================
# THEME EXTRACTION
# ===================================================================

class TestThemeExtraction:

    def test_gaming_themes(self):
        themes = _extract_themes_from_text("On joue a Minecraft ce soir ?")
        assert "gaming" in themes

    def test_tech_themes(self):
        themes = _extract_themes_from_text("Je code en Python un truc de fou")
        assert "tech" in themes

    def test_anime_themes(self):
        themes = _extract_themes_from_text("T'as vu le dernier anime ?")
        assert "anime" in themes

    def test_music_themes(self):
        themes = _extract_themes_from_text("J'adore cette chanson, la musique c'est ma vie")
        assert "musique" in themes

    def test_cooking_themes(self):
        themes = _extract_themes_from_text("J'ai une super recette de cuisine a partager")
        assert "cuisine" in themes

    def test_art_themes(self):
        themes = _extract_themes_from_text("Je fais du dessin et de la peinture")
        assert "art" in themes

    def test_sport_themes(self):
        themes = _extract_themes_from_text("Je suis alle courir et faire du velo")
        assert "sport" in themes

    def test_multiple_themes(self):
        themes = _extract_themes_from_text("Je code un jeu avec de la musique")
        assert "tech" in themes
        assert "gaming" in themes
        assert "musique" in themes

    def test_no_themes(self):
        themes = _extract_themes_from_text("Salut ca va ?")
        assert themes == []

    def test_empty_text(self):
        themes = _extract_themes_from_text("")
        assert themes == []

    def test_case_insensitive(self):
        themes = _extract_themes_from_text("PYTHON est genial pour le DEV")
        assert "tech" in themes


# ===================================================================
# CHAT MESSAGE HEURISTIC
# ===================================================================

class TestChatMessageHeuristic:

    def test_basic_message(self):
        signal = _heuristic_chat_message({
            "person_id": "alice_123",
            "source": "frontend",
            "text": "Salut Mika !",
        })

        assert isinstance(signal, InterpretedSignal)
        assert signal.category == "communication"
        assert signal.pertinence == 0.3
        assert "alice_123" in signal.summary
        assert "frontend" in signal.summary
        assert "alice_123" in signal.entities
        assert signal.should_remember is False

    def test_message_with_themes(self):
        signal = _heuristic_chat_message({
            "person_id": "bob",
            "source": "frontend",
            "text": "Tu joues a des jeux en Python ?",
        })

        assert "gaming" in signal.themes
        assert "tech" in signal.themes

    def test_unknown_person(self):
        signal = _heuristic_chat_message({
            "source": "frontend",
            "text": "yo",
        })

        assert signal.entities == []  # "?" is filtered out
        assert "?" in signal.summary

    def test_no_emotional_reaction(self):
        """Chat messages should not trigger emotional reactions heuristically."""
        signal = _heuristic_chat_message({
            "person_id": "user",
            "text": "JE SUIS EN COLERE !!!",
        })

        assert signal.emotional_reaction == ""
        assert signal.emotional_intensity == 0.0


# ===================================================================
# CHAT CONNECT/DISCONNECT HEURISTICS
# ===================================================================

class TestConnectionHeuristics:

    def test_connect(self):
        signal = _heuristic_chat_connect({})

        assert signal.category == "system"
        assert signal.pertinence == 0.1
        assert "connecte" in signal.summary
        assert signal.themes == []
        assert signal.entities == []
        assert signal.should_remember is False

    def test_disconnect(self):
        signal = _heuristic_chat_disconnect({})

        assert signal.category == "system"
        assert signal.pertinence == 0.1
        assert "deconnecte" in signal.summary
        assert signal.should_remember is False


# ===================================================================
# TELEGRAM MESSAGE HEURISTIC
# ===================================================================

class TestTelegramHeuristic:

    def test_basic_telegram_message(self):
        signal = _heuristic_telegram_message({
            "user_name": "jean_tg",
            "person_id": "tg_12345",
            "text": "Salut Mika depuis Telegram !",
        })

        assert signal.category == "communication"
        assert signal.pertinence == 0.4  # higher than web chat
        assert "jean_tg" in signal.summary
        assert "Telegram" in signal.summary
        assert "jean_tg" in signal.entities

    def test_telegram_with_themes(self):
        signal = _heuristic_telegram_message({
            "user_name": "dev_fan",
            "text": "J'ai code un truc en javascript trop bien",
        })

        assert "tech" in signal.themes

    def test_telegram_long_text_truncated_in_summary(self):
        long_text = "A" * 200
        signal = _heuristic_telegram_message({
            "user_name": "verbose",
            "text": long_text,
        })

        # Summary should contain truncated text (max 80 chars)
        assert len(signal.summary) < len(long_text)

    def test_telegram_no_username_fallback(self):
        signal = _heuristic_telegram_message({
            "person_id": "tg_999",
            "text": "yo",
        })

        assert "tg_999" in signal.summary


# ===================================================================
# HEURISTIC EVENT ROUTING
# ===================================================================

class TestHeuristicRouting:

    def test_known_events_have_heuristics(self):
        """All expected event types should have heuristic handlers."""
        expected = ["chat.message", "chat.connect", "chat.disconnect", "telegram.message"]
        for event_type in expected:
            assert event_type in HEURISTIC_EVENTS, \
                f"Missing heuristic for {event_type}"

    def test_unknown_event_not_in_heuristics(self):
        """Unknown events should NOT have a heuristic (goes to LLM path)."""
        assert "email.received" not in HEURISTIC_EVENTS
        assert "rss.new_article" not in HEURISTIC_EVENTS
        assert "random.event" not in HEURISTIC_EVENTS


# ===================================================================
# SIGNAL INTERPRETER (async, but heuristic path doesn't need LLM)
# ===================================================================

class TestSignalInterpreter:

    @pytest.mark.asyncio
    async def test_interpret_chat_message_uses_heuristic(self):
        """Known events should use heuristic path (no LLM call)."""
        interpreter = SignalInterpreter()
        event = ModuleEvent(
            event_type="chat.message",
            source_module="frontend",
            data={
                "person_id": "user1",
                "source": "frontend",
                "text": "Salut !",
            },
        )

        signal = await interpreter.interpret(event)

        assert isinstance(signal, InterpretedSignal)
        assert signal.category == "communication"
        assert signal.pertinence == 0.3

    @pytest.mark.asyncio
    async def test_interpret_connect_uses_heuristic(self):
        interpreter = SignalInterpreter()
        event = ModuleEvent(
            event_type="chat.connect",
            source_module="frontend",
            data={},
        )

        signal = await interpreter.interpret(event)
        assert signal.category == "system"
        assert signal.pertinence == 0.1

    @pytest.mark.asyncio
    async def test_fallback_signal_for_unknown_event(self):
        """Unknown events with no LLM should produce a fallback."""
        interpreter = SignalInterpreter()
        event = ModuleEvent(
            event_type="unknown.event",
            source_module="mystery",
            data={"key": "value"},
        )

        # Mock the LLM path to fail (no API configured in tests)
        from unittest.mock import AsyncMock, patch
        with patch.object(interpreter, "_interpret_with_llm",
                         side_effect=Exception("no LLM in tests")):
            signal = await interpreter.interpret(event)

        assert isinstance(signal, InterpretedSignal)
        assert "non interprete" in signal.summary
        assert signal.pertinence == 0.3

    @pytest.mark.asyncio
    async def test_fallback_signal_structure(self):
        """Fallback signal should have all required fields."""
        event = ModuleEvent(
            event_type="test.event",
            source_module="test",
            data={},
        )
        signal = SignalInterpreter._fallback_signal(event)

        assert signal.summary != ""
        assert signal.category == "system"
        assert 0.0 <= signal.pertinence <= 1.0
        assert signal.emotional_reaction == ""
        assert signal.emotional_intensity == 0.0
        assert signal.should_remember is False


# ===================================================================
# INTERPRETED SIGNAL STRUCTURE
# ===================================================================

class TestInterpretedSignal:

    def test_default_fields(self):
        signal = InterpretedSignal(
            summary="Test",
            category="communication",
            pertinence=0.5,
            emotional_reaction="happy",
            emotional_intensity=0.7,
        )
        assert signal.themes == []
        assert signal.entities == []
        assert signal.should_remember is False

    def test_all_categories_valid(self):
        valid_categories = ["communication", "emotional", "memory",
                           "temporal", "external", "system"]
        for cat in valid_categories:
            signal = InterpretedSignal(
                summary="test", category=cat,
                pertinence=0.5, emotional_reaction="", emotional_intensity=0.0,
            )
            assert signal.category == cat
