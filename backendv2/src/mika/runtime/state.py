"""La faculté interne du runtime : épisodes ouverts, questions en attente,
effets en attente d'approbation. Sert à la reprise après un arrêt brutal."""

from __future__ import annotations

from dataclasses import dataclass, replace

from mika.contracts import runtime as rt
from mika.kernel.faculty import Faculty
from mika.kernel.state import FrozenDict

REPLY = "REPLY"
MAX_REPLY_ATTEMPTS = 2
#: Issues qui ne règlent pas la question : elle reste en attente (dans la
#: limite des tentatives). Un arrêt, une panne, une supplantation ou une
#: préemption ne sont pas des réponses.
UNSETTLED = frozenset({"interrupted", "cancelled", "superseded", "preempted"})
#: Celles qui appellent une reprise immédiate (le processus tourne encore).
RETRY_NOW = frozenset({"superseded", "preempted"})


@dataclass(frozen=True, slots=True)
class OpenEpisode:
    kind: str
    started_at: int
    target: str | None = None
    reply_to: int | None = None


@dataclass(frozen=True, slots=True)
class Pending:
    handle: str
    at: int
    attempts: int = 0


@dataclass(frozen=True, slots=True)
class PendingEffect:
    capability: str
    owner: str
    at: int


@dataclass(frozen=True, slots=True)
class RuntimeState:
    open: FrozenDict[str, OpenEpisode] = FrozenDict()
    pending: FrozenDict[int, Pending] = FrozenDict()
    effects: FrozenDict[int, PendingEffect] = FrozenDict()


RUNTIME = Faculty("runtime", state=RuntimeState, init=lambda p: RuntimeState(), namespaces=rt.NAMESPACES)
RUNTIME.declare(*rt.ALL)


@RUNTIME.reducer(rt.PERCEPTION_RECEIVED)
def _perceived(s: RuntimeState, e, cx) -> RuntimeState:
    return replace(s, pending=s.pending.set(e.seq, Pending(e.data.handle, e.at)))


@RUNTIME.reducer(rt.EPISODE_STARTED)
def _started(s: RuntimeState, e, cx) -> RuntimeState:
    d = e.data
    s = replace(s, open=s.open.set(e.correlation, OpenEpisode(d.kind, e.at, d.target, d.reply_to)))
    if d.reply_to is not None and d.reply_to in s.pending:
        p = s.pending[d.reply_to]
        s = replace(s, pending=s.pending.set(d.reply_to, replace(p, attempts=p.attempts + 1)))
    return s


@RUNTIME.reducer(rt.UTTERANCE)
def _uttered(s: RuntimeState, e, cx) -> RuntimeState:
    if e.data.reply_to is not None:
        return replace(s, pending=s.pending.delete(e.data.reply_to))
    return s


@RUNTIME.reducer(rt.EPISODE_ENDED)
def _ended(s: RuntimeState, e, cx) -> RuntimeState:
    s = replace(s, open=s.open.delete(e.correlation))
    d = e.data
    if d.reply_to is not None and d.reply_to in s.pending:
        attempts = s.pending[d.reply_to].attempts
        keep = d.outcome in UNSETTLED and attempts < MAX_REPLY_ATTEMPTS
        if not keep:
            s = replace(s, pending=s.pending.delete(d.reply_to))
    return s


@RUNTIME.reducer(rt.EFFECT_PROPOSED)
def _proposed(s: RuntimeState, e, cx) -> RuntimeState:
    if not e.data.approval:
        return s
    return replace(s, effects=s.effects.set(e.seq, PendingEffect(e.data.capability, e.data.owner, e.at)))


@RUNTIME.reducer(rt.EFFECT_RESOLVED)
def _resolved(s: RuntimeState, e, cx) -> RuntimeState:
    return replace(s, effects=s.effects.delete(e.data.proposal))
