"""« À qui la main » (ADR 0281) : ce qui, dans ses projets, attend une personne.

- chaque sorte d'attente se lit dans l'état seul : un accord, un plan sans réponse, une demande d'aide, un projet
  arrêté par ses pannes, un objectif bloqué, les tickets dont la main est au propriétaire, un point d'arrêt dit prêt,
  des relectures refusées deux fois, les éléments d'une liste à la charge de quelqu'un ;
- elles viennent dans l'ordre où s'en occuper, la plus ancienne d'abord dans un même rang, tous projets confondus ;
- chacune dit le geste qui la règle ;
- par personne : son projet en entier, celui d'un autre selon ses lignes d'accès ; une attente est comptée pour qui
  peut la régler — un accord pour qui s'occupe d'elle, jamais pour le propriétaire d'un projet confié.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from mika.contracts import projects as c
from mika.faculties.projects import inspect, inspect_todo, todo
from mika.faculties.projects.faculty import PUSH_CAPABILITY, Board, Item, Listing, Milestone, Objective
from mika.vocab.access import OWNER, PERSON
from mika.vocab.episodes import project_target
from tests.unit.test_project_links import WORLD, _line, _project, _state

T = c.TICKETS


def pending(project: int, seq: int, at: int, capability: str = PUSH_CAPABILITY, owner: str = "projects"):
    """Un effet proposé qui attend un accord, tel que le runtime le donne."""
    return SimpleNamespace(proposal=seq, capability=capability, owner=owner, context=project_target(project),
                           summary_ref=f"s{seq}", at=at)


def ticket(number: int, stage: str, **facts) -> Item:
    return Item(list_name=T, key=f"t-{number}", number=number, title_ref=f"ticket{number}", status=stage,
                at=number, updated_at=100 + number, **facts)


def kinds(found) -> list[str]:
    return [w.kind for w in found]


def test_a_project_that_runs_alone_awaits_nobody():
    p = _project(1, objectives=(Objective(id=1, text_ref="o1"), Objective(id=2, text_ref="o2", kind=c.CONSTANT)),
                 board=Board(lists=(Listing("articles"),),
                             items=(ticket(1, c.STAGE_UNREAD), ticket(2, c.STAGE_WORKING, objective=1, validated_at=5),
                                    Item(list_name="articles", key="a", status=c.TODO))))
    assert todo.of_project(p) == ()
    assert todo.everywhere(_state(p)) == ()


def test_every_kind_of_wait_is_read_from_the_state_in_the_order_to_handle_them():
    objectives = (
        Objective(id=1, text_ref="o1", need_ref="need1", asked_at=30, asked_to="adrien"),
        Objective(id=2, text_ref="o2", status=c.BLOCKED, note_ref="why2", last_run_at=35),
        Objective(id=3, text_ref="o3", milestones=(
            Milestone(id=1, text_ref="m1", status=c.REACHED, check=c.CHECK_OWNER, ready_at=5),
            Milestone(id=2, text_ref="m2", check=c.CHECK_OWNER, ready_at=60),
            Milestone(id=3, text_ref="m3", check=c.CHECK_OWNER))),
        Objective(id=4, text_ref="o4", review_refused=("r1", "r2"), review_at=70),
        Objective(id=7, text_ref="o7", status=c.BLOCKED, ticket=6, last_run_at=36),  # celui du ticket n° 6
    )
    items = (
        ticket(1, c.STAGE_PROPOSED, proposed=True),
        ticket(2, c.STAGE_DECISION, asked_at=20),
        ticket(3, c.STAGE_DECISION, dismissal_at=21),
        ticket(4, c.STAGE_VALIDATION, plan_seq=44),
        ticket(5, c.STAGE_PR_READY, objective=3, validated_at=9, pull=c.PULL_READY),
        ticket(6, c.STAGE_WORKING, objective=7, validated_at=9, stuck=True),
        ticket(8, c.STAGE_ANALYSIS, taken_at=3),  # la main est à elle
        ticket(9, c.STAGE_TREATED, closed=c.DONE),
        Item(list_name="entreprises", key="acme", title_ref="acme", status=c.TODO, actor=c.ACTOR_OWNER, updated_at=80),
        Item(list_name="entreprises", key="bolt", title_ref="bolt", status=c.TODO, actor=c.ACTOR_PERSON, person="bea",
             updated_at=81),
        Item(list_name="entreprises", key="cité", status="contacté", actor=c.ACTOR_OWNER, updated_at=82),  # clos
        Item(list_name="entreprises", key="dune", status=c.TODO, actor=c.ACTOR_SELF, updated_at=83),  # à elle
    )
    p = _project(1, objectives=objectives, plan_state=c.PROPOSED, plan_ref="plan", plan_at=40, asked_by="adrien",
                 board=Board(lists=(Listing("entreprises", open=(c.TODO,), closed=("contacté",),
                                            actor=c.ACTOR_OWNER),), items=items))
    held = (pending(1, 900, at=50), pending(1, 901, at=45, capability="mcp.call", owner="mcp"),
            pending(2, 902, at=1))  # celui d'un autre projet
    found = todo.of_project(p, held)
    assert kinds(found) == [todo.APPROVAL, todo.APPROVAL, todo.PLAN, todo.NEED, todo.BLOCKED, *[todo.TICKET] * 6,
                            todo.CHECKPOINT, todo.REVIEW, todo.ITEM, todo.ITEM]
    by = {(w.kind, w.number or w.objective, w.key): w for w in found}
    # un accord : tout effet dont le contexte est le projet, l'appel d'un service compris ; il se décide dans la file
    assert [w.number for w in found[:2]] == [901, 900]  # le plus ancien d'abord
    assert found[0].what == "mcp.call" and found[0].gesture == todo.Gesture(where=todo.QUEUE,
                                                                             params=(("demande", "901"),))
    assert found[1].ref == "s900"
    # le plan attend qui l'a demandé ; le besoin, qui elle l'a dit
    assert found[2].person == "adrien" and found[2].gesture.action == "projects.plan_valider"
    assert found[3].ref == "need1" and found[3].since == 30 and found[3].person == "adrien"
    # un objectif bloqué se rouvre ; celui d'un ticket qui bloque ne se dit qu'une fois, par son ticket
    assert found[4].objective == 2 and found[4].gesture.args == (("objective", "2"), ("status", c.OPEN))
    assert [w.objective for w in found if w.kind == todo.BLOCKED] == [2]
    tickets_ = {w.number: w for w in found if w.kind == todo.TICKET}
    assert {n: w.what for n, w in tickets_.items()} == {
        1: todo.ACCEPT, 2: todo.QUESTION, 3: todo.DISMISSAL, 4: todo.VALIDATION, 5: todo.MERGE, 6: todo.STUCK}
    assert tickets_[1].gesture.args == (("item", "#1"), ("verdict", "accept"), ("plan", "0"))
    assert tickets_[2].gesture.action == "projects.element_noter" and tickets_[2].since == 20
    assert tickets_[3].gesture.args[1] == ("verdict", "dismiss")
    assert tickets_[4].gesture.args == (("item", "#4"), ("verdict", "validate"), ("plan", "44"))
    assert tickets_[4].gesture.params == (("element", "#4"),) and tickets_[4].gesture.tab == "tickets"
    assert tickets_[5].gesture.where == todo.HOST and not tickets_[5].gesture.action
    assert tickets_[6].gesture.action == "projects.objectif_statut" and tickets_[6].objective == 7
    # le point d'arrêt dit prêt (pas celui qui est atteint, ni celui qu'elle n'a pas dit prêt)
    stop = by[(todo.CHECKPOINT, 2, "")]
    assert stop.objective == 3 and stop.since == 60 and stop.ref == "m2"
    assert stop.gesture.args == (("objective", "3"), ("milestone", "2"))
    assert by[(todo.REVIEW, 4, "")].ref == "r2" and by[(todo.REVIEW, 4, "")].since == 70
    # les éléments ouverts à la charge d'une personne : le propriétaire, ou quelqu'un de nommé
    listed = [w for w in found if w.kind == todo.ITEM]
    assert [(w.key, w.person, w.what) for w in listed] == [("acme", "", "entreprises"), ("bolt", "bea", "entreprises")]
    assert listed[0].gesture.params == (("liste", "entreprises"), ("element", "acme"))
    assert todo.counts(found) == {1: len(found)}


def test_a_project_stopped_by_its_failures_awaits_and_an_archived_one_does_not():
    broken = _project(1, status=c.PAUSED, paused_at=10, stalled_at=10, plan_state=c.PROPOSED)
    found = todo.of_project(broken)
    assert kinds(found) == [todo.STALLED] and found[0].gesture.action == "projects.reprendre"  # son plan : en pause
    paused = _project(2, status=c.PAUSED, paused_at=10)  # une pause qu'on a posée soi-même n'attend personne
    assert todo.of_project(paused) == ()
    archived = _project(3, status=c.ARCHIVED, stalled_at=5, objectives=(Objective(id=1, text_ref="o", need_ref="n"),))
    assert todo.of_project(archived, (pending(3, 1, at=1),)) == ()


def test_across_projects_the_rank_comes_first_then_the_oldest():
    one = _project(1, objectives=(Objective(id=1, text_ref="o", need_ref="n", asked_at=5),))
    two = _project(2, plan_state=c.PROPOSED, plan_at=90,
                   objectives=(Objective(id=1, text_ref="o", need_ref="n", asked_at=3),))
    found = todo.everywhere(_state(one, two), (pending(1, 7, at=99),))
    assert [(w.project, w.kind) for w in found] == [(1, todo.APPROVAL), (2, todo.PLAN), (2, todo.NEED), (1, todo.NEED)]
    assert todo.counts(found) == {1: 2, 2: 2}


def test_a_person_sees_what_her_rights_give_and_settles_what_is_hers():
    items = (ticket(1, c.STAGE_PROPOSED, proposed=True),
             Item(list_name="entreprises", key="bolt", status=c.TODO, actor=c.ACTOR_PERSON, person="bea", updated_at=5),
             Item(list_name="entreprises", key="acme", status=c.TODO, actor=c.ACTOR_OWNER, updated_at=6))
    board = Board(lists=(Listing("entreprises"),), items=items)
    mine = _project(1, owner="adrien", board=board)
    s = _state(mine)
    found = todo.everywhere(s, (pending(1, 9, at=1),))
    assert kinds(found) == [todo.APPROVAL, todo.TICKET, todo.ITEM, todo.ITEM]

    # son propriétaire : tout, il tranche ; ce qui est à la charge d'une autre ne l'attend pas, lui
    seen = todo.for_person(s, WORLD, "adrien", found)
    assert [(x.entry.kind, x.mine, x.steer) for x in seen] == [
        (todo.APPROVAL, True, c.STEER_EDIT), (todo.TICKET, True, c.STEER_EDIT), (todo.ITEM, False, c.STEER_EDIT),
        (todo.ITEM, True, c.STEER_EDIT)]
    # une autre personne, sans ligne qui la désigne : rien, pas même ce qui est à sa charge
    assert todo.for_person(s, WORLD, "bea", found) == ()
    assert todo.for_person(s, WORLD, "", found) == ()

    # une ligne qui la laisse voir : ce qui est à sa charge l'attend, le reste lui est caché sans le détail
    seeing = replace(mine, access=(_line(PERSON + "bea", see=True),))
    seen = todo.for_person(_state(seeing), WORLD, "bea", found)
    assert [(x.entry.key, x.mine, x.steer) for x in seen] == [("bolt", True, c.STEER_READ)]
    # le détail (le piloter en lecture seule) : elle lit tout ; sur accord, elle demande ; un accord n'est pas à elle
    for level in (c.STEER_READ, c.STEER_ASK, c.STEER_EDIT):
        shared = replace(mine, access=(_line(PERSON + "bea", see=True, steer=level),))
        seen = todo.for_person(_state(shared), WORLD, "bea", found)
        assert [(x.entry.kind, x.mine, x.steer) for x in seen] == [
            (todo.APPROVAL, False, c.STEER_READ), (todo.TICKET, False, level), (todo.ITEM, True, level),
            (todo.ITEM, False, level)]

    # un projet à elle : quelqu'un qui s'occupe d'elle en est le propriétaire
    hers = _project(2, owner=None, board=board)
    found = todo.everywhere(_state(hers))
    assert all(x.mine for x in todo.for_person(_state(hers), WORLD, "adrien", found) if x.entry.person != "bea")
    assert todo.for_person(_state(hers), WORLD, "bea", found) == ()
    assert todo.owns(hers, "adrien", WORLD) and not todo.owns(hers, "bea", WORLD) and not todo.owns(mine, "", WORLD)


def test_an_accord_awaits_whoever_looks_after_her_even_in_a_project_entrusted_to_someone_else():
    """Une attente est comptée pour qui peut la régler : « ton accord », dans une ligne d'accès, est celui de qui
    s'occupe d'elle (ADR 0133) — pas celui de la personne à qui le projet est confié. La console (``awaits``), l'API
    par personne et ses clients (``for_person``) le lisent ici."""
    confided = _project(1, owner="bea", stalled_at=4, status=c.PAUSED)  # confié à Bea, qui ne s'occupe pas d'elle
    s = _state(confided)
    found = todo.everywhere(s, (pending(1, 9, at=1),))
    assert kinds(found) == [todo.APPROVAL, todo.STALLED]
    accord, stalled = found
    assert todo.awaits(confided, accord) == "" and todo.awaits(confided, stalled) == "bea"
    # sa propriétaire voit l'accord attendre, sans qu'il l'attende, elle : elle ne fait que le lire ; la reprise, si
    assert [(x.entry.kind, x.mine, x.steer) for x in todo.for_person(s, WORLD, "bea", found)] == [
        (todo.APPROVAL, False, c.STEER_READ), (todo.STALLED, True, c.STEER_EDIT)]
    # qui s'occupe d'elle : c'est lui que l'accord attend, dès que les lignes du projet lui en donnent le détail ;
    # la reprise reste à sa propriétaire
    assert [(x.entry.kind, x.mine, x.steer) for x in todo.for_person(s, WORLD, "adrien", found)] == [
        (todo.APPROVAL, True, c.STEER_EDIT), (todo.STALLED, False, c.STEER_READ)]
    # sans le détail (une ligne qui ne le laisse que voir), l'accord ne lui est pas montré d'ici
    seen_only = replace(confided, access=(_line(OWNER, see=True),))
    assert todo.for_person(_state(seen_only), WORLD, "adrien", found) == ()
    # une autre personne à qui le projet est ouvert en modification : ni l'accord ni la reprise ne sont à elle
    shared = replace(confided, access=(_line(PERSON + "carl", see=True, steer=c.STEER_EDIT),))
    assert [(x.entry.kind, x.mine, x.steer) for x in todo.for_person(_state(shared), WORLD, "carl", found)] == [
        (todo.APPROVAL, False, c.STEER_READ), (todo.STALLED, False, c.STEER_READ)]
    # un projet à elle : qui s'occupe d'elle en est le propriétaire, tout l'attend
    hers = _project(2, owner=None)
    found = todo.everywhere(_state(hers), (pending(2, 9, at=1),))
    assert todo.awaits(hers, found[0]) == ""
    assert [(x.mine, x.steer) for x in todo.for_person(_state(hers), WORLD, "adrien", found)] == [(True, c.STEER_EDIT)]
    # la console dit « toi » pour l'accord d'un projet confié, et sa propriétaire pour le reste
    who = SimpleNamespace(get=lambda key: None)
    said = [inspect.awaited(who, confided, w) for w in (accord, stalled)]
    assert said[0] == "toi" and said[1] != "toi"


def test_the_console_says_each_wait_in_a_line_and_folds_a_long_list():
    items = tuple(Item(list_name="entreprises", key=f"e{n}", title_ref=f"e{n}", status=c.TODO, actor=c.ACTOR_OWNER,
                       updated_at=n) for n in range(1, 7))
    p = _project(1, plan_state=c.PROPOSED, plan_at=2, board=Board(
        lists=(Listing("entreprises"),), items=(ticket(1, c.STAGE_VALIDATION, plan_seq=3), *items)))
    s = _state(p)
    found = todo.everywhere(s, (pending(1, 9, at=1),))
    texts = {"s9": "Pousser main vers GitHub", "ticket1": "Le pied de page", **{f"e{n}": f"Entreprise {n}" for n in range(1, 7)}}
    assert set(inspect_todo.refs(found)) >= {"s9", "ticket1", "e1"}
    table = inspect_todo.table(s, found, texts, lambda q, w: "toi")
    said = [row.cells[1].text for row in table.rows]
    assert said[0].startswith("Pousser vers le dépôt distant — Pousser main vers GitHub")
    assert "Son plan attend une réponse" in said[1]
    assert said[2] == "#1 Le pied de page — son plan attend ta validation"
    # trois éléments d'une liste, puis une ligne pour les autres, qui mène à la liste
    assert said[3:6] == [f"Entreprise {n} (liste « entreprises »)" for n in (1, 2, 3)]
    assert "3 autres éléments" in said[6] and len(table.rows) == 7
    assert table.rows[6].cells[4].params == (("onglet", "suivi"), ("liste", "entreprises"))
    assert table.title == "Ce qui t'attend (9)"  # neuf attentes, en sept lignes
    # chaque ligne mène là où elle se règle : la file ouverte sur la demande, l'onglet ouvert sur le ticket
    assert table.rows[0].cells[4].kind == "approvals" or dict(table.rows[0].cells[4].params).get("demande") == "9"
    assert table.rows[2].cells[4].params == (("onglet", "tickets"), ("element", "#1"))
    assert table.rows[2].cells[4].text == "Valider ou refuser son plan"
    # un texte oublié se dit, sans casser la ligne
    gone = inspect_todo.table(s, found, {}, lambda q, w: "toi")
    assert "(oublié)" in gone.rows[2].cells[1].text
    assert inspect_todo.table(s, (), {}, lambda q, w: "toi").empty == inspect_todo.EMPTY
