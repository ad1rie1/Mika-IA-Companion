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
from ai.quota import (
    current_project_id,
    estimate_tokens_from_chars,
    quota_tracker,
    _take_usage,
)

logger = logging.getLogger(__name__)


class AIRole(str, Enum):
    """Each distinct AI function in the system."""

    CONVERSATION = "conversation"
    CONVERSATION_TOOLS = "conversation_tools"  # Claude-only (MCP)
    EMAIL_TRIAGE = "email_triage"
    SIGNAL_INTERPRETATION = "signal_interpretation"
    MEMORY_EXTRACTION = "memory_extraction"
    VALIDITY_CHECK = "validity_check"
    # Vision captioning — takes an image attachment and returns a
    # textual description. Used by the vision preprocessor so non-text
    # perceptions can flow through the text pipeline.
    VISION_CAPTION = "vision_caption"


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
        """Read role → provider:model mappings from the config service."""
        from configs.service import config_service

        default_heavy = config_service.get("ai.claude.default_model", default="claude-opus-4-6")
        default_light = config_service.get("ai.claude.light_model", default="claude-sonnet-4-5")

        role_keys = {
            AIRole.CONVERSATION:          ("ai.role.conversation",          f"claude:{default_heavy}"),
            AIRole.CONVERSATION_TOOLS:    ("ai.role.conversation_tools",    f"claude:{default_heavy}"),
            AIRole.EMAIL_TRIAGE:          ("ai.role.email_triage",          f"claude:{default_light}"),
            AIRole.SIGNAL_INTERPRETATION: ("ai.role.signal_interpretation", f"claude:{default_light}"),
            AIRole.MEMORY_EXTRACTION:     ("ai.role.memory_extraction",     f"claude:{default_light}"),
            AIRole.VALIDITY_CHECK:        ("ai.role.validity_check",        f"claude:{default_light}"),
            # Vision defaults to Claude because other providers' multimodal
            # support in this codebase is limited (see ai/providers/*).
            AIRole.VISION_CAPTION:        ("ai.role.vision_caption",        f"claude:{default_light}"),
        }

        for role, (cfg_key, fallback) in role_keys.items():
            raw = config_service.get(cfg_key, default="") or fallback
            provider_name, model_name = _parse_role_setting(raw)
            self._role_config[role] = (provider_name, model_name)

        # Hot-reload on any ai.role.* change → rebuild role mapping
        config_service.on_change("ai.role.", lambda k, v: self._reload_role(k, v))
        config_service.on_change("ai.claude.default_model", lambda k, v: self._load_config())
        config_service.on_change("ai.claude.light_model",   lambda k, v: self._load_config())

    def _reload_role(self, key: str, value):
        from configs.service import config_service
        role_key = key.split("ai.role.", 1)[-1]
        try:
            role = AIRole(role_key)
        except ValueError:
            return
        raw = config_service.get(key, default="") or ""
        if not raw:
            return
        try:
            self._role_config[role] = _parse_role_setting(raw)
        except Exception:
            logger.exception("Invalid role config %s=%r", key, raw)

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

        # Project attribution (set by ProjectRunner via the context var).
        project_id = current_project_id.get()

        # Pre-call quota enforcement — refuse before we burn the API call.
        # Estimate: prompt tokens + a conservative 512-token reply room.
        expected_in = estimate_tokens_from_chars(prompt_chars)
        expected_total = expected_in + 512
        quota_tracker.check(
            role=role.value,
            project_id=project_id,
            expected_tokens=expected_total,
        )

        logger.debug(
            "AI call START  role=%s provider=%s model=%s prompt_chars=%d project=%s",
            role.value, provider_name, model, prompt_chars, project_id,
        )

        try:
            result = await provider.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                **kwargs,
            )
            elapsed_ms = (time.monotonic() - t0) * 1000

            # Prefer provider-native token counts; fall back to char estimate.
            usage = _take_usage()
            if usage:
                tokens_in = int(usage.get("in", 0))
                tokens_out = int(usage.get("out", 0))
            else:
                tokens_in = expected_in
                tokens_out = estimate_tokens_from_chars(len(result))

            cost_usd = quota_tracker.record(
                role=role.value,
                provider=provider_name,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                project_id=project_id,
            )

            logger.info(
                "AI call OK     role=%-22s provider=%-7s model=%-30s "
                "prompt=%5d chars  response=%5d chars  tok=%d/%d  $%.5f  %7.0f ms",
                role.value, provider_name, model,
                prompt_chars, len(result),
                tokens_in, tokens_out, cost_usd, elapsed_ms,
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
