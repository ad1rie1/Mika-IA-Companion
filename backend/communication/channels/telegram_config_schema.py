"""Config schema for the Telegram module."""
from __future__ import annotations

from configs.types import ConfigItem, ConfigSection

CONFIG_SCHEMA = [
    ConfigSection(
        key="module_telegram", label="Modules · Telegram", icon="📨", order=72,
        description="Bot Telegram pour converser à distance.",
    ),
    ConfigItem(
        key="telegram.token", type="secret", section="module_telegram",
        label="Bot token", env_fallback="TELEGRAM_TOKEN", sensitive=True,
        hint="Jeton fourni par @BotFather.",
    ),
]
