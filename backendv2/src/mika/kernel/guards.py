"""Gardes et baux : la validité d'une décision se vérifie au commit.

Un processus ou un épisode lit un état épinglé (sa *base*), travaille — un
appel de modèle peut durer une minute —, puis émet. Sa garde vérifie sur la
*tête* que ce qu'il a lu n'a pas changé (empreintes des faits), que son
prédicat tient encore, qu'il détient toujours ses baux et qu'il est vivant.
Sinon : ``Superseded``, et rien n'est ajouté.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from mika.kernel.builtin import LEASE
from mika.kernel.facts import FactRef, FactView


def floor(person: str) -> str:
    """La ressource « la parole avec cette personne »."""
    return f"floor:{person}"


def workshop(goal: str) -> str:
    """La ressource « l'atelier de ce but »."""
    return f"workshop:{goal}"


@dataclass(frozen=True, slots=True)
class Guard:
    name: str
    reads: tuple[FactRef, ...] = ()
    predicate: Callable[[FactView], bool] | None = None
    leases: tuple[str, ...] = ()
    max_lag: int | None = None

    def __and__(self, other: Guard) -> Guard:
        return combine(self, other)


def combine(*guards: Guard | None) -> Guard:
    real = [g for g in guards if g is not None]
    if not real:
        return Guard("vivant")
    preds = [g.predicate for g in real if g.predicate is not None]

    def predicate(view: FactView) -> bool:
        return all(p(view) for p in preds)

    reads: list[FactRef] = []
    for g in real:
        for r in g.reads:
            if r not in reads:
                reads.append(r)
    leases: list[str] = []
    for g in real:
        for lease in g.leases:
            if lease not in leases:
                leases.append(lease)
    lags = [g.max_lag for g in real if g.max_lag is not None]
    return Guard(
        name="+".join(g.name for g in real),
        reads=tuple(reads),
        predicate=predicate if preds else None,
        leases=tuple(leases),
        max_lag=min(lags) if lags else None,
    )


class Superseded(Exception):
    """La décision a été devancée : rien n'a été ajouté."""

    def __init__(self, guard: str, reason: str, changed: Iterable[str] = (), basis: int = 0, head: int = 0) -> None:
        self.guard = guard
        self.reason = reason
        self.changed = tuple(changed)
        self.basis = basis
        self.head = head
        detail = f" ({', '.join(self.changed)})" if self.changed else ""
        super().__init__(f"garde « {guard} » : {reason}{detail} [base {basis}, tête {head}]")


def check(
    guard: Guard,
    *,
    holder: str,
    basis_view: FactView,
    head_view: FactView,
    live: bool = True,
) -> Superseded | None:
    """Rend l'échec (sans le lever) ou ``None`` si la garde tient."""
    basis, head = basis_view.root.seq, head_view.root.seq
    if not live:
        return Superseded(guard.name, "épisode terminé", basis=basis, head=head)
    if guard.max_lag is not None and head - basis > guard.max_lag:
        return Superseded(guard.name, f"retard {head - basis} > {guard.max_lag}", basis=basis, head=head)
    changed = [repr(r) for r in guard.reads if basis_view.fingerprint(r) != head_view.fingerprint(r)]
    if changed:
        return Superseded(guard.name, "ce qui a été lu a changé", changed, basis, head)
    if guard.predicate is not None and not guard.predicate(head_view):
        return Superseded(guard.name, "le prédicat ne tient plus", basis=basis, head=head)
    for resource in guard.leases:
        lease = head_view.get(LEASE(resource))
        if lease is None or lease.holder != holder:
            return Superseded(guard.name, f"bail perdu : {resource}", basis=basis, head=head)
    return None
