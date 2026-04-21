"""Tests for AIRouter — role → declared model resolution.

The router no longer parses ``provider:model`` strings. Each role points
to a declared model (by its internal_name), and a declared model is an
``ai.models`` record-list row with (internal_name, provider, model_id,
temperature). These tests cover resolution behaviour under the new
scheme.
"""

from unittest.mock import MagicMock, patch

import pytest

from ai.router import AIRole, AIRouter, UnconfiguredRoleError


def _mock_declared(models: dict[str, dict]):
    """Patch the declared-models loader with a fake map."""
    return patch("ai.router._load_declared_models", return_value=models)


def _mock_config_get(role_map: dict[str, str]):
    """Patch config_service.get so role → internal_name lookups return the map."""
    from configs.service import config_service

    def _fake_get(key, default=""):
        return role_map.get(key, default)

    return patch.object(config_service, "get", side_effect=_fake_get)


class TestRoleResolution:

    def test_resolve_maps_role_to_declared_model(self):
        with _mock_config_get({"ai.role.conversation": "fast-chat"}), \
             _mock_declared({
                 "fast-chat": {"provider": "claude", "model_id": "claude-sonnet-4-5", "temperature": 0.6},
             }):
            router = AIRouter()
            provider, model, temp, internal = router.resolve(AIRole.CONVERSATION)
        assert provider == "claude"
        assert model == "claude-sonnet-4-5"
        assert temp == 0.6
        assert internal == "fast-chat"

    def test_missing_role_raises(self):
        with _mock_config_get({}), _mock_declared({}):
            router = AIRouter()
            with pytest.raises(UnconfiguredRoleError, match="Aucun modèle"):
                router.resolve(AIRole.CONVERSATION)

    def test_unknown_internal_name_raises(self):
        with _mock_config_get({"ai.role.conversation": "ghost"}), \
             _mock_declared({}):
            router = AIRouter()
            with pytest.raises(UnconfiguredRoleError, match="n'est pas \\(ou plus\\) déclaré"):
                router.resolve(AIRole.CONVERSATION)

    def test_get_model_and_get_provider_name_match_resolution(self):
        with _mock_config_get({"ai.role.email_triage": "triager"}), \
             _mock_declared({
                 "triager": {"provider": "openai", "model_id": "gpt-4o-mini", "temperature": 0.3},
             }):
            router = AIRouter()
            assert router.get_model(AIRole.EMAIL_TRIAGE) == "gpt-4o-mini"
            assert router.get_provider_name(AIRole.EMAIL_TRIAGE) == "openai"


class TestProviderInstantiation:

    def test_get_provider_caches_instance(self):
        with _mock_config_get({"ai.role.conversation": "claude-std"}), \
             _mock_declared({
                 "claude-std": {"provider": "claude", "model_id": "claude-sonnet-4-5", "temperature": 0.7},
             }):
            router = AIRouter()
            fake_instance = MagicMock(name="ClaudeProvider instance")
            with patch.dict(
                "ai.router._PROVIDER_CLASSES",
                {"claude": MagicMock(return_value=fake_instance)},
                clear=False,
            ):
                a = router.get_provider(AIRole.CONVERSATION)
                b = router.get_provider(AIRole.CONVERSATION)
        assert a is b is fake_instance

    def test_reset_provider_drops_cache(self):
        with _mock_config_get({"ai.role.conversation": "claude-std"}), \
             _mock_declared({
                 "claude-std": {"provider": "claude", "model_id": "claude-sonnet-4-5", "temperature": 0.7},
             }):
            router = AIRouter()
            first = MagicMock(name="first")
            second = MagicMock(name="second")
            fake_cls = MagicMock(side_effect=[first, second])
            with patch.dict(
                "ai.router._PROVIDER_CLASSES",
                {"claude": fake_cls},
                clear=False,
            ):
                assert router.get_provider(AIRole.CONVERSATION) is first
                router.reset_provider("claude")
                assert router.get_provider(AIRole.CONVERSATION) is second
