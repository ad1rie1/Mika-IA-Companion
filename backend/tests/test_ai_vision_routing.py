"""Tests for multimodal routing across providers.

Vision captioning needs to work on every provider we support. Claude
and OpenAI have native multimodal input; Ollama uses an `images` field
on the message and silently drops images when the model isn't vision-
capable. This suite checks each provider builds the right payload.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline.media import MediaAttachment


def _image_attachment() -> MediaAttachment:
    return MediaAttachment(
        name="cat.png",
        media_type="image/png",
        data="aGVsbG8=",  # base64 shape only
        category="image",
    )


class _patched_router:
    """Context manager giving a fresh ``AIRouter`` with VISION_CAPTION wired.

    The singleton router's config comes from a user-editable config store;
    tests must not depend on it being populated on disk.
    """

    def __init__(self, role_map):
        self.role_map = role_map

    def __enter__(self):
        from ai.router import AIRouter
        from configs.service import config_service

        declared: dict[str, dict] = {}
        role_config: dict[str, str] = {}
        for role, (provider, model) in self.role_map.items():
            internal = f"{role.value}-test"
            declared[internal] = {
                "provider": provider, "model_id": model, "temperature": 0.7,
            }
            role_config[f"ai.role.{role.value}"] = internal

        real_get = config_service.get

        def _fake_get(key, default=""):
            if key in role_config:
                return role_config[key]
            return real_get(key, default=default)

        self._declared_patch = patch("ai.router._load_declared_models", return_value=declared)
        self._config_patch = patch.object(config_service, "get", side_effect=_fake_get)
        self._declared_patch.start()
        self._config_patch.start()
        # Anything raising past this point skips ``__exit__`` entirely, and
        # the patch on ``config_service.get`` then survives for the rest of
        # the session — where the next user of this helper captures the mock
        # as its own ``real_get`` and the chain recurses. That is how one
        # failing test here turned a dozen unrelated ones red.
        try:
            self.router = AIRouter()
        except BaseException:
            self.__exit__()
            raise
        return self.router

    def __exit__(self, *a):
        self._config_patch.stop()
        self._declared_patch.stop()


@pytest.mark.asyncio
class TestClaudeProviderImage:

    async def test_embeds_image_block(self):
        from ai.providers.claude import ClaudeProvider

        provider = ClaudeProvider.__new__(ClaudeProvider)
        provider._client = MagicMock()
        fake_response = MagicMock()
        fake_text_block = MagicMock()
        fake_text_block.type = "text"
        fake_text_block.text = "une image"
        fake_response.content = [fake_text_block]
        provider._client.messages = MagicMock()
        provider._client.messages.create = AsyncMock(return_value=fake_response)

        result = await provider.complete(
            system_prompt="sys", user_prompt="decris",
            model="claude-sonnet", attachments=[_image_attachment()],
        )

        assert result == "une image"
        call_kwargs = provider._client.messages.create.call_args.kwargs
        user_content = call_kwargs["messages"][0]["content"]
        # Two blocks: image + text
        assert isinstance(user_content, list)
        assert user_content[0]["type"] == "image"
        assert user_content[0]["source"]["media_type"] == "image/png"
        assert user_content[0]["source"]["data"] == "aGVsbG8="
        assert user_content[-1]["type"] == "text"
        assert user_content[-1]["text"] == "decris"


@pytest.mark.asyncio
class TestOpenAIProviderImage:

    async def test_embeds_image_url_block(self):
        from ai.providers.openai_provider import OpenAIProvider

        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider._client = MagicMock()
        fake_choice = MagicMock()
        fake_choice.message.content = "une image"
        fake_response = MagicMock(choices=[fake_choice])
        provider._client.chat = MagicMock()
        provider._client.chat.completions = MagicMock()
        provider._client.chat.completions.create = AsyncMock(return_value=fake_response)

        result = await provider.complete(
            system_prompt="sys", user_prompt="decris",
            model="gpt-4o-mini", attachments=[_image_attachment()],
        )

        assert result == "une image"
        call_kwargs = provider._client.chat.completions.create.call_args.kwargs
        user_msg = call_kwargs["messages"][1]  # system is [0], user is [1]
        user_content = user_msg["content"]
        assert isinstance(user_content, list)
        assert user_content[0]["type"] == "image_url"
        assert user_content[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert user_content[-1]["type"] == "text"


@pytest.mark.asyncio
class TestOllamaProviderImage:

    async def test_passes_images_field(self):
        from ai.providers.ollama_provider import OllamaProvider

        provider = OllamaProvider.__new__(OllamaProvider)
        provider._client = MagicMock()
        fake_response = MagicMock()
        fake_response.message.content = "une image"
        provider._client.chat = AsyncMock(return_value=fake_response)

        result = await provider.complete(
            system_prompt="sys", user_prompt="decris",
            model="llava", attachments=[_image_attachment()],
        )

        assert result == "une image"
        call_kwargs = provider._client.chat.call_args.kwargs
        user_msg = call_kwargs["messages"][1]
        # Ollama's SDK takes images as a list of base64 strings.
        assert user_msg["images"] == ["aGVsbG8="]

    async def test_no_images_field_when_no_attachments(self):
        from ai.providers.ollama_provider import OllamaProvider

        provider = OllamaProvider.__new__(OllamaProvider)
        provider._client = MagicMock()
        fake_response = MagicMock()
        fake_response.message.content = "ok"
        provider._client.chat = AsyncMock(return_value=fake_response)

        await provider.complete(
            system_prompt="sys", user_prompt="hi", model="llama3", attachments=None,
        )
        user_msg = provider._client.chat.call_args.kwargs["messages"][1]
        assert "images" not in user_msg


@pytest.mark.asyncio
class TestRouterVisionRole:

    async def test_vision_caption_role_configured(self):
        from ai.router import AIRole
        with _patched_router({AIRole.VISION_CAPTION: ("claude", "claude-haiku-4-5")}) as router:
            provider = router.get_provider_name(AIRole.VISION_CAPTION)
            model = router.get_model(AIRole.VISION_CAPTION)
        assert provider in ("claude", "openai", "ollama")
        assert model  # non-empty

    async def test_attachments_passed_through_to_provider(self):
        """ai_router.complete forwards `attachments` kwarg to the provider."""
        from ai.router import AIRole

        with _patched_router({AIRole.VISION_CAPTION: ("claude", "claude-haiku-4-5")}) as router:
            fake_provider = MagicMock()
            fake_provider.complete = AsyncMock(return_value="caption")
            router._providers[router.get_provider_name(AIRole.VISION_CAPTION)] = fake_provider

            attachments = [_image_attachment()]
            result = await router.complete(
                role=AIRole.VISION_CAPTION,
                system_prompt="sys",
                user_prompt="decris",
                attachments=attachments,
            )
        assert result == "caption"
        passed = fake_provider.complete.call_args.kwargs["attachments"]
        assert passed is attachments
