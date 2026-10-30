"""De la demande au livrable (ADR 0161) : ce que la relecture du 2026-10-30 a trouvé aux jointures du cadrage.

Une demande se garde comme elle s'est dite (la conversation, qui a dit quoi) ; une promesse de travail ouvre un projet
à cadrer ; ce qu'on lui demande ne bute pas sur son plafond à elle ; une séance de cadrage se conclut par son plan et
ne recommence pas en boucle sans rien dire ; les questions de son plan restent avec leur réponse ; une étape bloquée
se rouvre quand on lui répond ; le premier passage d'un constant attend sa cadence ; le passage d'un constant qui a
regardé du réel se raconte ; un projet où vit une app ne se clôt pas seul ; une boucle qui se conclut par un outil
voit ses derniers tours comptés."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from pydantic import BaseModel

from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects.faculty import (
    PAUSED,
    Objective,
    Project,
    ProjectsState,
    _answered,
    _ended,
    _paused,
    _started,
    frame_subject,
    pick,
)
from mika.faculties.projects.faculty import params as projects_params
from mika.faculties.projects.prompt import _refs, _run_section, job_brief, work_brief
from mika.faculties.projects.tend import finished_at, pause_reason, unframed
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
from mika.faculties.projects.work import _need, _stalled, untold
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.events import Content, Origin
from mika.kernel.faculty import ToolSpec
from mika.kernel.frame import EpisodeRef
from mika.kernel.state import FrozenDict
from mika.ports.llm import LLMRequest, LLMResponse, ToolCall
from mika.runtime.tools import ToolResult, declare, run_tool_loop
from mika.vocab.episodes import Kind, goal_target, project_target
from tests.fixtures.mika import said
from tests.unit.test_projects import events, live
from tests.unit.test_projects_framing import _asked_project, _ctx

PM = projects_params(None)


def _cx(**facts):
    return SimpleNamespace(params=PM, facts=SimpleNamespace(get=lambda key: facts.get(str(key))))


def _ev(at: int, data, correlation: str = "e"):
    return SimpleNamespace(correlation=correlation, at=at, data=data)


# ── La demande ─────────────────────────────────────────────────────────────


def test_the_request_keeps_the_whole_exchange_with_who_said_what(tmp_path):
    """Une demande se précise en plusieurs échanges : « un projet de trading ? » — « lequel ? » — « par IA, pour de
    faux ». Le dernier message seul n'en gardait qu'un bout ; la conversation se garde, ses mots et les siens."""

    async def scenario(kernel, llm):
        first = await kernel.perceive(said("user_1", "tu pourrais me monter un projet de trading ?"))
        if first.reply is not None:
            await first.reply
        second = await kernel.perceive(said("user_1", "par IA, et pour de faux pour l'instant"))
        here = _ctx(kernel, "start_project", Kind.REPLY, "user_1", reply_to=second.seq)
        await start_project(StartArgs(title="Trading fictif", tools=["forge"]), here)
        return events(kernel, c.PROJECT_CREATED)[-1].data.request.text

    request = live(tmp_path, scenario)
    lines = request.split("\n")
    assert lines[0] == "Adrien : tu pourrais me monter un projet de trading ?"
    assert lines[-1] == "Adrien : par IA, et pour de faux pour l'instant"
    assert any(x.startswith("Toi : ") for x in lines[1:-1])  # ce qu'elle lui a répondu entre les deux


def test_a_work_promise_opens_a_framed_project_asked_by_who_received_it(tmp_path):
    """« Je te fais ça » sans rien ouvrir : la promesse devient une exploration, qui ouvrait un projet sans cadrage ni
    demande. Né d'une promesse, il est demandé par qui l'a reçue — à cadrer, avec la conversation où elle l'a dit."""

    async def scenario(kernel, llm):
        asked = await kernel.perceive(said("user_1", "tu me ferais une veille des prix de l'électricité ?"))
        if asked.reply is not None:
            await asked.reply
        adrien = kernel.mind.frame().get(identity_c.PERSON("user_1"))
        commit = await kernel.mind.append([goals_c.GOAL_OPENED.draft(
            kind=goals_c.EXPLORATION, authority=goals_c.SELF, title=Content.of("Ce que j'ai promis à Adrien", level=2),
            details=Content.of("une veille des prix", level=2), owner=adrien, about=(adrien,), max_steps=3,
            source="promise:1", sensitivity=2, desire=0.8, origin=goals_c.FROM_PROMISE,
            origin_at=kernel.mind.clock.now())], emitter="goals", correlation="promesse", origin=Origin.KERNEL)
        gid = commit.seqs[-1]
        step = _ctx(kernel, "start_project", Kind.STEP, goal_target(gid))
        out = await start_project(StartArgs(title="Veille de l'électricité", tools=["forge"]), step)
        return out, events(kernel, c.PROJECT_CREATED)[-1].data, adrien

    out, created, adrien = live(tmp_path, scenario)
    assert "naît à cadrer" in out and created.framing and created.asked_by == adrien
    assert "Adrien : tu me ferais une veille des prix de l'électricité ?" in created.request.text


def test_a_confided_project_can_get_the_forge_when_it_is_asked(tmp_path):
    """« Fais-moi une app » confié par create_project naissait sans la Forge : il prend ses outils avec qui le
    confie."""

    async def scenario(kernel, llm):
        asked = await kernel.perceive(said("user_1", "confie-toi ce projet : une app qui relève la météo"))
        here = _ctx(kernel, "create_project", Kind.REPLY, "user_1", reply_to=asked.seq)
        spec = kernel.mind.registry.tools["create_project"]
        await spec.handler(spec.args(title="Météo", tools=["forge"]), here)
        return events(kernel, c.PROJECT_CREATED)[-1].data

    created = live(tmp_path, scenario)
    assert "forge" in created.bundles and created.framing


# ── La séance de cadrage ───────────────────────────────────────────────────


def test_a_framing_session_is_briefed_to_conclude_with_its_plan():
    """Son brief disait « conclus en appelant report_run », que la séance refuse : il dit son plan."""

    def frame_with(subject: str):
        ep = EpisodeRef("ep", Kind.WORK, target=project_target(7), attrs=FrozenDict({"subject": subject}))
        return SimpleNamespace(episode=ep)

    framing, working = frame_with(frame_subject(7)), frame_with("objective:7:1")
    for brief in (work_brief(framing, None), job_brief(framing, None)):
        assert "project_plan" in brief and "report_run" not in brief
    assert "report_run" in work_brief(working, None)  # une exécution, elle, conclut par son verdict


def test_framing_sessions_without_a_plan_stop_the_project_and_she_says_so():
    """Une séance de cadrage qui n'écrivait pas de plan remettait le compteur de pannes à zéro : elle recommençait
    toutes les dix minutes, vingt-quatre fois par jour, sans rien dire. D'affilée, elles arrêtent le projet, et
    qui l'a demandé l'apprend — même pour un projet qu'on lui a confié."""
    p = Project(id=1, title_ref="t", authority=c.USER, created_at=0, owner="adrien", asked_by="adrien",
                plan_state=c.TO_FRAME)
    s = ProjectsState(projects=FrozenDict({1: p}))
    cx = _cx()
    t = HOUR
    for i in range(PM.silent_before_blocked):
        s = _started(s, _ev(t, rt.EpisodeStarted(kind=Kind.WORK, target=project_target(1), reason=c.RUN,
                                                 subject=frame_subject(1)), f"e{i}"), cx)
        t += 10 * MINUTE
        s = _ended(s, _ev(t, rt.EpisodeEnded(kind=Kind.WORK, outcome="done", target=project_target(1)), f"e{i}"), cx)
    p = s.projects[1]
    assert p.frame_silent == PM.silent_before_blocked and unframed(p, PM) and p.failures == 0
    assert "cadrage sans plan" in pause_reason(p, PM)
    s = _paused(s, _ev(t, PAUSED.payload(project=1, reason=pause_reason(p, PM), broke=True)), cx)
    assert _stalled(s.projects[1], t + MINUTE, PM)  # confié, il se dit quand même : on attend son plan

    known = {identity_c.OWNERS: ("adrien",), identity_c.IS_OWNER("adrien"): True,
             identity_c.HANDLES("adrien"): ("adrien",), identity_c.REACHABLE("adrien"): ("adrien",),
             identity_c.IDENTITY("adrien"): SimpleNamespace(name="Adrien")}
    frame = SimpleNamespace(now=t + MINUTE, root=None, env=SimpleNamespace(params_of=lambda *_: PM),
                            get=lambda key: known.get(key, ()))
    [cand] = _need(s, frame)
    assert cand.args["subject"] == "stalled:1" and "le plan" in cand.args["brief:projects"]


# ── Son plan et sa réponse ─────────────────────────────────────────────────


def test_the_answer_to_her_questions_stays_with_them_in_every_run(tmp_path):
    """Validé, le plan perdait ses questions ; la réponse devenait une consigne nue (« oui pour la 1 »). Elles
    restent ensemble sous ses yeux ; validé sans un mot, ce qu'elle recommandait vaut."""

    async def scenario(kernel, llm):
        pid = await _asked_project(kernel)
        framing = _ctx(kernel, "project_plan", Kind.WORK, project_target(pid), subject=frame_subject(pid))
        await project_plan(PlanArgs.model_validate({
            "aim": "Un labo.", "deliverables": "Une courbe.", "approach": "Une app et mes notes.",
            "steps": [{"text": "Écrire l'app", "done_when": "elle tourne à l'essai"}],
            "questions": [{"question": "Quelles actions suivre ?", "advice": "les cinq grosses de la tech"}]}),
            framing)
        yes = await kernel.perceive(said("user_1", "plutôt des ETF, sinon vas-y"))
        await project_steer(SteerArgs(project=str(pid), what="approve"),
                            _ctx(kernel, "project_steer", Kind.REPLY, "user_1", reply_to=yes.seq))
        frame = kernel.mind.frame()
        s = frame.state("projects")
        p = s.projects[pid]
        target = next(o for o in p.objectives if o.rank)
        run = _ctx(kernel, "report_run", Kind.WORK, project_target(pid), subject=f"objective:{pid}:{target.id}")
        texts = kernel.ports["store"].content(_refs(p))
        return p, _run_section(s, run.frame, {"projects": {"texts": texts}}).content

    p, section = live(tmp_path, scenario)
    assert p.plan_state == c.PLANNED and p.plan_answer_ref and not p.instructions  # pas une consigne nue
    assert "Quelles actions suivre ?" in section and "les cinq grosses de la tech" in section
    assert "plutôt des ETF, sinon vas-y" in section


# ── Le travail ─────────────────────────────────────────────────────────────


def test_a_blocked_step_reopens_when_she_gets_the_answer():
    """Une étape bloquée gelait tout ce qui en dépend : sa réponse ne la rouvrait pas. Elle la rouvre, sa réponse
    sous les yeux de l'exécution qui vient."""
    blocked = Objective(id=1, text_ref="a", status=c.BLOCKED, runs=12, silent=0, asked=True, asked_at=HOUR,
                        asked_to="adrien", need_ref="n", closed_at=HOUR - MINUTE)
    waiting = Objective(id=2, text_ref="b", after=1, rank=2)
    p = Project(id=1, title_ref="t", authority=c.SELF, created_at=0, plan_state=c.PLANNED,
                objectives=(blocked, waiting))
    s = ProjectsState(projects=FrozenDict({1: p}))
    assert pick(p, 2 * HOUR, PM) is None  # rien ne part : l'étape 2 attend la 1, bloquée
    from mika.faculties.projects.faculty import ANSWERED
    s = _answered(s, _ev(2 * HOUR, ANSWERED.payload(project=1, objective=1, person="adrien")), _cx())
    again = s.projects[1].objectives[0]
    assert again.status == c.OPEN and again.runs == 0 and again.answered_at == 2 * HOUR and again.need_ref == "n"
    assert pick(s.projects[1], 2 * HOUR, PM).id == 1


def test_a_constant_first_pass_waits_its_cadence_after_it_can_start():
    """Un bilan de la semaine qui dépend de l'app tombait le jour même où l'app était écrite, avant les étapes qui
    restaient : son premier passage vient une cadence après qu'il a pu commencer."""
    app = Objective(id=1, text_ref="app", status=c.DONE, closed_at=DAY, rank=1)
    views = Objective(id=2, text_ref="vues", after=1, rank=2)
    weekly = Objective(id=3, text_ref="bilan", kind=c.CONSTANT, cadence_us=7 * DAY, after=1, rank=3)
    p = Project(id=1, title_ref="t", authority=c.SELF, created_at=0, plan_state=c.PLANNED,
                objectives=(app, views, weekly))
    assert pick(p, DAY + MINUTE, PM).id == 2  # les vues d'abord
    done = replace(p, objectives=(app, replace(views, status=c.DONE), weekly))
    assert pick(done, 2 * DAY, PM) is None and pick(done, 8 * DAY, PM).id == 3


def test_a_kept_idea_of_the_person_keeps_its_place_in_the_plan():
    """Une idée de départ gardée par le plan passait devant ses autres étapes, quel que soit son rang."""
    first = Objective(id=2, text_ref="chercher", author="self", rank=1)
    kept = Objective(id=1, text_ref="l'idée d'Adrien", author="owner", rank=2)
    added = Objective(id=3, text_ref="ajouté par Adrien ensuite", author="owner")
    p = Project(id=1, title_ref="t", authority=c.USER, created_at=0, plan_state=c.PLANNED, objectives=(kept, first))
    assert pick(p, HOUR, PM).id == 2
    assert pick(replace(p, objectives=(kept, first, added)), HOUR, PM).id == 3  # hors plan, demandé : d'abord


def test_a_constant_pass_that_looked_at_something_real_is_told(tmp_path):
    """Un bilan qui lit la base de l'app et se résume dans son compte rendu n'écrivait rien : jamais « prouvé »,
    jamais raconté. Ce qu'il a regardé de réel suffit ; un passage qui n'a fait que tenir son carnet, non."""

    async def scenario(kernel, llm):
        pid = await _asked_project(kernel)
        framing = _ctx(kernel, "project_plan", Kind.WORK, project_target(pid), subject=frame_subject(pid))
        await project_plan(PlanArgs.model_validate({
            "aim": "Un suivi.", "deliverables": "Un bilan chaque semaine.", "approach": "Lire la base de l'app.",
            "steps": [{"text": "Faire le bilan de la semaine", "kind": "constant", "cadence_hours": 168}]}), framing)
        p = kernel.mind.frame().state("projects").projects[pid]
        weekly = next(o for o in p.objectives if o.rank)
        subject = f"objective:{pid}:{weekly.id}"
        idle = _ctx(kernel, "report_run", Kind.WORK, project_target(pid), subject=subject)
        idle.calls = (("project_note", True),)
        said_idle = await report_run(ReportArgs(verdict="done", summary="Rien à dire.", notable=0.7), idle)
        frame = kernel.mind.frame()
        before = untold(frame.state("projects").projects[pid], frame.now, PM)
        looked = _ctx(kernel, "report_run", Kind.WORK, project_target(pid), subject=subject)
        looked.calls = (("forge_db_query", True),)
        await report_run(ReportArgs(verdict="done", summary="Bilan : la stratégie RSI mène.", notable=0.7), looked)
        frame = kernel.mind.frame()
        return said_idle, before, untold(frame.state("projects").projects[pid], frame.now, PM), weekly.id

    said_idle, before, after, weekly = live(tmp_path, scenario)
    assert "ne se racontera pas" in said_idle and before == []
    assert [o.id for o in after] == [weekly]


def test_a_project_where_an_app_lives_is_not_closed_on_its_own():
    """Un projet à elle sans constant se close trois jours après sa dernière étape : son app tournait encore, sans
    plus personne pour la réparer. Une app qui vit dans le projet le garde ouvert."""
    done = Objective(id=1, text_ref="app", status=c.DONE, closed_at=DAY)
    p = Project(id=4, title_ref="t", authority=c.SELF, created_at=0, objectives=(done,))
    assert finished_at(p, PM) == DAY + PM.self_done_after_us
    assert finished_at(p, PM, frozenset({4})) is None


# ── La boucle d'outils ─────────────────────────────────────────────────────


class _Args(BaseModel):
    q: str = ""


class _Replies:
    def __init__(self, *outs: LLMResponse) -> None:
        self.outs, self.seen = list(outs), []

    async def call(self, req: LLMRequest) -> LLMResponse:
        self.seen.append(req)
        return self.outs.pop(0)


async def test_a_loop_that_ends_with_a_tool_counts_its_last_turns():
    """Au plafond de tours, le dernier tour n'a plus d'outil : une exécution qui n'avait pas conclu finissait sans
    verdict. Une boucle qui se conclut par un outil voit ses derniers tours comptés ; une autre, rien."""

    async def look(args: _Args, ctx) -> ToolResult:
        return ToolResult(content="vu")

    async def conclude(args: _Args, ctx) -> ToolResult:
        return ToolResult(content="noté")

    def spec(name, handler, **kw) -> ToolSpec:
        return ToolSpec(owner="x", name=name, description="…", args=_Args, handler=handler, bundle="x",
                        episodes=frozenset({"WORK"}), **kw)

    tools = {"look": spec("look", look), "report": spec("report", conclude, ends_loop=True)}
    calling = [LLMResponse("", (ToolCall(f"t{i}", "look", {}),), stop="tool_use") for i in range(4)]
    gw = _Replies(*calling, LLMResponse("", (ToolCall("r", "report", {}),), stop="tool_use"))
    req = LLMRequest(role="project", call_id="c#0", system_stable="s", tools=declare(list(tools.values())))
    loop = await run_tool_loop(gw, req, tools, lambda s, i: SimpleNamespace(call_id=i), max_turns=5)
    assert loop.stop == "tool_end"
    seen = [m.content for m in gw.seen[-1].messages if m.role == "tool"]
    assert "vu" == seen[0] and "Il te reste 3 tours" in seen[1] and "Il te reste 2 tours" in seen[2]
    assert "prochain tour est le dernier" in seen[3]

    plain = {"look": spec("look", look)}
    gw = _Replies(*[LLMResponse("", (ToolCall(f"t{i}", "look", {}),), stop="tool_use") for i in range(2)],
                  LLMResponse("fini"))
    await run_tool_loop(gw, req, plain, lambda s, i: SimpleNamespace(call_id=i), max_turns=3)
    assert all("Il te reste" not in m.content for m in gw.seen[-1].messages if m.role == "tool")


async def test_a_tool_can_end_the_loop_on_one_call_only():
    """Le plan conclut une séance de cadrage, pas une exécution qui le revoit : un outil dit qu'il conclut, par son
    résultat."""

    async def plan(args: _Args, ctx) -> ToolResult:
        return ToolResult(content="écrit", ends=args.q == "cadrage")

    spec = ToolSpec(owner="x", name="plan", description="…", args=_Args, handler=plan, bundle="x",
                    episodes=frozenset({"WORK"}))
    gw = _Replies(LLMResponse("", (ToolCall("p", "plan", {"q": "cadrage"}),), stop="tool_use"))
    req = LLMRequest(role="project", call_id="c#1", system_stable="s", tools=declare([spec]))
    loop = await run_tool_loop(gw, req, {"plan": spec}, lambda s, i: SimpleNamespace(call_id=i), max_turns=4)
    assert loop.stop == "tool_end" and len(gw.seen) == 1


# ── Ce que la personne voit ────────────────────────────────────────────────


def test_the_story_links_the_views_of_apps_that_work_and_only_for_who_has_the_console():
    """Le récit renvoyait vers « la console, sur leur fiche » sans lien, pour toute app, même sans vue ou en
    panne, et même à qui n'a pas la console."""
    from mika.contracts import forge as forge_c
    from mika.faculties.projects.prompt import _apps_where
    from mika.kernel.frame import Audience

    def app(name, views=("Relevés",), broken=""):
        return forge_c.AppView(name, name.title(), 1, True, broken, 0, False, False, "manual", project=3,
                               views=views)

    apps = (app("cours"), app("muette", views=()), app("cassee", broken="HTTP 503"))
    p = Project(id=3, title_ref="t", authority=c.SELF, created_at=0)

    def told(owner: bool) -> str:
        frame = SimpleNamespace(audience=Audience(owner=owner), get=lambda key: apps if key == forge_c.APPS else ())
        return _apps_where(p, frame)

    mine = told(True)
    assert "/inspecteur/fiche/app/cours?onglet=vues" in mine and "Muette" not in mine and "Cassee" not in mine
    other = told(False)
    assert "« Cours »" in other and "/inspecteur" not in other and "pas ouverte" in other


def test_her_app_settings_say_what_is_in_force_and_never_a_secret():
    """Elle changeait un défaut du manifeste sans effet, une valeur de la console l'emportant ; une clé manquante
    restait muette."""
    from mika.plugins.forge import App, settings_lines
    from mika.ports.forge import form_field

    info = SimpleNamespace(config_fields=(form_field("ville", "text", "Ville", default="Paris"),
                                          form_field("seuil", "float", "Seuil", default=1.0),
                                          form_field("cle", "secret", "Clé"), form_field("jeton", "secret", "Jeton")))
    ctx = SimpleNamespace(ports={"forge_settings": SimpleNamespace(values=lambda n: {"ville": "Lyon", "cle": "s3cr3t"})},
                          frame=SimpleNamespace(state=lambda owner: SimpleNamespace(
                              apps={"meteo": App("Météo", 1, trusted="")})))
    lines = "\n".join(settings_lines(ctx, "meteo", info))
    assert "ville : Lyon (réglé dans la console" in lines and "seuil : 1.0 (le défaut" in lines
    assert "s3cr3t" not in lines and "cle : secret défini" in lines and "pas encore validée" in lines
    assert "jeton : secret non défini" in lines
