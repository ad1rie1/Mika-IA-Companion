import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from configs import secrets

logger = logging.getLogger(__name__)

# Le port décide du mode de chiffrement, et aiosmtplib expose les deux par
# deux paramètres distincts : `use_tls` négocie le TLS sur la socket *avant*
# le greeting (TLS implicite, port 465), `start_tls` l'obtient par la commande
# ESMTP STARTTLS (port submission 587, en clair jusque-là). Forcer `use_tls`
# sur 587 — le port que le formulaire de configuration propose par défaut —
# fait échouer la poignée de main dès le greeting : aucun envoi ne passe.
IMPLICIT_TLS_PORT = 465


class SMTPClient:
    """Async SMTP client for sending email replies."""

    def __init__(self, host: str, port: int, user: str, password: str):
        self.host = host
        self.port = port
        self.user = user
        self.password = password

    @classmethod
    def from_account(cls, account) -> "SMTPClient":
        # Même règle que côté IMAP : déchiffrement au point d'usage, tolérant
        # aux lignes stockées en clair avant le chiffrement.
        password = secrets.decrypt(account.smtp_password) if account.smtp_password else ""
        return cls(account.smtp_host, account.smtp_port, account.smtp_user, password)

    async def send_reply(
        self,
        to_addr: str,
        subject: str,
        body: str,
        in_reply_to: str = "",
    ):
        """Send an email reply."""
        msg = MIMEMultipart()
        msg["From"] = self.user
        msg["To"] = to_addr
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        msg.attach(MIMEText(body, "plain", "utf-8"))

        # STARTTLS est exigé, pas auto-détecté : un identifiant SMTP ne part
        # jamais en clair, quitte à ce que l'envoi échoue franchement.
        tls_implicite = self.port == IMPLICIT_TLS_PORT
        try:
            await aiosmtplib.send(
                msg,
                hostname=self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                use_tls=tls_implicite,
                start_tls=None if tls_implicite else True,
            )
            logger.info("Email sent to %s: %s", to_addr, subject)
        except Exception:
            logger.exception("Failed to send email to %s", to_addr)
            raise
