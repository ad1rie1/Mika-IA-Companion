"""Le parcours d'un ticket en six étapes, son histoire, et les jalons commencés (ADR 0293) : des règles pures.

- chaque étape fine tombe dans l'une des six — non lu, en analyse, validation, pull request, fusion, traité — ; ce qui
  précède est passé, ce qui suit est à venir ;
- un ticket qui ne passe pas par une pull request saute les deux étapes du code : « validé, en cours », il n'attend
  plus que d'être traité ;
- fermé, une étape n'est passée que si un fait le dit ; écarté, il saute aussi « traité » ;
- son histoire se rejoue de ses événements par les règles de l'état, une ligne par changement d'étape ;
- elle s'est mise à un jalon dès qu'une exécution est partie depuis que le jalon d'avant est atteint.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from mika.contracts import projects as c
from mika.faculties.projects import milestones, tickets, tracker
from mika.faculties.projects.faculty import Item, Milestone, Objective
from mika.kernel.events import Content

T = tickets


def _ticket(**facts) -> Item:
    item = Item(list_name=c.TICKETS, key="k", number=1, **facts)
    return replace(item, status=tickets.stage(item))


def _states(item: Item, by_pulls: bool = False) -> dict[str, str]:
    return dict(tickets.journey(item, by_pulls).steps)


def test_every_fine_stage_falls_into_one_of_the_six_steps():
    assert tickets.JOURNEY == ("unread", "analysis", "validation", "pull", "merge", "treated")
    for fine in (*c.STAGES_OPEN, c.STAGE_TREATED):
        for coded in (True, False):
            assert tickets.step_of(fine, coded) in tickets.JOURNEY, fine
    assert tickets.step_of(c.STAGE_DISMISSED, True) == ""  # écarté : il n'est plus sur le parcours
    assert tickets.step_of(c.STAGE_PROPOSED, True) == T.STEP_UNREAD
    assert tickets.step_of(c.STAGE_DECISION, True) == T.STEP_ANALYSIS  # sa question posée : encore en analyse
    assert tickets.step_of(c.STAGE_PR_PENDING, True) == T.STEP_PULL
    assert tickets.step_of(c.STAGE_PR_READY, True) == T.STEP_MERGE


def test_what_comes_before_is_passed_and_what_follows_is_ahead():
    waiting = _ticket(taken_at=5, plan_seq=9)
    assert waiting.status == c.STAGE_VALIDATION
    j = tickets.journey(waiting, by_pulls=True)
    assert j.current == T.STEP_VALIDATION and j.through_pull and not j.ended
    assert dict(j.steps) == {"unread": T.PASSED, "analysis": T.PASSED, "validation": T.CURRENT, "pull": T.AHEAD,
                             "merge": T.AHEAD, "treated": T.AHEAD}
    asked = _ticket(taken_at=5, asked_at=6)
    assert asked.status == c.STAGE_DECISION and tickets.journey(asked).current == T.STEP_ANALYSIS
    proposed = _ticket(proposed=True)
    assert tickets.journey(proposed).current == T.STEP_UNREAD


def test_a_ticket_without_a_pull_request_skips_the_two_steps_of_the_code():
    working = _ticket(taken_at=5, plan_seq=9, validated_at=10, objective=3)
    assert working.status == c.STAGE_WORKING
    direct = tickets.journey(working, by_pulls=False)
    assert not direct.through_pull and direct.current == T.STEP_TREATED  # il n'attend plus que d'être traité
    assert dict(direct.steps) == {"unread": T.PASSED, "analysis": T.PASSED, "validation": T.PASSED,
                                  "pull": T.SKIPPED, "merge": T.SKIPPED, "treated": T.CURRENT}
    by_pull = tickets.journey(working, by_pulls=True)  # sur un projet par pull requests, elle la prépare
    assert by_pull.through_pull and by_pull.current == T.STEP_PULL
    ready = _ticket(taken_at=5, plan_seq=9, validated_at=10, objective=3, pull=c.PULL_READY, pull_number=12)
    assert tickets.journey(ready).current == T.STEP_MERGE  # sa pull request le dit, quel que soit le réglage
    assert _states(ready)["pull"] == T.PASSED


def test_a_closed_ticket_only_passed_the_steps_a_fact_tells():
    answered = _ticket(taken_at=5, closed=c.DONE, closed_at=20)  # une réponse dans son fil, rien à changer
    j = tickets.journey(answered, by_pulls=True)
    assert j.ended == c.STAGE_TREATED and not j.current and not j.through_pull
    assert dict(j.steps) == {"unread": T.PASSED, "analysis": T.PASSED, "validation": T.SKIPPED, "pull": T.SKIPPED,
                             "merge": T.SKIPPED, "treated": T.PASSED}
    merged = _ticket(taken_at=5, plan_seq=9, validated_at=10, objective=3, pull=c.PULL_MERGED, pull_number=12,
                     closed=c.DONE, closed_at=20)
    assert set(_states(merged).values()) == {T.PASSED}
    dismissed = _ticket(closed=c.DROPPED, closed_at=20)
    j = tickets.journey(dismissed, by_pulls=True)
    assert j.ended == c.STAGE_DISMISSED
    assert dict(j.steps) == {"unread": T.PASSED, "analysis": T.SKIPPED, "validation": T.SKIPPED, "pull": T.SKIPPED,
                             "merge": T.SKIPPED, "treated": T.SKIPPED}


def _event(name: str, seq: int, data) -> SimpleNamespace:
    return SimpleNamespace(type=SimpleNamespace(name=name), seq=seq, at=seq * 10, data=data)


def _changed(was: str, **what) -> tracker.ItemChanged:
    return tracker.ItemChanged(project=1, list_name=c.TICKETS, key="k", was=was, **what)


def test_the_history_of_a_ticket_is_replayed_from_its_events():
    added = tracker.ItemAdded(project=1, list_name=c.TICKETS, key="k", title=Content.of("Un titre"),
                              author=c.BY_PERSON, by="lea")
    plan = tracker.ItemNoted(project=1, list_name=c.TICKETS, key="k", text=Content.of("Plan"), kind=c.NOTE_PLAN)
    note = tracker.ItemNoted(project=1, list_name=c.TICKETS, key="k", text=Content.of("Vu"), author=c.BY_PERSON,
                             by="lea")
    events = [
        _event(tracker.ITEM_ADDED.name, 1, added),
        _event(tracker.ITEM_CHANGED.name, 2, _changed(c.STAGE_UNREAD, taken=True)),
        _event(tracker.ITEM_NOTED.name, 3, note),  # une note qui ne change pas d'étape : pas de ligne
        _event(tracker.ITEM_NOTED.name, 4, plan),
        _event(tracker.ITEM_CHANGED.name, 5, _changed(c.STAGE_VALIDATION, validated=True, plan=4, objective=7,
                                                      author=c.BY_OPERATOR, by="adrien")),
        _event(tracker.ITEM_CHANGED.name, 6, _changed(c.STAGE_UNREAD, closed=c.DONE)),  # périmé (``was``) : rien
        _event(tracker.ITEM_CHANGED.name, 7, _changed(c.STAGE_WORKING, closed=c.DONE)),
    ]
    found = tracker.passages(events)
    assert [(x.was, x.stage, x.at, x.seq) for x in found] == [
        ("", c.STAGE_UNREAD, 10, 1), (c.STAGE_UNREAD, c.STAGE_ANALYSIS, 20, 2),
        (c.STAGE_ANALYSIS, c.STAGE_VALIDATION, 40, 4), (c.STAGE_VALIDATION, c.STAGE_WORKING, 50, 5),
        (c.STAGE_WORKING, c.STAGE_TREATED, 70, 7)]
    assert [(x.author, x.by) for x in found] == [
        (c.BY_PERSON, "lea"), (c.BY_SELF, ""), (c.BY_SELF, ""), (c.BY_OPERATOR, "adrien"), (c.BY_SELF, "")]
    assert tracker.passages(events[1:]) == ()  # sans son ajout, rien ne se rejoue
    assert tracker.passages([]) == ()


def _objective(last_run: int, *marks: Milestone) -> Objective:
    return Objective(id=1, text_ref="t", last_run_at=last_run, milestones=marks)


def test_she_has_begun_a_milestone_once_a_run_started_after_the_one_before():
    first, second, third = (Milestone(id=n, text_ref=f"m{n}") for n in (1, 2, 3))
    assert milestones.begun(_objective(0, first, second)) == frozenset()  # aucune exécution : rien n'a commencé
    assert milestones.begun(_objective(50, first, second)) == {1}  # le premier ouvert ; le suivant l'attend
    reached = replace(first, status=c.REACHED, reached_at=60)
    assert milestones.begun(_objective(50, reached, second, third)) == {1}  # aucune exécution depuis qu'il est atteint
    assert milestones.begun(_objective(70, reached, second, third)) == {1, 2}
    dropped = replace(second, status=c.DROPPED)
    assert milestones.begun(_objective(70, reached, dropped, third)) == {1, 3}  # un jalon retiré ne compte pas
    assert milestones.begun(None) == frozenset()
