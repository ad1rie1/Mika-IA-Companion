"""AI Router — maps function roles to *declared models*.

Each function in the system (conversation, email triage, memory extraction,
etc.) is assigned to a role. A role points to a **declared model** by its
internal name. A declared model is a row of ``ai.models`` config carrying
(internal_name, provider, model_id, temperature).

The UI prevents free-text editing: declared models come from the provider
SDKs, and roles pick only among declared internal names.
"""

from __future__ import annotations

import logging
import time
from enum import Enum

from ai.providers import AIProvider
from ai.providers.claude import ClaudeProvider
from ai.providers.gemini_provider import GeminiProvider
from ai.providers.glm_provider import GLMProvider
from ai.providers.ollama_cloud_provider import OllamaCloudProvider
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
    # Inner monologue — turns "what she's about to do" + "what just came
    # back" into the short murmured reaction she thinks out loud. Small and
    # cheap by design: it fires far more often than a conversation turn.
    INNER_VOICE = "inner_voice"


# Config-key prefixes that carry a provider's credentials. A change under one
# of these evicts that provider's cached instance (see _invalidate_provider).
_PROVIDER_CONFIG_PREFIXES = (
    "ai.claude.", "ai.openai.", "ai.gemini.", "ai.glm.", "ai.ollama.",
    # Distinct from "ai.ollama." — prefix matching is a plain startswith and
    # "ai.ollama_cloud.api_key" does not begin with "ai.ollama.", so the two
    # providers are evicted independently rather than in lockstep.
    "ai.ollama_cloud.",
)

# Maps provider name → class
_PROVIDER_CLASSES: dict[str, type] = {
    "claude": ClaudeProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "glm": GLMProvider,
    "ollama": OllamaProvider,
    "ollama_cloud": OllamaCloudProvider,
}


def _load_declared_models() -> dict[str, dict]:
    """Return {internal_name: {provider, model_id, temperature}} from ai.models rows.

    Disabled rows are excluded — useful to park a model temporarily
    without losing its config.
    """
    from configs.service import config_service
    try:
        rows = config_service.list_rows("ai.models", decrypt_secrets=False)
    except KeyError:
        return {}
    out: dict[str, dict] = {}
    for row in rows:
        if not row.get("enabled", True):
            continue
        payload = row.get("payload") or {}
        name = (payload.get("internal_name") or "").strip()
        if not name:
            continue
        provider = (payload.get("provider") or "").strip().lower()
        model_id = (payload.get("model_id") or "").strip()
        if not provider or not model_id:
            continue
        try:
            temperature = float(payload.get("temperature", 0.7))
        except (TypeError, ValueError):
            temperature = 0.7
        out[name] = {
            "provider": provider,
            "model_id": model_id,
            "temperature": temperature,
        }
    return out


class UnconfiguredRoleError(RuntimeError):
    """Raised when a role is requested but has no valid declared model."""


class AIRouter:
    """Routes AI completion requests to the provider+model of a declared model.

    Providers are instantiated lazily on first use. If a provider's
    dependencies are missing (e.g. openai package not installed),
    the error surfaces only when that provider is actually needed.
    """

    def __init__(self):
        self._providers: dict[str, AIProvider] = {}
        self._role_to_internal: dict[AIRole, str] = {}
        self._load_config()

    # ── Configuration loading ───────────────────────────────────

    def _load_config(self):
        """Read role → internal_name mappings from the config service."""
        from configs.service import config_service

        role_keys = {
            AIRole.CONVERSATION:          "ai.role.conversation",
            AIRole.CONVERSATION_TOOLS:    "ai.role.conversation_tools",
            AIRole.EMAIL_TRIAGE:          "ai.role.email_triage",
            AIRole.SIGNAL_INTERPRETATION: "ai.role.signal_interpretation",
            AIRole.MEMORY_EXTRACTION:     "ai.role.memory_extraction",
            AIRole.VALIDITY_CHECK:        "ai.role.validity_check",
            AIRole.VISION_CAPTION:        "ai.role.vision_caption",
            AIRole.INNER_VOICE:           "ai.role.inner_voice",
        }
        for role, cfg_key in role_keys.items():
            name = (config_service.get(cfg_key, default="") or "").strip()
            if name:
                self._role_to_internal[role] = name

        config_service.on_change("ai.role.", lambda k, v: self._reload_role(k, v))
        # Providers read their credentials once, in __init__, and were cached
        # forever: rotating a leaked API key in the admin returned
        # {"ok": true} while the process kept authenticating with the old one.
        # Evict on any provider-credential change so the next call re-reads.
        for prefix in _PROVIDER_CONFIG_PREFIXES:
            config_service.on_change(
                prefix, lambda k, v, p=prefix: self._invalidate_provider(p, k)
            )

    def _invalidate_provider(self, prefix: str, key: str) -> None:
        """Drop the cached instance whose credentials just changed."""
        provider_name = prefix.removeprefix("ai.").rstrip(".")
        if self._providers.pop(provider_name, None) is not None:
            logger.info(
                "Provider '%s' evicted after %s changed — credentials will be "
                "re-read on the next call", provider_name, key,
            )

    def _reload_role(self, key: str, value):
        role_key = key.split("ai.role.", 1)[-1]
        try:
            role = AIRole(role_key)
        except ValueError:
            return
        self._role_to_internal[role] = (value or "").strip()
        logger.info(
            "AI Router role reloaded: %s → %s",
            role.value, self._role_to_internal[role] or "(vide)",
        )

    # ── Resolution ───────────────────────────────────────────────

    def _resolve(self, role: AIRole) -> tuple[str, str, float, str]:
        """Role → (provider, model_id, temperature, internal_name).

        Raises UnconfiguredRoleError if the role is missing or points to
        an unknown / disabled declared model.
        """
        internal_name = self._role_to_internal.get(role, "").strip()
        if not internal_name:
            raise UnconfiguredRoleError(
                f"Aucun modèle déclaré n'est associé au rôle '{role.value}'. "
                "Déclare un modèle dans Configuration > Déclaration des modèles "
                "puis mappe-le dans IA · Rôles."
            )
        declared = _load_declared_models()
        entry = declared.get(internal_name)
        if entry is None:
            raise UnconfiguredRoleError(
                f"Le rôle '{role.value}' pointe sur '{internal_name}' "
                "qui n'est pas (ou plus) déclaré."
            )
        return entry["provider"], entry["model_id"], entry["temperature"], internal_name

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

    def reset_provider(self, provider_name: str) -> None:
        """Drop a cached provider so the next call re-reads its credentials."""
        self._providers.pop(provider_name, None)

    def provider_by_name(self, provider_name: str) -> AIProvider:
        """Public access to a (cached) provider instance by registry name.

        For capability-specific call sites (e.g. Whisper transcription)
        that need a provider outside the role system. Benefits from the
        same cache + credential-change eviction as role-routed calls.
        Raises when the provider is unknown or its credentials are missing.
        """
        return self._get_provider(provider_name)

    def resolve(self, role: AIRole) -> tuple[str, str, float, str]:
        """Public alias of ``_resolve`` for callers that need provider/model/temp."""
        return self._resolve(role)

    def get_provider(self, role: AIRole) -> AIProvider:
        """Return a (cached, lazily-instantiated) provider instance for ``role``."""
        provider_name, _, _, _ = self._resolve(role)
        return self._get_provider(provider_name)

    def get_model(self, role: AIRole) -> str:
        """Return the model_id configured for a role."""
        _, model, _, _ = self._resolve(role)
        return model

    def get_provider_name(self, role: AIRole) -> str:
        """Return the provider name configured for a role."""
        provider, _, _, _ = self._resolve(role)
        return provider

    # ── Completion ───────────────────────────────────────────────

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
        provider_name, model, temperature, internal_name = self._resolve(role)
        provider = self._get_provider(provider_name)

        # Role-configured temperature wins unless the caller overrides it.
        kwargs.setdefault("temperature", temperature)

        prompt_chars = len(system_prompt) + len(user_prompt)
        t0 = time.monotonic()

        project_id = current_project_id.get()

        expected_in = estimate_tokens_from_chars(prompt_chars)
        expected_total = expected_in + 512
        quota_tracker.check(
            role=role.value,
            project_id=project_id,
            expected_tokens=expected_total,
        )

        logger.debug(
            "AI call START  role=%s internal=%s provider=%s model=%s prompt_chars=%d project=%s",
            role.value, internal_name, provider_name, model, prompt_chars, project_id,
        )

        try:
            result = await provider.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                **kwargs,
            )
            elapsed_ms = (time.monotonic() - t0) * 1000

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
                "AI call OK     role=%-22s internal=%-18s provider=%-7s model=%-30s "
                "prompt=%5d chars  response=%5d chars  tok=%d/%d  $%.5f  %7.0f ms",
                role.value, internal_name, provider_name, model,
                prompt_chars, len(result),
                tokens_in, tokens_out, cost_usd, elapsed_ms,
            )
            return result

        except Exception:
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.error(
                "AI call FAILED role=%-22s internal=%-18s provider=%-7s model=%-30s "
                "prompt=%5d chars  %7.0f ms",
                role.value, internal_name, provider_name, model,
                prompt_chars, elapsed_ms,
            )
            raise


ai_router = AIRouter()
