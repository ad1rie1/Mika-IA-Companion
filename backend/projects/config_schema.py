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
        label="Buffer prompt history", env_fallback="PROJECT_PROMPT_HISTORY_SIZE",
        default=30, min=0, max=500,
        hint="0 = désactive la capture prompt/response.",
    ),
]
