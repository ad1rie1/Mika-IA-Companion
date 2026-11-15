"""Le rythme d'un projet : quel objectif est dû et dans quel ordre (ADR 0145, 0161), ses plafonds, sa plage de
travail.

Des lectures pures de son état, que lisent le départ d'une exécution (``work.py``), son prompt, ses outils et la
console ; ``faculty.py`` n'en a pas besoin (il ne l'importe pas).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from mika.contracts import projects as c
from mika.faculties.projects.faculty import Objective, Project, ProjectsParams, nudged, objective_at
from mika.kernel.clock import DAY, instant, local


def daily_cap(p: Project, pm: ProjectsParams) -> int:
    return p.runs_per_day or pm.runs_per_day


def cadence(o: Objective, pm: ProjectsParams) -> int:
    return o.cadence_us or pm.constant_cadence_us


def runs_today(p: Project, now: int) -> int:
    return sum(1 for t in p.runs_at if now - t < DAY)


def due_at(p: Project, o: Objective, pm: ProjectsParams) -> int:
    """Quand un objectif peut être repris : un ponctuel tout de suite ; un constant une cadence après son dernier
    passage — et son premier, une cadence après qu'il a pu commencer (l'étape dont il dépend faite, sinon sa
    naissance) : un bilan de la semaine ne tombe pas le jour où l'app vient d'être écrite (ADR 0161)."""
    if o.kind != c.CONSTANT:
        return o.waiting_until
    if o.passed_at:
        return max(o.passed_at + cadence(o, pm), o.waiting_until)
    dep = objective_at(p, o.after) if o.after else None
    began = max(o.at, dep.closed_at if dep is not None else 0)
    return max(began + cadence(o, pm), o.waiting_until)


def framing(p: Project) -> bool:
    """Il n'a pas encore de plan qui vaille (ADR 0145) : à cadrer, ou un plan proposé qui attend sa réponse."""
    return p.plan_state in (c.TO_FRAME, c.PROPOSED)


def ready(p: Project, o: Objective) -> bool:
    """Ce dont il dépend dans son plan est fait (ou retiré, ou oublié) : il peut être travaillé (ADR 0145)."""
    dep = objective_at(p, o.after) if o.after else None
    return dep is None or dep.status in (c.DONE, c.DROPPED)


#: un objectif de son plan passe par son rang ; un objectif à elle hors plan, après eux
_UNRANKED = 10_000


def _order(o: Objective) -> tuple[int, int, int]:
    """L'ordre des ponctuels : ce qu'on a ajouté hors de son plan d'abord (l'opérateur, la personne), puis les
    étapes de son plan à leur rang — une idée de départ qu'il garde a le sien (ADR 0161) —, puis ce qu'elle a ajouté
    d'elle-même."""
    if o.rank:
        return 1, o.rank, o.id
    return (2 if o.author == "self" else 0), _UNRANKED, o.id


def pick(p: Project, now: int, pm: ProjectsParams) -> Objective | None:
    """L'objectif de la prochaine exécution : celui qu'on a demandé, sinon le constant le plus en retard,
    sinon le premier ponctuel ouvert (``_order``). Un objectif attend celui dont il dépend ; sans plan qui vaille,
    aucun (ADR 0145). Rien de dû : rien."""
    if framing(p):
        return None
    if nudged(p) and p.nudged_objective:
        wanted = objective_at(p, p.nudged_objective)
        if wanted is not None and wanted.status == c.OPEN:
            return wanted
    opened = [o for o in p.objectives if o.status == c.OPEN and ready(p, o)]
    constants = sorted((due_at(p, o, pm), o.id, o) for o in opened
                       if o.kind == c.CONSTANT and o.waiting_until <= now)
    due = [o for at, _, o in constants if at <= now]
    if due:
        return due[0]
    once = [o for o in opened if o.kind == c.ONCE and o.waiting_until <= now]
    once.sort(key=_order)
    if once:
        return once[0]
    # « lancer maintenant » sans rien de dû : le constant le plus proche de sa cadence, en avance
    return constants[0][2] if constants and nudged(p) else None


def next_due(p: Project, pm: ProjectsParams) -> int | None:
    """Le prochain instant où un objectif de ce projet sera dû (sans tenir compte de la plage) — aucun tant qu'il n'a
    pas de plan qui vaille."""
    if framing(p):
        return None
    times = [due_at(p, o, pm) for o in p.objectives if o.status == c.OPEN and ready(p, o)]
    return min(times) if times else None


# ── La plage de travail ───────────────────────────────────────────────────


def _day_ok(days: str, weekday: int) -> bool:
    if days == c.WEEKDAYS:
        return weekday < 5
    if days == c.WEEKEND:
        return weekday >= 5
    return True


def always(p: Project) -> bool:
    return p.days == c.EVERY_DAY and p.start_min <= 0 and p.end_min >= 24 * 60


def in_window(p: Project, t: int, tz: ZoneInfo) -> bool:
    """``t`` tombe-t-il dans sa plage de travail (jours, heures locales ; une plage dont la fin précède le
    début passe minuit et appartient au jour où elle commence) ?"""
    if always(p):
        return True
    dt = local(t, tz)
    minute = dt.hour * 60 + dt.minute
    start, end = p.start_min, p.end_min
    if start < end:
        return _day_ok(p.days, dt.weekday()) and start <= minute < end
    if minute >= start:
        return _day_ok(p.days, dt.weekday())
    return minute < end and _day_ok(p.days, (dt.weekday() - 1) % 7)


def window_opens(p: Project, after: int, tz: ZoneInfo) -> int | None:
    """Le premier instant à partir de ``after`` qui tombe dans sa plage (``None`` : jamais, sur huit jours)."""
    if in_window(p, after, tz):
        return after
    base = local(after, tz)
    for d in range(0, 9):
        day = (base + timedelta(days=d)).date()
        start = datetime(day.year, day.month, day.day, tzinfo=tz) + timedelta(minutes=p.start_min)
        at = instant(start)
        if at >= after and in_window(p, at, tz):
            return at
    return None
