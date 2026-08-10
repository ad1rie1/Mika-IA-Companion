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
    ConfigItem(
        key="telegram.rate_limit_max_messages", type="int",
        section="comm_telegram", group="Débit",
        label="Messages max par fenêtre",
        default=20, min=1, max=1000, hot_reload=True,
        hint=(
            "Fenêtre glissante par *compte* Telegram (le canal web compte par "
            "connexion — ici il n'y en a pas). Chaque message reçu coûte un "
            "tour de pipeline complet, et un nom de bot est découvrable. "
            "Réglage jumeau de « comm.web.rate_limit_max_messages », qui "
            "porte volontairement la même valeur de départ : le coût est le "
            "même de l'autre côté. Les deux clés restent distinctes, donc "
            "bouger celle-ci ne bouge PAS celle du web."
        ),
    ),
    ConfigItem(
        key="telegram.rate_limit_window_seconds", type="float",
        section="comm_telegram", group="Débit",
        label="Fenêtre de comptage (s)",
        default=10.0, min=0.5, max=3600.0, hot_reload=True,
        hint=(
            "Largeur de la fenêtre glissante. Jumelle de "
            "« comm.web.rate_limit_window_seconds » — même valeur de départ, "
            "délibérément, mais deux clés : la régler ici laisse celle du web "
            "où elle était."
        ),
    ),
]
