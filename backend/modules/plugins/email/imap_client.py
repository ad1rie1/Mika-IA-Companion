import logging
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser

from aioimaplib import IMAP4_SSL

logger = logging.getLogger(__name__)


@dataclass
class EmailMessage:
    uid: str
    message_id: str
    from_addr: str
    to_addr: str
    cc: str
    subject: str
    body_text: str
    body_html: str
    date: str
    in_reply_to: str = ""
    references: str = ""
    has_attachments: bool = False


class IMAPClient:
    """Async IMAP client for checking inbox."""

    def __init__(self, host: str, port: int, user: str, password: str):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self._client: IMAP4_SSL | None = None

    @classmethod
    def from_account(cls, account) -> "IMAPClient":
        return cls(account.imap_host, account.imap_port, account.imap_user, account.imap_password)

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

    async def fetch_all(self) -> list[EmailMessage]:
        """Fetch all emails from inbox."""
        return await self._fetch_by_criteria("ALL")

    async def fetch_since(self, since_date) -> list[EmailMessage]:
        """Fetch all emails since a given date (datetime or date object)."""
        date_str = since_date.strftime("%d-%b-%Y")
        return await self._fetch_by_criteria(f"SINCE {date_str}")

    async def _fetch_by_criteria(self, criteria: str) -> list[EmailMessage]:
        """Fetch emails matching IMAP search criteria."""
        if not self._client:
            await self.connect()

        result, data = await self._client.search(criteria)
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

                # aioimaplib returns a list of bytearray/bytes lines.
                # Find the largest one — that's the actual RFC822 email content.
                # Small items are IMAP protocol lines (e.g. "44 FETCH (RFC822 {size})").
                raw_bytes = None
                max_len = 0
                for item in msg_data:
                    if isinstance(item, (bytes, bytearray)) and len(item) > max_len:
                        raw_bytes = item
                        max_len = len(item)
                if raw_bytes is None:
                    continue

                msg = parser.parsebytes(raw_bytes)
                body_text = self._extract_body(msg, "text/plain")
                body_html = self._extract_body(msg, "text/html")

                has_attachments = False
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_disposition() == "attachment":
                            has_attachments = True
                            break

                message_id = msg.get("Message-ID", "") or f"<no-msgid-uid-{uid_str}@imap>"

                email_msg = EmailMessage(
                    uid=uid_str,
                    message_id=message_id,
                    from_addr=msg.get("From", ""),
                    to_addr=msg.get("To", ""),
                    cc=msg.get("Cc", "") or "",
                    subject=msg.get("Subject", "(no subject)"),
                    body_text=body_text[:5000],
                    body_html=body_html[:10000],
                    date=msg.get("Date", ""),
                    in_reply_to=msg.get("In-Reply-To", "") or "",
                    references=msg.get("References", "") or "",
                    has_attachments=has_attachments,
                )
                logger.info(
                    "Fetched email: from=%s cc=%s subject=%s date=%s has_attachments=%s",
                    email_msg.from_addr, email_msg.cc, email_msg.subject,
                    email_msg.date, email_msg.has_attachments,
                )
                emails.append(email_msg)
            except Exception:
                logger.exception("Error fetching email UID %s", uid)

        return emails

    def _extract_body(self, msg, content_type: str) -> str:
        """Extract body of given content type from email."""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == content_type:
                    try:
                        return part.get_content()
                    except Exception:
                        return ""
            return ""

        if msg.get_content_type() == content_type:
            try:
                return msg.get_content()
            except Exception:
                return ""
        return ""

    async def mark_as_seen(self, uid: str):
        """Mark a specific email as seen/read."""
        if self._client:
            await self._client.store(uid, "+FLAGS", "\\Seen")
