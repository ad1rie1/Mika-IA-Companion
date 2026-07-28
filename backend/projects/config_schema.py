"""Config schema for the projects subsystem."""
from __future__ import annotations

from configs.types import ConfigItem, ConfigSection

CONFIG_SCHEMA = [
    ConfigSection(
        key="projects", label="Projets", icon="◱", order=60,
        description="Runner des projets agent.",
    ),
    ConfigItem(
        key="projects.prompt_history_size", type="int", section="projects",
        label="Buffer prompt history",
        default=30, min=0, max=500,
        hint="0 = désactive la capture prompt/response.",
    ),
    ConfigItem(
        key="projects.runner_interval", type="int", section="projects",
        label="Période runner (s)",
        default=30, min=5, max=600, restart_required=True,
        hint="Cadence de la boucle dédiée qui fait avancer les projets dus. "
             "Découplée du consolidator — un interval:30s tient vraiment 30s.",
    ),
]
