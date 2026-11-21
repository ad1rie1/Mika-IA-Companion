"""Ce qu'elle ne défait pas en exécution, et un blocage qui ne se contourne pas (ADR 0278).

- en exécution, elle ne retire ni ne change la vérification d'un point d'arrêt, d'un jalon qu'un autre a posé, ni
  d'un jalon que le propriétaire a refusé ; elle n'en réécrit le texte que s'il est d'elle ;
- les jalons d'un plan qu'une personne a validé — le plan d'un ticket, le plan du projet — sont à cette personne :
  elle peut seulement leur donner une vérification là où ils n'avaient que sa parole ;
- ce qui est à elle seule reste libre, et ce que font le propriétaire et l'opérateur n'est pas jugé ;
- sur un vrai noyau : l'outil refuse en disant pourquoi et de le demander, rien ne s'écrit, et « fait » attend
  toujours le jalon qu'elle n'a pas pu défaire ;
- retirer ses jalons puis en poser d'autres ne remet pas à zéro le compte du blocage, et douze exécutions restent
  le filet d'un objectif qui a des jalons.
"""

from __future__ import annotations

from dataclasses import replace

from mika.contracts import projects as c
from mika.faculties.projects import faculty, milestones
from mika.faculties.projects.faculty import (
    HELD_AGREED,
    HELD_BREAKPOINT,
    HELD_OTHER,
    HELD_REFUSED,
    MILESTONE_CHANGED,
    PLAN_ANSWERED,
    PLAN_PROPOSED,
    Milestone,
    Objective,
    awaiting,
    milestone_at,
    milestone_guard,
    milestone_held,
    milestones_of,
    open_milestones,
)
from mika.faculties.projects.tracker import AddArgs, ItemArg, items_add
from mika.faculties.projects.triage import StepArgs, ticket_step
from mika.kernel.events import Content
from mika.runtime.operations import perform
from tests.unit.test_project_links import PM, _cx, _ev, _project, _state
from tests.unit.test_project_milestones import (
    TICKET_PLAN,
    Checked,
    _begin,
    _ctx,
    _end,
    _o,
    _pose,
    _pose_tool,
    _project_of,
    _reach,
    _report,
    _run,
    _step,
    _stuck,
    _target,
    _texts_of,
    _with,
)
from tests.unit.test_projects import create, live, row_form, wait

# ── La règle, pure ─────────────────────────────────────────────────────────


def _asks(**fields) -> object:
    """Ce qu'elle demande à un jalon, en exécution (la charge utile que juge ``milestone_guard``)."""
    return MILESTONE_CHANGED.payload(project=1, objective=1, milestone=1, **fields)


DROP = {"status": c.DROPPED, "reason": True}
TO_PROSE = {"check": c.CHECK_PROSE, "reason": True}


def test_in_a_run_she_neither_drops_nor_weakens_a_breakpoint_anothers_milestone_or_a_refused_one():
    s = _with(Objective(1, "o1", runs=1))
    s = _pose(s, 1, check=c.CHECK_OWNER, author="operator")  # un point d'arrêt posé dans la console
    s = _pose(s, 2, check=c.CHECK_COMMAND, command=Content(ref="cmd"), author="operator")  # sa commande aussi
    s = _pose(s, 3, check=c.CHECK_OWNER)  # un point d'arrêt qu'elle a posé elle-même
    s = _pose(s, 4)  # un jalon à elle, en prose
    # ni retiré, ni révisé en « prose » — le chemin qui laissait passer « fait » —, ni sa commande remplacée
    for number in (1, 2, 3):
        assert _step(s, number, 10, **DROP) is s
        assert _step(s, number, 10, **TO_PROSE) is s
    assert _step(s, 2, 10, command=Content(ref="true"), reason=True) is s
    assert _step(s, 2, 10, check=c.CHECK_ITEM, item_list="tickets", item_key="#1", item_status="traité") is s
    # le texte d'un autre ne se réécrit pas ; celui de son propre point d'arrêt, si — sa vérification reste
    assert _step(s, 1, 10, text=True, reason=True) is s and _step(s, 2, 10, text=True) is s
    reworded = milestone_at(_o(_step(s, 3, 10, text=True)), 3)
    assert (reworded.text_ref, reworded.check, reworded.revised) == ("text@10", c.CHECK_OWNER, 1)
    # ce qui est à elle seule reste libre : révisé, vérifié autrement, retiré
    free = _step(s, 4, 10, text=True, check=c.CHECK_COMMAND, command=Content(ref="c4"))
    assert (milestone_at(_o(free), 4).check, milestone_at(_o(free), 4).command_ref) == (c.CHECK_COMMAND, "c4")
    assert milestone_at(_o(_step(free, 4, 11, command=Content(ref="c5"))), 4).command_ref == "c5"
    assert milestone_at(_o(_step(s, 4, 10, **DROP)), 4).status == c.DROPPED
    # pourquoi, en un code que l'outil dit en mots
    one, two, three, four = (milestone_at(_o(s), n) for n in (1, 2, 3, 4))
    assert [milestone_held(m) for m in (one, two, three, four)] == [HELD_BREAKPOINT, HELD_OTHER, HELD_BREAKPOINT, ""]
    assert milestone_guard(one, _asks(status=c.DROPPED)) == HELD_BREAKPOINT
    assert milestone_guard(two, _asks(command=Content(ref="true"))) == HELD_OTHER
    assert milestone_guard(two, _asks(text=Content(ref="t"))) == HELD_OTHER
    assert milestone_guard(three, _asks(text=Content(ref="t"))) == "" == milestone_guard(four, _asks(**{
        "status": c.DROPPED}))
    # dire un jalon atteint, ou un point d'arrêt prêt, n'est pas le défaire ; le propriétaire et l'opérateur font
    # ce qu'ils veulent des leurs
    assert milestone_guard(two, _asks(status=c.REACHED)) == "" == milestone_guard(one, _asks(ready=True))
    assert milestone_guard(one, _asks(status=c.DROPPED, author="operator")) == ""
    assert milestone_at(_o(_step(s, 1, 10, author="operator", **DROP)), 1).status == c.DROPPED
    assert milestone_at(_o(_step(s, 2, 10, author="owner", by="adrien", **TO_PROSE)), 2).check == c.CHECK_PROSE
    # un jalon que le propriétaire a refusé : il lui revient pour être repris, pas pour être défait
    refused = _step(_step(s, 3, 20, ready=True, how=True), 3, 30, refused=True, reason=True, author="owner",
                    by="adrien")
    back = milestone_at(_o(refused), 3)
    assert back.refused_at == 30 and milestone_held(back) == HELD_REFUSED
    assert _step(refused, 3, 40, **DROP) is refused and _step(refused, 3, 40, **TO_PROSE) is refused
    assert awaiting(_o(_step(refused, 3, 40, ready=True, how=True))).id == 3  # elle le redit prêt, rien d'autre
    # « fait » attend donc toujours ces jalons-là
    assert [m.id for m in open_milestones(_o(refused))] == [1, 2, 3, 4]


def test_the_milestones_of_a_plan_a_person_validated_are_theirs_she_may_only_give_them_a_check():
    # le plan d'un ticket qu'une personne valide : ses jalons naissent « à elle » (la personne)
    s = _with(Objective(1, "o1", runs=1))
    s = _pose(s, 1, agreed=True)
    s = _pose(s, 2, check=c.CHECK_COMMAND, command=Content(ref="cmd"), agreed=True)
    one, two = milestone_at(_o(s), 1), milestone_at(_o(s), 2)
    assert (one.author, one.agreed, milestone_held(one)) == ("self", True, HELD_AGREED)
    # même à sa première exécution : ni retiré, ni réécrit, ni affaibli — la commande remplacée par « true »
    assert milestones.refining(_o(s))
    for number in (1, 2):
        assert _step(s, number, 10, **DROP) is s and _step(s, number, 10, text=True) is s
    assert _step(s, 2, 10, command=Content(ref="true")) is s and _step(s, 2, 10, **TO_PROSE) is s
    assert milestone_guard(two, _asks(command=Content(ref="true"))) == HELD_AGREED
    assert milestone_guard(one, _asks(text=Content(ref="t"))) == HELD_AGREED
    # affiner sans affaiblir : donner une vérification à celui qui n'avait que sa parole — son texte reste
    firm = _step(s, 1, 10, check=c.CHECK_COMMAND, command=Content(ref="c1"))
    got = milestone_at(_o(firm), 1)
    assert (got.check, got.command_ref, got.text_ref, got.agreed, got.revised) == (c.CHECK_COMMAND, "c1", "m1@1",
                                                                                 True, 1)
    assert _step(s, 1, 10, text=True, check=c.CHECK_COMMAND, command=Content(ref="c1")) is s  # pas en le réécrivant
    assert _step(firm, 1, 11, command=Content(ref="true")) is firm  # une fois fixée, elle ne bouge plus
    assert awaiting(_o(_step(_step(s, 1, 10, check=c.CHECK_OWNER), 1, 11, ready=True, how=True))).id == 1
    # elle les dit atteints comme les autres
    assert milestone_at(_o(_step(s, 1, 10, status=c.REACHED, how=True)), 1).status == c.REACHED

    # le plan du projet : validé par une personne, les jalons qu'il a posés sont à elle ; validé d'office, non
    def planned(state: str) -> faculty.ProjectsState:
        hers = Milestone(1, "m1"), Milestone(2, "m2", check=c.CHECK_OWNER)
        done = Milestone(3, "m3", status=c.REACHED)
        o = Objective(1, "o1", milestones=(*hers, done, Milestone(4, "m4", author="operator")), milestone_seq=4)
        return _state(replace(_project(1), objectives=(o, Objective(2, "o2", kind=c.CONSTANT)), objective_seq=2,
                              plan_state=state, plan_ref="plan"))

    def answer(s0: faculty.ProjectsState, verdict: str) -> faculty.ProjectsState:
        return faculty._plan_answered(s0, _ev(PLAN_ANSWERED.payload(project=1, verdict=verdict, by="adrien"), 5),
                                      _cx())

    approved = answer(planned(c.PROPOSED), faculty.APPROVE)
    assert approved.projects[1].plan_state == c.PLANNED
    assert [(m.id, m.agreed) for m in _o(approved).milestones] == [(1, True), (2, True), (3, False), (4, False)]
    assert _step(approved, 1, 10, **DROP) is approved and _step(approved, 2, 10, **TO_PROSE) is approved
    # une révision demandée, ou un plan qui vaut d'office (personne ne l'a validé) : ils restent à elle
    assert not any(m.agreed for m in _o(answer(planned(c.PROPOSED), faculty.REVISE)).milestones)
    assert not any(m.agreed for m in _o(answer(planned(c.PLANNED), faculty.APPROVE)).milestones)
    auto = faculty._plan_proposed(planned(c.TO_FRAME), _ev(PLAN_PROPOSED.payload(
        project=1, plan=Content(ref="p2"), approved=True), 6), _cx())
    assert auto.projects[1].plan_state == c.PLANNED and not any(m.agreed for m in _o(auto).milestones)
    assert milestone_at(_o(_step(auto, 1, 10, **DROP)), 1).status == c.DROPPED


# ── Sur un vrai noyau : l'outil refuse en disant pourquoi ──────────────────


def test_the_tool_refuses_to_undo_a_breakpoint_or_a_command_of_the_owner_and_done_still_waits(tmp_path):
    atelier = Checked()

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le site", objectives="Refaire la page Tarifs", start="3:00", end="4:00")

        async def act(nonce: str, name: str, milestone: str = "", **values: str):
            fixed = {"objective": "1", **({"milestone": milestone} if milestone else {})}
            return await perform(kernel, f"projects.{name}", row_form(fixed, **values), by="user_1",
                                 subject=str(pid), nonce=nonce)

        out = {}
        assert (await act("j1", "jalon_ajouter", text="La page est relue", check="owner")).ok
        assert (await act("j2", "jalon_ajouter", text="Les tests passent", check="command", command="pytest -q")).ok
        await _begin(kernel, pid, "run-1")  # sa première exécution : elle affine librement… ce qui est à elle
        before = _target(kernel, pid)
        out["to_prose"] = await _pose_tool(kernel, pid, "run-1", what="revise", milestone=1, check="prose")
        out["drop"] = await _pose_tool(kernel, pid, "run-1", what="drop", milestone=1, reason="Inutile.")
        out["to_true"] = await _pose_tool(kernel, pid, "run-1", what="revise", milestone=2, argv=["true"],
                                          reason="Plus simple.")
        out["reword"] = await _pose_tool(kernel, pid, "run-1", what="revise", milestone=2, text="Rien à vérifier")
        out["untouched"] = _target(kernel, pid) == before
        # un point d'arrêt qu'elle pose elle-même : elle en revoit le texte, pas la vérification, et ne le retire pas
        await _pose_tool(kernel, pid, "run-1", what="add", text="Montrer la maquette", check="owner")
        out["own_text"] = await _pose_tool(kernel, pid, "run-1", what="revise", milestone=3,
                                           text="Montrer la maquette de la page Tarifs")
        out["own_check"] = await _pose_tool(kernel, pid, "run-1", what="revise", milestone=3, check="prose")
        out["own_drop"] = await _pose_tool(kernel, pid, "run-1", what="drop", milestone=3, reason="Finalement non.")
        # « fait » attend toujours ce qu'elle n'a pas pu défaire
        await atelier.write(pid, "tarifs.html", "<p>90 € par an</p>")
        out["done"] = await _report(kernel, pid, "run-1", verdict="done", summary="Fini.", how_met="La page est juste.",
                                    calls=(("ws_write", True),))
        # refusé par le propriétaire : elle le reprend et le redit prêt, elle ne le défait pas
        await _reach(kernel, pid, 1, "Voir tarifs.html.", "run-1")
        assert (await act("t1", "jalon_trancher", milestone="1", verdict="refuse", reason="Le prix manque.")).ok
        out["refused_drop"] = await _pose_tool(kernel, pid, "run-1", what="drop", milestone=1, reason="Refusé.")
        out["refused_prose"] = await _pose_tool(kernel, pid, "run-1", what="revise", milestone=1, check="prose",
                                                reason="Refusé.")
        out["ready_again"] = await _reach(kernel, pid, 1, "Le prix y est.", "run-1")
        await _end(kernel, pid, "run-1")
        o = _target(kernel, pid)
        out["final"] = (o, _texts_of(kernel, o))
        return out

    out = live(tmp_path, scenario, atelier=atelier)
    for key in ("to_prose", "drop", "own_check", "own_drop"):
        got = out[key]
        assert not got.ok and "c'est un point d'arrêt" in got.content and "needs_you" in got.content, key
    for key in ("to_true", "reword"):
        got = out[key]
        assert not got.ok and "il n'est pas de toi" in got.content and "needs_you" in got.content, key
    assert out["untouched"]  # rien ne s'est écrit
    assert "révisé" in out["own_text"]
    assert not out["done"].ok and "n° 1" in out["done"].content and "n° 2" in out["done"].content
    for key in ("refused_drop", "refused_prose"):
        assert not out[key].ok and "Le jalon n° 1" in out[key].content and "il a été refusé" in out[key].content
    assert "attend" in out["ready_again"]
    o, texts = out["final"]
    assert [(m.id, m.check, m.status, m.author) for m in o.milestones] == [
        (1, c.CHECK_OWNER, c.OPEN, "operator"), (2, c.CHECK_COMMAND, c.OPEN, "operator"),
        (3, c.CHECK_OWNER, c.OPEN, "self")]
    assert texts[o.milestones[0].text_ref] == "La page est relue" and awaiting(o).id == 1
    assert milestones.decoded(texts[o.milestones[1].command_ref]) == ("pytest", "-q")


def test_the_milestones_of_a_ticket_plan_a_person_validated_cannot_be_undone_by_the_run(tmp_path):
    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le site", objectives="Écrire la page d'accueil", start="3:00",
                           end="4:00")
        await items_add(AddArgs(list_name="tickets", items=[ItemArg(title="La page Tarifs est fausse")]),
                        _ctx(kernel, "items_add", pid))
        await wait(1)  # « Traiter les tickets » naît de ce ticket qu'elle a ouvert (ADR 0280) : avant de valider
        await ticket_step(StepArgs(item="1", **TICKET_PLAN), _ctx(kernel, "ticket_step", pid))
        plan = next(x for x in _project_of(kernel, pid).board.items if x.number == 1)
        got = await perform(kernel, "projects.ticket_trancher",
                            row_form({"item": "1", "plan": str(plan.plan_seq)}, verdict="validate"), by="user_1",
                            subject=str(pid), nonce="v1")
        assert got.ok, got
        oid = next(x for x in _project_of(kernel, pid).board.items if x.number == 1).objective
        out = {"born": _target(kernel, pid, oid)}
        await _begin(kernel, pid, "run-1", oid)
        out["drop"] = await _pose_tool(kernel, pid, "run-1", oid, what="drop", milestone=1, reason="Déjà fait.")
        out["reword"] = await _pose_tool(kernel, pid, "run-1", oid, what="revise", milestone=2, text="Ne rien faire")
        out["firm"] = await _pose_tool(kernel, pid, "run-1", oid, what="revise", milestone=2, check="command",
                                       argv=["pytest", "-q"])
        out["weaken"] = await _pose_tool(kernel, pid, "run-1", oid, what="revise", milestone=2, argv=["true"])
        out["added"] = await _pose_tool(kernel, pid, "run-1", oid, what="add", text="Le pied de page est relu")
        out["own_drop"] = await _pose_tool(kernel, pid, "run-1", oid, what="drop", milestone=3, reason="Hors sujet.")
        await _end(kernel, pid, "run-1")
        o = _target(kernel, pid, oid)
        out["final"] = (o, _texts_of(kernel, o))
        return out

    out = live(tmp_path, scenario)
    assert [(m.author, m.agreed) for m in out["born"].milestones] == [("self", True), ("self", True)]
    for key in ("drop", "reword", "weaken"):
        got = out[key]
        assert not got.ok and "vient d'un plan qui a été validé" in got.content and "needs_you" in got.content, key
    assert "révisé" in out["firm"] and "posé" in out["added"] and "retiré" in out["own_drop"]
    o, texts = out["final"]
    assert [(m.id, m.check, m.status, m.agreed) for m in o.milestones] == [
        (1, c.CHECK_PROSE, c.OPEN, True), (2, c.CHECK_COMMAND, c.OPEN, True), (3, c.CHECK_PROSE, c.DROPPED, False)]
    assert texts[o.milestones[1].text_ref] == "Le corriger" and "pytest" in texts[o.milestones[1].command_ref]


# ── Le blocage ne se contourne pas ─────────────────────────────────────────


def test_dropping_her_milestones_and_posing_others_never_resets_the_count_and_twelve_runs_stay_the_net():
    s = _pose(_pose(_with(Objective(1, "o1")), 1), 2)
    assert _o(s).stale == 0
    # trois exécutions sans jalon atteint, puis elle retire ses jalons et en pose d'autres : le compte ne repart pas
    for n in range(1, 4):
        s = _run(s, n * 10)
    assert _o(s).stale == 3 and _stuck(s) == []
    s = _step(_step(s, 1, 35, **DROP), 2, 36, **DROP)
    assert milestones_of(_o(s)) == ()
    s = _pose(_pose(s, 3, at=37), 4, at=38)
    assert [m.id for m in milestones_of(_o(s))] == [3, 4] and _o(s).stale == 3
    s = _run(s, 40)
    assert _o(s).stale == PM.milestone_runs_max and _stuck(s) == ["4 exécutions de suite sans atteindre un nouveau jalon"]
    # la toute première pose, elle, fait repartir le compte ; un jalon atteint aussi
    assert _o(_pose(_with(Objective(1, "o1", stale=3)), 1)).stale == 0
    assert _o(_run(s, 50, reach=3)).stale == 0
    # et même en atteignant un jalon de temps en temps, douze exécutions en tout restent le plafond
    looping = _with(replace(_o(_run(s, 50, reach=3)), runs=PM.once_runs_max - 1))
    assert _stuck(looping) == []
    assert _stuck(_run(looping, 60)) == ["à bout d'exécutions (12) sans en venir à bout"]
    # sans plus aucun jalon vivant au moment du contrôle, c'est encore ce plafond qui vaut
    bare = _step(_step(_with(replace(_o(s), runs=PM.once_runs_max, stale=0)), 3, 70, **DROP), 4, 71, **DROP)
    assert _stuck(bare) == ["à bout d'exécutions (12) sans en venir à bout"]
