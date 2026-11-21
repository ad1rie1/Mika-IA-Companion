"""Le rythme d'un projet : quel objectif est dû et dans quel ordre (ADR 0145, 0161), ses plafonds, sa plage de
travail.

Un constant est dû au plus tôt de sa cadence et de ce qui le déclenche (ADR 0265) : une cause en attente le rend
dû quand le travail s'est posé — un délai réglable après la dernière cause, une heure au plus après la première.
Sans cadence (``only_on_event``), il ne passe que sur événement — sauf celui qui attend les tickets du projet : tant
qu'un ticket a la main chez elle, il revient à la cadence de secours (``fallback_due``, ADR 0272).

Des lectures pures de son état, que lisent le départ d'une exécution (``work.py``), son prompt, ses outils et la
console ; ``faculty.py`` n'en a pas besoin (il ne l'importe pas).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from mika.contracts import projects as c
from mika.faculties.projects import triggers
from mika.faculties.projects.faculty import (
    STIR_MAX_WAIT,
    Objective,
    Project,
    ProjectsParams,
    awaiting,
    nudged,
    objective_at,
)
from mika.kernel.clock import DAY, instant, local

#: jamais de lui-même : l'échéance d'un constant sans cadence que rien n'a déclenché
NEVER = 1 << 62


def daily_cap(p: Project, pm: ProjectsParams) -> int:
    return p.runs_per_day or pm.runs_per_day


def cadence(o: Objective, pm: ProjectsParams) -> int:
    return o.cadence_us or pm.constant_cadence_us


def runs_today(p: Project, now: int) -> int:
    return sum(1 for t in p.runs_at if now - t < DAY)


def stirred_due(o: Objective, pm: ProjectsParams) -> int | None:
    """Quand ce qui l'a déclenché rend un objectif dû (ADR 0265) : quand le travail s'est posé — ``stir_settle_us``
    après sa dernière cause —, et une heure au plus après la première (``STIR_MAX_WAIT``) : des causes qui
    continuent d'arriver ne le repoussent pas sans fin. ``None`` : rien ne l'a déclenché."""
    if not o.stirred:
        return None
    first = o.stirred_at or o.stirred[0].at
    return min(o.stirred[-1].at + pm.stir_settle_us, first + STIR_MAX_WAIT)


def tickets_in_hand(p: Project) -> bool:
    """Un ticket du projet a-t-il la main chez elle sans objectif à lui — non lu, ou en analyse ? Un ticket ouvert
    est toujours sous la main de l'état."""
    return any(x.list_name == c.TICKETS and x.status in (c.STAGE_UNREAD, c.STAGE_ANALYSIS) for x in p.board.items)


def fallback_due(p: Project, o: Objective, pm: ProjectsParams) -> int:
    """La cadence de secours de l'objectif qui attend les tickets (ADR 0272) : tant qu'un ticket du projet a la
    main chez elle (``tickets_in_hand``), il redevient dû une cadence des constants par défaut après son dernier
    départ — quel que soit le verdict de ce passage (« continue », « wait », aucun), qu'il ait eu douze tickets sous
    les yeux sur quinze, ou qu'un ticket lui soit revenu sans cause (son objectif retiré). Une lecture pure de
    l'état : rien ne s'écrit, et il ne repasse plus dès qu'aucun ticket ne l'attend. ``NEVER`` sinon."""
    if triggers.item_key(c.TICKETS) not in o.on or not tickets_in_hand(p):
        return NEVER
    return max(o.at, o.last_run_at, o.passed_at) + pm.constant_cadence_us


def cadence_due(p: Project, o: Objective, pm: ProjectsParams) -> int:
    """Quand sa cadence rend un constant dû : une cadence après son dernier passage — et son premier, une cadence
    après qu'il a pu commencer (l'étape dont il dépend faite, sinon sa naissance) : un bilan de la semaine ne tombe
    pas le jour où l'app vient d'être écrite (ADR 0161). Un constant qui le dit (``at_once``, ADR 0280) fait ce
    premier passage dès qu'il peut commencer : auditer le code chaque semaine commence par un audit, pas par une
    semaine d'attente. Sans cadence (``only_on_event``) : jamais — sauf, pour celui qui attend les tickets, sa
    cadence de secours (``fallback_due``)."""
    began = 0
    if not o.passed_at:
        dep = objective_at(p, o.after) if o.after else None
        began = max(o.at, dep.closed_at if dep is not None else 0)
        if o.at_once:
            return began
    if o.only_on_event:
        return fallback_due(p, o, pm)
    return (o.passed_at or began) + cadence(o, pm)


def due_at(p: Project, o: Objective, pm: ProjectsParams) -> int:
    """Quand un objectif peut être repris : un ponctuel tout de suite ; un constant au plus tôt de sa cadence
    (``cadence_due``) et de ce qui l'a déclenché (``stirred_due``, ADR 0265) — jamais avant la fin de l'attente
    qu'elle a demandée. ``NEVER`` : un constant sans cadence que rien n'a déclenché."""
    if o.kind != c.CONSTANT:
        return o.waiting_until
    stirred = stirred_due(o, pm)
    due = cadence_due(p, o, pm) if stirred is None else min(cadence_due(p, o, pm), stirred)
    return due if due >= NEVER else max(due, o.waiting_until)


def framing(p: Project) -> bool:
    """Il n'a pas encore de plan qui vaille (ADR 0145) : à cadrer, ou un plan proposé qui attend sa réponse."""
    return p.plan_state in (c.TO_FRAME, c.PROPOSED)


def held_back(p: Project, o: Objective) -> bool:
    """Né d'un ticket (ADR 0270), il attend quand son ticket attend le propriétaire : une question posée dans son
    fil, ou un plan à valider de nouveau (pris comme petit, il a dépassé sa borne). L'étape d'un ticket ouvert est
    toujours sous la main de l'état — un ticket rouvert après en être sorti y revient avec son numéro (ADR 0272).

    Et tout objectif attend quand un de ses jalons est un point d'arrêt qu'elle a dit prêt (ADR 0273) : la main est
    au propriétaire, qui le valide ou le refuse."""
    if awaiting(o) is not None:
        return True
    if not o.ticket:
        return False
    return any(x.number == o.ticket and x.status in (c.STAGE_DECISION, c.STAGE_VALIDATION)
               for x in p.board.items if x.list_name == c.TICKETS)


def ready(p: Project, o: Objective) -> bool:
    """Ce dont il dépend dans son plan est fait (ou retiré, ou oublié) : il peut être travaillé (ADR 0145) — et ni
    son ticket, s'il est né d'un ticket (ADR 0270), ni un de ses jalons (ADR 0273) n'attend le propriétaire."""
    dep = objective_at(p, o.after) if o.after else None
    return (dep is None or dep.status in (c.DONE, c.DROPPED)) and not held_back(p, o)


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
    pas de plan qui vaille, ni quand il n'a que des constants sans cadence que rien n'a déclenché."""
    if framing(p):
        return None
    times = [at for o in p.objectives if o.status == c.OPEN and ready(p, o) and (at := due_at(p, o, pm)) < NEVER]
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
