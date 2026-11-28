"""L'arbitre : un processus interne dont l'échéance est la prochaine occurrence
d'un processus de Poisson aminci.

À chaque événement, l'échéance est retirée (l'intensité a pu changer ; un
processus sans mémoire le permet sans biais). À l'échéance, les lignes sont
recalculées, l'occurrence acceptée avec la probabilité Σλ/borne, une ligne
choisie proportionnellement à son intensité — si ses ressources sont libres,
``kernel.selected`` est ajouté et l'épisode demandé est lancé.

Une ligne **attendue** (ADR 0306 : quelqu'un a demandé ce travail, « Préremplir avec Mika ») n'est pas une envie à
elle : ni le décalage d'usage ni la retenue des modèles ne la touchent (elle partira au premier plan). Tant qu'une de
ses ressources est tenue par ce qui ne lui cède pas la place, elle attend sous un veto (``BUSY``) plutôt que de perdre
une occurrence par seconde — la fin du bail est un événement, qui la relance ; un épisode qu'elle supplante (ce qu'elle
fait d'elle-même) ne la retient pas. Son essai qui a échoué (une panne, un délai) ou que la file a refusé attend une
minute avant le suivant (``RETRY``) : une panne passagère ne brûle pas ses essais en deux secondes.
"""

from __future__ import annotations

import random
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
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
from mika.runtime.state import RUNTIME
from mika.vocab.episodes import Kind

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
#: le veto d'une ligne dont le fournisseur refuserait l'appel d'avance (``LLMGateway.held``, ADR 0127)
HELD = "held"
#: le veto d'une ligne attendue dont une ressource est tenue (ADR 0306) : elle repart à la fin du bail
BUSY = "busy"
#: le veto d'une ligne attendue dont l'essai vient d'échouer (ADR 0306) : elle repart à la fin de ``RETRY_US``
RETRY = "retry"
RETRY_US = 60 * 1_000_000
#: les issues d'un essai qui a échoué : le suivant attend ``RETRY_US``
_FAILED = frozenset({"failed", "timeout"})
#: les réglages d'usage du runtime (``RuntimeParams``, ADR 0149) : le décalage de chaque sorte d'épisode — prendre
#: la parole, se mettre au travail ; les réveils par API n'en ont pas, quelqu'un les attend
USAGE_SHIFTS = {Kind.INITIATIVE: "speak_shift", Kind.STEP: "work_shift", Kind.TASK: "work_shift",
                Kind.WORK: "work_shift", Kind.JOB: "work_shift"}


class Arbiter:
    def __init__(self, registry_of: Callable[[], Registry], submit: Submit, *, seed: int | str = 0,
                 reevaluate_us: int = REEVALUATE_US, held: Callable[[str], str] | None = None,
                 yields: Callable[[str], bool] | None = None) -> None:
        self._registry_of = registry_of
        self._submit = submit
        #: le détenteur d'un bail le cède-t-il au premier plan (``EpisodeRunner.yields``, ADR 0306) ?
        self._yields = yields
        #: une ligne attendue → la fin de son attente après un essai qui a échoué (``RETRY_US``) ; en mémoire
        self.cooling: dict[str, int] = {}
        #: sorte d'épisode → la raison pour laquelle son fournisseur le refuserait d'avance (« » : il passerait) —
        #: le quota d'un abonnement réservé à la conversation (ADR 0127)
        self._held = held
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
                key = f"{e.data.kind}:{e.data.target or 'none'}"
                self.queued.discard(key)
                if e.data.outcome in _FAILED:
                    self.cooling[key] = e.at + RETRY_US

    # ── lignes ──
    def rows(self, frame: Frame, *, record: bool = True) -> list[Row]:
        """La table de l'arbitre dans ce cadre. ``record=False`` : une lecture seule (« Voir l'effet » d'un
        réglage, lu sous d'autres paramètres) — l'âge des lignes, la dernière table et les anomalies ne
        bougent pas, l'âge d'une ligne qui n'existe pas encore vaut zéro."""
        reg = self._registry_of()
        proposals: list[tuple[str, Candidate]] = []
        for spec in reg.proposers:
            got = call(spec.fn, frame.state(spec.owner), frame, label=f"preuves de {spec.owner}")
            if isinstance(got, Failed) or got is None:
                continue
            for c in got:
                rng = spec.reasons.get(c.reason)
                if rng is None or c.kind not in spec.kinds:
                    if record:
                        self.anomalies.append(f"{spec.owner} : raison ou type non déclaré ({c.kind}/{c.reason})")
                    continue
                lo, hi = rng
                clamped = min(hi, max(lo, c.evidence))
                if clamped != c.evidence:
                    c = replace(c, evidence=clamped)
                proposals.append((spec.owner, c))

        held: dict[str, str] = {}
        # lus dans le cadre : « Voir l'effet » les lit sous les paramètres prévus
        usage = frame.env.params_of(RUNTIME.name, frame.root) if RUNTIME.name in reg.faculties else None

        def modulate(view: RowView) -> list[tuple[str, Modulation]]:
            out: list[tuple[str, Modulation]] = []
            # ce que quelqu'un attend n'est ni une envie de parler ni une envie de travailler, et part au premier plan,
            # que la retenue des modèles laisse toujours passer (ADR 0306)
            knob = None if view.awaited else USAGE_SHIFTS.get(view.kind)
            shift = getattr(usage, knob, 0.0) if knob is not None else 0.0
            if shift:
                out.append((RUNTIME.name, Modulation(shift=shift)))
            if self._held is not None and not view.awaited:
                # un épisode que son fournisseur refuserait d'avance ne se lance pas : il finirait en zéro seconde,
                # sans rien faire, et un but le compterait (ADR 0127)
                if view.kind not in held:
                    got = call(self._held, view.kind, label="retenue des modèles")
                    held[view.kind] = got if isinstance(got, str) else ""
                if held[view.kind]:
                    out.append(("kernel", Modulation(veto=HELD)))
            for spec in reg.modulators:
                if view.kind not in spec.kinds:
                    continue
                m = call(spec.fn, frame.state(spec.owner), frame, view, label=f"modulation de {spec.owner}")
                if isinstance(m, Modulation):
                    out.append((spec.owner, m))
            return out

        now = frame.now
        keys = {f"{c.kind}:{c.target}" for _, c in proposals}
        if record:
            for k in list(self.first_seen):
                if k not in keys:
                    del self.first_seen[k]
            for k in keys:
                self.first_seen.setdefault(k, now)
            seen = self.first_seen
        else:
            seen = {k: self.first_seen.get(k, now) for k in keys}
        ages = {k: (now - t) / 1_000_000 for k, t in seen.items()}
        if record:
            self.cooling = {k: t for k, t in self.cooling.items() if t > now}
        rows = [self._waiting(r, frame) for r in pool(proposals, reg.arbitration, modulate, ages)
                if r.key not in self.queued]
        rows.sort(key=lambda r: (-r.hazard, r.key))
        if record:
            self.last_rows = rows[:LAST_ROWS_KEPT]
            self.last_at, self.last_seq = now, frame.seq
        return rows

    def _waiting(self, row: Row, frame: Frame) -> Row:
        """Une ligne attendue qui doit patienter (ADR 0306) : son essai vient d'échouer (``RETRY``, jusqu'à la fin de
        son attente), ou une de ses ressources est tenue par ce qui ne lui cède pas la place (``BUSY``, jusqu'à la fin
        du bail) — à son taux, elle perdrait sinon une occurrence par seconde. Les autres lignes perdent la leur, comme
        toujours."""
        if not row.awaited or row.vetoes:
            return row
        if self.cooling.get(row.key, 0) > frame.now:
            return replace(row, vetoes=(("kernel", RETRY),), hazard=0.0)
        for res in row.resources:
            lease = frame.get(LEASE(res))
            if lease is not None and not self._gives_way(lease.holder):
                return replace(row, vetoes=(("kernel", BUSY),), hazard=0.0)
        return row

    def _gives_way(self, holder: str) -> bool:
        """Le détenteur de ce bail le cède-t-il au premier plan (ce qu'elle fait d'elle-même, ADR 0306) ?"""
        return self._yields is not None and call(self._yields, holder, label="bail cédé") is True

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
            # une ligne attendue qui patiente après un essai échoué repart à la fin de son attente : une réévaluation
            soon = min((t for t in self.cooling.values() if t > frame.now), default=None)
            if soon is not None and soon < self.next_at:
                self.next_at, self._bound = soon, 0.0
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
            lease = frame.get(LEASE(res))
            if lease is not None and not (row.awaited and self._gives_way(lease.holder)):
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
        elif row.awaited:
            # la file l'a refusé (pleine) : une ligne attendue ne se resélectionne pas chaque seconde
            self.cooling[row.key] = ctx.now + RETRY_US


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
        max_quantum_us=int(quantum_s * 1_000_000),
    )
