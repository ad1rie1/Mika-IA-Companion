"""Les tables du magasin (ADR 0101) : le journal et ce qui l'accompagne dans ``mind`` (dédoublonnage, contenus et
leurs sujets, instantanés, file de sortie, ``meta``), l'état des projections différées dans ``views``.

Déclarées ici, au port, parce que tout le monde les lit : le magasin les écrit ; le runtime y range les versions et
l'avancement des projections ; la console et les outils de l'application lisent le journal et la file de sortie.

Les bornes : un identifiant d'événement est un ULID (26 caractères) ; une corrélation, un type, un nom de projection
tiennent largement dans les leurs. Une clé de dédoublonnage et un sujet de contenu peuvent venir de l'extérieur (un
identifiant de message client, une adresse) : le magasin les passe par ``fit`` à l'écriture comme à la lecture.
"""

from __future__ import annotations

from sqlalchemy import Index
from sqlalchemy.orm import Mapped, mapped_column

from mika.ports.sql import Key, LongText, MindBase, ViewsBase, table_args

#: la borne d'une clé de dédoublonnage et d'un sujet de contenu (``fit`` au-delà)
DEDUPE_KEY_MAX = 600
SUBJECT_MAX = 400


class JournalEvent(MindBase):
    """Un événement du journal, tel qu'écrit (les contenus remplacés par leurs références)."""

    __tablename__ = "events"
    __table_args__ = table_args(Index("events_type", "type", "seq"), Index("events_corr", "correlation"),
                                Index("events_cause", "causation"))
    seq: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    id: Mapped[str] = mapped_column(Key(40), unique=True)
    type: Mapped[str] = mapped_column(Key(120))
    v: Mapped[int]
    at: Mapped[int]
    causation: Mapped[str | None] = mapped_column(Key(255))
    correlation: Mapped[str] = mapped_column(Key(255))
    basis: Mapped[int]
    origin: Mapped[str] = mapped_column(LongText)
    data: Mapped[str] = mapped_column(LongText)


class JournalDedupe(MindBase):
    """Ce qu'un événement dédoublonne : son type et sa clé, et où il a été écrit."""

    __tablename__ = "dedupe"
    type: Mapped[str] = mapped_column(Key(120), primary_key=True)
    key: Mapped[str] = mapped_column(Key(DEDUPE_KEY_MAX), primary_key=True)
    seq: Mapped[int]


class JournalContent(MindBase):
    """Un texte libre, rangé à part du journal (effaçable : l'oubli)."""

    __tablename__ = "content"
    ref: Mapped[str] = mapped_column(Key(64), primary_key=True)
    seq: Mapped[int]
    level: Mapped[int]
    text: Mapped[str] = mapped_column(LongText)


class JournalSubject(MindBase):
    """Qui concerne un texte (``name:alice``, une adresse…) : ce que l'oubli d'un sujet efface."""

    __tablename__ = "content_subjects"
    __table_args__ = table_args(Index("content_by_subject", "subject"))
    ref: Mapped[str] = mapped_column(Key(64), primary_key=True)
    subject: Mapped[str] = mapped_column(Key(SUBJECT_MAX), primary_key=True)


class JournalSnapshot(MindBase):
    """Un instantané de l'état (les tranches des facultés), pour repartir sans tout rejouer."""

    __tablename__ = "snapshots"
    seq: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    at: Mapped[int]
    data: Mapped[str] = mapped_column(LongText)


class JournalOutbox(MindBase):
    """Un effet à faire partir après le commit (la file de sortie)."""

    __tablename__ = "outbox"
    __table_args__ = table_args(Index("outbox_pending", "status", "seq"))
    key: Mapped[str] = mapped_column(Key(255), primary_key=True)
    seq: Mapped[int]
    effect: Mapped[str] = mapped_column(LongText)
    status: Mapped[str] = mapped_column(Key(32))
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(LongText)


class MindMeta(MindBase):
    """Ce que le magasin et le runtime retiennent d'eux-mêmes (la version de chaque projection T0…)."""

    __tablename__ = "meta"
    key: Mapped[str] = mapped_column(Key(200), primary_key=True)
    value: Mapped[str] = mapped_column(LongText)


class ProjectorState(ViewsBase):
    """Une projection différée : sa version, et jusqu'où elle a lu le journal."""

    __tablename__ = "projector_state"
    name: Mapped[str] = mapped_column(Key(200), primary_key=True)
    version: Mapped[int]
    applied_seq: Mapped[int]


class ProjectorQuarantine(ViewsBase):
    """Un événement qu'une projection n'a pas su appliquer, après ses essais."""

    __tablename__ = "projector_quarantine"
    name: Mapped[str] = mapped_column(Key(200), primary_key=True)
    seq: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    error: Mapped[str | None] = mapped_column(LongText)


#: les tables du magasin par base (créées à l'ouverture sans migration : les tests, le simulateur)
MIND_TABLES = (JournalEvent, JournalDedupe, JournalContent, JournalSubject, JournalSnapshot, JournalOutbox, MindMeta)
VIEWS_TABLES = (ProjectorState, ProjectorQuarantine)

__all__ = [
    "DEDUPE_KEY_MAX", "MIND_TABLES", "SUBJECT_MAX", "VIEWS_TABLES",
    "JournalContent", "JournalDedupe", "JournalEvent", "JournalOutbox", "JournalSnapshot", "JournalSubject", "MindMeta",
    "ProjectorQuarantine", "ProjectorState",
]
