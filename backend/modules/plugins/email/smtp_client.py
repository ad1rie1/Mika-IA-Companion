import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

logger = logging.getLogger(__name__)


class SMTPClient:
    """Async SMTP client for sending email replies."""

    def __init__(self, host: str, port: int, user: str, password: str):
        self.host = host
        self.port = port
        self.user = user
        self.password = password

    @classmethod
    def from_account(cls, account) -> "SMTPClient":
        return cls(account.smtp_host, account.smtp_port, account.smtp_user, account.smtp_password)

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

        try:
            await aiosmtplib.send(
                msg,
                hostname=self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                use_tls=True,
            )
            logger.info("Email sent to %s: %s", to_addr, subject)
        except Exception:
            logger.exception("Failed to send email to %s", to_addr)
            raise
