"""Plafonds des blocs de prompt sans borne naturelle.

Rien en aval du ``gather_context`` ne mesure ni ne tronque (aucun tokenizer
dans le processus), donc chaque bloc doit porter sa propre limite. Ces tests
pinnent les bornes ajoutées aux blocs qui n'en avaient aucune : le
self-narrative, le contexte modules agrégé, les champs libres d'un projet et
le nombre de revendications d'identité affichées.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from old.backend.identity.trust import ChannelTrust
from old.backend.pipeline.context_blocks import (
    _IDENTITY_CLAIMS_MAX,
    _MODULE_CONTEXT_MAX_CHARS,
    _PROJECT_LIST_ITEMS_MAX,
    _PROJECT_TEXT_MAX_CHARS,
    _SELF_CONCEPT_MAX_CHARS,
    _clip,
    _fetch_self_concept,
    _format_identity_block,
    _format_project_block,
)


class TestClip:

    def test_short_text_is_untouched(self):
        assert _clip("court", 100) == "court"

    def test_long_text_is_capped_with_a_visible_marker(self):
        out = _clip("x" * 500, 100)
        assert len(out) <= 100
        assert out.endswith("…")


class TestProjectBlockCaps:

    def _data(self, **overrides):
        data = {
            "title": "Projet",
            "description": "d" * 2000,
            "tone_directive": "t" * 2000,
            "instructions": [f"consigne {i} " + "y" * 500 for i in range(20)],
            "out_of_scope": [f"hors {i}" for i in range(20)],
            "emotion_policy": "off",
        }
        data.update(overrides)
        return data

    def test_free_text_fields_are_clipped(self):
        block = _format_project_block(self._data())
        for line in block.splitlines():
            assert len(line) <= 2 * _PROJECT_TEXT_MAX_CHARS + 40

    def test_list_fields_are_count_capped(self):
        block = _format_project_block(self._data())
        assert block.count("consigne") == _PROJECT_LIST_ITEMS_MAX
        assert block.count("hors ") == _PROJECT_LIST_ITEMS_MAX

    def test_nominal_project_is_untouched(self):
        data = self._data(
            description="Un cadre court.",
            tone_directive="Neutre.",
            instructions=["Faire A", "Faire B"],
            out_of_scope=["C"],
        )
        block = _format_project_block(data)
        assert "Faire A" in block and "Faire B" in block and "…" not in block


class TestIdentityClaimsCap:

    def _ctx(self, claim_count: int):
        return SimpleNamespace(
            is_internal=False,
            trust=ChannelTrust.PUBLIC,
            description="Quelqu'un en face.",
            may_disclose=False,
            is_identified=False,
            pending_claims=[
                {"id": i, "name": f"Nom{i}", "evidence": "je suis lui"}
                for i in range(claim_count)
            ],
        )

    def test_claim_lines_are_capped_and_the_rest_is_counted(self):
        block = _format_identity_block(self._ctx(_IDENTITY_CLAIMS_MAX + 3))
        assert block.count("Revendication #") == _IDENTITY_CLAIMS_MAX
        assert "+3 autre(s)" in block

    def test_few_claims_show_no_counter(self):
        block = _format_identity_block(self._ctx(2))
        assert block.count("Revendication #") == 2
        assert "autre(s) revendication" not in block


class TestSelfConceptCap:

    async def test_long_narrative_is_clipped(self):
        narrative = SimpleNamespace(content="n" * (4 * _SELF_CONCEPT_MAX_CHARS))
        with patch("memory.read.latest_self_narrative", AsyncMock(return_value=narrative)):
            out = await _fetch_self_concept()
        assert len(out) <= _SELF_CONCEPT_MAX_CHARS
        assert out.endswith("…")

    async def test_short_narrative_is_untouched(self):
        narrative = SimpleNamespace(content="Je suis quelqu'un qui apprend.")
        with patch("memory.read.latest_self_narrative", AsyncMock(return_value=narrative)):
            out = await _fetch_self_concept()
        assert out == "Je suis quelqu'un qui apprend."


class TestModuleContextCap:

    def test_constant_is_generous_but_finite(self):
        # Garde-fou de cohérence : la borne existe et reste au-dessus de ce
        # que les modules embarqués produisent en usage nominal.
        assert 500 < _MODULE_CONTEXT_MAX_CHARS < 10_000
