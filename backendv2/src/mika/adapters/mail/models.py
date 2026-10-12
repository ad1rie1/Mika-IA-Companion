"""Les tables du cache du courrier (ADR 0101), déclarées sur ``MailBase`` : les mails à leur place, les dossiers, ce
qui a été rendu (et ce qui l'a été sans être encore accusé), les brouillons, ce qui est parti, l'état de chaque compte,
l'empreinte de ce qui a été oublié, et les personnes que chaque ligne nomme.

**Une ligne se désigne par son ``id``** (l'ordre d'arrivée, là où il sert : les rendus pas encore accusés, les
pages) ; la clé naturelle (compte, dossier, UID ; Message-ID d'un envoi ; identifiant d'un brouillon) est une
contrainte d'unicité.

**Ce que le SQL calculait par des fonctions Python est calculé ici, à l'écriture** (``message_values``…) : les
textes repliés de la recherche (``fold_*`` : casse et accents ôtés par ``fold_text``, comparés avec ``instr`` ; la
recherche est la même sur les deux moteurs), le Message-ID nu du parent (``parent``), la clé de référence
(``ref_key``), l'empreinte du contenu (``fingerprint``), la forme historique de la référence (``historic``), le nom d'un
dossier « Envoyés » (``sent_name``) et les personnes nommées (``recipients`` : l'expéditeur, les destinataires et
les copies, une ligne chacun — ce qu'oublier et compter les correspondants parcourent).

**Une valeur venue d'ailleurs trop longue pour sa colonne** (un Message-ID, un nom de dossier, une adresse) n'est
ni refusée ni coupée au hasard : ``fit`` la remplace, de façon déterministe, par son début suivi d'une empreinte de
l'ensemble — la même à l'écriture et à la lecture, sur les deux moteurs ; deux valeurs distinctes restent distinctes.
Les bornes tiennent dans les index de MariaDB (au plus 768 caractères par index, en utf8mb4).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from sqlalchemy import Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from mika.ports.mail import Draft, Mail, Sent, addresses, assigned_ref, mail_ref, reference_key, split_ref
from mika.ports.paging import fold_text
from mika.ports.sql import Id, Key, LongBlob, LongText, MailBase, fit, table_args

# ── les bornes ──
#: une clé de compte (``ACCOUNT_KEY`` : 40 caractères)
ACCOUNT = 40
#: un nom de dossier IMAP (décodé)
FOLDER = 255
#: un Message-ID (``parse`` borne un en-tête à 300 caractères ; un Message-ID propre en a au plus 300)
MID = 300
#: la partie locale d'une référence (un Message-ID, ``#2`` compris, ou une empreinte)
LOCAL = 360
#: une référence (``compte:`` + sa partie locale)
REF = 400
#: une clé de référence (``reference_key`` : 200 caractères au plus)
REF_KEY = 200
#: une adresse (RFC 5321 : 64 + 1 + 255)
ADDRESS = 320
#: l'identifiant d'un brouillon
DRAFT = 64
#: un mot d'un vocabulaire fermé (rôle d'un dossier, état d'un brouillon)
WORD = 16
#: une empreinte (sha256, en hexadécimal)
PRINT = 64

# ── les personnes nommées ──
#: à quoi appartient une ligne de ``recipients`` (un entier : ``Browse`` le joint à une colonne calculée)
MESSAGE, SENT, DRAFTED = 0, 1, 2
#: l'expéditeur (d'un mail reçu) ou un destinataire (« À » et « Cc »)
FROM, TO = 0, 1

#: les noms d'un dossier « Envoyés » qu'on reconnaît sans son rôle
SENT_NAMES = frozenset({"sent", "sent items", "envoyés"})




def content_print(address: str, subject: str, date: int, body: str) -> str:
    """L'empreinte d'un contenu : deux copies du même mail (deux dossiers) ont la même."""
    raw = "\x1f".join((address or "", subject or "", str(date or 0), (body or "")[:20_000]))
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()


def sent_name(folder: str) -> bool:
    """Le nom dit-il « Envoyés » (quand le serveur n'a pas donné de rôle) ?"""
    return (folder or "").lower() in SENT_NAMES


def attachments_text(items: Iterable[Any]) -> str:
    return json.dumps([[a.name, a.mime, a.size] for a in items], ensure_ascii=False)


class MessageRow(MailBase):
    """Un mail à sa place : (compte, dossier, UID) — un UID ne vaut que dans son dossier (et son UIDVALIDITY) ; un
    UID négatif est une place provisoire (un mail déplacé dont on ne sait pas encore le nouvel UID)."""

    __tablename__ = "messages"
    __table_args__ = table_args(
        UniqueConstraint("account", "folder", "uid", name="uq_messages_place"),
        Index("ix_messages_message_id", "account", "message_id"),
        Index("ix_messages_ref", "account", "ref"),
        Index("ix_messages_ref_key", "ref_key"),
        Index("ix_messages_date", "date"),
        Index("ix_messages_folder_date", "account", "folder", "date"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    account: Mapped[str] = mapped_column(Key(ACCOUNT))
    folder: Mapped[str] = mapped_column(Key(FOLDER))
    uid: Mapped[int]
    message_id: Mapped[str] = mapped_column(Key(MID))
    #: la référence attribuée à l'arrivée (``assigned_ref``), et sa clé imprimable (``reference_key``)
    ref: Mapped[str] = mapped_column(Key(REF))
    ref_key: Mapped[str] = mapped_column(Key(REF_KEY))
    #: la référence a la forme historique ``compte:Message-ID`` (ce que désigne une référence sans compte)
    historic: Mapped[bool]
    #: un autre mail de ce compte porte le même Message-ID avec un autre contenu
    twin: Mapped[bool]
    sender: Mapped[str] = mapped_column(LongText)
    address: Mapped[str] = mapped_column(LongText)
    reply_to: Mapped[str] = mapped_column(LongText)
    dest: Mapped[str] = mapped_column(LongText)
    cc: Mapped[str] = mapped_column(LongText)
    subject: Mapped[str] = mapped_column(LongText)
    date: Mapped[int]
    body: Mapped[str] = mapped_column(LongText)
    html: Mapped[str] = mapped_column(LongText)
    has_html: Mapped[bool]
    complete: Mapped[bool]
    attachments: Mapped[str] = mapped_column(LongText)
    in_reply_to: Mapped[str] = mapped_column(LongText)
    #: le Message-ID nu du mail auquel il répond (``split_ref(in_reply_to)``), borné comme ``message_id``
    parent: Mapped[str] = mapped_column(Key(MID))
    refs: Mapped[str] = mapped_column(LongText)
    bulk: Mapped[bool]
    seen: Mapped[bool]
    flagged: Mapped[bool]
    answered: Mapped[bool]
    #: l'empreinte de son contenu (``content_print``)
    fingerprint: Mapped[str] = mapped_column(Key(PRINT))
    #: son dossier s'appelle « Envoyés » (``sent_name``)
    sent_name: Mapped[bool]
    fold_subject: Mapped[str] = mapped_column(LongText)
    fold_sender: Mapped[str] = mapped_column(LongText)
    fold_dest: Mapped[str] = mapped_column(LongText)
    fold_body: Mapped[str] = mapped_column(LongText)
    #: ``fold_text(expéditeur + " " + adresse)``
    fold_who: Mapped[str] = mapped_column(LongText)


class FolderRow(MailBase):
    """Un dossier d'un compte : son rôle, son curseur IMAP, ses compteurs."""

    __tablename__ = "folders"

    account: Mapped[str] = mapped_column(Key(ACCOUNT), primary_key=True)
    name: Mapped[str] = mapped_column(Key(FOLDER), primary_key=True)
    role: Mapped[str] = mapped_column(Key(WORD), default="")
    uidvalidity: Mapped[int] = mapped_column(default=0)
    uidnext: Mapped[int] = mapped_column(default=0)
    total: Mapped[int] = mapped_column(default=0)
    unseen: Mapped[int] = mapped_column(default=0)
    last_sync: Mapped[int] = mapped_column(default=0)


class HandedRow(MailBase):
    """Rendu pour de bon (accusé) : par la partie locale de sa référence, quel que soit son dossier."""

    __tablename__ = "handed"

    account: Mapped[str] = mapped_column(Key(ACCOUNT), primary_key=True)
    local: Mapped[str] = mapped_column(Key(LOCAL), primary_key=True)


class OfferedRow(MailBase):
    """Rendu par un relevé, pas encore accusé ; ``id`` dit l'ordre d'arrivée."""

    __tablename__ = "offered"
    __table_args__ = table_args(UniqueConstraint("account", "ref", name="uq_offered_ref"))

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    account: Mapped[str] = mapped_column(Key(ACCOUNT))
    ref: Mapped[str] = mapped_column(Key(REF))


class DraftRow(MailBase):
    """Un brouillon (``draft_id`` : son identifiant, ``Draft.id``)."""

    __tablename__ = "drafts"
    __table_args__ = table_args(UniqueConstraint("draft_id", name="uq_drafts_draft_id"))

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    draft_id: Mapped[str] = mapped_column(Key(DRAFT))
    account: Mapped[str] = mapped_column(Key(ACCOUNT))
    dest: Mapped[str] = mapped_column(LongText)
    cc: Mapped[str] = mapped_column(LongText)
    subject: Mapped[str] = mapped_column(LongText)
    body: Mapped[str] = mapped_column(LongText)
    reply_to: Mapped[str] = mapped_column(LongText)
    quote: Mapped[bool]
    author: Mapped[str] = mapped_column(LongText)
    created: Mapped[int]
    updated: Mapped[int]
    state: Mapped[str] = mapped_column(Key(WORD))
    sent_id: Mapped[str] = mapped_column(LongText)
    edited_by: Mapped[str] = mapped_column(LongText)
    original_body: Mapped[str] = mapped_column(LongText)
    #: ``fold_text(objet + " " + destinataires)``
    fold_search: Mapped[str] = mapped_column(LongText)


class StatusRow(MailBase):
    """L'état d'un compte : le dernier relevé, la dernière erreur."""

    __tablename__ = "status"

    account: Mapped[str] = mapped_column(Key(ACCOUNT), primary_key=True)
    last_poll: Mapped[int] = mapped_column(default=0)
    error: Mapped[str] = mapped_column(LongText, default="")
    error_at: Mapped[int] = mapped_column(default=0)


class SentRow(MailBase):
    """Un mail parti de sa boîte (``message_id`` : tel qu'il est parti), avec son message brut quand on l'a."""

    __tablename__ = "sent"
    __table_args__ = table_args(
        UniqueConstraint("message_id", name="uq_sent_message_id"),
        Index("ix_sent_ref_key", "ref_key"),
        Index("ix_sent_mid_key", "mid_key"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    message_id: Mapped[str] = mapped_column(Key(MID))
    #: le Message-ID nu (``split_ref(message_id)``), sa référence (``compte:`` + lui) et leurs clés imprimables
    local: Mapped[str] = mapped_column(Key(MID))
    ref: Mapped[str] = mapped_column(Key(REF))
    ref_key: Mapped[str] = mapped_column(Key(REF_KEY))
    mid_key: Mapped[str] = mapped_column(Key(REF_KEY))
    account: Mapped[str] = mapped_column(Key(ACCOUNT))
    dest: Mapped[str] = mapped_column(LongText)
    cc: Mapped[str] = mapped_column(LongText)
    subject: Mapped[str] = mapped_column(LongText)
    body: Mapped[str] = mapped_column(LongText)
    date: Mapped[int]
    in_reply_to: Mapped[str] = mapped_column(LongText)
    #: le Message-ID nu de ce à quoi il répond (``in_reply_to`` est une référence)
    parent: Mapped[str] = mapped_column(Key(MID))
    #: qui l'a écrit (vide : elle)
    author: Mapped[str] = mapped_column(LongText)
    draft: Mapped[str] = mapped_column(LongText)
    attachments: Mapped[str] = mapped_column(LongText)
    source: Mapped[bytes | None] = mapped_column(LongBlob)
    fold_subject: Mapped[str] = mapped_column(LongText)
    fold_dest: Mapped[str] = mapped_column(LongText)
    fold_body: Mapped[str] = mapped_column(LongText)


class ForgottenRow(MailBase):
    """L'empreinte d'un mail oublié : une relecture du serveur ne le ramène pas."""

    __tablename__ = "forgotten"

    account: Mapped[str] = mapped_column(Key(ACCOUNT), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(Key(PRINT), primary_key=True)


class RecipientRow(MailBase):
    """Une personne nommée par une ligne (``kind`` : ``MESSAGE``, ``SENT`` ou ``DRAFTED`` ; ``owner`` : son ``id``) :
    l'expéditeur d'un mail (``FROM``), ou l'un de ses destinataires, copies comprises (``TO``)."""

    __tablename__ = "recipients"
    __table_args__ = table_args(
        Index("ix_recipients_owner", "kind", "owner"),
        Index("ix_recipients_address", "address"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    kind: Mapped[int]
    owner: Mapped[int]
    role: Mapped[int]
    #: en minuscules, bornée par ``fit``
    address: Mapped[str] = mapped_column(Key(ADDRESS))
    name: Mapped[str] = mapped_column(LongText)
    #: ``fold_text(nom + " " + adresse)``
    fold_who: Mapped[str] = mapped_column(LongText)


# ── ce qu'une ligne calcule à l'écriture ──
def message_values(m: Mail, uid: int, ref: str, twin: bool) -> dict[str, Any]:
    """Les colonnes d'un mail gardé à cette place, sous cette référence."""
    account, mid = fit(m.account, ACCOUNT), fit(m.message_id, MID)
    ref = fit(ref, REF)
    return dict(
        account=account, folder=fit(m.folder, FOLDER), uid=uid, message_id=mid, ref=ref,
        ref_key=fit(reference_key(ref), REF_KEY), historic=ref == mail_ref(account, mid), twin=twin,
        sender=m.sender or "", address=m.address or "", reply_to=m.reply_to or "", dest=m.to or "", cc=m.cc or "",
        subject=m.subject or "", date=m.date or 0, body=m.body or "", html=m.html or "", has_html=m.has_html,
        complete=m.complete, attachments=attachments_text(m.attachments), in_reply_to=m.in_reply_to or "",
        parent=fit(split_ref(m.in_reply_to or "")[1], MID), refs=m.references or "", bulk=m.bulk, seen=m.seen,
        flagged=m.flagged, answered=m.answered, fingerprint=content_print(m.address, m.subject, m.date, m.body),
        sent_name=sent_name(m.folder), fold_subject=fold_text(m.subject or ""), fold_sender=fold_text(m.sender or ""),
        fold_dest=fold_text(m.to or ""), fold_body=fold_text(m.body or ""),
        fold_who=fold_text(f"{m.sender or ''} {m.address or ''}"))


def first_ref(account: str, message_id: str) -> str:
    """La référence que reçoit le premier mail d'un Message-ID (bornée comme la colonne)."""
    return fit(assigned_ref(account, message_id), REF)


def sent_values(s: Sent, source: bytes | None) -> dict[str, Any]:
    mid = fit(s.message_id, MID)
    account = fit(s.account, ACCOUNT)
    local = fit(split_ref(s.message_id)[1], MID)
    ref = fit(mail_ref(account, local), REF)
    return dict(
        message_id=mid, local=local, ref=ref, ref_key=fit(reference_key(ref), REF_KEY),
        mid_key=fit(reference_key(mid), REF_KEY), account=account, dest=s.to or "", cc=s.cc or "",
        subject=s.subject or "", body=s.body or "", date=s.date or 0, in_reply_to=s.in_reply_to or "",
        parent=fit(split_ref(s.in_reply_to or "")[1], MID), author=s.by or "", draft=s.draft or "",
        attachments=attachments_text(s.attachments), source=source, fold_subject=fold_text(s.subject or ""),
        fold_dest=fold_text(s.to or ""), fold_body=fold_text(s.body or ""))


def draft_values(d: Draft) -> dict[str, Any]:
    return dict(
        draft_id=fit(d.id, DRAFT), account=fit(d.account, ACCOUNT), dest=d.to or "", cc=d.cc or "",
        subject=d.subject or "", body=d.body or "", reply_to=d.reply_to or "", quote=d.quote, author=d.author or "",
        created=d.created or 0, updated=d.updated or 0, state=fit(d.state or "brouillon", WORD),
        sent_id=d.sent_id or "", edited_by=d.edited_by or "", original_body=d.original_body or "",
        fold_search=fold_text(f"{d.subject or ''} {d.to or ''}"))


def people(kind: int, owner: int, *, to: str, cc: str, sender: str = "", address: str = "") -> list[dict[str, Any]]:
    """Les lignes de ``recipients`` d'une ligne : l'expéditeur (s'il a une adresse), puis chaque adresse de « À »
    et de « Cc », lues ensemble comme un en-tête — sans virgule au bord : la lecture stricte des adresses ne rend
    rien d'une liste qui finit par une virgule (« À » rempli, « Cc » vide)."""
    rows = []
    if sender or address:
        found = fit((address or "").lower(), ADDRESS)
        if "@" in found:
            rows.append(dict(kind=kind, owner=owner, role=FROM, address=found, name=sender or "",
                             fold_who=fold_text(f"{sender or ''} {found}")))
    for name, addr in addresses(f"{to or ''},{cc or ''}".strip(",")):
        found = fit(addr, ADDRESS)
        rows.append(dict(kind=kind, owner=owner, role=TO, address=found, name=name,
                         fold_who=fold_text(f"{name} {found}")))
    return rows


__all__ = [
    "ACCOUNT", "ADDRESS", "DRAFT", "DRAFTED", "FOLDER", "FROM", "LOCAL", "MESSAGE", "MID", "PRINT", "REF", "REF_KEY",
    "SENT", "SENT_NAMES", "TO", "WORD",
    "DraftRow", "FolderRow", "ForgottenRow", "HandedRow", "MessageRow", "OfferedRow", "RecipientRow", "SentRow",
    "StatusRow", "attachments_text", "content_print", "draft_values", "first_ref", "fit", "message_values", "people",
    "sent_name", "sent_values",
]
