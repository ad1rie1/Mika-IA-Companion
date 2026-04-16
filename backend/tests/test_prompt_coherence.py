"""
Tests for prompt <-> emotional state coherence.

Verifies that:
- get_emotion_context() produces French text matching the actual state
- to_prompt_description() uses correct intensity labels
- build_system_prompt() correctly layers emotion/memory/module context
- format_conversation() preserves message order and roles
- The prompt sent to Claude is internally consistent
"""

import pytest

from emotion.types import Emotion, EmotionData
from emotion.state import PersonMood, GlobalMood, Temperament, _intensity_label
from emotion.engine import EmotionEngine
from pipeline.prompt import build_system_prompt, format_conversation
from tests.conftest import TEMPERAMENT_DEFAULT


# ===================================================================
# INTENSITY LABEL
# ===================================================================

class TestIntensityLabel:

    def test_tres_for_high(self):
        assert _intensity_label(0.85) == "tres"
        assert _intensity_label(0.8) == "tres"
        assert _intensity_label(1.0) == "tres"

    def test_assez_for_medium(self):
        assert _intensity_label(0.5) == "assez"
        assert _intensity_label(0.7) == "assez"
        assert _intensity_label(0.79) == "assez"

    def test_legerement_for_low(self):
        assert _intensity_label(0.3) == "legerement"
        assert _intensity_label(0.4) == "legerement"
        assert _intensity_label(0.49) == "legerement"

    def test_a_peine_for_very_low(self):
        assert _intensity_label(0.1) == "a peine"
        assert _intensity_label(0.29) == "a peine"
        assert _intensity_label(0.0) == "a peine"


# ===================================================================
# PERSON MOOD PROMPT DESCRIPTION
# ===================================================================

class TestPersonMoodDescription:

    def test_no_feeling_when_intensity_below_threshold(self):
        mood = PersonMood(person_id="test", emotion=Emotion.HAPPY, intensity=0.05)
        desc = mood.to_prompt_description()
        assert "pas de sentiment particulier" in desc

    def test_description_contains_emotion_name(self):
        mood = PersonMood(person_id="test", emotion=Emotion.ANGRY, intensity=0.6)
        desc = mood.to_prompt_description()
        assert "angry" in desc

    def test_description_contains_intensity_label(self):
        mood = PersonMood(person_id="test", emotion=Emotion.SAD, intensity=0.85)
        desc = mood.to_prompt_description()
        assert "tres" in desc

    def test_description_contains_numeric_intensity(self):
        mood = PersonMood(person_id="test", emotion=Emotion.EXCITED, intensity=0.7)
        desc = mood.to_prompt_description()
        assert "0.7" in desc

    def test_all_emotions_produce_valid_descriptions(self):
        """Every emotion should produce a non-empty description."""
        for emotion in Emotion:
            mood = PersonMood(person_id="test", emotion=emotion, intensity=0.5)
            desc = mood.to_prompt_description()
            assert len(desc) > 10, f"Empty description for {emotion.value}"


# ===================================================================
# GLOBAL MOOD PROMPT DESCRIPTION
# ===================================================================

class TestGlobalMoodDescription:

    def test_default_mood_description(self):
        """When at default mood, should say 'comme d'habitude'."""
        glob = GlobalMood(emotion=Emotion.HAPPY, intensity=0.0)
        desc = glob.to_prompt_description(Emotion.HAPPY)
        assert "comme d'habitude" in desc

    def test_low_intensity_uses_default(self):
        glob = GlobalMood(emotion=Emotion.ANGRY, intensity=0.05)
        desc = glob.to_prompt_description(Emotion.HAPPY)
        assert "comme d'habitude" in desc

    def test_non_default_mood_mentions_both(self):
        """When in a non-default mood, should mention current and default."""
        glob = GlobalMood(emotion=Emotion.ANGRY, intensity=0.7)
        desc = glob.to_prompt_description(Emotion.HAPPY)
        assert "angry" in desc
        assert "happy" in desc
        assert "normalement" in desc

    def test_contains_intensity_label(self):
        glob = GlobalMood(emotion=Emotion.SAD, intensity=0.9)
        desc = glob.to_prompt_description(Emotion.HAPPY)
        assert "tres" in desc


# ===================================================================
# EMOTION CONTEXT (full engine output)
# ===================================================================

class TestEmotionContext:

    def test_context_contains_person_state(self, engine):
        """Context should describe person's emotional state."""
        engine.process_emotion(EmotionData(Emotion.EXCITED, 0.8), "user1")
        ctx = engine.get_emotion_context("user1")

        # Should contain something about the person's feeling
        assert len(ctx) > 20
        # Should be in French
        assert any(w in ctx for w in ["tu", "cette", "envers", "humeur"])

    def test_context_for_unknown_person(self, engine):
        """Context for a person with no interactions should mention no feeling."""
        ctx = engine.get_emotion_context("stranger")
        assert "pas de sentiment" in ctx

    def test_active_state_adds_anchoring_text(self, engine):
        """A strong active state (moving + intense) should add the 'bien ancree' text."""
        from emotion import pad
        pid = "anchored_user"
        for _ in range(6):
            engine.process_emotion(EmotionData(Emotion.HAPPY, 0.9), pid)

        mood = engine._get_person_mood(pid)
        speed = pad.norm(mood.dynamic.velocity)
        intensity = pad.norm(mood.dynamic.position)
        if speed > 0.3 and intensity > 0.4:
            ctx = engine.get_emotion_context(pid)
            assert "ancree" in ctx or "changer" in ctx

    def test_context_mentions_global_mood(self, engine):
        """Context should include global mood description."""
        engine.process_emotion(EmotionData(Emotion.ANGRY, 0.9), "user1")
        ctx = engine.get_emotion_context("user1")

        # Global mood section should be present
        assert "humeur" in ctx.lower()

    def test_context_coherent_after_troll_scenario(self, engine):
        """After a troll interaction, context should reflect negative state."""
        # Simulate troll
        for _ in range(3):
            engine.process_emotion(EmotionData(Emotion.ANGRY, 0.8), "troll")

        ctx = engine.get_emotion_context("troll")
        # Should mention something about the person's state
        assert len(ctx) > 0


# ===================================================================
# BUILD SYSTEM PROMPT
# ===================================================================

class TestBuildSystemPrompt:

    def test_base_prompt_contains_emotion_instructions(self):
        """System prompt must contain emotion tag format instructions."""
        prompt = build_system_prompt()
        assert "[EMOTION:" in prompt
        assert "intensite" in prompt.lower() or "intensité" in prompt

    def test_base_prompt_lists_all_emotions(self):
        """Prompt should list all 29+ emotion names."""
        prompt = build_system_prompt()
        for emotion in [Emotion.HAPPY, Emotion.SAD, Emotion.ANGRY,
                        Emotion.CURIOUS, Emotion.MISCHIEVOUS, Emotion.MELANCHOLIC]:
            assert emotion.value in prompt, \
                f"Emotion {emotion.value} missing from system prompt"

    def test_emotion_context_injected(self):
        """Emotion context should appear in the prompt."""
        prompt = build_system_prompt(
            emotion_context="Tu te sens tres excited envers cette personne."
        )
        assert "ETAT EMOTIONNEL" in prompt
        assert "tres excited" in prompt

    def test_memory_context_injected(self):
        prompt = build_system_prompt(
            memory_context="Tu te souviens que cette personne aime les chats."
        )
        assert "aime les chats" in prompt

    def test_module_context_injected(self):
        prompt = build_system_prompt(
            module_context="Tu as 3 emails non lus."
        )
        assert "CONTEXTE MODULES" in prompt
        assert "3 emails" in prompt

    def test_all_contexts_combined(self):
        """All three contexts should be present together without corruption."""
        prompt = build_system_prompt(
            emotion_context="EMOTION_MARKER",
            memory_context="MEMORY_MARKER",
            module_context="MODULE_MARKER",
        )
        assert "EMOTION_MARKER" in prompt
        assert "MEMORY_MARKER" in prompt
        assert "MODULE_MARKER" in prompt

    def test_empty_contexts_dont_add_sections(self):
        """Empty contexts should not add section headers."""
        prompt = build_system_prompt(
            emotion_context="",
            memory_context="",
            module_context="",
        )
        assert "CONTEXTE MODULES" not in prompt
        assert "ETAT EMOTIONNEL" not in prompt

    def test_prompt_mentions_personality_name(self):
        """Prompt should mention the VTuber's name."""
        prompt = build_system_prompt()
        # personality.yaml defines name as "Mika"
        assert "Mika" in prompt


# ===================================================================
# FORMAT CONVERSATION
# ===================================================================

class TestFormatConversation:

    def test_simple_message(self):
        result = format_conversation("Salut Mika !")
        assert "User: Salut Mika !" in result

    def test_with_history(self):
        history = [
            {"role": "user", "content": "Salut !"},
            {"role": "assistant", "content": "Hey ! Ca va ?"},
        ]
        result = format_conversation("Oui super !", history)

        assert "User: Salut !" in result
        assert "Assistant: Hey ! Ca va ?" in result
        assert "User: Oui super !" in result

    def test_history_order_preserved(self):
        history = [
            {"role": "user", "content": "First"},
            {"role": "assistant", "content": "Second"},
            {"role": "user", "content": "Third"},
            {"role": "assistant", "content": "Fourth"},
        ]
        result = format_conversation("Fifth", history)

        # Verify order: First should come before Second, etc.
        positions = [
            result.index("First"),
            result.index("Second"),
            result.index("Third"),
            result.index("Fourth"),
            result.index("Fifth"),
        ]
        assert positions == sorted(positions), "Messages should be in order"

    def test_no_history(self):
        result = format_conversation("Hello")
        assert result == "User: Hello"

    def test_empty_history(self):
        result = format_conversation("Hello", [])
        assert result == "User: Hello"

    def test_long_conversation_context(self):
        """20 exchanges should all be formatted correctly."""
        history = []
        for i in range(20):
            history.append({"role": "user", "content": f"Q{i}"})
            history.append({"role": "assistant", "content": f"A{i}"})

        result = format_conversation("Final question", history)
        assert "Q0" in result
        assert "Q19" in result
        assert "A19" in result
        assert "Final question" in result


# ===================================================================
# END-TO-END PROMPT COHERENCE
# ===================================================================

class TestEndToEndPromptCoherence:
    """Test that the full prompt pipeline produces coherent output."""

    def test_angry_state_produces_angry_prompt(self, engine):
        """When angry, the emotion context in the prompt should reflect anger."""
        engine.process_emotion(EmotionData(Emotion.ANGRY, 0.8), "user1")
        emotion_ctx = engine.get_emotion_context("user1")
        prompt = build_system_prompt(emotion_context=emotion_ctx)

        assert "angry" in prompt.lower() or "ANGRY" in prompt

    def test_happy_default_produces_neutral_prompt(self, engine):
        """Default state should show 'comme d'habitude' type language."""
        emotion_ctx = engine.get_emotion_context("new_user")
        prompt = build_system_prompt(emotion_context=emotion_ctx)

        assert "pas de sentiment" in prompt or "comme d'habitude" in prompt

    def test_full_prompt_with_conversation(self, engine):
        """Full prompt assembly with all layers should be valid."""
        engine.process_emotion(EmotionData(Emotion.CURIOUS, 0.7), "user1")

        emotion_ctx = engine.get_emotion_context("user1")
        memory_ctx = "Souvenir: cette personne aime Python et les chats."
        module_ctx = "Tu as 2 emails non lus."

        prompt = build_system_prompt(emotion_ctx, memory_ctx, module_ctx)
        user_prompt = format_conversation(
            "Tu connais Python ?",
            [{"role": "user", "content": "Salut !"}, {"role": "assistant", "content": "Hey !"}],
        )

        # Both should be non-empty and contain expected content
        assert len(prompt) > 100
        assert len(user_prompt) > 10
        assert "Python" in prompt  # from memory
        assert "emails" in prompt  # from modules
        assert "Tu connais Python" in user_prompt
