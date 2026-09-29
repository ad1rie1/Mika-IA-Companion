"""La faculté interne du runtime : épisodes ouverts, questions en attente,
effets en attente d'approbation. Sert à la reprise après un arrêt brutal."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from mika.contracts import runtime as rt
from mika.kernel.faculty import Faculty
from mika.kernel.state import FrozenDict
from mika.runtime.boundary import Failed, acall

REPLY = "REPLY"
MAX_REPLY_ATTEMPTS = 2
#: Issues qui ne règlent pas la question : elle reste en attente (dans la
#: limite des tentatives). Un arrêt, une panne, une supplantation ou une
#: préemption ne sont pas des réponses.
UNSETTLED = frozenset({"interrupted", "cancelled", "superseded", "preempted"})
#: Celles qui appellent une reprise immédiate (le processus tourne encore).
RETRY_NOW = frozenset({"superseded", "preempted"})
RESULT_MAX = 4000


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
    args_json: str = "{}"
    context: str = ""
    summary_ref: str = ""


@dataclass(frozen=True, slots=True)
class RuntimeState:
    open: FrozenDict[str, OpenEpisode] = FrozenDict()
    pending: FrozenDict[int, Pending] = FrozenDict()
    effects: FrozenDict[int, PendingEffect] = FrozenDict()


RUNTIME = Faculty("runtime", state=RuntimeState, init=lambda p: RuntimeState(), namespaces=rt.NAMESPACES)
RUNTIME.declare(*rt.ALL)


@RUNTIME.reducer(rt.PERCEPTION_RECEIVED)
def _perceived(s: RuntimeState, e, cx) -> RuntimeState:
    if not e.data.addressed:
        return s  # entendu, pas adressé : personne n'attend de réponse
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
    d = e.data
    return replace(s, effects=s.effects.set(e.seq, PendingEffect(d.capability, d.owner, e.at, d.args_json, d.context,
                                                                 d.summary.ref or "")))


@RUNTIME.reducer(rt.EFFECT_RESOLVED)
def _resolved(s: RuntimeState, e, cx) -> RuntimeState:
    return replace(s, effects=s.effects.delete(e.data.proposal))


@RUNTIME.fact(rt.AWAITING)
def _awaiting(s: RuntimeState, cx) -> tuple[int, ...]:
    return tuple(s.pending.keys())


@RUNTIME.fact(rt.PENDING_EFFECTS)
def _pending_effects(s: RuntimeState, cx) -> tuple[rt.PendingEffectView, ...]:
    return tuple(rt.PendingEffectView(seq, p.capability, p.owner, p.context, p.summary_ref, p.at)
                 for seq, p in sorted(s.effects.items()))


# ── Effets externes : exécutés après commit, jamais depuis un outil ───────


async def _execute(proposal: int, capability: str, args_json: str, context: str,
                   ports: Mapping[str, Any]) -> list[Any]:
    lookup = ports.get("capabilities")
    spec = lookup(capability) if lookup is not None else None
    if spec is None:
        return [rt.EFFECT_EXECUTED.draft(proposal=proposal, ok=False, result=f"capacité inconnue : {capability}")]
    try:
        args = json.loads(args_json or "{}")
    except ValueError:
        return [rt.EFFECT_EXECUTED.draft(proposal=proposal, ok=False, result="arguments illisibles")]
    out = await acall(spec.fn, args if isinstance(args, dict) else {}, context, ports, label=f"capacité {capability}")
    if isinstance(out, Failed):
        return [rt.EFFECT_EXECUTED.draft(proposal=proposal, ok=False, result=f"échec : {out.error!r}"[:RESULT_MAX])]
    ok, result = out
    return [rt.EFFECT_EXECUTED.draft(proposal=proposal, ok=bool(ok), result=str(result)[:RESULT_MAX])]


@RUNTIME.effect(rt.EFFECT_PROPOSED)
async def _auto(ev: Any, ports: Mapping[str, Any]) -> list[Any] | None:
    """Une proposition sans accord requis part tout de suite."""
    d = ev.data
    if d.approval:
        return None
    return await _execute(ev.seq, d.capability, d.args_json, d.context, ports)


@RUNTIME.effect(rt.EFFECT_RESOLVED)
async def _approved(ev: Any, ports: Mapping[str, Any]) -> list[Any] | None:
    d = ev.data
    if not d.approved:
        return None
    return await _execute(d.proposal, d.capability, d.args_json, d.context, ports)
