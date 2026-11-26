"""Les jalons d'un objectif (ADR 0273).

- un jalon se pose, cinq vivants au plus ; se révise avec sa raison ; atteint, il ne se défait ni ne se révise ;
- un point d'arrêt retient l'objectif jusqu'à ce que le propriétaire le tranche — lui seul —, validé ou refusé ;
- un objectif qui a des jalons bloque après quatre exécutions de suite sans nouveau jalon atteint ; et, avec ou
  sans jalon, à bout d'exécutions (ADR 0278) ;
- ce qu'une exécution en lit, la liste de passage d'un constant, ce qu'une relecture en cite, les jalons d'un plan de
  ticket relu ;
- sur un vrai noyau : le plan pose les jalons, la première exécution les affine, une exécution interrompue reprend
  au bon jalon, la commande qui échoue ne valide rien et celle qui réussit garde sa preuve, « fait » attend ;
- le jalon lié à un élément du registre ; les jalons d'un ticket validé deviennent ceux de son objectif ;
- la console : ajouter un jalon, valider ou refuser un point d'arrêt, la liste de passage d'un constant.
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from types import SimpleNamespace

from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects import faculty, milestones, tend, tickets
from mika.faculties.projects.faculty import (
    Objective,
    ProjectsState,
    _sent_back,
    awaiting,
    milestone_at,
    milestones_of,
    next_milestone,
    objective_at,
    open_milestones,
    subject_of,
)
from mika.faculties.projects.framing_tools import PlanArgs, project_plan
from mika.faculties.projects.milestones import MILESTONE_ADDED, MILESTONE_CHANGED
from mika.faculties.projects.prompt import _live_section, _run_section, _texts
from mika.faculties.projects.reaching import (
    PoseArgs,
    ReachArgs,
    SettleArgs,
    milestone_reach,
    project_milestone,
    project_milestones,
)
from mika.faculties.projects.rhythm import held_back, pick, ready
from mika.faculties.projects.tools import ReportArgs, report_run
from mika.faculties.projects.tracker_tools import AddArgs, ItemArg, items_add
from mika.faculties.projects.triage import StepArgs, ticket_step
from mika.kernel.events import Content, Origin
from mika.kernel.faculty import ToolResult
from mika.kernel.frame import EpisodeRef, Frame
from mika.kernel.inspect import Badge, Table
from mika.kernel.state import FrozenDict
from mika.ports.workshop import RunResult
from mika.runtime.operations import perform
from mika.runtime.tools import ToolContext
from mika.vocab.access import OWNER, PERSON
from mika.vocab.episodes import Kind, project_target
from tests.fixtures.atelier import Atelier
from tests.fixtures.mika import connect
from tests.unit.test_project_access import facing, set_access, talking
from tests.unit.test_project_links import PM, _cx, _ev, _project, _state
from tests.unit.test_projects import create, form, live, row_form, wait
from tests.unit.test_projects_console import tab, tables

_CALLS = itertools.count(1)


def _words(got) -> str:
    return got.content if isinstance(got, ToolResult) else got


# ── Les règles, pures ──────────────────────────────────────────────────────


def _with(*objectives: Objective) -> ProjectsState:
    return _state(replace(_project(1), objectives=objectives, objective_seq=len(objectives)))


def _o(s: ProjectsState, oid: int = 1) -> Objective:
    return objective_at(s.projects[1], oid)


def _pose(s: ProjectsState, number: int, at: int = 1, oid: int = 1, **fields) -> ProjectsState:
    data = MILESTONE_ADDED.payload(project=1, objective=oid, milestone=number, text=Content(ref=f"m{number}@{at}"),
                                   **fields)
    return milestones._milestone_added(s, _ev(data, at), _cx())


def _step(s: ProjectsState, number: int, at: int, **fields) -> ProjectsState:
    refs = {k: Content(ref=f"{k}@{at}") for k in ("text", "how", "proof", "reason") if fields.pop(k, False)}
    data = MILESTONE_CHANGED.payload(project=1, objective=1, milestone=number, **refs, **fields)
    return milestones._milestone_changed(s, _ev(data, at), _cx())


def test_five_milestones_at_most_a_revision_keeps_its_reason_and_a_reached_one_is_never_undone():
    s = _with(Objective(1, "o1"), Objective(2, "o2", kind=c.CONSTANT))
    for n in range(1, 6):
        s = _pose(s, n, at=n)
    assert [m.id for m in milestones_of(_o(s))] == [1, 2, 3, 4, 5]
    assert _pose(s, 6, at=6) is s  # cinq au plus
    assert _pose(s, 1, at=7, oid=2) is s and milestones_of(_o(s, 2)) == ()  # un constant n'a pas de jalons
    # retiré avec sa raison : il reste lisible, ne compte plus, et son numéro ne revient pas
    s = _step(s, 5, 10, status=c.DROPPED, reason=True)
    dropped = milestone_at(_o(s), 5)
    assert (dropped.status, dropped.reason_ref) == (c.DROPPED, "reason@10") and len(milestones_of(_o(s))) == 4
    s = _pose(s, 5, at=11)  # un numéro déjà donné : le suivant
    assert [m.id for m in milestones_of(_o(s))] == [1, 2, 3, 4, 6] and _o(s).milestone_seq == 6
    # révisé : son texte et sa vérification changent, sa raison est gardée, la révision comptée
    s = _step(s, 2, 20, text=True, check=c.CHECK_COMMAND, command=Content(ref="cmd@20"), reason=True)
    revised = milestone_at(_o(s), 2)
    assert (revised.text_ref, revised.check, revised.command_ref, revised.reason_ref, revised.revised) == \
        ("text@20", c.CHECK_COMMAND, "cmd@20", "reason@20", 1)
    assert _step(s, 2, 21, check=c.CHECK_COMMAND) is s  # rien ne change : pas une révision
    # atteint : comment, sa preuve, le commit ; ensuite il ne se défait ni ne se révise, ni ne s'atteint deux fois
    s = _step(s, 2, 30, status=c.REACHED, how=True, proof=True, commit="abc123")
    reached = milestone_at(_o(s), 2)
    assert (reached.status, reached.reached_at, reached.reached_by, reached.how_ref, reached.proof_ref,
            reached.commit) == (c.REACHED, 30, "self", "how@30", "proof@30", "abc123")
    for undo in ({"text": True, "reason": True}, {"status": c.DROPPED, "reason": True}, {"status": c.REACHED},
                 {"check": c.CHECK_PROSE}):
        assert _step(s, 2, 31, **undo) is s
    assert [m.id for m in open_milestones(_o(s))] == [1, 3, 4, 6] and next_milestone(_o(s)).id == 1
    # l'état reste borné : les jalons retirés les plus anciens tombent, jamais un vivant ni un atteint
    for n in range(7, 20):
        s = _pose(_step(s, n - 1, 100 + n, status=c.DROPPED, reason=True), n, at=100 + n)
    kept = _o(s).milestones
    assert len(kept) == milestones.MILESTONES_KEPT and [m.id for m in milestones_of(_o(s))] == [1, 2, 3, 4, 19]
    assert milestone_at(_o(s), 5) is None and milestone_at(_o(s), 2).status == c.REACHED


def test_a_breakpoint_holds_its_objective_until_the_owner_settles_it_and_only_the_owner_does():
    s = _pose(_pose(_with(Objective(1, "o1", stale=3)), 1, check=c.CHECK_OWNER), 2)
    p = s.projects[1]
    assert ready(p, _o(s)) and awaiting(_o(s)) is None
    assert _step(s, 1, 10, status=c.REACHED, how=True) is s  # elle ne se valide pas elle-même
    assert _step(s, 1, 10, status=c.REACHED, how=True, author="owner", by="adrien") is s  # ni lui avant qu'elle le dise
    assert _step(s, 2, 10, ready=True, how=True) is s  # seul un point d'arrêt se dit prêt
    s = _step(s, 1, 20, ready=True, how=True, commit="c1")
    held = awaiting(_o(s))
    assert (held.id, held.ready_at, held.how_ref, held.commit) == (1, 20, "how@20", "c1")
    assert _o(s).stale == 0  # le dire prêt est une avancée
    p = s.projects[1]
    assert held_back(p, _o(s)) and not ready(p, _o(s)) and pick(p, 100, PM) is None  # l'objectif attend
    assert next_milestone(_o(s)).id == 2  # ce qui vient n'est pas ce qui attend
    # la main est au propriétaire : elle ne le révise plus, ne le retire plus, ne le redit pas prêt
    for hers in ({"text": True, "reason": True}, {"status": c.DROPPED, "reason": True}, {"ready": True},
                 {"refused": True, "reason": True}):
        assert _step(s, 1, 21, **hers) is s
    # refusé : il lui revient, la raison gardée ; l'objectif repart
    s = _step(s, 1, 30, refused=True, reason=True, author="owner", by="adrien")
    back = milestone_at(_o(s), 1)
    assert (back.status, back.ready_at, back.refused_at, back.reason_ref) == (c.OPEN, 0, 30, "reason@30")
    assert ready(s.projects[1], _o(s)) and awaiting(_o(s)) is None
    # redit prêt, puis validé : atteint par lui, avec ce qu'elle en avait dit
    s = _step(s, 1, 40, ready=True, how=True, commit="c2")
    s = _step(s, 1, 50, status=c.REACHED, author="owner", by="adrien")
    done = milestone_at(_o(s), 1)
    assert (done.status, done.reached_by, done.how_ref, done.commit, done.ready_at) == \
        (c.REACHED, "adrien", "how@40", "c2", 0)
    assert ready(s.projects[1], _o(s))


def _run(s: ProjectsState, at: int, *, outcome: str = "done", reach: int = 0) -> ProjectsState:
    """Une exécution de l'objectif n° 1 : son départ, un jalon atteint ou non, son compte rendu, sa fin."""
    eid = f"e{at}"
    start = SimpleNamespace(kind=Kind.WORK, target=project_target(1), subject=subject_of(1, 1), reason="")
    s = faculty._started(s, _ev(start, at, eid), _cx())
    if reach:
        s = _step(s, reach, at + 1, status=c.REACHED, how=True)
    if outcome == "done":
        report = c.RUN_REPORTED.payload(project=1, objective=1, verdict=c.CONTINUE, summary=Content(ref=f"r{at}"))
        s = faculty._reported(s, _ev(report, at + 2, eid), _cx())
    end = SimpleNamespace(outcome=outcome, detail="", target=project_target(1))
    return faculty._ended(s, _ev(end, at + 3, eid), _cx())


def _stuck(s: ProjectsState) -> list[str]:
    frame = SimpleNamespace(env=SimpleNamespace(params_of=lambda owner, root: PM), root=None)
    return [why for _, _, why in tend.closures(s, frame)]


def test_an_objective_with_milestones_blocks_after_four_runs_without_a_new_one_the_others_keep_the_old_rule():
    s = _pose(_pose(_with(Objective(1, "o1")), 1), 2)
    for n in range(1, 4):
        s = _run(s, n * 10)
    assert _o(s).stale == 3 and _stuck(s) == []
    s = _run(s, 40, outcome="failed")  # une exécution qui n'a pas eu lieu ne compte pas
    assert _o(s).stale == 3 and _stuck(s) == []
    reached = _run(s, 50, reach=1)  # un jalon atteint : le compte repart
    assert _o(reached).stale == 0 and _stuck(reached) == []
    s = _run(s, 50)
    assert _o(s).stale == PM.milestone_runs_max == 4
    assert _stuck(s) == ["4 exécutions de suite sans atteindre un nouveau jalon"]
    # douze exécutions en tout restent le filet de tout ponctuel, même s'il avance (ADR 0278) ; sans jalon, de même
    busy = replace(_o(reached), runs=PM.once_runs_max)
    assert _stuck(_with(busy)) == ["à bout d'exécutions (12) sans en venir à bout"]
    assert _stuck(_with(replace(busy, runs=PM.once_runs_max - 1))) == []
    plain = Objective(1, "o1", runs=PM.once_runs_max - 1, stale=PM.once_runs_max - 1)
    assert _stuck(_with(plain)) == []
    assert _stuck(_with(replace(plain, runs=PM.once_runs_max))) == ["à bout d'exécutions (12) sans en venir à bout"]
    # ses premiers jalons font repartir le compte ; les retirer tous rend la règle d'avant
    late = _pose(_with(replace(plain, stale=9)), 1)
    assert _o(late).stale == 0 and _stuck(late) == []
    assert _stuck(_step(_with(replace(_o(late), runs=12)), 1, 5, status=c.DROPPED, reason=True)) != []
    # rouvert, il repart de rien
    again = faculty.reopened(replace(_o(s), status=c.BLOCKED), 99)
    assert (again.stale, again.runs) == (0, 0)


def test_what_a_run_reads_of_its_milestones_what_a_review_quotes_and_the_pass_list_of_a_constant():
    s = _with(Objective(1, "o1", runs=1))
    s = _pose(s, 1)
    s = _pose(s, 2, check=c.CHECK_COMMAND, command=Content(ref="cmd"))
    s = _pose(s, 3, check=c.CHECK_OWNER)
    s = _pose(s, 4, check=c.CHECK_ITEM, item_list="tickets", item_key="#3", item_status="treated")
    s = _step(s, 1, 10, status=c.REACHED, how=True, proof=True, commit="c0ffee0123456789")
    texts = {"m1@1": "Les prix sont relevés", "m2@1": "Les tests passent", "m3@1": "La page est relue",
             "m4@1": "Le ticket du pied de page est traité", "cmd": milestones.encoded(["pytest", "-q"]),
             "how@10": "Relevés dans prix.json", "proof@10": "pytest -q — code 0 (12 ms)\n3 passed"}
    o = _o(s)
    assert milestones.refs(o) == ["m1@1", "how@10", "proof@10", "m2@1", "cmd", "m3@1", "m4@1"]
    read = "\n".join(milestones.lines(o, texts, "« Adrien »"))
    assert "« done » attend qu'ils le soient tous" in read
    assert "- n° 1 [atteint] « Les prix sont relevés » — tu diras comment il est rempli. Preuve : pytest -q — code 0 " \
           "(12 ms) 3 passed" in read  # sa preuve, en une ligne
    assert "- n° 2 [à faire : c'est celui qui vient] « Les tests passent » — vérifié par une commande que " \
           "milestone_reach lance : pytest -q." in read
    assert "- n° 3 [à faire] « La page est relue » — point d'arrêt : tu le dis prêt, « Adrien » le valide" in read
    assert "l'élément « #3 » de la liste « tickets », au statut « treated »" in read
    assert "première exécution sur cet objectif" in read  # elle peut les affiner
    later = replace(o, runs=2, worked=2)
    assert "première exécution" not in "\n".join(milestones.lines(later, texts, "« Adrien »"))
    # rouvert par l'hôte, ses exécutions repartent de zéro : ce n'est pas pour autant sa première (ADR 0280) — ni
    # la phrase, ni le droit de réviser ses jalons sans dire pourquoi
    reopened = _sent_back(replace(o, status=c.DONE, runs=3, worked=3))
    assert (reopened.status, reopened.runs, reopened.worked) == (c.OPEN, 0, 3) and not milestones.refining(reopened)
    again = replace(reopened, runs=1, worked=4)  # l'exécution qui le reprend
    assert "première exécution" not in "\n".join(milestones.lines(again, texts, "« Adrien »"))
    assert milestones.refining(replace(o, runs=1, worked=1)) and milestones.refining(Objective(1, "o1"))
    waiting = _o(_step(s, 3, 20, ready=True, how=True))
    held = "\n".join(milestones.lines(waiting, texts, "« Adrien »"))
    assert "- n° 3 [prêt : il attend la validation de « Adrien »]" in held and "n'avance pas au-delà de lui" in held
    refused = _o(_step(_step(s, 3, 20, ready=True, how=True), 3, 30, refused=True, reason=True, author="owner"))
    assert "Refusé : « Trop pâle. »" in "\n".join(milestones.lines(refused, {**texts, "reason@30": "Trop pâle."}))
    # sans jalon : à sa première exécution elle peut en poser ; ensuite, rien
    assert "n'a pas de jalons" in milestones.lines(Objective(1, "o1", runs=1), {})[0]
    assert milestones.lines(Objective(1, "o1", runs=3, worked=3), {}) == []
    assert milestones.lines(Objective(1, "o1", runs=1, worked=4), {}) == []  # rouvert : pas sa première non plus
    # ce qu'une relecture cite : un jalon par ligne, sa preuve et son commit — une fonction pure des textes
    quoted = milestones.cited(o, texts)
    assert len(quoted) == 4
    assert quoted[0] == ("Jalon n° 1 « Les prix sont relevés » — atteint (tu diras comment il est rempli). Comment : "
                         "Relevés dans prix.json Preuve : pytest -q — code 0 (12 ms) 3 passed Commit : c0ffee012345.")
    assert quoted[1].startswith("Jalon n° 2 « Les tests passent » — à faire (vérifié par une commande")
    assert "(un jalon dont le texte est oublié)" in milestones.cited(o, {})[0]
    # un constant : sa liste de passage, cinq lignes au plus, et aucun jalon
    kept = milestones.routine_text(["Relever les prix", "  ", "Noter  les écarts", "c", "d", "e", "f"])
    assert kept.split("\n") == ["Relever les prix", "Noter les écarts", "c", "d", "e"]
    constant = Objective(2, "o2", kind=c.CONSTANT, routine_ref="routine")
    assert milestones.routine_lines(constant, {"routine": kept})[0].startswith("À chaque passage :\n- Relever les prix")
    assert milestones.lines(constant, {}) == [] and milestones.routine_lines(o, {"routine": kept}) == []
    # ce qu'un jalon demandé doit avoir ; les jalons d'un plan de ticket, relus
    assert [milestones.problem(milestones.Spec(*x)) for x in (
        ("",), ("x", "magie"), ("x", c.CHECK_COMMAND), ("x", c.CHECK_ITEM, (), "tickets", "", "done"),
        ("x", c.CHECK_COMMAND, ("pytest",)), ("x", c.CHECK_OWNER))] == \
        ["no_text", "bad_check", "no_command", "no_item", "", ""]
    plan = tickets.plan_text("Corriger le lien", "README.md", ["Trouver le lien", "Le corriger"], "le reste", True)
    assert tickets.plan_steps(plan) == ("Trouver le lien", "Le corriger")
    assert tickets.plan_steps(tickets.plan_text("Corriger le lien", "", [], "", False)) == ()
    assert tickets.STEPS_MAX == c.MILESTONES_MAX == 5


# ── Sur un vrai noyau ──────────────────────────────────────────────────────


class Checked(Atelier):
    """Un atelier dont les programmes échouent tant qu'on le dit."""

    failing = False

    async def run(self, project: int, argv, *, timeout_s=None, network: bool = False, views=()) -> RunResult:
        got = await super().run(project, argv, timeout_s=timeout_s, network=network, views=views)
        self.networked = network
        return RunResult(tuple(argv), 1, stderr="1 failed\n") if self.failing else replace(got, stdout="3 passed\n")


def _project_of(kernel, pid: int):
    return kernel.mind.frame().state("projects").projects[pid]


def _target(kernel, pid: int, oid: int = 1) -> Objective:
    return objective_at(_project_of(kernel, pid), oid)


def _ctx(kernel, name: str, pid: int, oid: int = 1, eid: str = "", calls: tuple = ()) -> ToolContext:
    """Un appel d'outil pendant l'exécution ``eid`` qui vise cet objectif."""
    mind, n = kernel.mind, next(_CALLS)
    eid = eid or f"ep-jalons-{n}"
    episode = EpisodeRef(eid, Kind.WORK, target=project_target(pid),
                         attrs=FrozenDict({"subject": subject_of(pid, oid)}))
    frame = Frame(mind.frame().root, mind.clock.now(), mind.registry, facing("user_1", owner=True), episode)
    return ToolContext(mind, mind.registry.tools[name], f"appel-jalons-{n}", eid, frame, ports=kernel.ports,
                       calls=calls)


async def _begin(kernel, pid: int, eid: str, oid: int = 1) -> None:
    await kernel.mind.append([rt.EPISODE_STARTED.draft(kind=Kind.WORK, target=project_target(pid),
                                                       subject=subject_of(pid, oid))],
                             emitter="runtime", correlation=eid, origin=Origin.KERNEL)


async def _end(kernel, pid: int, eid: str, outcome: str = "done") -> None:
    await kernel.mind.append([rt.EPISODE_ENDED.draft(kind=Kind.WORK, outcome=outcome, target=project_target(pid))],
                             emitter="runtime", correlation=eid, origin=Origin.KERNEL)


async def _pose_tool(kernel, pid: int, eid: str = "", oid: int = 1, **fields):
    return await project_milestones(PoseArgs(**fields), _ctx(kernel, "project_milestones", pid, oid, eid))


async def _reach(kernel, pid: int, number: int, how: str, eid: str = "", oid: int = 1):
    return await milestone_reach(ReachArgs(milestone=number, how=how), _ctx(kernel, "milestone_reach", pid, oid, eid))


async def reach_all(kernel, pid: int, oid: int) -> None:
    """Dire atteints tous les jalons encore ouverts de cet objectif : ce qu'une exécution fait avant « fait » (les
    jalons d'un plan de ticket validé sont ceux de son objectif)."""
    for m in open_milestones(_target(kernel, pid, oid)):
        got = await _reach(kernel, pid, m.id, "C'est fait.", oid=oid)
        assert not isinstance(got, ToolResult), got


async def _report(kernel, pid: int, eid: str = "", oid: int = 1, calls: tuple = (), **fields):
    return await report_run(ReportArgs(**fields), _ctx(kernel, "report_run", pid, oid, eid, calls))


async def _reads(kernel, pid: int, oid: int = 1) -> str:
    """Ce que l'exécution qui vise cet objectif lit de son projet."""
    frame = _ctx(kernel, "report_run", pid, oid).frame
    s = frame.state("projects")
    return _run_section(s, frame, {"projects": await _texts(s, frame, kernel.ports)}).content


async def _talk(kernel, handle: str, audience) -> str:
    """« TES PROJETS », tel qu'elle le lit en répondant à cette personne."""
    mind = kernel.mind
    frame = Frame(mind.frame().root, mind.clock.now(), mind.registry, audience,
                  EpisodeRef("ep-parle", Kind.REPLY, target=handle))
    s = frame.state("projects")
    body = _live_section(s, frame, {"projects": await _texts(s, frame, kernel.ports)})
    return body.content if body is not None else ""


def _texts_of(kernel, o: Objective) -> dict[str, str]:
    return kernel.ports["store"].content(milestones.refs(o))


PLAN = {
    "aim": "Une page Tarifs juste.", "deliverables": "La page Tarifs à jour.", "approach": "Relever, corriger, relire.",
    "steps": [
        {"text": "Refaire la page Tarifs", "done_when": "la page affiche les bons prix", "keep": 1, "milestones": [
            {"text": "Les prix sont relevés"},
            {"text": "Les tests passent", "check": "command", "argv": ["pytest", "-q"]},
            {"text": "La page est relue", "check": "owner"}]},
        {"text": "Surveiller les prix", "kind": "constant", "cadence_hours": 24,
         "each_pass": ["Relever les prix", "Noter les écarts"]},
    ],
}
BAD_PLAN = {**PLAN, "steps": [
    {"text": "Refaire la page", "done_when": "elle est juste", "keep": 1, "each_pass": ["Relire"],
     "milestones": [{"text": "Les tests passent", "check": "command"}]},
    {"text": "Surveiller", "kind": "constant", "milestones": [{"text": "Un jalon"}]}]}


def test_the_plan_poses_milestones_the_first_run_refines_them_and_an_interrupted_run_resumes_at_the_right_one(tmp_path):
    atelier = Checked()

    async def scenario(kernel, llm):
        await connect(kernel, "user_2", "Camille")
        pid = await create(kernel, "p1", title="Le site", objectives="Refaire la page Tarifs", start="3:00", end="4:00")
        await set_access(kernel, pid, {"who": [OWNER], "see": True, "steer": "modification"},
                         {"who": [PERSON + "user_2"], "see": True, "steer": "modification"}, nonce="a1")
        camille, adrien = facing("user_2"), facing("user_1", owner=True)
        out = {"pid": pid}
        # ── le plan pose les jalons grossiers d'un ponctuel, et la liste de passage d'un constant
        out["bad_plan"] = await project_plan(PlanArgs.model_validate(BAD_PLAN), _ctx(kernel, "project_plan", pid))
        out["plan"] = await project_plan(PlanArgs.model_validate(PLAN), _ctx(kernel, "project_plan", pid))
        out["posed"] = _target(kernel, pid)
        constant = next(o for o in _project_of(kernel, pid).objectives if o.kind == c.CONSTANT)
        out["constant"] = constant
        out["routine"] = kernel.ports["store"].content([constant.routine_ref])[constant.routine_ref]
        out["constant_reads"] = await _reads(kernel, pid, constant.id)
        out["constant_reach"] = await _reach(kernel, pid, 1, "Fait.", oid=constant.id)
        out["constant_pose"] = await _pose_tool(kernel, pid, oid=constant.id, what="add", text="Un jalon")
        # ── sa première exécution : elle affine sans dire pourquoi, en pose un, en atteint un — puis elle est coupée
        await _begin(kernel, pid, "run-1")
        out["first_reads"] = await _reads(kernel, pid)
        out["refined"] = await _pose_tool(kernel, pid, "run-1", what="revise", milestone=1,
                                          text="Les prix de 2026 sont relevés dans prix.json")
        out["added"] = await _pose_tool(kernel, pid, "run-1", what="add", text="Le pied de page est à jour")
        out["no_command"] = await _pose_tool(kernel, pid, "run-1", what="add", text="Un essai", check="command")
        out["reach_1"] = await _reach(kernel, pid, 1, "Relevés dans prix.json", "run-1")
        out["reach_1_twice"] = await _reach(kernel, pid, 1, "Encore.", "run-1")
        out["undo_1"] = await _pose_tool(kernel, pid, "run-1", what="drop", milestone=1, reason="Finalement non.")
        await _end(kernel, pid, "run-1", "interrupted")
        out["interrupted"] = _target(kernel, pid)
        # ── l'exécution suivante reprend au bon jalon ; la commande qui échoue ne valide rien
        await _begin(kernel, pid, "run-2")
        out["resumed_reads"] = await _reads(kernel, pid)
        atelier.failing = True
        out["failed"] = await _reach(kernel, pid, 2, "Les tests passent.", "run-2")
        out["after_failure"] = milestone_at(_target(kernel, pid), 2)
        await atelier.write(pid, "tarifs.html", "<p>90 € par an</p>")
        out["done_too_early"] = await _report(kernel, pid, "run-2", verdict="done", summary="Fini.",
                                              how_met="La page affiche 90 €.")
        out["nothing_committed"] = await atelier.pending(pid)
        atelier.failing = False
        out["reach_2"] = await _reach(kernel, pid, 2, "Les tests passent.", "run-2")
        out["ran"] = (atelier.ran[-1], atelier.networked)
        out["reach_3"] = await _reach(kernel, pid, 3, "Voir tarifs.html : les trois prix.", "run-2")
        out["reach_3_twice"] = await _reach(kernel, pid, 3, "Encore.", "run-2")
        out["revise_waiting"] = await _pose_tool(kernel, pid, "run-2", what="revise", milestone=3, text="Autre",
                                                 reason="Pour voir.")
        out["waited"] = await _report(kernel, pid, "run-2", verdict="wait", summary="La page attend sa relecture.",
                                      needs_you="Relis la page Tarifs.")
        await _end(kernel, pid, "run-2")
        p = _project_of(kernel, pid)
        out["held"] = (_target(kernel, pid), ready(p, _target(kernel, pid)), p.last_commit)
        # ── le point d'arrêt : il attend le propriétaire, et lui seul le tranche
        out["talk"] = await _talk(kernel, "user_1", adrien)
        out["talk_camille"] = await _talk(kernel, "user_2", camille)

        async def settle(handle: str, audience, **fields):
            return await project_milestone(SettleArgs(project="le site", **fields),
                                           talking(kernel, handle, audience, "project_milestone"))

        out["camille"] = await settle("user_2", camille, what="validate")
        out["refuse_bare"] = await settle("user_1", adrien, what="refuse")
        out["refused"] = await settle("user_1", adrien, what="refuse", text="Le prix mensuel manque.")
        out["after_refusal"] = (_target(kernel, pid), ready(_project_of(kernel, pid), _target(kernel, pid)))
        out["nothing_waits"] = await settle("user_1", adrien, what="validate")
        # ── une exécution plus tard : une révision dit sa raison, un retrait toujours
        await _begin(kernel, pid, "run-3")
        out["refused_reads"] = await _reads(kernel, pid)
        out["revise_bare"] = await _pose_tool(kernel, pid, "run-3", what="revise", milestone=4, text="Le pied de page")
        out["revised"] = await _pose_tool(kernel, pid, "run-3", what="revise", milestone=4,
                                          text="Le pied de page dit 2026", reason="Plus précis.")
        out["drop_bare"] = await _pose_tool(kernel, pid, "run-3", what="drop", milestone=4)
        out["dropped"] = await _pose_tool(kernel, pid, "run-3", what="drop", milestone=4,
                                          reason="Le pied de page n'a pas de prix.")
        out["reach_3_again"] = await _reach(kernel, pid, 3, "Le prix mensuel y est.", "run-3")
        await _report(kernel, pid, "run-3", verdict="wait", summary="Elle attend de nouveau.")
        await _end(kernel, pid, "run-3")
        out["validated"] = await settle("user_1", adrien, what="validate", objective=1, milestone=3, text="Parfait.")
        # ── tous atteints : « fait » s'écrit
        await _begin(kernel, pid, "run-4")
        await atelier.write(pid, "tarifs.html", "<p>90 € par an, 9 € par mois</p>")
        out["done"] = await _report(kernel, pid, "run-4", verdict="done", summary="La page est juste.",
                                    how_met="Elle affiche les trois prix.", calls=(("ws_write", True),))
        await _end(kernel, pid, "run-4")
        o = _target(kernel, pid)
        out["final"] = o
        out["final_texts"] = _texts_of(kernel, o)
        out["cited"] = milestones.cited(o, out["final_texts"])
        return out

    out = live(tmp_path, scenario, atelier=atelier)
    # le plan : un constant n'a pas de jalons, un ponctuel pas de liste de passage, une commande a ses arguments
    bad = out["bad_plan"]
    assert not bad.ok and "étape 1 : each_pass est pour un constant" in bad.content
    assert "étape 1, jalon 1 : une vérification par commande demande sa commande" in bad.content
    assert "étape 2 : un constant n'a pas de jalons" in bad.content
    assert "Ton plan est revu" in _words(out["plan"])
    posed = out["posed"]
    assert [(m.id, m.check, m.status, m.author) for m in posed.milestones] == \
        [(1, c.CHECK_PROSE, c.OPEN, "self"), (2, c.CHECK_COMMAND, c.OPEN, "self"), (3, c.CHECK_OWNER, c.OPEN, "self")]
    # la liste de passage d'un constant : montrée à chaque passage ; ses jalons ne valent rien
    assert out["routine"] == "Relever les prix\nNoter les écarts" and out["constant"].milestones == ()
    assert "À chaque passage :\n- Relever les prix\n- Noter les écarts" in out["constant_reads"]
    assert "Ses jalons" not in out["constant_reads"]
    for refused in (out["constant_reach"], out["constant_pose"]):
        assert not refused.ok and "Un objectif constant n'a pas de jalons" in refused.content
    # la première exécution voit les jalons du plan, celui qui vient, et qu'elle peut les affiner
    first = out["first_reads"]
    assert "- n° 1 [à faire : c'est celui qui vient] « Les prix sont relevés »" in first
    assert "vérifié par une commande que milestone_reach lance : pytest -q" in first
    assert "première exécution sur cet objectif" in first
    assert "révisé" in out["refined"] and "Jalon n° 4 posé (encore 1 possible(s))" in out["added"]
    assert not out["no_command"].ok and "demande sa commande" in out["no_command"].content
    assert "Jalon n° 1 atteint" in out["reach_1"] and "Vient le n° 2 : « Les tests passent »" in out["reach_1"]
    for undone in (out["reach_1_twice"], out["undo_1"]):  # atteint, il ne se défait pas
        assert not undone.ok and "ne se défait pas" in undone.content
    # coupée sans compte rendu : son crédit est rendu, ce qu'elle a atteint reste
    cut = out["interrupted"]
    assert (cut.runs, cut.stale) == (0, 0) and milestone_at(cut, 1).status == c.REACHED
    resumed = out["resumed_reads"]
    assert "- n° 1 [atteint] « Les prix de 2026 sont relevés dans prix.json »" in resumed
    assert "Preuve : Relevés dans prix.json" in resumed  # sans preuve gardée, comment elle l'a dit
    assert "- n° 2 [à faire : c'est celui qui vient] « Les tests passent »" in resumed
    # la commande qui échoue ne valide rien, et dit pourquoi ; « fait » est refusé, en nommant ce qui reste
    assert not out["failed"].ok and "n'a pas réussi" in out["failed"].content and "1 failed" in out["failed"].content
    assert (out["after_failure"].status, out["after_failure"].proof_ref) == (c.OPEN, "")
    early = out["done_too_early"]
    assert not early.ok and "des jalons qui ne sont pas atteints" in early.content
    assert "- n° 2 [à faire] « Les tests passent »" in early.content and "- n° 3 " in early.content
    assert "n° 1 " not in early.content and out["nothing_committed"] == ["tarifs.html"]  # rien ne s'est enregistré
    # celle qui réussit garde sa preuve : c'est l'outil qui l'a lancée, sans réseau
    assert "Jalon n° 2 atteint" in out["reach_2"] and "Vient le n° 3" in out["reach_2"]
    assert out["ran"] == ((out["pid"], ("pytest", "-q"), ()), False)
    # le point d'arrêt : dit prêt, il retient l'objectif ; le commit montré est celui de son exécution
    assert "attend la validation de « Adrien »" in out["reach_3"]
    for again in (out["reach_3_twice"], out["revise_waiting"]):
        assert not again.ok and "tu n'y touches plus" in again.content
    assert "tu y reviendras" in _words(out["waited"])
    held, is_ready, last_commit = out["held"]
    assert awaiting(held).id == 3 and not is_ready and last_commit
    assert awaiting(held).commit == last_commit == milestone_at(held, 2).commit
    talk = out["talk"]
    assert "un point d'arrêt attend sa validation — objectif n° 1, jalon n° 3 : « La page est relue »" in talk
    # le journal porte l'identifiant complet du commit, ce qu'on lui montre en est l'abrégé (ADR 0277)
    assert len(last_commit) == 40 and f"« Voir tarifs.html : les trois prix. » (commit {last_commit[:12]})" in talk
    assert "project_milestone (what « validate »)" in talk
    assert "point d'arrêt" not in out["talk_camille"]  # il n'est montré qu'à qui le tranche
    assert not out["camille"].ok and "revient à" in out["camille"].content
    assert not out["refuse_bare"].ok and "sans dire pourquoi" in out["refuse_bare"].content
    assert "est refusé" in out["refused"]
    back, is_ready = out["after_refusal"]
    assert awaiting(back) is None and is_ready and milestone_at(back, 3).refused_at
    assert not out["nothing_waits"].ok
    assert "Refusé : « Le prix mensuel manque. »" in out["refused_reads"]
    assert "première exécution" not in out["refused_reads"]
    # passé sa première exécution, une révision dit sa raison ; un retrait, toujours
    for bare in (out["revise_bare"], out["drop_bare"]):
        assert not bare.ok and "Dis pourquoi" in bare.content
    assert "révisé" in out["revised"] and "retiré" in out["dropped"]
    assert "attend la validation" in out["reach_3_again"] and "est validé" in out["validated"]
    # tous atteints (le quatrième retiré) : « fait » s'écrit
    assert "l'objectif n° 1 est atteint" in _words(out["done"])
    final, texts = out["final"], out["final_texts"]
    assert final.status == c.DONE and open_milestones(final) == ()
    two, three, four = (milestone_at(final, n) for n in (2, 3, 4))
    assert texts[two.proof_ref].startswith("pytest -q — code 0") and "3 passed" in texts[two.proof_ref]
    assert (three.status, three.reached_by, texts[three.how_ref]) == (c.REACHED, "user_1", "Le prix mensuel y est.")
    assert texts[three.reason_ref] == "Parfait."
    assert (four.status, four.revised, texts[four.reason_ref]) == (c.DROPPED, 1, "Le pied de page n'a pas de prix.")
    cited = out["cited"]
    assert len(cited) == 3 and "Preuve : pytest -q — code 0" in cited[1] and f"Commit : {two.commit[:12]}." in cited[1]
    assert cited[2].startswith("Jalon n° 3 « La page est relue » — atteint (point d'arrêt")


TICKET_PLAN = {"what": "plan", "changes": "Corriger le prix annuel de la page Tarifs", "where": "site/tarifs.html",
               "steps": ["Relire le prix", "Le corriger"], "untouched": "le pied de page"}


def test_a_milestone_tied_to_an_item_and_the_milestones_of_a_validated_ticket_become_its_objectives(tmp_path):
    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le site", objectives="Écrire la page d'accueil", start="3:00",
                           end="4:00")
        out = {"pid": pid}
        await items_add(AddArgs(list_name="tickets", items=[ItemArg(title="La page Tarifs est fausse"),
                                                            ItemArg(title="Le lien du pied de page est mort")]),
                        _ctx(kernel, "items_add", pid))

        async def step(**fields):
            return await ticket_step(StepArgs(**fields), _ctx(kernel, "ticket_step", pid))

        # ── un jalon lié à un élément du registre : relu au moment où elle le dit
        out["tied"] = await _pose_tool(kernel, pid, what="add", text="Le lien mort est traité", check="item",
                                       item_list="tickets", item="#2", item_status="traité")
        out["missing"] = await _pose_tool(kernel, pid, what="add", text="Un essai", check="item", item_list="tickets")
        out["too_early"] = await _reach(kernel, pid, 1, "Je l'ai regardé.")
        await step(item="2", what="answer", text="Le lien a été retiré : rien à changer.")
        out["reached"] = await _reach(kernel, pid, 1, "Le ticket est fermé.")
        tied = milestone_at(_target(kernel, pid), 1)
        out["tied_state"] = (tied.status, kernel.ports["store"].content([tied.proof_ref])[tied.proof_ref])
        # ── les jalons du plan d'un ticket deviennent ceux de l'objectif qui en naît
        await step(item="1", **TICKET_PLAN)
        plan = next(x for x in _project_of(kernel, pid).board.items if x.number == 1)
        got = await perform(kernel, "projects.ticket_trancher",
                            row_form({"item": "1", "plan": str(plan.plan_seq)}, verdict="validate"), by="user_1",
                            subject=str(pid), nonce="v1")
        assert got.ok, got
        ticket = next(x for x in _project_of(kernel, pid).board.items if x.number == 1)
        o = _target(kernel, pid, ticket.objective)
        out["born"] = o
        out["born_texts"] = _texts_of(kernel, o)
        out["reads"] = await _reads(kernel, pid, o.id)
        await kernel.ports["workshop"].write(pid, "site/tarifs.html", "<p>90 € par an</p>")
        out["early"] = await _report(kernel, pid, oid=o.id, verdict="done", summary="Prix corrigé.",
                                     how_met="Relu : 90 €.", calls=(("ws_write", True),))
        await reach_all(kernel, pid, o.id)
        out["done"] = await _report(kernel, pid, oid=o.id, verdict="done", summary="Prix corrigé.",
                                    how_met="Relu : 90 €.", calls=(("ws_write", True),))
        await wait(2)
        out["closed"] = next((x.status for x in _project_of(kernel, pid).board.items if x.number == 1), "")
        return out

    out = live(tmp_path, scenario)
    assert "Jalon n° 1 posé" in out["tied"]
    assert not out["missing"].ok and "sa liste, l'élément et le statut attendu" in out["missing"].content
    assert not out["too_early"].ok and "#2 est au statut « en analyse », pas « traité »" in out["too_early"].content
    assert "Jalon n° 1 atteint" in out["reached"]
    assert out["tied_state"] == (c.REACHED, "#2 de la liste « tickets » est au statut « traité »")
    born, texts = out["born"], out["born_texts"]
    assert born.ticket == 1 and [(m.id, m.check, m.status, texts[m.text_ref]) for m in born.milestones] == \
        [(1, c.CHECK_PROSE, c.OPEN, "Relire le prix"), (2, c.CHECK_PROSE, c.OPEN, "Le corriger")]
    assert "- n° 1 [à faire : c'est celui qui vient] « Relire le prix »" in out["reads"]
    assert not out["early"].ok and "- n° 2 [à faire] « Le corriger »" in out["early"].content
    assert "est atteint" in _words(out["done"]) and out["closed"] == c.STAGE_TREATED


def test_the_console_adds_a_milestone_settles_a_breakpoint_and_sets_the_pass_list_of_a_constant(tmp_path):
    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le site", objectives="Refaire la page Tarifs", start="3:00", end="4:00")

        async def act(nonce: str, name: str, fixed: dict[str, str], **values: str):
            return await perform(kernel, f"projects.{name}", row_form(fixed, **values), by="user_1", subject=str(pid),
                                 nonce=nonce)

        async def rows():
            """La liste des objectifs, et les jalons que porte le détail de l'objectif n° 1."""
            objectives = tables(await tab(kernel, "objectifs", subject=str(pid)))["Ses objectifs"]
            detail = next(row.detail for row in objectives.rows if row.cells[0] == 1)
            return objectives, next((d for d in detail if isinstance(d, Table) and d.title == "Ses jalons"), None)

        one = {"objective": "1"}
        out = {"pid": pid}
        out["added"] = await act("j1", "jalon_ajouter", one, text="La page est relue", check="owner")
        out["command"] = await act("j2", "jalon_ajouter", one, text="Les tests passent", check="command",
                                   command="pytest -q 'tests/test tarifs.py'")
        out["no_command"] = await act("j3", "jalon_ajouter", one, text="Un essai", check="command")
        out["not_waiting"] = await act("t0", "jalon_trancher", {**one, "milestone": "1"}, verdict="validate")
        o = _target(kernel, pid)
        out["posed"] = (o, _texts_of(kernel, o))
        out["before"] = await rows()
        # elle le dit prêt : la ligne dit qu'il t'attend ; refusé avec sa raison, puis validé
        await _reach(kernel, pid, 1, "Voir tarifs.html.")
        out["waiting"] = await rows()
        out["refuse_bare"] = await act("t1", "jalon_trancher", {**one, "milestone": "1"}, verdict="refuse")
        out["refused"] = await act("t2", "jalon_trancher", {**one, "milestone": "1"}, verdict="refuse",
                                   reason="Le prix mensuel manque.")
        out["after_refusal"] = milestone_at(_target(kernel, pid), 1)
        await _reach(kernel, pid, 1, "Le prix mensuel y est.")
        out["validated"] = await act("t3", "jalon_trancher", {**one, "milestone": "1"}, verdict="validate")
        out["settled"] = milestone_at(_target(kernel, pid), 1)
        # un constant : pas de jalon, sa liste de passage se règle avec lui
        got = await perform(kernel, "projects.objectif_ajouter",
                            form(("only_on_event",), text="Surveiller les prix", kind="constant", cadence_hours="24",
                                 routine="Relever les prix\n\nNoter les écarts"), by="user_1", subject=str(pid),
                            nonce="c1")
        assert got.ok, got
        constant = next(x for x in _project_of(kernel, pid).objectives if x.kind == c.CONSTANT)
        out["routine"] = kernel.ports["store"].content([constant.routine_ref])[constant.routine_ref]
        out["constant_milestone"] = await act("j4", "jalon_ajouter", {"objective": str(constant.id)}, text="Un jalon")
        out["reads"] = await _reads(kernel, pid, constant.id)
        cleared = await act("c2", "objectif_modifier", {"objective": str(constant.id)}, text="Surveiller les prix",
                            kind="constant", cadence_hours="24", routine="")
        assert cleared.ok, cleared
        out["cleared"] = next(x for x in _project_of(kernel, pid).objectives if x.id == constant.id).routine_ref
        return out

    out = live(tmp_path, scenario)
    assert out["added"].ok and out["command"].ok
    assert not out["no_command"].ok and not out["not_waiting"].ok
    o, texts = out["posed"]
    assert [(m.check, m.author) for m in o.milestones] == [(c.CHECK_OWNER, "operator"), (c.CHECK_COMMAND, "operator")]
    assert milestones.decoded(texts[o.milestones[1].command_ref]) == ("pytest", "-q", "tests/test tarifs.py")

    def rhythm(table) -> str:
        column = [col.label for col in table.columns].index("rythme")
        return next(row.cells[column] for row in table.rows if row.cells[0] == 1)

    objectives, shown = out["before"]
    assert "jalons 0/2" in rhythm(objectives)
    assert [(row.cells[0], row.cells[2]) for row in shown.rows] == \
        [(1, "toi (un point d'arrêt)"), (2, "la commande : pytest -q 'tests/test tarifs.py'")]
    objectives, shown = out["waiting"]
    assert "un point d'arrêt t'attend" in rhythm(objectives)
    assert shown.rows[0].cells[3] == Badge("t'attend", "warn") and "Voir tarifs.html." in str(shown.rows[0].cells[4])
    assert not out["refuse_bare"].ok and out["refused"].ok
    assert (out["after_refusal"].status, out["after_refusal"].ready_at) == (c.OPEN, 0)
    assert out["validated"].ok and out["settled"].status == c.REACHED and out["settled"].reached_by
    assert out["routine"] == "Relever les prix\nNoter les écarts"
    assert not out["constant_milestone"].ok
    assert "À chaque passage :\n- Relever les prix\n- Noter les écarts" in out["reads"]
    assert out["cleared"] == ""
