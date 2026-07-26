"""Provider instances must not outlive their credentials.

Each provider reads its API key once, in __init__, and the router caches the
instance for the process lifetime. Without eviction, rotating a leaked key in
the dashboard returned {"ok": true} while every subsequent call kept using
the compromised one.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_router():
    from ai.router import AIRouter
    r = AIRouter.__new__(AIRouter)
    r._providers = {}
    r._role_to_internal = {}
    return r


class TestProviderEviction:

    def test_credential_change_evicts_that_provider(self):
        r = _make_router()
        sentinel = MagicMock()
        r._providers["claude"] = sentinel

        r._invalidate_provider("ai.claude.", "ai.claude.api_key")

        assert "claude" not in r._providers

    def test_other_providers_are_left_alone(self):
        r = _make_router()
        openai = MagicMock()
        r._providers["claude"] = MagicMock()
        r._providers["openai"] = openai

        r._invalidate_provider("ai.claude.", "ai.claude.api_key")

        assert r._providers.get("openai") is openai

    def test_eviction_of_an_uncached_provider_is_a_noop(self):
        r = _make_router()
        r._invalidate_provider("ai.gemini.", "ai.gemini.api_key")  # no raise
        assert r._providers == {}

    @pytest.mark.parametrize("prefix,expected", [
        ("ai.claude.", "claude"),
        ("ai.openai.", "openai"),
        ("ai.gemini.", "gemini"),
        ("ai.glm.", "glm"),
        ("ai.ollama.", "ollama"),
    ])
    def test_every_declared_prefix_maps_to_a_known_provider(self, prefix, expected):
        from ai.router import _PROVIDER_CLASSES, _PROVIDER_CONFIG_PREFIXES

        assert prefix in _PROVIDER_CONFIG_PREFIXES
        r = _make_router()
        r._providers[expected] = MagicMock()
        r._invalidate_provider(prefix, prefix + "api_key")
        assert expected not in r._providers
        assert expected in _PROVIDER_CLASSES

    def test_all_provider_classes_have_a_credential_prefix(self):
        # A new provider added without a prefix would silently keep stale keys.
        from ai.router import _PROVIDER_CLASSES, _PROVIDER_CONFIG_PREFIXES

        covered = {p.removeprefix("ai.").rstrip(".")
                   for p in _PROVIDER_CONFIG_PREFIXES}
        assert set(_PROVIDER_CLASSES) <= covered
