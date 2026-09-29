"""Le registre : assemble les facultés et valide le graphe de contributions.

Au démarrage, toute incohérence est une erreur de composition, listée en
entier : événement privé réduit par un autre propriétaire, fait inconnu ou
fourni deux fois, cycle de faits ou de sections, ancre de section inconnue,
seuil d'arbitrage inatteignable, noms d'outils ou de processus en double.
"""

from __future__ import annotations

import heapq
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, TypeAdapter

from mika.kernel.builtin import KERNEL, KernelParams, KernelState
from mika.kernel.codec import canonical_json
from mika.kernel.events import EventRegistry
from mika.kernel.facts import FactSpec, UnknownFact
from mika.kernel.faculty import (
    AppraisalSpec,
    EffectSpec,
    EnricherSpec,
    Faculty,
    FeelSpec,
    InspectSpec,
    InterpreterSpec,
    InvariantSpec,
    ModulatorSpec,
    PreludeSpec,
    ProcessSpec,
    ProjectorSpec,
    ProposerSpec,
    ReducerSpec,
    SectionSpec,
    ToolSpec,
)
from mika.kernel.state import FrozenDict, Root


class CompositionError(Exception):
    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = list(problems)
        super().__init__("composition invalide :\n- " + "\n- ".join(self.problems))


@dataclass(frozen=True, slots=True)
class ArbitrationPolicy:
    """Seuils (log-odds) et taux maximaux (par seconde) par type d'épisode."""

    thresholds: Mapping[str, float] = field(default_factory=dict)
    max_rates: Mapping[str, float] = field(default_factory=dict)
    aging_per_hour: Mapping[str, float] = field(default_factory=dict)
    top_k: int = 5


class Registry:
    def __init__(self, faculties: Iterable[Faculty[Any, Any]], *, arbitration: ArbitrationPolicy | None = None) -> None:
        facs = [KERNEL] + [f for f in faculties if f is not KERNEL]
        problems: list[str] = []
        self.faculties: dict[str, Faculty[Any, Any]] = {}
        for f in facs:
            if f.name in self.faculties:
                problems.append(f"faculté déclarée deux fois : {f.name}")
            self.faculties[f.name] = f
        self.arbitration = arbitration or ArbitrationPolicy()

        # événements
        self.events = EventRegistry()
        for f in facs:
            for t in f.events.values():
                ns = t.name.split(".", 1)[0]
                if ns not in f.namespaces:
                    problems.append(f"{t.name} : espace de noms « {ns} » hors de {f.name}")
                try:
                    self.events.add(t)
                except ValueError as exc:
                    problems.append(str(exc))

        # faits
        self.providers: dict[str, FactSpec] = {}
        for f in facs:
            for spec in f.facts:
                if spec.key.name in self.providers:
                    problems.append(
                        f"fait fourni deux fois : {spec.key.name} ({self.providers[spec.key.name].owner}, {f.name})"
                    )
                self.providers[spec.key.name] = spec
        for spec in self.providers.values():
            for r in spec.reads:
                if r not in self.providers:
                    problems.append(f"{spec.owner} : le fait {spec.key.name} lit un fait inconnu {r}")
        cycle = _find_cycle({n: [r for r in s.reads if r in self.providers] for n, s in self.providers.items()})
        if cycle:
            problems.append("cycle de faits : " + " → ".join(cycle))

        # réducteurs
        self.reducers_by_type: dict[str, list[ReducerSpec]] = defaultdict(list)
        for f in facs:
            for spec in f.reducers:
                for r in spec.reads:
                    if r not in self.providers:
                        problems.append(f"{f.name} : un réducteur lit un fait inconnu {r}")
                for t in spec.types:
                    if t.name not in self.events:
                        problems.append(f"{f.name} réduit un événement inconnu : {t.name}")
                        continue
                    if t.owner != f.name and not t.public:
                        problems.append(f"{f.name} réduit l'événement privé {t.name} de {t.owner}")
                    self.reducers_by_type[t.name].append(spec)
        for name in self.reducers_by_type:
            self.reducers_by_type[name].sort(key=lambda s: s.owner)

        # évaluations émotionnelles (déclarées par le propriétaire de l'événement)
        self.appraisals: dict[str, list[AppraisalSpec]] = defaultdict(list)
        for f in facs:
            for spec in f.appraisals:
                if spec.type.owner != f.name:
                    problems.append(f"{f.name} déclare l'évaluation d'un événement de {spec.type.owner}")
                self.appraisals[spec.type.name].append(spec)
                for r in spec.reads:
                    if r not in self.providers:
                        problems.append(f"{f.name} : une évaluation lit un fait inconnu {r}")
        feels = [s for f in facs for s in f.feelings]
        if len(feels) > 1:
            problems.append("plusieurs receveurs d'évaluations : " + ", ".join(s.owner for s in feels))
        self.feel: FeelSpec | None = feels[0] if feels else None

        # sections
        self.sections: list[SectionSpec] = []
        keys: dict[str, SectionSpec] = {}
        for f in facs:
            for spec in f.sections:
                if spec.key in keys:
                    problems.append(f"section déclarée deux fois : {spec.key}")
                keys[spec.key] = spec
        edges: dict[str, list[str]] = {k: [] for k in keys}
        for k, spec in keys.items():
            for a in spec.after:
                if a not in keys:
                    problems.append(f"section {k} : ancre inconnue « after={a} »")
                else:
                    edges[a].append(k)
            for b in spec.before:
                if b not in keys:
                    problems.append(f"section {k} : ancre inconnue « before={b} »")
                else:
                    edges[k].append(b)
            for r in spec.reads:
                if r not in self.providers:
                    problems.append(f"section {k} : lit un fait inconnu {r}")
        order = _topo(edges)
        if order is None:
            problems.append("cycle dans l'ordre des sections")
        else:
            self.sections = [keys[k] for k in order]

        # autres contributions
        self.enrichers: list[EnricherSpec] = [s for f in facs for s in f.enrichers]
        self.proposers: list[ProposerSpec] = [s for f in facs for s in f.proposers]
        self.modulators: list[ModulatorSpec] = [s for f in facs for s in f.modulators]
        self.preludes: list[PreludeSpec] = [s for f in facs for s in f.preludes]
        self.interpreters: dict[str, list[InterpreterSpec]] = defaultdict(list)
        for f in facs:
            for spec in f.interpreters:
                for name in sorted(spec.types):
                    if name not in self.events:
                        problems.append(f"{f.name} interprète un événement inconnu : {name}")
                        continue
                    t = self.events.get(name)
                    if t.owner != f.name and not t.public:
                        problems.append(f"{f.name} interprète l'événement privé {name} de {t.owner}")
                    self.interpreters[name].append(spec)
        for name in self.interpreters:
            self.interpreters[name].sort(key=lambda s: s.owner)
        self.inspectors: list[InspectSpec] = [s for f in facs for s in f.inspectors]
        self.invariants: list[InvariantSpec] = [s for f in facs for s in f.invariants]
        self.processes: dict[str, ProcessSpec] = {}
        for s in (s for f in facs for s in f.processes):
            if s.name in self.processes:
                problems.append(f"processus déclaré deux fois : {s.name}")
            self.processes[s.name] = s
            for w in s.wake_on:
                if w not in self.events:
                    problems.append(f"processus {s.name} : réveil sur un événement inconnu {w}")
        self.tools: dict[str, ToolSpec] = {}
        for s in (s for f in facs for s in f.tools):
            if s.name in self.tools:
                problems.append(f"outil déclaré deux fois : {s.name}")
            self.tools[s.name] = s
        self.projectors: dict[str, ProjectorSpec] = {}
        for s in (s for f in facs for s in f.projectors):
            if s.name in self.projectors:
                problems.append(f"projection déclarée deux fois : {s.name}")
            self.projectors[s.name] = s
        self.effects: dict[str, list[EffectSpec]] = defaultdict(list)
        for s in (s for f in facs for s in f.effects):
            self.effects[s.type.name].append(s)

        for p in self.proposers:
            for reason, (lo, hi) in p.reasons.items():
                if lo > hi:
                    problems.append(f"{p.owner} : plage de preuve inversée pour {reason}")
            for r in p.reads:
                if r not in self.providers:
                    problems.append(f"{p.owner} : une proposition lit un fait inconnu {r}")
        # atteignabilité des seuils
        for kind, threshold in self.arbitration.thresholds.items():
            proposers = [p for p in self.proposers if kind in p.kinds]
            if not proposers:
                continue
            best = sum(max((hi for (_, hi) in p.reasons.values()), default=0.0) for p in proposers)
            if best < threshold:
                problems.append(
                    f"seuil inatteignable pour {kind} : preuves maximales {best:.2f} < seuil {threshold:.2f}"
                )

        if problems:
            raise CompositionError(problems)

        self._adapters: dict[str, TypeAdapter[Any]] = {}

    # ── états ──
    def owners(self) -> list[str]:
        return sorted(self.faculties)

    def persisted_owners(self) -> list[str]:
        return [n for n in self.owners() if not self.faculties[n].volatile]

    def slice_adapter(self, owner: str) -> TypeAdapter[Any]:
        if owner not in self._adapters:
            self._adapters[owner] = TypeAdapter(self.faculties[owner].state)
        return self._adapters[owner]

    def initial_root(self) -> Root:
        slices = {}
        for name, f in self.faculties.items():
            slices[name] = f.init(f.default_params())
        return Root(slices=FrozenDict(slices))

    # ── paramètres ──
    def params_of(self, owner: str, root: Root) -> Any:
        f = self.faculties[owner]
        if f.params is None:
            return None
        ks: KernelState = root.slices["kernel"]
        rec = ks.params.get(owner)
        if rec is None:
            return _default_params(f)
        return _decode_params(f.params, rec.data)

    def tz_of(self, root: Root) -> ZoneInfo:
        params: KernelParams = self.params_of("kernel", root)
        return _zone(params.tz)

    def fact_spec(self, name: str) -> FactSpec:
        try:
            return self.providers[name]
        except KeyError:
            raise UnknownFact(name) from None

    def encode_params(self, owner: str, params: BaseModel) -> str:
        return canonical_json(params)

    # ── reconstruction ──
    def read_closure(self, owners: Iterable[str]) -> set[str]:
        """Les propriétaires à rejouer pour reconstruire ``owners`` : eux, et
        ceux dont leurs réducteurs lisent des faits (transitivement)."""
        todo = list(owners)
        seen: set[str] = set()
        while todo:
            owner = todo.pop()
            if owner in seen:
                continue
            seen.add(owner)
            facts: set[str] = set()
            for spec in self.faculties[owner].reducers:
                facts |= spec.reads
            if self.feel is not None and self.feel.owner == owner:
                facts |= self.feel.reads
                for specs in self.appraisals.values():
                    for a in specs:
                        facts |= a.reads
            stack = list(facts)
            visited: set[str] = set()
            while stack:
                name = stack.pop()
                if name in visited or name not in self.providers:
                    continue
                visited.add(name)
                prov = self.providers[name]
                if prov.owner not in seen:
                    todo.append(prov.owner)
                stack.extend(prov.reads)
        seen.add("kernel")
        return seen

    def replay_types(self, closure: set[str]) -> set[str]:
        """Les types d'événements qui touchent ces propriétaires (réducteurs,
        et évaluations quand le receveur en fait partie)."""
        types = {name for name, specs in self.reducers_by_type.items() if any(s.owner in closure for s in specs)}
        if self.feel is not None and self.feel.owner in closure:
            types |= set(self.appraisals)
        return types

    def check_invariants(self, root: Root) -> list[str]:
        failures = []
        for inv in self.invariants:
            msg = inv.fn(self.params_of(inv.owner, root))
            if msg:
                failures.append(f"{inv.owner}.{inv.name} : {msg}")
        return failures


@lru_cache(maxsize=256)
def _decode_params_cached(model: type[BaseModel], data: str) -> BaseModel:
    return model.model_validate(json.loads(data))


def _decode_params(model: type[BaseModel], data: str) -> BaseModel:
    return _decode_params_cached(model, data)


@lru_cache(maxsize=64)
def _default_params(f: Faculty[Any, Any]) -> Any:
    return f.default_params()


@lru_cache(maxsize=16)
def _zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def _find_cycle(graph: Mapping[str, Sequence[str]]) -> list[str] | None:
    WHITE, GREY, BLACK = 0, 1, 2
    color = dict.fromkeys(graph, WHITE)
    stack: list[str] = []

    def visit(n: str) -> list[str] | None:
        color[n] = GREY
        stack.append(n)
        for m in sorted(graph.get(n, ())):
            if color.get(m, WHITE) == GREY:
                return stack[stack.index(m):] + [m]
            if color.get(m, WHITE) == WHITE:
                found = visit(m)
                if found:
                    return found
        stack.pop()
        color[n] = BLACK
        return None

    for n in sorted(graph):
        if color[n] == WHITE:
            found = visit(n)
            if found:
                return found
    return None


def _topo(edges: Mapping[str, Sequence[str]]) -> list[str] | None:
    """Tri topologique stable (égalités départagées par la clé)."""
    indeg = dict.fromkeys(edges, 0)
    for _n, outs in edges.items():
        for m in outs:
            indeg[m] += 1
    ready = [n for n, d in indeg.items() if d == 0]
    heapq.heapify(ready)
    out: list[str] = []
    while ready:
        n = heapq.heappop(ready)
        out.append(n)
        for m in sorted(edges[n]):
            indeg[m] -= 1
            if indeg[m] == 0:
                heapq.heappush(ready, m)
    if len(out) != len(edges):
        return None
    return out
