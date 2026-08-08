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

from configs.types import ConfigItem, ConfigRecord, ConfigSection, record_item

CONFIG_SCHEMA = [
    ConfigSection(
        key="module_email", label="Modules · Email", icon="✉", order=71,
        description=(
            "Comptes IMAP/SMTP (table EmailAccount) et garde-fous de la "
            "réponse automatique."
        ),
    ),
    ConfigItem(
        key="email.accounts", type="record_list", section="module_email",
        label="Comptes email", min_items=0, max_items=50,
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
        key="email.auto_reply_enabled", type="bool", section="module_email",
        group="Réponse automatique", label="Réponse automatique au triage",
        default=True, hot_reload=True,
        description=(
            "Le triage peut répondre seul à un e-mail. La décision est prise "
            "par le modèle avec le corps du message dans son contexte : une "
            "injection y porte directement. Décocher coupe l'envoi sans "
            "toucher au reste du triage — notification, mémoire, priorité."
        ),
    ),
    ConfigItem(
        key="email.auto_reply_max_per_tick", type="int", section="module_email",
        group="Réponse automatique", label="Réponses auto max par relève",
        default=3, min=0, max=50, hot_reload=True,
        description=(
            "Une relève traite tout ce qui est arrivé depuis la précédente ; "
            "sans plafond, un lot de rattrapage envoie autant de réponses "
            "qu'il lit de messages."
        ),
        hint="0 = aucune réponse automatique.",
    ),
    ConfigItem(
        key="email.auto_reply_max_per_sender", type="int", section="module_email",
        group="Réponse automatique",
        label="Réponses auto max par expéditeur (24 h)",
        default=1, min=0, max=50, hot_reload=True,
        description=(
            "Ce qu'un plafond par relève ne peut pas arrêter : un répondeur "
            "automatique qui n'annonce rien dans ses en-têtes réécrit à "
            "chaque passage, soit toutes les 60 secondes."
        ),
    ),
]
