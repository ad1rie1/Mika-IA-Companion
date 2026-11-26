"""Ce qu'un projet montre d'un coup d'œil (ADR 0297), pur : de quoi dessiner sa carte et sa vue d'ensemble sans rien
recalculer ailleurs. Deux lecteurs s'en servent — l'API par personne (``app/domains/projects/api/projects.py``), qui y ajoute ce que
chacun a le droit d'en lire, et la fiche de la console (``app/domains/projects/console/subject.py``), qui voit tout.

- ``progress`` : où en sont ses objectifs ponctuels, dans l'ordre du plan ;
- ``steps`` : ses tickets comptés par étape du parcours en six ;
- ``milestone_state`` : où en est un jalon, en un mot ;
- ``last_activity`` : la dernière fois que quelque chose y a bougé ;
- ``cadence_words`` : la cadence d'une mission, en mots ;
- ``next_state`` : où en est son prochain passage ;
- ``of`` : le tout, pour la vue d'ensemble de la console.

Rien n'est estimé ni inventé : ce sont des lectures de sa tranche. Les textes restent des références (l'oubli les
atteint) : qui dessine les relit dans le magasin de contenus.
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.contracts import projects as c
from mika.faculties.projects import milestones, pulls, tickets, tracker, work
from mika.faculties.projects.faculty import (
    ON_DEMAND,
    PULL_OPEN,
    Milestone,
    Objective,
    Project,
    ProjectsState,
    awaiting,
    busy,
    by_pulls,
    milestones_of,
    readers_of,
)
from mika.faculties.projects.rhythm import schedule_words
from mika.faculties.projects.triggers import trigger_words
from mika.kernel.clock import DAY, HOUR
from mika.kernel.frame import Frame

#: où en est un objectif ponctuel sur la carte de son projet
DONE, DOING, TODO, BLOCKED = "done", "doing", "todo", "blocked"
#: où en est un jalon : atteint, retiré, dit prêt (il attend qu'on le tranche), refusé, commencé, à venir
M_REACHED, M_DROPPED, M_READY, M_REFUSED, M_STARTED, M_TODO = "reached", "dropped", "ready", "refused", "started", "todo"
#: où en est son prochain passage : en cours, daté, en pause, sur demande, rien en vue
RUNNING, DUE, PAUSED, ON_ASK, IDLE = "running", "due", "paused", "on_demand", "idle"


def progress(p: Project) -> tuple[tuple[int, str], ...]:
    """Où en sont ses objectifs ponctuels, dans l'ordre du plan : (son numéro, ``DONE``, ``DOING`` — au moins une
    exécution —, ``TODO`` ou ``BLOCKED``). Les retirés n'y sont pas."""
    once = sorted((o for o in p.objectives if o.kind == c.ONCE and o.status != c.DROPPED),
                  key=lambda o: (o.rank or 10_000, o.id))
    return tuple((o.id, DONE if o.status == c.DONE else BLOCKED if o.status == c.BLOCKED else
                  DOING if o.worked or o.runs else TODO) for o in once)


def steps(p: Project) -> dict[str, int]:
    """Ses tickets comptés par étape du parcours en six (``tickets.JOURNEY``), d'après ses comptes par étape fine :
    un ticket « validé, en cours » se range selon le flux du projet ; les écartés ne sont plus sur le parcours."""
    counts = dict.fromkeys(tickets.JOURNEY, 0)
    for name, fine, n in p.board.counts:
        step = tickets.step_of(fine, by_pulls(p)) if name == c.TICKETS else ""
        if step:
            counts[step] += n
    return counts


def milestone_state(o: Objective, m: Milestone) -> str:
    """Où en est un jalon, en un mot : atteint, retiré, dit prêt (``awaiting`` : un point d'arrêt qui attend qu'on le
    tranche), refusé, commencé (``milestones.begun`` : elle s'y est mise), sinon à venir."""
    if m.status == c.REACHED:
        return M_REACHED
    if m.status == c.DROPPED:
        return M_DROPPED
    waits = awaiting(o)
    if waits is not None and waits.id == m.id:
        return M_READY
    if m.refused_at:
        return M_REFUSED
    return M_STARTED if m.id in milestones.begun(o) else M_TODO


def last_activity(p: Project) -> int:
    """La dernière fois que quelque chose a bougé dans ce projet, d'après ce que l'état en garde : une exécution,
    son plan, un élément de son registre, un objectif, sa pull request, sa relecture."""
    return max(p.created_at, p.last_run_at, p.plan_at, p.paused_at, *(i.updated_at for i in p.board.items),
               *(at for o in p.objectives for at in (o.at, o.closed_at, o.pull_at, o.review_at, o.checks_at)))


def cadence_words(o: Objective) -> str:
    """La cadence d'une mission, en mots : en jours quand elle tombe juste, en heures sinon."""
    if not o.cadence_us:
        return "à la cadence par défaut"
    return f"tous les {o.cadence_us // DAY} jours" if o.cadence_us >= 2 * DAY and o.cadence_us % DAY == 0 else \
        f"toutes les {max(1, round(o.cadence_us / HOUR))} h"


def next_state(p: Project, s: ProjectsState, coming: work.Coming) -> str:
    """Où en est son prochain passage : une exécution est en cours, il est daté, le projet est en pause ou archivé,
    il n'avance que sur demande, ou rien n'est en vue."""
    return RUNNING if busy(s, p.id) else DUE if coming.at else PAUSED if p.status != c.ACTIVE else \
        ON_ASK if p.schedule == ON_DEMAND else IDLE


@dataclass(frozen=True, slots=True)
class Pull:
    """La pull request ouverte d'un objectif : son numéro, son titre, son adresse chez l'hôte, depuis quand, où en
    sont ses vérifications (``ports.workshop.CHECKS_…`` ; vide : aucune vue) et sa relecture (``None`` : pas relue)."""

    objective: int
    number: int
    title: str
    url: str
    at: int
    checks: str
    reviewed: bool | None
    conflicts: bool


@dataclass(frozen=True, slots=True)
class Goal:
    """Un objectif ponctuel sur la vue d'ensemble : son texte (une référence), son statut, ses jalons vivants un à un
    (``milestone_state``), et combien sont atteints."""

    id: int
    text_ref: str
    status: str
    marks: tuple[str, ...]
    reached: int


@dataclass(frozen=True, slots=True)
class Mission:
    """Une mission (un objectif constant) : sa cadence et ce qui la déclenche, en mots."""

    id: int
    text_ref: str
    status: str
    cadence: str
    on: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Glance:
    """Un projet d'un coup d'œil : ses objectifs ponctuels (ceux en cours d'abord, puis les faits) et combien sont
    faits, ses missions, ses pull requests ouvertes, ses tickets par étape et combien restent ouverts, ce qu'il lit
    et qui le lit (leurs numéros), son prochain passage (``work.Coming``) et où il en est, son rythme en mots, la
    dernière fois que quelque chose a bougé."""

    goals: tuple[Goal, ...]
    done: int
    total: int
    missions: tuple[Mission, ...]
    pulls: tuple[Pull, ...]
    steps: tuple[tuple[str, int], ...]
    tickets_open: int
    reads: tuple[int, ...]
    readers: tuple[int, ...]
    coming: work.Coming
    next: str
    schedule: str
    last_activity: int


def _goal(o: Objective) -> Goal:
    alive = [m for m in milestones_of(o) if m.status != c.DROPPED]
    marks = tuple(milestone_state(o, m) for m in alive)
    return Goal(o.id, o.text_ref, o.status, marks, sum(1 for x in marks if x == M_REACHED))


def _pull(p: Project, o: Objective) -> Pull:
    return Pull(o.id, o.pull, pulls.title_of(o), pulls.pull_url(p, o), o.pull_at, o.checks if o.checks_sha else "",
                o.review_ok if o.review_at else None, bool(o.pull_conflicts))


def of(p: Project, s: ProjectsState, frame: Frame) -> Glance:
    """Tout ce que la vue d'ensemble d'un projet dessine, lu une fois dans sa tranche."""
    once = [o for o in p.objectives if o.kind == c.ONCE and o.status != c.DROPPED]
    shown = sorted(once, key=lambda o: (o.status == c.DONE, o.rank or 10_000, o.id))
    coming = work.coming(p, s, frame)
    return Glance(
        goals=tuple(_goal(o) for o in shown), done=sum(1 for o in once if o.status == c.DONE), total=len(once),
        missions=tuple(Mission(o.id, o.text_ref, o.status,
                               "sur événement seulement" if o.only_on_event else cadence_words(o),
                               tuple(trigger_words(k) for k in o.on))
                       for o in p.objectives if o.kind == c.CONSTANT and o.status != c.DROPPED),
        pulls=tuple(_pull(p, o) for o in p.objectives if o.pull_state == PULL_OPEN) if by_pulls(p) else (),
        steps=tuple(steps(p).items()), tickets_open=tracker.open_tickets(p.board),
        reads=tuple(p.reads), readers=tuple(r.id for r in readers_of(s, p.id)),
        coming=coming, next=next_state(p, s, coming), schedule=schedule_words(p.schedule),
        last_activity=last_activity(p))
