"""Arbitrage de l'initiative : des preuves cumulées, un déclenchement à taux.

Chaque faculté apporte des preuves (log-odds) pour « tel type d'épisode, vers
telle cible », pour une raison déclarée dans son contrat. Les preuves sont
cumulées par (type, cible) : deux raisons faibles franchissent ensemble un
seuil qu'aucune ne franchit seule. Une preuve « ANY » soutient toutes les
cibles de son type. Les modulations sont additives ou des vetos : leur ordre
n'a pas d'importance.

Le déclenchement est un processus de Poisson d'intensité
``λ = λ_max(type) · σ(score)`` : le prochain instant est tiré par
amincissement, si bien que le comportement ne dépend pas de la cadence à
laquelle on évalue, et que la gigue vient d'elle-même.
"""

from __future__ import annotations

import enum
import math
import random
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from mika.kernel.builtin import RowRecord
from mika.kernel.guards import Guard
from mika.kernel.registry import ArbitrationPolicy
from mika.kernel.state import FrozenDict


class Anyone(enum.StrEnum):
    NONE = "none"  # épisode sans cible (murmure)
    ANY = "any"  # soutient toutes les cibles de ce type


@dataclass(frozen=True, slots=True)
class Candidate:
    kind: str
    target: str
    reason: str
    evidence: float
    args: FrozenDict[str, Any] = field(default_factory=FrozenDict)
    resources: frozenset[str] = frozenset()
    deadline: int | None = None
    guards: tuple[Guard, ...] = ()


@dataclass(frozen=True, slots=True)
class Modulation:
    shift: float = 0.0
    veto: str | None = None


@dataclass(frozen=True, slots=True)
class RowView:
    """Ce qu'un modulateur voit : la ligne cumulée, avant décalages — et sa
    raison la plus forte prise seule, hors soutiens « ANY » (ce qui réveille
    quelqu'un est une raison forte, pas une somme d'envies)."""

    kind: str
    target: str
    evidence: float
    reasons: tuple[str, ...]
    strongest: float = 0.0


@dataclass(frozen=True, slots=True)
class Row:
    kind: str
    target: str
    parts: tuple[tuple[str, str, float], ...]
    shift: float
    vetoes: tuple[tuple[str, str], ...]
    score: float
    hazard: float
    resources: frozenset[str] = frozenset()
    guards: tuple[Guard, ...] = ()
    args: FrozenDict[str, Any] = field(default_factory=FrozenDict)
    deadline: int | None = None
    threshold: float = 0.0
    aging: float = 0.0
    #: décalage par propriétaire de modulateur (triés) ; leur somme est ``shift``
    shifts: tuple[tuple[str, float], ...] = ()

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.target}"

    @property
    def evidence(self) -> float:
        return sum(p[2] for p in self.parts)

    def record(self) -> RowRecord:
        return RowRecord(
            kind=self.kind, target=self.target, parts=self.parts, shift=round(self.shift, 6),
            vetoes=self.vetoes, score=round(self.score, 6), hazard=self.hazard,
            threshold=round(self.threshold, 6), aging=round(self.aging, 6),
            shifts=tuple((owner, round(v, 6)) for owner, v in self.shifts),
        )


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def pool(
    proposals: Sequence[tuple[str, Candidate]],
    policy: ArbitrationPolicy,
    modulate: Callable[[RowView], Sequence[tuple[str, Modulation]]],
    ages_s: Mapping[str, float] | None = None,
) -> list[Row]:
    """Cumule les preuves en lignes, applique modulations, vieillissement, seuils."""
    ages_s = ages_s or {}
    parts: dict[tuple[str, str], list[tuple[str, str, float]]] = defaultdict(list)
    extra: dict[tuple[str, str], list[Candidate]] = defaultdict(list)
    any_parts: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for source, c in proposals:
        if c.target == Anyone.ANY:
            any_parts[c.kind].append((source, c.reason, c.evidence))
            continue
        parts[(c.kind, c.target)].append((source, c.reason, c.evidence))
        extra[(c.kind, c.target)].append(c)

    rows: list[Row] = []
    for (kind, target), ps in sorted(parts.items()):
        if target != Anyone.NONE:
            ps = ps + any_parts.get(kind, [])
        cands = extra[(kind, target)]
        evidence = sum(p[2] for p in ps)
        strongest = max((c.evidence for c in cands), default=0.0)
        view = RowView(kind, target, evidence, tuple(sorted({p[1] for p in ps})), strongest)
        shift = 0.0
        by_owner: dict[str, float] = {}
        vetoes: list[tuple[str, str]] = []
        for source, m in modulate(view):
            shift += m.shift
            if m.shift:
                by_owner[source] = by_owner.get(source, 0.0) + m.shift
            if m.veto:
                vetoes.append((source, m.veto))
        key = f"{kind}:{target}"
        aging = policy.aging_per_hour.get(kind, 0.0) * ages_s.get(key, 0.0) / 3600.0
        threshold = policy.thresholds.get(kind, 0.0)
        score = evidence + shift + aging - threshold
        rate = policy.max_rates.get(kind, 0.0)
        hazard = 0.0 if vetoes else rate * sigmoid(score)
        resources: frozenset[str] = frozenset().union(*(c.resources for c in cands)) if cands else frozenset()
        guards = tuple(g for c in cands for g in c.guards)
        # un épisode porte sur un seul sujet : quand plusieurs candidats en ont un (deux buts, un projet,
        # sur la même adresse), seuls les arguments du plus fort passent ; les autres reviendront
        subjects = [c for c in cands if c.args.get("subject")]
        chosen = max(subjects, key=lambda c: (c.evidence, str(c.args["subject"]))) if subjects else None
        args: dict[str, Any] = {}
        for c in cands:
            if c is chosen or not c.args.get("subject"):
                args.update(c.args.to_dict())
        deadlines = [c.deadline for c in cands if c.deadline is not None]
        rows.append(
            Row(kind, target, tuple(sorted(ps)), shift, tuple(sorted(vetoes)), score, hazard,
                resources, guards, FrozenDict(args), min(deadlines) if deadlines else None,
                threshold=threshold, aging=aging, shifts=tuple(sorted(by_owner.items())))
        )
    rows = _share_any(rows, {k: sum(p[2] for p in v) for k, v in any_parts.items()}, policy)
    rows.sort(key=lambda r: (-r.hazard, r.key))
    return rows


def _share_any(rows: list[Row], any_evidence: Mapping[str, float], policy: ArbitrationPolicy) -> list[Row]:
    """Une envie « ANY » (parler à quelqu'un, n'importe qui) est **une** envie,
    pas une par présent : sans cela, huit personnes connectées multipliaient
    par huit son taux d'initiative. Ce qu'elle ajoute à l'intensité est donc
    partagé entre les lignes de son type : au total, pas plus que ce qu'elle
    ajoute à la ligne qu'elle soulève le plus — chacune en garde une part au
    prorata de ce qu'elle lui ajoutait (le choix de la cible reste au prorata).
    Une envie négative (une retenue) freine chaque ligne, elle n'a pas à être
    partagée."""
    extra: dict[int, float] = {}
    own: dict[int, float] = {}
    for i, r in enumerate(rows):
        ev = any_evidence.get(r.kind, 0.0)
        if r.target == Anyone.NONE or not ev or r.vetoes or r.hazard <= 0.0:
            continue
        base = policy.max_rates.get(r.kind, 0.0) * sigmoid(r.score - ev)
        if r.hazard > base:
            own[i], extra[i] = base, r.hazard - base
    by_kind: dict[str, list[int]] = defaultdict(list)
    for i in extra:
        by_kind[rows[i].kind].append(i)
    out = list(rows)
    for idx in by_kind.values():
        total, most = sum(extra[i] for i in idx), max(extra[i] for i in idx)
        if total <= most:
            continue
        factor = most / total
        for i in idx:
            out[i] = replace(rows[i], hazard=own[i] + extra[i] * factor)
    return out


def rate_bound(rows: Sequence[Row], policy: ArbitrationPolicy) -> float:
    """Borne supérieure de l'intensité totale : σ ≤ 1."""
    return sum(policy.max_rates.get(r.kind, 0.0) for r in rows if not r.vetoes)


def local_bound(rows: Sequence[Row], headroom: float = 2.0) -> float:
    """Une borne de l'intensité totale valable jusqu'à la prochaine
    réévaluation : ``headroom`` fois l'intensité actuelle. L'intensité ne
    change qu'avec un événement (réévaluation immédiate) ou avec le temps
    (réévaluation périodique) ; entre deux, la marge couvre sa dérive."""
    return headroom * sum(r.hazard for r in rows)


def next_arrival_us(rng: random.Random, bound_per_s: float) -> int | None:
    if bound_per_s <= 0:
        return None
    return max(1, round(rng.expovariate(bound_per_s) * 1_000_000))


def thin(rows: Sequence[Row], bound_per_s: float, rng: random.Random) -> tuple[Row | None, float]:
    """Accepte l'occurrence avec la probabilité Σλ/borne, puis choisit une ligne
    proportionnellement à son intensité. Rend (ligne ou None, tirage)."""
    total = sum(r.hazard for r in rows)
    u = rng.random()
    if bound_per_s <= 0 or u * bound_per_s >= total:
        return None, u
    pick = rng.random() * total
    acc = 0.0
    for r in rows:
        acc += r.hazard
        if pick < acc:
            return r, u
    return rows[-1], u
