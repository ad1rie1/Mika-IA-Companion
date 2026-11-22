"""L'annuaire, déclaré (ADR 0101, 0298) : la base ``contacts`` (``contacts.db`` sous SQLite, ``mika_contacts`` sous
MariaDB).

- ``contacts`` : un contact, une personne ou une organisation (``kind``) ; son nom (celui sous lequel on la voit le
  plus récemment ; une organisation, son domaine), son organisation (``org`` : la ligne d'une organisation, 0 :
  aucune), la personne de l'identité à qui il est relié (``person``), et ce qu'une recherche compare (``search`` :
  ses noms et ses identifiants, repliés), son poste et son service (ceux de la vue la plus récente qui les dit) —
  recalculés à chaque écriture qui le touche ;
- ``identifiers`` : un identifiant (sorte, valeur normalisée), à un seul contact (la clé unique) ; ``generic`` : une
  adresse générique rangée à son organisation ;
- ``sightings`` : où elle voit un identifiant — une source, un compte, combien, de quand à quand (µs, l'heure de la
  source), sous quel nom (et ce nom replié, ``fold``), avec quel poste, quel service et quelle entreprise (un profil
  Teams les dit) ; ``own`` : le compte le désigne lui-même (sa personne) ;
- ``threads`` : les conversations où elle voit un identifiant dans une vue (le téléphone : la clé opaque de la
  conversation, son titre de groupe, combien de messages, de quand à quand) — les plus récentes seulement ;
- ``dismissed`` : deux contacts qu'une opératrice a dits différents (les suggestions ne les rapprochent plus) ;
- ``cursors`` : où s'est arrêtée la lecture de chaque source ;
- ``forgotten`` : l'empreinte d'un identifiant oublié (jamais sa valeur) et l'instant de l'oubli ;
- ``notes`` : ce qu'elle sait d'un contact à partir de ce qu'elle lit (lot 6), chaque fait sous la vue d'où il vient ;
  ``notes_forgotten`` : l'empreinte des mots d'un fait oublié (jamais son texte) ; ``portraits`` : chaque passage du
  portrait sur une vue.

Ce qui se cherche est replié à l'écriture (``fold_text``) et comparé par ``instr`` : la même réponse sur les deux
moteurs. Une valeur venue d'ailleurs trop longue pour sa clé est ramenée à sa borne par ``fit``.
"""

from __future__ import annotations

from sqlalchemy import Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from mika.ports.sql import HANDLE_MAX, ContactsBase, Id, Key, LongText, fit, table_args

#: une sorte de contact, d'identifiant, une source (des mots courts)
WORD = 16
#: la valeur d'un identifiant (une adresse : 64 + 1 + 255)
VALUE = 320
#: la clé d'un compte (``ports.teams.ACCOUNT_KEY``, ``ports.mail.ACCOUNT_KEY`` : 40 au plus)
ACCOUNT = 40
#: la clé d'une personne de l'identité
PERSON = HANDLE_MAX
#: le nom d'un curseur
CURSOR = 64
#: une empreinte (sha256, en hexadécimal)
PRINT = 64
#: la clé d'une conversation (le téléphone : une empreinte en hexadécimal, ``app/phone.py``)
THREAD = 64
#: la référence d'un message (Teams, un mail, ``p<seq>``), l'identifiant d'un appel du modèle
REF = 200


class ContactRow(ContactsBase):
    __tablename__ = "contacts"
    __table_args__ = table_args(
        Index("ix_contacts_org", "org"),
        Index("ix_contacts_person", "person"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    kind: Mapped[str] = mapped_column(Key(WORD))
    name: Mapped[str] = mapped_column(LongText, default="")
    org: Mapped[int] = mapped_column(default=0)
    person: Mapped[str] = mapped_column(Key(PERSON), default="")
    search: Mapped[str] = mapped_column(LongText, default="")
    #: quand il est né (µs, l'horloge du serveur)
    created: Mapped[int] = mapped_column(default=0)
    #: son poste et son service (le lot des profils Teams : vides pour un contact d'avant)
    title: Mapped[str] = mapped_column(LongText, default="", server_default="")
    department: Mapped[str] = mapped_column(LongText, default="", server_default="")


class IdentifierRow(ContactsBase):
    __tablename__ = "identifiers"
    __table_args__ = table_args(
        UniqueConstraint("kind", "value", name="uq_identifiers_kind_value"),
        Index("ix_identifiers_contact", "contact"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    contact: Mapped[int]
    kind: Mapped[str] = mapped_column(Key(WORD))
    value: Mapped[str] = mapped_column(Key(VALUE))
    generic: Mapped[bool] = mapped_column(default=False)


class SightingRow(ContactsBase):
    __tablename__ = "sightings"
    __table_args__ = table_args(
        UniqueConstraint("identifier", "source", "account", name="uq_sightings_place"),
        Index("ix_sightings_source", "source", "account"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    identifier: Mapped[int]
    source: Mapped[str] = mapped_column(Key(WORD))
    account: Mapped[str] = mapped_column(Key(ACCOUNT))
    count: Mapped[int] = mapped_column(default=0)
    first: Mapped[int] = mapped_column(default=0)
    last: Mapped[int] = mapped_column(default=0)
    name: Mapped[str] = mapped_column(LongText, default="")
    #: ``name`` replié (une recherche faite pour quelqu'un ne compare que les noms de ses vues visibles)
    fold: Mapped[str] = mapped_column(LongText, default="")
    own: Mapped[bool] = mapped_column(default=False)
    #: ce que le dernier profil Teams de cette vue dit de son poste et de son service
    title: Mapped[str] = mapped_column(LongText, default="", server_default="")
    department: Mapped[str] = mapped_column(LongText, default="", server_default="")
    #: l'entreprise (repliée, ``ports.contacts.normalized``) que le dernier profil Teams de cette vue dit : ce qui
    #: prouve, à qui voit cette vue, que sa personne est de l'organisation de ce nom
    company: Mapped[str] = mapped_column(LongText, default="", server_default="")


class ThreadRow(ContactsBase):
    """Une conversation où elle voit un identifiant, dans une de ses vues (même identifiant, source et compte)."""

    __tablename__ = "threads"
    __table_args__ = table_args(
        UniqueConstraint("identifier", "source", "account", "thread", name="uq_threads_place"),
        Index("ix_threads_identifier", "identifier"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    identifier: Mapped[int]
    source: Mapped[str] = mapped_column(Key(WORD))
    account: Mapped[str] = mapped_column(Key(ACCOUNT))
    thread: Mapped[str] = mapped_column(Key(THREAD))
    #: le nom d'un groupe (vide : un tête-à-tête), le plus récent qu'on lui voit
    title: Mapped[str] = mapped_column(LongText, default="")
    grouped: Mapped[bool] = mapped_column(default=False)
    count: Mapped[int] = mapped_column(default=0)
    first: Mapped[int] = mapped_column(default=0)
    last: Mapped[int] = mapped_column(default=0)


class DismissedRow(ContactsBase):
    """Deux contacts dits différents (``a`` < ``b``)."""

    __tablename__ = "dismissed"

    a: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    b: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)


class CursorRow(ContactsBase):
    __tablename__ = "cursors"

    name: Mapped[str] = mapped_column(Key(CURSOR), primary_key=True)
    value: Mapped[int] = mapped_column(default=0)


class ForgottenRow(ContactsBase):
    """Un identifiant oublié, par l'empreinte de sa sorte et de sa valeur : ce qui le revoit daté d'avant ``until``
    (µs) ne le ramène pas."""

    __tablename__ = "forgotten"

    digest: Mapped[str] = mapped_column(Key(PRINT), primary_key=True)
    until: Mapped[int] = mapped_column(default=0)


class NoteRow(ContactsBase):
    """Un fait qu'elle tire de ce qu'un contact écrit (lot 6), sous la vue d'où il vient (``source``, ``account`` :
    qui la voit le voit) : son texte, sa sorte, sa confiance (en centièmes), le message qui le fonde (``ref``) et où il
    était (``place``), sa date (``said_at``), quand elle l'a appris (``at``), l'appel du modèle (``call_id``)."""

    __tablename__ = "notes"
    __table_args__ = table_args(
        Index("ix_notes_contact", "contact"),
        Index("ix_notes_place", "source", "account"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    contact: Mapped[int]
    source: Mapped[str] = mapped_column(Key(WORD))
    account: Mapped[str] = mapped_column(Key(ACCOUNT))
    text: Mapped[str] = mapped_column(LongText, default="")
    kind: Mapped[str] = mapped_column(Key(WORD), default="other")
    confidence: Mapped[int] = mapped_column(default=50)
    ref: Mapped[str] = mapped_column(Key(REF), default="")
    place: Mapped[str] = mapped_column(LongText, default="")
    said_at: Mapped[int] = mapped_column(default=0)
    at: Mapped[int] = mapped_column(default=0)
    call_id: Mapped[str] = mapped_column(Key(REF), default="")


class NoteForgottenRow(ContactsBase):
    """Un fait oublié d'un contact, par l'empreinte de ses mots (``ports.contacts.note_print``, jamais son texte) : le
    même fait, reformulé, ne se réapprend pas."""

    __tablename__ = "notes_forgotten"
    __table_args__ = table_args(Index("ix_notes_forgotten_contact", "contact"))

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    contact: Mapped[int]
    prints: Mapped[str] = mapped_column(LongText, default="")
    at: Mapped[int] = mapped_column(default=0)


class PortraitRow(ContactsBase):
    """Un passage du portrait sur une vue d'un contact (lot 6) : quand, jusqu'à quelle date il a lu, combien de
    messages, s'il a gardé des faits, l'appel du modèle — les plafonds par jour se comptent sur eux."""

    __tablename__ = "portraits"
    __table_args__ = table_args(
        Index("ix_portraits_place", "contact", "source", "account"),
        Index("ix_portraits_at", "at"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    contact: Mapped[int]
    source: Mapped[str] = mapped_column(Key(WORD))
    account: Mapped[str] = mapped_column(Key(ACCOUNT))
    at: Mapped[int] = mapped_column(default=0)
    upto: Mapped[int] = mapped_column(default=0)
    read: Mapped[int] = mapped_column(default=0)
    ok: Mapped[bool] = mapped_column(default=True)
    call_id: Mapped[str] = mapped_column(Key(REF), default="")


__all__ = [
    "ACCOUNT", "CURSOR", "PERSON", "PRINT", "REF", "THREAD", "VALUE", "WORD",
    "ContactRow", "CursorRow", "DismissedRow", "ForgottenRow", "IdentifierRow", "NoteForgottenRow", "NoteRow",
    "PortraitRow", "SightingRow", "ThreadRow", "fit",
]
