"""Lire un mail brut : en-têtes utiles, texte brut (même d'un mail HTML, sans
scripts ni styles), pièces jointes (nom, type, taille — jamais leur contenu),
envoi de masse reconnu."""

from __future__ import annotations

import email.utils
import html
import re
from email import policy
from email.parser import BytesParser
from typing import Any

from mika.ports.mail import Attachment, Mail

BODY_MAX = 20_000
HEADER_MAX = 300
ATTACHMENTS_MAX = 20
_NOREPLY = ("noreply", "no-reply", "ne-pas-repondre", "nepasrepondre", "donotreply", "do-not-reply",
            "mailer-daemon")


def strip_html(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", raw)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", text)
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", text))
    return re.sub(r"\s*\n\s*", "\n", re.sub(r"[ \t ]+", " ", text)).strip()


def _text_of(msg: Any) -> tuple[str, bool]:
    """Le texte du mail, et s'il avait une version HTML."""
    has_html = any(p.get_content_type() == "text/html" for p in msg.walk())
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and part.get_content_disposition() != "attachment":
                return str(part.get_content()), has_html
        for part in msg.walk():
            if part.get_content_type() == "text/html" and part.get_content_disposition() != "attachment":
                return strip_html(str(part.get_content())), has_html
        return "", has_html
    if msg.get_content_type() == "text/html":
        return strip_html(str(msg.get_content())), True
    return str(msg.get_content()), has_html


def _attachments(msg: Any) -> tuple[Attachment, ...]:
    out = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        name = part.get_filename()
        if part.get_content_disposition() != "attachment" and not name:
            continue
        try:
            size = len(part.get_payload(decode=True) or b"")
        except (TypeError, ValueError):
            size = 0
        out.append(Attachment(str(name or "(sans nom)")[:200], part.get_content_type()[:100], size))
        if len(out) >= ATTACHMENTS_MAX:
            break
    return tuple(out)


def _header(msg: Any, name: str) -> str:
    try:
        return " ".join(str(msg.get(name, "") or "").split())[:HEADER_MAX]
    except (TypeError, ValueError, IndexError):
        return ""


def parse(raw: bytes, uid: str = "", *, account: str = "", folder: str = "") -> Mail:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    sender = _header(msg, "From")
    address = email.utils.parseaddr(sender)[1].lower()
    date = 0
    try:
        dt = email.utils.parsedate_to_datetime(str(msg.get("Date", "")))
        date = int(dt.timestamp() * 1_000_000)
    except (TypeError, ValueError, IndexError):
        pass
    try:
        body, has_html = _text_of(msg)
    except (LookupError, UnicodeError):
        body, has_html = "", False
    try:
        attachments = _attachments(msg)
    except (LookupError, UnicodeError):
        attachments = ()
    auto = _header(msg, "Auto-Submitted").lower()
    bulk = bool(msg.get("List-Unsubscribe")) or _header(msg, "Precedence").lower() in ("bulk", "list", "junk") \
        or (auto not in ("", "no")) or address.split("@")[0].startswith(_NOREPLY)
    message_id = _header(msg, "Message-ID") or f"<uid-{uid or 'x'}@imap>"
    return Mail(
        message_id=message_id, sender=sender[:200], address=address, subject=_header(msg, "Subject") or "(sans objet)",
        date=date, body=body.strip()[:BODY_MAX], to=_header(msg, "To"), in_reply_to=_header(msg, "In-Reply-To"),
        bulk=bulk, account=account, folder=folder, cc=_header(msg, "Cc"), reply_to=_header(msg, "Reply-To"),
        references=" ".join(str(msg.get("References", "") or "").split())[:2000], attachments=attachments,
        has_html=has_html)
