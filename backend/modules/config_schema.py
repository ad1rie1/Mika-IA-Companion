"""Config schema for the modules scheduler + email module (embedded demo).

The per-module schema hook (``BaseModule.config_schema()``) will let
each module ship its own declarations later. For now we expose the
cross-module settings here + the email account list as a reference
record_list implementation.
"""
from __future__ import annotations

from configs.types import ConfigItem, ConfigRecord, ConfigSection, record_item

CONFIG_SCHEMA = [
    ConfigSection(
        key="modules_runtime", label="Modules · Runtime", icon="▦", order=70,
        description="Planificateur cron des modules.",
    ),
    ConfigItem(
        key="modules.cron_tick_interval", type="int", section="modules_runtime",
        label="Tick scheduler (s)", env_fallback="CRON_TICK_INTERVAL",
        default=60, min=1, max=3600, restart_required=True,
    ),

    ConfigSection(
        key="module_email", label="Modules · Email", icon="✉", order=71,
        description="Comptes IMAP/SMTP — la liste remplace les variables d'env mono-compte.",
    ),
    ConfigItem(
        key="email.triage_intervals_seconds", type="int", section="module_email",
        label="Intervalle polling défaut (s)", default=60, min=10, max=3600,
        hot_reload=True,
    ),
    ConfigItem(
        key="email.accounts", type="record_list", section="module_email",
        label="Comptes email", min_items=0, max_items=20,
        description="Chaque ligne est un compte autonome. Le module surveille tous les comptes activés.",
        record=ConfigRecord(
            name="email_account",
            label="Compte email",
            fields=(
                record_item(key="name",         type="str",    label="Nom",         hint="Étiquette interne (unique)."),
                record_item(key="description",  type="text",   label="Description"),
                record_item(key="imap_host",    type="str",    label="Hôte IMAP"),
                record_item(key="imap_port",    type="int",    label="Port IMAP",   default=993),
                record_item(key="imap_user",    type="str",    label="Login IMAP"),
                record_item(key="imap_password",type="secret", label="Mot de passe IMAP", sensitive=True),
                record_item(key="smtp_host",    type="str",    label="Hôte SMTP"),
                record_item(key="smtp_port",    type="int",    label="Port SMTP",   default=587),
                record_item(key="smtp_user",    type="str",    label="Login SMTP"),
                record_item(key="smtp_password",type="secret", label="Mot de passe SMTP", sensitive=True),
                record_item(key="poll_interval",type="int",    label="Intervalle (s)", default=60, min=10, max=3600),
            ),
        ),
    ),

    ConfigSection(
        key="module_telegram", label="Modules · Telegram", icon="📨", order=72,
    ),
    ConfigItem(
        key="telegram.token", type="secret", section="module_telegram",
        label="Bot token", env_fallback="TELEGRAM_TOKEN", sensitive=True,
    ),

    ConfigSection(
        key="module_rss", label="Modules · RSS", icon="⌁", order=73,
    ),
    ConfigItem(
        key="rss.poll_interval", type="int", section="module_rss",
        label="Intervalle polling (s)", env_fallback="RSS_POLL_INTERVAL",
        default=600, min=60, max=86400, hot_reload=True,
    ),
    ConfigItem(
        key="rss.feeds", type="record_list", section="module_rss",
        label="Flux RSS", min_items=0, max_items=50,
        record=ConfigRecord(
            name="rss_feed", label="Flux RSS",
            fields=(
                record_item(key="name", type="str", label="Nom"),
                record_item(key="url",  type="str", label="URL"),
            ),
        ),
    ),
]
