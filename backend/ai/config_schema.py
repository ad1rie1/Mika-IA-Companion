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

from configs.types import (
    ConfigGroup, ConfigItem, ConfigRecord, ConfigSection, record_item,
)

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

# Avertissement commun aux trois parts de fenêtre. Elles ne sont pas trois
# réglages indépendants : c'est leur somme qui engage la fenêtre, et rien ne
# l'empêche de dépasser 1.0.
_PART_HINT = (
    "Part de la fenêtre UTILISABLE (fenêtre × part visée − sortie − outils − "
    "marge). Les trois parts — fil 0.60, relationnel 0.04, rappel 0.06 — sont "
    "couplées : elles somment aujourd'hui à 0.70, et les 0.30 restants sont "
    "une réserve délibérée. Rien n'interdit de les faire dépasser 1.0 ; le "
    "budget promet alors plus de place que la fenêtre n'en contient, et le "
    "provider tronque PAR LA TÊTE, c'est-à-dire par la personnalité. Vérifier "
    "la somme des trois avant d'en monter une seule. "
)

CONFIG_SCHEMA = [
    ConfigSection(
        key="ai_providers", label="Providers", icon="⟠", order=20,
        family="intelligence",
        summary="Chez qui elle pense : identifiants, endpoints, appels simultanés.",
        description=(
            "Clés d'authentification des fournisseurs LLM. "
            "Seules les deux variantes d'Ollama demandent une URL — les SDK "
            "officiels (Anthropic, OpenAI, Gemini) gèrent eux-mêmes leur "
            "endpoint."
        ),
    ),
    # ── Organisation de l'écran ─────────────────────────────────────
    #
    # Un bloc par fournisseur : ce ne sont pas six variantes d'un même
    # réglage, ce sont six comptes dont un seul est peut-être ouvert. La
    # description dit ce que ce fournisseur-là sait faire de plus que les
    # autres — c'est ce qui décide à quels rôles on l'attribue ensuite.
    #
    # Aucun n'est replié : un bloc d'identifiants est exactement ce qu'on
    # vient chercher sur cette page, y compris celui qu'on n'a pas encore
    # rempli.
    ConfigGroup(
        section="ai_providers", key="Claude", order=10,
        description="Le seul fournisseur qui met en cache le préfixe stable "
                    "du prompt — personnalité, récit de soi et déclarations "
                    "d'outils sont alors écrits une fois puis relus à ~0,1× "
                    "leur prix. Clé d'API seulement : le passage par un jeton "
                    "OAuth Claude.ai n'existe plus.",
    ),
    ConfigGroup(
        section="ai_providers", key="OpenAI", order=20,
        description="Sert au-delà de la conversation : c'est le seul "
                    "fournisseur déclaré à exposer de la reconnaissance "
                    "vocale, donc c'est cette clé qui transcrit les messages "
                    "audio reçus, quel que soit le modèle qui répondra ensuite.",
    ),
    ConfigGroup(
        section="ai_providers", key="Gemini", order=30,
        description="Fournisseur hébergé multimodal. Rien à renseigner "
                    "d'autre que la clé : le SDK trouve son endpoint seul.",
    ),
    ConfigGroup(
        section="ai_providers", key="GLM", order=40,
        description="Endpoint compatible OpenAI côté Zhipu. Comme les autres "
                    "hébergés, il ne coûte rien à déclarer sans l'utiliser : "
                    "un fournisseur n'est instancié qu'au premier appel d'un "
                    "rôle qui pointe sur lui.",
    ),
    ConfigGroup(
        section="ai_providers", key="Ollama", order=50,
        description="Le serveur local. C'est le seul bloc où la génération "
                    "elle-même se règle — raisonnement et longueur de réponse "
                    "— parce que c'est le seul où le temps de génération "
                    "arrive en face du délai d'un tour au lieu d'une facture.",
    ),
    ConfigGroup(
        section="ai_providers", key="Ollama Cloud", order=60,
        description="Même protocole, autre machine, autre budget : les deux "
                    "Ollama se déclarent en même temps, un petit modèle local "
                    "sur la voix intérieure et un gros modèle hébergé sur la "
                    "conversation. Les plafonds ne sont donc pas partagés — "
                    "la ceinture calibrée pour une carte graphique tronquerait "
                    "un modèle hébergé.",
    ),
    # Claude
    ConfigItem(
        key="ai.claude.api_key", type="secret", section="ai_providers", group="Claude",
        label="Clé d'API", sensitive=True,
        hot_reload=True,
        hint=(
            "Clé Anthropic (commence par sk-ant-api). Seul mode "
            "d'authentification accepté : les jetons OAuth Claude.ai "
            "passaient par un sous-processus CLI qu'Anthropic ne supporte "
            "plus."
        ),
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
        key="ai_models", label="Modèles", icon="◈", order=21,
        family="intelligence",
        summary="Le catalogue : quel modèle, chez quel fournisseur, sous quel nom interne.",
        description=(
            "Catalogue des modèles utilisables par l'application. "
            "Chaque entrée mappe un nom interne (librement choisi) vers "
            "un couple provider/model. Ces noms internes sont ensuite "
            "sélectionnables dans la section IA · Rôles."
        ),
    ),
    ConfigGroup(
        section="ai_models", key="Catalogue", order=10,
        description="Rien ne tourne tant que cette liste est vide : les rôles "
                    "ne choisissent pas un modèle, ils choisissent un nom "
                    "déclaré ici. Une ligne porte aussi sa fenêtre de contexte "
                    "et sa réserve de sortie, qui dimensionnent tout le budget "
                    "du prompt — laissée à 0, la fenêtre est devinée d'après "
                    "l'identifiant du modèle.",
    ),
    ConfigItem(
        key="ai.models", type="record_list", section="ai_models",
        group="Catalogue",
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
                record_item(
                    key="max_tokens", type="int", label="Max tokens (réponse)",
                    default=4096, min=256, max=64000,
                    hint=(
                        "Plafond de génération par appel pour ce modèle. "
                        "Ollama garde en plus sa ceinture locale "
                        "(ai.ollama.max_reply_tokens) : le plus petit gagne."
                    ),
                ),
                record_item(
                    key="context_window", type="int", label="Fenêtre de contexte (tokens)",
                    default=0, min=0, max=2_000_000,
                    hint=(
                        "0 = inconnue : les plafonds fixes actuels restent "
                        "seuls maîtres. Déclarée, elle dimensionne le budget "
                        "de contexte (historique, rappel mémoire) et le "
                        "seuil de compaction du fil."
                    ),
                ),
            ),
        ),
    ),

    # ── Rôles ─────────────────────────────────────────────────────
    # type=select : les choix sont injectés dynamiquement à partir de
    # ai.models par GestionSysteme.views.config._inject_dynamic_choices.
    ConfigSection(
        key="ai_roles", label="Rôles", icon="⟰", order=22,
        family="intelligence",
        summary="Quel modèle déclaré répond à quoi — parler, retenir, percevoir, penser tout bas.",
        description="Associe chaque rôle à un modèle déclaré (par son nom interne).",
    ),
    # ── Organisation de l'écran ─────────────────────────────────────
    #
    # Les dix rôles ne se valent pas : deux tiennent la conversation, les
    # autres tournent en fond, à des cadences et pour des budgets qui n'ont
    # rien à voir. Regroupés par ce qu'ils font tourner, pas par ordre
    # d'apparition dans l'énumération.
    ConfigGroup(
        section="ai_roles", key="Conversation", order=10,
        description="Ce qui répond quand quelqu'un parle. C'est le seul "
                    "endroit où la latence se voit : tout le reste tourne en "
                    "fond, où un appel lent ne coûte qu'un tick.",
    ),
    ConfigGroup(
        section="ai_roles", key="Mémoire & consolidation", order=20,
        description="Ce que la boucle de fond fait de ce qui a été dit : en "
                    "tirer des souvenirs et des connaissances, vérifier "
                    "celles que la suite contredit, replier le fil trop long "
                    "en résumé. Aucun de ces appels n'est attendu par "
                    "quelqu'un — un petit modèle y est un bon choix.",
    ),
    ConfigGroup(
        section="ai_roles", key="Perception", order=30,
        description="Ce qui transforme un stimulus en texte qu'elle peut "
                    "lire : décrire une image, classer un signal reçu, trier "
                    "un mail. L'interprétation des signaux est appelée sur "
                    "chaque événement qui n'a pas de raccourci, donc souvent.",
    ),
    ConfigGroup(
        section="ai_roles", key="Voix intérieure", order=40,
        description="Le murmure qui accompagne une initiative — « oh tiens, "
                    "si j'envoyais un message à Alice… ». Il est fabriqué "
                    "à chaque fois, jamais recyclé, et un échec se solde par "
                    "du silence : garde un petit modèle.",
    ),
    ConfigItem(
        key="ai.role.conversation", type="select", section="ai_roles",
        group="Conversation",
        label="Conversation",
        hint="Rôle principal utilisé pour parler à l'utilisateur.",
    ),
    ConfigItem(
        key="ai.role.conversation_tools", type="select", section="ai_roles",
        group="Conversation",
        label="Conversation (avec outils MCP)",
        hint="Doit pointer sur un modèle Claude (seul provider MCP-capable).",
    ),
    ConfigItem(
        key="ai.role.preparation", type="select", section="ai_roles",
        group="Conversation",
        label="Préparation (rappel dirigé)",
        hint="Pré-passe qui planifie les recherches mémoire avant la réponse. "
             "Petit modèle rapide (Haiku). Non mappé = désactivée — "
             "recommandé derrière un modèle local lent.",
    ),
    ConfigItem(
        key="ai.role.memory_extraction", type="select", section="ai_roles",
        group="Mémoire & consolidation",
        label="Extraction mémoire",
    ),
    ConfigItem(
        key="ai.role.validity_check", type="select", section="ai_roles",
        group="Mémoire & consolidation",
        label="Validation connaissances",
    ),
    ConfigItem(
        key="ai.role.compaction", type="select", section="ai_roles",
        group="Mémoire & consolidation",
        label="Compaction du fil",
        hint="Résumé roulant de la conversation, hors tour. Petit modèle. "
             "Non mappé = désactivée (l'historique reste borné en nombre).",
    ),
    ConfigItem(
        key="ai.role.vision_caption", type="select", section="ai_roles",
        group="Perception",
        label="Caption vision",
        hint="Modèle multimodal requis.",
    ),
    ConfigItem(
        key="ai.role.signal_interpretation", type="select", section="ai_roles",
        group="Perception",
        label="Interprétation signaux",
    ),
    ConfigItem(
        key="ai.role.email_triage", type="select", section="ai_roles",
        group="Perception",
        label="Triage email",
    ),
    ConfigItem(
        key="ai.role.inner_voice", type="select", section="ai_roles",
        group="Voix intérieure",
        label="Voix intérieure",
        hint="Pensées murmurées. Appelé souvent — garde un petit modèle.",
    ),

    ConfigSection(
        key="ai_context", label="Contexte", icon="◫", order=25,
        family="intelligence",
        summary="Ce qui tient dans la fenêtre du modèle, et en quelles proportions.",
        description=(
            "Passe de préparation (rappel dirigé) et gestion de la fenêtre "
            "de contexte."
        ),
    ),
    # ── Organisation de l'écran ─────────────────────────────────────
    #
    # Du plus lisible au plus interne : ce qu'elle va chercher avant de
    # répondre, combien de fenêtre on s'autorise, comment cette fenêtre se
    # partage — puis deux blocs qu'on n'ouvre qu'en diagnostic.
    ConfigGroup(
        section="ai_context", key="Préparation", order=10,
        description="Une pré-passe minuscule qui, avant la réponse, décide "
                    "quoi aller chercher en mémoire et écrit une note de "
                    "focus. Elle court en parallèle du rappel spéculatif et "
                    "n'est jamais attendue : passé son délai, le tour part "
                    "sans elle et ressemble trait pour trait à un tour d'avant.",
    ),
    ConfigGroup(
        section="ai_context", key="Budget", order=20,
        description="Quelle part de la fenêtre du modèle on s'autorise à "
                    "remplir. La fenêtre est un plafond, pas une cible : ce "
                    "qu'on ne dépense pas reste comme marge de session avant "
                    "que la compaction n'ait à replier le fil.",
    ),
    ConfigGroup(
        section="ai_context", key="Répartition du contexte", order=30,
        description="Comment la place utilisable se partage entre le fil, ce "
                    "qu'elle sait de la personne et ce qu'elle se rappelle. "
                    "C'est leur SOMME qui engage la fenêtre, et rien ne "
                    "l'empêche de dépasser 1,0 : le budget promet alors plus "
                    "de place qu'il n'y en a, et le fournisseur tronque par la "
                    "tête, c'est-à-dire par la personnalité.",
    ),
    ConfigGroup(
        section="ai_context", key="Rendu du fil", order=40, advanced=True,
        description="Deux ceintures sur ce qui part réellement sur le réseau : "
                    "un message d'historique démesuré (un collage de 50 ko) et "
                    "un résumé roulant qui grossirait au point de manger la "
                    "part du fil vivant. Le tampon court terme, lui, ne "
                    "plafonne que le NOMBRE de messages.",
    ),
    ConfigGroup(
        section="ai_context", key="Calibration jetons", order=50, advanced=True,
        description="Il n'y a pas de tokenizer dans le processus : la taille "
                    "d'un prompt est estimée par un ratio caractères→jetons "
                    "qu'une moyenne mobile corrige à partir des appels réels, "
                    "par fournisseur. On n'y touche que si le budget se "
                    "trompe visiblement de volume.",
    ),
    ConfigItem(
        key="ai.preparation.deadline_ms", type="int", section="ai_context",
        group="Préparation", label="Deadline du plan (ms)",
        default=1500, min=300, max=5000, hot_reload=True,
        hint="La réponse n'attend JAMAIS la réflexion au-delà : passé ce "
             "délai, le tour part avec le rappel spéculatif seul.",
    ),
    ConfigItem(
        key="ai.preparation.min_chars", type="int", section="ai_context",
        group="Préparation", label="Longueur minimale du message",
        default=20, min=0, max=200, hot_reload=True,
        hint="Sous ce seuil (et sans « ? »), pas de passe — le small talk "
             "garde sa latence actuelle.",
    ),
    ConfigItem(
        key="ai.preparation.max_rappels", type="int", section="ai_context",
        group="Préparation", label="Rappels max par plan",
        default=3, min=1, max=5, hot_reload=True,
    ),
    ConfigItem(
        key="ai.context.usage_ratio", type="float", section="ai_context",
        group="Budget", label="Part de fenêtre visée",
        default=0.5, min=0.1, max=0.95, hot_reload=True,
        hint="La fenêtre est un plafond, pas une cible : 0.5 borne le coût "
             "du pire tour et laisse l'autre moitié comme marge de session "
             "avant compaction.",
    ),
    ConfigItem(
        key="ai.context.default_window", type="int", section="ai_context",
        group="Budget", label="Fenêtre de repli (tokens)",
        default=16384, min=2048, max=2_000_000, hot_reload=True,
        hint="Utilisée quand le modèle déclaré n'a pas de context_window : "
             "la compaction du fil garde ainsi toujours un seuil.",
    ),

    # ── Répartition du contexte ──────────────────────────────────
    # Les trois parts sont un seul réglage en trois champs : c'est leur
    # SOMME qui engage la fenêtre. D'où un avertissement identique sur
    # chacune — un opérateur qui n'en monte qu'une ne voit que celle-là.
    ConfigItem(
        key="ai.context.l3_history_share", type="float", section="ai_context",
        group="Répartition du contexte", label="Part du fil de conversation",
        default=0.60, min=0.0, max=1.0, hot_reload=True,
        hint=_PART_HINT + "Couche L3 : verbatim du fil + résumé roulant. "
             "C'est la part la plus grosse, et celle qui dimensionne aussi le "
             "seuil de compaction — les deux lisent le même budget.",
    ),
    ConfigItem(
        key="ai.context.l2_relational_share", type="float", section="ai_context",
        group="Répartition du contexte", label="Part du contexte relationnel",
        default=0.04, min=0.0, max=1.0, hot_reload=True,
        hint=_PART_HINT + "Couche L2 : profil de la personne, engagements en "
             "cours, historique émotionnel.",
    ),
    ConfigItem(
        key="ai.context.l5_recall_share", type="float", section="ai_context",
        group="Répartition du contexte", label="Part du rappel mémoire",
        default=0.06, min=0.0, max=1.0, hot_reload=True,
        hint=_PART_HINT + "Couche L5 : souvenirs, connaissances et échanges "
             "passés retrouvés par recherche sémantique.",
    ),
    ConfigItem(
        key="ai.context.safety_margin", type="float", section="ai_context",
        group="Répartition du contexte", label="Marge de sécurité",
        default=0.05, min=0.0, max=0.5, hot_reload=True,
        hint=(
            "Fraction de la fenêtre gardée libre, retirée deux fois : du "
            "budget utilisable et de la place physique restante. Elle absorbe "
            "l'écart entre notre estimation caractères→tokens et le "
            "tokenizer réel du provider. La descendre rapproche du bord où "
            "la troncature se fait par la tête."
        ),
    ),
    ConfigItem(
        key="ai.context.default_max_tokens", type="int", section="ai_context",
        group="Répartition du contexte", label="Sortie réservée par défaut (tokens)",
        default=4096, min=256, max=64000, hot_reload=True,
        hint=(
            "Place réservée à la RÉPONSE quand la ligne modèle ne déclare pas "
            "son propre max_tokens : elle est soustraite de la fenêtre avant "
            "toute répartition. Un max_tokens déclaré sur le modèle gagne "
            "toujours."
        ),
    ),
    ConfigItem(
        key="ai.context.l3_floor_chars", type="int", section="ai_context",
        group="Répartition du contexte", label="Plancher du fil (caractères)",
        default=4000, min=500, max=200_000, hot_reload=True,
        hint=(
            "Le fil n'est jamais borné en dessous, quelle que soit la fenêtre "
            "déclarée ou l'illisibilité de la configuration : c'est le cap "
            "historique, devenu plancher. La part ci-dessus le dépasse, elle "
            "ne le remplace pas."
        ),
    ),

    # ── Rendu du fil ─────────────────────────────────────────────
    ConfigItem(
        key="ai.chat.history_msg_max_chars", type="int", section="ai_context",
        group="Rendu du fil", label="Taille max d'un message d'historique",
        default=4000, min=500, max=100_000, hot_reload=True,
        hint=(
            "Le tampon court terme plafonne le NOMBRE de messages, pas leur "
            "taille : un collage de 50 ko entre verbatim et repart sur le "
            "réseau à chaque tour jusqu'à sortir du tampon. 4 000 caractères "
            "(~1 000 tokens) laissent intact n'importe quel message de "
            "conversation réel."
        ),
    ),
    ConfigItem(
        key="ai.chat.summary_max_chars", type="int", section="ai_context",
        group="Rendu du fil", label="Taille max du résumé roulant",
        default=8000, min=500, max=100_000, hot_reload=True,
        hint=(
            "Ceinture sur le résumé de compaction, rendu comme premier tour "
            "user. Le compactor vise bien plus court ; ce plafond existe pour "
            "que le résumé ne puisse jamais manger la part du fil vivant."
        ),
    ),

    # ── Calibration jetons ───────────────────────────────────────
    ConfigItem(
        key="ai.calibration.default_chars_per_token", type="float",
        section="ai_context", group="Calibration jetons",
        label="Caractères par token (valeur initiale)",
        default=4.0, min=1.0, max=12.0, hot_reload=True,
        hint=(
            "Point de départ du ratio, avant que la moyenne mobile n'ait vu "
            "de vrais appels chez ce provider. Le français tourne plutôt "
            "autour de 3,4–3,9 selon le modèle ; 4.0 reste aligné sur "
            "l'estimation du contrôle de quota."
        ),
    ),
    ConfigItem(
        key="ai.calibration.alpha", type="float", section="ai_context",
        group="Calibration jetons", label="Réactivité de la moyenne mobile",
        default=0.2, min=0.01, max=1.0, hot_reload=True,
        hint=(
            "Poids du dernier échantillon dans la moyenne mobile "
            "exponentielle : 1.0 = suit le dernier appel et oublie tout le "
            "reste, 0.01 = ne bouge presque plus. Monter accélère "
            "l'auto-correction après un changement de modèle, au prix du "
            "bruit."
        ),
    ),

    ConfigSection(
        key="ai_quota", label="Quotas", icon="⌁", order=23,
        family="intelligence",
        summary="Ce qu'elle a le droit de dépenser, et le temps qu'un appel a le droit de prendre.",
        description="Plafonds tokens, 0 = illimité.",
    ),
    ConfigGroup(
        section="ai_quota", key="Plafonds de dépense", order=10,
        description="Bornes de consommation, tous rôles confondus. 0 = pas de "
                    "plafond. À poser avant de brancher un modèle hébergé sur "
                    "une conscience qui délibère toutes les trente secondes.",
    ),
    ConfigGroup(
        section="ai_quota", key="Délais et parallélisme", order=20,
        description="Combien de temps un appel a le droit de prendre, et "
                    "combien de tours de conversation avancent de front. Les "
                    "deux se lisent ensemble : c'est le second qui décide si "
                    "une personne attend derrière une autre, et le premier ce "
                    "qui arrive quand l'attente est trop longue — un texte de "
                    "repli, indiscernable d'un modèle simplement lent.",
    ),
    ConfigItem(
        key="ai.quota.daily_tokens", type="int", section="ai_quota",
        group="Plafonds de dépense",
        label="Plafond journalier (tokens)",
        default=0, min=0, hot_reload=True,
    ),
    ConfigItem(
        key="ai.quota.monthly_tokens", type="int", section="ai_quota",
        group="Plafonds de dépense",
        label="Plafond mensuel (tokens)",
        default=0, min=0, hot_reload=True,
    ),
    ConfigItem(
        key="ai.call_timeout_seconds", type="int", section="ai_quota",
        group="Délais et parallélisme",
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
        group="Délais et parallélisme",
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
        key="ai_tools", label="Outils", icon="⚒", order=24,
        family="intelligence",
        summary="Quels modules exposent leurs outils en conversation — une déclaration est du prompt.",
        description=(
            "Quels modules exposent leurs outils dans une conversation. "
            "Chaque schéma d'outil est renvoyé au modèle à chaque tour : "
            "c'est du prompt payé en entier, à chaque fois."
        ),
    ),
    ConfigGroup(
        section="ai_tools", key="Outils en conversation", order=10,
        description="Ce qu'elle peut faire pendant qu'elle parle : chercher "
                    "dans sa mémoire, écrire un module, envoyer un mail. Le "
                    "coût n'est pas dans l'appel de l'outil mais dans sa "
                    "*déclaration*, réécrite à chaque tour de la boucle. "
                    "Restreindre ici n'enlève rien ailleurs — conscience, "
                    "projets et tâches de fond gardent l'outillage complet.",
    ),
    ConfigItem(
        key="ai.conversation_tool_modules", type="list", section="ai_tools",
        group="Outils en conversation",
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
