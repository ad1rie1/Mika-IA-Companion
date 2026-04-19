"""Config schema for the RSS module.

Feed storage is owned by ``modules.plugins.rss.models.RSSFeed`` (dedicated
page in the module dashboard). The config system exposes only the
scalar polling knob.
"""
from __future__ import annotations

from configs.types import ConfigItem, ConfigSection

CONFIG_SCHEMA = [
    ConfigSection(
        key="module_rss", label="Modules · RSS", icon="⌁", order=73,
        description="Flux gérés dans la table RSSFeed (page dédiée).",
    ),
    ConfigItem(
        key="rss.poll_interval", type="int", section="module_rss",
        label="Intervalle polling (s)", env_fallback="RSS_POLL_INTERVAL",
        default=600, min=60, max=86400, hot_reload=True,
    ),
]
