"""Cross-cutting module infrastructure settings.

Module-specific settings live in each module's ``config_schema()``
class method so they stay co-located with the code that consumes them.
"""
from __future__ import annotations

from configs.types import ConfigItem, ConfigSection

CONFIG_SCHEMA = [
    ConfigSection(
        key="modules_runtime", label="Modules · Runtime", icon="▦", order=70,
        description="Planificateur cron partagé par tous les modules.",
    ),
    ConfigItem(
        key="modules.cron_tick_interval", type="int", section="modules_runtime",
        label="Tick scheduler (s)",
        default=60, min=1, max=3600, restart_required=True,
    ),
]
