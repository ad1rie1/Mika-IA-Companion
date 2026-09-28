"""Une faculté = un paquet qui déclare ses contributions.

Tout passe par des décorateurs sur un objet ``Faculty`` : événements du
contrat, réducteurs, faits, évaluations émotionnelles, sections de prompt,
enrichisseurs, preuves d'initiative, modulations, processus, outils,
projections, effets, vues d'inspecteur, invariants. Le registre
(``kernel.registry``) assemble et valide le tout au démarrage.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from mika.kernel.events import EventType, Payload, Upcaster
from mika.kernel.facts import Declared, FactSpec

S = TypeVar("S")
Pm = TypeVar("Pm")


def _names(reads: Iterable[Declared | str]) -> frozenset[str]:
    return frozenset(r if isinstance(r, str) else r.name for r in reads)


class Zone(enum.StrEnum):
    STABLE = "stable"
    HISTORY = "history"
    VOLATILE = "volatile"


class CatchUp(enum.StrEnum):
    SKIP = "skip"
    ONCE = "once"


class Tier(enum.StrEnum):
    T0 = "t0"  # dans la transaction d'ajout
    T1 = "t1"  # différée
    T2 = "t2"  # différée, calcul lourd


class EffectClass(enum.StrEnum):
    NONE = "none"
    INTERNAL = "internal"
    EXTERNAL = "external"


# ── Spécifications de contributions ───────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ReducerSpec:
    owner: str
    types: tuple[EventType[Any], ...]
    fn: Callable[..., Any]
    reads: frozenset[str]


@dataclass(frozen=True, slots=True)
class AppraisalSpec:
    owner: str
    type: EventType[Any]
    fn: Callable[..., Any]
    reads: frozenset[str]


@dataclass(frozen=True, slots=True)
class SectionSpec:
    owner: str
    key: str
    zone: Zone
    episodes: frozenset[str]
    fn: Callable[..., Any]
    after: tuple[str, ...] = ()
    before: tuple[str, ...] = ()
    trim_rank: int = 50
    floor_chars: int = 0
    tags: frozenset[str] = frozenset()
    reads: frozenset[str] = frozenset()
    title: str | None = None


@dataclass(frozen=True, slots=True)
class EnricherSpec:
    owner: str
    key: str
    episodes: frozenset[str]
    deadline_ms: int
    fn: Callable[..., Any]
    reads: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ProposerSpec:
    owner: str
    kinds: frozenset[str]
    reasons: Mapping[str, tuple[float, float]]
    fn: Callable[..., Any]
    reads: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ModulatorSpec:
    owner: str
    kinds: frozenset[str]
    fn: Callable[..., Any]
    reads: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ProcessSpec:
    owner: str
    name: str
    process: Any  # objet avec next_due(state, frame) et run(ctx)
    wake_on: frozenset[str] = frozenset()
    priority: int = 50
    catch_up: CatchUp = CatchUp.ONCE
    max_quantum_us: int = 300 * 1_000_000
    lane: str = "background"
    reads: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ToolSpec:
    owner: str
    name: str
    description: str
    args: type[BaseModel]
    handler: Callable[..., Any]
    bundle: str
    episodes: frozenset[str]
    min_level: int | None = None
    effect: EffectClass = EffectClass.NONE
    max_calls_per_episode: int | None = None


@dataclass(frozen=True, slots=True)
class ProjectorSpec:
    owner: str
    name: str
    version: int
    tier: Tier
    types: frozenset[str]
    projector: Any  # objet avec schema(), apply(conn, events), reset(conn)


@dataclass(frozen=True, slots=True)
class EffectSpec:
    owner: str
    type: EventType[Any]
    fn: Callable[..., Any]


@dataclass(frozen=True, slots=True)
class InspectSpec:
    owner: str
    name: str
    fn: Callable[..., Any]


@dataclass(frozen=True, slots=True)
class InvariantSpec:
    owner: str
    name: str
    fn: Callable[..., str | None]


@dataclass(frozen=True, slots=True)
class PreludeSpec:
    owner: str
    kinds: frozenset[str]
    fn: Callable[..., Any]


# ── La faculté ────────────────────────────────────────────────────────────


@dataclass(eq=False)
class Faculty(Generic[S, Pm]):
    """Un propriétaire : une tranche d'état, ses paramètres, ses contributions."""

    name: str
    state: type[S]
    init: Callable[[Pm], S]
    state_version: int = 1
    params: type[Pm] | None = None
    namespaces: tuple[str, ...] = ()
    volatile: bool = False
    derive: Callable[[Any, Mapping[str, Any]], Pm] | None = None

    events: dict[str, EventType[Any]] = field(default_factory=dict)
    reducers: list[ReducerSpec] = field(default_factory=list)
    facts: list[FactSpec] = field(default_factory=list)
    appraisals: list[AppraisalSpec] = field(default_factory=list)
    sections: list[SectionSpec] = field(default_factory=list)
    enrichers: list[EnricherSpec] = field(default_factory=list)
    proposers: list[ProposerSpec] = field(default_factory=list)
    modulators: list[ModulatorSpec] = field(default_factory=list)
    processes: list[ProcessSpec] = field(default_factory=list)
    tools: list[ToolSpec] = field(default_factory=list)
    projectors: list[ProjectorSpec] = field(default_factory=list)
    effects: list[EffectSpec] = field(default_factory=list)
    inspectors: list[InspectSpec] = field(default_factory=list)
    invariants: list[InvariantSpec] = field(default_factory=list)
    preludes: list[PreludeSpec] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.namespaces:
            self.namespaces = (self.name,)

    def __hash__(self) -> int:
        return hash(self.name)

    # ── contrat ──
    def event(
        self,
        name: str,
        payload: type[Payload],
        *,
        version: int = 1,
        public: bool = False,
        upcasters: Mapping[int, Upcaster] | None = None,
        content: Iterable[str] = (),
        subjects: Iterable[str] = (),
        authored: bool = False,
    ) -> EventType[Any]:
        full = name if "." in name else f"{self.namespaces[0]}.{name}"
        t = EventType(
            name=full,
            owner=self.name,
            payload=payload,
            version=version,
            public=public,
            upcasters=dict(upcasters or {}),
            content_fields=frozenset(content),
            subject_fields=frozenset(subjects),
            authored=authored,
        )
        return self.declare(t)

    def declare(self, *types: EventType[Any]) -> EventType[Any]:
        last: EventType[Any] | None = None
        for t in types:
            if t.owner != self.name:
                raise ValueError(f"{t.name} appartient à {t.owner}, pas à {self.name}")
            self.events[t.name] = t
            last = t
        assert last is not None
        return last

    # ── état ──
    def reducer(self, *types: EventType[Any], reads: Iterable[Declared | str] = ()):
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.reducers.append(ReducerSpec(self.name, tuple(types), fn, _names(reads)))
            return fn

        return deco

    def fact(self, key: Declared, *, reads: Iterable[Declared | str] = ()):
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.facts.append(FactSpec(self.name, key, fn, _names(reads)))
            return fn

        return deco

    def appraisal(self, type_: EventType[Any], *, reads: Iterable[Declared | str] = ()):
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.appraisals.append(AppraisalSpec(self.name, type_, fn, _names(reads)))
            return fn

        return deco

    # ── prompt ──
    def section(
        self,
        key: str,
        *,
        zone: Zone,
        episodes: Iterable[str],
        after: Iterable[str] = (),
        before: Iterable[str] = (),
        trim_rank: int = 50,
        floor_chars: int = 0,
        tags: Iterable[str] = (),
        reads: Iterable[Declared | str] = (),
        title: str | None = None,
    ):
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.sections.append(
                SectionSpec(
                    self.name, key, zone, frozenset(episodes), fn, tuple(after), tuple(before),
                    trim_rank, floor_chars, frozenset(tags), _names(reads), title,
                )
            )
            return fn

        return deco

    def enricher(self, key: str, *, episodes: Iterable[str], deadline_ms: int, reads: Iterable[Declared | str] = ()):
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.enrichers.append(EnricherSpec(self.name, key, frozenset(episodes), deadline_ms, fn, _names(reads)))
            return fn

        return deco

    # ── comportement ──
    def propose(
        self,
        *,
        kinds: Iterable[str],
        reasons: Mapping[str, tuple[float, float]],
        reads: Iterable[Declared | str] = (),
    ):
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.proposers.append(ProposerSpec(self.name, frozenset(kinds), dict(reasons), fn, _names(reads)))
            return fn

        return deco

    def modulate(self, *, kinds: Iterable[str], reads: Iterable[Declared | str] = ()):
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.modulators.append(ModulatorSpec(self.name, frozenset(kinds), fn, _names(reads)))
            return fn

        return deco

    def process(
        self,
        name: str,
        *,
        wake_on: Iterable[EventType[Any] | str] = (),
        priority: int = 50,
        catch_up: CatchUp = CatchUp.ONCE,
        max_quantum_s: float = 300.0,
        lane: str = "background",
        reads: Iterable[Declared | str] = (),
    ):
        wake = frozenset(w if isinstance(w, str) else w.name for w in wake_on)

        def deco(obj: Any) -> Any:
            instance = obj() if isinstance(obj, type) else obj
            self.processes.append(
                ProcessSpec(
                    self.name, name, instance, wake, priority, catch_up,
                    int(max_quantum_s * 1_000_000), lane, _names(reads),
                )
            )
            return obj

        return deco

    def tool(
        self,
        name: str,
        *,
        description: str,
        args: type[BaseModel],
        bundle: str | None = None,
        episodes: Iterable[str],
        min_level: int | None = None,
        effect: EffectClass = EffectClass.NONE,
        max_calls_per_episode: int | None = None,
    ):
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.tools.append(
                ToolSpec(
                    self.name, name, description, args, fn, bundle or self.name,
                    frozenset(episodes), min_level, effect, max_calls_per_episode,
                )
            )
            return fn

        return deco

    # ── E/S ──
    def projector(self, name: str, *, version: int, tier: Tier, types: Iterable[EventType[Any] | str]):
        names = frozenset(t if isinstance(t, str) else t.name for t in types)

        def deco(obj: Any) -> Any:
            instance = obj() if isinstance(obj, type) else obj
            self.projectors.append(ProjectorSpec(self.name, name, version, tier, names, instance))
            return obj

        return deco

    def effect(self, type_: EventType[Any]):
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.effects.append(EffectSpec(self.name, type_, fn))
            return fn

        return deco

    # ── exploitation ──
    def inspect(self, name: str):
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.inspectors.append(InspectSpec(self.name, name, fn))
            return fn

        return deco

    def invariant(self, name: str):
        def deco(fn: Callable[..., str | None]) -> Callable[..., str | None]:
            self.invariants.append(InvariantSpec(self.name, name, fn))
            return fn

        return deco

    def prelude(self, *, kinds: Iterable[str]):
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.preludes.append(PreludeSpec(self.name, frozenset(kinds), fn))
            return fn

        return deco

    # ── paramètres ──
    def default_params(self) -> Pm | None:
        if self.params is None:
            return None
        return self.params()  # type: ignore[call-arg]
