"""Config schema for the conscience engine."""
from __future__ import annotations

from configs.types import ConfigItem, ConfigSection

CONFIG_SCHEMA = [
    ConfigSection(
        key="conscience", label="Conscience", icon="◉", order=50,
        description="Boucle de décision, seuil d'action, cooldown.",
    ),
    ConfigItem(
        key="conscience.decision_interval", type="int", section="conscience",
        label="Intervalle décision (s)", env_fallback="CONSCIENCE_DECISION_INTERVAL",
        default=30, min=5, max=3600, restart_required=True,
    ),
    ConfigItem(
        key="conscience.cooldown_seconds", type="int", section="conscience",
        label="Cooldown entre actions (s)", env_fallback="CONSCIENCE_COOLDOWN_SECONDS",
        default=300, min=0, max=86400, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.act_threshold", type="float", section="conscience",
        label="Seuil score → agir", env_fallback="CONSCIENCE_ACT_THRESHOLD",
        default=0.5, min=0.0, max=1.0, hot_reload=True,
        hint="Plus haut = Mika parle moins spontanément.",
    ),
]
