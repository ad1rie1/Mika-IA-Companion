"""Budget de contexte + calibration chars→tokens."""

from __future__ import annotations

from ai.budget import ContextBudget, build_budget, budget_for, default_window_tokens
from ai.calibration import DEFAULT_CHARS_PER_TOKEN, TokenCalibration


class TestBuildBudget:

    def test_the_math_on_a_1m_window(self):
        b = build_budget(1_000_000, max_tokens=16_000, tools_chars=28_000)
        # 500k (ratio 0.5) − 16k sortie − 7k outils − 50k marge = 427k
        assert b.usable_tokens == 427_000
        assert b.l3_history_tokens == int(427_000 * 0.60)
        assert b.l5_recall_tokens == int(427_000 * 0.06)

    def test_a_small_window_never_goes_negative(self):
        b = build_budget(2_000, max_tokens=4_096)
        assert b.usable_tokens == 0

    def test_l5_chars_never_undercuts_the_floor(self):
        b = build_budget(8_000)
        assert b.l5_chars(floor=4_000) == 4_000

    def test_l5_chars_grows_with_the_window(self):
        b = build_budget(1_000_000, max_tokens=16_000)
        assert b.l5_chars(floor=4_000) > 50_000

    def test_default_window_fallback(self):
        assert default_window_tokens() == 16_384


class TestBudgetFor:

    def test_unmapped_role_is_none(self):
        from ai.router import AIRole

        # Environnement de test : aucun rôle mappé.
        assert budget_for(AIRole.CONVERSATION) is None

    def test_declared_window_yields_a_budget(self, monkeypatch):
        from ai import router as router_mod
        from ai.router import AIRole

        monkeypatch.setattr(
            router_mod.ai_router, "resolve",
            lambda role: ("claude", "model-x", 0.7, "x"),
        )
        monkeypatch.setattr(
            router_mod.ai_router, "_get_declared_models",
            lambda: {"x": {"context_window": 200_000, "max_tokens": 8_000}},
        )
        budget = budget_for(AIRole.CONVERSATION)
        assert isinstance(budget, ContextBudget)
        assert budget.window_tokens == 200_000
        assert budget.usable_tokens > 0

    def test_missing_window_is_none(self, monkeypatch):
        from ai import router as router_mod
        from ai.router import AIRole

        monkeypatch.setattr(
            router_mod.ai_router, "resolve",
            lambda role: ("claude", "model-x", 0.7, "x"),
        )
        monkeypatch.setattr(
            router_mod.ai_router, "_get_declared_models",
            lambda: {"x": {"context_window": None}},
        )
        assert budget_for(AIRole.CONVERSATION) is None


class TestCalibration:

    def test_ema_converges_toward_the_real_ratio(self):
        cal = TokenCalibration()
        for _ in range(30):
            cal.record("claude", prompt_chars=35_000, tokens_in=10_000)
        assert abs(cal.ratio("claude") - 3.5) < 0.05

    def test_small_samples_are_ignored(self):
        cal = TokenCalibration()
        cal.record("claude", prompt_chars=100, tokens_in=10)
        assert cal.ratio("claude") == DEFAULT_CHARS_PER_TOKEN

    def test_outliers_are_rejected(self):
        cal = TokenCalibration()
        # Usage cumulé d'une boucle d'outils : ratio < 1 char/token.
        cal.record("claude", prompt_chars=10_000, tokens_in=45_000)
        assert cal.ratio("claude") == DEFAULT_CHARS_PER_TOKEN

    def test_unknown_provider_defaults(self):
        assert TokenCalibration().ratio("ollama") == DEFAULT_CHARS_PER_TOKEN
