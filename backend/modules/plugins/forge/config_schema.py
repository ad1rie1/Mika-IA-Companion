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
]
