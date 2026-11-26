"""La relecture indépendante (ADR 0276) : avant que le travail conclu d'un objectif sorte, une autre exécution le
relit, sans ce que la première en a dit.

- un parcours entier sur le vrai noyau et le vrai atelier, du « fait » à la proposition de pull request : la
  relecture part d'elle-même, sous son rôle de modèle, ne voit ni le compte rendu ni le carnet de l'exécution qui a
  travaillé, n'a aucun outil qui écrit, conclut par ``review_verdict`` — et la proposition ne part qu'après, son
  aperçu portant le verdict ;
- un verdict défavorable rouvre l'objectif, ses constats cités à l'exécution suivante comme le dire d'une autre
  exécution ; après deux refus de suite, la troisième n'a pas lieu et la main est au propriétaire ;
- le verdict d'un commit ne vaut plus quand la branche a bougé ; jamais deux relectures pour le même commit ;
- rien ne sort sans verdict quand le réglage le demande (une pull request, un envoi au flux direct), et tout sort
  comme avant en « jamais » ;
- une relecture en panne ne vaut pas « bon » ; menée au bout sans conclure, elle rend la main ;
- elle compte dans les plafonds du projet ; son rôle de modèle se règle à part ; la console en dit le nécessaire.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import replace

import pytest

from mika.adapters.llm.config import ROLE_LABELS, ROLES
from mika.app import composition
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects import inspect_reviews, pulls, review, triage
from mika.faculties.projects import prompt as project_prompt
from mika.faculties.projects.actions import ModifyArgs
from mika.faculties.projects.faculty import (
    PULL_REQUEST_CAPABILITY,
    PUSH_CAPABILITY,
    REFRAMED,
    REVIEW_REFUSALS_MAX,
    Item,
    Objective,
    Project,
    handed_over,
    objective_at,
    push_reviewed,
    reopened,
    rereads,
    review_of,
    review_subject,
    review_waiting,
    unreviewed,
)
from mika.faculties.projects.review import REVIEW_ASKED, REVIEWED
from mika.faculties.projects.tools import NoteArgs, ReportArgs, project_note, report_run
from mika.kernel.events import Origin
from mika.kernel.faculty import ToolResult
from mika.kernel.frame import Audience, EpisodeRef, Frame
from mika.kernel.state import FrozenDict
from mika.runtime import decisions
from mika.runtime.tools import ToolContext
from mika.sim.clock import SimClock, run_virtual
from mika.sim.llm.persona import PersonaSimLLM
from mika.vocab.episodes import FALLBACKS, MODES, REVIEW, Kind, Role, project_target
from tests.fixtures.atelier import Atelier
from tests.fixtures.mika import boot, build, connect
from tests.unit.test_project_pulls import NO_RUN, URL, Host, Shop, _start
from tests.unit.test_projects import MONDAY, _run_context, create, events, runs, wait

needs_bwrap = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap absent")
ONE = "work/objective-1"
TOOLS = "OUTILS : review_list, review_read, review_run, review_verdict"
SHA, OTHER = "a" * 40, "b" * 40


def live(tmp_path, scenario, *, real: bool = False):
    """Le vrai noyau : avec le vrai atelier et un faux hôte (``real`` : un projet à pull requests), ou un atelier en
    mémoire. Le modèle simulé joue la relecture selon ``llm.review_mode``."""
    clock = SimClock(MONDAY)
    llm = PersonaSimLLM(clock, seed=1, abstain_rate=0.0, latency=2.0)
    llm.step_mode = "honest"
    shop = Shop(tmp_path / "ateliers") if real else None
    ports = {"workshop": shop.ws, "repo_host": Host()} if shop is not None else {"workshop": Atelier()}
    kernel, clock, _, _ = build(tmp_path, None, clock=clock, llm=llm, ports=ports)

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            return await scenario(kernel, llm, shop)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


def _project(kernel, pid: int) -> Project:
    return kernel.mind.frame().state("projects").projects[pid]


def _objective(kernel, pid: int, oid: int = 1) -> Objective:
    return objective_at(_project(kernel, pid), oid)


def _proposed(kernel, capability: str) -> list:
    return [e for e in events(kernel, rt.EFFECT_PROPOSED) if e.data.capability == capability]


def _reviews(kernel, pid: int) -> list:
    """Les relectures parties sur ce projet (leurs départs d'épisode)."""
    return [e for e in runs(kernel, pid) if review_of(e.data.subject) is not None]


async def _done(kernel, pid: int, summary: str = "Un pas de plus.", oid: int = 1):
    return await report_run(ReportArgs(verdict="done", summary=summary, how_met="Vu."),
                            _run_context(kernel, pid, oid, (("ws_write", True),)))


async def _work(kernel, pid: int, name: str, text: str, *, real: bool, summary: str = "Un pas de plus."):
    """Une exécution jouée à la main sur l'objectif n° 1 : elle écrit un fichier et conclut « fait »."""
    ws = kernel.ports["workshop"]
    if real:
        await _start(kernel, pid, 1)
    await ws.write(pid, name, text)
    return await _done(kernel, pid, summary)


# ── Le parcours entier : du « fait » à la proposition de pull request ──────


@needs_bwrap
def test_a_done_objective_is_reread_by_another_run_before_its_pull_request_is_proposed(tmp_path):
    async def scenario(kernel, llm, shop):
        ws, out = shop.ws, {}
        pid = await create(kernel, "p1", title="Le site", objectives="Écrire la page d'accueil", approval="on",
                           remote=URL, **NO_RUN)
        out["setting"] = (_project(kernel, pid).flow, _project(kernel, pid).reread)
        await ws.write(pid, "LISEZMOI.md", "# Le site\n")
        await ws.commit(pid, "la base")
        await _start(kernel, pid, 1)
        await ws.write(pid, "page.html", "<h1>Accueil</h1>\n")
        # son carnet et son compte rendu : ce qu'une relecture ne doit jamais lire
        await project_note(NoteArgs(text="CARNET-SECRET : j'ai sauté les tests."), _run_context(kernel, pid, 1))
        out["done"] = await _done(kernel, pid, "COMPTE-RENDU-SECRET : tout est fait.")
        out["head"] = await ws._ref(pid, f"refs/heads/{ONE}")
        await wait(12)
        out["objective"], out["project"] = _objective(kernel, pid), _project(kernel, pid)
        out["asked"] = events(kernel, REVIEW_ASKED)
        out["verdicts"] = events(kernel, REVIEWED)
        out["reviews"] = _reviews(kernel, pid)
        out["pulls"] = _proposed(kernel, PULL_REQUEST_CAPABILITY)
        out["seen"] = list(llm.reviews_seen)
        # ce que l'exécution qui travaille lit, elle : son compte rendu et son carnet y sont bien
        frame = _run_context(kernel, pid, 1).frame
        s = frame.state("projects")
        out["worker"] = project_prompt._run_section(
            s, frame, {"projects": await project_prompt._texts(s, frame, kernel.ports)}).content
        out["preview"] = await decisions.preview(kernel.mind, kernel.ports, PULL_REQUEST_CAPABILITY,
                                                 out["pulls"][0].data.args_json) if out["pulls"] else None
        await wait(15)
        out["reviews_later"] = len(_reviews(kernel, pid))  # pas deux relectures du même commit
        # la branche bouge : le verdict de l'ancien commit ne vaut plus, la pull request ne se compose plus
        await ws.write(pid, "pied.html", "<footer>Fin</footer>\n")
        await ws.commit(pid, "un commit de plus")
        out["moved"] = await pulls.compose({**json.loads(out["pulls"][0].data.args_json), "sha": ""}, kernel.ports)
        return out

    out = live(tmp_path, scenario, real=True)
    assert out["setting"] == (c.FLOW_PR, c.REREAD_OUT)  # le défaut : avant de sortir
    assert "Une autre exécution va relire ce travail" in out["done"]
    o, [asked], [verdict], [started], [pull] = (out["objective"], out["asked"], out["verdicts"], out["reviews"],
                                               out["pulls"])
    # une relecture, pour le commit au bout de la branche, impersonnelle, dans son mode et à son sujet
    assert asked.data.sha == out["head"] == verdict.data.sha == o.reviewed and verdict.data.good and o.review_ok
    assert (started.data.kind, started.data.subject) == (Kind.JOB, review_subject(out["project"].id, 1))
    # la proposition ne part qu'après le verdict, et porte le commit relu
    assert asked.seq < started.seq < verdict.seq < pull.seq
    assert json.loads(pull.data.args_json)["sha"] == out["head"]
    assert (o.status, o.review_due, o.review_refused, bool(o.pull_proposal)) == (c.DONE, "", (), True)
    # elle a vu la demande et le diff — ni le compte rendu, ni le carnet de l'exécution qui a travaillé
    [seen] = out["seen"]
    assert "Écrire la page d'accueil" in seen and "<h1>Accueil</h1>" in seen and "page.html" in seen
    assert "LE TRAVAIL À RELIRE" in seen and "LE DIFF À RELIRE" in seen and out["head"][:12] in seen
    assert "COMPTE-RENDU-SECRET" in out["worker"] and "CARNET-SECRET" in out["worker"]
    assert "COMPTE-RENDU-SECRET" not in seen and "CARNET-SECRET" not in seen and "report_run" not in seen
    # ses outils : lire, lancer, conclure — rien qui écrit
    assert TOOLS in seen
    # elle compte dans les plafonds du projet (les exécutions jouées à la main n'ont pas d'épisode)
    assert len(out["project"].runs_at) == 1 and out["reviews_later"] == 1
    # l'aperçu de la proposition porte le verdict : qui a relu, quel commit
    assert not out["preview"].blocked
    assert f"Relecture indépendante : bon, au commit {out['head'][:12]} par « fake »." in out["preview"].text
    # la branche a bougé : ce qui partirait n'a pas été relu
    assert out["moved"] == inspect_reviews.UNREVIEWED


# ── Un refus rouvre ; deux refus rendent la main ───────────────────────────


@needs_bwrap
def test_a_refusal_reopens_with_the_findings_quoted_and_two_in_a_row_hand_it_to_the_owner(tmp_path):
    async def scenario(kernel, llm, shop):
        ws, out = shop.ws, {}
        llm.review_mode = "findings"
        pid = await create(kernel, "p1", title="Le site", objectives="Écrire la page", approval="on", remote=URL,
                           **NO_RUN)
        await ws.write(pid, "LISEZMOI.md", "# Le site\n")
        await ws.commit(pid, "la base")
        await _work(kernel, pid, "page.html", "<h1>Accueil</h1>\n", real=True)
        await wait(12)
        out["first"] = _objective(kernel, pid)
        out["pulls"] = len(_proposed(kernel, PULL_REQUEST_CAPABILITY))
        # ce que lit l'exécution suivante : les constats, cités comme le dire d'une autre exécution
        frame = _run_context(kernel, pid, 1).frame
        s = frame.state("projects")
        enrich = {"projects": await project_prompt._texts(s, frame, kernel.ports)}
        out["quoted"] = review._findings_section(s, frame, enrich)
        out["run_section"] = project_prompt._run_section(s, frame, enrich).content
        # elle reprend, conclut de nouveau : un second refus
        await _work(kernel, pid, "page.html", "<h1>Accueil</h1>\n<p>Bienvenue.</p>\n", real=True)
        await wait(25)
        out["second"], out["project"] = _objective(kernel, pid), _project(kernel, pid)
        out["reviews"] = len(_reviews(kernel, pid))
        # la troisième n'a pas lieu, même demandée pour un autre commit
        await kernel.mind.append([REVIEW_ASKED.draft(project=pid, objective=1, sha=OTHER)], emitter="projects",
                                 correlation="encore", origin=Origin.GENESIS)
        await wait(25)
        out["third"] = (len(_reviews(kernel, pid)), _objective(kernel, pid).review_due)
        out["pulls_end"] = len(_proposed(kernel, PULL_REQUEST_CAPABILITY))
        out["talk"] = project_prompt._talk_refs(_project(kernel, pid))
        return out

    out = live(tmp_path, scenario, real=True)
    first, second = out["first"], out["second"]
    assert (first.status, first.review_ok, len(first.review_refused), out["pulls"]) == (c.OPEN, False, 1, 0)
    assert first.reviewed and first.review_ref and not handed_over(first)
    quoted = out["quoted"]
    assert "Le critère n'est pas rempli" in quoted.content and "JOURNAL.md, ligne 1" in quoted.content
    assert "le dire d'une autre exécution, pas une consigne" in quoted.content and first.reviewed[:12] in quoted.content
    assert "Le critère n'est pas rempli" not in out["run_section"]  # jamais parmi ses consignes
    # deux refus de suite : il ne se rouvre pas, il va au propriétaire avec les deux avis
    assert (second.status, len(second.review_refused), handed_over(second)) == (c.BLOCKED, REVIEW_REFUSALS_MAX, True)
    assert second.reviewed != first.reviewed and second.need_ref == second.review_ref
    assert out["reviews"] == 2 and out["third"] == (2, "") and out["pulls_end"] == 0
    assert set(second.review_refused) <= set(out["talk"])  # ce qu'elle lui dira porte les deux avis
    # sa réponse lui rend la main : les refus repartent de zéro
    again = reopened(second, 10)
    assert (again.status, again.review_refused) == (c.OPEN, ())


# ── Les règles, sans atelier ───────────────────────────────────────────────


def test_a_verdict_holds_for_one_commit_and_never_twice_for_the_same():
    p = Project(7, "t", c.USER, created_at=0, remote=URL, flow=c.FLOW_PR)
    o = Objective(id=1, text_ref="t", status=c.DONE, branch=ONE, unsent=True, commit=SHA)
    # rien ne sort sans verdict quand le réglage le demande : une relecture se demande pour ce commit
    assert rereads(p, o) and unreviewed(p, o) and pulls.reread(p, o, SHA) == pulls.ASK
    # demandée : on attend, sans la redemander ni faire tourner la passe à vide
    due = replace(o, review_due=SHA)
    assert pulls.reread(p, due, SHA) == pulls.WAIT and pulls.parked(p, due) and not pulls.parked(p, o)
    assert review_waiting(replace(p, objectives=(due,))) == due
    # bon : la proposition part — pour ce commit-là seulement
    good = replace(o, reviewed=SHA, review_ok=True)
    assert pulls.reread(p, good, SHA) == pulls.PASS and not unreviewed(p, good)
    assert pulls.reread(p, good, OTHER) == pulls.ASK  # la branche a bougé : il ne vaut plus
    # refusé : ce commit n'est pas relu une seconde fois
    bad = replace(o, reviewed=SHA, review_ok=False)
    assert pulls.reread(p, bad, SHA) == pulls.WAIT and pulls.parked(p, bad)
    # la main au propriétaire : plus aucune relecture, même pour un autre commit
    held = replace(bad, review_refused=("r1", "r2"))
    assert pulls.reread(p, held, OTHER) == pulls.WAIT and review_waiting(replace(p, objectives=(
        replace(held, review_due=OTHER),))) is None
    # « jamais » : tout sort comme avant
    never = replace(p, reread=c.REREAD_NEVER)
    assert not rereads(never, o) and pulls.reread(never, o, SHA) == pulls.PASS and push_reviewed(never, SHA)
    assert review_waiting(replace(never, objectives=(due,))) is None


def test_when_a_project_rereads_and_what_may_leave_a_direct_project():
    once, constant = Objective(id=1, text_ref="t", commit=SHA), Objective(id=2, text_ref="t", kind=c.CONSTANT)
    local = Project(7, "t", c.USER, created_at=0)
    direct = replace(local, remote="https://example.org/moi/site.git", auto_push=True)
    # avant de sortir (le défaut) : rien à relire sur un projet dont rien ne sort
    assert local.reread == c.REREAD_OUT and not rereads(local, once) and rereads(direct, once)
    assert rereads(direct, constant)
    # à chaque « fait » : aussi un ponctuel d'un projet sans dépôt distant, pas le passage d'un constant
    each = replace(local, reread=c.REREAD_EACH)
    assert rereads(each, once) and not rereads(each, constant)
    # un envoi d'elle-même, au flux direct : seulement le commit qu'une relecture a dit bon
    assert not push_reviewed(replace(direct, objectives=(once,)), SHA)
    judged = replace(direct, objectives=(replace(once, reviewed=SHA, review_ok=True),))
    assert push_reviewed(judged, SHA) and not push_reviewed(judged, OTHER)
    # le ticket d'un travail qui attend sa relecture ne se ferme pas encore
    item = Item(list_name=c.TICKETS, key="1", number=1, objective=1, validated_at=5)
    waiting = replace(direct, objectives=(replace(once, status=c.DONE, ticket=1, closed_at=9),),
                      board=replace(direct.board, items=(item,)))
    state = type("S", (), {"projects": {7: waiting}})()
    assert triage.follow_ups(state) == []
    passed = replace(waiting, objectives=(replace(waiting.objectives[0], reviewed=SHA, review_ok=True),))
    state.projects = {7: passed}
    assert [d.data.closed for d in triage.follow_ups(state)] == [c.DONE]


# ── Hors des pull requests : à chaque « fait », l'envoi direct, la panne ───


def test_each_done_is_reread_once_and_a_silent_review_hands_the_objective_back(tmp_path):
    async def scenario(kernel, llm, shop):
        out = {}
        pid = await create(kernel, "p1", title="Un carnet", objectives="Tenir le carnet", reread=c.REREAD_EACH,
                           **NO_RUN)
        off = await create(kernel, "p2", title="Un autre", objectives="Tenir l'autre", reread=c.REREAD_NEVER,
                           **NO_RUN)
        await _work(kernel, pid, "carnet.md", "Jour 1\n", real=False)
        await _work(kernel, off, "autre.md", "Jour 1\n", real=False)
        await wait(12)
        out["each"], out["never"] = _objective(kernel, pid), _objective(kernel, off)
        await wait(15)
        out["counts"] = (len(_reviews(kernel, pid)), len(_reviews(kernel, off)), len(events(kernel, REVIEW_ASKED)))
        # une relecture qui ne conclut pas : deux essais, puis la main revient — ni bon, ni refusé
        llm.review_mode = "silent"
        mute = await create(kernel, "p3", title="Un muet", objectives="Tenir le muet", reread=c.REREAD_EACH,
                            **NO_RUN)
        await _work(kernel, mute, "muet.md", "Jour 1\n", real=False)
        await wait(40)
        out["silent"] = (_objective(kernel, mute), len(_reviews(kernel, mute)))
        return out

    out = live(tmp_path, scenario)
    each, never = out["each"], out["never"]
    assert each.commit and (each.reviewed, each.review_ok, each.status) == (each.commit, True, c.DONE)
    assert (never.reviewed, never.review_due, never.status) == ("", "", c.DONE)
    assert out["counts"] == (1, 0, 1)  # une seule relecture du même commit ; aucune en « jamais »
    silent, tried = out["silent"]
    assert (silent.status, silent.review_ok, silent.reviewed, silent.review_tries, tried) == (c.BLOCKED, False, "",
                                                                                            2, 2)


def test_a_direct_project_pushes_nothing_of_itself_before_a_good_verdict_and_a_broken_review_is_not_one(tmp_path):
    async def scenario(kernel, llm, shop):
        out = {}
        pid = await create(kernel, "p1", title="Le dépôt", objectives="Écrire le fichier", approval="on",
                           auto_push="on", remote="https://example.org/moi/site.git", **NO_RUN)
        out["flow"] = _project(kernel, pid).flow
        llm.fail = {"review": 1}  # la première relecture tombe en panne : le modèle ne répond pas
        out["done"] = await _work(kernel, pid, "fichier.md", "Un\n", real=False)
        out["after_done"] = len(_proposed(kernel, PUSH_CAPABILITY))
        for _ in range(60):
            await wait(1)
            if events(kernel, REVIEWED):
                break
        await wait(2)
        out["objective"], out["project"] = _objective(kernel, pid), _project(kernel, pid)
        out["ended"] = [(e.seq, e.data.outcome) for e in events(kernel, rt.EPISODE_ENDED)
                        if e.correlation in {x.correlation for x in _reviews(kernel, pid)}]
        out["verdicts"] = [(e.seq, e.data.good) for e in events(kernel, REVIEWED)]
        out["pushes"] = [(e.seq, json.loads(e.data.args_json)) for e in _proposed(kernel, PUSH_CAPABILITY)]
        return out

    out = live(tmp_path, scenario)
    o = out["objective"]
    assert out["flow"] == c.FLOW_DIRECT and "Rien ne part encore au dépôt distant" in out["done"]
    assert out["after_done"] == 0  # rien ne sort sans verdict
    # la panne : une relecture qui n'a pas eu lieu, sans verdict — puis une autre, qui conclut
    (broke_at, broke), (_, ended) = out["ended"]
    [(judged_at, good)] = out["verdicts"]
    assert broke == "failed" and ended == "done" and good and broke_at < judged_at
    # l'envoi ne part qu'après le verdict favorable, pour le commit relu
    [(pushed_at, args)] = out["pushes"]
    assert pushed_at > judged_at and args["sha"] == o.commit == o.reviewed and o.review_ok
    assert out["project"].failures == 0


# ── Ses outils se refusent hors d'une relecture ────────────────────────────


def _tool_context(kernel, pid: int, name: str, *, reviewing: bool) -> ToolContext:
    mind = kernel.mind
    attrs = {"subject": review_subject(pid, 1), "mode": REVIEW} if reviewing else {"subject": f"objective:{pid}:1"}
    episode = EpisodeRef("ep-relit", Kind.JOB, target=project_target(pid), attrs=FrozenDict(attrs))
    frame = Frame(mind.frame().root, mind.clock.now(), mind.registry, Audience(owner=True), episode)
    return ToolContext(mind, mind.registry.tools[name], "appel-relit", "ep-relit", frame, ports=kernel.ports)


def test_review_tools_only_serve_a_review_and_the_verdict_ends_the_loop(tmp_path):
    async def scenario(kernel, llm, shop):
        out = {}
        pid = await create(kernel, "p1", title="Un carnet", objectives="Tenir le carnet", reread=c.REREAD_NEVER,
                           **NO_RUN)
        await _work(kernel, pid, "carnet.md", "Jour 1\n", real=False)
        sha = _objective(kernel, pid).commit
        await kernel.mind.append([REFRAMED.draft(project=pid, reread=c.REREAD_EACH)], emitter="projects",
                                 correlation="regle", origin=Origin.GENESIS)
        await kernel.mind.append([REVIEW_ASKED.draft(project=pid, objective=1, sha=sha)], emitter="projects",
                                 correlation="demande", origin=Origin.GENESIS)
        # hors d'une relecture : refusés
        plain = _tool_context(kernel, pid, "review_verdict", reviewing=False)
        out["outside"] = [await review.review_verdict(review.VerdictArgs(verdict="good"), plain),
                          await review.review_list(review.ListArgs(), plain)]
        ctx = _tool_context(kernel, pid, "review_verdict", reviewing=True)
        out["listed"] = await review.review_list(review.ListArgs(), ctx)
        out["empty"] = await review.review_verdict(review.VerdictArgs(verdict="findings"), ctx)
        out["both"] = await review.review_verdict(review.VerdictArgs(
            verdict="good", findings=[review.Finding(where="carnet.md", what="rien")]), ctx)
        out["before"] = len(events(kernel, REVIEWED))
        out["verdict"] = await review.review_verdict(review.VerdictArgs(verdict="findings", findings=[
            review.Finding(where="carnet.md, ligne 1", what="Il manque la date.")]), ctx)
        out["event"] = events(kernel, REVIEWED)[-1]
        out["objective"] = _objective(kernel, pid)
        out["offered"] = sorted(n for n, t in kernel.mind.registry.tools.items() if t.bundle == review.BUNDLE)
        out["specs"] = {n: (t.acts, sorted(t.episodes)) for n, t in kernel.mind.registry.tools.items()
                        if t.bundle == review.BUNDLE}
        return out, sha

    out, sha = live(tmp_path, scenario)
    assert all(isinstance(x, ToolResult) and not x.ok and "relecture indépendante" in x.content
               for x in out["outside"])
    assert "carnet.md" in out["listed"]
    assert not out["empty"].ok and not out["both"].ok and out["before"] == 0
    # le verdict conclut la boucle, et se pose sur l'objectif pour le commit relu
    assert out["verdict"].ok and out["verdict"].ends
    d = out["event"].data
    assert (d.sha, d.good, d.by, d.findings.text) == (sha, False, "fake", "- carnet.md, ligne 1 : Il manque la date.")
    o = out["objective"]
    assert (o.reviewed, o.review_ok, o.status, len(o.review_refused)) == (sha, False, c.OPEN, 1)
    # son lot : quatre outils, pour une exécution impersonnelle — le seul qui écrit quelque chose est son verdict
    assert out["offered"] == ["review_list", "review_read", "review_run", "review_verdict"]
    assert {n: acts for n, (acts, _) in out["specs"].items() if acts} == {"review_verdict": True}
    assert all(kinds == [Kind.JOB] for _, kinds in out["specs"].values())


# ── Son rôle de modèle, son mode, la console ───────────────────────────────


def test_the_review_has_its_own_model_role_and_its_mode_is_never_asked_by_a_message():
    # un rôle à elle, que l'opérateur route où il veut ; sans réglage, celui des exécutions impersonnelles
    assert str(Role.REVIEW) in ROLES and "relire" in ROLE_LABELS[str(Role.REVIEW)]
    assert FALLBACKS[Role.REVIEW] == Role.JOB and Role.REVIEW not in composition.VOICE_ROLES
    mode = composition.modes()[REVIEW]
    policy = mode.applied(composition.policies()[Kind.JOB])
    assert mode.kinds == frozenset({Kind.JOB}) and policy.role == Role.REVIEW and not policy.voice
    assert policy.max_tool_turns == composition.REVIEW_TURNS < composition.WORK_TURNS
    assert REVIEW not in MODES  # un message ne peut pas le demander : seul son candidat le fait
    # son lot n'est pas de ceux qu'un projet choisit, et il est en main pendant une relecture
    assert review.BUNDLE not in composition.PROJECT_TOOLS and review.BUNDLE in policy.tool_bundles
    assert review.BUNDLE in policy.core_bundles


def test_the_console_says_the_setting_the_last_verdict_and_the_verdict_of_a_proposal():
    p = Project(7, "t", c.USER, created_at=0, remote=URL, flow=c.FLOW_PR)
    # absent d'un formulaire, le réglage garde sa valeur (un formulaire d'avant l'ADR 0276 reste valable)
    assert "reread" in ModifyArgs.model_fields and ModifyArgs.model_fields["reread"].default is None
    assert [k for k, _ in inspect_reviews.REREAD_CHOICES] == list(c.REREADS)
    good = Objective(id=1, text_ref="t", reviewed=SHA, review_ok=True, review_by="opus")
    assert inspect_reviews.review_words(p, good) == f"relu au commit {SHA[:12]} par « opus » : bon"
    assert inspect_reviews.review_line(p, good, SHA) == f"Relecture indépendante : bon, au commit {SHA[:12]} par « opus »."
    assert "aucun verdict favorable" in inspect_reviews.review_line(p, good, OTHER)
    assert "n'en demande pas" in inspect_reviews.review_line(replace(p, reread=c.REREAD_NEVER), good, SHA)
    bad = replace(good, review_ok=False, review_ref="r2", review_refused=("r1", "r2"))
    [prose] = inspect_reviews.detail(p, bad, {"r1": "- a.py : le premier", "r2": "- b.py : le second"})
    assert prose.title == inspect_reviews.TITLE and "refusé (2 refus de suite)" in prose.text
    assert "la main est à toi" in prose.text and "- b.py : le second" in prose.text and "- a.py : le premier" in prose.text
    assert inspect_reviews.detail(p, Objective(id=2, text_ref="t"), {}) == []
    assert inspect_reviews.refs([bad]) == ["r2", "r1", "r2"]
