"""Tests for AI providers — init, auth, complete(), error handling."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ===================================================================
# ClaudeProvider
# ===================================================================

class TestClaudeProvider:

    def _make_provider(self, api_key="sk-ant-test", oauth_token="", mock_client=None):
        mock_client = mock_client or MagicMock()
        with patch("ai.providers.claude.settings") as ms, \
             patch("anthropic.AsyncAnthropic", return_value=mock_client):
            ms.ANTHROPIC_API_KEY = api_key
            ms.CLAUDE_OAUTH_TOKEN = oauth_token
            from ai.providers.claude import ClaudeProvider
            p = ClaudeProvider()
            p._client = mock_client
        return p

    def test_init_requires_credentials(self):
        with patch("ai.providers.claude.settings") as ms:
            ms.ANTHROPIC_API_KEY = ""
            ms.CLAUDE_OAUTH_TOKEN = ""
            from ai.providers.claude import ClaudeProvider
            with pytest.raises(ValueError, match="nécessite"):
                ClaudeProvider()

    def test_init_with_api_key(self):
        with patch("ai.providers.claude.settings") as ms, \
             patch("anthropic.AsyncAnthropic") as mock_cls:
            ms.ANTHROPIC_API_KEY = "sk-ant-api-test"
            ms.CLAUDE_OAUTH_TOKEN = ""
            from ai.providers.claude import ClaudeProvider
            ClaudeProvider()
        mock_cls.assert_called_once_with(api_key="sk-ant-api-test")

    def test_init_with_oauth_prefers_token(self):
        with patch("ai.providers.claude.settings") as ms, \
             patch("anthropic.AsyncAnthropic") as mock_cls:
            ms.ANTHROPIC_API_KEY = ""
            ms.CLAUDE_OAUTH_TOKEN = "sk-ant-oat01-xxx"
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
        with patch("ai.providers.openai_provider.settings") as ms, \
             patch("openai.AsyncOpenAI", return_value=mock_client):
            ms.OPENAI_API_KEY = api_key
            ms.OPENAI_BASE_URL = base_url
            from ai.providers.openai_provider import OpenAIProvider
            p = OpenAIProvider()
            p._client = mock_client
        return p

    def test_init_missing_api_key_raises(self):
        with patch("ai.providers.openai_provider.settings") as ms, \
             patch("openai.AsyncOpenAI"):
            ms.OPENAI_API_KEY = ""
            ms.OPENAI_BASE_URL = ""
            from ai.providers.openai_provider import OpenAIProvider
            with pytest.raises(ValueError, match="OPENAI_API_KEY"):
                OpenAIProvider()

    def test_init_passes_custom_base_url(self):
        with patch("ai.providers.openai_provider.settings") as ms, \
             patch("openai.AsyncOpenAI") as mock_cls:
            ms.OPENAI_API_KEY = "sk-test"
            ms.OPENAI_BASE_URL = "https://api.groq.com"
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
        with patch("ai.providers.ollama_provider.settings") as ms, \
             patch("ollama.AsyncClient", return_value=mock_client):
            ms.OLLAMA_BASE_URL = host
            from ai.providers.ollama_provider import OllamaProvider
            p = OllamaProvider()
            p._client = mock_client
        return p

    def test_init_default_host(self):
        with patch("ai.providers.ollama_provider.settings") as ms, \
             patch("ollama.AsyncClient") as mock_cls:
            ms.OLLAMA_BASE_URL = ""
            from ai.providers.ollama_provider import OllamaProvider
            OllamaProvider()
        assert mock_cls.call_args[1]["host"] == "http://localhost:11434"

    def test_init_custom_host(self):
        with patch("ai.providers.ollama_provider.settings") as ms, \
             patch("ollama.AsyncClient") as mock_cls:
            ms.OLLAMA_BASE_URL = "http://192.168.1.10:11434"
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
