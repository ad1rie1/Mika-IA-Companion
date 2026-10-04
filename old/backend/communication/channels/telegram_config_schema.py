"""Config schema for the Telegram communication channel."""
from __future__ import annotations

from old.backend.configs.types import ConfigGroup, ConfigItem, ConfigSection

CONFIG_SCHEMA = [
    ConfigSection(
        key="comm_telegram", label="Telegram", icon="📨", order=32,
        family="canaux",
        summary="Le bot Telegram : son jeton, qui a le droit de lui écrire, "
                "et à quel rythme.",
        description="Bot Telegram pour converser à distance.",
    ),
    ConfigGroup(
        section="comm_telegram", key="Connexion", order=10,
        description="Le jeton du bot. Sans lui le canal ne démarre pas du "
                    "tout — il se tait proprement plutôt que d'échouer. La "
                    "valeur est chiffrée en base et n'est jamais réaffichée : "
                    "le champ repart vide, et le laisser vide ne l'efface pas.",
    ),
    ConfigGroup(
        section="comm_telegram", key="Qui a le droit d'écrire", order=20,
        description="La liste blanche est vérifiée avant la moindre écriture : "
                    "un inconnu ne laisse ni entrée de présence, ni handle "
                    "d'identité, ni message en base. Le refus est dit à voix "
                    "haute plutôt que subi en silence.",
    ),
    ConfigGroup(
        section="comm_telegram", key="Débit", order=30,
        description="Fenêtre glissante par *compte* — il n'y a pas de "
                    "connexion à compter de ce côté. Mêmes valeurs de départ "
                    "que le canal web, délibérément : un message y coûte le "
                    "même tour de pipeline complet. Les deux clés restent "
                    "distinctes, régler ici ne touche pas au web.",
    ),
    ConfigItem(
        key="telegram.token", type="secret", section="comm_telegram",
        group="Connexion",
        label="Bot token", sensitive=True,
        hint="Jeton fourni par @BotFather.",
    ),
    ConfigItem(
        key="telegram.allowed_chats", type="list", section="comm_telegram",
        group="Qui a le droit d'écrire",
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
