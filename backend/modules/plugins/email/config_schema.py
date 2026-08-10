"""Config schema for the email module.

Accounts are stored in ``modules.plugins.email.models.EmailAccount`` — the
config UI edits them via the ``EmailAccountBackend`` adapter so the
generic ``ConfigRecordItem`` table is never used for email. The
config editor and the module's own storage stay in lockstep without
duplication.
"""
from __future__ import annotations

# Importing the backend registers it — side-effect intentional.
from modules.plugins.email import config_backend  # noqa: F401

from configs.types import (
    ConfigGroup, ConfigItem, ConfigRecord, ConfigSection, record_item,
)

CONFIG_SCHEMA = [
    ConfigSection(
        key="module_email", label="Modules · Email", icon="✉", order=71,
        family="systeme",
        summary="Les boîtes qu'elle relève, à quelle cadence, et ce qu'un tour a le droit de traiter.",
        description="Comptes IMAP/SMTP (table EmailAccount).",
    ),

    # ── Organisation de l'écran ─────────────────────────────────────────
    # Trois questions distinctes : quelles boîtes, à quel rythme on les
    # relève, et combien de temps on garde ce qu'on y a lu.
    ConfigGroup(
        section="module_email", key="Comptes", order=10,
        description="Les boîtes relevées. Chaque ligne est un compte autonome, "
                    "stocké dans la table EmailAccount — pas dans le registre "
                    "de configuration.",
    ),
    ConfigGroup(
        section="module_email", key="Relevé", order=20,
        description="Le rythme du module et ce qu'un tour a le droit d'avaler. "
                    "Les trois réglages sont couplés : un message neuf coûte "
                    "deux appels LLM en série, et le lot doit tenir dans le "
                    "délai maximum du tour.",
    ),
    ConfigGroup(
        section="module_email", key="Conservation", order=30, advanced=True,
        description="Combien de messages relevés restent en base une fois "
                    "triés. Ce ne sont pas les mails eux-mêmes : le serveur les "
                    "garde, ceci ne borne que la trace locale qui sert de "
                    "curseur au relevé.",
    ),
    ConfigItem(
        key="email.accounts", type="record_list", section="module_email",
        group="Comptes", label="Comptes email", min_items=0, max_items=50,
        description=(
            "Chaque ligne est un compte autonome. Le polling visite tous "
            "les comptes activés."
        ),
        record=ConfigRecord(
            name="email_account", label="Compte email",
            fields=(
                record_item(key="name",          type="str",    label="Nom",         hint="Étiquette interne."),
                record_item(key="email_address", type="str",    label="Adresse email"),
                record_item(key="imap_host",     type="str",    label="Hôte IMAP"),
                record_item(key="imap_port",     type="int",    label="Port IMAP",   default=993),
                record_item(key="imap_user",     type="str",    label="Login IMAP",  hint="Par défaut = adresse email."),
                record_item(key="imap_password", type="secret", label="Mot de passe IMAP", sensitive=True),
                record_item(key="smtp_host",     type="str",    label="Hôte SMTP"),
                record_item(key="smtp_port",     type="int",    label="Port SMTP",   default=587,
                            hint="Le port choisit le chiffrement : 465 = TLS implicite, tout autre port (587, 25) = STARTTLS."),
                record_item(key="smtp_user",     type="str",    label="Login SMTP"),
                record_item(key="smtp_password", type="secret", label="Mot de passe SMTP", sensitive=True),
            ),
        ),
    ),
    ConfigItem(
        key="email.poll_interval", type="int", section="module_email",
        group="Relevé", label="Intervalle de relevé (s)",
        default=60, min=30, max=86400, hot_reload=True,
        description=(
            "Cadence du tick qui visite tous les comptes activés. Chaque "
            "compte ouvre une session IMAP et peut déclencher des appels LLM "
            "de triage : descendre sous la minute ne rend pas la boîte plus "
            "fraîche, ça superpose les relevés."
        ),
    ),
    ConfigItem(
        key="email.max_per_tick", type="int", section="module_email",
        group="Relevé", label="Messages traités par tour et par compte",
        default=15, min=1, max=500, hot_reload=True,
        description=(
            "Le reste est repris au tour suivant. Un message neuf coûte deux "
            "appels LLM en série (triage puis interprétation par la "
            "conscience) : au-delà d'une quinzaine, le tour dépasse son délai "
            "maximum de 180 s. Pendant la synchro initiale aucun appel LLM "
            "n'a lieu, donc une valeur élevée y est sans risque — la monter "
            "le temps d'importer une grosse boîte, puis la redescendre."
        ),
    ),
    ConfigItem(
        key="email.tick_timeout_s", type="int", section="module_email",
        group="Relevé", label="Délai maximum par compte et par tour (s)",
        default=180, min=30, max=1800, hot_reload=True,
        description=(
            "Plafond d'une passe relève+traitement sur un compte. Au-delà, la "
            "connexion est lâchée et reprise au tour suivant — aioimaplib "
            "n'a aucun délai propre, donc un serveur qui accepte le TCP puis "
            "se tait bloquait ce module pour la vie du processus. "
            "Ce budget et « Messages traités par tour » sont deux moitiés du "
            "même réglage : c'est sur ces 180 s que la quinzaine de messages "
            "est calibrée. Monter le lot sans monter le délai, c'est faire "
            "expirer le tour ; monter le délai sans monter le lot ne sert "
            "qu'à une boîte volumineuse en synchro initiale."
        ),
    ),
    ConfigItem(
        key="email.keep_per_account", type="int", section="module_email",
        group="Conservation", label="Messages conservés par compte",
        default=200, min=20, max=100000, hot_reload=True,
        description=(
            "Les plus anciens sont supprimés au-delà, jamais pendant la "
            "synchro initiale : les lignes stockées servent de curseur, et "
            "élaguer pendant l'import ferait revenir au tour suivant, comme "
            "« nouveaux », les messages qu'on vient d'effacer."
        ),
    ),
]
