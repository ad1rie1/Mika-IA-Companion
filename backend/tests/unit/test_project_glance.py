"""Ce qu'un projet montre d'un coup d'œil (ADR 0297), pur : la source que lisent l'API par personne et la fiche de la
console.

- l'avancement de ses objectifs ponctuels se lit dans l'ordre du plan, sans les retirés ;
- ses tickets se comptent par étape du parcours en six, selon le flux du projet ;
- un jalon dit où il en est en un mot : atteint, retiré, dit prêt, refusé, commencé, à venir ;
- la cadence d'une mission se dit en jours quand elle tombe juste, en heures sinon ;
- la dernière activité est le plus récent de ce que l'état garde.
"""

from __future__ import annotations

from mika.contracts import projects as c
from mika.faculties.projects import glance, tickets, work
from mika.faculties.projects.faculty import Board, Milestone, Objective
from mika.kernel.clock import DAY, HOUR
from tests.unit.test_project_links import _project, _state


def test_the_progress_of_once_objectives_follows_the_plan():
    p = _project(1, objectives=(
        Objective(1, "o1", status=c.DONE, rank=2), Objective(2, "o2", runs=1, rank=1),
        Objective(3, "o3"), Objective(4, "o4", status=c.BLOCKED), Objective(5, "o5", status=c.DROPPED),
        Objective(6, "m", kind=c.CONSTANT)))
    assert glance.progress(p) == ((2, glance.DOING), (1, glance.DONE), (3, glance.TODO), (4, glance.BLOCKED))


def test_tickets_are_counted_by_step_of_the_journey():
    counts = ((c.TICKETS, c.STAGE_UNREAD, 2), (c.TICKETS, c.STAGE_PROPOSED, 1), (c.TICKETS, c.STAGE_VALIDATION, 1),
              (c.TICKETS, c.STAGE_WORKING, 3), (c.TICKETS, c.STAGE_TREATED, 4), (c.TICKETS, c.STAGE_DISMISSED, 5),
              ("entreprises", c.TODO, 9))
    direct = glance.steps(_project(1, board=Board(counts=counts)))
    assert list(direct) == list(tickets.JOURNEY)  # les six étapes, dans l'ordre, même vides
    assert direct[tickets.STEP_UNREAD] == 3 and direct[tickets.STEP_VALIDATION] == 1
    assert sum(direct.values()) == 11  # ni les écartés, ni une autre liste
    # « validé, en cours » : elle prépare sa pull request si le projet passe par là, sinon il attend d'être traité
    assert direct[tickets.STEP_TREATED] == 7
    by_pulls = glance.steps(_project(1, board=Board(counts=counts), flow=c.FLOW_PR,
                                     remote="https://github.com/exemple/outils.git"))
    assert by_pulls[tickets.STEP_PULL] + by_pulls[tickets.STEP_MERGE] == 3
    assert direct[tickets.STEP_PULL] == direct[tickets.STEP_MERGE] == 0


def test_a_milestone_says_where_it_stands_in_one_word():
    marks = (Milestone(1, "j1", status=c.REACHED), Milestone(2, "j2", status=c.DROPPED),
             Milestone(3, "j3", check=c.CHECK_OWNER, ready_at=5), Milestone(4, "j4", refused_at=3), Milestone(5, "j5"))
    o = Objective(1, "o1", milestones=marks)
    said = [glance.milestone_state(o, m) for m in marks]
    assert said[:2] == [glance.M_REACHED, glance.M_DROPPED] and said[2] == glance.M_READY
    assert said[3] == glance.M_REFUSED and said[4] in (glance.M_TODO, glance.M_STARTED)


def test_a_cadence_reads_in_days_when_it_falls_right_else_in_hours():
    assert glance.cadence_words(Objective(1, "m", kind=c.CONSTANT)) == "à la cadence par défaut"
    assert glance.cadence_words(Objective(1, "m", kind=c.CONSTANT, cadence_us=2 * DAY)) == "tous les 2 jours"
    assert glance.cadence_words(Objective(1, "m", kind=c.CONSTANT, cadence_us=DAY)) == "toutes les 24 h"
    assert glance.cadence_words(Objective(1, "m", kind=c.CONSTANT, cadence_us=36 * HOUR)) == "toutes les 36 h"


def test_the_last_activity_and_the_next_pass_read_the_state():
    p = _project(1, last_run_at=40, plan_at=70, objectives=(Objective(1, "o1", at=10, closed_at=90),))
    assert glance.last_activity(p) == 90
    s = _state(p)
    assert glance.next_state(p, s, work.Coming(at=5, sort=work.COMING_RUN)) == glance.DUE
    assert glance.next_state(p, s, work.Coming()) in (glance.IDLE, glance.ON_ASK)
    paused = _project(2, status=c.PAUSED)
    assert glance.next_state(paused, _state(paused), work.Coming()) == glance.PAUSED
