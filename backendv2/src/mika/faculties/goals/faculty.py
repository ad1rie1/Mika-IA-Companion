"""La faculté ``goals`` : sa tranche, ses réducteurs, ses faits, ce que ses
événements font ressentir.

- **Un pas se réserve au départ** (``episode.started``) : un pas qui tue le
  processus n'est pas rejoué à l'infini ; un pas qui échoue sans que le
  modèle ait répondu (panne, délai, supplantation) **rend son crédit**.
- **Un pas sans verdict** compte : trois de suite, et le but est bloqué.
- **« Fini » sans preuve** n'est pas fini : il est noté, le but continue.
- **L'envie** d'une exploration s'use (demi-vie de six heures) ; celle d'un
  projet confié ne s'use pas — c'est un engagement.
- **Un rappel** qui n'a pas pu être dit est retenté, espacé (5 min × n), au
  plus trois fois.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import goals as c
from mika.contracts import runtime as rt
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.events import Content, Payload
from mika.kernel.faculty import Faculty
from mika.kernel.state import FrozenDict
from mika.vocab.affect import Appraisal, Emotion
from mika.vocab.episodes import Kind, goal_of
from mika.vocab.temperament import Temperament

KEEP_CLOSED = 32
NOTES_KEPT = 5


class GoalsParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # l'envie d'une exploration
    desire_half_life_us: int = 6 * HOUR
    abandon_below: float = 0.15
    # les pas
    step_spacing_us: int = 30 * MINUTE
    project_spacing_us: int = 10 * MINUTE
    steps_per_hour: int = 4
    exploration_steps: int = 4
    project_steps: int = 12
    silent_before_blocked: int = 3
    failures_before_failed: int = 5
    wait_min_us: int = 10 * MINUTE
    wait_max_us: int = DAY
    # preuves (log-odds) : de l'envie au pas ; un projet confié, constant quand il est dû
    work_base: float = 4.0
    work_per_desire: float = 8.0
    project_evidence: float = 10.0
    # rappels
    remind_evidence: float = 12.0
    remind_attempts: int = 3
    remind_retry_us: int = 5 * MINUTE
    remind_too_late_us: int = 12 * HOUR
    # ouvrir de soi-même
    live_self_max: int = 2
    seed_spacing_us: int = 2 * HOUR
    seed_thought_from: float = 0.35
    seed_thought_age_us: int = 30 * MINUTE
    seed_curiosity_from: float = 0.7
    seed_day_start_min: int = 9 * 60
    seed_day_end_min: int = 21 * 60
    no_reopen_us: int = DAY
    interest_rest_us: int = 3 * DAY
    # raconter ce qu'elle a mené à bout
    share_notable_from: float = 0.4
    share_within_us: int = 12 * HOUR
    share_evidence: float = 10.0
    share_attempts: int = 2


def derive(t: Temperament, overrides: Any = None) -> GoalsParams:
    """La persévérance donne plus de pas et une envie plus tenace ; la
    curiosité ouvre une exploration plus tôt."""
    values: dict[str, Any] = {
        "exploration_steps": 3 + round(3 * t.perseverance),
        "desire_half_life_us": round((3 + 6 * t.perseverance) * HOUR),
        "seed_curiosity_from": round(0.85 - 0.3 * t.curiosity, 3),
    }
    values.update(dict(overrides or {}))
    return GoalsParams(**values)


@dataclass(frozen=True, slots=True)
class Goal:
    id: int
    kind: str
    authority: str
    title_ref: str
    opened_at: int
    details_ref: str = ""
    owner: str | None = None
    address: str | None = None
    about: tuple[str, ...] = ()
    sensitivity: int = 1
    source: str = ""
    bundles: tuple[str, ...] = ()
    max_steps: int = 0
    due: int | None = None
    urgent: bool = False
    schedule: str = ""
    approval: bool = True
    status: str = c.ACTIVE
    desire: float = 0.0
    desire_at: int = 0
    # le travail
    steps: int = 0
    silent: int = 0
    unproven: int = 0
    failures: int = 0
    evidence: int = 0
    last_step_at: int = 0
    waiting_until: int = 0
    summary_ref: str = ""
    notes: tuple[str, ...] = ()  # références des notes de son carnet
    effects: tuple[str, ...] = ()  # ce que sont devenus ses effets externes (courtes lignes)
    # les rappels
    delivered: bool = False
    attempts: int = 0
    retry_at: int = 0
    # clos
    closed_at: int = 0
    notable: float = 0.0
    result_ref: str = ""
    shared: bool = False
    share_attempts: int = 0


@dataclass(frozen=True, slots=True)
class Run:
    goal: int
    purpose: str  # "step" | "remind" | "share"
    reported: bool = False


@dataclass(frozen=True, slots=True)
class GoalsState:
    goals: FrozenDict[int, Goal] = field(default_factory=FrozenDict)
    running: FrozenDict[str, Run] = field(default_factory=FrozenDict)
    #: les pas de la dernière heure (plafond horaire)
    steps_at: tuple[int, ...] = ()
    #: source → fermeture : on ne rouvre pas sous 24 h ce qu'on vient de clore
    closed_sources: FrozenDict[str, int] = field(default_factory=FrozenDict)
    #: centre d'intérêt → dernière exploration
    explored: FrozenDict[str, int] = field(default_factory=FrozenDict)
    #: proposition d'effet → but
    proposals: FrozenDict[int, int] = field(default_factory=FrozenDict)
    #: la dernière fois qu'elle a entrepris quelque chose d'elle-même
    self_opened_at: int = 0


GOALS = Faculty("goals", state=GoalsState, init=lambda p: GoalsState(), params=GoalsParams, derive=derive)
GOALS.declare(*c.ALL)


class Noted(Payload):
    """Une note de son carnet de travail (privée : personne d'autre ne la réduit)."""

    goal: int
    text: Content


NOTED = GOALS.event("noted", Noted, content=("text",))


def params(p: GoalsParams | None) -> GoalsParams:
    return p if p is not None else GoalsParams()


def desire(g: Goal, now: int, p: GoalsParams) -> float:
    if g.kind != c.EXPLORATION:
        return 1.0
    return g.desire * 0.5 ** (max(0, now - g.desire_at) / p.desire_half_life_us)


def status(g: Goal, now: int) -> str:
    """Le statut à l'instant : une attente échue redevient active."""
    if g.status == c.WAITING and g.waiting_until <= now:
        return c.ACTIVE
    return g.status


def live(g: Goal, now: int) -> bool:
    return status(g, now) in (c.ACTIVE, c.WAITING)


def _set(s: GoalsState, g: Goal) -> GoalsState:
    return replace(s, goals=s.goals.set(g.id, g))


def _prune(s: GoalsState, now: int) -> GoalsState:
    closed = sorted((g for g in s.goals.values() if g.status in c.CLOSED_STATUSES), key=lambda g: (g.closed_at, g.id))
    drop = [g.id for g in closed[:-KEEP_CLOSED]] + [g.id for g in closed if now - g.closed_at > 7 * DAY]
    goals = s.goals
    for gid in drop:
        goals = goals.delete(gid)
    sources = FrozenDict({k: v for k, v in s.closed_sources.items() if now - v <= 7 * DAY})
    proposals = FrozenDict({k: v for k, v in s.proposals.items() if v in goals})
    return replace(s, goals=goals, closed_sources=sources, proposals=proposals)


# ── Réducteurs ────────────────────────────────────────────────────────────


@GOALS.reducer(c.GOAL_OPENED)
def _opened(s: GoalsState, e, cx) -> GoalsState:
    d = e.data
    g = Goal(
        id=e.seq, kind=d.kind, authority=d.authority, title_ref=d.title.ref or "", opened_at=e.at,
        details_ref=d.details.ref or "" if d.details is not None else "", owner=d.owner, address=d.address,
        about=tuple(d.about), sensitivity=d.sensitivity, source=d.source, bundles=tuple(d.bundles),
        max_steps=d.max_steps, due=d.due, urgent=d.urgent, schedule=d.schedule, approval=d.approval,
        desire=d.desire, desire_at=e.at,
    )
    s = _set(s, g)
    if d.source.startswith("interest:"):
        s = replace(s, explored=s.explored.set(d.source, e.at))
    if d.authority == c.SELF:
        s = replace(s, self_opened_at=e.at)
    return s


@GOALS.reducer(rt.EPISODE_STARTED)
def _started(s: GoalsState, e, cx) -> GoalsState:
    d = e.data
    if d.kind == Kind.STEP:
        gid = goal_of(d.target)
        g = s.goals.get(gid) if gid is not None else None
        if g is None:
            return s
        s = replace(s, running=s.running.set(e.correlation, Run(g.id, "step")),
                    steps_at=tuple(t for t in s.steps_at if e.at - t < HOUR) + (e.at,))
        return _set(s, replace(g, steps=g.steps + 1, last_step_at=e.at))
    gid = goal_of(d.subject)
    if d.kind != Kind.INITIATIVE or gid is None or gid not in s.goals:
        return s
    reasons = d.reason.split(",")
    purpose = "remind" if c.REMIND in reasons else "share" if c.SHARE in reasons else ""
    if not purpose:
        return s
    return replace(s, running=s.running.set(e.correlation, Run(gid, purpose)))


@GOALS.reducer(rt.UTTERANCE)
def _uttered(s: GoalsState, e, cx) -> GoalsState:
    run = s.running.get(e.correlation)
    if run is None or run.goal not in s.goals:
        return s
    g = s.goals[run.goal]
    if run.purpose == "remind":
        return _set(s, replace(g, delivered=True))
    if run.purpose == "share":
        return _set(s, replace(g, shared=True))
    return s


#: Ce qui ne dit rien du pas : il n'a pas eu lieu, son crédit est rendu.
REFUND = frozenset({"failed", "timeout", "superseded", "preempted", "cancelled", "interrupted"})


@GOALS.reducer(rt.EPISODE_ENDED)
def _ended(s: GoalsState, e, cx) -> GoalsState:
    run = s.running.get(e.correlation)
    if run is None:
        return s
    s = replace(s, running=s.running.delete(e.correlation))
    g = s.goals.get(run.goal)
    if g is None:
        return s
    p = params(cx.params)
    outcome = e.data.outcome
    if run.purpose == "step":
        if run.reported:
            return s
        if outcome in REFUND:
            broke = outcome in ("failed", "timeout")
            return _set(s, replace(g, steps=max(0, g.steps - 1), failures=g.failures + (1 if broke else 0)))
        return _set(s, replace(g, silent=g.silent + 1))  # le modèle a travaillé, mais n'a rien conclu
    if run.purpose == "remind" and not g.delivered:
        if outcome in ("superseded", "preempted", "cancelled", "interrupted"):
            return _set(s, replace(g, retry_at=e.at + p.remind_retry_us))
        n = g.attempts + 1
        return _set(s, replace(g, attempts=n, retry_at=e.at + p.remind_retry_us * n))
    if run.purpose == "share" and not g.shared:
        return _set(s, replace(g, share_attempts=g.share_attempts + 1))
    return s


@GOALS.reducer(c.STEP_REPORTED)
def _reported(s: GoalsState, e, cx) -> GoalsState:
    d = e.data
    g = s.goals.get(d.goal)
    if g is None:
        return s
    run = s.running.get(e.correlation)
    if run is not None and run.goal == g.id:
        s = replace(s, running=s.running.set(e.correlation, replace(run, reported=True)))
    p = params(cx.params)
    g = replace(g, silent=0, failures=0, summary_ref=d.summary.ref or g.summary_ref,
                evidence=g.evidence + len(d.tools))
    if d.verdict == c.WAIT:
        wait = max(p.wait_min_us, min(p.wait_max_us, d.wait_s * 1_000_000))
        g = replace(g, status=c.WAITING, waiting_until=e.at + wait)
    elif d.verdict == c.DONE and not d.proven:
        g = replace(g, unproven=g.unproven + 1)
    elif g.status == c.WAITING:
        g = replace(g, status=c.ACTIVE)
    return _set(s, g)


@GOALS.reducer(NOTED)
def _noted(s: GoalsState, e, cx) -> GoalsState:
    g = s.goals.get(e.data.goal)
    if g is None or not e.data.text.ref:
        return s
    return _set(s, replace(g, notes=(*g.notes, e.data.text.ref)[-NOTES_KEPT:]))


@GOALS.reducer(c.GOAL_CLOSED)
def _closed(s: GoalsState, e, cx) -> GoalsState:
    d = e.data
    g = s.goals.get(d.goal)
    if g is None or g.status in c.CLOSED_STATUSES:
        return s
    g = replace(g, status=d.status, closed_at=e.at, notable=d.notable,
                result_ref=d.result.ref or "" if d.result is not None else "")
    s = _set(s, g)
    if g.source:
        s = replace(s, closed_sources=s.closed_sources.set(g.source, e.at))
    return _prune(s, e.at)


@GOALS.reducer(rt.EFFECT_PROPOSED)
def _proposed(s: GoalsState, e, cx) -> GoalsState:
    gid = goal_of(e.data.context)
    if e.data.owner != c.OWNER or gid is None or gid not in s.goals:
        return s
    g = s.goals[gid]
    line = f"#{e.seq} proposé ({e.data.capability})" + (" — en attente d'accord" if e.data.approval else "")
    return replace(_set(s, replace(g, effects=(*g.effects, line)[-NOTES_KEPT:])),
                   proposals=s.proposals.set(e.seq, gid))


@GOALS.reducer(rt.EFFECT_RESOLVED)
def _resolved(s: GoalsState, e, cx) -> GoalsState:
    gid = s.proposals.get(e.data.proposal)
    if gid is None or gid not in s.goals or e.data.approved:
        return s
    g = s.goals[gid]
    note = f" : « {e.data.note[:200]} »" if e.data.note else ""
    line = f"#{e.data.proposal} refusé{note}"
    return _set(s, replace(g, effects=(*g.effects, line)[-NOTES_KEPT:]))


@GOALS.reducer(rt.EFFECT_EXECUTED)
def _executed(s: GoalsState, e, cx) -> GoalsState:
    gid = s.proposals.get(e.data.proposal)
    if gid is None or gid not in s.goals:
        return s
    g = s.goals[gid]
    line = f"#{e.data.proposal} {'fait' if e.data.ok else 'échoué'} : {e.data.result[:300]}"
    return _set(s, replace(g, effects=(*g.effects, line)[-NOTES_KEPT:]))


# ── Faits ─────────────────────────────────────────────────────────────────


def view(g: Goal, now: int) -> c.GoalView:
    return c.GoalView(
        id=g.id, kind=g.kind, authority=g.authority, status=status(g, now), title_ref=g.title_ref, owner=g.owner,
        about=g.about, sensitivity=g.sensitivity, opened_at=g.opened_at, steps=g.steps, max_steps=g.max_steps,
        due=g.due, waiting_until=g.waiting_until if status(g, now) == c.WAITING else 0,
        last_summary_ref=g.summary_ref, schedule=g.schedule,
    )


@GOALS.fact(c.LIVE)
def _live(s: GoalsState, cx) -> tuple[c.GoalView, ...]:
    return tuple(view(g, cx.now) for g in sorted(s.goals.values(), key=lambda g: g.id) if live(g, cx.now))


@GOALS.fact(c.STATUS)
def _status(s: GoalsState, cx, goal: int) -> str:
    g = s.goals.get(goal)
    return status(g, cx.now) if g is not None else ""


# ── Ce que ses événements font ressentir ──────────────────────────────────


@GOALS.appraisal(c.GOAL_CLOSED)
def _closed_felt(e, cx) -> Appraisal | None:
    """Mener à bout rend fière ; bloquer frustre ; renoncer d'elle-même laisse
    une teinte de mélancolie. Un rappel dit n'est pas un exploit."""
    d = e.data
    if d.kind == c.REMINDER:
        return None
    if d.status == c.ACHIEVED:
        return Appraisal(Emotion.PROUD, 0.4, reason="abouti")
    if d.status == c.STUCK:
        return Appraisal(Emotion.FRUSTRATED, 0.35, reason="bloquée")
    if d.status == c.ABANDONED:
        return Appraisal(Emotion.MELANCHOLIC, 0.25, reason="abandon")
    return None
