"""Ollama Cloud — a second provider sharing one implementation.

The hosted endpoint speaks the same protocol as a local server, so the class
is a subclass and the tool loop is not duplicated. Everything worth testing
is therefore at the seams, where "same protocol" stops being true:

  - the two providers must read **different** config keys, or the local cap
    of 768 tokens (calibrated for an RTX 3060) governs a hosted model;
  - they must be **evicted independently**, or rotating one key silently
    keeps the other's stale credential — the exact bug provider eviction
    exists to prevent;
  - ``test()`` must probe the **credential**, not the endpoint. Measured
    against the live host: ``GET /api/tags`` answers 200 with no key at all,
    so the inherited ``default_test`` (which just counts ``list_models()``)
    would report a provider with no API key as healthy.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _provider(host="https://ollama.com"):
    from ai.providers.ollama_cloud_provider import OllamaCloudProvider

    p = OllamaCloudProvider.__new__(OllamaCloudProvider)
    p._host = host
    p._client = MagicMock()
    p._client.chat = AsyncMock(return_value=_response("ok"))
    return p


def _response(text):
    msg = MagicMock()
    msg.content = text
    msg.tool_calls = []
    resp = MagicMock()
    resp.message = msg
    return resp


def _config(values):
    def fake_get(key, default=None):
        if key in values:
            return values[key]
        raise KeyError(key)

    return patch("configs.service.config_service.get", side_effect=fake_get)


class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _fake_httpx(response, recorder=None, raises=None):
    """Patch ``httpx.AsyncClient`` and capture how it was constructed."""

    class _Client:
        def __init__(self, **kwargs):
            if recorder is not None:
                recorder.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            if recorder is not None:
                recorder["url"] = url
            if raises is not None:
                raise raises
            return response

    return patch("httpx.AsyncClient", _Client)


# ── Registration ────────────────────────────────────────────────────────

class TestRegistration:

    def test_the_provider_is_routable(self):
        from ai.providers.ollama_cloud_provider import OllamaCloudProvider
        from ai.router import _PROVIDER_CLASSES

        assert _PROVIDER_CLASSES["ollama_cloud"] is OllamaCloudProvider

    def test_it_is_selectable_in_the_model_declaration_form(self):
        """A provider the router knows and the form doesn't is unreachable;
        one the form offers and the router can't build fails at the first
        AI call, far from the screen where it was chosen."""
        from ai.config_schema import PROVIDERS
        from ai.router import _PROVIDER_CLASSES
        from configs.types import choice_values

        assert set(choice_values(PROVIDERS)) == set(_PROVIDER_CLASSES)

    def test_the_dropdown_carries_a_readable_label(self):
        from ai.config_schema import PROVIDERS
        from configs.types import choice_options

        labels = dict(choice_options(PROVIDERS))
        assert labels["ollama_cloud"] == "Ollama Cloud"
        assert labels["ollama"] == "Ollama (local)"

    def test_the_two_ollama_providers_evict_independently(self):
        """Prefix matching is a plain ``startswith``.

        "ai.ollama_cloud.api_key" does not begin with "ai.ollama." — that is
        what keeps them apart, and it would stop being true under a naming
        like "ai.ollama.cloud.api_key".
        """
        from ai.router import AIRouter

        r = AIRouter.__new__(AIRouter)
        r._providers = {"ollama": MagicMock(), "ollama_cloud": MagicMock()}
        local = r._providers["ollama"]

        r._invalidate_provider("ai.ollama_cloud.", "ai.ollama_cloud.api_key")

        assert "ollama_cloud" not in r._providers
        assert r._providers.get("ollama") is local

    def test_rotating_the_local_url_leaves_the_cloud_alone(self):
        from ai.router import AIRouter

        r = AIRouter.__new__(AIRouter)
        cloud = MagicMock()
        r._providers = {"ollama": MagicMock(), "ollama_cloud": cloud}

        r._invalidate_provider("ai.ollama.", "ai.ollama.base_url")

        assert "ollama" not in r._providers
        assert r._providers.get("ollama_cloud") is cloud

    def test_a_cloud_key_change_does_not_match_the_local_prefix(self):
        """The eviction wiring above only holds because of this."""
        assert not "ai.ollama_cloud.api_key".startswith("ai.ollama.")


# ── Authentication ──────────────────────────────────────────────────────

class TestAuthentication:

    def test_the_key_is_sent_as_a_bearer_header(self):
        p = _provider()
        with _config({"ai.ollama_cloud.api_key": "sk-abc"}):
            assert p._headers() == {"Authorization": "Bearer sk-abc"}

    def test_no_key_means_no_header(self):
        """Rather than "Bearer " — an empty credential must read as absent,
        which is what ``test()`` reports on."""
        p = _provider()
        with _config({"ai.ollama_cloud.api_key": "   "}):
            assert p._headers() == {}

    def test_an_unreadable_config_yields_no_header(self):
        """A config read can precede a reachable database; the provider must
        still instantiate and say plainly that it has no key."""
        p = _provider()
        with patch("configs.service.config_service.get",
                   side_effect=RuntimeError("db down")):
            assert p._headers() == {}

    def test_the_header_reaches_the_sdk_client(self):
        from ai.providers.ollama_cloud_provider import OllamaCloudProvider

        seen = {}

        def fake_client(**kwargs):
            seen.update(kwargs)
            return MagicMock()

        with _config({"ai.ollama_cloud.api_key": "sk-abc",
                      "ai.ollama_cloud.base_url": "https://ollama.com"}), \
             patch("ollama.AsyncClient", fake_client):
            OllamaCloudProvider()

        assert seen["host"] == "https://ollama.com"
        assert seen["headers"] == {"Authorization": "Bearer sk-abc"}

    async def test_the_header_reaches_the_catalogue_call(self):
        """``list_models`` goes through plain httpx, not the SDK — it needed
        the header wired a second time."""
        p = _provider()
        seen = {}
        with _config({"ai.ollama_cloud.api_key": "sk-abc"}), \
             _fake_httpx(_FakeResponse(200, {"models": [{"name": "kimi-k3"}]}), seen):
            models = await p.list_models()

        assert seen["headers"] == {"Authorization": "Bearer sk-abc"}
        assert seen["url"] == "https://ollama.com/api/tags"
        assert models == [{"id": "kimi-k3", "label": "kimi-k3"}]

    def test_the_local_provider_still_sends_none(self):
        from ai.providers.ollama_provider import OllamaProvider

        p = OllamaProvider.__new__(OllamaProvider)
        assert p._headers() == {}


# ── The credential probe ────────────────────────────────────────────────

class TestCredentialProbe:

    async def test_no_key_is_not_healthy(self):
        """The trap this override exists for: /api/tags answers 200 without
        any credential, so counting models would call this provider fine."""
        p = _provider()
        with _config({"ai.ollama_cloud.api_key": ""}):
            result = await p.test()

        assert result["ok"] is False
        assert "clé" in result["error"].lower()

    async def test_a_rejected_key_is_reported(self):
        p = _provider()
        with _config({"ai.ollama_cloud.api_key": "sk-bad"}), \
             _fake_httpx(_FakeResponse(401, {"error": "unauthorized"})):
            result = await p.test()

        assert result["ok"] is False
        assert "401" in result["error"]

    async def test_an_accepted_key_counts_the_catalogue(self):
        p = _provider()
        calls = {"n": 0}

        def response_for(_url):
            calls["n"] += 1
            return _FakeResponse(200, {"models": [{"name": "gpt-oss:120b"}]})

        class _Client:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url):
                return response_for(url)

        with _config({"ai.ollama_cloud.api_key": "sk-good"}), \
             patch("httpx.AsyncClient", _Client):
            result = await p.test()

        assert result["ok"] is True
        assert result["model_count"] == 1

    async def test_a_host_without_the_probe_endpoint_is_not_a_failure(self):
        """404/405 says nothing about the credential — only 401/403 does.
        Reading "endpoint absent" as "key refused" would break a self-hosted
        gateway that is perfectly authenticated."""
        p = _provider()

        class _Client:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url):
                if url.endswith("/api/ps"):
                    return _FakeResponse(404)
                return _FakeResponse(200, {"models": [{"name": "glm-5.2"}]})

        with _config({"ai.ollama_cloud.api_key": "sk-good"}), \
             patch("httpx.AsyncClient", _Client):
            result = await p.test()

        assert result["ok"] is True
        assert result["model_count"] == 1

    async def test_an_unreachable_host_is_reported_not_raised(self):
        p = _provider()
        with _config({"ai.ollama_cloud.api_key": "sk-good"}), \
             _fake_httpx(None, raises=OSError("connection refused")):
            result = await p.test()

        assert result["ok"] is False
        assert "injoignable" in result["error"]


# ── Generation policy is per-provider ───────────────────────────────────

@pytest.mark.asyncio
class TestSeparateBudget:

    async def test_the_cloud_reads_its_own_cap(self):
        """The whole reason this is a distinct provider: 768 tokens is a belt
        against a 19 tok/s local model, not a sentence-length policy."""
        p = _provider()
        with _config({"ai.ollama_cloud.thinking": False,
                      "ai.ollama_cloud.max_reply_tokens": 2048,
                      "ai.ollama.max_reply_tokens": 768}), \
             patch("ai.providers.ollama_provider._record_ollama_usage"):
            await p.complete("sys", "coucou", model="gpt-oss:120b", max_tokens=4096)

        opts = p._client.chat.await_args.kwargs["options"]
        assert opts["num_predict"] == 2048

    async def test_the_local_cap_does_not_leak_into_the_cloud(self):
        """Only the local key is set: the cloud must fall back to its own
        default, not inherit 768."""
        p = _provider()
        with _config({"ai.ollama.max_reply_tokens": 768,
                      "ai.ollama.thinking": True}), \
             patch("ai.providers.ollama_provider._record_ollama_usage"):
            await p.complete("sys", "coucou", model="gpt-oss:120b", max_tokens=4096)

        kwargs = p._client.chat.await_args.kwargs
        assert kwargs["options"]["num_predict"] == 2048
        assert kwargs["think"] is False

    async def test_a_smaller_caller_budget_still_wins(self):
        p = _provider()
        with _config({"ai.ollama_cloud.thinking": False,
                      "ai.ollama_cloud.max_reply_tokens": 2048}), \
             patch("ai.providers.ollama_provider._record_ollama_usage"):
            await p.complete("sys", "coucou", model="m", max_tokens=100)

        assert p._client.chat.await_args.kwargs["options"]["num_predict"] == 100

    async def test_an_unreadable_config_still_caps(self):
        p = _provider()
        with patch("configs.service.config_service.get",
                   side_effect=RuntimeError("db down")), \
             patch("ai.providers.ollama_provider._record_ollama_usage"):
            await p.complete("sys", "coucou", model="m", max_tokens=4096)

        assert p._client.chat.await_args.kwargs["options"]["num_predict"] == 2048

    async def test_thinking_is_read_from_the_cloud_key(self):
        p = _provider()
        with _config({"ai.ollama_cloud.thinking": True,
                      "ai.ollama_cloud.max_reply_tokens": 2048}), \
             patch("ai.providers.ollama_provider._record_ollama_usage"):
            await p.complete("sys", "coucou", model="m")

        assert p._client.chat.await_args.kwargs["think"] is True

    async def test_the_tool_loop_uses_the_same_policy(self):
        p = _provider()
        p._client.chat = AsyncMock(return_value=_response("fini"))
        with _config({"ai.ollama_cloud.thinking": False,
                      "ai.ollama_cloud.max_reply_tokens": 2048}), \
             patch("ai.providers.ollama_provider._record_ollama_usage"):
            text, called = await p.complete_with_tools(
                "sys", "coucou", model="m", tools=[], max_tokens=4096,
            )

        assert text == "fini"
        assert p._client.chat.await_args.kwargs["options"]["num_predict"] == 2048


# ── Declared configuration ──────────────────────────────────────────────

class TestDeclaredConfig:

    def _items(self):
        from ai.config_schema import CONFIG_SCHEMA

        return {getattr(i, "key", None): i for i in CONFIG_SCHEMA
                if getattr(i, "key", None)}

    def test_the_four_knobs_are_declared(self):
        items = self._items()
        for key in ("api_key", "base_url", "thinking", "max_reply_tokens"):
            assert f"ai.ollama_cloud.{key}" in items

    def test_the_key_is_a_secret(self):
        """It is stored encrypted and never rendered back to the browser."""
        item = self._items()["ai.ollama_cloud.api_key"]
        assert item.type == "secret"
        assert item.sensitive is True

    def test_defaults(self):
        items = self._items()
        assert items["ai.ollama_cloud.base_url"].default == "https://ollama.com"
        assert items["ai.ollama_cloud.thinking"].default is False
        assert items["ai.ollama_cloud.max_reply_tokens"].default == 2048

    def test_every_knob_is_hot_reloadable(self):
        """Credentials especially: a rotated key that needs a restart is the
        bug provider eviction was written for."""
        items = self._items()
        for key in ("api_key", "base_url", "thinking", "max_reply_tokens"):
            assert items[f"ai.ollama_cloud.{key}"].hot_reload is True

    def test_the_two_providers_have_distinct_groups(self):
        """Same section, different group — the form must not present one set
        of fields for two machines."""
        items = self._items()
        assert items["ai.ollama.base_url"].group == "Ollama"
        assert items["ai.ollama_cloud.base_url"].group == "Ollama Cloud"
        assert items["ai.ollama_cloud.base_url"].section == "ai_providers"


class TestQuota:

    def test_hosted_ollama_is_billed_by_subscription_not_by_token(self):
        from ai.quota import _lookup_pricing

        assert _lookup_pricing("ollama_cloud", "gpt-oss:120b") == (0.0, 0.0)
        assert _lookup_pricing("ollama", "gemma4:12b") == (0.0, 0.0)

    def test_a_hosted_model_never_falls_through_to_the_pricing_table(self):
        """A model id that happens to prefix-match a priced one must not
        invent a cost for a provider that has none."""
        from ai.quota import _lookup_pricing

        assert _lookup_pricing("ollama_cloud", "gpt-4o") == (0.0, 0.0)
