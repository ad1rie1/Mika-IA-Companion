"""Le diagramme des objectifs d'un projet (ADR 0290, 0297), pur : la source que lisent ``GET …/diagramme`` de l'API par
personne et la fiche de la console, qui le dessine côté serveur.

- un épisode du projet se dit par sa sorte (un cadrage, du travail, une relecture) et l'objectif visé ;
- les départs de ses exécutions de travail se rangent par objectif, du plus ancien au plus récent ;
- elle se met à un jalon à la première exécution qui suit le jalon d'avant atteint ; sans exécution depuis, il n'a
  pas commencé — aucune date n'est inventée ;
- ses lignes : ses objectifs et ses missions qui ne sont pas retirés, dans l'ordre du plan, avec leurs jalons vivants
  et leurs dates ; une mission porte ses passages.
"""

from __future__ import annotations

from types import SimpleNamespace

from mika.contracts import projects as c
from mika.faculties.projects import diagram
from mika.faculties.projects.faculty import Milestone, Objective
from tests.unit.test_project_links import _project


def _started(subject: str, at: int) -> SimpleNamespace:
    return SimpleNamespace(at=at, data=SimpleNamespace(subject=subject))


def test_an_episode_says_its_sort_and_the_objective_it_aimed_at():
    p = _project(7)
    assert diagram.episode_sort(p, "frame:7") == (diagram.FRAME, 0)
    assert diagram.episode_sort(p, "review:7:3") == (diagram.REVIEW, 3)
    assert diagram.episode_sort(p, "objective:7:2") == (diagram.RUN, 2)
    # un autre projet, un récit, rien : pas une exécution de celui-ci
    assert diagram.episode_sort(p, "objective:8:2") is None and diagram.episode_sort(p, "plan:7") is None
    assert diagram.episode_sort(p, None) is None


def test_the_starts_of_its_runs_are_kept_by_objective_oldest_first():
    p = _project(7)
    # le journal les rend du plus récent au plus ancien
    journal = [_started("objective:7:2", 40), _started("review:7:2", 35), _started("objective:7:1", 30),
               _started("objective:8:1", 25), _started("objective:7:2", 20), _started("frame:7", 10)]
    assert diagram.starts_of(p, journal) == {2: [20, 40], 1: [30]}


def test_she_starts_a_milestone_at_the_first_run_after_the_one_before_is_reached():
    marks = (Milestone(1, "j1", status=c.REACHED, reached_at=25), Milestone(2, "j2", status=c.REACHED, reached_at=45),
             Milestone(3, "j3"), Milestone(4, "j4"), Milestone(5, "j5", status=c.DROPPED))
    o = Objective(1, "o1", milestones=marks)
    got = diagram.spans(o, [10, 20, 30, 40, 50, 60])
    assert got[1] == (10, 2)  # deux exécutions avant qu'il soit atteint
    assert got[2] == (30, 2)  # la première après le jalon d'avant
    assert got[3] == (50, 2)  # commencé, pas atteint : toutes celles qui suivent
    assert 4 not in got and 5 not in got  # les suivants attendent celui-là ; un retiré ne compte pas
    # sans exécution depuis le jalon d'avant, il n'a pas commencé : aucune date
    assert diagram.spans(o, [10, 20, 30, 40])[3] == (0, 0)
    # atteint dans la même exécution que le précédent : il part de celle-là
    same = Objective(1, "o1", milestones=(Milestone(1, "j1", status=c.REACHED, reached_at=15),
                                          Milestone(2, "j2", status=c.REACHED, reached_at=15)))
    assert diagram.spans(same, [10])[2] == (10, 1)


def test_its_rows_follow_the_plan_with_real_dates_only():
    p = _project(7, objectives=(
        Objective(1, "o1", at=5, status=c.DONE, closed_at=50, last_run_at=45, rank=2,
                  milestones=(Milestone(1, "j1", at=6, status=c.REACHED, reached_at=30),
                              Milestone(2, "j2", at=6, check=c.CHECK_OWNER, ready_at=44))),
        Objective(2, "o2", at=5, rank=1, after=1, ticket=4), Objective(3, "o3", status=c.DROPPED),
        Objective(4, "m", kind=c.CONSTANT, at=7, last_run_at=90)))
    rows = diagram.rows(p, {1: [10, 20, 40], 4: [60, 70, 90]})
    assert [r.id for r in rows] == [2, 1, 4]  # l'ordre du plan ; le retiré n'y est pas
    waiting, done, mission = rows
    assert (waiting.started_at, waiting.runs, waiting.marks, waiting.after, waiting.ticket) == (0, 0, (), 1, 4)
    assert (done.added_at, done.started_at, done.closed_at, done.last_run, done.runs, done.reached) == (5, 10, 50, 45, 3, 1)
    first, second = done.marks
    assert (first.started_at, first.reached_at, first.runs, first.ready) == (10, 30, 2, False)
    assert (second.started_at, second.ready_at, second.runs, second.ready) == (40, 44, 1, True)
    assert second.check == c.CHECK_OWNER and second.text_ref == "j2"
    assert mission.kind == c.CONSTANT and mission.passes == (60, 70, 90) and mission.marks == ()
    assert done.passes == ()  # seule une mission porte ses passages
    # ses passages rendus sont les derniers, au plus
    many = diagram.rows(p, {4: list(range(1, diagram.PASSES_SHOWN + 20))})[-1]
    assert len(many.passes) == diagram.PASSES_SHOWN and many.passes[-1] == diagram.PASSES_SHOWN + 19
