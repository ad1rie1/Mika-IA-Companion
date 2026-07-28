"""Config schema for the memory subsystem."""
from __future__ import annotations

from configs.types import ConfigItem, ConfigSection

CONFIG_SCHEMA = [
    ConfigSection(
        key="memory", label="Mémoire", icon="❖", order=30,
        description="Court-terme, consolidation, décroissance, récupération sémantique.",
    ),
    ConfigItem(
        key="memory.short_term_limit", type="int", section="memory", group="Court-terme",
        label="Messages en RAM",
        default=20, min=5, max=200, hot_reload=True,
    ),
    ConfigItem(
        key="memory.consolidation_interval", type="int", section="memory", group="Consolidation",
        label="Période consolidation (s)",
        default=60, min=10, max=3600, restart_required=True,
    ),
    ConfigItem(
        key="memory.decay_rate", type="float", section="memory", group="Décroissance",
        label="Taux de décroissance/jour",
        default=0.95, min=0.5, max=1.0, hot_reload=True,
        hint="0.95 = perd 5% d'importance par jour.",
    ),
    ConfigItem(
        key="memory.min_importance", type="float", section="memory", group="Décroissance",
        label="Seuil de purge",
        default=0.1, min=0.0, max=1.0, hot_reload=True,
    ),
    ConfigItem(
        key="memory.retrieval_souvenirs", type="int", section="memory", group="Récupération",
        label="Souvenirs retournés",
        default=5, min=1, max=50, hot_reload=True,
    ),
    ConfigItem(
        key="memory.retrieval_connaissances", type="int", section="memory", group="Récupération",
        label="Connaissances retournées",
        default=10, min=1, max=50, hot_reload=True,
    ),
    ConfigItem(
        key="memory.sleep_check_interval", type="int", section="memory", group="Consolidation",
        label="Période check sleep cycle (s)",
        default=60, min=10, max=600, restart_required=True,
        hint="Cadence de la boucle dédiée qui appelle sleep_cycle.run_if_due() "
             "(journal/rêves/digestion). Découplée du consolidator.",
    ),
]
