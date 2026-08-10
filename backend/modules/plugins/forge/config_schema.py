"""Config de l'hôte Forge — les limites du bac à sable.

Les sections de config des modules forgés eux-mêmes sont déclarées
dynamiquement (``ForgeModule._register_config``) sous les clés
``forge.<module>.<champ>``.
"""
from __future__ import annotations

from configs.types import ConfigItem, ConfigSection

CONFIG_SCHEMA = [
    ConfigSection(
        key="module_forge", label="Modules · Forge", icon="⚒", order=74,
        description=(
            "Espace confiné où Mika crée ses propres mini-modules "
            "(data/forge_modules/). Limites du bac à sable."
        ),
    ),
    ConfigItem(
        key="forge.handler_timeout_s", type="int", section="module_forge",
        label="Timeout handler (s)", default=10, min=1, max=120,
        hot_reload=True,
        description="Budget temps d'un handler de module forgé.",
    ),
    ConfigItem(
        key="forge.max_modules", type="int", section="module_forge",
        label="Nb max de modules", default=12, min=1, max=50,
        hot_reload=True,
    ),
    ConfigItem(
        key="forge.max_consecutive_failures", type="int",
        section="module_forge",
        label="Échecs avant disjoncteur", default=5, min=1, max=50,
        hot_reload=True,
        description="Échecs consécutifs avant auto-désactivation.",
    ),
    ConfigItem(
        key="forge.max_records_per_module", type="int",
        section="module_forge",
        label="Quota stockage (lignes)", default=5000, min=100, max=100000,
        hot_reload=True,
    ),
    ConfigItem(
        key="forge.max_value_kb", type="int", section="module_forge",
        label="Taille max d'une valeur (Ko)", default=32, min=1, max=512,
        hot_reload=True,
    ),
    ConfigItem(
        key="forge.max_source_kb", type="int", section="module_forge",
        label="Taille max du code (Ko)", default=64, min=1, max=128,
        hot_reload=True,
    ),
    ConfigItem(
        key="forge.notify_cooldown_s", type="int", section="module_forge",
        label="Cooldown notify_ai (s)", default=300, min=10, max=86400,
        hot_reload=True,
        description="Délai mini entre deux réveils de Mika par un même module.",
    ),
    ConfigItem(
        key="forge.emit_rate_per_min", type="int", section="module_forge",
        label="Événements émis max /min", default=12, min=1, max=120,
        hot_reload=True,
    ),
    ConfigItem(
        key="forge.http_timeout_s", type="int", section="module_forge",
        label="Timeout HTTP (s)", default=10, min=1, max=60,
        hot_reload=True,
    ),
    ConfigItem(
        key="forge.http_max_kb", type="int", section="module_forge",
        label="Réponse HTTP max (Ko)", default=512, min=1, max=4096,
        hot_reload=True,
    ),
    ConfigItem(
        key="forge.max_http_calls_per_run", type="int", section="module_forge",
        label="Appels HTTP max par exécution", default=10, min=1, max=200,
        hot_reload=True,
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

    # ── Exécution ──────────────────────────────────────────────────────
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
        group="Plafonds", label="Lignes de journal max par exécution",
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
        group="Plafonds", label="Taille max du manifeste (Ko)",
        default=16, min=1, max=256, hot_reload=True,
        description="Un manifest.yaml plus gros est refusé à la lecture.",
    ),
    ConfigItem(
        key="forge.max_view_payload_kb", type="int", section="module_forge",
        group="Plafonds", label="Charge utile max d'une vue (Ko)",
        default=512, min=8, max=8192, hot_reload=True,
        description=(
            "Au-delà, la page affiche une erreur invitant à paginer avec "
            "params['page'] / params['limit'] plutôt que de sérialiser un "
            "tableau entier à chaque affichage."
        ),
    ),
    ConfigItem(
        key="forge.panel_code_chars", type="int", section="module_forge",
        group="Plafonds", label="Code affiché dans la fiche (caractères)",
        default=8000, min=500, max=200000, hot_reload=True,
        description=(
            "Troncature d'affichage du source dans l'espace d'un module "
            "forgé. N'a aucun effet sur ce qui est exécuté : la taille du "
            "code lui-même est bornée par « Taille max du code (Ko) »."
        ),
    ),
]
