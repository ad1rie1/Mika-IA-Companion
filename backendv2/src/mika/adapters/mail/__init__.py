"""Le courrier réel : plusieurs comptes IMAP/SMTP, un cache SQLite (voir ``client``)."""

from mika.adapters.mail.client import ImapSmtpMail
from mika.adapters.mail.config import LEGACY_ACCOUNT, MailAccount, MailConfig, from_stored
from mika.adapters.mail.parse import parse

__all__ = ["LEGACY_ACCOUNT", "ImapSmtpMail", "MailAccount", "MailConfig", "from_stored", "parse"]
