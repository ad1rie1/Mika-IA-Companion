"""AI Router — maps function roles to provider+model pairs.

Each function in the system (conversation, email triage, memory extraction, etc.)
can be independently assigned to a different AI provider and model via settings.

All AI calls pass through the router, which provides unified logging:
timing, role, provider, model, and response length for every call.
"""

from __future__ import annotations

import logging
import time
from enum import Enum

from django.conf import settings

from ai.providers import AIProvider
from ai.providers.claude import ClaudeProvider
from ai.providers.ollama_provider import OllamaProvider
from ai.providers.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)


class AIRole(str, Enum):
    """Each distinct AI function in the system."""

    CONVERSATION = "conversation"
    CONVERSATION_TOOLS = "conversation_tools"  # Claude-only (MCP)
    EMAIL_TRIAGE = "email_triage"
    SIGNAL_INTERPRETATION = "signal_interpretation"
    MEMORY_EXTRACTION = "memory_extraction"
    VALIDITY_CHECK = "validity_check"


# Maps provider name → class
_PROVIDER_CLASSES: dict[str, type] = {
    "claude": ClaudeProvider,
    "openai": OpenAIProvider,
    "ollama": OllamaProvider,
}


def _parse_role_setting(value: str) -> tuple[str, str]:
    """Parse a 'provider:model' string. Returns (provider_name, model_name)."""
    if ":" not in value:
        raise ValueError(
            f"Format invalide '{value}'. Attendu 'provider:model' "
            f"(ex: 'claude:claude-opus-4-6', 'openai:gpt-4o-mini')"
        )
    provider, model = value.split(":", 1)
    return provider.strip().lower(), model.strip()


class AIRouter:
    """Routes AI completion requests to the appropriate provider+model.

    Providers are instantiated lazily on first use. If a provider's
    dependencies are missing (e.g. openai package not installed),
    the error surfaces only when that provider is actually needed.
    """

    def __init__(self):
        self._providers: dict[str, AIProvider] = {}
        self._role_config: dict[AIRole, tuple[str, str]] = {}
        self._load_config()

    def _load_config(self):
        """Read AI_ROLE_* settings and parse them."""
        role_settings = {
            AIRole.CONVERSATION: getattr(
                settings, "AI_ROLE_CONVERSATION",
                f"claude:{settings.CLAUDE_MODEL}",
            ),
            AIRole.CONVERSATION_TOOLS: getattr(
                settings, "AI_ROLE_CONVERSATION_TOOLS",
                f"claude:{settings.CLAUDE_MODEL}",
            ),
            AIRole.EMAIL_TRIAGE: getattr(
                settings, "AI_ROLE_EMAIL_TRIAGE",
                f"claude:{settings.CLAUDE_MODEL_LIGHT}",
            ),
            AIRole.SIGNAL_INTERPRETATION: getattr(
                settings, "AI_ROLE_SIGNAL_INTERPRETATION",
                f"claude:{settings.CLAUDE_MODEL_LIGHT}",
            ),
            AIRole.MEMORY_EXTRACTION: getattr(
                settings, "AI_ROLE_MEMORY_EXTRACTION",
                f"claude:{settings.CLAUDE_MODEL_LIGHT}",
            ),
            AIRole.VALIDITY_CHECK: getattr(
                settings, "AI_ROLE_VALIDITY_CHECK",
                f"claude:{settings.CLAUDE_MODEL_LIGHT}",
            ),
        }

        for role, value in role_settings.items():
            provider_name, model_name = _parse_role_setting(value)
            self._role_config[role] = (provider_name, model_name)

        configured = {
            role.value: f"{p}:{m}" for role, (p, m) in self._role_config.items()
        }
        logger.info("AI Router configured: %s", configured)

    def _get_provider(self, provider_name: str) -> AIProvider:
        """Get or lazily create a provider instance."""
        if provider_name not in self._providers:
            cls = _PROVIDER_CLASSES.get(provider_name)
            if cls is None:
                available = ", ".join(_PROVIDER_CLASSES.keys())
                raise ValueError(
                    f"Provider inconnu '{provider_name}'. "
                    f"Disponibles : {available}"
                )
            self._providers[provider_name] = cls()
            logger.info("Provider '%s' initialisé", provider_name)
        return self._providers[provider_name]

    def get_model(self, role: AIRole) -> str:
        """Return the model name configured for a role."""
        _, model = self._role_config[role]
        return model

    def get_provider_name(self, role: AIRole) -> str:
        """Return the provider name configured for a role."""
        provider_name, _ = self._role_config[role]
        return provider_name

    async def complete(
        self,
        role: AIRole,
        system_prompt: str,
        user_prompt: str,
        **kwargs,
    ) -> str:
        """Route a completion request to the configured provider+model.

        Wraps every call with unified logging: timing, role, provider,
        model, prompt size, and response size.
        """
        provider_name, model = self._role_config[role]
        provider = self._get_provider(provider_name)

        prompt_chars = len(system_prompt) + len(user_prompt)
        t0 = time.monotonic()

        logger.debug(
            "AI call START  role=%s provider=%s model=%s prompt_chars=%d",
            role.value, provider_name, model, prompt_chars,
        )

        try:
            result = await provider.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                **kwargs,
            )
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.info(
                "AI call OK     role=%-22s provider=%-7s model=%-30s "
                "prompt=%5d chars  response=%5d chars  %7.0f ms",
                role.value, provider_name, model,
                prompt_chars, len(result), elapsed_ms,
            )
            return result

        except Exception:
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.error(
                "AI call FAILED role=%-22s provider=%-7s model=%-30s "
                "prompt=%5d chars  %7.0f ms",
                role.value, provider_name, model,
                prompt_chars, elapsed_ms,
            )
            raise


ai_router = AIRouter()
