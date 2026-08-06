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
        label="Bot token", sensitive=True,
        hint="Jeton fourni par @BotFather.",
    ),
    ConfigItem(
        key="telegram.allowed_chats", type="list", section="comm_telegram",
        label="Comptes et groupes autorisés",
        default=[], hot_reload=True,
        description=(
            "Vide = tout le monde. Sinon, liste blanche d'identifiants "
            "Telegram : un compte y figure par son id d'utilisateur, un "
            "salon par son id de chat. Un nom de bot est découvrable, et "
            "chaque message reçu coûte un tour de pipeline complet — prompt "
            "système, mémoire, outils — plus deux lignes en mémoire longue."
        ),
        hint="Ex. 123456789 pour un compte, -1001234567890 pour un groupe.",
    ),
]
