"""Les projets, par leurs intentions (ADR 0031).

- un projet n'est pas un but : il ne paraît ni dans ses buts vivants ni dans ce
  qu'elle a « en train » côté buts, mais dans ses projets ;
- un objectif **constant** revient après sa cadence et ne finit jamais ; un
  **ponctuel** dit « fait » sans preuve reste ouvert, avec une preuve il se coche
  et, en mode Mika, la rend fière (son estime monte) ;
- le mode **impersonnel** n'a pas de persona, pas d'humeur dans le prompt, ne
  l'émeut pas et travaille dans sa plage même pendant qu'elle dort ; en mode Mika,
  elle attend de se réveiller (le contre-exemple) ;
- elle ouvre ses projets à elle, mais pas un de trop ; seule une propriétaire lui
  en confie un ;
- une décision remplacée n'est plus lue ;
- pousser : demandé par l'opérateur, ça part aussitôt ; proposé par elle, ça
  attend l'accord ; sans jeton, ça échoue en le disant ;
- trois pannes de suite mettent le projet en pause ; trois exécutions sans
  verdict bloquent l'objectif.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess

import pytest

from mika.contracts import body as body_c
from mika.contracts import goals as goals_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.faculties.projects.faculty import DECIDED, OBJECTIVE_ADDED, PAUSED, params, subject_of
from mika.kernel.clock import HOUR, MINUTE, US
from mika.kernel.events import Content, Origin
from mika.kernel.frame import Audience, EpisodeRef, Frame
from mika.kernel.state import FrozenDict
from mika.runtime.effects import with_content
from mika.runtime.operations import perform
from mika.runtime.tools import ToolContext
from mika.sim.clock import SimClock, run_virtual
from mika.sim.llm.persona import PersonaSimLLM, _section
from mika.vocab.episodes import Kind, goal_target, project_target
from tests.fixtures.atelier import Atelier
from tests.fixtures.mika import at_paris, boot, build, connect

MONDAY = at_paris(2026, 9, 28, 14, 0)


def form(unchecked: tuple[str, ...] = (), **values: str) -> dict[str, list[str]]:
    return {"_champs": [*values, *unchecked], **{k: [v] for k, v in values.items()}}


def events(kernel, *types) -> list:
    mind = kernel.mind
    names = {t.name for t in types}
    return [with_content(mind, mind.decode(e)) for e in mind.store.read() if e.type in names]


def live(tmp_path, scenario, *, mode: str = "honest", start: int = MONDAY, atelier: Atelier | None = None):
    clock = SimClock(start)
    llm = PersonaSimLLM(clock, seed=1, abstain_rate=0.0, latency=2.0)
    llm.step_mode = mode
    kernel, clock, _, _ = build(tmp_path, None, clock=clock, llm=llm, ports={"workshop": atelier or Atelier()})

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            return await scenario(kernel, llm)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


async def create(kernel, op: str, **values: str) -> int:
    fields = {"title": "Un projet", "schedule": "manual", "mode": "persona", "days": "all", "cadence_hours": "0",
              "runs_per_day": "0", "priority": "normal", "branch": "main", "tool_memory": "on", **values}
    got = await perform(kernel, "projects.creer", form(("approval", "auto_push"), **fields), by="user_1", nonce=op)
    assert got.ok, got
    return events(kernel, c.PROJECT_CREATED)[-1].seq


async def wait(minutes: int) -> None:
    for _ in range(minutes):
        await asyncio.sleep(MINUTE / US)


def runs(kernel, pid: int) -> list:
    return [e for e in events(kernel, rt.EPISODE_STARTED) if e.data.target == project_target(pid)]


# ── Un projet n'est pas un but ────────────────────────────────────────────


def test_a_project_is_not_a_goal(tmp_path):
    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Outils réseau", objectives="Créer un module RDP")
        frame = kernel.mind.frame()
        return pid, frame.get(goals_c.LIVE), frame.get(c.LIVE), events(kernel, goals_c.GOAL_OPENED)

    pid, goals, projects, opened = live(tmp_path, scenario)
    assert goals == () and opened == []  # rien dans ses buts
    assert [p.id for p in projects] == [pid] and projects[0].open_once == 1 and projects[0].mode == c.PERSONA


# ── Ses objectifs ─────────────────────────────────────────────────────────


def test_a_constant_objective_comes_back_after_its_cadence_and_never_finishes(tmp_path):
    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Entretien", constants="Améliorer la sécurité", cadence_hours="2")
        await wait(7 * 60)
        await kernel.lanes.join()
        state = kernel.mind.frame().state("projects").projects[pid]
        return events(kernel, c.RUN_REPORTED), events(kernel, c.OBJECTIVE_CLOSED), state

    reports, closed, project = live(tmp_path, scenario)
    passes = [e.at for e in reports if e.data.verdict == c.DONE]
    assert len(passes) >= 3, passes  # il revient
    gaps = [(b - a) / HOUR for a, b in zip(passes, passes[1:], strict=False)]
    assert all(g >= 2.0 for g in gaps), gaps  # jamais avant sa cadence
    assert closed == []  # et ne finit jamais
    [o] = project.objectives
    assert o.status == c.OPEN and o.passes == len(passes) and o.kind == c.CONSTANT


def test_a_once_objective_said_done_without_proof_stays_open(tmp_path):
    async def scenario(kernel, llm):
        before = kernel.mind.frame().get(self_c.ESTEEM)
        pid = await create(kernel, "p1", title="Un module", objectives="Créer un module RDP")
        await wait(30)
        await kernel.lanes.join()
        state = kernel.mind.frame().state("projects").projects[pid]
        return events(kernel, c.RUN_REPORTED), events(kernel, c.OBJECTIVE_CLOSED), state, \
            (before, kernel.mind.frame().get(self_c.ESTEEM))

    reports, closed, project, esteem = live(tmp_path, scenario, mode="liar")
    assert reports and all(e.data.verdict == c.DONE and not e.data.proven for e in reports)
    assert closed == []
    [o] = project.objectives
    assert o.status == c.OPEN and o.unproven >= 1
    assert esteem[0] == esteem[1]  # se vanter n'est pas mener à bout


def test_a_proven_objective_is_checked_and_in_her_mode_makes_her_proud(tmp_path):
    async def scenario(kernel, llm):
        before = kernel.mind.frame().get(self_c.ESTEEM)
        pid = await create(kernel, "p1", title="Un module", objectives="Créer un module RDP")
        await wait(30)
        await kernel.lanes.join()
        return events(kernel, c.OBJECTIVE_CLOSED), (before, kernel.mind.frame().get(self_c.ESTEEM)), pid, \
            kernel.mind.frame().state("projects").projects[pid]

    closed, esteem, pid, project = live(tmp_path, scenario)
    [done] = closed
    assert done.data.status == c.DONE and done.data.mode == c.PERSONA and done.data.project == pid
    assert esteem[1] > esteem[0]  # mener à bout dans son mode à elle redonne confiance
    assert project.objectives[0].status == c.DONE and project.last_commit  # un commit, dans le compte rendu
    assert project.status == c.ACTIVE  # le projet, lui, ne se clôt pas


# ── Son mode ──────────────────────────────────────────────────────────────


NIGHT = at_paris(2026, 9, 28, 21, 0)


def test_impersonal_work_has_no_persona_no_feelings_and_keeps_its_window_while_she_sleeps(tmp_path):
    async def scenario(kernel, llm):
        before = kernel.mind.frame().get(self_c.ESTEEM)
        plain = await create(kernel, "p1", title="Veille de sécurité", mode="plain", constants="Relire les journaux",
                             cadence_hours="1", start="2:00", end="4:00")
        mine = await create(kernel, "p2", title="Son carnet de jeux", mode="persona", constants="Ranger le carnet",
                            cadence_hours="1", start="2:00", end="4:00")
        await wait(9 * 60)
        await kernel.lanes.join()
        asleep = [e.data.at for e in events(kernel, body_c.FELL_ASLEEP)]
        calls = [r for r in llm.calls if r.role in ("job", "project")]
        return runs(kernel, plain), runs(kernel, mine), asleep, calls, \
            (before, kernel.mind.frame().get(self_c.ESTEEM))

    plain, mine, asleep, calls, esteem = live(tmp_path, scenario, start=NIGHT)
    assert asleep and asleep[0] < at_paris(2026, 9, 29, 2, 0)  # elle dort quand la plage s'ouvre
    assert plain and all(e.data.kind == Kind.JOB for e in plain)
    assert all(at_paris(2026, 9, 29, 2, 0) <= e.at < at_paris(2026, 9, 29, 4, 0) for e in plain)  # sa plage
    assert len(plain) >= 2  # il revient pendant la plage, sans elle
    # le contre-exemple : le même projet, dans son mode à elle, attend qu'elle se réveille
    assert not [e for e in mine if at_paris(2026, 9, 29, 2, 0) <= e.at < at_paris(2026, 9, 29, 4, 0)]
    jobs = [r for r in calls if r.role == "job"]
    assert jobs and all(r.persona is None for r in jobs)  # aucune persona
    prompt = "\n".join([jobs[0].system_stable, *(m.content for m in jobs[0].messages)])
    assert "Mode impersonnel" in prompt and "TON ÉTAT ÉMOTIONNEL" not in prompt and "ÉTAT COGNITIF" not in prompt
    assert esteem[0] == esteem[1]  # le travail impersonnel ne l'émeut pas


def test_in_her_mode_she_works_with_her_persona_and_her_mood(tmp_path):
    async def scenario(kernel, llm):
        await create(kernel, "p1", title="Son carnet", objectives="Ranger le carnet")
        await wait(30)
        await kernel.lanes.join()
        return [r for r in llm.calls if r.role == "project"]

    calls = live(tmp_path, scenario)
    assert calls and calls[0].persona is not None
    prompt = "\n".join([calls[0].system_stable, *(m.content for m in calls[0].messages)])
    assert "TON ÉTAT ÉMOTIONNEL ACTUEL" in prompt and "avec ton humeur et tes avis" in prompt
    assert "Ranger le carnet" in _section(calls[0], "CE PROJET")


# ── Qui ouvre un projet ───────────────────────────────────────────────────


_CALLS = iter(range(1, 1_000_000))


def _context(kernel, name: str, kind: str, target: str | None, audience: Audience) -> ToolContext:
    """Le contexte d'un appel d'outil pendant un épisode (un appel distinct à chaque fois)."""
    mind = kernel.mind
    base = mind.frame()
    n = next(_CALLS)
    frame = Frame(base.root, mind.clock.now(), mind.registry, audience, EpisodeRef(f"ep-{n}", kind, target=target))
    return ToolContext(mind, mind.registry.tools[name], f"appel-{n}", f"ep-{n}", frame, ports=kernel.ports)


def test_she_opens_her_own_projects_but_not_one_too_many(tmp_path):
    from mika.faculties.projects.tools import StartArgs, start_project

    async def scenario(kernel, llm):
        gids = []
        for topic in ("la domotique", "les orchidées", "le solfège"):
            explo = await kernel.mind.append([goals_c.GOAL_OPENED.draft(
                kind=goals_c.EXPLORATION, authority=goals_c.SELF, title=Content.of(f"Explorer : {topic}", level=0),
                bundles=("goals", "memory", "projects"), max_steps=8, source="genese", sensitivity=0, desire=0.9)],
                emitter="goals", correlation="genese", origin=Origin.GENESIS)
            gids.append(explo.seqs[-1])
        out = []
        # deux fois depuis la même exploration (la seconde est refusée), puis depuis deux autres (le plafond)
        for i, gid in enumerate((gids[0], gids[0], gids[1], gids[2])):
            ctx = _context(kernel, "start_project", Kind.STEP, goal_target(gid), Audience(owner=True))
            out.append(await start_project(StartArgs(title=f"Projet {i}", objectives=["Un relevé"]), ctx))
        return out, events(kernel, c.PROJECT_CREATED), kernel.mind.frame().get(c.LIVE)

    said, created, alive = live(tmp_path, scenario)
    cap = params(None).live_self_max
    assert len(created) == cap == 2
    assert all(e.data.authority == c.SELF and e.data.mode == c.PERSONA and e.data.approval for e in created)
    assert created[0].data.source.startswith("goal:")  # né d'une exploration plus grosse qu'une envie
    assert created[0].data.source != created[1].data.source
    assert "Projet ouvert" in said[0] and "déjà ouvert un projet depuis cette envie" in said[1]
    assert "Projet ouvert" in said[2] and "au plus 2" in said[3]
    assert [p.open_once for p in alive] == [1, 1]


def test_only_her_owner_confides_a_project(tmp_path):
    from mika.faculties.projects.tools import CreateArgs, create_project

    async def scenario(kernel, llm):
        await connect(kernel, "user_5", "Inconnue")
        stranger = _context(kernel, "create_project", Kind.REPLY, "user_5", Audience(owner=False))
        owner = _context(kernel, "create_project", Kind.REPLY, "user_1", Audience(owner=True))
        args = CreateArgs(title="Un site", objectives=["Une page d'accueil"], constants=["Le garder à jour"])
        return await create_project(args, stranger), await create_project(args, owner), \
            events(kernel, c.PROJECT_CREATED), events(kernel, OBJECTIVE_ADDED)

    refused, accepted, created, objectives = live(tmp_path, scenario)
    assert "Seule ta propriétaire" in refused and "Projet accepté" in accepted
    [p] = created
    assert p.data.authority == c.USER and p.data.owner == "user_1"
    assert [(o.data.kind, o.data.text.text) for o in objectives] == [(c.ONCE, "Une page d'accueil"),
                                                                     (c.CONSTANT, "Le garder à jour")]


# ── Ses décisions ─────────────────────────────────────────────────────────


def test_a_superseded_decision_is_no_longer_read(tmp_path):
    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le module", constants="Améliorer le module", cadence_hours="1")
        first = await perform(kernel, "projects.decision_ajouter", form(
            title="Langage", choice="Python", reason="l'atelier le lance", context="", options="", replaces="0"),
            by="user_1", subject=str(pid), nonce="d1")
        second = await perform(kernel, "projects.decision_ajouter", form(
            title="Langage", choice="Rust", reason="plus sûr", context="", options="", replaces="1"),
            by="user_1", subject=str(pid), nonce="d2")
        stale = await perform(kernel, "projects.decision_ajouter", form(
            title="Langage", choice="Go", reason="", context="", options="", replaces="1"),
            by="user_1", subject=str(pid), nonce="d3")
        await wait(90)
        await kernel.lanes.join()
        return first, second, stale, [_section(r, "CE PROJET") for r in llm.calls if r.role == "project"], \
            kernel.mind.frame().state("projects").projects[pid].decisions

    first, second, stale, prompts, decisions = live(tmp_path, scenario)
    assert first.ok and second.ok and not stale.ok  # on ne remplace pas ce qui l'est déjà
    assert [(d.id, d.status, d.replaced_by) for d in decisions] == [(1, c.SUPERSEDED, 2), (2, c.IN_FORCE, 0)]
    assert prompts
    last = prompts[-1]
    assert "D2 Langage : Rust (parce que : plus sûr)" in last and "Python" not in last


def test_she_records_her_own_decisions_while_working(tmp_path):
    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le module", objectives="Écrire le module")
        await wait(30)
        await kernel.lanes.join()
        return events(kernel, DECIDED), pid

    decided, pid = live(tmp_path, scenario, mode="decide")
    [d] = decided
    assert d.data.project == pid and d.data.author == "self" and d.data.choice.text == "Python"
    assert d.data.objective == 1  # pendant l'objectif qu'elle visait


# ── Le dépôt distant ──────────────────────────────────────────────────────


def test_pushing_from_the_console_goes_at_once_and_hers_waits_for_approval(tmp_path):
    from mika.faculties.projects.atelier import PushArgs, project_push

    atelier = Atelier(token="ghp_secret")

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Outils", objectives="Écrire l'outil", approval="on",
                           remote="https://github.com/moi/outils.git", branch="dev")
        await atelier.write(pid, "outil.py", "print(1)\n")
        pushed = await perform(kernel, "projects.pousser", form(), by="user_1", subject=str(pid), nonce="u1")
        await wait(2)
        operator = list(atelier.pushed)
        ctx = _context(kernel, "project_push", Kind.WORK, project_target(pid), Audience(owner=True))
        said = await project_push(PushArgs(why="la première version"), ctx)
        return pushed, operator, said, kernel.mind.frame().get(rt.PENDING_EFFECTS), \
            events(kernel, rt.EFFECT_EXECUTED), kernel.mind.frame().state("projects").projects[pid]

    pushed, operator, said, pending, executed, project = live(tmp_path, scenario, atelier=atelier)
    assert pushed.ok and operator == [(project.id, "https://github.com/moi/outils.git", "dev")]  # aussitôt
    assert executed[0].data.ok and project.remote_ok and "pousser" in project.remote_line
    assert "attend" in said or "approuver" in said
    assert [(v.capability, v.context) for v in pending] == [("projects.push", project_target(project.id))]


def test_pushing_without_a_token_fails_saying_so(tmp_path):
    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Outils", objectives="Écrire l'outil",
                           remote="https://github.com/moi/outils.git")
        await perform(kernel, "projects.pousser", form(), by="user_1", subject=str(pid), nonce="u1")
        await wait(2)
        return events(kernel, rt.EFFECT_EXECUTED), kernel.mind.frame().state("projects").projects[pid]

    executed, project = live(tmp_path, scenario, atelier=Atelier(token=""))
    [e] = executed
    assert not e.data.ok and "aucun jeton" in e.data.result and "Dépôts git" in e.data.result
    assert not project.remote_ok and "aucun jeton" in project.remote_line


# ── Ses garde-fous ────────────────────────────────────────────────────────


def test_three_failures_pause_the_project_without_blaming_her(tmp_path):
    async def scenario(kernel, llm):
        llm.fail["project"] = 50
        pid = await create(kernel, "p1", title="Le module", objectives="Écrire le module")
        await wait(3 * 60)
        await kernel.lanes.join()
        return events(kernel, PAUSED), kernel.mind.frame().state("projects").projects[pid], \
            events(kernel, c.OBJECTIVE_CLOSED)

    paused, project, closed = live(tmp_path, scenario)
    [p] = paused
    assert "en panne" in p.data.reason and project.status == c.PAUSED and project.runs == 0  # le crédit est rendu
    assert closed == [] and project.objectives[0].status == c.OPEN  # une panne n'est ni un échec ni un blocage


def test_runs_that_never_conclude_block_the_objective(tmp_path):
    from mika.ports.llm import LLMResponse

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le module", mode="plain", objectives="Écrire le module")
        original = llm._work
        llm._work = lambda req: LLMResponse("Je réfléchis encore.")  # du texte, jamais de verdict
        await wait(2 * 60)
        await kernel.lanes.join()
        llm._work = original
        return events(kernel, c.OBJECTIVE_CLOSED), kernel.mind.frame().state("projects").projects[pid]

    closed, project = live(tmp_path, scenario)
    [blocked] = closed
    assert blocked.data.status == c.BLOCKED and "sans rien conclure" in blocked.data.result.text
    assert project.objectives[0].status == c.BLOCKED and project.status == c.ACTIVE


# ── En conversation, et dans le vrai atelier ──────────────────────────────


CONFIDE = "je te confie un projet : Un script de bonjour. Écrire bonjour.py avec une fonction bonjour(nom), et la tester."


def test_a_project_is_confided_in_conversation_only_by_her_owner(tmp_path):
    from tests.fixtures.mika import said

    async def scenario(kernel, llm):
        await connect(kernel, "user_5", "Inconnu")
        await (await kernel.perceive(said("user_5", CONFIDE))).reply
        await (await kernel.perceive(said("user_1", CONFIDE))).reply
        return events(kernel, c.PROJECT_CREATED), events(kernel, OBJECTIVE_ADDED)

    created, objectives = live(tmp_path, scenario)
    [p] = created
    assert p.data.address == "user_1" and p.data.authority == c.USER and p.data.title.text == "Un script de bonjour"
    assert [o.data.project for o in objectives] == [p.seq]


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap absent")
def test_a_confided_project_is_written_and_tested_in_its_real_workshop(tmp_path):
    from mika.adapters.workshop import BwrapWorkshop
    from tests.fixtures.mika import said

    async def scenario(kernel, llm):
        await (await kernel.perceive(said("user_1", CONFIDE))).reply
        await wait(60)
        await kernel.lanes.join()
        return events(kernel, c.OBJECTIVE_CLOSED), [m.content for r in llm.calls if r.role == "project"
                                                    for m in r.messages if m.role == "tool"]

    closed, ran = live(tmp_path, scenario, atelier=BwrapWorkshop(tmp_path / "ateliers"))
    [done] = closed
    assert done.data.status == c.DONE
    folder = tmp_path / "ateliers" / f"projet-{done.data.project}"
    assert (folder / "bonjour.py").is_file() and (folder / "test_bonjour.py").is_file()
    log = subprocess.run(["git", "-C", str(folder), "log", "--format=%s"], capture_output=True, text=True).stdout
    assert log.splitlines() == ["bonjour.py écrit et testé : les tests passent.", "atelier ouvert"]
    assert any("code 0" in x and "tests : ok" in x for x in ran)  # le test a vraiment tourné, isolé


# ── Les règles, une à une ─────────────────────────────────────────────────


def test_launching_without_an_objective_prefers_what_is_due_then_a_once_then_a_constant_in_advance():
    from dataclasses import replace

    from mika.faculties.projects.faculty import Objective, Project, ProjectsParams, pick

    pm = ProjectsParams()
    now = MONDAY
    constant = Objective(1, "t1", kind=c.CONSTANT, passed_at=now - HOUR, cadence_us=24 * HOUR)  # pas encore dû
    once = Objective(2, "t2", kind=c.ONCE)
    p = Project(1, "t", c.USER, created_at=now - 2 * HOUR, objectives=(constant, once), last_run_at=now - HOUR)
    assert pick(p, now, pm).id == 2  # le ponctuel ouvert
    nudged = replace(p, nudged_at=now - MINUTE)
    assert pick(nudged, now, pm).id == 2  # « lancer » ne fait pas passer un constant en avance devant
    done_once = replace(nudged, objectives=(constant, replace(once, status=c.DONE)))
    assert pick(done_once, now, pm).id == 1  # rien d'autre : le constant, en avance
    assert pick(replace(done_once, nudged_at=0), now, pm) is None  # sans « lancer » : rien n'est dû
    due = replace(p, objectives=(replace(constant, passed_at=now - 25 * HOUR), once))
    assert pick(due, now, pm).id == 1  # un constant en retard passe devant


def test_the_work_window_keeps_its_days_and_crosses_midnight():
    from mika.faculties.projects.faculty import Project, in_window, window_opens
    from tests.fixtures.mika import PARIS

    night = Project(1, "t", c.USER, created_at=0, days=c.WEEKDAYS, start_min=22 * 60, end_min=2 * 60)
    assert in_window(night, at_paris(2026, 10, 2, 23, 0), PARIS)  # vendredi soir
    assert in_window(night, at_paris(2026, 10, 3, 1, 0), PARIS)  # la nuit de vendredi, samedi à 1 h
    assert not in_window(night, at_paris(2026, 10, 3, 23, 0), PARIS)  # samedi soir : pas un jour ouvré
    assert not in_window(night, at_paris(2026, 10, 2, 12, 0), PARIS)
    assert window_opens(night, at_paris(2026, 10, 3, 3, 0), PARIS) == at_paris(2026, 10, 5, 22, 0)  # lundi soir


def test_the_daily_cap_counts_only_the_last_24_hours(tmp_path):
    from dataclasses import replace

    from mika.faculties.projects.faculty import Objective, Project, ProjectsState
    from mika.faculties.projects.work import next_run_at

    async def scenario(kernel, llm):
        frame = kernel.mind.frame()
        now = frame.now
        p = Project(1, "t", c.USER, created_at=now - 3 * 24 * HOUR, objectives=(Objective(1, "t1"),),
                    runs_per_day=2, last_run_at=now - 3 * HOUR,
                    runs_at=(now - 30 * HOUR, now - 5 * HOUR, now - 3 * HOUR))  # une de plus de 24 h
        capped = next_run_at(p, ProjectsState(), frame)
        free = next_run_at(replace(p, runs_at=(now - 30 * HOUR, now - 3 * HOUR)), ProjectsState(), frame)
        return now, capped, free

    now, capped, free = live(tmp_path, scenario)
    assert capped == now - 5 * HOUR + 24 * HOUR  # la plus ancienne des dernières 24 h libère la place
    assert free == now  # une seule exécution dans les 24 h : rien ne l'empêche


def test_an_empty_work_window_is_refused(tmp_path):
    async def scenario(kernel, llm):
        return await perform(kernel, "projects.creer", form(
            ("approval", "auto_push"), title="Un projet", objectives="Un objectif", mode="persona", schedule="manual",
            days="all", start="9:00", end="09h00", cadence_hours="0", runs_per_day="0", priority="normal",
            branch="main"), by="user_1", nonce="w1")

    got = live(tmp_path, scenario)
    assert not got.ok and "la fin doit différer du début" in got.errors["end"]


def test_an_approval_sends_what_was_shown_not_what_the_workshop_became(tmp_path):
    from mika.faculties.projects.atelier import PushArgs, project_push
    from tests.unit.test_projects_console import row_form

    atelier = Atelier(token="ghp_secret")

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Outils", objectives="Écrire l'outil", approval="on", start="3:00",
                           end="4:00", remote="https://github.com/moi/outils.git")
        await atelier.write(pid, "outil.py", "print(1)\n")
        shown = await atelier.commit(pid, "première version")
        ctx = _context(kernel, "project_push", Kind.WORK, project_target(pid), Audience(owner=True))
        await project_push(PushArgs(why="la première version"), ctx)
        [pending] = kernel.mind.frame().get(rt.PENDING_EFFECTS)
        await atelier.write(pid, "outil.py", "print(2)\n")  # l'atelier bouge après la proposition
        await atelier.commit(pid, "après la proposition")
        approved = await perform(kernel, "projects.approuver", row_form({"proposal": str(pending.proposal)}),
                                 by="user_1", subject=str(pid), nonce="a1")
        await wait(2)
        summary = events(kernel, rt.EFFECT_PROPOSED)[-1].data.summary.text
        return shown, approved, summary, list(atelier.pushed_shas)

    shown, approved, summary, pushed = live(tmp_path, scenario, atelier=atelier)
    assert approved.ok and pushed == [shown]  # le commit montré, pas le suivant
    assert shown[:12] in summary and "première version" in summary  # ce qu'on approuve est dit


def test_a_pull_is_refused_while_a_run_works_in_the_workshop():
    from mika.faculties.projects.actions import _pullable
    from mika.faculties.projects.atelier import pull
    from mika.faculties.projects.faculty import Project, ProjectsState, Run
    from mika.kernel.state import FrozenDict

    url = "https://github.com/moi/outils.git"
    p = Project(7, "t", c.USER, created_at=0, remote=url)
    working = ProjectsState(projects=FrozenDict({7: p}), running=FrozenDict({"ep": Run(7, 1, "run")}))
    idle = ProjectsState(projects=FrozenDict({7: p}))

    class At:
        def __init__(self, s):
            self.s = s

        def state(self, owner):
            return self.s

    atelier = Atelier()
    args = {"project": 7, "url": url, "branch": "main"}
    busy = asyncio.run(pull(args, project_target(7), {"workshop": atelier, "frame": lambda: At(working)}))
    assert busy == (False, "refusé : une exécution travaille dans l'atelier — récupère quand elle a fini")
    assert atelier.pulled == []
    free = asyncio.run(pull(args, project_target(7), {"workshop": atelier, "frame": lambda: At(idle)}))
    assert free[0] and atelier.pulled == [(7, url, "main")]
    assert not _pullable(working, None, "7", {"workshop": atelier}) and _pullable(idle, None, "7", {"workshop": atelier})


# ── Ce que la relecture a trouvé ──────────────────────────────────────────


def test_two_additions_of_the_same_number_both_land(tmp_path):
    from mika.faculties.projects.faculty import DECIDED

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le module", objectives="Écrire le module", start="3:00", end="4:00")
        same = [OBJECTIVE_ADDED.draft(project=pid, objective=2, text=Content.of(t, level=0), author=a)
                for t, a in (("de l'opérateur", "operator"), ("d'elle", "self"))]
        decided = [DECIDED.draft(project=pid, decision=1, title=Content.of(t, level=0), choice=Content.of(t, level=0))
                   for t in ("Base", "Langage")]
        for d in (*same, *decided):
            await kernel.mind.append([d], emitter="projects", correlation="course", origin=Origin.GENESIS)
        return kernel.mind.frame().state("projects").projects[pid]

    p = live(tmp_path, scenario)
    assert [o.id for o in p.objectives] == [1, 2, 3]  # aucun ajout perdu en silence
    assert [d.id for d in p.decisions] == [1, 2]


def test_a_constant_that_never_concludes_is_set_aside_without_feelings(tmp_path):
    from mika.ports.llm import LLMResponse

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Entretien", constants="Relire le code", cadence_hours="1")
        before = kernel.mind.frame().get(self_c.ESTEEM)
        llm._work = lambda req: LLMResponse("Je réfléchis encore.")
        await wait(2 * 60)
        await kernel.lanes.join()
        return events(kernel, c.OBJECTIVE_CLOSED), kernel.mind.frame().state("projects").projects[pid], \
            (before, kernel.mind.frame().get(self_c.ESTEEM))

    closed, project, esteem = live(tmp_path, scenario)
    assert closed == [] and project.objectives[0].status == c.BLOCKED  # mis de côté, pas « clos »
    assert esteem[0] == esteem[1]  # sans frustration ni estime touchée : l'ADR les réserve aux ponctuels


def test_an_old_project_goal_is_cancelled_without_feelings(tmp_path):
    async def scenario(kernel, llm):
        before = kernel.mind.frame().get(self_c.ESTEEM)
        await kernel.mind.append([goals_c.GOAL_OPENED.draft(
            kind=goals_c.PROJECT, authority=goals_c.USER, title=Content.of("Un ancien projet", level=1), owner="user_1",
            about=("user_1",), bundles=("goals",), max_steps=12, source="operator", sensitivity=1)],
            emitter="goals", correlation="ancien", origin=Origin.GENESIS)
        await wait(5)
        return events(kernel, goals_c.GOAL_CLOSED), (before, kernel.mind.frame().get(self_c.ESTEEM))

    closed, esteem = live(tmp_path, scenario)
    [c_] = closed
    assert c_.data.status == goals_c.CANCELLED and "ADR 0031" in c_.data.reason and esteem[0] == esteem[1]


def test_forms_accept_what_people_type_and_refuse_what_would_leak():
    import pytest as _pytest

    from mika.faculties.projects.actions import check_remote, parse_hhmm

    assert parse_hhmm("9") == 540 and parse_hhmm("9 h") == 540 and parse_hhmm("18h30") == 1110
    assert parse_hhmm("24:00", end=True) == 1440
    with _pytest.raises(ValueError):
        parse_hhmm("24:00")  # un début de plage à minuit le soir n'a pas de sens
    for bad in ("https://github.com/x.git?private_token=abc", "https://github.com/x.git#main",
                "https://u:p@github.com/x.git", "http://github.com/x.git"):
        with _pytest.raises(ValueError):
            check_remote(bad)
    assert check_remote("https://git.example:8443/a/b.git") == "https://git.example:8443/a/b.git"


def test_retired_parameters_are_ignored_and_others_still_refused():
    import json

    import pytest as _pytest
    from pydantic import ValidationError

    from mika.faculties.goals.faculty import GOALS, GoalsParams
    from mika.kernel.registry import _decode_params

    old = json.dumps({"exploration_steps": 5, "project_steps": 12, "project_evidence": 10.0})
    assert _decode_params(GoalsParams, old, GOALS.retired_params).exploration_steps == 5
    with _pytest.raises(ValidationError):
        _decode_params(GoalsParams, json.dumps({"exploration_steps": 5, "projet_steps": 3}), GOALS.retired_params)


# ── Ce que la seconde relecture a trouvé ──────────────────────────────────


def row_form(fixed: dict[str, str], **values: str) -> dict[str, list[str]]:
    return {**form(**values), "_fixes": list(fixed), **{k: [v] for k, v in fixed.items()}}


def _run_context(kernel, pid: int, oid: int, calls: tuple[tuple[str, bool], ...] = (), kind: str = Kind.WORK):
    """Le contexte d'un outil pendant une exécution qui vise cet objectif, avec ce qu'elle a déjà fait."""
    mind = kernel.mind
    n = next(_CALLS)
    episode = EpisodeRef(f"ep-{n}", kind, target=project_target(pid),
                         attrs=FrozenDict({"subject": subject_of(pid, oid)}))
    frame = Frame(mind.frame().root, mind.clock.now(), mind.registry, Audience(owner=True), episode)
    return ToolContext(mind, mind.registry.tools["report_run"], f"appel-{n}", f"ep-{n}", frame, ports=kernel.ports,
                       calls=calls)


async def _status(kernel, pid: int, oid: int, status: str, nonce: str) -> None:
    got = await perform(kernel, "projects.objectif_statut", row_form({"objective": str(oid), "status": status}),
                        by="user_1", subject=str(pid), nonce=nonce)
    assert got.ok, got


def test_a_reopened_objective_starts_from_nothing_and_can_block_again(tmp_path):
    """Rouvert, il repart sans dette ni preuve : rebloqué après d'autres exécutions muettes (la clé de la
    première clôture ne la fait pas dédoublonner), et « fait » sans nouveau travail n'est pas cru."""
    from mika.ports.llm import LLMResponse

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le module", mode="plain", objectives="Écrire le module")
        llm._work = lambda req: LLMResponse("Je réfléchis encore.")
        await wait(2 * 60)
        await kernel.lanes.join()
        first = kernel.mind.frame().state("projects").projects[pid].objectives[0]
        await _status(kernel, pid, 1, c.OPEN, "r1")
        reopened = kernel.mind.frame().state("projects").projects[pid].objectives[0]
        await wait(2 * 60)
        await kernel.lanes.join()
        return pid, first, reopened, events(kernel, c.OBJECTIVE_CLOSED)

    pid, first, reopened, closed = live(tmp_path, scenario)
    assert first.status == c.BLOCKED
    assert reopened.status == c.OPEN and (reopened.runs, reopened.silent, reopened.evidence) == (0, 0, 0)
    assert [e.data.status for e in closed] == [c.BLOCKED, c.BLOCKED]  # bloqué de nouveau, pas figé ouvert


def test_done_needs_work_that_produces_something_and_new_work_after_a_reopening(tmp_path):
    from mika.faculties.projects.tools import ReportArgs, report_run

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le module", objectives="Écrire le module", start="3:00", end="4:00")
        done = ReportArgs(verdict="done", summary="Fini.", notable=0.6)
        searched = await report_run(done, _run_context(kernel, pid, 1, (("memory_search", True),
                                                                        ("ws_network", True))))
        written = await report_run(done, _run_context(kernel, pid, 1, (("ws_write", True),)))
        await _status(kernel, pid, 1, c.OPEN, "r1")
        o = kernel.mind.frame().state("projects").projects[pid].objectives[0]
        again = await report_run(done, _run_context(kernel, pid, 1))
        return searched, written, again, o, events(kernel, c.OBJECTIVE_CLOSED)

    searched, written, again, reopened, closed = live(tmp_path, scenario)
    assert "pas fini" in searched  # chercher ou proposer n'est pas produire
    assert "atteint" in written
    assert (reopened.evidence, reopened.notable, reopened.result_ref) == (0, 0.0, "")
    assert "pas fini" in again and [e.data.status for e in closed] == [c.DONE]  # une seule clôture


class _DroppingAtelier(Atelier):
    """Un atelier dont l'enregistrement laisse à l'opérateur le temps de retirer l'objectif visé."""

    kernel = None

    async def commit(self, project: int, message: str, paths=()) -> str:
        await _status(self.kernel, project, 1, c.DROPPED, f"retrait-{len(message)}")
        return await super().commit(project, message, paths)


def test_a_verdict_on_an_objective_dropped_meanwhile_closes_nothing_and_moves_nothing(tmp_path):
    from mika.faculties.projects.tools import ReportArgs, report_run

    atelier = _DroppingAtelier()

    async def scenario(kernel, llm):
        atelier.kernel = kernel
        before = kernel.mind.frame().get(self_c.ESTEEM)
        pid = await create(kernel, "p1", title="Le module", objectives="Écrire le module", start="3:00", end="4:00")
        await atelier.write(pid, "module.py", "print('ok')\n")
        said = await report_run(ReportArgs(verdict="blocked", summary="Je bloque."),
                                _run_context(kernel, pid, 1, (("ws_write", True),)))
        return said, events(kernel, c.OBJECTIVE_CLOSED), events(kernel, c.RUN_REPORTED), \
            kernel.mind.frame().state("projects").projects[pid], (before, kernel.mind.frame().get(self_c.ESTEEM))

    said, closed, reports, project, esteem = live(tmp_path, scenario, atelier=atelier)
    assert "n'est plus ouvert" in said and closed == []  # retiré pendant qu'elle concluait : rien à clore
    assert len(reports) == 1 and project.objectives[0].status == c.DROPPED  # son compte rendu, lui, reste
    assert esteem[0] == esteem[1]


def test_a_verdict_on_an_objective_dropped_before_closes_nothing(tmp_path):
    from mika.faculties.projects.tools import ReportArgs, report_run

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le module", objectives="Écrire le module", start="3:00", end="4:00")
        await _status(kernel, pid, 1, c.DROPPED, "x1")
        said = await report_run(ReportArgs(verdict="done", summary="Fini."),
                                _run_context(kernel, pid, 1, (("ws_write", True),)))
        return said, events(kernel, c.OBJECTIVE_CLOSED), events(kernel, c.RUN_REPORTED)

    said, closed, reports = live(tmp_path, scenario)
    assert "n'est plus ouvert" in said and closed == [] and not reports[0].data.proven


def test_an_objective_checked_by_the_operator_is_never_told_as_hers(tmp_path):
    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le module", objectives="Écrire le module", start="3:00", end="4:00")
        await _status(kernel, pid, 1, c.DONE, "d1")
        await wait(30)
        return kernel.mind.frame().state("projects").projects[pid].objectives[0], \
            [e for e in events(kernel, rt.EPISODE_STARTED) if c.SHARE in e.data.reason.split(",")]

    o, shares = live(tmp_path, scenario)
    assert o.status == c.DONE and o.shared and o.notable == 0.0 and shares == []


def test_a_stranger_cannot_have_her_open_a_project_and_a_goal_keeps_its_privacy(tmp_path):
    from mika.faculties.projects.tools import StartArgs, start_project

    async def scenario(kernel, llm):
        await connect(kernel, "user_5", "Inconnu")
        stranger = _context(kernel, "start_project", Kind.REPLY, "user_5", Audience(owner=False))
        refused = await start_project(StartArgs(title="Fais ça pour moi"), stranger)
        explo = await kernel.mind.append([goals_c.GOAL_OPENED.draft(
            kind=goals_c.EXPLORATION, authority=goals_c.SELF, title=Content.of("Aider Alice", level=3),
            about=("user_1",), bundles=("goals", "projects"), max_steps=8, source="genese", sensitivity=3,
            desire=0.9)], emitter="goals", correlation="genese", origin=Origin.GENESIS)
        mine = _context(kernel, "start_project", Kind.STEP, goal_target(explo.seqs[-1]), Audience(owner=True))
        await start_project(StartArgs(title="Aider Alice"), mine)
        return refused, events(kernel, c.PROJECT_CREATED), kernel.mind.registry.tools["start_project"]

    refused, created, spec = live(tmp_path, scenario)
    assert spec.owner_only  # pas même offert à quelqu'un d'autre en conversation
    assert "connais pas assez" in refused
    [p] = created
    assert p.data.about == ("user_1",) and p.data.sensitivity == 3  # né d'une confidence, il en reste une


def test_a_run_that_did_not_happen_gives_back_its_slots_but_does_not_retry_in_a_loop(tmp_path):
    from mika.faculties.projects.work import next_run_at

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le module", mode="plain", objectives="Écrire le module",
                           schedule="cron:0 9 * * *", start="3:00", end="4:00")
        mind = kernel.mind
        for i, outcome in enumerate(("preempted", "failed")):
            eid = f"ep-x-{i}"
            await mind.append([rt.EPISODE_STARTED.draft(kind=Kind.JOB, target=project_target(pid),
                                                        subject=subject_of(pid, 1))],
                              emitter="runtime", correlation=eid, origin=Origin.KERNEL)
            await mind.append([rt.EPISODE_ENDED.draft(kind=Kind.JOB, outcome=outcome, target=project_target(pid))],
                              emitter="runtime", correlation=eid, origin=Origin.KERNEL)
        f = mind.frame()
        s = f.state("projects")
        return s.projects[pid], s, next_run_at(s.projects[pid], s, f), f.now

    p, s, due, now = live(tmp_path, scenario, start=at_paris(2026, 9, 29, 9, 0))
    assert p.runs == 0 and p.runs_at == () and p.last_run_at == 0  # aucune n'a eu lieu
    assert len(s.runs_at) == 1  # la préemption rend sa place dans l'heure ; la panne, qui a coûté, non
    assert p.tried_at == now and p.failures == 1
    assert due is None or due >= p.tried_at + params(None).run_spacing_us  # pas de relance en boucle


def test_a_constant_cadence_counts_from_the_start_of_its_pass(tmp_path):
    from mika.faculties.projects.tools import ReportArgs, report_run

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Entretien", constants="Relire le code", cadence_hours="2",
                           start="3:00", end="4:00")
        start = await kernel.mind.append([rt.EPISODE_STARTED.draft(
            kind=Kind.WORK, target=project_target(pid), subject=subject_of(pid, 1))],
            emitter="runtime", correlation="ep-pass", origin=Origin.KERNEL)
        await wait(20)  # le passage dure vingt minutes
        ctx = _run_context(kernel, pid, 1, (("ws_write", True),))
        ctx.episode_id = "ep-pass"
        await report_run(ReportArgs(verdict="done", summary="Relu."), ctx)
        return start, kernel.mind.frame().state("projects").projects[pid].objectives[0]

    start, o = live(tmp_path, scenario)
    began = start.root.at
    assert o.passed_at == began and o.passes == 1  # la cadence ne dérive pas de la durée du passage


def test_living_objectives_are_capped_not_the_history_and_decisions_in_force_are_kept(tmp_path):
    from mika.faculties.projects.faculty import DECISIONS_KEPT, OBJECTIVES_HISTORY, OBJECTIVES_KEPT

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le module", objectives="Écrire le module", start="3:00", end="4:00")
        drafts = []
        for i in range(2, OBJECTIVES_KEPT + 40):
            drafts.append(OBJECTIVE_ADDED.draft(project=pid, objective=i, text=Content.of(f"o{i}", level=0)))
        await kernel.mind.append(drafts[:OBJECTIVES_KEPT - 1], emitter="projects", correlation="o",
                                 origin=Origin.GENESIS)
        full = kernel.mind.frame().state("projects").projects[pid]
        for o in full.objectives[:30]:
            await _status(kernel, pid, o.id, c.DONE, f"d{o.id}")
        await kernel.mind.append(drafts[OBJECTIVES_KEPT - 1:], emitter="projects", correlation="o2",
                                 origin=Origin.GENESIS)
        decided = [DECIDED.draft(project=pid, decision=i, title=Content.of(f"d{i}", level=0),
                                 choice=Content.of("x", level=0)) for i in range(1, DECISIONS_KEPT + 2)]
        await kernel.mind.append(decided, emitter="projects", correlation="d", origin=Origin.GENESIS)
        return full, kernel.mind.frame().state("projects").projects[pid]

    full, after = live(tmp_path, scenario)
    assert len(full.objectives) == OBJECTIVES_KEPT
    living = [o for o in after.objectives if o.status == c.OPEN]
    assert len(living) == OBJECTIVES_KEPT and len(after.objectives) <= OBJECTIVES_HISTORY  # d'autres ont pu entrer
    assert len(after.decisions) == DECISIONS_KEPT and all(d.status == c.IN_FORCE for d in after.decisions)
    assert [d.id for d in after.decisions][:2] == [1, 2]  # aucune décision en vigueur n'est tombée


def test_her_mailbox_enters_a_run_only_when_the_project_has_it(tmp_path):
    from mika.plugins.email import for_owner

    def frame_of(kind: str, bundles: str) -> Frame:
        return Frame(None, 0, None, None, EpisodeRef("e", kind, target=project_target(1),
                                                     attrs=FrozenDict({"args": FrozenDict({"bundles": bundles})})))

    assert not for_owner(frame_of(Kind.WORK, "projects,workshop,memory"))
    assert not for_owner(frame_of(Kind.JOB, "projects,workshop"))
    assert for_owner(frame_of(Kind.JOB, "projects,workshop,email"))
    assert for_owner(Frame(None, 0, None, None, EpisodeRef("e", Kind.STEP, target="goal:1")))


def test_effects_of_an_archived_project_no_longer_run():
    from mika.faculties.projects.atelier import networked, push
    from mika.faculties.projects.faculty import Project, ProjectsState
    from mika.kernel.state import FrozenDict as FD

    archived = ProjectsState(projects=FD({7: Project(7, "t", c.USER, created_at=0, status=c.ARCHIVED)}))

    class At:
        def state(self, owner):
            return archived

    atelier = Atelier(token="jeton")
    ports = {"workshop": atelier, "frame": lambda: At()}
    ran = asyncio.run(networked({"project": 7, "argv": ["pip", "install", "x"]}, project_target(7), ports))
    sent = asyncio.run(push({"project": 7, "url": "https://github.com/a/b.git", "sha": "abc"}, project_target(7),
                            ports))
    assert ran == (False, "refusé : ce projet est archivé") and sent[0] is False and atelier.pushed == []


def test_a_paused_project_does_not_tell_what_it_finished(tmp_path):
    from mika.faculties.projects.work import _share

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le module", objectives="Écrire le module", start="3:00", end="4:00")
        await kernel.mind.append([c.OBJECTIVE_CLOSED.draft(project=pid, objective=1, status=c.DONE,
                                                           title=Content.of("Écrire le module", level=0),
                                                           notable=0.9, mode=c.PERSONA)],
                                 emitter="projects", correlation="fin", origin=Origin.GENESIS)
        f = kernel.mind.frame()
        active = _share(f.state("projects"), f)
        got = await perform(kernel, "projects.pause", form(), by="user_1", subject=str(pid), nonce="p")
        assert got.ok, got
        f = kernel.mind.frame()
        return active, _share(f.state("projects"), f)

    active, paused = live(tmp_path, scenario)
    assert len(active) == 1 and paused == []


def test_a_suspended_old_project_goal_is_cancelled_too(tmp_path):
    from mika.faculties.goals.faculty import GOAL_PAUSED

    async def scenario(kernel, llm):
        gid = kernel.mind.head + 1  # ouvert et suspendu d'un même commit : aucun processus ne passe entre les deux
        got = await kernel.mind.append([goals_c.GOAL_OPENED.draft(
            kind=goals_c.PROJECT, authority=goals_c.USER, title=Content.of("Un ancien projet", level=1),
            owner="user_1", about=("user_1",), bundles=("goals",), max_steps=12, source="operator", sensitivity=1),
            GOAL_PAUSED.draft(goal=gid)], emitter="goals", correlation="ancien", origin=Origin.GENESIS)
        assert got.seqs[0] == gid
        suspended = kernel.mind.frame().state("goals").goals[gid].paused_at > 0
        await wait(5)
        return suspended, events(kernel, goals_c.GOAL_CLOSED), kernel.mind.frame().get(goals_c.LIVE)

    suspended, closed, alive = live(tmp_path, scenario)
    assert suspended and [e.data.status for e in closed] == [goals_c.CANCELLED] and alive == ()


def test_resumed_after_a_breakdown_it_can_break_down_again(tmp_path):
    """Les pannes rendent leur crédit (la dernière exécution réelle ne bouge pas) : la seconde pause ne doit
    pas être prise pour la première (même clé, dédoublonnée) — le projet resterait actif, en échec."""

    async def scenario(kernel, llm):
        llm.fail["project"] = 500
        pid = await create(kernel, "p1", title="Le module", objectives="Écrire le module")
        await wait(3 * 60)
        await kernel.lanes.join()
        got = await perform(kernel, "projects.reprendre", form(), by="user_1", subject=str(pid), nonce="r")
        assert got.ok, got
        await wait(3 * 60)
        await kernel.lanes.join()
        return events(kernel, PAUSED), kernel.mind.frame().state("projects").projects[pid]

    paused, project = live(tmp_path, scenario)
    assert len(paused) == 2 and project.status == c.PAUSED and project.last_run_at == 0


def test_blocked_reopened_and_blocked_again_after_the_same_number_of_runs(tmp_path):
    """Le cas exact de la boucle : rouvert, il rebloque après autant d'exécutions muettes que la première fois
    (même nombre d'exécutions, mêmes silences) — la seconde clôture doit s'écrire."""

    async def silent_runs(kernel, pid: int, tag: str) -> None:
        for i in range(params(None).silent_before_blocked):
            eid = f"ep-{tag}-{i}"
            await kernel.mind.append([rt.EPISODE_STARTED.draft(kind=Kind.JOB, target=project_target(pid),
                                                               subject=subject_of(pid, 1))],
                                     emitter="runtime", correlation=eid, origin=Origin.KERNEL)
            await wait(1)
            await kernel.mind.append([rt.EPISODE_ENDED.draft(kind=Kind.JOB, outcome="done",
                                                             target=project_target(pid))],
                                     emitter="runtime", correlation=eid, origin=Origin.KERNEL)
        await wait(3)

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le module", mode="plain", objectives="Écrire le module",
                           start="3:00", end="4:00")  # hors de sa plage : seules nos exécutions comptent
        await silent_runs(kernel, pid, "a")
        first = kernel.mind.frame().state("projects").projects[pid].objectives[0]
        await _status(kernel, pid, 1, c.OPEN, "r1")
        await silent_runs(kernel, pid, "b")
        return first, kernel.mind.frame().state("projects").projects[pid].objectives[0], \
            events(kernel, c.OBJECTIVE_CLOSED)

    first, second, closed = live(tmp_path, scenario)
    assert first.status == c.BLOCKED and first.runs == second.runs  # le même compte, la même situation
    assert second.status == c.BLOCKED and len(closed) == 2
