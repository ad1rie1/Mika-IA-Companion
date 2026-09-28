"""L'arbitre : un processus interne dont l'échéance est la prochaine occurrence
d'un processus de Poisson aminci.

À chaque événement, l'échéance est retirée (l'intensité a pu changer ; un
processus sans mémoire le permet sans biais). À l'échéance, les lignes sont
recalculées, l'occurrence acceptée avec la probabilité Σλ/borne, une ligne
choisie proportionnellement à son intensité — si ses ressources sont libres,
``kernel.selected`` est ajouté et l'épisode demandé est lancé.
"""

from __future__ import annotations

import random
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any

from mika.kernel.arbitration import (
    Candidate,
    Modulation,
    Row,
    RowView,
    next_arrival_us,
    pool,
    rate_bound,
    thin,
)
from mika.kernel.builtin import LEASE, SELECTED
from mika.kernel.codec import h64
from mika.kernel.events import Event
from mika.kernel.faculty import ProcessSpec
from mika.kernel.frame import Frame
from mika.kernel.registry import Registry
from mika.kernel.state import Root
from mika.runtime.boundary import Failed, call

if TYPE_CHECKING:
    from mika.runtime.scheduler import ProcessContext

Submit = Callable[[Row, Frame], Awaitable[Any]]


class Arbiter:
    def __init__(self, registry_of: Callable[[], Registry], submit: Submit, *, seed: int | str = 0) -> None:
        self._registry_of = registry_of
        self._submit = submit
        self._seed = seed
        self.next_at: int | None = None
        self.first_seen: dict[str, int] = {}
        self.attempts = 0
        self.last_rows: list[Row] = []
        self.anomalies: list[str] = []
        self.fired: list[tuple[int, str]] = []

    def invalidate(self, events: Sequence[Event[Any]] = (), root: Root | None = None) -> None:
        self.next_at = None

    # ── lignes ──
    def rows(self, frame: Frame) -> list[Row]:
        reg = self._registry_of()
        proposals: list[tuple[str, Candidate]] = []
        for spec in reg.proposers:
            got = call(spec.fn, frame.state(spec.owner), frame, label=f"preuves de {spec.owner}")
            if isinstance(got, Failed) or got is None:
                continue
            for c in got:
                rng = spec.reasons.get(c.reason)
                if rng is None or c.kind not in spec.kinds:
                    self.anomalies.append(f"{spec.owner} : raison ou type non déclaré ({c.kind}/{c.reason})")
                    continue
                lo, hi = rng
                clamped = min(hi, max(lo, c.evidence))
                if clamped != c.evidence:
                    c = Candidate(c.kind, c.target, c.reason, clamped, c.args, c.resources, c.deadline, c.guards)
                proposals.append((spec.owner, c))

        def modulate(view: RowView) -> list[tuple[str, Modulation]]:
            out: list[tuple[str, Modulation]] = []
            for spec in reg.modulators:
                if view.kind not in spec.kinds:
                    continue
                m = call(spec.fn, frame.state(spec.owner), frame, view, label=f"modulation de {spec.owner}")
                if isinstance(m, Modulation):
                    out.append((spec.owner, m))
            return out

        now = frame.now
        keys = {f"{c.kind}:{c.target}" for _, c in proposals}
        for k in list(self.first_seen):
            if k not in keys:
                del self.first_seen[k]
        for k in keys:
            self.first_seen.setdefault(k, now)
        ages = {k: (now - t) / 1_000_000 for k, t in self.first_seen.items()}
        rows = pool(proposals, reg.arbitration, modulate, ages)
        self.last_rows = rows
        return rows

    def _rng(self, frame: Frame, salt: str) -> random.Random:
        return random.Random(h64("arbitre", self._seed, frame.seq, self.attempts, salt))

    # ── protocole de processus ──
    def next_due(self, state: Any, frame: Frame, last_run: int | None) -> int | None:
        if self.next_at is None:
            rows = self.rows(frame)
            dt = next_arrival_us(self._rng(frame, "arrivée"), rate_bound(rows, self._registry_of().arbitration))
            self.next_at = None if dt is None else frame.now + dt
        return self.next_at

    async def run(self, ctx: ProcessContext) -> None:
        self.next_at = None
        self.attempts += 1
        frame = ctx.frame
        reg = self._registry_of()
        rows = self.rows(frame)
        row, draw = thin(rows, rate_bound(rows, reg.arbitration), self._rng(frame, "amincissement"))
        if row is None:
            return
        for res in sorted(row.resources):
            if frame.get(LEASE(res)) is not None:
                return  # ressource occupée : l'occurrence est perdue, pas reportée
        await ctx.emit(
            SELECTED.draft(rows=tuple(r.record() for r in rows[: reg.arbitration.top_k]), fired=(row.key,), draw=draw),
            emitter="kernel",
        )
        self.fired.append((ctx.now, row.key))
        await self._submit(row, frame)


def arbiter_spec(arbiter: Arbiter, *, quantum_s: float = 600.0) -> ProcessSpec:
    return ProcessSpec(
        owner="kernel", name="arbitre", process=arbiter, wake_on=frozenset({"*"}), priority=10,
        max_quantum_us=int(quantum_s * 1_000_000), lane="arbitre",
    )
