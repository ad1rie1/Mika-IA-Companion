"""Config schema for the emotion engine."""
from __future__ import annotations

from configs.types import ConfigItem, ConfigSection

CONFIG_SCHEMA = [
    ConfigSection(
        key="emotion", label="Émotion", icon="❋", order=40,
        description="Décroissance PAD, snapshots, rétention.",
    ),
    ConfigItem(
        key="emotion.decay_rate", type="float", section="emotion",
        label="Décroissance/seconde",
        default=0.02, min=0.001, max=0.5, hot_reload=True,
    ),
    ConfigItem(
        key="emotion.snapshot_interval", type="int", section="emotion",
        label="Intervalle snapshot (s)",
        default=30, min=5, max=600, hot_reload=True,
    ),
    ConfigItem(
        key="emotion.snapshot_retention_days", type="int", section="emotion",
        label="Rétention snapshots (jours)",
        default=2, min=1, max=90,
    ),
]
