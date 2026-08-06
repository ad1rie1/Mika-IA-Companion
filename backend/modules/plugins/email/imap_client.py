import logging
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser

from aioimaplib import IMAP4_SSL

from configs import secrets

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
        # Le mot de passe est chiffré au repos, comme tout champ ``sensitive``
        # du registre de configuration. ``decrypt`` rend la valeur telle quelle
        # si la ligne est antérieure au chiffrement.
        password = secrets.decrypt(account.imap_password) if account.imap_password else ""
        return cls(account.imap_host, account.imap_port, account.imap_user, password)

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
        return await self.fetch_uids(await self.list_uids("ALL"))

    async def fetch_since(self, since_date) -> list[EmailMessage]:
        """Fetch all emails since a given date (datetime or date object)."""
        return await self.fetch_uids(await self.list_uids_since(since_date))

    async def list_uids(self, criteria: str = "ALL") -> list[str]:
        """Liste les UID correspondant au critère, sans rien télécharger.

        Séparé du téléchargement parce que c'est lui qui coûte : un SEARCH
        rend cinq mille identifiants en un aller-retour, là où le FETCH
        correspondant en demande cinq mille. L'appelant peut donc décider
        *avant* de payer ce qu'il va vraiment chercher.

        ``UID SEARCH`` et non ``SEARCH`` : ce dernier rend des **numéros de
        séquence**, qui se décalent dès qu'un message est supprimé ailleurs
        (le client de messagerie de l'utilisateur, une règle serveur). Le
        module s'en sert pour savoir ce qu'il a déjà importé — sur un numéro
        qui glisse, ce repère désigne le tour suivant un autre message, et
        un courrier jamais importé serait sauté silencieusement. Un UID est
        stable et jamais réattribué.
        """
        if not self._client:
            await self.connect()

        result, data = await self._client.uid_search(criteria)
        if result != "OK" or not data or not data[0]:
            return []

        return [
            uid.decode() if isinstance(uid, bytes) else uid
            for uid in data[0].split()
        ]

    async def list_uids_since(self, since_date) -> list[str]:
        """Identifiants des messages reçus depuis une date (jour près, IMAP)."""
        date_str = since_date.strftime("%d-%b-%Y")
        return await self.list_uids(f"SINCE {date_str}")

    async def fetch_uids(self, uids: list[str]) -> list[EmailMessage]:
        """Télécharge et analyse les messages désignés."""
        if not uids:
            return []
        if not self._client:
            await self.connect()

        emails = []
        parser = BytesParser(policy=policy.default)

        for uid_str in uids:
            try:
                result, msg_data = await self._client.uid("fetch", uid_str, "(RFC822)")
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
                logger.exception("Error fetching email UID %s", uid_str)

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
            # UID STORE : l'identifiant vient de `list_uids`, donc d'un UID
            # SEARCH. Un STORE simple le lirait comme un numéro de séquence
            # et marquerait un autre message.
            await self._client.uid("store", uid, "+FLAGS", "\\Seen")
