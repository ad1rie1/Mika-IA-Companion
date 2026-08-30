"""Config schema for the projects subsystem."""
from __future__ import annotations

from configs.types import ConfigGroup, ConfigItem, ConfigSection

CONFIG_SCHEMA = [
    ConfigSection(
        key="projects", label="Projets", icon="◱", order=60,
        family="travail",
        summary="Sa part professionnelle : quand un projet avance seul, et "
                "quand il prend le ton en main.",
        description="Runner des projets agent.",
    ),
    ConfigGroup(
        section="projects", key="Détection en conversation", order=10,
        description="Un message est rattaché à un projet par heuristique — "
                    "titre, mots-clés, propriétaire — sans appel LLM. Le "
                    "rattachement ne fait pas qu'ajouter un bloc au prompt : "
                    "un projet en `emotion_policy=OFF`, ce qui est le défaut à "
                    "la création, bascule le tour en mode professionnel — plus "
                    "de balise [EMOTION:], plus de bloc de variabilité, aucune "
                    "impulsion affective vers la personne.",
    ),
    ConfigGroup(
        section="projects", key="Cadence du runner", order=20,
        description="La boucle dédiée qui fait avancer les projets dus, "
                    "découplée du consolidator pour qu'un `interval:30s` "
                    "tienne vraiment 30 s. Chaque avance est un appel LLM "
                    "complet : ce qui arrive à échéance ensemble est servi par "
                    "priorité, le reste attend le tick suivant.",
    ),
    ConfigGroup(
        section="projects", key="Garde-fous d'autonomie", order=30,
        description="Ce qui empêche un projet mal cadré de tourner tout seul "
                    "indéfiniment, et une avance de fond de monopoliser "
                    "l'unique créneau d'un modèle local pendant que quelqu'un "
                    "attend une réponse.",
    ),
    ConfigGroup(
        section="projects", key="Atelier", order=25,
        description="Un projet est un dossier réel, séparé du moteur, avec de "
                    "quoi le manipuler. C'est la symétrie inverse de la Forge : "
                    "celle-ci est confinée PARCE QU'ELLE tourne dans le "
                    "processus de Mika ; un atelier est capable PARCE QU'IL "
                    "est dehors. Ce que la trousse écrit reste sous la racine, "
                    "toujours.",
    ),
    ConfigGroup(
        section="projects", key="Exécution", order=26,
        description="La frontière retenue est le sous-processus borné : pas de "
                    "shell, exécutables déclarés, dossier verrouillé, "
                    "environnement reconstruit et non hérité (sans quoi un "
                    "script écrit par le modèle recevrait CONFIG_ENCRYPTION_KEY "
                    "et DJANGO_SECRET_KEY), entrée fermée, délai qui tue tout "
                    "le groupe de processus. ⚠ Elle protège de l'accident, pas "
                    "d'un adversaire : le programme lancé tourne avec les "
                    "droits du serveur et peut lire le disque. N'expose pas "
                    "Mika à d'autres personnes tant que c'est ce mode.",
    ),
    ConfigGroup(
        section="projects", key="Traçabilité", order=40, advanced=True,
        description="Le tampon roulant qui garde le prompt envoyé et la "
                    "réponse brute de chaque avance, relisible sur la fiche du "
                    "projet. C'est de l'inspection : on l'ouvre quand un projet "
                    "part de travers, pas pour le régler au quotidien.",
    ),
    ConfigItem(
        key="projects.prompt_history_size", type="int", section="projects",
        group="Traçabilité",
        label="Buffer prompt history",
        default=30, min=0, max=500,
        hint="0 = désactive la capture prompt/response.",
    ),
    ConfigItem(
        key="projects.runner_interval", type="int", section="projects",
        group="Cadence du runner",
        label="Période runner (s)",
        default=30, min=5, max=600, restart_required=True,
        hint="Cadence de la boucle dédiée qui fait avancer les projets dus. "
             "Découplée du consolidator — un interval:30s tient vraiment 30s.",
    ),
    ConfigItem(
        key="projects.max_advances_per_tick", type="int", section="projects",
        group="Cadence du runner",
        label="Projets avancés par tick",
        default=3, min=1, max=20, hot_reload=True,
        hint=(
            "Garde-fou anti-rafale : si une douzaine de projets arrivent à "
            "échéance en même temps, seuls les N premiers (par priorité) "
            "avancent, les autres attendent le tick suivant. Chaque avance "
            "coûte un appel LLM complet."
        ),
    ),
    ConfigItem(
        key="projects.llm_timeout_seconds", type="int", section="projects",
        group="Garde-fous d'autonomie",
        label="Timeout d'une avance (s)",
        default=90, min=5, max=600, hot_reload=True,
        hint=(
            "Second plafond, plus serré : `ai.call_timeout_seconds` (120 s "
            "par défaut) borne déjà le même appel depuis l'intérieur du "
            "routeur. Le mettre au-dessus ne rallonge donc rien — c'est le "
            "plus petit des deux qui décide. Le garder plus bas évite qu'une "
            "avance de fond monopolise l'unique emplacement d'un modèle local "
            "pendant que quelqu'un attend une réponse."
        ),
    ),
    ConfigItem(
        key="projects.runs_since_input_cap", type="int", section="projects",
        group="Garde-fous d'autonomie",
        label="Avances max sans retour humain",
        default=10, min=1, max=100, hot_reload=True,
        hint=(
            "Au-delà, le projet cesse d'être dû jusqu'à ce que quelqu'un "
            "revienne (message, avance manuelle, mise à jour). Sans ce "
            "plafond, un projet mal cadré tourne indéfiniment tout seul en "
            "brûlant des appels."
        ),
    ),
    ConfigItem(
        key="projects.match_confidence_threshold", type="float",
        section="projects", group="Détection en conversation",
        label="Seuil de détection en conversation",
        default=0.4, min=0.0, max=1.0, hot_reload=True,
        hint=(
            "Score minimal (heuristique, sans LLM : titre, mots-clés, "
            "propriétaire) pour qu'un message soit rattaché à un projet. "
            "Attention, ce rattachement ne fait pas qu'ajouter un bloc de "
            "contexte : un projet en `emotion_policy=OFF` bascule le tour en "
            "mode professionnel — plus de tag [EMOTION:], plus de bloc de "
            "variabilité. Baisser le seuil rend Mika plate sur des messages "
            "qui n'ont rien à voir ; le monter lui fait oublier le projet "
            "dont on est en train de lui parler."
        ),
    ),
    # ── Atelier ───────────────────────────────────────────────────
    ConfigItem(
        key="projects.workspace.root", type="str", section="projects",
        group="Atelier", label="Dossier des ateliers",
        default="data/projects", restart_required=True,
        hint="Où vivent les dossiers de travail. Un chemin relatif part de la "
             "racine du dépôt ; un chemin absolu sort les ateliers du dépôt, "
             "ce qui est le bon réglage si tu ne veux pas mélanger le travail "
             "aux données du moteur. Un atelier n'est créé qu'au premier "
             "fichier écrit : un projet qui ne produit rien n'a pas de dossier.",
    ),
    ConfigItem(
        key="projects.workspace.max_file_bytes", type="int", section="projects",
        group="Atelier", label="Taille maximale d'un fichier lu (octets)",
        default=400000, min=1000, max=5000000, hot_reload=True,
        hint="Au-delà, la lecture est tronquée et le dit. Borne ce qu'un "
             "fichier peut occuper dans l'invite du tour suivant.",
    ),
    ConfigItem(
        key="projects.workspace.max_tree_entries", type="int", section="projects",
        group="Atelier", label="Entrées maximum dans une arborescence",
        default=400, min=10, max=5000, hot_reload=True,
        hint="Un dossier de dépendances installées compte des milliers de "
             "fichiers ; les lister noierait la réponse.",
    ),
    ConfigItem(
        key="projects.max_tool_turns_per_advance", type="int", section="projects",
        group="Garde-fous d'autonomie", label="Tours de boucle d'outils par avance",
        default=12, min=1, max=60, hot_reload=True,
        hint="Une avance est devenue une boucle d'outils : à chaque tour le "
             "modèle appelle des outils et relit leurs réponses. Sans borne, "
             "une boucle qui tourne en rond consomme un budget entier sur un "
             "seul tick. Le défaut des providers est 10 ; un projet en demande "
             "un peu plus, parce que lire un fichier avant de l'éditer coûte "
             "déjà deux tours.",
    ),

    # ── Exécution ─────────────────────────────────────────────────
    ConfigItem(
        key="projects.exec.allowed_commands", type="list", section="projects",
        group="Exécution", label="Exécutables autorisés",
        default=["python", "python3", "pytest", "node", "npm", "npx", "git",
                 "ls", "cat", "head", "tail", "wc", "grep", "find",
                 "mkdir", "cp", "mv"],
        hot_reload=True,
        hint="Comparé au nom du programme, jamais au chemin complet. Tout ce "
             "qui n'est pas dans la liste est refusé, et le refus dit au "
             "modèle ce qui est disponible.",
    ),
    ConfigItem(
        key="projects.exec.timeout_seconds", type="int", section="projects",
        group="Exécution", label="Délai d'une commande (s)",
        default=120, min=1, max=1800, hot_reload=True,
        hint="À l'échéance, c'est tout le groupe de processus qui est tué — "
             "tuer le seul enfant laisserait ses petits-enfants tourner.",
    ),
    ConfigItem(
        key="projects.exec.max_output_chars", type="int", section="projects",
        group="Exécution", label="Sortie maximale d'une commande",
        default=20000, min=200, max=200000, hot_reload=True,
        hint="Le début et la fin sont gardés, le milieu coupé — c'est aux deux "
             "bouts que se lit un échec de test.",
    ),
    ConfigItem(
        key="projects.exec.block_network", type="bool", section="projects",
        group="Exécution", label="Couper le réseau des commandes",
        default=True, hot_reload=True,
        hint="Utilise `unshare -rn` quand la machine le permet. Si le noyau "
             "refuse les espaces de noms, la coupure N'A PAS LIEU et la "
             "commande le signale plutôt que de le taire.",
    ),
]
