"""Le magasin : journal d'événements, contenus, instantanés, file de sortie,
projections.

Deux bases : ``mind`` (sa vie : journal, contenus, instantanés, file de sortie,
projections T0 — sauvegardée) et ``views`` (projections différées et
vecteurs — jetable, reconstructible).
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class StoredEvent:
    seq: int
    id: str
    type: str
    v: int
    at: int
    causation: str | None
    correlation: str
    basis: int
    origin: str
    data: str  # JSON (contenus remplacés par leurs références)


@dataclass(frozen=True, slots=True)
class ContentRow:
    ref: str
    seq: int
    subjects: tuple[str, ...]
    level: int
    text: str


@dataclass(frozen=True, slots=True)
class OutboxRow:
    key: str  # "<event id>:<propriétaire de l'effet>"
    seq: int
    effect: str  # "<propriétaire>:<type d'événement>"
    status: str = "pending"
    attempts: int = 0
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class SnapshotRow:
    seq: int
    at: int
    data: str  # JSON : {"slices": {owner: {"v": n, "data": ...}}, "changed": ..., "tainted": ...}


class Sql(Protocol):
    """Accès SQL d'une projection (connexion fournie par l'adaptateur)."""

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any: ...

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> Any: ...

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]: ...


T0Apply = Callable[[Sql], None]


@dataclass(slots=True)
class AppendBatch:
    events: list[StoredEvent]
    contents: list[ContentRow] = field(default_factory=list)
    dedupe: list[tuple[str, str, int]] = field(default_factory=list)
    outbox: list[OutboxRow] = field(default_factory=list)
    snapshot: SnapshotRow | None = None
    t0: T0Apply | None = None


class EventStore(Protocol):
    async def open(self) -> None: ...

    async def close(self) -> None: ...

    async def append(self, batch: AppendBatch) -> None: ...

    def head(self) -> int: ...

    def last_at(self) -> int: ...

    def find_dedupe(self, type_name: str, key: str) -> int | None: ...

    def read(
        self, after: int = 0, types: Collection[str] | None = None, upto: int | None = None
    ) -> Iterator[StoredEvent]: ...

    def get_events(self, seqs: Collection[int]) -> list[StoredEvent]: ...

    def latest(self, types: Collection[str], limit: int, *, where: tuple[str, Any] | None = None,
               before: int | None = None, correlations: Collection[str] | None = None) -> list[StoredEvent]:
        """Les ``limit`` derniers événements de ces types, du plus récent au plus
        ancien ; ``where=(champ, valeur)`` filtre sur un champ de premier niveau
        de la charge utile, ``correlations`` sur l'épisode ou l'exécution."""
        ...

    def tally(self, type_name: str, field: str) -> list[tuple[Any, int, int]]:
        """Par valeur d'un champ de premier niveau : (valeur, nombre, dernier instant)."""
        ...

    def content(self, refs: Collection[str]) -> dict[str, str]: ...

    def latest_snapshot(self) -> SnapshotRow | None: ...

    def pending_outbox(self) -> list[OutboxRow]: ...

    async def mark_outbox(self, key: str, status: str, error: str | None = None) -> None: ...

    # projections différées (base views)
    def projector_state(self, name: str) -> tuple[int, int] | None: ...

    async def run_views(self, fn: Callable[[Sql], Any]) -> Any: ...

    def query_views(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]: ...

    def query_mind(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]: ...

    async def run_mind(self, fn: Callable[[Sql], Any]) -> Any: ...

    async def forget_subject(self, subject: str, purge: Callable[[Sql, Sql], Iterable[str] | None]) -> int: ...
    # ``purge`` peut rendre des références de contenus à effacer aussi : des textes qui ne nomment pas ce sujet,
    # mais que les projections lui ont rattachés depuis (un souvenir renforcé par ce qu'il a dit, ADR 0054)
