"""Ce que le soi garde (typé : les instantanés le sérialisent)."""

from __future__ import annotations

from dataclasses import dataclass

from mika.vocab.lineage import Lineage


@dataclass(frozen=True, slots=True)
class Journal:
    day: str
    text_ref: str
    about: tuple[str, ...]
    dominant: str
    at: int
    #: combien de fois elle l'a réécrit (une nuit coupée par une conversation)
    rev: int = 0
    #: sa journée à elle, sans personne d'autre : ce qui se montre à qui n'est pas le seul concerné
    shareable_ref: str = ""
    #: devant qui sa version intime peut se montrer (``None`` : un journal d'avant)
    lineage: Lineage | None = None
    #: une de ses sources est devenue secrète depuis : seule sa version partageable se montre (ADR 0082)
    masked: bool = False


@dataclass(frozen=True, slots=True)
class Dream:
    id: int
    night: str
    text_ref: str
    kind: str
    vividness: float
    emotion: str
    about: tuple[str, ...]
    sensitivity: int
    at: int
    #: revenu dans un prompt où elle parlait : il s'est effacé
    recalled: bool = False
    #: au réveil, elle s'en est souvenue (un tirage enregistré dans ``self.woke_with``)
    remembered: bool = False
    #: devant qui il peut se raconter (``None`` : un rêve d'avant)
    lineage: Lineage | None = None
    #: une de ses sources est devenue secrète depuis : il ne se raconte plus (ADR 0082)
    masked: bool = False


@dataclass(frozen=True, slots=True)
class Knock:
    """Un coup porté à son estime : quand, pourquoi, de combien."""

    at: int
    cause: str
    delta: float


@dataclass(frozen=True, slots=True)
class Effort:
    """Ce qu'un but (ou un objectif de projet) lui a demandé jusqu'ici."""

    steps: int
    proven: bool
    at: int


@dataclass(frozen=True, slots=True)
class Deed:
    """Une chose qu'elle a faite de son côté : se lancer dans quelque chose, le
    mener à bout, y bloquer, y renoncer, travailler sur un projet."""

    at: int
    what: str  # OPENED | ACHIEVED | STUCK | ABANDONED | REMINDED | WORKED
    title_ref: str = ""
    owner: str = ""
    project: int = 0
    #: qui ce qu'elle a fait concerne, et à quel point c'est sensible (un but né d'une confidence)
    about: tuple[str, ...] = ()
    sensitivity: int = 0
