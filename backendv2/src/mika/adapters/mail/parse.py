"""Lire un mail brut : en-têtes utiles, texte brut (même d'un mail HTML, sans
scripts ni styles), pièces jointes (nom, type, taille — jamais leur contenu),
envoi de masse reconnu.

``read`` rend aussi ses pièces avec leurs octets (``Part``), que le cache garde
(ADR 0172) : chaque pièce jointe, à son rang (celui du lien de
téléchargement), et chaque image intégrée que le HTML désigne par ``cid:``.
Elles ne vont qu'au cache, jamais au modèle.

Le texte d'un mail HTML se lit en **une passe linéaire** sur une source bornée
(``ports.preprocess.html_text``) : un mail de 5 Mo bâti pour faire revenir une
expression régulière en arrière ne fige plus rien. Un mail sans Message-ID
reçoit un identifiant tiré de son contenu (le même mail rangé dans deux
dossiers garde le même)."""

from __future__ import annotations

import email.utils
import hashlib
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class Part:
    """Une pièce d'un mail avec ses octets : une pièce jointe (``position`` : son rang parmi elles) ou une image
    intégrée (``position`` -1) ; ``content_id`` : son Content-ID nu, en minuscules (vide s'il n'en a pas) ;
    ``data`` à ``None`` : illisible."""

    position: int
    name: str
    mime: str
    content_id: str
    data: bytes | None


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


def _inline_parts(msg: Any):
    """Les images intégrées que le HTML désigne par leur Content-ID (celles qui sont aussi des pièces jointes à part)."""
    if msg.get_content_disposition() == "attachment" or msg.get_filename():
        return
    if msg.is_multipart():
        for child in msg.iter_parts():
            yield from _inline_parts(child)
    elif msg.get_content_maintype() == "image" and msg.get("Content-ID"):
        yield msg


def content_id(header: str) -> str:
    """Un Content-ID tel que ``cid:`` le désigne : sans chevrons ni espaces, en minuscules."""
    return header.strip().strip("<>").strip().lower()


def _cid(part: Any) -> str:
    try:
        return content_id(str(part.get("Content-ID", "") or ""))
    except (TypeError, ValueError, IndexError, LookupError):
        return ""


def _part(position: int, name: str, part: Any, read: Any) -> Part:
    try:
        data = read(part)
    except (TypeError, ValueError, LookupError):
        data = None
    return Part(position, name, part.get_content_type(), _cid(part), data)


def parts_of(msg: Any) -> tuple[Part, ...]:
    """Ses pièces jointes, à leur rang, puis ses images intégrées : ce que le cache garde."""
    try:
        attached = [_part(i, str(part.get_filename() or "piece-jointe"), part, _attachment_data)
                    for i, part in enumerate(_attachment_parts(msg))]
        inline = [_part(-1, "", part, lambda p: p.get_payload(decode=True) or b"") for part in _inline_parts(msg)]
    except (LookupError, UnicodeError):
        return ()
    return (*attached, *inline)


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
    return _mail(BytesParser(policy=policy.default).parsebytes(raw), raw, complete, account=account, folder=folder)


def read(raw: bytes, uid: str = "", *, account: str = "", folder: str = "",
         complete: bool = False) -> tuple[Mail, tuple[Part, ...]]:
    """Le mail (comme ``parse``) et ses pièces, avec leurs octets, en une seule lecture."""
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    return _mail(msg, raw, complete, account=account, folder=folder), parts_of(msg)


def _mail(msg: Any, raw: bytes, complete: bool, *, account: str = "", folder: str = "") -> Mail:
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
