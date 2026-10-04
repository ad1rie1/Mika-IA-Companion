"""Tests for MemoryExtractor — analyze_messages, validity check, JSON parsing."""

import json
import pytest
from unittest.mock import AsyncMock, patch


def _make_extractor():
    from old.backend.memory.extraction.extractor import MemoryExtractor
    e = MemoryExtractor()
    e._system_prompt = "System: extrait les mémoires."
    return e


def _palette_du_prompt() -> set[str]:
    """Les emotions que le prompt d'extraction autorise, telles qu'il les dit."""
    from old.backend.memory.extraction.extractor import EXTRACTION_PROMPT_TEMPLATE, EXTRACTION_EMOTIONS

    rendu = EXTRACTION_PROMPT_TEMPLATE.format(
        name="Mika", description="d", tone="t", traits="a",
        emotions=EXTRACTION_EMOTIONS,
    )
    ligne = next(l for l in rendu.splitlines() if "Emotion parmi:" in l)
    return {mot.strip() for mot in ligne.split("Emotion parmi:", 1)[1].split(",")}


# ===================================================================
# Palette émotionnelle imposée au modèle
# ===================================================================

class TestPaletteEmotionnelle:

    def test_la_palette_est_derivee_de_emotion_types(self):
        from old.backend.emotion.types import Emotion

        assert _palette_du_prompt() == {e.value for e in Emotion}

    def test_les_cauchemars_de_peur_deviennent_possibles(self):
        """Le classifieur de rêves (memory/sleep.py) attend scared/anxious ;
        aucun souvenir ne pouvait les porter, et DIGESTION_DRIFT déclarait des
        transitions pour des émotions inatteignables."""
        palette = _palette_du_prompt()
        negatives = {"sad", "angry", "scared", "disgusted", "frustrated",
                     "lonely", "anxious", "jealous", "embarrassed"}
        assert {"scared", "anxious"} <= palette
        assert {"scared", "anxious"} <= palette & negatives


# ===================================================================
# analyze_messages
# ===================================================================

class TestAnalyzeMessages:

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self):
        e = _make_extractor()
        result = await e.analyze_messages([])
        assert result == []

    @pytest.mark.asyncio
    async def test_valid_extraction_returned(self):
        e = _make_extractor()
        response = json.dumps({"extractions": [
            {"type": "souvenir", "store": True, "content": "On a joué à Zelda", "emotion": "happy", "themes": [], "entities": []},
            {"type": "connaissance", "store": True, "content": "Thomas aime les chats", "themes": [], "entities": []},
        ]})
        with patch.object(e, "_query_model", new_callable=AsyncMock, return_value=response):
            result = await e.analyze_messages([{"role": "user", "content": "test"}])
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_store_false_filtered_out(self):
        e = _make_extractor()
        response = json.dumps({"extractions": [
            {"type": "souvenir", "store": False, "content": "Banal"},
            {"type": "connaissance", "store": True, "content": "Important", "themes": [], "entities": []},
        ]})
        with patch.object(e, "_query_model", new_callable=AsyncMock, return_value=response):
            result = await e.analyze_messages([{"role": "user", "content": "test"}])
        assert len(result) == 1
        assert result[0]["content"] == "Important"

    # Le pin change : `[]` ne peut plus vouloir dire deux choses. Un échec
    # transport rend `None` (le consolidateur laisse alors sa fenêtre en
    # attente) ; `[]` reste réservé à « rien à retenir ».
    @pytest.mark.asyncio
    async def test_ai_error_returns_none(self):
        e = _make_extractor()
        with patch.object(e, "_query_model", new_callable=AsyncMock, side_effect=Exception("AI down")):
            result = await e.analyze_messages([{"role": "user", "content": "test"}])
        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self):
        import asyncio
        e = _make_extractor()

        async def slow(*a, **kw):
            await asyncio.sleep(100)
            return "{}"

        with patch.object(e, "_query_model", side_effect=slow), \
             patch("memory.extraction.extractor._call_timeout", lambda: 0.01):
            result = await e.analyze_messages([{"role": "user", "content": "test"}])
        assert result is None

    @pytest.mark.asyncio
    async def test_role_non_mappe_rend_none(self):
        from old.backend.ai.router import UnconfiguredRoleError

        e = _make_extractor()
        with patch.object(e, "_query_model", new_callable=AsyncMock,
                          side_effect=UnconfiguredRoleError("aucun modèle")):
            result = await e.analyze_messages([{"role": "user", "content": "test"}])
        assert result is None

    @pytest.mark.asyncio
    async def test_json_illisible_vaut_rien_a_extraire(self):
        """Un modèle qui rend de la prose sur UNE tranche empoisonnerait le
        checkpoint pour toujours s'il valait « aucune réponse »."""
        e = _make_extractor()
        with patch.object(e, "_query_model", new_callable=AsyncMock,
                          return_value="Bien sûr ! Voici mon analyse."):
            result = await e.analyze_messages([{"role": "user", "content": "test"}])
        assert result == []

    @pytest.mark.asyncio
    async def test_reponse_vide_rend_none(self):
        e = _make_extractor()
        with patch("ai.router.ai_router.complete", new_callable=AsyncMock, return_value="   "):
            result = await e.analyze_messages([{"role": "user", "content": "test"}])
        assert result is None

    def test_la_borne_ne_descend_jamais_sous_celle_du_routeur(self):
        """Un second plafond plus serré que `ai.call_timeout_seconds` ferait
        expirer chaque extraction sur un backend local — et depuis que le
        checkpoint n'avance plus sur échec, ce serait définitif."""
        from old.backend.memory.extraction.extractor import EXTRACTION_TIMEOUT, _call_timeout

        with patch("configs.service.config_service.get", return_value=120.0):
            assert _call_timeout() == 120.0
        with patch("configs.service.config_service.get", return_value=10.0):
            assert _call_timeout() == EXTRACTION_TIMEOUT
        with patch("configs.service.config_service.get",
                   side_effect=RuntimeError("config illisible")):
            assert _call_timeout() == EXTRACTION_TIMEOUT


# ===================================================================
# _query_model_json
# ===================================================================

class TestQueryModelJson:

    @pytest.mark.asyncio
    async def test_valid_json_parsed(self):
        e = _make_extractor()
        with patch.object(e, "_query_model", new_callable=AsyncMock, return_value='{"extractions": []}'):
            result = await e._query_model_json("test")
        assert result == {"extractions": []}

    @pytest.mark.asyncio
    async def test_markdown_json_stripped(self):
        e = _make_extractor()
        with patch.object(e, "_query_model", new_callable=AsyncMock, return_value='```json\n{"extractions": []}\n```'):
            result = await e._query_model_json("test")
        assert result == {"extractions": []}

    @pytest.mark.asyncio
    async def test_invalid_json_returns_none(self):
        e = _make_extractor()
        with patch.object(e, "_query_model", new_callable=AsyncMock, return_value="not json"):
            result = await e._query_model_json("test")
        assert result is None

    @pytest.mark.asyncio
    async def test_none_response_returns_none(self):
        e = _make_extractor()
        with patch.object(e, "_query_model", new_callable=AsyncMock, return_value=None):
            result = await e._query_model_json("test")
        assert result is None


# ===================================================================
# check_connaissance_validity
# ===================================================================

class TestCheckConnaissanceValidity:

    @pytest.mark.asyncio
    async def test_still_valid(self):
        e = _make_extractor()
        r = json.dumps({"still_valid": True, "new_confidence": 0.9, "reason": "ok"})
        with patch.object(e, "_query_model", new_callable=AsyncMock, return_value=r):
            valid, conf = await e.check_connaissance_validity("fact", "context")
        assert valid is True
        assert conf == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_invalidated(self):
        e = _make_extractor()
        r = json.dumps({"still_valid": False, "new_confidence": 0.1, "reason": "contradiction"})
        with patch.object(e, "_query_model", new_callable=AsyncMock, return_value=r):
            valid, conf = await e.check_connaissance_validity("fact", "context")
        assert valid is False
        assert conf == pytest.approx(0.1)

    @pytest.mark.asyncio
    async def test_error_fallback_conservative(self):
        e = _make_extractor()
        with patch.object(e, "_query_model", new_callable=AsyncMock, side_effect=Exception("err")):
            valid, conf = await e.check_connaissance_validity("fact", "context")
        assert valid is True
        assert conf is None

    @pytest.mark.asyncio
    async def test_le_controle_de_validite_compte_ses_pannes(self):
        """Le repli conservateur reste le même ; ce qui manquait, c'est la
        ligne au registre — seule la panne *facturée et répondue* comptait."""
        import asyncio

        from old.backend.ai.router import UnconfiguredRoleError
        from old.backend.utils.degradation import degradations

        async def slow(*a, **kw):
            await asyncio.sleep(100)
            return "{}"

        cas = [
            (UnconfiguredRoleError("pas de modèle"),
             "extraction: role IA non mappe pour le controle de validite"),
            (Exception("provider mort"),
             "extraction: controle de validite en echec"),
        ]
        for erreur, libelle in cas:
            degradations.reset()
            e = _make_extractor()
            with patch.object(e, "_query_model", new_callable=AsyncMock, side_effect=erreur):
                valid, conf = await e.check_connaissance_validity("fait", "contexte")
            assert (valid, conf) == (True, None)
            assert degradations.count_for(libelle) == 1

        degradations.reset()
        e = _make_extractor()
        with patch.object(e, "_query_model", side_effect=slow), \
             patch("memory.extraction.extractor._call_timeout", lambda: 0.01):
            valid, conf = await e.check_connaissance_validity("fait", "contexte")
        assert (valid, conf) == (True, None)
        assert degradations.count_for(
            "extraction: delai depasse sur controle de validite") == 1

    @pytest.mark.asyncio
    async def test_confidence_clamped(self):
        e = _make_extractor()
        r = json.dumps({"still_valid": True, "new_confidence": 2.5, "reason": "ok"})
        with patch.object(e, "_query_model", new_callable=AsyncMock, return_value=r):
            _, conf = await e.check_connaissance_validity("fact", "context")
        assert conf <= 1.0
