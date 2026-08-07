"""Config schema for the AI subsystem — providers, declared models, role routing, quotas.

Design:

- **ai_providers** only hosts authentication + Ollama base URL. The other
  providers rely on their SDK to pick the endpoint.
- **ai_models** is a ``record_list`` of *declared models*: a row is
  (internal_name, provider, model_id, temperature). The UI fills
  ``model_id`` by querying the provider's SDK — the user never types a
  model name (voir GestionSysteme/choices.py).
- **ai_roles** references a declared model by its ``internal_name``.
  GestionSystème injects the currently-declared names as ``choices``
  at render time so the field is always a typed dropdown.
"""
from __future__ import annotations

from configs.types import ConfigItem, ConfigRecord, ConfigSection, record_item

# Valeurs = clés de ``ai.router._PROVIDER_CLASSES``. Forme (valeur, libellé) :
# « ollama_cloud » dans une liste déroulante ne dit pas de quoi il s'agit.
PROVIDERS = (
    ("claude", "Claude (Anthropic)"),
    ("openai", "OpenAI"),
    ("gemini", "Gemini (Google)"),
    ("glm", "GLM (Zhipu)"),
    ("ollama", "Ollama (local)"),
    ("ollama_cloud", "Ollama Cloud"),
)

# Partie commune de l'explication du plafond de concurrence. Le « pourquoi »
# diffère d'un provider à l'autre, le « quoi » non.
_CONCURRENCY_HINT = (
    "Nombre maximal d'appels IA simultanés vers ce provider ; 0 = illimité. "
    "Le routeur réserve un créneau avant chaque appel, et l'attente est "
    "comptée *dans* le timeout de l'appel plutôt qu'ajoutée à côté. Les "
    "émetteurs sont nombreux et chacun sur sa propre cadence — conversation, "
    "conscience, consolidateur, sommeil, projets, cron des modules, voix "
    "intérieure — et seule la conversation passe par la file des tours. "
)


def _concurrency_item(provider: str, group: str, *, default: int,
                      maximum: int, hint: str) -> ConfigItem:
    """Plafond d'appels simultanés, déclaré pour *tous* les providers.

    Le réglage n'appartient pas au seul Ollama : ce qui lui est propre,
    c'est le défaut (1) et sa raison — un serveur local met les appels en
    file au lieu de les paralléliser, donc la concurrence n'y achète rien
    et transforme « lent » en « échoué ». Chez un hébergé le parallélisme
    est réel, mais il est facturé et contingenté : sans ce champ il n'y
    aurait aucun moyen de tenir la limite de débit d'un fournisseur, qu'une
    rafale de boucles de fond peut dépasser à elle seule. D'où le même
    champ partout, avec un défaut qui préserve le comportement existant.
    """
    return ConfigItem(
        key=f"ai.{provider}.max_concurrent_calls", type="int",
        section="ai_providers", group=group,
        label="Appels simultanés autorisés",
        default=default, min=0, max=maximum, restart_required=True,
        hint=_CONCURRENCY_HINT + hint,
    )


_HOSTED_CONCURRENCY_HINT = (
    "Illimité par défaut : le parallélisme y est réel, et rien ne gagne à "
    "sérialiser des appels qui tournent vraiment de front. À plafonner pour "
    "tenir la limite de débit du fournisseur ou lisser la dépense — 3 est "
    "un point de départ raisonnable. Un appel qui attend un créneau "
    "consomme son propre timeout : plafonner trop bas fait échouer des "
    "tours au lieu de les ralentir."
)

CONFIG_SCHEMA = [
    ConfigSection(
        key="ai_providers", label="IA · Providers", icon="⟠", order=20,
        description=(
            "Clés d'authentification des fournisseurs LLM. "
            "Seules les deux variantes d'Ollama demandent une URL — les SDK "
            "officiels (Anthropic, OpenAI, Gemini) gèrent eux-mêmes leur "
            "endpoint."
        ),
    ),
    # Claude
    ConfigItem(
        key="ai.claude.oauth_token", type="secret", section="ai_providers", group="Claude",
        label="OAuth token", sensitive=True,
        hot_reload=True,
        hint="Jeton Claude.ai (commence par sk-ant-oat01-).",
    ),
    ConfigItem(
        key="ai.claude.api_key", type="secret", section="ai_providers", group="Claude",
        label="API key (fallback)", sensitive=True,
        hot_reload=True,
        hint="Requis uniquement si pas d'OAuth token.",
    ),
    _concurrency_item("claude", "Claude", default=0, maximum=64,
                      hint=_HOSTED_CONCURRENCY_HINT),
    # OpenAI
    ConfigItem(
        key="ai.openai.api_key", type="secret", section="ai_providers", group="OpenAI",
        label="API key", sensitive=True,
        hot_reload=True,
    ),
    _concurrency_item("openai", "OpenAI", default=0, maximum=64,
                      hint=_HOSTED_CONCURRENCY_HINT),
    # Gemini (Google)
    ConfigItem(
        key="ai.gemini.api_key", type="secret", section="ai_providers", group="Gemini",
        label="API key", sensitive=True,
        hot_reload=True,
        hint="Obtenable depuis Google AI Studio.",
    ),
    _concurrency_item("gemini", "Gemini", default=0, maximum=64,
                      hint=_HOSTED_CONCURRENCY_HINT),
    # GLM (Zhipu AI)
    ConfigItem(
        key="ai.glm.api_key", type="secret", section="ai_providers", group="GLM",
        label="API key", sensitive=True,
        hot_reload=True,
        hint="Obtenable depuis open.bigmodel.cn. Endpoint OpenAI-compatible.",
    ),
    _concurrency_item("glm", "GLM", default=0, maximum=64,
                      hint=_HOSTED_CONCURRENCY_HINT),
    # Ollama (seul provider qui a besoin d'une URL côté app)
    ConfigItem(
        key="ai.ollama.base_url", type="str", section="ai_providers", group="Ollama",
        label="Base URL", default="http://localhost:11434",
        hot_reload=True,
        hint="URL du serveur Ollama (le SDK ne la découvre pas tout seul).",
    ),
    ConfigItem(
        key="ai.ollama.thinking", type="bool", section="ai_providers", group="Ollama",
        label="Raisonnement visible (thinking)", default=False,
        hot_reload=True,
        hint=(
            "Les modèles à raisonnement (gemma4, qwen3, deepseek-r1…) "
            "réfléchissent par défaut, et le raisonnement est facturé en "
            "temps de génération avant le premier mot de la réponse. Mesuré "
            "sur gemma4:12b, un simple « coucou » passe de 1,5 s à 27 s. "
            "Laisser désactivé pour une conversation ; à activer seulement "
            "si la qualité le justifie et que le timeout suit."
        ),
    ),
    ConfigItem(
        key="ai.ollama.max_reply_tokens", type="int", section="ai_providers",
        group="Ollama", label="Longueur max d'une réponse (tokens)",
        default=768, min=64, max=8192,
        hot_reload=True,
        hint=(
            "Plafond de génération par tour. Sans lui, un modèle qui ne "
            "s'arrête pas génère jusqu'à 4096 tokens : à 19 tokens/s c'est "
            "219 s, soit bien au-delà du timeout, et le tour échoue toujours."
        ),
    ),
    _concurrency_item(
        "ollama", "Ollama", default=1, maximum=8,
        hint=(
            "Le seul provider plafonné par défaut, parce que le parallélisme "
            "y est faux : un serveur local n'a qu'un emplacement d'exécution, "
            "deux appels n'y tournent pas de front, ils font la queue — et "
            "cette queue-là, personne ne la mesure. Garder 1 pour qu'un tour "
            "de conversation n'attende pas derrière deux générations de fond. "
            "À monter seulement si le serveur sert vraiment plusieurs "
            "requêtes en parallèle (OLLAMA_NUM_PARALLEL, VRAM suffisante pour "
            "garder le modèle chargé)."
        ),
    ),

    # Ollama Cloud — même protocole, autre machine, autres identifiants.
    # Provider distinct plutôt que clé greffée sur le local : les deux se
    # déclarent en même temps (un petit modèle local sur « voix intérieure »,
    # un gros modèle hébergé sur « conversation »), et les plafonds du local
    # sont calibrés pour une carte graphique, pas pour un serveur.
    ConfigItem(
        key="ai.ollama_cloud.api_key", type="secret", section="ai_providers",
        group="Ollama Cloud", label="API key", sensitive=True,
        hot_reload=True,
        hint="À créer sur ollama.com/settings/keys.",
    ),
    ConfigItem(
        key="ai.ollama_cloud.base_url", type="str", section="ai_providers",
        group="Ollama Cloud", label="Base URL", default="https://ollama.com",
        hot_reload=True,
        hint=(
            "Endpoint hébergé. Les identifiants de modèles y sont sans "
            "suffixe (gpt-oss:120b, kimi-k3, glm-5.2) : le suffixe « -cloud » "
            "appartient à l'autre montage, celui où un Ollama local relaie "
            "vers le cloud."
        ),
    ),
    ConfigItem(
        key="ai.ollama_cloud.thinking", type="bool", section="ai_providers",
        group="Ollama Cloud", label="Raisonnement visible (thinking)",
        default=False, hot_reload=True,
        hint=(
            "Désactivé par défaut comme en local, mais pour une autre raison : "
            "ici le raisonnement coûte du quota plutôt que des secondes. "
            "L'activer est jouable si la qualité le justifie."
        ),
    ),
    ConfigItem(
        key="ai.ollama_cloud.max_reply_tokens", type="int", section="ai_providers",
        group="Ollama Cloud", label="Longueur max d'une réponse (tokens)",
        default=2048, min=64, max=8192,
        hot_reload=True,
        hint=(
            "Plus haut qu'en local (768) : le plafond local est une ceinture "
            "contre un modèle qui génère à 19 tokens/s et ne finit jamais "
            "dans le timeout — contrainte qui n'existe pas côté hébergé."
        ),
    ),
    _concurrency_item(
        "ollama_cloud", "Ollama Cloud", default=0, maximum=64,
        hint=(
            _HOSTED_CONCURRENCY_HINT
            + " Le plafond du local (1) n'a aucune raison de s'appliquer "
              "ici : deux machines, deux catalogues, deux budgets."
        ),
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
    # ai.models par GestionSysteme.views.config._inject_dynamic_choices.
    ConfigSection(
        key="ai_roles", label="IA · Rôles", icon="⟰", order=22,
        description="Associe chaque rôle à un modèle déclaré (par son nom interne).",
    ),
    ConfigItem(
        key="ai.role.conversation", type="select", section="ai_roles",
        label="Conversation",
        hint="Rôle principal utilisé pour parler à l'utilisateur.",
    ),
    ConfigItem(
        key="ai.role.conversation_tools", type="select", section="ai_roles",
        label="Conversation (avec outils MCP)",
        hint="Doit pointer sur un modèle Claude (seul provider MCP-capable).",
    ),
    ConfigItem(
        key="ai.role.email_triage", type="select", section="ai_roles",
        label="Triage email",
    ),
    ConfigItem(
        key="ai.role.signal_interpretation", type="select", section="ai_roles",
        label="Interprétation signaux",
    ),
    ConfigItem(
        key="ai.role.memory_extraction", type="select", section="ai_roles",
        label="Extraction mémoire",
    ),
    ConfigItem(
        key="ai.role.validity_check", type="select", section="ai_roles",
        label="Validation connaissances",
    ),
    ConfigItem(
        key="ai.role.vision_caption", type="select", section="ai_roles",
        label="Caption vision",
        hint="Modèle multimodal requis.",
    ),
    ConfigItem(
        key="ai.role.inner_voice", type="select", section="ai_roles",
        label="Voix intérieure",
        hint="Pensées murmurées. Appelé souvent — garde un petit modèle.",
    ),

    ConfigSection(
        key="ai_quota", label="IA · Quotas", icon="⌁", order=23,
        description="Plafonds tokens, 0 = illimité.",
    ),
    ConfigItem(
        key="ai.quota.daily_tokens", type="int", section="ai_quota",
        label="Plafond journalier (tokens)",
        default=0, min=0, hot_reload=True,
    ),
    ConfigItem(
        key="ai.quota.monthly_tokens", type="int", section="ai_quota",
        label="Plafond mensuel (tokens)",
        default=0, min=0, hot_reload=True,
    ),
    ConfigItem(
        key="ai.call_timeout_seconds", type="int", section="ai_quota",
        label="Timeout appel IA (s)",
        description=(
            "Borne de TOUT appel IA routé — conversation, triage email, "
            "extraction mémoire, vision, boucles de fond. Au-delà, l'appel "
            "est abandonné (le tour de conversation rend un texte de repli). "
            "Un modèle local paie l'intégralité du prompt à chaque tour "
            "d'outils : 60 s suffisent à une API distante, pas à un 12B qui "
            "réfléchit avant de parler."
        ),
        default=120, min=5, max=600, hot_reload=True,
    ),
    ConfigItem(
        key="pipeline.turn_workers", type="int", section="ai_quota",
        label="Tours de conversation en parallèle",
        description=(
            "Nombre de tours traités simultanément par la file. Garder 1 "
            "devant un modèle local : un serveur à un seul emplacement "
            "d'exécution ne les traite pas en parallèle, il les met en "
            "attente, et chacun bloque celui qui l'attend. Au-delà de 1, "
            "deux personnes peuvent être servies en même temps — utile "
            "seulement derrière une API distante."
        ),
        default=1, min=1, max=8, restart_required=True,
    ),

    ConfigSection(
        key="ai_tools", label="IA · Outils", icon="⚒", order=24,
        description=(
            "Quels modules exposent leurs outils dans une conversation. "
            "Chaque schéma d'outil est renvoyé au modèle à chaque tour : "
            "c'est du prompt payé en entier, à chaque fois."
        ),
    ),
    ConfigItem(
        key="ai.conversation_tool_modules", type="list", section="ai_tools",
        label="Modules outillés en conversation",
        description=(
            "Vide = tous les modules démarrés. Sinon, liste blanche de noms "
            "de modules. Les outils des autres restent utilisables ailleurs "
            "(conscience, projets, tâches de fond) — seule la conversation "
            "est allégée."
        ),
        hint=(
            "Un modèle local pousse à réduire : la déclaration des 47 outils "
            "pèse ~6 500 tokens, soit plus de 80 % du prompt d'un simple "
            "« coucou », réévalués à chaque tour de la boucle d'outils."
        ),
        default=(), hot_reload=True,
    ),
]
