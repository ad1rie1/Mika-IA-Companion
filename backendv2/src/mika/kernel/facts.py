"""Faits typés : le seul canal de lecture entre facultés.

Une clé de fait (``FactKey``) ou une famille paramétrée (``FactFamily``,
p. ex. ``STANCE(personne)``) est déclarée dans le contrat de son propriétaire ;
un seul fournisseur la calcule, par une fonction pure de sa tranche et de
l'instant. Une lecture hors de ce qu'une contribution a déclaré lève
``UndeclaredRead`` : la clôture de reconstruction en dépend.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar
from zoneinfo import ZoneInfo

from mika.kernel.clock import local as to_local
from mika.kernel.codec import digest, h64

if TYPE_CHECKING:
    from mika.kernel.state import Root

T = TypeVar("T")
A = TypeVar("A")


@dataclass(frozen=True, slots=True)
class FactKey(Generic[T]):
    name: str
    type: Any = object
    time_varying: bool = False
    doc: str = ""


@dataclass(frozen=True, slots=True)
class FactFamily(Generic[A, T]):
    name: str
    arg: Any = str
    type: Any = object
    time_varying: bool = False
    doc: str = ""

    def __call__(self, arg: Hashable) -> BoundFact:
        return BoundFact(self, arg)


@dataclass(frozen=True, slots=True)
class BoundFact:
    family: FactFamily[Any, Any]
    arg: Hashable

    @property
    def name(self) -> str:
        return self.family.name

    def __repr__(self) -> str:
        return f"{self.family.name}({self.arg!r})"


FactRef = FactKey[Any] | BoundFact
Declared = FactKey[Any] | FactFamily[Any, Any]


def ref_name(ref: FactRef | Declared) -> str:
    return ref.name


def ref_key(ref: FactRef) -> tuple[str, Hashable]:
    if isinstance(ref, BoundFact):
        return (ref.family.name, ref.arg)
    return (ref.name, None)


def is_time_varying(ref: FactRef | Declared) -> bool:
    if isinstance(ref, BoundFact):
        return ref.family.time_varying
    return ref.time_varying


class UndeclaredRead(LookupError):
    pass


class UnknownFact(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class FactSpec:
    owner: str
    key: Declared
    fn: Callable[..., Any]
    reads: frozenset[str]


class FactEnv(Protocol):
    """Ce que les vues de faits demandent au registre."""

    def fact_spec(self, name: str) -> FactSpec: ...

    def params_of(self, owner: str, root: Root) -> Any: ...

    def tz_of(self, root: Root) -> ZoneInfo: ...


@dataclass(slots=True)
class FactContext:
    """Ce qu'un fournisseur de fait reçoit."""

    now: int
    params: Any
    facts: FactView
    tz: ZoneInfo

    def local(self, t: int | None = None) -> datetime:
        return to_local(self.now if t is None else t, self.tz)


class FactView:
    """Lecture mémoïsée des faits d'une racine à un instant donné."""

    __slots__ = ("_root", "_now", "_env", "_allowed", "_memo", "_trace")

    def __init__(
        self,
        root: Root,
        now: int,
        env: FactEnv,
        allowed: frozenset[str] | None = None,
        memo: dict[tuple[str, Hashable], Any] | None = None,
        trace: list[str] | None = None,
    ) -> None:
        self._root = root
        self._now = now
        self._env = env
        self._allowed = allowed
        self._memo = {} if memo is None else memo
        self._trace = trace

    @property
    def root(self) -> Root:
        return self._root

    @property
    def now(self) -> int:
        return self._now

    def restricted(self, allowed: frozenset[str] | None) -> FactView:
        return FactView(self._root, self._now, self._env, allowed, self._memo, self._trace)

    def get(self, ref: FactRef) -> Any:
        name = ref.name
        if self._allowed is not None and name not in self._allowed:
            raise UndeclaredRead(f"lecture non déclarée : {name}")
        key = ref_key(ref)
        if key in self._memo:
            return self._memo[key]
        if self._trace is not None:
            self._trace.append(name)
        spec = self._env.fact_spec(name)
        state = self._root.slices[spec.owner]
        ctx = FactContext(
            now=self._now,
            params=self._env.params_of(spec.owner, self._root),
            facts=FactView(self._root, self._now, self._env, spec.reads, self._memo, self._trace),
            tz=self._env.tz_of(self._root),
        )
        if isinstance(ref, BoundFact):
            value = spec.fn(state, ctx, ref.arg)
        else:
            value = spec.fn(state, ctx)
        self._memo[key] = value
        return value

    def fingerprint(self, ref: FactRef) -> str:
        """Empreinte d'un fait pour les gardes.

        Pour un fait qui varie avec le temps, sa valeur dérive sans événement :
        on prend le ``seq`` de la dernière modification de la tranche qui le
        fournit — deux lectures au même état ont la même empreinte.
        """
        spec = self._env.fact_spec(ref.name)
        if is_time_varying(ref):
            return digest((ref_key(ref), self._root.changed.get(spec.owner, 0)))
        return digest((ref_key(ref), self.restricted(None).get(ref)))


@dataclass(slots=True)
class ReduceContext:
    """Ce qu'un réducteur reçoit : paramètres en vigueur à ``e.at``, faits des
    autres propriétaires **avant** l'événement, hasard dérivé de l'événement."""

    owner: str
    event_id: str
    now: int
    params: Any
    tz: ZoneInfo
    _facts_factory: Callable[[], FactView]
    _facts: FactView | None = field(default=None)
    _rng: random.Random | None = field(default=None)

    @property
    def facts(self) -> FactView:
        if self._facts is None:
            self._facts = self._facts_factory()
        return self._facts

    @property
    def rng(self) -> random.Random:
        if self._rng is None:
            self._rng = random.Random(h64(self.event_id, self.owner))
        return self._rng

    def local(self, t: int | None = None) -> datetime:
        return to_local(self.now if t is None else t, self.tz)
