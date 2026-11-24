"""L'agenda, déclaré (ADR 0101, 0309) : la base ``agenda`` (``agenda.db`` sous SQLite, ``mika_agenda`` sous MariaDB).

- ``accounts`` : un compte d'agenda — sa sorte, à qui il est et son adresse à lui (tels que les réglages les disent :
  l'oubli s'en sert pour ne jamais vider l'agenda d'un compte à la personne oubliée), et sa synchro (la dernière
  réussie, le dernier essai, les échecs de suite, l'erreur en mots) ;
- ``calendars`` : un agenda, sous son compte — sa clé (``ports.agenda.calendar_key``), son identifiant chez le
  fournisseur, son nom, sa couleur chez lui, si on peut y écrire, son fuseau, s'il est le principal, si le
  fournisseur le coche, son curseur de synchro ;
- ``events`` : une ligne par événement simple, par série et par exception d'une série (``original`` : la clé de
  l'occurrence qu'elle remplace) — ses instants en µs UTC (``start_at``, ``end_at`` ; une journée entière à minuit
  UTC de ses dates) et son fuseau, la fin de sa dernière occurrence (``last_end`` : une série sans fin, ``FOREVER``),
  sa règle (RRULE, EXDATE, RDATE), son état, « occupé », « privé », son organisatrice, la réponse du compte de
  l'agenda (``response``), les rappels du fournisseur, ce que Mika y a mis (``added_by``, ``added_ref``,
  ``added_at``), l'agenda de l'organisatrice d'une copie d'invitation (``origin``), ce qu'en dit le fournisseur
  (``remote``, ``etag``, ``raw``) ; ``forgotten`` : son organisatrice est oubliée, il ne garde que son créneau ;
  ``remind`` : « Mika te le rappelle » pour cet événement (vide : le choix de son agenda), qui ne vit qu'ici — ni une
  synchronisation ni une écriture du fournisseur ne le touchent ;
- ``attendees`` : ses participantes, dans l'ordre (adresse, nom, clé de personne, réponse, facultative, le compte
  lui-même) ;
- ``forgotten`` : l'empreinte d'une adresse oubliée (jamais l'adresse) et l'instant de l'oubli — une synchronisation
  ne la ramène pas dans ce qui a été créé avant ;
- ``sync_notes`` : l'historique de la synchro de chaque compte (lot 5) — une relecture qui a changé quelque chose, la
  copie relue après une écriture, une panne et sa reprise, un agenda qu'on ne suit plus : son agenda (vide : tout le
  compte), quand, ce que c'était, combien d'événements, l'erreur en mots ; jamais un titre ni une adresse. Ce qui est
  plus ancien que sa durée de garde part à chaque ligne ajoutée.

Une période se lit par ``events.calendar`` et ``last_end`` (ce qui finit après son début), puis ``start_at`` (ce qui
commence avant sa fin) : la base ne rend que ce qui la touche, les séries se développent ensuite. Une valeur venue
d'ailleurs trop longue pour sa clé est ramenée à sa borne par ``fit``.
"""

from __future__ import annotations

from sqlalchemy import Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from mika.ports.agenda import LOCAL_MAX, SYSTEM_PREFIX
from mika.ports.sql import HANDLE_MAX, AgendaBase, Id, Key, LongText, fit, table_args

#: une sorte, un état, une réponse (des mots courts)
WORD = 16
#: la clé d'un compte (``moi:`` et la clé d'une personne, pour un compte du système)
ACCOUNT = len(SYSTEM_PREFIX) + HANDLE_MAX
#: la clé d'un agenda (``<compte>~<clé courte>``)
CALENDAR = ACCOUNT + 1 + LOCAL_MAX
#: l'UID d'un événement, son identifiant chez le fournisseur
UID = 400
#: la clé d'une occurrence (``20261123T070000Z``)
OCCURRENCE = 20
#: une adresse (64 + 1 + 255)
ADDRESS = 320
#: la clé d'une personne de l'identité
PERSON = HANDLE_MAX
#: une empreinte (sha256, en hexadécimal)
PRINT = 64


class AccountRow(AgendaBase):
    __tablename__ = "accounts"

    key: Mapped[str] = mapped_column(Key(ACCOUNT), primary_key=True)
    kind: Mapped[str] = mapped_column(Key(WORD))
    owner: Mapped[str] = mapped_column(Key(PERSON), default="")
    address: Mapped[str] = mapped_column(Key(ADDRESS), default="")
    #: décoché dans les réglages : il ne se synchronise plus, et la santé ne le compte pas
    enabled: Mapped[bool] = mapped_column(default=True)
    #: la dernière synchronisation réussie, le dernier essai (µs, l'horloge du serveur)
    synced_at: Mapped[int] = mapped_column(default=0)
    tried_at: Mapped[int] = mapped_column(default=0)
    failures: Mapped[int] = mapped_column(default=0)
    error: Mapped[str] = mapped_column(LongText, default="")
    created: Mapped[int] = mapped_column(default=0)


class CalendarRow(AgendaBase):
    __tablename__ = "calendars"
    __table_args__ = table_args(
        UniqueConstraint("key", name="uq_calendars_key"),
        Index("ix_calendars_account", "account"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    key: Mapped[str] = mapped_column(Key(CALENDAR))
    account: Mapped[str] = mapped_column(Key(ACCOUNT))
    remote: Mapped[str] = mapped_column(LongText, default="")
    name: Mapped[str] = mapped_column(LongText, default="")
    color: Mapped[str] = mapped_column(LongText, default="")
    writable: Mapped[bool] = mapped_column(default=True)
    zone: Mapped[str] = mapped_column(LongText, default="")
    #: l'agenda principal du compte (« Mon agenda », le principal de Google)
    main: Mapped[bool] = mapped_column(default=False)
    selected: Mapped[bool] = mapped_column(default=True)
    cursor: Mapped[str] = mapped_column(LongText, default="")
    synced_at: Mapped[int] = mapped_column(default=0)
    created: Mapped[int] = mapped_column(default=0)
    #: le nom que la personne lui a donné dans Mika (un agenda branché ; vide : celui du fournisseur, ``name``)
    alias: Mapped[str] = mapped_column(LongText, default="")
    #: les rappels que le fournisseur pose sur un événement qui suit ceux de l'agenda (Google) : une liste JSON de
    #: paires [minutes, méthode]
    reminders: Mapped[str] = mapped_column(LongText, default="")


class EventRow(AgendaBase):
    __tablename__ = "events"
    __table_args__ = table_args(
        UniqueConstraint("calendar", "uid", "original", name="uq_events_calendar_uid_original"),
        Index("ix_events_calendar_last_end", "calendar", "last_end"),
        Index("ix_events_calendar_start_at", "calendar", "start_at"),
        Index("ix_events_calendar_response", "calendar", "response"),
        Index("ix_events_calendar_remote", "calendar", "remote"),
        Index("ix_events_uid", "uid"),
        Index("ix_events_organizer_address", "organizer_address"),
        Index("ix_events_organizer_person", "organizer_person"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    #: la ligne de son agenda (``calendars.id``)
    calendar: Mapped[int]
    uid: Mapped[str] = mapped_column(Key(UID))
    original: Mapped[str] = mapped_column(Key(OCCURRENCE), default="")
    #: la copie d'une invitation du système : la ligne de l'agenda de l'organisatrice (0 : aucune)
    origin: Mapped[int] = mapped_column(default=0)
    title: Mapped[str] = mapped_column(LongText, default="")
    location: Mapped[str] = mapped_column(LongText, default="")
    description: Mapped[str] = mapped_column(LongText, default="")
    conference: Mapped[str] = mapped_column(LongText, default="")
    start_at: Mapped[int] = mapped_column(default=0)
    end_at: Mapped[int] = mapped_column(default=0)
    all_day: Mapped[bool] = mapped_column(default=False)
    zone: Mapped[str] = mapped_column(LongText, default="")
    last_end: Mapped[int] = mapped_column(default=0)
    rule: Mapped[str] = mapped_column(LongText, default="")
    #: des listes JSON de clés d'occurrence
    exdates: Mapped[str] = mapped_column(LongText, default="")
    rdates: Mapped[str] = mapped_column(LongText, default="")
    status: Mapped[str] = mapped_column(Key(WORD), default="")
    busy: Mapped[bool] = mapped_column(default=True)
    private: Mapped[bool] = mapped_column(default=False)
    response: Mapped[str] = mapped_column(Key(WORD), default="")
    organizer_address: Mapped[str] = mapped_column(Key(ADDRESS), default="")
    organizer_name: Mapped[str] = mapped_column(LongText, default="")
    organizer_person: Mapped[str] = mapped_column(Key(PERSON), default="")
    #: les rappels du fournisseur : une liste JSON de paires [minutes avant, méthode] (``ports.agenda.Alert``)
    reminders: Mapped[str] = mapped_column(LongText, default="")
    #: il suit les rappels de son agenda (Google : ``useDefault``), que ``calendars.reminders`` dit
    reminders_default: Mapped[bool] = mapped_column(default=False)
    added_by: Mapped[str] = mapped_column(Key(WORD), default="")
    added_ref: Mapped[str] = mapped_column(LongText, default="")
    added_at: Mapped[int] = mapped_column(default=0)
    remote: Mapped[str] = mapped_column(Key(UID), default="")
    etag: Mapped[str] = mapped_column(LongText, default="")
    raw: Mapped[str] = mapped_column(LongText, default="")
    sequence: Mapped[int] = mapped_column(default=0)
    #: sa création chez le fournisseur (sinon, quand la base l'a vu la première fois), sa dernière modification
    created: Mapped[int] = mapped_column(default=0)
    updated: Mapped[int] = mapped_column(default=0)
    forgotten: Mapped[bool] = mapped_column(default=False)
    #: « Mika te le rappelle » pour cet événement (``ports.agenda.REMINDERS`` ; vide : le choix de son agenda)
    remind: Mapped[str] = mapped_column(Key(WORD), default="")


class AttendeeRow(AgendaBase):
    __tablename__ = "attendees"
    __table_args__ = table_args(
        Index("ix_attendees_event", "event"),
        Index("ix_attendees_address", "address"),
        Index("ix_attendees_person", "person"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    event: Mapped[int]
    position: Mapped[int] = mapped_column(default=0)
    address: Mapped[str] = mapped_column(Key(ADDRESS), default="")
    name: Mapped[str] = mapped_column(LongText, default="")
    person: Mapped[str] = mapped_column(Key(PERSON), default="")
    response: Mapped[str] = mapped_column(Key(WORD), default="")
    optional: Mapped[bool] = mapped_column(default=False)
    me: Mapped[bool] = mapped_column(default=False)


class ForgottenRow(AgendaBase):
    __tablename__ = "forgotten"

    digest: Mapped[str] = mapped_column(Key(PRINT), primary_key=True)
    until: Mapped[int] = mapped_column(default=0)


class SyncNoteRow(AgendaBase):
    __tablename__ = "sync_notes"
    __table_args__ = table_args(
        Index("ix_sync_notes_account_at", "account", "at"),
        Index("ix_sync_notes_at", "at"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    account: Mapped[str] = mapped_column(Key(ACCOUNT))
    #: la clé de son agenda (vide : tout le compte)
    calendar: Mapped[str] = mapped_column(Key(CALENDAR), default="")
    at: Mapped[int] = mapped_column(default=0)
    what: Mapped[str] = mapped_column(Key(WORD), default="")
    changed: Mapped[int] = mapped_column(default=0)
    detail: Mapped[str] = mapped_column(LongText, default="")


__all__ = ["ACCOUNT", "ADDRESS", "CALENDAR", "OCCURRENCE", "PERSON", "PRINT", "UID", "WORD", "AccountRow",
           "AttendeeRow", "CalendarRow", "EventRow", "ForgottenRow", "SyncNoteRow", "fit"]
