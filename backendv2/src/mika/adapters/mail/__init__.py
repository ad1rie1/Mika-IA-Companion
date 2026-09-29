"""Le courrier réel : IMAP pour lire, SMTP pour envoyer (bibliothèque
standard, dans un fil), un cache SQLite à part pour ce qui est arrivé.

- **Chaque mail n'est rendu qu'une fois** (``fetch_new``) : le cache retient
  les identifiants déjà remis. Au premier relevé, on ne remonte que quelques
  jours — pas toute la boîte.
- **UID**, jamais numéro de séquence : un numéro glisse dès qu'un message est
  supprimé ailleurs.
- La configuration est relue à chaque relevé (changer de compte ne demande
  pas de redémarrer).
"""

from __future__ import annotations

import asyncio
import email.utils
import html
import imaplib
import re
import smtplib
import sqlite3
import ssl
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from mika.ports.mail import Mail

BODY_MAX = 20_000


class MailConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    address: str = ""
    imap_host: str = ""
    imap_port: int = 993
    imap_ssl: bool = True
    user: str = ""
    password: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    #: « ssl » (port 465), « starttls » (587), « none » (tests)
    smtp_security: str = "starttls"
    since_days: int = 2
    folder: str = "INBOX"

    @property
    def ready(self) -> bool:
        return bool(self.imap_host and self.user)


def _text_of(msg: Any) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and part.get_content_disposition() != "attachment":
                return str(part.get_content())
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return _strip_html(str(part.get_content()))
        return ""
    if msg.get_content_type() == "text/html":
        return _strip_html(str(msg.get_content()))
    return str(msg.get_content())


def _strip_html(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", raw)
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", text))
    return re.sub(r"\s*\n\s*", "\n", re.sub(r"[ \t]+", " ", text)).strip()


def parse(raw: bytes, uid: str = "") -> Mail:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    sender = str(msg.get("From", ""))
    address = email.utils.parseaddr(sender)[1].lower()
    date = 0
    try:
        dt = email.utils.parsedate_to_datetime(str(msg.get("Date", "")))
        date = int(dt.timestamp() * 1_000_000)
    except (TypeError, ValueError, IndexError):
        pass
    try:
        body = _text_of(msg)
    except (LookupError, UnicodeError):
        body = ""
    bulk = bool(msg.get("List-Unsubscribe")) or str(msg.get("Precedence", "")).lower() in ("bulk", "list") \
        or address.startswith(("noreply", "no-reply", "ne-pas-repondre"))
    return Mail(
        message_id=str(msg.get("Message-ID", "") or f"<uid-{uid}@imap>").strip(), sender=sender[:200],
        address=address, subject=str(msg.get("Subject", "") or "(sans objet)")[:300], date=date,
        body=body.strip()[:BODY_MAX], to=str(msg.get("To", ""))[:300],
        in_reply_to=str(msg.get("In-Reply-To", "") or "").strip(), bulk=bulk)


class ImapSmtpMail:
    def __init__(self, config: Callable[[], MailConfig], cache: Path, *,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._config = config
        self._now = now
        cache.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(cache), check_same_thread=False)
        self._db.executescript(
            "CREATE TABLE IF NOT EXISTS mails(message_id TEXT PRIMARY KEY, uid TEXT, sender TEXT, address TEXT,"
            " subject TEXT, date INTEGER, body TEXT, dest TEXT, in_reply_to TEXT, bulk INTEGER, seen_at TEXT);"
            "CREATE TABLE IF NOT EXISTS uids(uid TEXT PRIMARY KEY);")
        self._lock = asyncio.Lock()

    def configured(self) -> bool:
        return self._config().ready

    # ── lire ──
    async def fetch_new(self, limit: int) -> list[Mail]:
        cfg = self._config()
        if not cfg.ready:
            return []
        async with self._lock:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._fetch_sync, cfg, limit)

    def _fetch_sync(self, cfg: MailConfig, limit: int) -> list[Mail]:
        box: imaplib.IMAP4 = (imaplib.IMAP4_SSL(cfg.imap_host, cfg.imap_port, ssl_context=ssl.create_default_context())
                              if cfg.imap_ssl else imaplib.IMAP4(cfg.imap_host, cfg.imap_port))
        try:
            box.login(cfg.user, cfg.password)
            box.select(cfg.folder, readonly=True)
            since = (self._now() - timedelta(days=max(0, cfg.since_days))).strftime("%d-%b-%Y")
            status, data = box.uid("SEARCH", None, f"SINCE {since}")
            if status != "OK" or not data or not data[0]:
                return []
            known = {r[0] for r in self._db.execute("SELECT uid FROM uids")}
            fresh = [u.decode() for u in data[0].split() if u.decode() not in known][:limit]
            out: list[Mail] = []
            for uid in fresh:
                status, parts = box.uid("FETCH", uid, "(RFC822)")
                raw = next((p[1] for p in parts or () if isinstance(p, tuple) and len(p) > 1), None)
                self._db.execute("INSERT OR IGNORE INTO uids(uid) VALUES(?)", (uid,))
                if status != "OK" or not isinstance(raw, bytes | bytearray):
                    continue
                mail = parse(bytes(raw), uid)
                self._store(mail, uid)
                out.append(mail)
            self._db.commit()
            return out
        finally:
            try:
                box.logout()
            except (imaplib.IMAP4.error, OSError):
                pass

    def _store(self, m: Mail, uid: str) -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO mails VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (m.message_id, uid, m.sender, m.address, m.subject, m.date, m.body, m.to, m.in_reply_to, int(m.bulk),
             self._now().isoformat()))

    @staticmethod
    def _row(r: tuple[Any, ...]) -> Mail:
        return Mail(message_id=r[0], sender=r[2], address=r[3], subject=r[4], date=r[5], body=r[6], to=r[7],
                    in_reply_to=r[8], bulk=bool(r[9]))

    async def get(self, message_id: str) -> Mail | None:
        return self.cached_one(message_id)

    async def recent(self, limit: int) -> list[Mail]:
        return self.cached(limit)

    def cached_one(self, message_id: str) -> Mail | None:
        rows = self._db.execute("SELECT * FROM mails WHERE message_id=?", (message_id,)).fetchall()
        return self._row(rows[0]) if rows else None

    def cached(self, limit: int) -> list[Mail]:
        rows = self._db.execute("SELECT * FROM mails ORDER BY date DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
        return [self._row(r) for r in rows]

    # ── envoyer ──
    async def send(self, to: str, subject: str, body: str, in_reply_to: str = "") -> str:
        cfg = self._config()
        if not cfg.smtp_host:
            raise RuntimeError("aucun serveur d'envoi configuré")
        msg = EmailMessage()
        msg["From"] = cfg.address or cfg.user
        msg["To"] = to
        msg["Subject"] = subject
        msg["Message-ID"] = email.utils.make_msgid(domain=(cfg.address or cfg.user).split("@")[-1] or "mika.local")
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        msg.set_content(body)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._send_sync, cfg, msg)
        return str(msg["Message-ID"])

    @staticmethod
    def _send_sync(cfg: MailConfig, msg: EmailMessage) -> None:
        if cfg.smtp_security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=30,
                                                    context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30)
        try:
            if cfg.smtp_security == "starttls":
                server.starttls(context=ssl.create_default_context())
            if cfg.user and cfg.password:
                server.login(cfg.user, cfg.password)
            server.send_message(msg)
        finally:
            try:
                server.quit()
            except (smtplib.SMTPException, OSError):
                pass

    def close(self) -> None:
        self._db.close()
