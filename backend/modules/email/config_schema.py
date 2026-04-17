"""Config schema for the email module.

Accounts are stored in ``modules.email.models.EmailAccount`` — the
config UI edits them via the ``EmailAccountBackend`` adapter so the
generic ``ConfigRecordItem`` table is never used for email. The
config editor and the module's own storage stay in lockstep without
duplication.
"""
from __future__ import annotations

# Importing the backend registers it — side-effect intentional.
from modules.email import config_backend  # noqa: F401

from configs.types import ConfigItem, ConfigRecord, ConfigSection, record_item

CONFIG_SCHEMA = [
    ConfigSection(
        key="module_email", label="Modules · Email", icon="✉", order=71,
        description="Comptes IMAP/SMTP (table EmailAccount).",
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
                record_item(key="smtp_port",     type="int",    label="Port SMTP",   default=587),
                record_item(key="smtp_user",     type="str",    label="Login SMTP"),
                record_item(key="smtp_password", type="secret", label="Mot de passe SMTP", sensitive=True),
            ),
        ),
    ),
]
