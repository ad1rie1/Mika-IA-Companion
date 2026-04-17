"""Config schema for the Telegram communication channel."""
from __future__ import annotations

from configs.types import ConfigItem, ConfigSection

CONFIG_SCHEMA = [
    ConfigSection(
        key="comm_telegram", label="Communication · Telegram", icon="📨", order=32,
        description="Bot Telegram pour converser à distance.",
    ),
    ConfigItem(
        key="telegram.token", type="secret", section="comm_telegram",
        label="Bot token", env_fallback="TELEGRAM_TOKEN", sensitive=True,
        hint="Jeton fourni par @BotFather.",
    ),
]
