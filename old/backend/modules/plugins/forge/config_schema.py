"""Config de l'hôte Forge — les limites du bac à sable.

Les sections de config des modules forgés eux-mêmes sont déclarées
dynamiquement (``ForgeModule._register_config``) sous les clés
``forge.<module>.<champ>``.
"""
from __future__ import annotations

from old.backend.configs.types import ConfigGroup, ConfigItem, ConfigSection

CONFIG_SCHEMA = [
    ConfigSection(
        key="module_forge", label="Modules · Forge", icon="⚒", order=74,
        family="systeme",
        summary="Les limites du bac à sable où Mika écrit et fait tourner ses propres modules.",
        description=(
            "Espace confiné où Mika crée ses propres mini-modules "
            "(data/forge_modules/). Limites du bac à sable."
        ),
    ),

    # ── Organisation de l'écran ─────────────────────────────────────────
    #
    # Vingt et un réglages qui répondent à des questions distinctes : combien
    # de modules elle peut tenir, combien de temps un handler a le droit de
    # tourner, quand on lui coupe le courant, ce qu'il peut appeler dehors, ce
    # qu'il peut écrire. L'ordre suit la vie d'un module forgé — écrit, exécuté,
    # surveillé, autorisé à sortir — et ce qu'on n'ouvre qu'en diagnostic
    # (quotas de stockage, plafonds par exécution, rétention des versions) est
    # replié. Replié ne veut pas dire caché : le bloc reste cherchable et
    # s'ouvre seul s'il contient une valeur modifiée.
    ConfigGroup(
        section="module_forge", key="Atelier", order=10,
        description="Combien de modules Mika peut tenir en même temps, et "
                    "jusqu'où peut aller le code qu'elle écrit. Ces modules "
                    "sont écrits par elle à l'exécution et tournent dans ce "
                    "processus : ces deux nombres bornent la surface.",
    ),
    ConfigGroup(
        section="module_forge", key="Exécution", order=20,
        description="Les délais au bout desquels un handler forgé est coupé. "
                    "Une boucle infinie écrite par erreur ne doit pas immobiliser "
                    "un fil du bac à sable : c'est le rôle de ces budgets.",
    ),
    ConfigGroup(
        section="module_forge", key="Disjoncteur", order=30,
        description="Après N échecs consécutifs, le module est désactivé tout "
                    "seul, déchargé, et Mika est prévenue une fois avec "
                    "l'erreur — elle relit son code, le corrige, et le "
                    "réactive. Sans ça, un module cassé rejoue son échec à "
                    "chaque tick, pour toujours.",
    ),
    ConfigGroup(
        section="module_forge", key="Réveils et événements", order=40,
        description="Ce qu'un module forgé a le droit de déclencher chez les "
                    "autres. Un réveil, c'est un tour de pipeline complet ; un "
                    "événement traverse le bus et peut en réveiller d'autres.",
    ),
    ConfigGroup(
        section="module_forge", key="Accès réseau", order=50,
        description="Ce que « api.http_get » peut ramener. Ces bornes limitent "
                    "le VOLUME sortant, pas les destinations : la liste blanche "
                    "de domaines vit dans le manifeste de chaque module et ne "
                    "se règle pas d'ici.",
    ),
    ConfigGroup(
        section="module_forge", key="Stockage", order=60, advanced=True,
        description="Les quotas de « api.storage ». Les modules forgés n'ont "
                    "jamais de DDL : ils écrivent tous dans la même table de "
                    "l'hôte, d'où un quota par module plutôt qu'un schéma par "
                    "module.",
    ),
    ConfigGroup(
        section="module_forge", key="Plafonds par exécution", order=70,
        advanced=True,
        description="Ce qu'un seul passage d'un handler a le droit de produire. "
                    "Bornes de charge, pas de sécurité : elles empêchent une "
                    "boucle maladroite de saturer la base ou l'écran, et le "
                    "dépassement est toujours dit, jamais silencieux.",
    ),
    ConfigGroup(
        section="module_forge", key="Historique", order=80, advanced=True,
        description="Ce qui reste d'un module après qu'il a changé ou disparu : "
                    "versions archivées, corbeille, journal. C'est ce qui rend "
                    "« rollback » possible et ce qu'on relit quand un module a "
                    "sauté.",
    ),

    # ── Atelier ────────────────────────────────────────────────────────
    ConfigItem(
        key="forge.max_modules", type="int", section="module_forge",
        group="Atelier", label="Nb max de modules", default=12, min=1, max=50,
        hot_reload=True,
        description=(
            "Combien de mini-modules forgés peuvent coexister. Chacun est du "
            "code que Mika a écrit elle-même et qui tourne dans ce processus : "
            "il occupe un tick, il peut s'abonner au bus, il apparaît dans "
            "l'écran des apps. Au-delà de ce compte, une création est refusée "
            "— à elle d'en effacer un."
        ),
    ),
    ConfigItem(
        key="forge.max_source_kb", type="int", section="module_forge",
        group="Atelier", label="Taille max du code (Ko)", default=64,
        min=1, max=128, hot_reload=True,
        description=(
            "Refus à l'écriture au-delà. Un module forgé est censé faire une "
            "chose ; passé quelques dizaines de kilo-octets, ce n'est plus un "
            "mini-module, et le validateur AST comme la relecture humaine y "
            "perdent tous les deux."
        ),
    ),

    # ── Exécution ──────────────────────────────────────────────────────
    ConfigItem(
        key="forge.handler_timeout_s", type="int", section="module_forge",
        group="Exécution", label="Timeout handler (s)", default=10, min=1,
        max=120, hot_reload=True,
        description=(
            "Budget d'un handler forgé — tick, événement, vue. La deadline est "
            "posée dans le fil d'exécution lui-même et ne peut pas être "
            "rattrapée par le code surveillé : c'est ce qui garantit qu'un "
            "« while True » rend la main. Le dépassement compte comme un échec "
            "pour le disjoncteur."
        ),
    ),
    ConfigItem(
        key="forge.pool_workers", type="int", section="module_forge",
        group="Exécution", label="Fils d'exécution du bac à sable",
        default=2, min=1, max=16, restart_required=True,
        description=(
            "Nombre de handlers forgés pouvant tourner en même temps. "
            "L'exécuteur et son sémaphore sont bâtis une seule fois au "
            "démarrage du module : la valeur ne prend effet qu'après un "
            "redémarrage de la Forge. Chaque fil est un handler sous "
            "deadline ; en monter beaucoup revient à donner au code écrit à "
            "l'exécution une part plus grande du CPU du processus."
        ),
    ),
    ConfigItem(
        key="forge.context_timeout_s", type="float", section="module_forge",
        group="Exécution", label="Timeout get_context (s)",
        default=5.0, min=0.5, max=60.0, hot_reload=True,
        description=(
            "Budget du handler « get_context », plus court que celui des "
            "autres : son résultat part dans l'invite système, donc dans le "
            "chemin d'un tour de conversation qui attend déjà le modèle."
        ),
    ),
    ConfigItem(
        key="forge.load_timeout_s", type="float", section="module_forge",
        group="Exécution", label="Timeout de chargement (s)",
        default=10.0, min=1.0, max=120.0, hot_reload=True,
        description=(
            "Budget de l'exécution du code au niveau module (l'import, pas "
            "un handler) lors d'un chargement ou d'un rechargement à chaud."
        ),
    ),

    # ── Disjoncteur ────────────────────────────────────────────────────
    ConfigItem(
        key="forge.max_consecutive_failures", type="int",
        section="module_forge", group="Disjoncteur",
        label="Échecs avant disjoncteur", default=5, min=1, max=50,
        hot_reload=True,
        description=(
            "Échecs consécutifs de tick ou d'événement avant que le module ne "
            "soit désactivé de lui-même : l'état est écrit dans son "
            "« state.json », le module est déchargé, et Mika reçoit une fois "
            "l'erreur pour qu'elle puisse relire son code et le réactiver. "
            "Un succès remet le compteur à zéro. Monter trop haut, c'est "
            "laisser un module cassé rejouer son échec à chaque tick."
        ),
    ),

    # ── Réveils et événements ──────────────────────────────────────────
    ConfigItem(
        key="forge.notify_cooldown_s", type="int", section="module_forge",
        group="Réveils et événements", label="Cooldown notify_ai (s)",
        default=300, min=10, max=86400, hot_reload=True,
        description=(
            "Délai mini entre deux réveils de Mika par un même module. Un "
            "réveil n'est pas une notification : c'est un tour de pipeline "
            "complet, invite système et déclaration d'outils comprises. Un "
            "module qui surveille quelque chose de bavard interromprait "
            "sinon la conversation à chaque tick."
        ),
    ),
    ConfigItem(
        key="forge.emit_rate_per_min", type="int", section="module_forge",
        group="Réveils et événements", label="Événements émis max /min",
        default=12, min=1, max=120, hot_reload=True,
        description=(
            "Ce qu'un module peut poser sur le bus par minute. Un événement "
            "forgé est relayé aux autres modules forgés et lu par la "
            "conscience : c'est bon marché à l'unité, et une boucle qui en "
            "émet en rafale réveille tout le monde en même temps."
        ),
    ),

    # ── Accès réseau ───────────────────────────────────────────────────
    ConfigItem(
        key="forge.http_timeout_s", type="int", section="module_forge",
        group="Accès réseau", label="Timeout HTTP (s)", default=10, min=1,
        max=60, hot_reload=True,
        description=(
            "Attente maximale d'une réponse. Elle se dépense DANS le budget du "
            "handler : la poser au-dessus du timeout de handler ne sert à "
            "rien, la deadline du bac à sable tombe la première."
        ),
    ),
    ConfigItem(
        key="forge.http_max_kb", type="int", section="module_forge",
        group="Accès réseau", label="Réponse HTTP max (Ko)", default=512,
        min=1, max=4096, hot_reload=True,
        description=(
            "La lecture s'arrête à cette taille. Un module forgé lit des "
            "petites API, pas des archives : au-delà, ce qui revient finit "
            "de toute façon tronqué ou recopié dans le stockage."
        ),
    ),
    ConfigItem(
        key="forge.max_http_calls_per_run", type="int", section="module_forge",
        group="Accès réseau", label="Appels HTTP max par exécution",
        default=10, min=1, max=200, hot_reload=True,
        description=(
            "Un handler qui dépasse ce compte lève une erreur d'API. Ce "
            "plafond borne le *volume* de trafic sortant, rien d'autre : la "
            "liste des destinations autorisées reste le manifeste du module "
            "(« allowed_domains »), vérifiée à chaque appel, et elle n'est pas "
            "réglable d'ici. Monter ce nombre laisse un module appeler plus "
            "souvent les domaines qu'il a déjà le droit d'appeler ; ça ne lui "
            "en ouvre aucun nouveau."
        ),
    ),

    # ── Stockage ───────────────────────────────────────────────────────
    ConfigItem(
        key="forge.max_records_per_module", type="int",
        section="module_forge", group="Stockage",
        label="Quota stockage (lignes)", default=5000, min=100, max=100000,
        hot_reload=True,
        description=(
            "Lignes que « api.storage » accepte de garder pour un module. "
            "Tous les modules forgés écrivent dans la même table de l'hôte "
            "(ils n'obtiennent jamais de schéma à eux) : sans quota par "
            "module, un seul collecteur bavard remplirait la base pour tous "
            "les autres. Au-delà, l'écriture est refusée — au module de "
            "faire son ménage."
        ),
    ),
    ConfigItem(
        key="forge.max_value_kb", type="int", section="module_forge",
        group="Stockage", label="Taille max d'une valeur (Ko)", default=32,
        min=1, max=512, hot_reload=True,
        description=(
            "Une valeur stockée est du JSON sérialisé dans une colonne de la "
            "base partagée. Ce plafond dit ce qu'est une « fiche » plutôt "
            "qu'un fichier : un module qui veut garder une grosse réponse HTTP "
            "entière se fait refuser, et c'est le but."
        ),
    ),

    # ── Historique et corbeille ────────────────────────────────────────
    ConfigItem(
        key="forge.max_versions_kept", type="int", section="module_forge",
        group="Historique", label="Versions archivées par module",
        default=10, min=1, max=200, hot_reload=True,
        description=(
            "Chaque écriture archive la version précédente sous "
            "« _versions/ » ; c'est ce qui rend « rollback » possible. "
            "Au-delà, les plus anciennes sont supprimées."
        ),
    ),
    ConfigItem(
        key="forge.max_trash_kept", type="int", section="module_forge",
        group="Historique", label="Suppressions conservées",
        default=20, min=1, max=200, hot_reload=True,
        description=(
            "Un module effacé part dans « _trash/ » plutôt qu'au néant. "
            "C'est un filet de sécurité, pas une archive : sans plafond, une "
            "boucle écrire→effacer ferait grossir le disque indéfiniment."
        ),
    ),
    ConfigItem(
        key="forge.log_keep_per_module", type="int", section="module_forge",
        group="Historique", label="Lignes de journal gardées par module",
        default=300, min=20, max=10000, hot_reload=True,
        description=(
            "Le journal est ce qu'on lit quand un module casse. Élaguer trop "
            "court efface la trace de l'échec qui a fait sauter le "
            "disjoncteur ; trop long fait de ForgeLog la table qui grossit "
            "le plus vite de la base."
        ),
    ),

    # ── Plafonds par exécution ─────────────────────────────────────────
    ConfigItem(
        key="forge.max_log_calls_per_run", type="int", section="module_forge",
        group="Plafonds par exécution", label="Lignes de journal max par exécution",
        default=200, min=10, max=5000, hot_reload=True,
        description=(
            "Chaque ligne est un INSERT synchrone sur la base partagée : un "
            "« for x in items: print(x) » sur 500 éléments prend 500 fois le "
            "verrou d'écriture, à chaque tick, sans que le disjoncteur ne "
            "voie rien. Le surplus est compté et dit en fin d'exécution, "
            "jamais silencieux."
        ),
    ),
    ConfigItem(
        key="forge.max_manifest_kb", type="int", section="module_forge",
        group="Plafonds par exécution", label="Taille max du manifeste (Ko)",
        default=16, min=1, max=256, hot_reload=True,
        description="Un manifest.yaml plus gros est refusé à la lecture.",
    ),
    ConfigItem(
        key="forge.max_view_payload_kb", type="int", section="module_forge",
        group="Plafonds par exécution", label="Charge utile max d'une vue (Ko)",
        default=512, min=8, max=8192, hot_reload=True,
        description=(
            "Au-delà, la page affiche une erreur invitant à paginer avec "
            "params['page'] / params['per_page'] plutôt que de sérialiser un "
            "tableau entier à chaque affichage."
        ),
    ),
]
