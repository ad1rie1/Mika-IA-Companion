"""Le cadrage (ADR 0145) : un projet né en conversation garde les mots de sa demande et naît à cadrer ; sa séance de
cadrage écrit son plan ; un plan qui pose des questions attend la réponse de qui l'a demandé, qu'elle lui dit ; sa
réponse le lance ou le lui fait reprendre ; planifié, il suit son ordre, et un « fait » dit comment son critère est
rempli. Un passage notable d'un constant se raconte."""

from __future__ import annotations

import itertools

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.faculties.projects.faculty import (
    OBJECTIVE_ADDED,
    PLAN_ANSWERED,
    PLAN_PROPOSED,
    frame_subject,
    pick,
    plan_subject,
)
from mika.faculties.projects.faculty import params as projects_params
from mika.faculties.projects.tools import (
    PlanArgs,
    ReportArgs,
    StartArgs,
    SteerArgs,
    project_plan,
    project_steer,
    report_run,
    start_project,
)
from mika.faculties.projects.work import _plan, _run, untold
from mika.kernel.frame import EpisodeRef, Frame
from mika.kernel.state import FrozenDict
from mika.runtime.tools import ToolContext
from mika.vocab.episodes import Kind, project_target
from tests.fixtures.mika import said
from tests.unit.test_project_access import facing
from tests.unit.test_projects import events, live, wait

_CALLS = itertools.count(1)


def _ctx(kernel, name: str, kind: str, target: str, **attrs) -> ToolContext:
    """Un appel d'outil pendant un épisode : une réponse à Adrien (``reply_to`` : son message) ou une exécution de
    projet (``subject`` : ce qu'elle vise)."""
    mind, n = kernel.mind, next(_CALLS)
    episode = EpisodeRef(f"ep-cadrage-{n}", kind, target=target, attrs=FrozenDict(attrs))
    frame = Frame(mind.frame().root, mind.clock.now(), mind.registry, facing("user_1", owner=True), episode)
    return ToolContext(mind, mind.registry.tools[name], f"appel-{n}", f"ep-cadrage-{n}", frame, ports=kernel.ports)


ASKED = ("peux-tu créer un projet pour faire du trading par ia ?", "mais pour le moment fais semblant d'acheter/vendre")


async def _asked_project(kernel) -> int:
    """Adrien le lui demande en deux messages ; elle ouvre le projet en lui répondant (au second)."""
    first = await kernel.perceive(said("user_1", ASKED[0]))
    second = await kernel.perceive(said("user_1", ASKED[1]))
    here = _ctx(kernel, "start_project", Kind.REPLY, "user_1", reply_to=second.seq)
    said_back = await start_project(StartArgs(title="Trading fictif", objectives=["Une première stratégie simple"],
                                              tools=["forge"]), here)
    assert "naît à cadrer" in said_back and first.seq < second.seq
    for got in (first, second):  # elle lui répond : ce qu'il écrira ensuite est une autre demande
        if got.reply is not None:
            await got.reply
    return events(kernel, c.PROJECT_CREATED)[-1].seq


def test_a_project_asked_in_conversation_keeps_their_words_and_is_framed_before_any_objective(tmp_path):
    async def scenario(kernel, llm):
        pid = await _asked_project(kernel)
        frame = kernel.mind.frame()
        s = frame.state("projects")
        return events(kernel, c.PROJECT_CREATED)[-1], s.projects[pid], _run(s, frame), \
            frame.get(identity_c.PERSON("user_1"))

    created, p, candidates, adrien = live(tmp_path, scenario)
    # ses mots, tels quels, dans l'ordre — pas la paraphrase qu'elle en fait
    assert created.data.request.text == "\n".join(ASKED) and created.data.asked_by == adrien
    assert created.data.framing and p.plan_state == c.TO_FRAME and p.status == c.ACTIVE
    assert pick(p, p.created_at, projects_params(None)) is None  # aucune exécution ne vise encore un objectif
    assert [cand.args["subject"] for cand in candidates] == [frame_subject(p.id)]  # sa séance de cadrage d'abord


def test_her_framing_session_writes_a_plan_that_starts_and_she_says_what_she_will_do(tmp_path):
    """La doublure garde ses idées de départ, sans question : le plan part tout de suite, et elle le dira à Adrien."""

    async def scenario(kernel, llm):
        pid = await _asked_project(kernel)
        await wait(40)
        frame = kernel.mind.frame()
        s = frame.state("projects")
        works = [r for r in llm.calls if r.role == "project"]
        return s.projects[pid], events(kernel, PLAN_PROPOSED), works, _plan(s, frame)

    p, plans, works, telling = live(tmp_path, scenario)
    [plan] = plans
    assert plan.data.approved and plan.data.tell and p.plan_state == c.PLANNED
    assert "séance de cadrage" in works[0].messages[-1].content or any(
        "séance de cadrage" in m.content for m in works[0].messages)
    kept = [o for o in p.objectives if o.rank]
    assert kept and all(o.done_when_ref for o in kept if o.kind == c.ONCE)
    # le plan se dit (« je m'y mets ») à moins qu'elle ne l'ait déjà dit
    assert p.plan_asked or [x.args["subject"] for x in telling] == [plan_subject(p.id)]


def test_a_plan_with_questions_waits_for_their_answer_then_follows_its_order(tmp_path):
    async def scenario(kernel, llm):
        pid = await _asked_project(kernel)
        framing = _ctx(kernel, "project_plan", Kind.WORK, project_target(pid), subject=frame_subject(pid))
        out = {"plan": await project_plan(PlanArgs.model_validate({
            "aim": "Voir si une IA qui lit l'actualité trade mieux qu'un portefeuille qui dort.",
            "deliverables": "Un tableau de bord dans la console : la courbe de chaque stratégie face au buy and hold.",
            "approach": "Une app relève cours et titres ; je note chaque titre à mes exécutions ; une stratégie suit "
                        "mes notes.",
            "steps": [
                {"text": "Écrire l'app qui relève cours et titres", "done_when": "l'app tourne à l'essai"},
                {"text": "Noter les titres du jour", "kind": "constant", "cadence_hours": 24, "after": 1},
                {"text": "Faire le tableau de bord", "done_when": "la vue s'affiche", "after": 1},
            ],
            "questions": [{"question": "Quelles actions suivre ?", "advice": "les cinq grosses de la tech"}],
        }), framing)}
        frame = kernel.mind.frame()
        s = frame.state("projects")
        out["waiting"] = s.projects[pid]
        out["telling"] = _plan(s, frame)
        yes = await kernel.perceive(said("user_1", "vas-y, ça me va"))
        out["approved"] = await project_steer(SteerArgs(project=str(pid), what="approve"),
                                              _ctx(kernel, "project_steer", Kind.REPLY, "user_1", reply_to=yes.seq))
        out["after"] = kernel.mind.frame().state("projects").projects[pid]
        out["answers"] = events(kernel, PLAN_ANSWERED)
        out["added"] = [e.data for e in events(kernel, OBJECTIVE_ADDED) if e.data.project == pid]
        return pid, out

    pid, out = live(tmp_path, scenario)
    waiting, after = out["waiting"], out["after"]
    assert "attend la réponse" in out["plan"] and waiting.plan_state == c.PROPOSED
    assert pick(waiting, waiting.plan_at, projects_params(None)) is None  # rien ne part avant sa réponse
    assert [x.args["subject"] for x in out["telling"]] == [plan_subject(pid)]  # elle le lui dit
    assert [x.reason for x in out["telling"]] == [c.PLAN]
    # son idée de départ est retirée, les trois étapes du plan la remplacent, chacune à sa place
    idea = next(o for o in after.objectives if not o.rank)
    assert idea.status == c.DROPPED
    app, notes, board = sorted((o for o in after.objectives if o.rank), key=lambda o: o.rank)
    assert notes.kind == c.CONSTANT and notes.after == app.id and board.after == app.id and app.done_when_ref
    assert "C'est parti" in out["approved"] and after.plan_state == c.PLANNED
    assert out["answers"][-1].data.words.text == "vas-y, ça me va"  # ses mots, tels quels
    # dans l'ordre : l'app d'abord — les notes et le tableau attendent qu'elle soit faite
    assert pick(after, after.plan_at + 1, projects_params(None)).id == app.id


def test_a_done_on_an_objective_with_a_criterion_says_how_it_is_met(tmp_path):
    async def scenario(kernel, llm):
        pid = await _asked_project(kernel)
        framing = _ctx(kernel, "project_plan", Kind.WORK, project_target(pid), subject=frame_subject(pid))
        await project_plan(PlanArgs.model_validate({
            "aim": "Un essai.", "deliverables": "Un fichier.", "approach": "Simple.",
            "steps": [{"text": "Écrire le fichier", "done_when": "le fichier existe et se relit"}]}), framing)
        p = kernel.mind.frame().state("projects").projects[pid]
        target = next(o for o in p.objectives if o.rank)
        run = _ctx(kernel, "report_run", Kind.WORK, project_target(pid), subject=f"objective:{pid}:{target.id}")
        silent = await report_run(ReportArgs(verdict="done", summary="Écrit."), run)
        return silent

    silent = live(tmp_path, scenario)
    assert not silent.ok and "le fichier existe et se relit" in silent.content  # elle doit dire comment c'est rempli


def test_a_revision_brings_the_framing_back_with_their_words(tmp_path):
    async def scenario(kernel, llm):
        pid = await _asked_project(kernel)
        framing = _ctx(kernel, "project_plan", Kind.WORK, project_target(pid), subject=frame_subject(pid))
        await project_plan(PlanArgs.model_validate({
            "aim": "Un essai.", "deliverables": "Un tableau.", "approach": "Des règles fixes.",
            "steps": [{"text": "Écrire les règles", "done_when": "elles tournent"}],
            "questions": [{"question": "Des règles fixes, ça te va ?", "advice": "oui, pour commencer"}]}), framing)
        no = await kernel.perceive(said("user_1", "non, je veux que ce soit toi qui décides, avec les actus"))
        said_back = await project_steer(SteerArgs(project=str(pid), what="revise", text="qu'elle décide"),
                                        _ctx(kernel, "project_steer", Kind.REPLY, "user_1", reply_to=no.seq))
        frame = kernel.mind.frame()
        s = frame.state("projects")
        store = kernel.ports["store"]
        p = s.projects[pid]
        return said_back, p, store.content(list(p.instructions)), _run(s, frame)

    said_back, p, texts, candidates = live(tmp_path, scenario)
    assert "reprendras ton plan" in said_back and p.plan_state == c.TO_FRAME
    assert "non, je veux que ce soit toi qui décides, avec les actus" in texts.values()  # ses mots, une consigne
    assert [cand.args["subject"] for cand in candidates] == [frame_subject(p.id)]  # une séance de cadrage, de nouveau


def test_a_project_from_before_gets_a_plan_when_asked_to_revise_it(tmp_path):
    """Un projet d'avant (ou de la console) n'a pas de plan : le revoir lui en donne un, ses mots sous les yeux."""
    from tests.unit.test_projects import create

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le labo", objectives="Relever les cours")
        before = kernel.mind.frame().state("projects").projects[pid].plan_state
        asked = await kernel.perceive(said("user_1", "refais le plan du labo : je veux que tu lises les actus"))
        said_back = await project_steer(SteerArgs(project=str(pid), what="revise", text="lire les actus"),
                                        _ctx(kernel, "project_steer", Kind.REPLY, "user_1", reply_to=asked.seq))
        frame = kernel.mind.frame()
        s = frame.state("projects")
        return before, said_back, s.projects[pid], _run(s, frame)

    before, said_back, p, candidates = live(tmp_path, scenario)
    assert before == c.UNPLANNED and "reprendras ton plan" in said_back and p.plan_state == c.TO_FRAME
    assert [cand.args["subject"] for cand in candidates] == [frame_subject(p.id)]


def test_a_notable_pass_of_a_constant_is_told_like_a_finished_objective(tmp_path):
    async def scenario(kernel, llm):
        pid = await _asked_project(kernel)
        framing = _ctx(kernel, "project_plan", Kind.WORK, project_target(pid), subject=frame_subject(pid))
        await project_plan(PlanArgs.model_validate({
            "aim": "Un suivi.", "deliverables": "Un bilan chaque semaine.", "approach": "Un relevé, un bilan.",
            "steps": [{"text": "Faire le bilan de la semaine", "kind": "constant", "cadence_hours": 168}]}), framing)
        p = kernel.mind.frame().state("projects").projects[pid]
        weekly = next(o for o in p.objectives if o.rank)
        run = _ctx(kernel, "report_run", Kind.WORK, project_target(pid), subject=f"objective:{pid}:{weekly.id}")
        run.calls = (("ws_write", True),)
        run.proofs = (True,)
        await report_run(ReportArgs(verdict="done", summary="Bilan : la stratégie RSI mène.", notable=0.7), run)
        frame = kernel.mind.frame()
        p = frame.state("projects").projects[pid]
        return untold(p, frame.now, projects_params(None)), weekly.id

    told, weekly = live(tmp_path, scenario)
    assert [o.id for o in told] == [weekly]  # le passage du bilan se raconte, comme un ponctuel mené à bout
