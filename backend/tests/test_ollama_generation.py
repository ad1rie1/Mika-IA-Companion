"""Ollama generation policy — the two knobs that decide if a local model answers.

Measured on gemma4:12b, RTX 3060, model fully in VRAM at ~30 tok/s:

    think default (on)   "coucou" → 257 tokens generated, 27.1 s
    think: false         "coucou" →  16 tokens generated,  1.5 s

With a real system prompt and 34 tool declarations the same greeting ran
past 2000 generated tokens and was *still generating* when the 120 s
timeout fired — the server log shows the client aborting, not the model
stopping. Every turn came back as the fallback.

The second knob is the belt: ``max_tokens`` defaulted to 4096 and was
passed straight through as ``num_predict``, which at the ~19 tok/s a long
context degrades to is 219 s of generation. A turn that cannot finish
inside any sane timeout.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _provider():
    from ai.providers.ollama_provider import OllamaProvider

    p = OllamaProvider.__new__(OllamaProvider)
    p._host = "http://localhost:11434"
    p._client = MagicMock()
    p._client.chat = AsyncMock(return_value=_response("ok"))
    return p


def _response(text, tool_calls=None):
    msg = MagicMock()
    msg.content = text
    msg.tool_calls = tool_calls or []
    resp = MagicMock()
    resp.message = msg
    return resp


def _config(values):
    """Patch the config service the provider reads its policy from."""
    def fake_get(key, default=None):
        if key in values:
            return values[key]
        raise KeyError(key)

    return patch("configs.service.config_service.get", side_effect=fake_get)


@pytest.mark.asyncio
class TestThinking:

    async def test_thinking_is_off_by_default(self):
        """A reasoning model reasons before the first word of the reply.

        On a hosted API that is a quality choice; on a local 12B it is the
        difference between a 1.5 s greeting and a 27 s one.
        """
        p = _provider()
        with _config({"ai.ollama.thinking": False,
                      "ai.ollama.max_reply_tokens": 768}), \
             patch("ai.providers.ollama_provider._record_ollama_usage"):
            await p.complete("sys", "coucou", model="gemma4:12b")

        assert p._client.chat.await_args.kwargs["think"] is False

    async def test_thinking_can_be_turned_back_on(self):
        p = _provider()
        with _config({"ai.ollama.thinking": True,
                      "ai.ollama.max_reply_tokens": 768}), \
             patch("ai.providers.ollama_provider._record_ollama_usage"):
            await p.complete("sys", "coucou", model="gemma4:12b")

        assert p._client.chat.await_args.kwargs["think"] is True

    async def test_an_unreadable_config_does_not_re_enable_thinking(self):
        """Silence must fall on the safe side.

        The config service reads a database that may not be reachable yet;
        defaulting to "reason freely" would restore the exact behaviour that
        made every turn time out.
        """
        p = _provider()
        with patch("configs.service.config_service.get",
                   side_effect=RuntimeError("db down")), \
             patch("ai.providers.ollama_provider._record_ollama_usage"):
            await p.complete("sys", "coucou", model="gemma4:12b")

        assert p._client.chat.await_args.kwargs["think"] is False

    async def test_a_server_that_rejects_think_is_retried_without_it(self):
        """Not every model or Ollama build accepts the parameter.

        A provider that cannot talk to half the local models would be a
        worse regression than the one it fixes.
        """
        p = _provider()
        calls = []

        async def chat(**kwargs):
            calls.append(kwargs)
            if "think" in kwargs and len(calls) == 1:
                raise ValueError("unknown parameter: think")
            return _response("ok")

        p._client.chat = chat
        with _config({"ai.ollama.thinking": False,
                      "ai.ollama.max_reply_tokens": 768}), \
             patch("ai.providers.ollama_provider._record_ollama_usage"):
            out = await p.complete("sys", "coucou", model="gemma4:12b")

        assert out == "ok"
        assert len(calls) == 2
        assert "think" not in calls[1]


@pytest.mark.asyncio
class TestReplyCap:

    async def test_num_predict_is_capped(self):
        """The caller's 4096 default is a 219 s rope at a degraded 19 tok/s."""
        p = _provider()
        with _config({"ai.ollama.thinking": False,
                      "ai.ollama.max_reply_tokens": 768}), \
             patch("ai.providers.ollama_provider._record_ollama_usage"):
            await p.complete("sys", "coucou", model="m", max_tokens=4096)

        assert p._client.chat.await_args.kwargs["options"]["num_predict"] == 768

    async def test_a_smaller_caller_budget_still_wins(self):
        """The cap is a ceiling, not a target."""
        p = _provider()
        with _config({"ai.ollama.thinking": False,
                      "ai.ollama.max_reply_tokens": 768}), \
             patch("ai.providers.ollama_provider._record_ollama_usage"):
            await p.complete("sys", "coucou", model="m", max_tokens=100)

        assert p._client.chat.await_args.kwargs["options"]["num_predict"] == 100

    async def test_an_unreadable_config_still_caps(self):
        """The unbounded rope is what this exists to prevent — a config read
        failing must not quietly restore it."""
        p = _provider()
        with patch("configs.service.config_service.get",
                   side_effect=RuntimeError("db down")), \
             patch("ai.providers.ollama_provider._record_ollama_usage"):
            await p.complete("sys", "coucou", model="m", max_tokens=4096)

        assert p._client.chat.await_args.kwargs["options"]["num_predict"] == 768

    async def test_the_tool_loop_applies_the_same_policy(self):
        """The tool loop is where it matters most: every round re-prefills the
        whole prompt, so an unbounded reply per round compounds."""
        p = _provider()
        p._client.chat = AsyncMock(return_value=_response("fini"))
        with _config({"ai.ollama.thinking": False,
                      "ai.ollama.max_reply_tokens": 768}), \
             patch("ai.providers.ollama_provider._record_ollama_usage"):
            text, called = await p.complete_with_tools(
                "sys", "coucou", model="m", tools=[], max_tokens=4096,
            )

        assert text == "fini"
        kwargs = p._client.chat.await_args.kwargs
        assert kwargs["think"] is False
        assert kwargs["options"]["num_predict"] == 768


class TestDeclaredConfig:
    """The knobs exist in the registry, so they are editable without code."""

    def test_both_knobs_are_declared_with_safe_defaults(self):
        from ai.config_schema import CONFIG_SCHEMA

        items = {
            getattr(i, "key", None): i for i in CONFIG_SCHEMA
            if getattr(i, "key", None)
        }
        assert items["ai.ollama.thinking"].default is False
        assert items["ai.ollama.max_reply_tokens"].default == 768
        # Hot-reloadable: these are values you tune while watching a turn,
        # not on the next restart.
        assert items["ai.ollama.thinking"].hot_reload is True
