"""Lire un mail brut : en-têtes utiles, texte brut (même d'un mail HTML, sans
scripts ni styles), pièces jointes (nom, type, taille — jamais leur contenu),
envoi de masse reconnu.

Le texte d'un mail HTML se lit en **une passe linéaire** sur une source bornée
(``ports.preprocess.html_text``) : un mail de 5 Mo bâti pour faire revenir une
expression régulière en arrière ne fige plus rien. Un mail sans Message-ID
reçoit un identifiant tiré de son contenu (le même mail rangé dans deux
dossiers garde le même)."""

from __future__ import annotations

import email.utils
import hashlib
from email import policy
from email.parser import BytesParser
from typing import Any

from mika.ports.mail import Attachment, File, Mail
from mika.ports.preprocess import html_text

BODY_MAX = 20_000
HTML_MAX = 200_000
HEADER_MAX = 300
_NOREPLY = ("noreply", "no-reply", "ne-pas-repondre", "nepasrepondre", "donotreply", "do-not-reply",
            "mailer-daemon")


def strip_html(raw: str) -> str:
    """Le texte d'un corps HTML, en temps linéaire sur une source bornée."""
    return html_text(raw)


def _text_of(msg: Any) -> tuple[str, bool]:
    """Le texte du mail, et s'il avait une version HTML."""
    rich = msg.get_body(preferencelist=('html',))
    body = msg.get_body(preferencelist=('plain', 'html'))
    if body is None:
        return "", rich is not None
    text = str(body.get_content())
    return strip_html(text) if body.get_content_type() == "text/html" else text, rich is not None


def _attachment_parts(msg: Any):
    # Ne pas descendre dans un message joint : il constitue un seul fichier .eml.
    if msg.get_content_disposition() == "attachment" or msg.get_filename():
        yield msg
    elif msg.is_multipart():
        for child in msg.iter_parts():
            yield from _attachment_parts(child)


def _attachment_data(part: Any) -> bytes:
    if part.is_multipart():
        if part.get_content_type() == "message/rfc822":
            return b"\r\n".join(child.as_bytes(policy=policy.SMTP) for child in part.iter_parts())
        return part.as_bytes(policy=policy.SMTP)
    return part.get_payload(decode=True) or b""


def _attachments(msg: Any) -> tuple[Attachment, ...]:
    out = []
    for part in _attachment_parts(msg):
        name = part.get_filename()
        try:
            size = len(_attachment_data(part))
        except (TypeError, ValueError):
            size = 0
        out.append(Attachment(str(name or "(sans nom)")[:200], part.get_content_type()[:100], size))
    return tuple(out)


def _header(msg: Any, name: str) -> str:
    try:
        return " ".join(str(msg.get(name, "") or "").split())[:HEADER_MAX]
    except (TypeError, ValueError, IndexError):
        return ""


def parse(raw: bytes, uid: str = "", *, account: str = "", folder: str = "", complete: bool = False) -> Mail:
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
    rich = ""
    part = msg.get_body(preferencelist=('html',))
    if part is not None:
        try:
            rich = str(part.get_content())
        except (LookupError, UnicodeError):
            pass
    try:
        attachments = _attachments(msg)
    except (LookupError, UnicodeError):
        attachments = ()
    auto = _header(msg, "Auto-Submitted").lower()
    bulk = bool(msg.get("List-Unsubscribe")) or _header(msg, "Precedence").lower() in ("bulk", "list", "junk") \
        or (auto not in ("", "no")) or address.split("@")[0].startswith(_NOREPLY)
    message_id = _header(msg, "Message-ID") or f"<sans-id-{hashlib.sha256(raw).hexdigest()[:20]}@mika>"
    return Mail(
        message_id=message_id, sender=sender[:200], address=address, subject=_header(msg, "Subject") or "(sans objet)",
        date=date, body=body.strip() if complete else body.strip()[:BODY_MAX], to=_header(msg, "To"), in_reply_to=_header(msg, "In-Reply-To"),
        bulk=bulk, account=account, folder=folder, cc=_header(msg, "Cc"), reply_to=_header(msg, "Reply-To"),
        references=" ".join(str(msg.get("References", "") or "").split())[:2000], attachments=attachments,
        has_html=has_html, html=rich if complete else rich[:HTML_MAX],
        complete=complete or len(body.strip()) <= BODY_MAX and len(rich) <= HTML_MAX)


def attachment_files(raw: bytes) -> tuple[File, ...]:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    files = []
    for part in _attachment_parts(msg):
        files.append(File(str(part.get_filename() or "piece-jointe"), part.get_content_type(), _attachment_data(part)))
    return tuple(files)
