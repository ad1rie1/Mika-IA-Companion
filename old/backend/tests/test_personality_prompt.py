"""
Tests for personality loading and system prompt generation.

Verifies that personality.yaml loads correctly and generates
a well-formed system prompt for the AI.
"""

import pytest
from pathlib import Path

from old.backend.config.personality import Personality, personality
from old.backend.emotion.types import Emotion
from old.backend.emotion.state import Temperament


# ===================================================================
# PERSONALITY LOADING
# ===================================================================

class TestPersonalityLoading:

    def test_personality_singleton_exists(self):
        """The global personality singleton should be initialized."""
        assert personality is not None
        assert isinstance(personality, Personality)

    def test_name_loaded(self):
        assert personality.name == "Mika"

    def test_description_not_empty(self):
        assert len(personality.description) > 10

    def test_language_is_french(self):
        assert personality.language == "fr"

    def test_greeting_not_empty(self):
        assert len(personality.greeting) > 5

    def test_tone_has_default(self):
        assert "default" in personality.tone
        assert len(personality.tone["default"]) > 10

    def test_tone_has_variants(self):
        tone = personality.tone
        assert "when_excited" in tone
        assert "when_teasing" in tone

    def test_traits_loaded(self):
        assert isinstance(personality.traits, list)
        assert len(personality.traits) > 0

    def test_interests_loaded(self):
        assert isinstance(personality.interests, list)
        assert len(personality.interests) > 0

    def test_speech_patterns_loaded(self):
        assert isinstance(personality.speech_patterns, list)
        assert len(personality.speech_patterns) > 0

    def test_mood_greetings_loaded(self):
        greetings = personality.mood_greetings
        assert isinstance(greetings, dict)


# ===================================================================
# TEMPERAMENT
# ===================================================================

class TestTemperamentFromPersonality:

    def test_temperament_is_valid(self):
        temp = personality.temperament
        assert isinstance(temp, Temperament)

    def test_volatility_in_range(self):
        temp = personality.temperament
        assert 0.0 <= temp.volatility <= 1.0

    def test_intensity_base_in_range(self):
        temp = personality.temperament
        assert 0.0 <= temp.intensity_base <= 1.0

    def test_recovery_speed_in_range(self):
        temp = personality.temperament
        assert 0.0 <= temp.recovery_speed <= 1.0

    def test_global_bleed_in_range(self):
        temp = personality.temperament
        assert 0.0 <= temp.global_bleed <= 1.0

    def test_default_mood_is_valid_emotion(self):
        temp = personality.temperament
        assert isinstance(temp.default_mood, Emotion)

    def test_mika_defaults(self):
        """Mika's temperament should match personality.yaml values."""
        temp = personality.temperament
        assert temp.volatility == 0.7
        assert temp.intensity_base == 0.6
        assert temp.recovery_speed == 0.5
        assert temp.default_mood == Emotion.HAPPY
        assert temp.global_bleed == 0.3


# ===================================================================
# SYSTEM PROMPT GENERATION
# ===================================================================

class TestSystemPromptGeneration:

    def test_prompt_contains_name(self):
        prompt = personality.to_system_prompt()
        assert "Mika" in prompt

    def test_prompt_contains_description(self):
        prompt = personality.to_system_prompt()
        assert personality.description[:30] in prompt

    def test_prompt_lists_all_emotions(self):
        """All 29 emotions should be listed in the prompt."""
        prompt = personality.to_system_prompt()
        for emotion in Emotion:
            assert emotion.value in prompt, \
                f"Emotion {emotion.value} missing from system prompt"

    def test_prompt_contains_emotion_format_instruction(self):
        """Prompt must instruct the AI to use [EMOTION:name:intensity] format."""
        prompt = personality.to_system_prompt()
        assert "[EMOTION:" in prompt
        assert "intensité" in prompt or "intensite" in prompt

    def test_prompt_contains_examples(self):
        """Prompt should contain example emotion tags."""
        prompt = personality.to_system_prompt()
        assert "[EMOTION:excited:0.8]" in prompt
        assert "[EMOTION:thinking:0.4]" in prompt
        assert "[EMOTION:mischievous:0.6]" in prompt

    def test_prompt_mentions_language(self):
        prompt = personality.to_system_prompt()
        assert "fr" in prompt

    def test_prompt_contains_tone(self):
        prompt = personality.to_system_prompt()
        assert personality.tone["default"][:20] in prompt

    def test_prompt_contains_traits(self):
        prompt = personality.to_system_prompt()
        if personality.traits:
            assert personality.traits[0] in prompt

    def test_prompt_contains_speech_patterns(self):
        prompt = personality.to_system_prompt()
        if personality.speech_patterns:
            assert personality.speech_patterns[0] in prompt

    def test_prompt_is_reasonable_length(self):
        """System prompt should not be excessively long or short."""
        prompt = personality.to_system_prompt()
        assert len(prompt) > 200, "Prompt too short"
        assert len(prompt) < 10000, "Prompt too long"

    def test_prompt_contains_intensity_scale_guide(self):
        """Prompt should explain what intensity values mean."""
        prompt = personality.to_system_prompt()
        assert "0.3" in prompt  # léger
        assert "0.5" in prompt  # modéré
        assert "0.7" in prompt  # fort
        assert "0.9" in prompt  # très intense


# ===================================================================
# PERSONALITY WITH MISSING DATA
# ===================================================================

class TestPersonalityDefaults:
    """Le personnage se lit au registre — plus aucun fichier derrière.

    Ces tests portaient sur le chargeur YAML (fichier absent, vide, minimal,
    malformé). Le fichier n'existe plus : ces cas n'ont plus de sens, mais la
    propriété qu'ils protégeaient, elle, en a toujours une — *une valeur
    illisible ne doit jamais produire un prompt cassé*. Elle se vérifie
    maintenant sur les deux façons dont une lecture peut mal tourner : une
    valeur effacée dans le tableau de bord, et un registre hors d'atteinte.
    """

    def test_les_defauts_declares_donnent_mika(self):
        """Sans aucun réglage enregistré, on obtient le personnage livré."""
        p = Personality()
        assert p.name == "Mika"
        assert p.language == "fr"
        assert p.greeting.startswith("Hey !")
        assert p.traits, "les traits déclarés au schéma doivent remonter"
        assert isinstance(p.temperament, Temperament)

    @pytest.mark.django_db
    def test_un_nom_regle_remplace_le_defaut(self):
        """Écrire dans la configuration change le prompt du tour suivant."""
        from old.backend.configs.service import config_service

        config_service.set("personality.name", "TestBot", actor="test")
        try:
            p = Personality()
            assert p.name == "TestBot"
            assert "TestBot" in p.to_system_prompt()
        finally:
            config_service.unset("personality.name", actor="test")
            config_service.invalidate_cache("personality.name")

    @pytest.mark.django_db
    def test_un_nom_efface_reste_dicible(self):
        """Un nom vidé ne doit pas ouvrir le prompt sur « Tu es , … ».

        Le formulaire permet d'effacer un champ texte, et le prompt met le nom
        juste après « Tu es ». Le repli n'est pas une préférence, c'est ce qui
        reste prononçable.
        """
        from old.backend.configs.service import config_service

        config_service.set("personality.name", "", actor="test")
        try:
            assert Personality().name == "Mika"
        finally:
            config_service.unset("personality.name", actor="test")
            config_service.invalidate_cache("personality.name")

    def test_un_registre_injoignable_ne_casse_pas_le_prompt(self, monkeypatch):
        """Base illisible : on sert les replis, on ne lève pas.

        C'est le cas qui remplace « fichier absent ». Il arrive pour de vrai —
        un import avant ``migrate``, une base verrouillée — et la personnalité
        est la première couche du prompt : elle échoue avant tout le reste.
        """
        from old.backend.configs.service import config_service

        def _explose(*a, **kw):
            raise RuntimeError("base injoignable")

        monkeypatch.setattr(config_service, "get", _explose)

        p = Personality()
        assert p.name == "Mika"
        assert p.language == "fr"
        # Les listes retombent sur « rien à dire », pas sur une exception : le
        # prompt perd des sections, il reste bien formé.
        assert p.traits == []
        prompt = p.to_system_prompt()
        assert "Tu es Mika" in prompt
        assert "[EMOTION:" in prompt
