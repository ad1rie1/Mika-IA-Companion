"""Config schema for the AI subsystem — providers, declared models, role routing, quotas.

Design:

- **ai_providers** only hosts authentication + Ollama base URL. The other
  providers rely on their SDK to pick the endpoint.
- **ai_models** is a ``record_list`` of *declared models*: a row is
  (internal_name, provider, model_id, temperature). The UI fills
  ``model_id`` by querying the provider's SDK — the user never types a
  model name.
- **ai_roles** references a declared model by its ``internal_name``.
  The dashboard API injects the currently-declared names as ``choices``
  at render time so the field is always a typed dropdown.
"""
from __future__ import annotations

from configs.types import ConfigItem, ConfigRecord, ConfigSection, record_item

PROVIDERS = ("claude", "openai", "gemini", "glm", "ollama")

CONFIG_SCHEMA = [
    ConfigSection(
        key="ai_providers", label="IA · Providers", icon="⟠", order=20,
        description=(
            "Clés d'authentification des fournisseurs LLM. "
            "Seul Ollama demande une URL — les SDK officiels "
            "(Anthropic, OpenAI, Gemini) gèrent eux-mêmes leur endpoint."
        ),
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
    # OpenAI
    ConfigItem(
        key="ai.openai.api_key", type="secret", section="ai_providers", group="OpenAI",
        label="API key", env_fallback="OPENAI_API_KEY", sensitive=True,
    ),
    # Gemini (Google)
    ConfigItem(
        key="ai.gemini.api_key", type="secret", section="ai_providers", group="Gemini",
        label="API key", env_fallback="GEMINI_API_KEY", sensitive=True,
        hint="Obtenable depuis Google AI Studio.",
    ),
    # GLM (Zhipu AI)
    ConfigItem(
        key="ai.glm.api_key", type="secret", section="ai_providers", group="GLM",
        label="API key", env_fallback="GLM_API_KEY", sensitive=True,
        hint="Obtenable depuis open.bigmodel.cn. Endpoint OpenAI-compatible.",
    ),
    # Ollama (seul provider qui a besoin d'une URL côté app)
    ConfigItem(
        key="ai.ollama.base_url", type="str", section="ai_providers", group="Ollama",
        label="Base URL", env_fallback="OLLAMA_BASE_URL", default="http://localhost:11434",
        hint="URL du serveur Ollama (le SDK ne la découvre pas tout seul).",
    ),

    # ── Déclaration des modèles ──────────────────────────────────
    ConfigSection(
        key="ai_models", label="Déclaration des modèles", icon="◈", order=21,
        description=(
            "Catalogue des modèles utilisables par l'application. "
            "Chaque entrée mappe un nom interne (librement choisi) vers "
            "un couple provider/model. Ces noms internes sont ensuite "
            "sélectionnables dans la section IA · Rôles."
        ),
    ),
    ConfigItem(
        key="ai.models", type="record_list", section="ai_models",
        label="Modèles déclarés",
        hint=(
            "Ajouter un modèle : choisir le provider → charger la liste "
            "via le SDK / l'API → sélectionner → nommer."
        ),
        record=ConfigRecord(
            name="model_declaration",
            label="Modèle",
            fields=(
                record_item(
                    key="internal_name", type="str", label="Nom interne",
                    hint="Identifiant libre utilisé par les rôles (ex. fast-chat, vision-smart).",
                ),
                record_item(
                    key="provider", type="select", label="Fournisseur",
                    choices=PROVIDERS,
                ),
                record_item(
                    key="model_id", type="str", label="Modèle",
                    hint="Rempli automatiquement depuis le provider.",
                ),
                record_item(
                    key="temperature", type="float", label="Température",
                    default=0.7, min=0.0, max=2.0,
                ),
            ),
        ),
    ),

    # ── Rôles ─────────────────────────────────────────────────────
    # type=select : les choix sont injectés dynamiquement à partir de
    # ai.models par le handler /dashboard/api/config/schema.
    ConfigSection(
        key="ai_roles", label="IA · Rôles", icon="⟰", order=22,
        description="Associe chaque rôle à un modèle déclaré (par son nom interne).",
    ),
    ConfigItem(
        key="ai.role.conversation", type="select", section="ai_roles",
        label="Conversation", env_fallback="AI_ROLE_CONVERSATION",
        hint="Rôle principal utilisé pour parler à l'utilisateur.",
    ),
    ConfigItem(
        key="ai.role.conversation_tools", type="select", section="ai_roles",
        label="Conversation (avec outils MCP)", env_fallback="AI_ROLE_CONVERSATION_TOOLS",
        hint="Doit pointer sur un modèle Claude (seul provider MCP-capable).",
    ),
    ConfigItem(
        key="ai.role.email_triage", type="select", section="ai_roles",
        label="Triage email", env_fallback="AI_ROLE_EMAIL_TRIAGE",
    ),
    ConfigItem(
        key="ai.role.signal_interpretation", type="select", section="ai_roles",
        label="Interprétation signaux", env_fallback="AI_ROLE_SIGNAL_INTERPRETATION",
    ),
    ConfigItem(
        key="ai.role.memory_extraction", type="select", section="ai_roles",
        label="Extraction mémoire", env_fallback="AI_ROLE_MEMORY_EXTRACTION",
    ),
    ConfigItem(
        key="ai.role.validity_check", type="select", section="ai_roles",
        label="Validation connaissances", env_fallback="AI_ROLE_VALIDITY_CHECK",
    ),
    ConfigItem(
        key="ai.role.vision_caption", type="select", section="ai_roles",
        label="Caption vision", env_fallback="AI_ROLE_VISION_CAPTION",
        hint="Modèle multimodal requis.",
    ),

    ConfigSection(
        key="ai_quota", label="IA · Quotas", icon="⌁", order=23,
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
