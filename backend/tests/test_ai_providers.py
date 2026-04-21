"""Tests for AI providers — init, auth, complete(), error handling."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_config(values: dict):
    """Patch ``config_service.get`` so providers read the given values.

    The providers migrated off ``django.conf.settings`` — all credentials
    now come from ``configs.service.config_service``.
    """
    from configs.service import config_service

    def _fake_get(key, default=""):
        return values.get(key, default)

    return patch.object(config_service, "get", side_effect=_fake_get)


# ===================================================================
# ClaudeProvider
# ===================================================================

class TestClaudeProvider:

    def _make_provider(self, api_key="sk-ant-test", oauth_token="", mock_client=None):
        mock_client = mock_client or MagicMock()
        with _mock_config({
            "ai.claude.api_key": api_key,
            "ai.claude.oauth_token": oauth_token,
        }), patch("anthropic.AsyncAnthropic", return_value=mock_client):
            from ai.providers.claude import ClaudeProvider
            p = ClaudeProvider()
            p._client = mock_client
        return p

    def test_init_requires_credentials(self):
        with _mock_config({"ai.claude.api_key": "", "ai.claude.oauth_token": ""}):
            from ai.providers.claude import ClaudeProvider
            with pytest.raises(ValueError, match="nécessite"):
                ClaudeProvider()

    def test_init_with_api_key(self):
        with _mock_config({
            "ai.claude.api_key": "sk-ant-api-test",
            "ai.claude.oauth_token": "",
        }), patch("anthropic.AsyncAnthropic") as mock_cls:
            from ai.providers.claude import ClaudeProvider
            ClaudeProvider()
        mock_cls.assert_called_once_with(api_key="sk-ant-api-test")

    def test_init_with_oauth_prefers_token(self):
        with _mock_config({
            "ai.claude.api_key": "",
            "ai.claude.oauth_token": "sk-ant-oat01-xxx",
        }), patch("anthropic.AsyncAnthropic") as mock_cls:
            from ai.providers.claude import ClaudeProvider
            ClaudeProvider()
        call_kw = mock_cls.call_args[1]
        assert call_kw.get("auth_token") == "sk-ant-oat01-xxx"

    @pytest.mark.asyncio
    async def test_complete_returns_text_blocks(self):
        block = MagicMock()
        block.type = "text"
        block.text = "Bonjour !"
        mock_response = MagicMock()
        mock_response.content = [block]

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        p = self._make_provider(mock_client=mock_client)
        result = await p.complete("sys", "user", "claude-test")
        assert result == "Bonjour !"

    @pytest.mark.asyncio
    async def test_complete_joins_multiple_blocks(self):
        blocks = []
        for txt in ["Hello", " ", "World"]:
            b = MagicMock()
            b.type = "text"
            b.text = txt
            blocks.append(b)
        mock_response = MagicMock()
        mock_response.content = blocks

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        p = self._make_provider(mock_client=mock_client)
        result = await p.complete("sys", "user", "model")
        assert result == "Hello World"

    @pytest.mark.asyncio
    async def test_complete_skips_non_text_blocks(self):
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Réponse"
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        mock_response = MagicMock()
        mock_response.content = [text_block, tool_block]

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        p = self._make_provider(mock_client=mock_client)
        result = await p.complete("sys", "user", "model")
        assert result == "Réponse"


# ===================================================================
# OpenAIProvider
# ===================================================================

class TestOpenAIProvider:

    def _make_provider(self, api_key="sk-test", base_url="", mock_client=None):
        mock_client = mock_client or MagicMock()
        with _mock_config({
            "ai.openai.api_key": api_key,
            "ai.openai.base_url": base_url,
        }), patch("openai.AsyncOpenAI", return_value=mock_client):
            from ai.providers.openai_provider import OpenAIProvider
            p = OpenAIProvider()
            p._client = mock_client
        return p

    def test_init_missing_api_key_raises(self):
        with _mock_config({"ai.openai.api_key": "", "ai.openai.base_url": ""}), \
             patch("openai.AsyncOpenAI"):
            from ai.providers.openai_provider import OpenAIProvider
            with pytest.raises(ValueError, match="ai\\.openai\\.api_key"):
                OpenAIProvider()

    def test_init_passes_custom_base_url(self):
        with _mock_config({
            "ai.openai.api_key": "sk-test",
            "ai.openai.base_url": "https://api.groq.com",
        }), patch("openai.AsyncOpenAI") as mock_cls:
            from ai.providers.openai_provider import OpenAIProvider
            OpenAIProvider()
        assert mock_cls.call_args[1]["base_url"] == "https://api.groq.com"

    @pytest.mark.asyncio
    async def test_complete_returns_message_content(self):
        mock_choice = MagicMock()
        mock_choice.message.content = "Salut depuis OpenAI!"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        p = self._make_provider(mock_client=mock_client)
        result = await p.complete("sys", "user", "gpt-4o")
        assert result == "Salut depuis OpenAI!"

    @pytest.mark.asyncio
    async def test_complete_none_content_returns_empty(self):
        mock_choice = MagicMock()
        mock_choice.message.content = None
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        p = self._make_provider(mock_client=mock_client)
        result = await p.complete("sys", "user", "gpt-4o")
        assert result == ""


# ===================================================================
# OllamaProvider
# ===================================================================

class TestOllamaProvider:

    def _make_provider(self, host="", mock_client=None):
        mock_client = mock_client or MagicMock()
        with _mock_config({"ai.ollama.base_url": host}), \
             patch("ollama.AsyncClient", return_value=mock_client):
            from ai.providers.ollama_provider import OllamaProvider
            p = OllamaProvider()
            p._client = mock_client
        return p

    def test_init_default_host(self):
        with _mock_config({"ai.ollama.base_url": ""}), \
             patch("ollama.AsyncClient") as mock_cls:
            from ai.providers.ollama_provider import OllamaProvider
            OllamaProvider()
        assert mock_cls.call_args[1]["host"] == "http://localhost:11434"

    def test_init_custom_host(self):
        with _mock_config({"ai.ollama.base_url": "http://192.168.1.10:11434"}), \
             patch("ollama.AsyncClient") as mock_cls:
            from ai.providers.ollama_provider import OllamaProvider
            OllamaProvider()
        assert mock_cls.call_args[1]["host"] == "http://192.168.1.10:11434"

    @pytest.mark.asyncio
    async def test_complete_returns_message_content(self):
        mock_response = MagicMock()
        mock_response.message.content = "Réponse Ollama"
        mock_client = MagicMock()
        mock_client.chat = AsyncMock(return_value=mock_response)

        p = self._make_provider(mock_client=mock_client)
        result = await p.complete("sys", "user", "llama3")
        assert result == "Réponse Ollama"

    @pytest.mark.asyncio
    async def test_complete_passes_options(self):
        mock_response = MagicMock()
        mock_response.message.content = "ok"
        mock_client = MagicMock()
        mock_client.chat = AsyncMock(return_value=mock_response)

        p = self._make_provider(mock_client=mock_client)
        await p.complete("sys", "user", "llama3", max_tokens=512, temperature=0.3)

        opts = mock_client.chat.call_args[1]["options"]
        assert opts["num_predict"] == 512
        assert opts["temperature"] == 0.3
