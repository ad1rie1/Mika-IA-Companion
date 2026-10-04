"""Tests for AI providers — init, auth, complete(), error handling."""

import ast
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

_BACKEND = Path(__file__).resolve().parent.parent


def _mock_config(values: dict):
    """Patch ``config_service.get`` so providers read the given values.

    The providers migrated off ``django.conf.settings`` — all credentials
    now come from ``configs.service.config_service``.
    """
    from old.backend.configs.service import config_service

    def _fake_get(key, default=""):
        return values.get(key, default)

    return patch.object(config_service, "get", side_effect=_fake_get)


# ===================================================================
# Le chemin claude_agent_sdk n'existe plus
# ===================================================================

class TestAgentSdkRemoved:
    """Anthropic ne supporte plus le sous-processus CLI authentifié par
    jeton OAuth. Le paquet reste installable et importable : une
    réintroduction ne casserait donc rien à l'exécution, elle rebrancherait
    silencieusement un chemin mort. Ce pin est la seule chose qui le dit.
    """

    def _source_files(self):
        for path in _BACKEND.rglob("*.py"):
            parts = path.relative_to(_BACKEND).parts
            if "tests" in parts or "__pycache__" in parts:
                continue
            yield path

    def test_no_backend_module_imports_claude_agent_sdk(self):
        offenders = []
        for path in self._source_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                if any(
                    name == "claude_agent_sdk" or name.startswith("claude_agent_sdk.")
                    for name in names
                ):
                    offenders.append(f"{path.relative_to(_BACKEND)}:{node.lineno}")
        assert offenders == []

    def test_requirements_no_longer_pin_the_sdk(self):
        text = (_BACKEND / "requirements.txt").read_text(encoding="utf-8")
        assert "claude_agent_sdk" not in text
        assert "claude-agent-sdk" not in text
        # anthropic reste la dépendance qui porte tout le provider.
        assert "anthropic" in text


# ===================================================================
# ClaudeProvider
# ===================================================================

class TestClaudeProvider:

    def _make_provider(self, api_key="sk-ant-test", mock_client=None):
        mock_client = mock_client or MagicMock()
        with _mock_config({
            "ai.claude.api_key": api_key,
        }), patch("anthropic.AsyncAnthropic", return_value=mock_client):
            from old.backend.ai.providers.claude import ClaudeProvider
            p = ClaudeProvider()
            p._client = mock_client
        return p

    def test_init_without_api_key_refuses_clearly(self):
        """Le refus doit nommer la clé d'API et où la saisir.

        Ce pin était « api_key OU oauth_token » : le second identifiant
        n'existe plus, donc une installation qui n'avait qu'un jeton OAuth
        se retrouve sans identifiant du tout et doit l'apprendre du message
        d'erreur, pas d'un 401 au premier tour.
        """
        with _mock_config({"ai.claude.api_key": ""}):
            from old.backend.ai.providers.claude import ClaudeProvider
            with pytest.raises(ValueError) as err:
                ClaudeProvider()
        message = str(err.value)
        assert "clé d'API" in message
        assert "IA · Claude" in message

    def test_init_with_api_key(self):
        with _mock_config({
            "ai.claude.api_key": "sk-ant-api-test",
        }), patch("anthropic.AsyncAnthropic") as mock_cls:
            from old.backend.ai.providers.claude import ClaudeProvider
            ClaudeProvider()
        mock_cls.assert_called_once_with(api_key="sk-ant-api-test")

    def test_oauth_token_alone_is_refused(self):
        """Pin retourné : un jeton OAuth seul suffisait, il ne suffit plus.

        L'ancien test affirmait que le jeton était *préféré* à la clé et
        passé en ``auth_token=``. Il n'était vrai que parce que la boucle
        d'outils repassait par le sous-processus CLI, seul chemin où ces
        jetons ont des droits. Ce chemin est supprimé : une valeur restée
        en base sous ``ai.claude.oauth_token`` n'est plus lue du tout.
        """
        with _mock_config({
            "ai.claude.api_key": "",
            "ai.claude.oauth_token": "sk-ant-oat01-xxx",
        }), patch("anthropic.AsyncAnthropic") as mock_cls:
            from old.backend.ai.providers.claude import ClaudeProvider
            with pytest.raises(ValueError):
                ClaudeProvider()
        mock_cls.assert_not_called()

    def test_oauth_token_is_no_longer_a_declared_config_item(self):
        from old.backend.ai.config_schema import CONFIG_SCHEMA

        keys = {getattr(item, "key", None) for item in CONFIG_SCHEMA}
        assert "ai.claude.oauth_token" not in keys
        assert "ai.claude.api_key" in keys

    @pytest.mark.asyncio
    async def test_authentication_error_propagates(self):
        """Pin retourné : un 401 basculait sur le CLI, il remonte maintenant.

        La bascule existait pour les jetons OAuth aux droits CLI seulement.
        Sans ce chemin, masquer l'erreur ne ferait que retarder le
        diagnostic — une clé révoquée doit se voir tout de suite.
        """
        import anthropic
        from old.backend.ai.chat import ChatPrompt

        error = anthropic.AuthenticationError(
            "unauthorized",
            response=MagicMock(status_code=401, headers={}),
            body=None,
        )
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(side_effect=error)

        p = self._make_provider(mock_client=mock_client)
        with pytest.raises(anthropic.AuthenticationError):
            await p.complete_chat(ChatPrompt("S", message="m"), model="claude-opus-4-8")

    @pytest.mark.asyncio
    async def test_tooled_turn_runs_on_the_native_messages_api(self):
        """Un tour outillé ne passe plus que par ``messages.create``."""
        tool_use = MagicMock()
        tool_use.type = "tool_use"
        tool_use.name = "ping"
        tool_use.input = {}
        tool_use.id = "tu_1"
        first = MagicMock(content=[tool_use], stop_reason="tool_use", usage=None)

        final_text = MagicMock()
        final_text.type = "text"
        final_text.text = "fini"
        second = MagicMock(content=[final_text], stop_reason="end_turn", usage=None)

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(side_effect=[first, second])

        async def handler(args):
            return {"content": [{"type": "text", "text": "pong"}]}

        tool = MagicMock()
        tool.name = "ping"
        tool.description = "d"
        tool.to_json_schema.return_value = {"type": "object", "properties": {}}
        tool.handler = handler

        from old.backend.ai.chat import ChatPrompt

        p = self._make_provider(mock_client=mock_client)
        text, calls = await p.complete_chat_with_tools(
            ChatPrompt("sys", message="user"), model="claude-3-5-haiku",
            tools=[tool],
        )
        assert text == "fini"
        assert calls == ["ping"]
        assert mock_client.messages.create.await_count == 2
        assert mock_client.messages.create.await_args_list[0].kwargs["tools"][0]["name"] == "ping"

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
            from old.backend.ai.providers.openai_provider import OpenAIProvider
            p = OpenAIProvider()
            p._client = mock_client
        return p

    def test_init_missing_api_key_raises(self):
        with _mock_config({"ai.openai.api_key": "", "ai.openai.base_url": ""}), \
             patch("openai.AsyncOpenAI"):
            from old.backend.ai.providers.openai_provider import OpenAIProvider
            with pytest.raises(ValueError, match="ai\\.openai\\.api_key"):
                OpenAIProvider()

    def test_init_passes_custom_base_url(self):
        with _mock_config({
            "ai.openai.api_key": "sk-test",
            "ai.openai.base_url": "https://api.groq.com",
        }), patch("openai.AsyncOpenAI") as mock_cls:
            from old.backend.ai.providers.openai_provider import OpenAIProvider
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
            from old.backend.ai.providers.ollama_provider import OllamaProvider
            p = OllamaProvider()
            p._client = mock_client
        return p

    def test_init_default_host(self):
        with _mock_config({"ai.ollama.base_url": ""}), \
             patch("ollama.AsyncClient") as mock_cls:
            from old.backend.ai.providers.ollama_provider import OllamaProvider
            OllamaProvider()
        assert mock_cls.call_args[1]["host"] == "http://localhost:11434"

    def test_init_custom_host(self):
        with _mock_config({"ai.ollama.base_url": "http://192.168.1.10:11434"}), \
             patch("ollama.AsyncClient") as mock_cls:
            from old.backend.ai.providers.ollama_provider import OllamaProvider
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
