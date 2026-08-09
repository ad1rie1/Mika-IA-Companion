"""Passe de préparation — skip-gate, parse tolérant, fail-open, couture.

La propriété que tout le fichier défend : la passe est une amélioration,
jamais une dépendance. Quand elle ne tourne pas (gate, rôle non mappé,
timeout, JSON illisible), le tour est strictement identique à avant.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline.preparation import (
    NOTE_MAX_CHARS,
    PreparationPlan,
    Rappel,
    _parse_plan,
    execute_plan,
    prepare,
    should_prepare,
)


class TestSkipGate:

    def test_internal_person_never_prepares(self):
        assert should_prepare("une longue question sur le passé ?", "conscience_mika") is False

    def test_emoji_only_never_prepares(self):
        assert should_prepare("😂😂😂 !!!", "web_a") is False

    def test_small_talk_never_prepares(self):
        assert should_prepare("Coucou !", "web_a") is False
        assert should_prepare("ça va ?", "web_a") is False

    def test_short_without_question_mark_skips(self):
        assert should_prepare("cool merci bien", "web_a") is False

    def test_unmapped_role_disables_the_pass(self):
        """L'état par défaut d'une installation : aucun rôle preparation
        mappé → gate fermé, zéro coût."""
        long_msg = "tu te souviens de ce que je t'ai raconté sur le projet fusée ?"
        assert should_prepare(long_msg, "web_a") is False

    def test_mapped_role_and_real_question_opens_the_gate(self):
        with patch("ai.router.ai_router.resolve", return_value=("claude", "m", 0.7, "x")):
            assert should_prepare(
                "tu te souviens de ce que je t'ai dit sur Thomas ?", "web_a",
            ) is True

    def test_short_question_is_rescued_by_the_question_mark(self):
        with patch("ai.router.ai_router.resolve", return_value=("claude", "m", 0.7, "x")):
            assert should_prepare("et Alice ?", "web_a") is True


class TestParsePlan:

    def test_clean_json(self):
        plan = _parse_plan(
            '{"rappels":[{"type":"souvenirs","query":"le chat"}],'
            '"note_de_focus":"elle reparle du chat"}', 3,
        )
        assert plan.rappels[0].type == "souvenirs"
        assert plan.note_de_focus == "elle reparle du chat"

    def test_fenced_and_prose_wrapped_json(self):
        raw = 'Voici le plan :\n```json\n{"rappels":[],"note_de_focus":"ras"}\n```'
        plan = _parse_plan(raw, 3)
        assert plan is not None and plan.note_de_focus == "ras"

    def test_garbage_is_none(self):
        assert _parse_plan("désolé je ne peux pas", 3) is None
        assert _parse_plan("", 3) is None

    def test_unknown_types_are_dropped_and_count_is_capped(self):
        raw = (
            '{"rappels":['
            '{"type":"internet","query":"x"},'
            '{"type":"souvenirs","query":"a"},'
            '{"type":"connaissances","query":"b"},'
            '{"type":"echanges_passes","query":"c","person":"Thomas"},'
            '{"type":"souvenirs","query":"d"}'
            '],"note_de_focus":""}'
        )
        plan = _parse_plan(raw, 3)
        assert [r.type for r in plan.rappels] == [
            "souvenirs", "connaissances", "echanges_passes",
        ]
        assert plan.exchange_rappels[0].person == "Thomas"

    def test_note_is_clipped(self):
        plan = _parse_plan(
            '{"rappels":[],"note_de_focus":"' + "n" * 500 + '"}', 3,
        )
        assert len(plan.note_de_focus) == NOTE_MAX_CHARS

    def test_memory_queries_property_excludes_exchanges(self):
        plan = PreparationPlan(rappels=(
            Rappel("souvenirs", "a"),
            Rappel("echanges_passes", "b"),
        ))
        assert plan.memory_queries == ["a"]

    def test_charge_emotionnelle_parsed_and_clamped(self):
        assert _parse_plan(
            '{"rappels":[],"note_de_focus":"","charge_emotionnelle":0.8}', 3,
        ).charge_emotionnelle == pytest.approx(0.8)
        # bornée [0,1]
        assert _parse_plan(
            '{"rappels":[],"charge_emotionnelle":5}', 3,
        ).charge_emotionnelle == 1.0
        # illisible → 0.0 (tour ordinaire), jamais d'erreur
        assert _parse_plan(
            '{"rappels":[],"charge_emotionnelle":"beaucoup"}', 3,
        ).charge_emotionnelle == 0.0
        # absente → 0.0
        assert _parse_plan('{"rappels":[]}', 3).charge_emotionnelle == 0.0


class TestPrepare:

    async def test_router_failure_is_fail_open(self):
        with patch("ai.router.ai_router.complete",
                   AsyncMock(side_effect=RuntimeError("down"))):
            assert await prepare("msg", [], "web_a", 1.0) is None

    async def test_plan_round_trip(self):
        raw = '{"rappels":[{"type":"souvenirs","query":"vacances"}],"note_de_focus":"ok"}'
        with patch("ai.router.ai_router.complete", AsyncMock(return_value=raw)) as mock:
            plan = await prepare("dis", [{"role": "user", "content": "avant"}], "web_a", 1.0)
        assert plan.rappels[0].query == "vacances"
        # La deadline du plan est aussi le timeout de l'appel routé.
        assert mock.call_args.kwargs["timeout"] == 1.0
        assert "avant" in mock.call_args.kwargs["user_prompt"]


class TestExecutePlan:

    async def test_memory_queries_pass_through_without_any_call(self):
        plan = PreparationPlan(rappels=(Rappel("souvenirs", "a"),))
        results = await execute_plan(plan, "web_a")
        assert results.memory_queries == ["a"]
        assert results.exchange_hits == []

    async def test_exchange_intents_query_the_episodic_tier(self):
        from memory.episodic.api import ExchangeHit

        hit = ExchangeHit("5", "Lui: x", "web_b", 1, 5, 6, 0.0, 0.2)
        plan = PreparationPlan(rappels=(
            Rappel("echanges_passes", "le projet", person="Thomas"),
            Rappel("echanges_passes", "le projet encore"),
        ))
        with patch("memory.episodic.api.search_exchanges",
                   AsyncMock(return_value=[hit])) as mock:
            results = await execute_plan(plan, "web_a")
        assert mock.call_count == 2
        assert mock.call_args_list[0].kwargs["person"] == "Thomas"
        # Même chunk remonté deux fois → dédupliqué.
        assert len(results.exchange_hits) == 1


class TestGatherSeam:
    """La couture dans gather_context : note posée, rappel dirigé utilisé,
    et fail-open byte-identique quand le plan échoue."""

    def _patches(self, mock_mem):
        mock_emo = MagicMock()
        mock_emo.get_global_mood_context = MagicMock(return_value="")
        mock_drive = MagicMock()
        mock_drive.get_context = MagicMock(return_value="")
        mock_mod = MagicMock()
        mock_mod.collect_context = MagicMock(return_value="")
        mock_mod.collect_tools = MagicMock(return_value=[])
        return [
            patch("pipeline.context.memory_manager", mock_mem),
            patch("pipeline.context.emotion_engine", mock_emo),
            patch("pipeline.context.drive_engine", mock_drive),
            patch("pipeline.context.module_manager", mock_mod),
            patch("pipeline.context._fetch_self_concept",
                  new_callable=AsyncMock, return_value=""),
            patch("pipeline.context._fetch_person_context",
                  new_callable=AsyncMock, return_value=""),
        ]

    def _mock_mem(self):
        mock_mem = MagicMock()
        mock_mem.get_memory_context = AsyncMock(return_value="spéculatif")
        mock_mem.get_memory_context_multi = AsyncMock(return_value="dirigé")
        mock_mem.get_conversation_context = MagicMock(return_value=[])
        return mock_mem

    async def test_plan_drives_the_recall_and_sets_the_note(self):
        from pipeline.context import gather_context

        plan = PreparationPlan(
            rappels=(Rappel("souvenirs", "le chat"),),
            note_de_focus="elle reparle du chat",
        )

        async def _plan():
            return plan

        mock_mem = self._mock_mem()
        patches = self._patches(mock_mem) + [
            patch("pipeline.context._launch_preparation",
                  return_value=(asyncio.ensure_future(_plan()), 1e12)),
        ]
        for p in patches:
            p.start()
        try:
            ctx = await gather_context("le chat va bien ?", person_id="web_a")
        finally:
            for p in reversed(patches):
                p.stop()

        assert ctx.memory_context == "dirigé"
        assert "elle reparle du chat" in ctx.note_de_focus
        assert "pensée pré-verbale" in ctx.note_de_focus
        queries = mock_mem.get_memory_context_multi.call_args.args[0]
        assert queries == ["le chat va bien ?", "le chat"]

    async def test_charge_emotionnelle_becomes_the_salience_boost(self):
        from pipeline.context import gather_context

        plan = PreparationPlan(
            rappels=(Rappel("souvenirs", "la dispute"),),
            charge_emotionnelle=0.8,
        )

        async def _plan():
            return plan

        mock_mem = self._mock_mem()
        patches = self._patches(mock_mem) + [
            patch("pipeline.context._launch_preparation",
                  return_value=(asyncio.ensure_future(_plan()), 1e12)),
        ]
        for p in patches:
            p.start()
        try:
            await gather_context("on doit parler d'hier", person_id="web_a")
        finally:
            for p in reversed(patches):
                p.stop()

        boost = mock_mem.get_memory_context_multi.call_args.kwargs["salience_boost"]
        assert boost == pytest.approx(0.8)

    async def test_failed_plan_falls_back_to_the_speculative_floor(self):
        from pipeline.context import gather_context

        async def _boom():
            raise RuntimeError("plan cassé")

        mock_mem = self._mock_mem()
        patches = self._patches(mock_mem) + [
            patch("pipeline.context._launch_preparation",
                  return_value=(asyncio.ensure_future(_boom()), 1e12)),
        ]
        for p in patches:
            p.start()
        try:
            ctx = await gather_context("le chat va bien ?", person_id="web_a")
        finally:
            for p in reversed(patches):
                p.stop()

        assert ctx.memory_context == "spéculatif"
        assert ctx.note_de_focus == ""
        mock_mem.get_memory_context_multi.assert_not_called()

    async def test_no_pass_is_byte_identical_to_before(self):
        from pipeline.context import gather_context

        mock_mem = self._mock_mem()
        patches = self._patches(mock_mem)
        for p in patches:
            p.start()
        try:
            # Rôle non mappé dans l'environnement de test → gate fermé.
            ctx = await gather_context("tu te souviens du projet fusée ?",
                                       person_id="web_a")
        finally:
            for p in reversed(patches):
                p.stop()

        assert ctx.memory_context == "spéculatif"
        assert ctx.note_de_focus == ""
