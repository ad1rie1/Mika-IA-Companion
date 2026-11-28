"""Ce que le soi garde (typé : les instantanés le sérialisent)."""

from __future__ import annotations

from dataclasses import dataclass

from mika.vocab.lineage import Lineage

# ce qu'elle a fait (``Deed.what``)
OPENED, DONE, BLOCKED, ABANDONED, REMINDED, WORKED = "opened", "done", "blocked", "abandoned", "reminded", "worked"
#: elle a laissé son esprit vagabonder (une rêverie écrite) : rien n'est arrivé, son journal le dit une fois
MUSED = "mused"
#: elle a pris le temps de repenser à ce qui pesait (une réflexion menée au bout) : pas un exploit (ADR 0096)
REFLECTED = "reflected"


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


@dataclass(frozen=True, slots=True)
class Mark:
    """Une réussite ou un raté qui dit quelque chose d'elle (ADR 0088) : tenir parole (``promises``), mener au bout
    (``finishing``), voir venir (``foresight`` : ``value``, l'écart au carré entre ce qu'elle attendait et ce qui est
    arrivé) ; ``ref`` : la promesse, le but, l'objectif, le moment."""

    at: int
    domain: str
    outcome: str
    value: float = 0.0
    ref: int = 0


@dataclass(frozen=True, slots=True)
class Interest:
    """Un de ses centres d'intérêt, vivant (ADR 0089) : de sa persona (``line``, il s'endort sans disparaître) ou
    vécu (``label_ref``, ``detail_ref`` : son sujet et ce qu'il est, dits par elle ; ``about`` : de qui il est né, ce
    que l'oubli emporte). ``glow`` : sa vivacité à ``glow_at`` ; ``touched`` : ce que ses flux lui ont rendu la
    journée vécue ``touched_day``."""

    key: str
    origin: str
    line: str = ""
    label_ref: str = ""
    detail_ref: str = ""
    about: tuple[str, ...] = ()
    born_at: int = 0
    glow: float = 0.5
    glow_at: int = 0
    fed_at: int = 0
    feeds: int = 0
    touched_day: str = ""
    touched: float = 0.0


@dataclass(frozen=True, slots=True)
class Lead:
    """Une piste (ADR 0089) : quelque chose qui pourrait devenir un intérêt — ce qu'on lui a raconté et qu'elle a
    médité (``talk``), un article lu (``reading``), ce qu'elle a trouvé en explorant (``found``). Jamais une
    confidence ; ``about`` : de qui elle vient."""

    seq: int
    at: int
    kind: str
    ref: str
    about: tuple[str, ...] = ()
    sensitivity: int = 0
    #: ce dont elle vient (un article, un but) : relu quatre fois, un article reste une piste
    key: str = ""
