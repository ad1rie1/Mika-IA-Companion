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
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any

from mika.kernel.arbitration import (
    Candidate,
    Modulation,
    Row,
    RowView,
    local_bound,
    next_arrival_us,
    pool,
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

Submit = Callable[[Row, Frame, int], Awaitable[Any]]


#: Au plus tard, l'intensité est réévaluée à ce rythme (une preuve qui monte
#: avec le temps seul — un silence qui s'allonge — est vue dans ce délai).
REEVALUATE_US = 300 * 1_000_000
#: la dernière table vivante gardée en mémoire (les lignes les plus intenses)
LAST_ROWS_KEPT = 256
#: les derniers déclenchements et anomalies gardés en mémoire
RECENT_KEPT = 512


class Arbiter:
    def __init__(self, registry_of: Callable[[], Registry], submit: Submit, *, seed: int | str = 0,
                 reevaluate_us: int = REEVALUATE_US) -> None:
        self._registry_of = registry_of
        self._submit = submit
        self._seed = seed
        self.reevaluate_us = reevaluate_us
        self.next_at: int | None = None
        #: la borne de l'occurrence en attente (0 : une simple réévaluation)
        self._bound = 0.0
        self.draws = 0
        self.first_seen: dict[str, int] = {}
        self.attempts = 0
        #: la dernière table calculée, entière jusqu'à ``LAST_ROWS_KEPT`` lignes
        #: (triées par intensité décroissante), et quand
        self.last_rows: list[Row] = []
        self.last_at: int | None = None
        self.last_seq: int | None = None
        self.anomalies: deque[str] = deque(maxlen=RECENT_KEPT)
        self.fired: deque[tuple[int, str]] = deque(maxlen=RECENT_KEPT)
        #: lignes déjà choisies dont l'épisode n'est pas terminé : on ne les
        #: choisit pas deux fois pendant qu'elles attendent leur tour
        self.queued: set[str] = set()

    def invalidate(self, events: Sequence[Event[Any]] = (), root: Root | None = None) -> None:
        self.next_at = None
        self._bound = 0.0
        for e in events:
            if e.type.name == "episode.ended":
                self.queued.discard(f"{e.data.kind}:{e.data.target or 'none'}")

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
        rows = [r for r in pool(proposals, reg.arbitration, modulate, ages) if r.key not in self.queued]
        self.last_rows = rows[:LAST_ROWS_KEPT]
        self.last_at, self.last_seq = now, frame.seq
        return rows

    def _rng(self, frame: Frame, salt: str) -> random.Random:
        return random.Random(h64("arbitre", self._seed, frame.seq, self.attempts, salt))

    # ── protocole de processus ──
    def next_due(self, state: Any, frame: Frame, last_run: int | None) -> int | None:
        if self.next_at is None:
            rows = self.rows(frame)
            bound = local_bound(rows)
            # deux réévaluations sans événement entre elles ne tirent pas le même
            # délai ; le compteur (et non l'instant, sensible à la microseconde
            # près au rythme des réveils) garde le tirage indépendant de la cadence
            self.draws += 1
            dt = next_arrival_us(self._rng(frame, f"arrivée:{self.draws}"), bound)
            if dt is None or dt >= self.reevaluate_us:
                self.next_at, self._bound = frame.now + self.reevaluate_us, 0.0
            else:
                self.next_at, self._bound = frame.now + dt, bound
        return self.next_at

    async def run(self, ctx: ProcessContext) -> None:
        bound, self._bound = self._bound, 0.0
        self.next_at = None
        if bound <= 0:
            return  # une réévaluation, pas une occurrence
        self.attempts += 1
        frame = ctx.frame
        reg = self._registry_of()
        rows = self.rows(frame)
        total = sum(r.hazard for r in rows)
        bound = max(bound, total)
        row, draw = thin(rows, bound, self._rng(frame, "amincissement"))
        if row is None:
            return
        for res in sorted(row.resources):
            if frame.get(LEASE(res)) is not None:
                return  # ressource occupée : l'occurrence est perdue, pas reportée
        commit = await ctx.emit(
            SELECTED.draft(rows=tuple(r.record() for r in shown(rows, row, reg.arbitration.top_k)),
                           fired=(row.key,), draw=draw, candidates=len(rows), bound=bound, total=total),
            emitter="kernel",
        )
        self.fired.append((ctx.now, row.key))
        # l'épisode porte le numéro exact de la sélection qui l'a choisi (``episode.started.selected``)
        if await self._submit(row, frame, commit.seqs[-1]):
            self.queued.add(row.key)


def shown(rows: Sequence[Row], fired: Row, top_k: int) -> list[Row]:
    """Les lignes journalisées d'une sélection : le haut de la table, et
    toujours la ligne choisie — une ligne tirée loin derrière les premières
    (l'amincissement choisit au prorata de l'intensité, pas le maximum) doit
    pouvoir s'expliquer."""
    top = list(rows[: max(0, top_k)])
    if all(r.key != fired.key for r in top):
        top.append(fired)
    return top


def arbiter_spec(arbiter: Arbiter, *, quantum_s: float = 600.0) -> ProcessSpec:
    return ProcessSpec(
        owner="kernel", name="arbitre", process=arbiter, wake_on=frozenset({"*"}), priority=10,
        max_quantum_us=int(quantum_s * 1_000_000), lane="arbitre",
    )
