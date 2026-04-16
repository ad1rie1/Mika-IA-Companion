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

from emotion import pad
from emotion.types import Emotion, EmotionData
from emotion.state import PersonMood, GlobalMood, Temperament, _intensity_label
from emotion.engine import EmotionEngine
from pipeline.prompt import build_system_prompt, format_conversation
from tests.conftest import TEMPERAMENT_DEFAULT


def _make_person(emotion: Emotion, intensity: float) -> PersonMood:
    m = PersonMood(person_id="test")
    m.dynamic.position = pad.label_to_pad(emotion, intensity)
    return m


def _make_global(emotion: Emotion, intensity: float) -> GlobalMood:
    g = GlobalMood()
    g.dynamic.position = pad.label_to_pad(emotion, intensity)
    return g


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
        mood = _make_person(Emotion.HAPPY, 0.05)
        desc = mood.to_prompt_description()
        assert "pas de sentiment particulier" in desc

    def test_description_contains_emotion_name(self):
        mood = _make_person(Emotion.ANGRY, 0.9)
        desc = mood.to_prompt_description()
        assert "angry" in desc

    def test_description_contains_intensity_label(self):
        mood = _make_person(Emotion.SAD, 1.0)
        desc = mood.to_prompt_description()
        # For strong SAD, intensity label should be "tres" or "assez"
        assert any(w in desc for w in ["tres", "assez"])

    def test_description_contains_numeric_intensity(self):
        mood = _make_person(Emotion.EXCITED, 0.9)
        desc = mood.to_prompt_description()
        # Should include a numeric intensity formatted to 1 decimal
        assert any(f"0.{n}" in desc for n in range(1, 10))

    def test_all_emotions_produce_valid_descriptions(self):
        """Every emotion should produce a non-empty description."""
        for emotion in Emotion:
            if emotion == Emotion.NEUTRAL:
                continue  # neutral at intensity 0.8 is still origin
            mood = _make_person(emotion, 0.8)
            desc = mood.to_prompt_description()
            assert len(desc) > 10, f"Empty description for {emotion.value}"


# ===================================================================
# GLOBAL MOOD PROMPT DESCRIPTION
# ===================================================================

class TestGlobalMoodDescription:

    def test_default_mood_description(self):
        """When at default mood, should say 'comme d'habitude'."""
        glob = GlobalMood()  # at origin
        desc = glob.to_prompt_description(Emotion.HAPPY)
        assert "comme d'habitude" in desc

    def test_low_intensity_uses_default(self):
        glob = _make_global(Emotion.ANGRY, 0.05)
        desc = glob.to_prompt_description(Emotion.HAPPY)
        assert "comme d'habitude" in desc

    def test_non_default_mood_mentions_both(self):
        """When in a non-default mood, should mention current and default."""
        glob = _make_global(Emotion.ANGRY, 0.9)
        desc = glob.to_prompt_description(Emotion.HAPPY)
        assert "angry" in desc
        assert "happy" in desc
        assert "normalement" in desc

    def test_contains_intensity_label(self):
        glob = _make_global(Emotion.SAD, 1.0)
        desc = glob.to_prompt_description(Emotion.HAPPY)
        assert any(w in desc for w in ["tres", "assez"])


# ===================================================================
# EMOTION CONTEXT (full engine output)
# ===================================================================

class TestEmotionContext:
    """Global mood context covers Mika's standalone affective state only.

    Per-person affect was moved into `get_person_affect_context()` so the
    two concerns — "how Mika feels" vs "how Mika feels about X" — don't
    mix in the same prompt block.
    """

    def test_global_context_contains_humeur(self, engine):
        engine.process_emotion(EmotionData(Emotion.EXCITED, 0.8), "user1")
        ctx = engine.get_global_mood_context()
        assert "humeur" in ctx.lower()

    def test_global_context_default_mood_without_interaction(self, engine):
        """No interaction → description still says 'comme d'habitude'."""
        ctx = engine.get_global_mood_context()
        assert "habitude" in ctx.lower() or "humeur" in ctx.lower()

    def test_person_affect_contains_person_state(self, engine):
        engine.process_emotion(EmotionData(Emotion.EXCITED, 0.8), "user1")
        ctx = engine.get_person_affect_context("user1")
        assert len(ctx) > 0
        assert any(w in ctx for w in ["tu", "cette", "envers"])

    def test_person_affect_for_unknown_person_is_empty(self, engine):
        """Unknown person → empty string (no boilerplate)."""
        ctx = engine.get_person_affect_context("stranger")
        assert ctx == ""

    def test_active_state_adds_anchoring_text(self, engine):
        """Strong active person state adds the 'bien ancree' marker."""
        from emotion import pad
        pid = "anchored_user"
        for _ in range(6):
            engine.process_emotion(EmotionData(Emotion.HAPPY, 0.9), pid)

        mood = engine._get_person_mood(pid)
        speed = pad.norm(mood.dynamic.velocity)
        intensity = pad.norm(mood.dynamic.position)
        if speed > 0.3 and intensity > 0.4:
            ctx = engine.get_person_affect_context(pid)
            assert "ancree" in ctx or "estomper" in ctx

    def test_person_affect_does_not_leak_into_global(self, engine):
        """Regression guard: per-person impulse must not alter the global block."""
        ctx_before = engine.get_global_mood_context()
        engine.process_emotion(EmotionData(Emotion.ANGRY, 0.9), "someone")
        # Global mood can shift via bleed, but the block should still be
        # a *global* sentence — never mentioning "envers cette personne".
        ctx_after = engine.get_global_mood_context()
        for ctx in (ctx_before, ctx_after):
            assert "envers cette personne" not in ctx.lower()

    def test_troll_reflected_in_person_affect(self, engine):
        for _ in range(3):
            engine.process_emotion(EmotionData(Emotion.ANGRY, 0.8), "troll")
        ctx = engine.get_person_affect_context("troll")
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

    def test_angry_state_reflects_in_full_prompt(self, engine):
        """Anger should surface somewhere in the prompt — either in the
        global block (via bleed) or in the person-affect block."""
        engine.process_emotion(EmotionData(Emotion.ANGRY, 0.8), "user1")
        emotion_ctx = engine.get_global_mood_context()
        person_ctx = engine.get_person_affect_context("user1")
        prompt = build_system_prompt(
            emotion_context=emotion_ctx, person_context=person_ctx,
        )
        assert "angry" in prompt.lower()

    def test_default_state_shows_baseline_language(self, engine):
        """Default state → global block mentions 'comme d'habitude' language.
        Affect block is empty for a new user (no filler)."""
        emotion_ctx = engine.get_global_mood_context()
        person_ctx = engine.get_person_affect_context("new_user")
        assert person_ctx == ""
        prompt = build_system_prompt(
            emotion_context=emotion_ctx, person_context=person_ctx,
        )
        assert "habitude" in prompt or "humeur" in prompt

    def test_full_prompt_with_conversation(self, engine):
        """Full prompt assembly with all layers should be valid."""
        engine.process_emotion(EmotionData(Emotion.CURIOUS, 0.7), "user1")

        emotion_ctx = engine.get_global_mood_context()
        person_ctx = engine.get_person_affect_context("user1")
        memory_ctx = "Souvenir: cette personne aime Python et les chats."
        module_ctx = "Tu as 2 emails non lus."

        prompt = build_system_prompt(
            emotion_context=emotion_ctx,
            memory_context=memory_ctx,
            module_context=module_ctx,
            person_context=person_ctx,
        )
        user_prompt = format_conversation(
            "Tu connais Python ?",
            [{"role": "user", "content": "Salut !"}, {"role": "assistant", "content": "Hey !"}],
        )

        assert len(prompt) > 100
        assert len(user_prompt) > 10
        assert "Python" in prompt  # from memory
        assert "emails" in prompt  # from modules
        assert "Tu connais Python" in user_prompt
