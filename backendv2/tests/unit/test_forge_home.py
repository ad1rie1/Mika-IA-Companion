"""Une app a un foyer (ADR 0104) — par leurs intentions.

- un projet à elle peut forger : elle se donne la Forge en l'ouvrant, ou en cours
  de route (``project_equip``), et l'exécution suivante l'a en main ; une
  exploration devenue projet garde ses mains ;
- elle ne se donne que de quoi fabriquer et observer (``SELF_BUNDLES``) : ni le
  courrier, ni la caméra ; un projet confié garde le cadre qu'on lui a donné ;
- une exécution sait ce qui lui manque : elle ne devine pas ses outils ;
- « je vais essayer de me monter un outil pour ça », dit à sa propriétaire sans
  appeler d'outil, ne s'évapore pas : la promesse de travail met en route une
  exploration qui a la Forge — faite à une amie, ou sans travail, non.
"""

from __future__ import annotations

import asyncio
import html
import http.server
import ipaddress
import json
import re
import shutil
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import get_args

import pytest

from mika.adapters import forge as forge_adapter
from mika.adapters.forge import ForgeHost, checked_headers, read_manifest
from mika.adapters.forge.manifest import coherence, signatures
from mika.app.composition import policies
from mika.contracts import forge as forge_c
from mika.contracts import goals as goals_c
from mika.contracts import memory as memory_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects.faculty import NUDGED, SELF_BUNDLES, subject_of
from mika.faculties.projects.prompt import app_lines, missing_tools
from mika.faculties.projects.tools import EquipArgs, SelfBundle, StartArgs, project_equip, start_project
from mika.kernel.clock import HOUR, MINUTE, US
from mika.kernel.events import Content, Origin
from mika.kernel.faculty import proving_tools
from mika.kernel.frame import Audience, EpisodeRef, Frame
from mika.kernel.state import FrozenDict
from mika.plugins.forge import (
    INSTALL,
    SWITCHED,
    TICKED,
    App,
    ForgeState,
    WriteArgs,
    _install_resolved,
    concerns,
    forge_write,
    guide,
    install_draft,
    written_draft,
)
from mika.plugins.forge import (
    TestArgs as ForgeTestArgs,
)
from mika.plugins.forge.guide import VEILLE_CODE, VEILLE_MANIFEST
from mika.ports.llm import LLMResponse, ToolCall
from mika.runtime.tools import ToolContext, offer
from mika.sim.clock import SimClock, run_virtual
from mika.sim.llm.persona import PersonaSimLLM
from mika.vocab.episodes import Kind, goal_target, project_target
from mika.vocab.privacy import ChannelTrust
from tests.fixtures.atelier import Atelier
from tests.fixtures.console_html import ConsoleHTML
from tests.fixtures.harness import events_of
from tests.fixtures.memory import seq_of, token
from tests.fixtures.mika import boot, build, connect, disconnect, reply
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée
from tests.unit.test_forge_console import ADRIEN, WORKING, FakeApi, _content, _her_tool
from tests.unit.test_projects import MONDAY, _context, create, events, live
from tests.unit.test_promises_and_moments import Script, chat
from tests.unit.test_promises_and_moments import events as named
from tests.unit.test_promises_and_moments import run as converse


def _run_offer(kernel, project) -> set[str]:
    """Ce qu'une exécution de ce projet aurait en main : la politique ``WORK``, restreinte à ses lots."""
    working = Audience(persons=(), channel="internal", public=False, trust=ChannelTrust.INTERNAL.value, owner=True)
    tools = offer(kernel.mind.registry.tools, policies()[Kind.WORK], Kind.WORK, working, only=",".join(project.bundles))
    return set(tools)


def test_her_bundles_are_the_ones_she_can_give_herself():
    assert get_args(SelfBundle) == SELF_BUNDLES
    assert "email" not in SELF_BUNDLES and "camera" not in SELF_BUNDLES


def test_a_project_she_opens_with_the_forge_lets_its_runs_forge(tmp_path):
    async def scenario(kernel, llm):
        reply = _context(kernel, "start_project", Kind.REPLY, "user_1", Audience(owner=True))
        said = await start_project(StartArgs(title="Suivre la bourse", objectives=["Une app qui relève les cours"],
                                             tools=["forge", "forge_apps", "rss"]), reply)
        bare = _context(kernel, "start_project", Kind.REPLY, "user_1", Audience(owner=True))
        await start_project(StartArgs(title="Un carnet"), bare)
        projects = kernel.mind.frame().state("projects").projects
        return said, [projects[e.seq] for e in events(kernel, c.PROJECT_CREATED)], kernel

    said, (tooled, plain), kernel = live(tmp_path, scenario)
    assert "Projet ouvert" in said
    assert set(tooled.bundles) == {"projects", "workshop", "memory", "mcp.web", "forge", "forge_apps", "rss"}
    assert {"forge_write", "forge_edit", "forge_test", "forge_help"} <= _run_offer(kernel, tooled)
    # sans rien demander : son atelier, sa mémoire et le web (ADR 0105), pas la Forge
    assert plain.bundles == ("projects", "workshop", "memory", "mcp.web")
    assert "forge_write" not in _run_offer(kernel, plain)


def test_an_exploration_that_becomes_a_project_keeps_its_hands(tmp_path):
    async def scenario(kernel, llm):
        explo = await kernel.mind.append([goals_c.GOAL_OPENED.draft(
            kind=goals_c.EXPLORATION, authority=goals_c.SELF, title=Content.of("Mon app ne marche plus", level=0),
            bundles=("forge", "goals", "memory", "projects", "camera"), max_steps=8, source="genese",
            sensitivity=0, desire=0.9)], emitter="goals", correlation="genese", origin=Origin.GENESIS)
        ctx = _context(kernel, "start_project", Kind.STEP, goal_target(explo.seqs[-1]), Audience(owner=True))
        await start_project(StartArgs(title="Réparer mon app"), ctx)
        [created] = events(kernel, c.PROJECT_CREATED)
        return kernel.mind.frame().state("projects").projects[created.seq]

    p = live(tmp_path, scenario)
    assert "forge" in p.bundles  # la Forge de l'app à réparer…
    assert "camera" not in p.bundles  # …mais jamais ce qu'elle ne se donne pas elle-même


def test_she_equips_her_own_project_but_not_a_confided_one(tmp_path):
    async def scenario(kernel, llm):
        reply = _context(kernel, "start_project", Kind.REPLY, "user_1", Audience(owner=True))
        await start_project(StartArgs(title="Suivre la bourse", objectives=["Relever les cours"]), reply)
        mine = events(kernel, c.PROJECT_CREATED)[-1].seq
        confided = await create(kernel, "p1", title="Le module", objectives="Écrire le module")
        out = {}
        for pid in (mine, confided):
            ctx = _context(kernel, "project_equip", Kind.WORK, project_target(pid), Audience(owner=True))
            out[pid] = await project_equip(EquipArgs(tool="forge", why="écrire l'app qui relève les cours"), ctx)
        again = _context(kernel, "project_equip", Kind.WORK, project_target(mine), Audience(owner=True))
        out["again"] = await project_equip(EquipArgs(tool="forge", why="encore"), again)
        projects = kernel.mind.frame().state("projects").projects
        notes = kernel.mind.store.content(list(projects[mine].notes))
        return out, projects[mine], projects[confided], notes, kernel

    out, mine, confided, notes, kernel = live(tmp_path, scenario)
    assert "prochaine exécution" in out[mine.id]
    assert "forge" in mine.bundles and "forge_write" in _run_offer(kernel, mine)
    assert not out[confided.id].ok and "needs_you" in out[confided.id].content
    assert "forge" not in confided.bundles
    assert not out["again"].ok and "déjà" in out["again"].content
    # sa raison reste dans le carnet du projet
    assert any("relève les cours" in t for t in notes.values())


def test_a_run_is_told_what_it_lacks(tmp_path):
    async def scenario(kernel, llm):
        reply = _context(kernel, "start_project", Kind.REPLY, "user_1", Audience(owner=True))
        await start_project(StartArgs(title="Suivre la bourse", tools=["forge"]), reply)
        mine = events(kernel, c.PROJECT_CREATED)[-1].seq
        confided = await create(kernel, "p1", title="Le module", objectives="Écrire le module")
        projects = kernel.mind.frame().state("projects").projects
        return projects[mine], projects[confided]

    mine, confided = live(tmp_path, scenario)
    own = missing_tools(mine)
    assert "project_equip" in own and "flux" in own and "Forge" not in own  # elle a déjà la Forge
    assert "needs_you" in missing_tools(confided) and "project_equip" not in missing_tools(confided)


# ── Une intention ne se perd plus (L2) ────────────────────────────────────


@pytest.mark.parametrize("who,operator,work,opened,started", [
    ("Adrien", True, True, True, False),  # sa propriétaire, un travail : mis en route
    ("Bea", False, True, False, False),  # une amie : une promesse, pas un travail qu'on lui donne
    ("Adrien", True, False, False, False),  # un mot à dire n'est pas un travail
    ("Adrien", True, True, False, True),  # elle a déjà ouvert un projet pour lui : le travail est en route
])
def test_a_work_promise_to_her_owner_sets_out_with_the_forge(tmp_path, who, operator, work, opened, started):
    def extract(prompt):
        said = prompt.split("Les messages :", 1)[-1]
        if "bourse" not in said or "Promesses en cours" in prompt:
            return None
        return {"promesses": [{"texte": "me monter un petit outil pour suivre la bourse", "envers": token(prompt, who),
                               "travail": work, "messages": seq_of(prompt, "bourse")}]}

    def reply(message, req):
        if "bourse" in message and started and not any(m.role == "tool" for m in req.messages):
            return LLMResponse("", tool_calls=(ToolCall(f"{req.call_id}:p", "start_project", {
                "title": "Suivre la bourse", "objectives": ["Une app qui relève le cours"], "tools": ["forge"]}),),
                stop="tool_use")
        if "bourse" in message:  # elle annonce, sans appeler d'outil (la sonde du 12 octobre)
            return "Je peux essayer de me monter un petit outil dans ma Forge pour ça. [EMOTION:curious:0.4]"
        return None

    async def scenario(kernel):
        handle = "user_1" if operator else "user_2"
        await connect(kernel, handle, who, operator=operator)
        await chat(kernel, handle, ["ce serait bien que tu suives un peu la bourse, ça pourrait t'intéresser",
                                    "bon je file"])
        await disconnect(kernel, handle)
        await asyncio.sleep(3 * HOUR / US)
        return named(kernel, memory_c.PROMISE_NOTICED.name), named(kernel, goals_c.GOAL_OPENED.name), handle

    promised, goals, handle = converse(tmp_path, scenario, Script(reply, extract))
    assert len(promised) == 1 and promised[0].data.work == work
    kept = [g for g in goals if g.data.origin == goals_c.FROM_PROMISE]
    if not opened:
        assert kept == []
        return
    [g] = kept
    assert g.data.source == f"promise:{promised[0].seq}" and g.data.about == (handle,)
    assert "forge" in g.data.bundles and "projects" in g.data.bundles  # de quoi se fabriquer l'outil, ou un projet
    assert g.data.sensitivity >= 2  # ce qu'elle a promis à quelqu'un reste à cette personne


# ── Le guide dit vrai, l'essai couvre tout (L5) ───────────────────────────

#: ce que rendraient les taux de la BCE : l'euro à +2,82 % face au dollar depuis le jour ouvré précédent (la livre
#: aussi, pour une autre devise)
QUOTE = json.dumps({"amount": 1.0, "base": "EUR", "start_date": "2026-10-16", "end_date": "2026-10-26", "rates": {
    "2026-10-22": {"USD": 1.12, "GBP": 0.86}, "2026-10-23": {"USD": 1.1, "GBP": 0.86},
    "2026-10-26": {"USD": 1.131, "GBP": 0.87}}})


class WebApi(FakeApi):
    """L'api d'une app, avec un réseau qui rend toujours les mêmes taux."""

    def __init__(self, config):
        super().__init__(config)
        self.fetched: list[str] = []

    def http_get(self, url):
        self.fetched.append(url)
        return QUOTE


def test_the_watch_example_is_valid_and_watches_a_rate():
    manifest, problems = read_manifest(VEILLE_MANIFEST)
    code_problems, functions = signatures(VEILLE_CODE)
    assert problems == [] and code_problems == [] and coherence(manifest, functions) == []
    assert manifest["schedule"] == "cron:0 17 * * 1-5" and manifest["context"] and manifest["timeout"] == 20
    assert manifest["allowed_domains"] == []  # son réseau est libre (ADR 0105) : rien à déclarer
    [tool] = manifest["tools"]
    assert [a["key"] for a in tool["args"]] == ["devise"] and not tool["args"][0]["required"]
    api = WebApi({f["key"]: f["default"] for f in manifest["config_fields"]})
    app: dict = {}
    exec(compile(VEILLE_CODE, "main.py", "exec"), app)  # noqa: S102 — l'exemple lui-même
    got = app["tick"](api)
    assert got["ecart"] == 2.82 and api.fetched[0].startswith("https://api.frankfurter.dev/")  # une API ouverte
    assert api.signals and "2.82" in api.signals[0]  # un seuil franchi : elle est prévenue…
    app["tick"](api)
    assert len(api.signals) == 1  # …une fois par jour, pas à chaque battement
    assert "EUR/USD" in app["context"](api) and app["tool_maintenant"](api, {"devise": ""})["taux"] == 1.131
    other = app["tool_maintenant"](api, {"devise": "gbp"})  # une autre devise, juste pour le dire
    assert other["devise"] == "GBP" and "to=GBP" in api.fetched[-1] and len(api.signals) == 1
    text = guide.topic("veille")
    assert "http_get" in text and "file de l'app" in text and "interval:1h" in text and "tick(api)" in text
    assert VEILLE_CODE in text and VEILLE_MANIFEST in text  # l'exemple montré est celui qui tourne


needs_bwrap = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap absent")


def fake_forge(tmp_path: Path):
    """Un noyau et un hôte réel dont le réseau rend toujours les mêmes taux (rien ne sort de la machine)."""
    forge = ForgeHost(tmp_path / "forge", http_get=lambda url: QUOTE, public=lambda host: True)
    kernel, clock, _, _ = build(tmp_path, reply("d'accord [EMOTION:neutral:0.3]"), ports={"forge": forge})
    return kernel, clock, forge


FAINT = """\
title: Murmure
schedule: manual
"""
FAINT_CODE = """\
def tick(api):
    api.signal("rien", pertinence=0.3)
    api.signal("encore", pertinence=0.9)
    return 1
"""


@needs_bwrap
def test_forge_test_tries_what_she_wrote_and_its_signals_really_go_to_the_queue(tmp_path):
    """Un essai est un vrai passage (sonde du 2026-10-13) : ce qu'il range reste dans la base, alors ce qu'il signale
    part dans la file — sinon le passage planifié suivant ne trouve plus rien de « nouveau » et la nouveauté se perd
    sans bruit. Le résultat le dit au présent."""
    kernel, clock, forge = fake_forge(tmp_path)

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            out = {"écrite": await _her_tool(kernel, "forge_write", {"app": "cours", "manifest": VEILLE_MANIFEST,
                                                                      "code": VEILLE_CODE}),
                   "murmure": await _her_tool(kernel, "forge_write", {"app": "murmure", "manifest": FAINT,
                                                                       "code": FAINT_CODE})}
            for method, extra in (("tick", {}), ("context", {}), ("tool_maintenant", {}), ("tool_inconnu", {}),
                                  ("view_cours", {}), ("on_event", {"summary": "un titre"})):
                out[method] = await _her_tool(kernel, "forge_test", {"app": "cours", "method": method, "args": extra})
            out["faint"] = await _her_tool(kernel, "forge_test", {"app": "murmure", "method": "tick"})
            out["queued"] = [e.data.app for e in events_of(kernel, forge_c.QUEUED.name)]
            out["queue"] = len(kernel.mind.frame().state("forge").apps["murmure"].queue)
            return out
        finally:
            forge.shutdown()
            await kernel.stop()

    out = run_virtual(clock, main)
    assert "Écrite" in _content(out["écrite"])
    tick = _content(out["tick"])
    assert out["tick"].ok and "1.131" in tick and "sa file" in tick  # il irait dans la file de l'app (ADR 0105)
    assert out["context"].ok and "EUR/USD" in _content(out["context"])
    assert out["tool_maintenant"].ok and "ecart" in _content(out["tool_maintenant"])
    assert not out["tool_inconnu"].ok
    assert out["view_cours"].ok
    assert not out["on_event"].ok  # elle n'a pas écrit on_event : l'hôte refuse une fonction absente
    faint = _content(out["faint"])
    assert "Ses 2 signal(aux) sont partis dans sa file" in faint  # les deux : c'est à elle de juger, en les lisant
    assert out["queued"].count("murmure") == 2 and out["queue"] == 2  # vraiment dans sa file, pas seulement dits


# ── La preuve se déclare sur l'outil (L6) ─────────────────────────────────


def test_a_declared_proof_outweighs_the_rule_of_whoever_judges():
    calls = [("forge_list", True), ("forge_test", True), ("rss_read", True), ("forge_write", False)]
    proofs = [False, True, None, None]
    everything = lambda name: True  # noqa: E731 — la règle d'un but : tout ce qui touche autre chose que sa tête
    assert proving_tools(calls, proofs, everything) == ("forge_test", "rss_read")  # relire sa Forge ne prouve rien
    assert proving_tools(calls, proofs, lambda name: False) == ("forge_test",)
    assert proving_tools(calls, [], everything) == ("forge_list", "forge_test", "rss_read")  # un appel d'avant


def _same_episode(kernel, episode: str):
    """Ses outils de Forge, appelés dans un même épisode (une réponse à Adrien)."""
    mind = kernel.mind
    ref = EpisodeRef(episode, Kind.REPLY, target="user_1")
    n = iter(range(1000))

    def call(name, args):
        frame = Frame(mind.frame().root, mind.clock.now(), mind.registry, ADRIEN, ref)
        spec = mind.registry.tools[name]
        return spec.handler(spec.args(**args), ToolContext(mind, spec, f"{episode}-{next(n)}", episode, frame,
                                                           ports=kernel.ports))
    return call


@needs_bwrap
def test_writing_an_app_proves_nothing_until_it_has_been_tried(tmp_path):
    kernel, clock, forge = fake_forge(tmp_path)

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            here = _same_episode(kernel, "ep-ici")
            out = {"écrite": await here("forge_write", {"app": "cours", "manifest": VEILLE_MANIFEST,
                                                         "code": VEILLE_CODE}),
                   "lue": await here("forge_list", {}),
                   "essayée": await here("forge_test", {"app": "cours", "method": "tick"})}
            later = _same_episode(kernel, "ep-plus-tard")
            out["essayée plus tard"] = await later("forge_test", {"app": "cours", "method": "tick"})
            out["relancée"] = await later("forge_command", {"app": "cours", "command": "enable"})
            return out
        finally:
            forge.shutdown()
            await kernel.stop()

    out = run_virtual(clock, main)
    assert out["écrite"].ok and out["écrite"].proof is False  # pas encore essayée : rien de prouvé
    assert out["lue"].proof is False
    assert out["essayée"].ok and out["essayée"].proof is True  # écrite et essayée ici : une app qui marche
    assert out["essayée plus tard"].ok and out["essayée plus tard"].proof is False  # l'essai seul ne prouve rien
    assert out["relancée"].proof is False  # réactiver n'est pas réparer


# ── Une app a un foyer (L3) ───────────────────────────────────────────────


def _project_kernel(tmp_path):
    """Un noyau avec une Forge au réseau simulé, et le harnais des projets (Adrien, propriétaire, connecté)."""
    forge = ForgeHost(tmp_path / "forge", http_get=lambda url: QUOTE, public=lambda host: True)
    clock = SimClock(MONDAY)
    llm = PersonaSimLLM(clock, seed=1, abstain_rate=0.0, latency=2.0)
    kernel, clock, _, _ = build(tmp_path, None, clock=clock, llm=llm, ports={"workshop": Atelier(), "forge": forge})
    return kernel, clock, forge


@needs_bwrap
def test_an_app_written_during_a_run_lives_there_and_its_breakage_asks_for_a_repair(tmp_path):
    kernel, clock, forge = _project_kernel(tmp_path)

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            reply = _context(kernel, "start_project", Kind.REPLY, "user_1", Audience(owner=True))
            await start_project(StartArgs(title="Suivre la bourse", objectives=["Une app qui relève le CAC 40"],
                                          tools=["forge"]), reply)
            pid = events(kernel, c.PROJECT_CREATED)[-1].seq
            run = _context(kernel, "forge_write", Kind.WORK, project_target(pid), Audience(owner=True), bundles="forge")
            wrote = await forge_write(WriteArgs(app="cours", manifest=VEILLE_MANIFEST, code=VEILLE_CODE), run)
            frame = kernel.mind.frame()
            app = next(a for a in frame.get(forge_c.APPS) if a.name == "cours")
            state_app = frame.state("forge").apps["cours"]
            who = concerns(frame, state_app)
            await kernel.mind.append([SWITCHED.draft(app="cours", state="broken", reason="HTTP 503")],
                                     emitter="forge", correlation="genese", origin=Origin.GENESIS)
            broke = kernel.mind.frame()
            lines = app_lines(broke.state("projects").projects[pid], broke)  # ce que voit l'exécution à cet instant
            await asyncio.sleep(5 * MINUTE / US)
            frame = kernel.mind.frame()
            p = frame.state("projects").projects[pid]
            nudges = [e for e in events(kernel, NUDGED) if e.data.project == pid]
            reports = [e for e in events(kernel, c.RUN_REPORTED) if e.data.project == pid]
            return wrote, app, who, p, lines, nudges, reports
        finally:
            forge.shutdown()
            await kernel.stop()

    wrote, app, who, p, lines, nudges, reports = run_virtual(clock, main)
    assert "Écrite" in wrote.content and app.project == p.id  # écrite pendant une exécution : elle y vit
    assert who[0] == ("user_1",) and who[1] >= 2  # ce qu'elle trouve concerne Adrien, au niveau du projet
    [repair] = [o for o in p.objectives if o.app]
    assert repair.app == "cours@1" and repair.author == "self"
    # l'exécution lancée l'a réparée (réécrite, puis essayée) : c'est l'essai qui la prouve, jamais un fichier de
    # l'atelier
    closing = [r for r in reports if r.data.objective == repair.id and r.data.proven]
    assert repair.status != c.DONE or (closing and closing[-1].data.proof == "outil")
    assert nudges and nudges[-1].data.objective == repair.id  # une exécution tout de suite
    assert any("cours" in line and "en panne" in line and "HTTP 503" in line for line in lines)
    # leurs rythmes suivent son heure : elle se demandait si leur cron tournait en UTC (sonde du 2026-10-13)
    assert any("Europe/Paris" in line and "pas l'UTC" in line for line in lines)


def test_a_version_waiting_for_approval_is_a_card_in_her_owners_chat_and_a_refusal_comes_back():
    draft = install_draft("cours", "abc", None, "un secret", decider="user_1")
    assert json.loads(draft.data.args_json)[rt.DECIDER] == "user_1"
    assert rt.DECIDER not in json.loads(install_draft("cours", "abc", None, "un secret").data.args_json)
    state = ForgeState(apps=FrozenDict({"cours": App("Suivi", 2)}), installs=FrozenDict({41: "cours"}))
    resolved = SimpleNamespace(data=SimpleNamespace(proposal=41, owner="forge", capability=INSTALL, approved=False))
    after = _install_resolved(state, resolved, None)
    assert after.apps["cours"].install_refused and 41 not in after.installs  # elle le sait ; plus en attente
    approved = SimpleNamespace(data=SimpleNamespace(proposal=41, owner="forge", capability=INSTALL, approved=True))
    assert not _install_resolved(state, approved, None).apps["cours"].install_refused


def test_her_own_project_asks_for_help_too(tmp_path):
    from mika.faculties.projects.tools import ReportArgs, report_run
    from mika.faculties.projects.work import _need

    async def scenario(kernel, llm):
        reply = _context(kernel, "start_project", Kind.REPLY, "user_1", Audience(owner=True))
        await start_project(StartArgs(title="Suivre la bourse", objectives=["Relever le cours"], tools=["forge"]),
                            reply)
        pid = events(kernel, c.PROJECT_CREATED)[-1].seq
        oid = kernel.mind.frame().state("projects").projects[pid].objectives[0].id
        run = _context(kernel, "report_run", Kind.WORK, project_target(pid), Audience(owner=True))
        run.frame = run.frame.with_episode(EpisodeRef(run.episode_id, Kind.WORK, target=project_target(pid),
                                                      attrs=FrozenDict({"subject": subject_of(pid, oid)})),
                                           run.frame.audience)
        await report_run(ReportArgs(verdict="wait", summary="Il me faut une clé d'API pour ce site.",
                                    needs_you="une clé d'API pour le site des cours"), run)
        frame = kernel.mind.frame()
        return _need(frame.state("projects"), frame)

    candidates = live(tmp_path, scenario)
    assert [cand.target for cand in candidates] == ["user_1"]  # à qui s'occupe d'elle : un projet à elle demande


# ── Ses actions deviennent de vrais outils (L10) ──────────────────────────

SECRET_MANIFEST = VEILLE_MANIFEST.replace("config:\n", "config:\n  - {key: cle, type: secret, label: Clé}\n")


@needs_bwrap
def test_each_app_announces_itself_and_its_actions_are_her_tools(tmp_path):
    kernel, clock, forge = fake_forge(tmp_path)
    forge.on_change(kernel.refresh_tools)
    keys = {"coffre": {"cle": "abc"}}
    kernel.ports["forge_settings"] = SimpleNamespace(values=lambda app: keys.get(app, {}))

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            here = _same_episode(kernel, "ep-ecrire")
            await here("forge_write", {"app": "cours", "manifest": VEILLE_MANIFEST, "code": VEILLE_CODE})
            await here("forge_write", {"app": "coffre", "manifest": SECRET_MANIFEST, "code": VEILLE_CODE})
            registry = kernel.mind.registry
            frame = kernel.mind.frame()
            owner = offer(registry.tools, policies()[Kind.REPLY], Kind.REPLY, ADRIEN, frame=frame)
            stranger = offer(registry.tools, policies()[Kind.REPLY], Kind.REPLY, Audience(owner=False), frame=frame)
            talk = _same_episode(kernel, "ep-parler")
            out = {"agir": await talk("cours_maintenant", {}), "lire": await talk("cours_pages", {}),
                   "coffre": await talk("coffre_maintenant", {})}
            work = _context(kernel, "coffre_maintenant", Kind.WORK, project_target(1), WORKING)
            out["coffre au travail"] = await registry.tools["coffre_maintenant"].handler(
                registry.tools["coffre_maintenant"].args(), work)
            await here("forge_command", {"app": "coffre", "command": "erase"})
            return owner, stranger, dict(registry.bundles), set(registry.tools), out
        finally:
            forge.shutdown()
            await kernel.stop()

    owner, stranger, bundles, after, out = run_virtual(clock, main)
    spec = owner["cours_maintenant"]
    assert spec.bundle == "forge_apps.cours" and spec.in_hand and "Suivi d'un cours" in spec.description
    assert "cours_pages" in owner and "Suivi d'un cours" in bundles["forge_apps.cours"]  # elle s'annonce
    assert not {"cours_maintenant", "cours_pages"} & set(stranger)  # pas devant n'importe qui
    assert out["agir"].ok and "1.131" in out["agir"].content
    assert out["lire"].ok and "Cours" in out["lire"].content and out["lire"].proof is False  # lire n'est pas faire
    assert not out["coffre"].ok and "promue" in out["coffre"].content  # des secrets : pas en conversation…
    assert out["coffre au travail"].ok  # …mais au travail, oui
    assert "coffre_maintenant" not in after and "cours_maintenant" in after  # effacée : ses outils partent avec elle


# ── Un exécuteur de plusieurs services (L9) ───────────────────────────────

SERVICES = """\
title: Deux services
schedule: manual
services:
  - {name: vite, schedule: interval:5m, description: compter}
  - {name: casse, schedule: interval:5m, description: rater}
"""
SERVICES_CODE = """\
def service_vite(api):
    n = api.kv_get("n", 0) + 1
    api.kv_set("n", n)
    return n


def service_casse(api):
    raise ValueError("la source a disparu")
"""


def test_services_are_read_checked_and_each_needs_its_function():
    manifest, problems = read_manifest(SERVICES)
    assert problems == [] and [x["name"] for x in manifest["services"]] == ["vite", "casse"]
    _, functions = signatures(SERVICES_CODE)
    assert coherence(manifest, functions) == []
    assert coherence(manifest, signatures("def service_vite(api):\n    return 1\n")[1]) == [
        "le service « casse » est déclaré sans fonction service_casse(api)"]
    bad, said = read_manifest("title: X\nservices:\n  - {name: tick, schedule: interval:1h}\n"
                              "  - {name: jamais, schedule: manual}\n")
    assert bad["services"] == [] and any("« tick »" in x for x in said) and any("un rythme" in x for x in said)
    assert ForgeTestArgs(app="deux", method="service_vite").method == "service_vite"


@needs_bwrap
def test_each_service_runs_on_its_own_and_a_broken_one_does_not_stop_the_others(tmp_path):
    kernel, clock, forge = fake_forge(tmp_path)

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            here = _same_episode(kernel, "ep-services")
            await here("forge_write", {"app": "deux", "manifest": SERVICES, "code": SERVICES_CODE})
            await asyncio.sleep(HOUR / US)
            frame = kernel.mind.frame()
            ticks = [e for e in events(kernel, TICKED) if e.data.app == "deux"]
            return ticks, next(a for a in frame.get(forge_c.APPS) if a.name == "deux"), \
                events(kernel, goals_c.GOAL_OPENED)
        finally:
            forge.shutdown()
            await kernel.stop()

    ticks, app, opened = run_virtual(clock, main)
    fast = [t for t in ticks if t.data.service == "vite"]
    broken = [t for t in ticks if t.data.service == "casse"]
    assert [t.data.ok for t in broken] == [False] * 5  # cinq échecs, puis son disjoncteur l'arrête…
    assert len(fast) >= 10 and all(t.data.ok for t in fast)  # …et l'autre continue toute l'heure
    assert fast[-1].at > broken[-1].at
    assert app.enabled and not app.broken and "la source a disparu" in dict(app.broken_services)["casse"]
    assert app.services == ("vite", "casse")
    repairs = [g for g in opened if g.data.origin == goals_c.FROM_REPAIR]
    assert len(repairs) == 1 and "casse" in repairs[0].data.details.text  # sa réparation s'ouvre quand même


# ── Les petits trous de la forge (L7) ─────────────────────────────────────


def test_an_app_sends_the_headers_it_wants_but_not_the_ones_the_host_sets():
    """Son réseau est libre (ADR 0105) : ses en-têtes (une clé, un cookie, une langue, son nom de client), mais pas
    ceux qui disent quelle machine joindre ou comment lire la réponse ; et ses domaines ne sont plus qu'indicatifs."""
    sent = {"Accept": "application/json", "X-Api-Key": "k", "Cookie": "s=1", "Accept-Language": "fr",
            "User-Agent": "Mika (+https://exemple.fr)", "If-None-Match": '"abc"'}
    assert checked_headers(sent) == sent
    for bad in ({"Host": "ailleurs"}, {"Content-Length": "9"}, {"Authorization": "a\r\nX: b"}, ["Accept"],
                {"mal nommé": "x"}):
        with pytest.raises(ValueError):
            checked_headers(bad)
    many = "title: X\nallowed_domains: [" + ", ".join(f"d{i}.fr" for i in range(11)) + "]\n"
    manifest, problems = read_manifest(many)
    assert problems == [] and len(manifest["allowed_domains"]) == 11


def test_a_redirect_is_followed_and_a_key_does_not_follow_it_elsewhere(monkeypatch):
    """Une redirection est suivie (ADR 0105), chaque saut revérifié ; vers une autre machine, la clé reste en
    arrière. Une méthode et un corps partent tels quels ; une erreur HTTP est une réponse."""
    seen: list[tuple[str, str, str, str]] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def _answer(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode() if length else ""
            seen.append((self.command, self.headers.get("Host", ""), self.headers.get("Authorization", ""), body))
            if self.path == "/ailleurs":
                self.send_response(302)
                self.send_header("Location", f"http://autre.exemple.fr:{port}/cours")
                self.end_headers()
                return
            if self.path == "/absent":
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"introuvable")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(b'{"ok": 1}')

        do_GET = do_POST = _answer  # noqa: N815 — les noms qu'attend http.server

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    monkeypatch.setattr(forge_adapter, "resolve_public", lambda host, p=443: [ipaddress.ip_address("127.0.0.1")])
    try:
        got = forge_adapter.real_http_get(f"http://cours.exemple.fr:{port}/cours", headers={"Authorization": "Bearer k"})
        assert got == '{"ok": 1}' and seen[-1][2] == "Bearer k"
        moved = forge_adapter.real_http("GET", f"http://cours.exemple.fr:{port}/ailleurs",
                                        headers={"Authorization": "Bearer k"})
        assert moved["status"] == 200 and moved["url"] == f"http://autre.exemple.fr:{port}/cours"
        assert seen[-1][1].startswith("autre.exemple.fr") and seen[-1][2] == ""  # la clé n'a pas suivi
        posted = forge_adapter.real_http("POST", f"http://cours.exemple.fr:{port}/cours", body=b'{"q": 1}',
                                         headers={"Content-Type": "application/json"})
        assert posted["status"] == 200 and seen[-1][0] == "POST" and seen[-1][3] == '{"q": 1}'
        assert posted["headers"]["content-type"].startswith("application/json")
        missing = forge_adapter.real_http("GET", f"http://cours.exemple.fr:{port}/absent")
        assert missing["status"] == 404 and missing["body"] == b"introuvable"
        with pytest.raises(RuntimeError, match="HTTP 404"):
            forge_adapter.real_http_get(f"http://cours.exemple.fr:{port}/absent")
    finally:
        server.shutdown()


EMITTER = "title: Source\nschedule: interval:5m\n"
EMITTER_CODE = "def tick(api):\n    api.emit('prix', {'v': 42})\n    return 1\n"
LISTENER_APP = "title: Oreille\nschedule: manual\ncontext: true\nevents: [forge.source.*]\n"
LISTENER_CODE = """\
def on_event(api, e):
    api.kv_set("recu", e)


def context(api):
    return str(api.kv_get("recu", ""))
"""


@needs_bwrap
def test_what_an_app_emits_reaches_the_apps_that_listen(tmp_path):
    kernel, clock, forge = fake_forge(tmp_path)

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            here = _same_episode(kernel, "ep-emettre")
            await here("forge_write", {"app": "oreille", "manifest": LISTENER_APP, "code": LISTENER_CODE})
            await here("forge_write", {"app": "source", "manifest": EMITTER, "code": EMITTER_CODE})
            await asyncio.sleep(20 * MINUTE / US)
            return (await forge.call("oreille", "context")).value
        finally:
            forge.shutdown()
            await kernel.stop()

    heard = run_virtual(clock, main)
    assert "forge.source.prix" in heard and "42" in heard  # une émission n'arrive plus nulle part


def test_the_apps_section_carries_the_level_of_what_it_concerns():
    from mika.plugins.forge import _section

    got = _section(ForgeState(), None, {"apps": {"lines": {"Suivi d'un cours": "CAC : 7300"}, "level": 2}})
    assert got.level == 2 and "CAC : 7300" in got.content
    assert _section(ForgeState(), None, {}) is None


# ── Ses pages et ses réglages dans la Forge (L11) ─────────────────────────

TWO_PAGES = """\
title: Deux pages
schedule: manual
config:
  - {key: ville, type: str, label: Ville, default: Paris}
views:
  - {key: cours, label: Le cours}
  - {key: histoire, label: Son histoire}
"""
TWO_PAGES_CODE = """\
def view_cours(api, params):
    return {"version": 2, "blocks": [{"type": "note", "text": "page du cours"}]}


def view_histoire(api, params):
    return {"version": 2, "blocks": [{"type": "note", "text": "page de l'histoire"}]}
"""


def _tabs(body: str) -> list[str]:
    bar = re.search(r'<nav class="tabs" aria-label="Onglets">(.*?)</nav>', body, re.S)
    return re.findall(r'>([^<>]+)</a>', bar.group(1)) if bar else []


def _gear(body: str) -> list[str]:
    panel = re.search(r'<nav class="gear-panel"[^>]*>(.*?)</nav>', body, re.S)
    return re.findall(r'>([^<>]+)</a>', panel.group(1)) if panel else []


@needs_bwrap
def test_an_apps_pages_are_its_tabs_and_its_settings_sit_behind_the_gear(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    forge, kernel = live.kernel.ports["forge"], live.kernel
    client.portal.call(forge.write, "deux", TWO_PAGES, TWO_PAGES_CODE)
    draft = written_draft(forge.info("deux"))
    client.portal.call(lambda: kernel.mind.append([draft], emitter="forge", correlation="t", origin=Origin.GENESIS))
    first = html.unescape(client.get("/inspecteur/fiche/app/deux").text)
    assert _tabs(first) == ["Le cours", "Son histoire", "Accès"]  # ses pages sont ses onglets…
    assert "page du cours" in first
    assert _gear(first) == ["Réglages", "État", "Code", "Base", "Journal", "Vécu"]  # …le reste derrière la roue
    second = html.unescape(client.get("/inspecteur/fiche/app/deux?onglet=vues&vue=histoire").text)
    assert "page de l'histoire" in second and 'class="tab on" href="/inspecteur/fiche/app/deux?onglet=vues&vue=histoire"' \
        in second.replace("&amp;", "&")
    settings = html.unescape(client.get("/inspecteur/fiche/app/deux?onglet=reglages").text)
    assert 'class="gear-menu on"' in settings and 'class="tab on"' not in settings and "Ville" in settings
    ConsoleHTML(client.get("/inspecteur/fiche/app/deux").text).check()


# ── Une preuve par version (ADR 0161) ─────────────────────────────────────


@needs_bwrap
def test_an_app_written_by_a_run_that_failed_is_proven_by_the_next_runs_test(tmp_path):
    """Une app écrite par une exécution qui n'a pas abouti ne se prouvait plus : seul un essai dans l'épisode qui
    l'avait écrite comptait. Une version de son projet qu'aucun essai n'a prouvée se prouve à l'essai suivant — une
    fois crédité par le compte rendu de son exécution ; une exécution qui n'aboutit pas ne consomme rien. Une app
    relancée après une panne se prouve dans l'épisode qui l'a relancée."""
    from mika.plugins.forge import CommandArgs, forge_command, forge_test

    kernel, clock, forge = _project_kernel(tmp_path)

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            reply = _context(kernel, "start_project", Kind.REPLY, "user_1", Audience(owner=True))
            await start_project(StartArgs(title="Suivre l'euro", objectives=["Une app"], tools=["forge"]), reply)
            pid = events(kernel, c.PROJECT_CREATED)[-1].seq

            def run(name):
                return _context(kernel, name, Kind.WORK, project_target(pid), Audience(owner=True), bundles="forge")

            async def ended(ctx, reported: bool) -> None:  # la fin de son exécution, créditée ou non
                if reported:
                    await kernel.mind.append([c.RUN_REPORTED.draft(
                        project=pid, objective=1, verdict="done", proof="outil", proven=True,
                        summary=Content.of("Fait.", level=1))], emitter="projects", correlation=ctx.episode_id,
                        origin=Origin.KERNEL)
                await kernel.mind.append([rt.EPISODE_ENDED.draft(kind=Kind.WORK, outcome="done" if reported
                                                                 else "timeout", target=project_target(pid))],
                                         emitter="runtime", correlation=ctx.episode_id, origin=Origin.KERNEL)

            await forge_write(WriteArgs(app="cours", manifest=VEILLE_MANIFEST, code=VEILLE_CODE), run("forge_write"))
            failed = run("forge_test")
            out = {"panne": await forge_test(ForgeTestArgs(app="cours", method="tick"), failed)}
            await ended(failed, reported=False)  # son délai passe : rien n'est consommé
            credited = run("forge_test")
            out["suivante"] = await forge_test(ForgeTestArgs(app="cours", method="tick"), credited)
            await ended(credited, reported=True)
            out["encore"] = await forge_test(ForgeTestArgs(app="cours", method="tick"), run("forge_test"))
            out["contexte"] = await forge_test(ForgeTestArgs(app="cours", method="context"), run("forge_test"))
            await kernel.mind.append([SWITCHED.draft(app="cours", state="broken", reason="HTTP 503")],
                                     emitter="forge", correlation="genese", origin=Origin.GENESIS)
            revive = run("forge_command")
            out["relancée"] = await forge_command(CommandArgs(app="cours", command="enable"), revive)
            mind = kernel.mind
            same = Frame(mind.frame().root, mind.clock.now(), mind.registry, Audience(owner=True),
                         revive.frame.episode)
            spec = mind.registry.tools["forge_test"]
            out["réparée"] = await forge_test(ForgeTestArgs(app="cours", method="tick"), ToolContext(
                mind, spec, "appel-réparée", revive.episode_id, same, ports=kernel.ports))
            out["prouvée"] = mind.frame().state("forge").apps["cours"].proven
            return out
        finally:
            forge.shutdown()
            await kernel.stop()

    out = run_virtual(clock, main)
    assert out["panne"].proof is True  # il prouvait, mais son exécution n'a rien crédité…
    assert out["suivante"].ok and out["suivante"].proof is True  # …la suivante la prouve encore
    assert out["encore"].ok and out["encore"].proof is False  # déjà prouvée : un essai de plus ne prouve rien
    assert out["contexte"].proof is False  # sa ligne de contexte ne montre pas qu'elle travaille
    assert out["relancée"].proof is False and out["réparée"].proof is True  # relancée puis essayée ici : réparée
    assert out["prouvée"] == 1


def test_a_paced_app_without_tick_is_refused_at_writing():
    """Un rythme appelle tick : une app qui n'avait que des services échouait à chaque passage, jusqu'au
    disjoncteur."""
    assert any("sans fonction tick" in p for p in coherence({"schedule": "interval:1h"}, {}))
    assert not any("tick" in p for p in coherence({"schedule": "manual"}, {}))
    assert not coherence({"schedule": "cron:0 8 * * *"}, {"tick": 1})


def test_an_error_says_the_line_of_main_py_where_it_was_born():
    """« KeyError: 'rates' » ne disait pas quoi corriger : l'erreur dit sa ligne de main.py et son code."""
    from mika.adapters.forge import worker

    worker.SOURCE[:] = ["def tick(api):", "    rates = {}", "    return rates['eur']"]
    space: dict = {}
    exec(compile("\n".join(worker.SOURCE), "main.py", "exec"), space)  # noqa: S102 — le code d'une app d'essai
    try:
        space["tick"](None)
    except KeyError as exc:
        assert worker.where(exc) == " (main.py, ligne 3 : return rates['eur'])"
    try:
        compile("def tick(api)\n    pass", "main.py", "exec")
    except SyntaxError as exc:
        assert worker.where(exc).startswith(" (main.py, ligne 1")


def test_a_view_that_breaks_in_the_console_reaches_the_run_of_its_project(tmp_path):
    """Une vue rendue invalide dans la console se notait dans le journal de l'app, que personne ne relisait :
    l'exécution suivante de son projet le voit, jusqu'à la version suivante de l'app."""
    host = ForgeHost(tmp_path / "forge")

    async def main():
        await host.write("cours", VEILLE_MANIFEST, VEILLE_CODE)
        host.note("cours", "view_releves : enveloppe invalide dans la console — blocks[0].rows : une liste")
        host.note("cours", "view_releves : enveloppe invalide dans la console — blocks[0].rows : une liste")
        seen = host.problems("cours")
        await host.write("cours", VEILLE_MANIFEST, VEILLE_CODE + "\n")
        return seen, host.problems("cours")

    try:
        seen, after = asyncio.run(main())
    finally:
        host.shutdown()
    assert seen == ["view_releves : enveloppe invalide dans la console — blocks[0].rows : une liste"]  # une fois
    assert after == []  # la version suivante repart de zéro
    p = SimpleNamespace(id=7)
    frame = SimpleNamespace(get=lambda key: (forge_c.AppView("cours", "Cours", 2, True, "", 0, False, False, "manual",
                                                             project=7, ticked_at=0),) if key == forge_c.APPS else (),
                            now=0, env=SimpleNamespace(tz_of=lambda root: "Europe/Paris"), root=None)
    lines = "\n".join(app_lines(p, frame, {"cours": seen}))
    assert "vu dans la console depuis sa dernière version" in lines and "blocks[0].rows" in lines


def test_an_address_shown_in_an_error_or_the_journal_never_carries_its_query():
    """Une app validée met souvent sa clé dans l'adresse (``?apikey=…``) : une erreur ou son journal l'auraient
    gardée pour toujours. Ils montrent le schéma, l'hôte et le chemin."""
    from mika.adapters.forge import shown_url

    assert shown_url("https://api.exemple.fr/v1/cours?apikey=SECRET&d=EUR") == "https://api.exemple.fr/v1/cours?…"
    assert shown_url("https://moi:motdepasse@exemple.fr/flux#x") == "https://exemple.fr/flux?…"
    assert shown_url("https://exemple.fr/flux") == "https://exemple.fr/flux"
