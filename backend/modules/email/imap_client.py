import logging
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser

from aioimaplib import IMAP4_SSL
from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class EmailMessage:
    uid: str
    message_id: str
    from_addr: str
    to_addr: str
    subject: str
    body_text: str
    date: str


class IMAPClient:
    """Async IMAP client for checking inbox."""

    def __init__(self):
        self.host = settings.IMAP_HOST
        self.port = settings.IMAP_PORT
        self.user = settings.IMAP_USER
        self.password = settings.IMAP_PASSWORD
        self._client: IMAP4_SSL | None = None

    async def connect(self):
        self._client = IMAP4_SSL(host=self.host, port=self.port)
        await self._client.wait_hello_from_server()
        await self._client.login(self.user, self.password)
        await self._client.select("INBOX")
        logger.info("IMAP connected to %s", self.host)

    async def disconnect(self):
        if self._client:
            try:
                await self._client.logout()
            except Exception:
                logger.debug("IMAP logout error (non-fatal)")
            self._client = None

    async def fetch_unread(self) -> list[EmailMessage]:
        """Fetch all unread emails from inbox."""
        if not self._client:
            await self.connect()

        result, data = await self._client.search("UNSEEN")
        if result != "OK" or not data[0]:
            return []

        uids = data[0].split()
        emails = []
        parser = BytesParser(policy=policy.default)

        for uid in uids:
            try:
                uid_str = uid.decode() if isinstance(uid, bytes) else uid
                result, msg_data = await self._client.fetch(uid_str, "(RFC822)")
                if result != "OK":
                    continue

                # Find the raw email bytes in the response
                raw_bytes = None
                for item in msg_data:
                    if isinstance(item, bytes):
                        raw_bytes = item
                        break
                if raw_bytes is None:
                    continue

                msg = parser.parsebytes(raw_bytes)
                body = self._extract_body(msg)

                emails.append(
                    EmailMessage(
                        uid=uid_str,
                        message_id=msg.get("Message-ID", ""),
                        from_addr=msg.get("From", ""),
                        to_addr=msg.get("To", ""),
                        subject=msg.get("Subject", "(no subject)"),
                        body_text=body[:2000],
                        date=msg.get("Date", ""),
                    )
                )
            except Exception:
                logger.exception("Error fetching email UID %s", uid)

        return emails

    def _extract_body(self, msg) -> str:
        """Extract plain text body from email."""
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == "text/plain":
                    try:
                        return part.get_content()
                    except Exception:
                        return ""
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == "text/html":
                    try:
                        return part.get_content()
                    except Exception:
                        return ""
            return ""

        try:
            return msg.get_content()
        except Exception:
            return ""

    async def mark_as_seen(self, uid: str):
        """Mark a specific email as seen/read."""
        if self._client:
            await self._client.store(uid, "+FLAGS", "\\Seen")
