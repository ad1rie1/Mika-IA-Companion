"""Tests for AIRouter — role mapping, provider routing, error handling."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ai.router import AIRole, AIRouter, _parse_role_setting


class TestParseRoleSetting:

    def test_valid_claude(self):
        provider, model = _parse_role_setting("claude:claude-opus-4-6")
        assert provider == "claude"
        assert model == "claude-opus-4-6"

    def test_valid_openai(self):
        provider, model = _parse_role_setting("openai:gpt-4o-mini")
        assert provider == "openai"
        assert model == "gpt-4o-mini"

    def test_strips_whitespace(self):
        provider, model = _parse_role_setting("  claude : claude-sonnet-4-6  ")
        assert provider == "claude"
        assert model == "claude-sonnet-4-6"

    def test_colon_in_model_name(self):
        """Model names with extra colons (fine-tuned IDs) should work."""
        provider, model = _parse_role_setting("openai:ft:gpt-4o:custom")
        assert provider == "openai"
        assert model == "ft:gpt-4o:custom"

    def test_missing_colon_raises(self):
        with pytest.raises(ValueError, match="Format invalide"):
            _parse_role_setting("claudeclaude-opus")

    def test_provider_lowercased(self):
        provider, _ = _parse_role_setting("CLAUDE:some-model")
        assert provider == "claude"


class TestAIRouterConfig:

    def test_all_roles_configured(self):
        router = AIRouter()
        for role in AIRole:
            provider, model = router._role_config[role]
            assert provider
            assert model

    def test_get_model_returns_string(self):
        router = AIRouter()
        model = router.get_model(AIRole.CONVERSATION)
        assert isinstance(model, str) and len(model) > 0

    def test_get_provider_name_is_known(self):
        router = AIRouter()
        provider = router.get_provider_name(AIRole.EMAIL_TRIAGE)
        assert provider in ("claude", "openai", "ollama")

    def test_default_conversation_uses_claude(self):
        router = AIRouter()
        assert router.get_provider_name(AIRole.CONVERSATION) == "claude"


class TestAIRouterGetProvider:

    def test_lazy_instantiation(self):
        router = AIRouter()
        assert "fakeprovider" not in router._providers
        mock_instance = MagicMock()
        with patch.dict("ai.router._PROVIDER_CLASSES", {"fakeprovider": lambda: mock_instance}):
            p = router._get_provider("fakeprovider")
        assert p is mock_instance

    def test_provider_cached_on_second_call(self):
        router = AIRouter()
        mock_cls = MagicMock(return_value=MagicMock())
        with patch.dict("ai.router._PROVIDER_CLASSES", {"myprov": mock_cls}):
            p1 = router._get_provider("myprov")
            p2 = router._get_provider("myprov")
        assert p1 is p2
        assert mock_cls.call_count == 1

    def test_unknown_provider_raises(self):
        router = AIRouter()
        with pytest.raises(ValueError, match="Provider inconnu"):
            router._get_provider("does_not_exist")


class TestAIRouterComplete:

    @pytest.mark.asyncio
    async def test_routes_to_provider_with_correct_model(self):
        router = AIRouter()
        mock_provider = MagicMock()
        mock_provider.complete = AsyncMock(return_value="Réponse")
        router._providers["claude"] = mock_provider
        router._role_config[AIRole.CONVERSATION] = ("claude", "claude-opus-4-6")

        result = await router.complete(AIRole.CONVERSATION, "sys", "user")

        assert result == "Réponse"
        call_kw = mock_provider.complete.call_args[1]
        assert call_kw["model"] == "claude-opus-4-6"
        assert call_kw["system_prompt"] == "sys"
        assert call_kw["user_prompt"] == "user"

    @pytest.mark.asyncio
    async def test_reraises_provider_exception(self):
        router = AIRouter()
        mock_provider = MagicMock()
        mock_provider.complete = AsyncMock(side_effect=RuntimeError("API down"))
        router._providers["claude"] = mock_provider
        router._role_config[AIRole.CONVERSATION] = ("claude", "model")

        with pytest.raises(RuntimeError, match="API down"):
            await router.complete(AIRole.CONVERSATION, "sys", "user")

    @pytest.mark.asyncio
    async def test_different_roles_use_different_models(self):
        router = AIRouter()
        models_used = []

        async def mock_complete(*, system_prompt, user_prompt, model, **kw):
            models_used.append(model)
            return "ok"

        mock_provider = MagicMock()
        mock_provider.complete = mock_complete
        router._providers["claude"] = mock_provider
        router._role_config[AIRole.CONVERSATION] = ("claude", "claude-opus-4-6")
        router._role_config[AIRole.EMAIL_TRIAGE] = ("claude", "claude-haiku-4-5-20251001")

        await router.complete(AIRole.CONVERSATION, "s", "u")
        await router.complete(AIRole.EMAIL_TRIAGE, "s", "u")

        assert models_used[0] == "claude-opus-4-6"
        assert models_used[1] == "claude-haiku-4-5-20251001"
