"""Config schema for the AI subsystem — providers, role routing, quotas."""
from __future__ import annotations

from configs.types import ConfigItem, ConfigSection

PROVIDERS = ("claude", "openai", "ollama")

CONFIG_SCHEMA = [
    ConfigSection(
        key="ai_providers", label="IA · Providers", icon="⟠", order=20,
        description="Clés et endpoints des fournisseurs LLM.",
    ),
    # Claude
    ConfigItem(
        key="ai.claude.oauth_token", type="secret", section="ai_providers", group="Claude",
        label="OAuth token", env_fallback="CLAUDE_OAUTH_TOKEN", sensitive=True,
        hint="Jeton Claude.ai (commence par sk-ant-oat01-).",
    ),
    ConfigItem(
        key="ai.claude.api_key", type="secret", section="ai_providers", group="Claude",
        label="API key (fallback)", env_fallback="ANTHROPIC_API_KEY", sensitive=True,
        hint="Requis uniquement si pas d'OAuth token.",
    ),
    ConfigItem(
        key="ai.claude.default_model", type="str", section="ai_providers", group="Claude",
        label="Modèle principal", env_fallback="CLAUDE_MODEL", default="claude-opus-4-6",
    ),
    ConfigItem(
        key="ai.claude.light_model", type="str", section="ai_providers", group="Claude",
        label="Modèle léger", env_fallback="CLAUDE_MODEL_LIGHT", default="claude-sonnet-4-5",
    ),
    # OpenAI
    ConfigItem(
        key="ai.openai.api_key", type="secret", section="ai_providers", group="OpenAI",
        label="API key", env_fallback="OPENAI_API_KEY", sensitive=True,
    ),
    ConfigItem(
        key="ai.openai.base_url", type="str", section="ai_providers", group="OpenAI",
        label="Base URL", env_fallback="OPENAI_BASE_URL",
        hint="Vide = api.openai.com. Utiliser pour Azure/proxy.",
    ),
    # Ollama
    ConfigItem(
        key="ai.ollama.base_url", type="str", section="ai_providers", group="Ollama",
        label="Base URL", env_fallback="OLLAMA_BASE_URL", default="http://localhost:11434",
    ),

    ConfigSection(
        key="ai_roles", label="IA · Rôles", icon="⟰", order=21,
        description="Mapping rôle → provider:model (ex. claude:claude-opus-4-6).",
    ),
    ConfigItem(
        key="ai.role.conversation", type="str", section="ai_roles",
        label="Conversation", env_fallback="AI_ROLE_CONVERSATION",
        hint="Rôle principal utilisé pour parler à l'utilisateur.",
    ),
    ConfigItem(
        key="ai.role.conversation_tools", type="str", section="ai_roles",
        label="Conversation (avec outils MCP)", env_fallback="AI_ROLE_CONVERSATION_TOOLS",
    ),
    ConfigItem(
        key="ai.role.email_triage", type="str", section="ai_roles",
        label="Triage email", env_fallback="AI_ROLE_EMAIL_TRIAGE",
    ),
    ConfigItem(
        key="ai.role.signal_interpretation", type="str", section="ai_roles",
        label="Interprétation signaux", env_fallback="AI_ROLE_SIGNAL_INTERPRETATION",
    ),
    ConfigItem(
        key="ai.role.memory_extraction", type="str", section="ai_roles",
        label="Extraction mémoire", env_fallback="AI_ROLE_MEMORY_EXTRACTION",
    ),
    ConfigItem(
        key="ai.role.validity_check", type="str", section="ai_roles",
        label="Validation connaissances", env_fallback="AI_ROLE_VALIDITY_CHECK",
    ),
    ConfigItem(
        key="ai.role.vision_caption", type="str", section="ai_roles",
        label="Caption vision", env_fallback="AI_ROLE_VISION_CAPTION",
    ),

    ConfigSection(
        key="ai_quota", label="IA · Quotas", icon="⌁", order=22,
        description="Plafonds tokens, 0 = illimité.",
    ),
    ConfigItem(
        key="ai.quota.daily_tokens", type="int", section="ai_quota",
        label="Plafond journalier (tokens)", env_fallback="AI_QUOTA_DAILY_TOKENS",
        default=0, min=0, hot_reload=True,
    ),
    ConfigItem(
        key="ai.quota.monthly_tokens", type="int", section="ai_quota",
        label="Plafond mensuel (tokens)", env_fallback="AI_QUOTA_MONTHLY_TOKENS",
        default=0, min=0, hot_reload=True,
    ),
    ConfigItem(
        key="ai.call_timeout_seconds", type="int", section="ai_quota",
        label="Timeout appel IA (s)", env_fallback="AI_CALL_TIMEOUT",
        default=60, min=5, max=600, hot_reload=True,
    ),
]
