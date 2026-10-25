"""La Forge libre et outillée (ADR 0105) — par leurs intentions.

- elle a le web quand elle travaille : ses projets (même ouverts avant), ses explorations, ses réparations, ses
  promesses ; y repenser, non ; et chercher sur le web n'est pas réparer une app ;
- un outil d'app déclare ses arguments dans le vocabulaire des champs d'action : le modèle voit leur schéma, l'hôte
  les vérifie avant d'appeler l'app — et ``forge_test`` aussi ;
- un battement, un service, un outil ont le délai que leur manifeste déclare ;
- son réseau est libre : toute méthode, un corps, ses en-têtes, la réponse entière (statut, en-têtes, texte ou
  octets) ; une réponse coupée le dit ; une boucle qui martèle s'arrête ;
- elle relit une app par morceaux numérotés, cherche dans ses apps, la retouche sans tout réécrire — tout ou rien,
  relu comme une écriture.
"""

from __future__ import annotations

import asyncio
import shutil
import textwrap
from types import SimpleNamespace

import pytest

from mika.adapters.forge import ForgeHost, read_manifest
from mika.adapters.forge.manifest import coherence, signatures
from mika.contracts import goals as goals_c
from mika.contracts import mcp as mcp_c
from mika.contracts import projects as projects_c
from mika.faculties.goals.tend import (
    EXPLORE_BUNDLES,
    PROMISE_BUNDLES,
    REFLECT_BUNDLES,
    REPAIR_BUNDLES,
    inherited,
)
from mika.faculties.goals.tools import judge
from mika.faculties.projects.faculty import DEFAULT_BUNDLES, WEB, run_bundles
from mika.faculties.projects.prompt import missing_tools
from mika.kernel.faculty import proving_tools
from mika.plugins import mcp as mcp_plugin
from mika.plugins import web as web_plugin
from mika.plugins.forge import Edit, ForgeParams, apply_edits, guide, timeout_of
from mika.plugins.forge.guide import EXAMPLE_CODE, EXAMPLE_MANIFEST
from mika.ports.forge import arg_specs, args_schema, check_args
from mika.runtime.tools import admitted
from tests.unit.test_forge_console import _content, _her_tool, install, run

needs_bwrap = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap absent")


def go(coro):
    return asyncio.run(coro)


# ── Le web quand elle travaille ───────────────────────────────────────────


def test_her_work_has_the_web_and_a_reflection_does_not():
    assert WEB == mcp_c.WEB_BUNDLE == f"{mcp_plugin.FAMILY}.{web_plugin.SERVER}"  # le lot de son serveur web
    assert WEB in DEFAULT_BUNDLES
    old = SimpleNamespace(authority=projects_c.SELF, bundles=("projects", "workshop", "memory"))
    assert WEB in run_bundles(old) and admitted(frozenset(run_bundles(old)), "mcp.web")  # même un projet d'avant
    assert "le web" not in missing_tools(old)
    confided = SimpleNamespace(authority=projects_c.USER, bundles=("projects", "workshop"))
    assert WEB not in run_bundles(confided)  # un projet confié garde son cadre…
    assert "le web" in missing_tools(confided)  # …et elle sait qu'il lui manque
    for bundles in (EXPLORE_BUNDLES, PROMISE_BUNDLES, REPAIR_BUNDLES, inherited("rss"), inherited("email")):
        assert WEB in bundles
    assert WEB not in REFLECT_BUNDLES  # y repenser se fait avec sa tête et sa mémoire


def test_searching_the_web_does_not_prove_a_repair():
    ctx = SimpleNamespace(mind=SimpleNamespace(registry=SimpleNamespace(tools={
        "mcp_web_search": SimpleNamespace(bundle="mcp.web")})))
    repair = SimpleNamespace(origin=goals_c.FROM_REPAIR, source="app:cours@3", bundles=REPAIR_BUNDLES)
    curious = SimpleNamespace(origin=goals_c.FROM_SIGNAL, source="thought:1", bundles=EXPLORE_BUNDLES)
    calls = [("mcp_web_search", True), ("forge_test", True)]
    assert proving_tools(calls[:1], [None], judge(ctx, curious)) == ("mcp_web_search",)  # aller lire, c'est explorer
    assert proving_tools(calls[:1], [None], judge(ctx, repair)) == ()  # mais pas réparer
    assert proving_tools(calls, [None, True], judge(ctx, repair)) == ("forge_test",)  # l'app essayée, oui


# ── Des outils qui disent leurs arguments ─────────────────────────────────

TOOLED = """\
title: Cours
schedule: manual
tools:
  - name: cours
    description: Le cours d'une action
    timeout: 15
    args:
      - {key: symbole, type: text, label: Symbole, required: true, max_length: 12, description: "AAPL, ^FCHI…"}
      - {key: devise, type: select, choices: [EUR, USD], default: EUR}
      - {key: jours, type: int, min: 1, max: 30, default: 1}
      - {key: detail, type: bool}
      - {key: autres, type: lines}
  - {name: rien, description: Sans argument}
"""
TOOLED_CODE = """\
def tool_cours(api, args):
    print("appelé", args["symbole"])
    return args


def tool_rien(api, args):
    return {"recu": args}
"""


def test_tool_arguments_are_declared_like_action_fields_and_checked_by_the_host():
    manifest, problems = read_manifest(TOOLED)
    assert problems == [] and coherence(manifest, signatures(TOOLED_CODE)[1]) == []
    cours, rien = manifest["tools"]
    assert cours["timeout"] == 15 and rien["args"] == [] and rien["timeout"] == 0
    specs = arg_specs(cours["args"])
    schema = args_schema(specs)
    assert schema["required"] == ["symbole"] and schema["additionalProperties"] is False
    assert schema["properties"]["devise"] == {"type": "string", "enum": ["EUR", "USD"], "default": "EUR"}
    assert schema["properties"]["jours"]["minimum"] == 1 and schema["properties"]["autres"]["type"] == "array"
    assert "Symbole — AAPL" in schema["properties"]["symbole"]["description"]
    values, errors = check_args(specs, {"symbole": "AAPL", "jours": "3", "detail": "oui"})
    assert errors == {} and values == {"symbole": "AAPL", "devise": "EUR", "jours": 3, "detail": True, "autres": []}
    _, errors = check_args(specs, {"jours": 40, "devise": "JPY", "symbole": "x" * 13, "pirate": 1})
    assert errors == {"pirate": "argument inconnu", "jours": "doit être entre 1 et 30",
                      "devise": "un de ces choix : EUR, USD", "symbole": "trop long : 12 caractères au plus"}
    assert check_args(specs, {})[1] == {"symbole": "valeur requise"}
    bad, said = read_manifest("title: X\ntools:\n  - {name: a1, args: [{key: n, type: entier}], timeout: 90}\n"
                              "  - {name: a1}\n  - {name: b2, couleur: rouge}\n")
    assert any("tools[0] (« a1 »).args[0] (« n ») : type inconnu" in x for x in said)
    assert any("« timeout » : un nombre de secondes, de 1 à 60" in x for x in said)
    assert any("outil déclaré deux fois" in x for x in said) and any("couleur" in x for x in said)
    many = "title: X\ntools:\n" + "".join(f"  - {{name: t{i}x}}\n" for i in range(9))
    assert "« tools » : 8 outils au plus" in read_manifest(many)[1]


@needs_bwrap
def test_her_app_tools_carry_their_schema_and_refuse_bad_arguments_before_calling_the_app(tmp_path):
    async def scenario(kernel, forge, store):
        await install(kernel, forge, "cours", TOOLED, TOOLED_CODE)
        kernel.refresh_tools()
        spec = kernel.mind.registry.tools["cours_cours"]
        out = {"schéma": spec.schema, "rien": kernel.mind.registry.tools["cours_rien"].schema}
        out["refusé"] = await _her_tool(kernel, "cours_cours", {"jours": 99, "pirate": 1})
        out["journal avant"] = list(forge.logs("cours"))
        out["fait"] = await _her_tool(kernel, "cours_cours", {"symbole": "AAPL"})
        out["essai refusé"] = await _her_tool(kernel, "forge_test", {"app": "cours", "method": "tool_cours",
                                                                      "args": {"devise": "JPY"}})
        out["essai"] = await _her_tool(kernel, "forge_test", {"app": "cours", "method": "tool_rien"})
        return out

    got = run(tmp_path, scenario)
    assert got["schéma"]["required"] == ["symbole"] and set(got["schéma"]["properties"]) == {
        "symbole", "devise", "jours", "detail", "autres"}
    assert got["rien"] == {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    refused = _content(got["refusé"])
    assert not got["refusé"].ok and "rien n'a été appelé" in refused and "pirate : argument inconnu" in refused
    assert "symbole : valeur requise" in refused and "symbole (text, requis)" in refused
    assert not any("appelé" in line for line in got["journal avant"])  # l'app n'a pas été appelée
    assert got["fait"].ok and '"devise": "EUR"' in _content(got["fait"]) and '"jours": 1' in _content(got["fait"])
    assert not got["essai refusé"].ok and "un de ces choix : EUR, USD" in _content(got["essai refusé"])
    assert got["essai"].ok and '"recu": {}' in _content(got["essai"])


# ── Des délais déclarés ───────────────────────────────────────────────────

SLOW = """\
title: Lente
schedule: manual
timeout: 30
services:
  - {name: lent, schedule: interval:1h, timeout: 4}
  - {name: presse, schedule: interval:1h}
"""
SLOW_CODE = """\
import time


def service_lent(api):
    time.sleep(1.5)
    return "fini"


def service_presse(api):
    time.sleep(1.5)
    return "fini"
"""


def test_a_timeout_is_declared_bounded_and_read_where_it_runs():
    manifest, problems = read_manifest(SLOW)
    assert problems == [] and manifest["timeout"] == 30
    assert [s["timeout"] for s in manifest["services"]] == [4.0, 0.0]
    _, said = read_manifest("title: X\ntimeout: 500\nservices:\n  - {name: aa, schedule: interval:1h, timeout: 0}\n")
    assert sum("« timeout » : un nombre de secondes, de 1 à 120" in x for x in said) == 2
    info = SimpleNamespace(timeout=30.0, services=(SimpleNamespace(name="lent", timeout=4.0),
                                                   SimpleNamespace(name="presse", timeout=0.0)),
                           tools=(SimpleNamespace(name="cours", timeout=15.0), SimpleNamespace(name="vite", timeout=0.0)))
    p = ForgeParams(tick_timeout_s=2.0)
    assert [timeout_of(info, m, p) for m in ("tick", "on_event", "service_lent", "service_presse", "tool_cours",
                                             "tool_vite")] == [30.0, 30.0, 4.0, 2.0, 15.0, 10.0]
    assert timeout_of(None, "tick", p) == 2.0


@needs_bwrap
def test_a_service_has_the_time_its_manifest_gives_it(tmp_path):
    h = ForgeHost(tmp_path / "forge")
    go(h.write("lente", SLOW, SLOW_CODE))
    info, p = h.info("lente"), ForgeParams(tick_timeout_s=1.0)
    try:
        slow = go(h.call("lente", "service_lent", timeout_s=timeout_of(info, "service_lent", p)))
        hurried = go(h.call("lente", "service_presse", timeout_s=timeout_of(info, "service_presse", p)))
    finally:
        h.shutdown()
    assert slow.ok and slow.value == "fini"  # quatre secondes déclarées : elle a le temps
    assert not hurried.ok and hurried.killed  # le défaut (1 s ici) : tuée


# ── Un réseau libre ───────────────────────────────────────────────────────

NET = "title: Réseau\nschedule: manual\nservices:\n  - {name: boucle, schedule: interval:1h, timeout: 60}\n"
NET_CODE = """\
import base64


def tick(api):
    r = api.http("https://api.exemple.fr/v1/q", method="POST", json={"q": "café"},
                 headers={"Authorization": "Bearer k", "Accept-Language": "fr"})
    img = api.http("https://img.exemple.fr/a.png", binary=True)
    big = api.http("https://gros.exemple.fr/")
    try:
        api.http_get("https://api.exemple.fr/panne")
        panne = "passé"
    except RuntimeError as exc:
        panne = str(exc)
    return {"r": r, "img": base64.b64decode(img["base64"]).hex(), "big": big["truncated"], "panne": panne,
            "page": api.http_get("https://ailleurs.exemple.org/page")}


def service_boucle(api):
    n = 0
    try:
        while True:
            api.http("https://api.exemple.fr/p" + str(n))
            n += 1
    except RuntimeError as exc:
        return [n, str(exc)]
"""


@needs_bwrap
def test_her_apps_reach_the_whole_internet_with_any_method_and_the_whole_answer(tmp_path):
    sent = []

    def net(method, url, headers, body):
        sent.append((method, url, dict(headers), body))
        if "panne" in url:
            return {"status": 500, "body": b"non", "headers": {}}
        if url.endswith(".png"):
            return {"status": 200, "body": bytes([0x89, 0x50]), "headers": {"content-type": "image/png"}}
        if "gros" in url:
            return {"status": 200, "body": b"x" * 10, "headers": {}, "truncated": True}
        return {"status": 201, "url": url, "body": b'{"ok": "oui"}',
                "headers": {"content-type": "application/json"}}

    h = ForgeHost(tmp_path / "forge", http=net)
    go(h.write("reseau", NET, NET_CODE))
    try:
        got = go(h.call("reseau", "tick", timeout_s=20))
        loop = go(h.call("reseau", "service_boucle", timeout_s=60))
        logs = h.logs("reseau")
    finally:
        h.shutdown()
    assert got.ok, got.error
    value = got.value
    assert value["r"] == {"status": 201, "ok": True, "url": "https://api.exemple.fr/v1/q",
                          "headers": {"content-type": "application/json"}, "truncated": False,
                          "text": '{"ok": "oui"}'}
    method, url, headers, body = sent[0]
    assert method == "POST" and body == '{"q": "café"}'.encode()
    assert headers == {"Authorization": "Bearer k", "Accept-Language": "fr", "Content-Type": "application/json"}
    assert value["img"] == "8950" and value["big"] is True and value["panne"].endswith("HTTP 500")
    assert value["page"] == '{"ok": "oui"}'  # n'importe quel domaine, sans rien déclarer
    assert any("réponse coupée" in line and "gros.exemple.fr" in line for line in logs)
    assert loop.ok and loop.value[0] == 200 and "trop de requêtes" in loop.value[1]  # une boucle qui martèle s'arrête


# ── Lire, chercher, retoucher ─────────────────────────────────────────────


def test_edits_replace_exact_fragments_all_or_nothing():
    text = "a = 1\nb = 2\na = 1\n"
    assert apply_edits(text, [Edit(old_string="b = 2", new_string="b = 3")]) == ("a = 1\nb = 3\na = 1\n", "")
    assert apply_edits(text, [Edit(old_string="a = 1", new_string="a = 0", replace_all=True)])[0] == \
        "a = 0\nb = 2\na = 0\n"
    same, why = apply_edits(text, [Edit(old_string="b = 2", new_string="b = 9"), Edit(old_string="a = 1",
                                                                                         new_string="a = 5")])
    assert same == text and "se trouve 2 fois (lignes 1, 3)" in why  # la seconde échoue : la première ne passe pas
    assert "ne trouve pas son fragment" in apply_edits(text, [Edit(old_string="c = 3", new_string="")])[1]
    assert "par lui-même" in apply_edits(text, [Edit(old_string="a", new_string="a")])[1]


@needs_bwrap
def test_she_reads_searches_and_edits_an_app_without_rewriting_it(tmp_path):
    async def scenario(kernel, forge, store):
        await install(kernel, forge, "meteo", EXAMPLE_MANIFEST, EXAMPLE_CODE)
        await install(kernel, forge, "carnet", "title: Carnet\n", "def view(api):\n    return api.kv_get('n', 0)\n")
        out = {"morceau": await _her_tool(kernel, "forge_read", {"app": "meteo", "file": "code", "offset": 4,
                                                                  "limit": 1})}
        out["tout"] = await _her_tool(kernel, "forge_read", {"app": "meteo"})
        out["cherché"] = await _her_tool(kernel, "forge_search", {"pattern": "api.kv_get("})
        out["une app"] = await _her_tool(kernel, "forge_search", {"pattern": "DEF VIEW_", "app": "meteo",
                                                                   "regex": True, "ignore_case": True})
        out["illisible"] = await _her_tool(kernel, "forge_search", {"pattern": "(", "regex": True})
        out["retouchée"] = await _her_tool(kernel, "forge_edit", {"app": "meteo", "edits": [
            {"old_string": '"Relevé ajouté pour "', "new_string": '"C\'est noté pour "'}]})
        out["code"] = forge.source("meteo")[1]
        out["introuvable"] = await _her_tool(kernel, "forge_edit", {"app": "meteo", "edits": [
            {"old_string": '"C\'est noté pour "', "new_string": '"Noté : "'},
            {"old_string": "n'existe pas", "new_string": "x"}]})
        out["cassée"] = await _her_tool(kernel, "forge_edit", {"app": "meteo", "edits": [
            {"old_string": "def action_releves_vider(api, data):", "new_string": "def action_releves_vider(api, data)"}]})
        out["version"] = forge.info("meteo").version
        out["manifeste"] = await _her_tool(kernel, "forge_edit", {"app": "meteo", "file": "manifest", "edits": [
            {"old_string": "title: Carnet météo", "new_string": "title: Carnet du temps"}]})
        out["titre"] = forge.info("meteo").title
        return out

    got = run(tmp_path, scenario)
    assert _content(got["morceau"]).splitlines() == [f"main.py, lignes 4 à 4 sur {len(EXAMPLE_CODE.splitlines())} :",
                                                     "     4\tdef _releves(api, ville):"]
    assert "     1\timport time" in _content(got["tout"]) and "     1\ttitle: Carnet météo" in _content(got["tout"])
    found = _content(got["cherché"])
    assert "carnet/main.py:2: " in found and "meteo/main.py:" in found  # dans toutes ses apps
    assert "meteo/main.py:" in _content(got["une app"]) and "carnet" not in _content(got["une app"])
    assert not got["illisible"].ok and "illisible" in _content(got["illisible"])
    edited = _content(got["retouchée"])
    assert "Écrite (version 2)" in edited and "Autour de ce qui a changé (main.py)" in edited and "C'est noté" in edited
    assert "C'est noté pour " in got["code"] and "Relevé ajouté pour" not in got["code"]
    assert not got["introuvable"].ok and "retouche n° 2 ne trouve pas" in _content(got["introuvable"])
    assert not got["cassée"].ok and "erreur de syntaxe" in _content(got["cassée"])
    assert got["version"] == 2  # tout ou rien : ni la retouche à moitié, ni le code cassé
    assert "Écrite (version 3)" in _content(got["manifeste"]) and got["titre"] == "Carnet du temps"


# ── Le mode d'emploi dit vrai ─────────────────────────────────────────────


def test_the_guide_shows_tools_that_read_and_a_free_network():
    text = guide.topic("outils")
    block = text[text.index("  tools:"):text.index("\n\n", text.index("  tools:"))]
    manifest, problems = read_manifest("title: X\n" + textwrap.dedent(block))
    assert problems == [] and [a["key"] for a in manifest["tools"][0]["args"]] == [
        "symbole", "devise", "jours", "detail", "autres"]
    network = guide.topic("reseau")
    assert "api.http(" in network and "jamais" in network and "5 Mo" in network
    assert "allowed_domains" not in guide.VEILLE_MANIFEST and "forge_edit" in guide.topic("manifeste")


# ── Ce que son app trouve, elle le dit à qui son projet concerne ──────────


def test_an_app_finding_informs_and_is_not_held_back_by_an_unanswered_message():
    """Dire à la personne ce que son app vient de trouver pour elle, c'est prévenir (``agency.INFORMS``) : une question
    restée sans réponse ne le retient pas (sonde du 2026-10-13 : l'alerte attendait qu'Adrien réponde à autre chose)."""
    from mika.contracts import agency as agency_c
    from mika.contracts import forge as forge_c

    assert forge_c.APP_NEWS in agency_c.INFORMS


@needs_bwrap
def test_what_her_app_finds_for_someone_she_tells_them_herself_once(tmp_path):
    """Une app de son projet pour Adrien signale : le signal attend dans sa file, elle le lit (une tâche), juge qu'il
    faut le dire — une initiative part vers Adrien, sa section lui montre ce qu'elle a retenu (la consigne murmurée
    n'en dit rien), ce qu'elle dit la marque dite : elle ne le redit pas. Ce qu'elle juge sans intérêt ne se dit pas."""
    from dataclasses import replace as replaced

    from mika.contracts import forge as forge_c
    from mika.contracts import projects as projects_c
    from mika.contracts import runtime as rt
    from mika.faculties.projects.tools import StartArgs, start_project
    from mika.kernel.clock import MINUTE, US
    from mika.kernel.events import Content, Origin
    from mika.kernel.frame import Audience
    from mika.plugins.forge import WriteArgs, _news, concerns, forge_write
    from mika.plugins.forge.guide import VEILLE_CODE, VEILLE_MANIFEST
    from mika.sim.clock import run_virtual
    from mika.vocab.episodes import Kind, project_target
    from tests.fixtures.atelier import Atelier
    from tests.fixtures.mika import boot, build, connect
    from tests.unit.test_forge_home import QUOTE
    from tests.unit.test_projects import _context, events

    forge = ForgeHost(tmp_path / "forge", http_get=lambda url: QUOTE, public=lambda host: True)
    kernel, clock, _, _ = build(tmp_path, _judging_llm("le CAC a bougé de 2,82 %", ""),
                                ports={"forge": forge, "workshop": Atelier()})

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            here = _context(kernel, "start_project", Kind.REPLY, "user_1", Audience(owner=True))
            await start_project(StartArgs(title="Suivre la bourse", objectives=["Une app qui relève le cours"],
                                          tools=["forge"]), here)
            pid = events(kernel, projects_c.PROJECT_CREATED)[-1].seq
            run = _context(kernel, "forge_write", Kind.WORK, project_target(pid), Audience(owner=True), bundles="forge")
            await forge_write(WriteArgs(app="cours", manifest=VEILLE_MANIFEST.replace("interval:1h", "manual"),
                                        code=VEILLE_CODE), run)
            frame = kernel.mind.frame()
            about, level = concerns(frame, frame.state("forge").apps["cours"])
            await kernel.mind.append([forge_c.QUEUED.draft(app="cours", summary=Content.of(text, level=level),
                                                           pertinence=pertinence, about=about, sensitivity=level)
                                      for text, pertinence in (("le CAC a bougé de 2,82 %", 0.8),
                                                               ("le CAC n'a presque pas bougé", 0.3))],
                                     emitter="forge", correlation="essai-signal", origin=Origin.GENESIS)
            await asyncio.sleep(30 * MINUTE / US)
            frame = kernel.mind.frame()
            state = frame.state("forge")
            untold = replaced(state, news=state.news.set("cours", replaced(state.news["cours"], told=False)))
            return {"about": about, "judged": events(kernel, forge_c.JUDGED), "dite": state.news["cours"],
                    "après": _news(state, frame), "candidat": _news(untold, frame),
                    "énoncés": [e for e in events(kernel, rt.UTTERANCE) if e.data.kind == Kind.INITIATIVE
                                and any(p.startswith("forge-news:") for p in e.data.provenance)]}
        finally:
            forge.shutdown()
            await kernel.stop()

    got = run_virtual(clock, main)
    assert got["about"] == ("user_1",)
    assert [e.data.tell is not None for e in got["judged"]] == [True, False]  # lus un par un : l'un se dit
    [cand] = got["candidat"]  # une trouvaille à dire : une initiative vers Adrien
    assert cand.reason == "app_news" and cand.target == "user_1"
    assert "Suivi d'un cours" in cand.args["brief:forge"] and "2,82" not in cand.args["brief:forge"]  # rien du contenu
    assert len(got["énoncés"]) == 1  # elle l'a dit, une fois
    assert got["dite"].told and got["après"] == []  # …et ne le redira pas


def test_only_a_strong_recent_untold_finding_about_that_person_is_to_tell():
    from mika.kernel.clock import HOUR
    from mika.kernel.state import FrozenDict
    from mika.plugins.forge import App, ForgeState, News, news_for

    s = ForgeState(apps=FrozenDict({a: App(a, 1) for a in ("fort", "faible", "vieux", "dit", "autre", "essaye")}),
                   news=FrozenDict({
                       "fort": News(1, 10 * HOUR, ("user_1",), 2, "r1", 0.8),
                       "faible": News(2, 10 * HOUR, ("user_1",), 2, "r2", 0.3),
                       "vieux": News(3, 1 * HOUR, ("user_1",), 2, "r3", 0.9),
                       "dit": News(4, 10 * HOUR, ("user_1",), 2, "r4", 0.9, told=True),
                       "autre": News(5, 10 * HOUR, ("user_2",), 2, "r5", 0.9),
                       "essaye": News(6, 10 * HOUR, ("user_1",), 2, "r6", 0.9, attempts=2),
                       "efface": News(7, 10 * HOUR, ("user_1",), 2, "r7", 0.9)}))
    p = ForgeParams()  # dans les 6 h, deux essais au plus
    assert [k for k, _ in news_for(s, "user_1", 11 * HOUR, p, 0.6)] == ["fort"]
    assert [k for k, _ in news_for(s, "user_2", 11 * HOUR, p, 0.6)] == ["autre"]
    assert news_for(s, "", 11 * HOUR, p, 0.6) == []


# ── Une base qui se lit sous les deux moteurs ─────────────────────────────


def test_what_she_writes_for_mariadb_runs_on_sqlite_and_the_other_way_round(tmp_path):
    """Le guide dit « AUTO_INCREMENT » (MariaDB) ; l'essai tourne sous SQLite, où ça plantait (sonde du 2026-10-13).
    L'hôte adapte les deux formes courantes, dans les deux sens, et rien d'autre."""
    from mika.adapters.forge.bases import ForgeBases, portable

    mariadb = "CREATE TABLE t (id INT NOT NULL AUTO_INCREMENT, nom VARCHAR(20) DEFAULT 'a,b', PRIMARY KEY (id)) " \
              "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    assert portable(mariadb, "sqlite") == "CREATE TABLE t ( id INTEGER PRIMARY KEY AUTOINCREMENT, nom VARCHAR(20) " \
                                          "DEFAULT 'a,b')"
    assert portable(mariadb, "mariadb") == mariadb
    assert portable("CREATE TABLE u (id INTEGER PRIMARY KEY AUTOINCREMENT)", "mariadb") == \
        "CREATE TABLE u (id INTEGER PRIMARY KEY AUTO_INCREMENT)"
    assert portable("insert ignore into t (nom) values (:n)", "sqlite").startswith("INSERT OR IGNORE")
    assert portable("INSERT OR IGNORE INTO t VALUES (1)", "mariadb").startswith("INSERT IGNORE")
    assert portable("INSERT OR REPLACE INTO t VALUES (1)", "mariadb").startswith("REPLACE")
    for kept in ("CREATE TABLE v (k TEXT PRIMARY KEY) WITHOUT ROWID", "CREATE TABLE x (a INT)",
                 "UPDATE t SET nom = 'auto_increment'"):
        assert portable(kept, "sqlite") == kept
    b = ForgeBases(tmp_path / "forge")
    b.ensure("essai")
    try:
        b.execute("essai", "CREATE TABLE IF NOT EXISTS releves (id INTEGER PRIMARY KEY AUTO_INCREMENT, "
                           "ville VARCHAR(100)) ENGINE=InnoDB")
        assert b.execute("essai", "INSERT INTO releves (ville) VALUES (:v)", {"v": "Lyon"})["id"] == 1
        assert b.execute("essai", "INSERT IGNORE INTO releves (id, ville) VALUES (1, 'doublon')")["rows"] == 0
        assert b.execute("essai", "INSERT INTO releves (ville) VALUES (:v)", {"v": "Paris"})["id"] == 2
        assert b.query("essai", "SELECT ville FROM releves ORDER BY id") == [{"ville": "Lyon"}, {"ville": "Paris"}]
    finally:
        b.close()


# ── Une liste écrite en texte JSON ────────────────────────────────────────


def test_a_list_given_as_json_text_is_read_as_a_list_and_a_text_stays_a_text():
    from mika.plugins.forge import EditArgs, WriteArgs
    from mika.runtime.tools import unquoted

    edit = SimpleNamespace(schema=None, args=EditArgs)
    got = unquoted(edit, {"app": "meteo", "edits": '[{"old_string": "a", "new_string": "b"}]'})
    assert EditArgs.model_validate(got).edits[0].new_string == "b"
    broken = '[{"old_string">  api.execute('  # ce que le modèle a vraiment envoyé une fois : laissé tel quel, refusé
    assert unquoted(edit, {"app": "meteo", "edits": broken})["edits"] == broken
    write = SimpleNamespace(schema=None, args=WriteArgs)
    raw = {"app": "meteo", "manifest": "[pas une liste]", "code": '{"x": 1}'}
    assert unquoted(write, raw) == raw  # des textes attendus restent des textes
    schema = SimpleNamespace(schema={"type": "object", "properties": {"autres": {"type": "array"}}}, args=None)
    assert unquoted(schema, {"autres": '["AAPL", "^FCHI"]'}) == {"autres": ["AAPL", "^FCHI"]}


# ── Ses signaux : une file par app, lue par lots, sous un quota (ADR 0105) ─


def test_the_manifest_declares_the_queue_of_its_signals():
    manifest, problems = read_manifest("title: X\nsignals: {queue: 5, per_call: 3, quota: 4, instructions: "
                                       "'dis à Adrien ce qui parle de domotique'}\n")
    assert problems == [] and manifest["signals"] == {"queue": 5, "per_call": 3, "quota": 4,
                                                      "instructions": "dis à Adrien ce qui parle de domotique"}
    assert read_manifest("title: X\n")[0]["signals"] == {"queue": 20, "per_call": 1, "quota": 12, "instructions": ""}
    _, said = read_manifest("title: X\nsignals: {queue: 500, per_call: 0, couleur: rouge}\n")
    assert any("couleur" in x for x in said)
    _, said = read_manifest("title: X\nsignals: {queue: 500, per_call: 0}\n")
    assert any("« queue » : un entier de 1 à 100" in x for x in said)
    assert any("« per_call » : un entier de 1 à 20" in x for x in said)


FEED = """\
title: Veille domotique
schedule: interval:5m
signals: {queue: 5, per_call: 3, quota: 2, instructions: dis à Adrien ce qui parle de domotique}
"""
FEED_CODE = """\
ARTICLES = ["Matter 1.4 sort", "Un thermostat qui apprend", "La pluie demain", "Zigbee ou Thread",
            "Un capteur de CO2 à 20 euros", "Recette de crêpes", "Home Assistant change d'interface"]


def tick(api):
    vus = api.kv_get("vus", 0)
    for titre in ARTICLES[vus:]:
        api.signal("nouvel article : " + titre, pertinence=0.5)
    api.kv_set("vus", len(ARTICLES))
    return len(ARTICLES) - vus
"""
WEATHER = """\
title: Température
schedule: manual
services:
  - {name: releve, schedule: "cron:0 8,18 * * *", description: la température deux fois par jour}
signals: {per_call: 1, quota: 4, instructions: donne la température à Adrien}
"""
WEATHER_CODE = """\
def service_releve(api):
    n = api.kv_get("n", 0) + 1
    api.kv_set("n", n)
    api.signal("il fait " + str(10 + n) + " °C à Lyon", pertinence=0.4)
    return n
"""


def _judging_llm(*tells: str):
    """Un modèle simulé : une tâche qui lit une file conclut par son verdict (le suivant de ``tells``, le dernier
    ensuite), une initiative dit une phrase."""
    from mika.ports.llm import LLMResponse, ToolCall

    said = iter(range(1, 1000))
    verdicts = iter(tells)
    last = [tells[-1]]

    def respond(req):
        if any(t.name == "forge_signals_done" for t in req.tools):
            last[0] = next(verdicts, last[0])
            return LLMResponse("", tool_calls=(ToolCall("v1", "forge_signals_done", {"tell": last[0]}),))
        # chaque parole est neuve (sa garde anti-redite tait une phrase déjà dite)
        return LLMResponse(f"Message n° {next(said)} : {last[0] or tells[0]} [EMOTION:happy:0.3]")

    return respond


@needs_bwrap
def test_an_app_signals_each_new_article_into_its_queue_read_in_batches_under_its_quota(tmp_path):
    """Sept articles en un battement : la file en garde cinq (deux partent, comptés) ; elle les lit par trois, deux
    fois au plus dans la journée (son quota), et dit ce qu'elle retient à Adrien — une fois."""
    from mika.contracts import forge as forge_c
    from mika.contracts import runtime as rt
    from mika.kernel.clock import MINUTE, US
    from mika.sim.clock import run_virtual
    from mika.vocab.episodes import Kind
    from tests.fixtures.mika import boot, build, connect
    from tests.unit.test_forge_console import events

    forge = ForgeHost(tmp_path / "forge", http_get=lambda url: "", public=lambda host: True)
    kernel, clock, _, _ = build(tmp_path, _judging_llm("Matter 1.4 est sorti, et un capteur de CO2 à 20 euros", ""),
                                ports={"forge": forge})

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            await install(kernel, forge, "flux", FEED, FEED_CODE)
            await asyncio.sleep(90 * MINUTE / US)
            frame = kernel.mind.frame()
            return {"app": frame.state("forge").apps["flux"], "queued": events(kernel, forge_c.QUEUED),
                    "judged": events(kernel, forge_c.JUDGED), "news": frame.state("forge").news.get("flux"),
                    "said": [e for e in events(kernel, rt.UTTERANCE) if e.data.kind == Kind.INITIATIVE
                             and any(x.startswith("forge-news:") for x in e.data.provenance)]}
        finally:
            forge.shutdown()
            await kernel.stop()

    got = run_virtual(clock, main)
    assert len(got["queued"]) == 7 and got["app"].dropped == 2  # une file de cinq : les deux plus anciens partent
    assert [len(e.data.seqs) for e in got["judged"]] == [3, 2]  # lus par trois : deux appels, le quota du jour
    assert len(got["app"].calls_at) == 2 and got["app"].queue == ()
    assert [e.data.tell is not None for e in got["judged"]] == [True, False]  # un lot à dire, l'autre non
    assert got["news"] is not None and got["news"].told and len(got["said"]) == 1  # dit à Adrien, une fois


@needs_bwrap
def test_a_service_signals_the_temperature_twice_a_day_and_she_tells_it(tmp_path):
    """Un service relève la température à 8 h et à 18 h et la signale : chaque relevé est lu (un par appel) et dit à
    Adrien, qui lui répond — quatre en deux jours, sous un quota de quatre par jour. (S'il ne lui répondait plus, ce
    qu'une app trouve attendrait qu'il l'ait fait : ``test_speaking_up``, 2026-10-19.)"""
    from mika.app import composition
    from mika.contracts import forge as forge_c
    from mika.contracts import runtime as rt
    from mika.kernel.clock import HOUR, MINUTE, US
    from mika.sim.clock import run_virtual
    from mika.vocab.episodes import Kind
    from tests.fixtures.mika import DOC, build, connect, said
    from tests.unit.test_forge_console import events

    forge = ForgeHost(tmp_path / "forge", http_get=lambda url: "", public=lambda host: True)
    kernel, clock, _, _ = build(tmp_path, _judging_llm("il fait doux à Lyon"), ports={"forge": forge})

    async def answers():
        """Adrien répond à ce qu'elle lui écrit d'elle-même, quelques minutes après."""
        seen = 0
        while True:
            await asyncio.sleep(10 * MINUTE / US)
            sent = [e for e in events(kernel, rt.UTTERANCE) if e.data.kind == Kind.INITIATIVE]
            if len(sent) > seen:
                seen = len(sent)
                await (await kernel.perceive(said("user_1", "ah merci !"))).reply

    async def main():
        # il répond à tout : elle lui écrit plus souvent — ce n'est pas son plafond du jour qu'on regarde ici
        await kernel.start(configure=lambda k: composition.configure(k, DOC, {"agency": {"daily_cap": 12}}))
        answering = None
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            await install(kernel, forge, "meteo", WEATHER, WEATHER_CODE)
            answering = asyncio.create_task(answers())
            await asyncio.sleep(48 * HOUR / US)
            return {"queued": events(kernel, forge_c.QUEUED), "judged": events(kernel, forge_c.JUDGED),
                    "said": [e for e in events(kernel, rt.UTTERANCE) if e.data.kind == Kind.INITIATIVE
                             and any(x.startswith("forge-news:meteo:") for x in e.data.provenance)]}
        finally:
            if answering is not None:
                answering.cancel()
            forge.shutdown()
            await kernel.stop()

    got = run_virtual(clock, main)
    hours = sorted({clock.local(e.at).hour for e in got["queued"]}) if hasattr(clock, "local") else None
    assert len(got["queued"]) == 4 and (hours is None or hours == [8, 18])
    assert [len(e.data.seqs) for e in got["judged"]] == [1, 1, 1, 1]
    assert len(got["said"]) == 4  # chaque relevé dit à Adrien



@needs_bwrap
def test_reading_a_queue_is_work_done_and_what_she_keeps_is_her_own_thought(tmp_path):
    """Lire la file d'une app est un travail fait par un outil, sans un mot à personne : il finit « fait », pas
    « elle s'est tue ». Ce qu'elle garde pour elle est sa pensée à elle, pas un signal de l'app (sonde du
    2026-10-13 : « Mon app me signale : … je l'ai signalé quand même »)."""
    from mika.contracts import forge as forge_c
    from mika.contracts import runtime as rt
    from mika.kernel.clock import HOUR, US
    from mika.ports.llm import LLMResponse, ToolCall
    from mika.runtime.effects import with_content
    from mika.sim.clock import run_virtual
    from mika.vocab.episodes import Kind
    from tests.fixtures.mika import boot, build, connect
    from tests.unit.test_forge_console import events

    def respond(req):
        if any(t.name == "forge_signals_done" for t in req.tools):
            return LLMResponse("", tool_calls=(ToolCall("v1", "forge_signals_done",
                                                        {"keep": "QuoiVoir parle de films, pas d'IA"}),))
        return LLMResponse("D'accord. [EMOTION:happy:0.3]")

    forge = ForgeHost(tmp_path / "forge", http_get=lambda url: "", public=lambda host: True)
    kernel, clock, _, _ = build(tmp_path, respond, ports={"forge": forge})

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            await install(kernel, forge, "meteo", WEATHER, WEATHER_CODE)
            await asyncio.sleep(26 * HOUR / US)
            mind = kernel.mind
            return {"ended": [e.data.outcome for e in events(kernel, rt.EPISODE_ENDED) if e.data.kind == Kind.TASK],
                    "kept": [with_content(mind, e).data.summary.text for e in events(kernel, forge_c.SIGNALED)
                             if e.data.app == "meteo"]}
        finally:
            forge.shutdown()
            await kernel.stop()

    got = run_virtual(clock, main)
    assert got["ended"] and set(got["ended"]) == {"done"}
    assert got["kept"] and all(k.startswith("En lisant ce que mon app « Température » a trouvé, je me suis dit")
                               for k in got["kept"])



@needs_bwrap
def test_reading_a_queue_she_knows_what_she_already_told_and_what_the_project_asked(tmp_path):
    """Un signal peut revenir (un flux republie, une base repart de zéro), et qui suit le projet a pu demander d'écarter
    certains articles. En lisant la file, elle a sous les yeux ce qu'elle a déjà dit de cette app et les consignes de
    son projet (sonde du 2026-10-13 : les mêmes quatre articles redits, faux positifs compris, alors qu'Adrien avait
    demandé de les écarter)."""
    from mika.contracts import forge as forge_c
    from mika.contracts import runtime as rt
    from mika.faculties.projects.faculty import AMENDED
    from mika.kernel.clock import MINUTE, US
    from mika.kernel.events import Content, Origin, VoiceProvenance
    from mika.plugins.forge import written_draft
    from mika.ports.llm import LLMResponse, ToolCall
    from mika.sim.clock import run_virtual
    from tests.fixtures.mika import boot, build, connect, disconnect
    from tests.unit.test_projects import create

    seen: list[str] = []

    def respond(req):
        if any(t.name == "forge_signals_done" for t in req.tools):
            seen.append(req.system_stable + "\n".join(m.content for m in req.messages))
            return LLMResponse("", tool_calls=(ToolCall("v1", "forge_signals_done", {"keep": "rien de neuf"}),))
        return LLMResponse("D'accord. [EMOTION:happy:0.3]")

    forge = ForgeHost(tmp_path / "forge", http_get=lambda url: "", public=lambda host: True)
    kernel, clock, _, _ = build(tmp_path, respond, ports={"forge": forge})

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            pid = await create(kernel, "op1", title="Veille domotique", objectives="Suivre la domotique")
            mind = kernel.mind
            await mind.append([AMENDED.draft(project=pid, instruction=Content.of("Écarte la cuisine.", level=2),
                                             by="user_1")], emitter="projects", correlation="op2",
                              origin=Origin.GENESIS)
            await forge.write("flux", FEED, FEED_CODE)
            await mind.append([written_draft(forge.info("flux"), project=pid)], emitter="forge",
                              correlation="genese", origin=Origin.GENESIS)
            told = await mind.append([forge_c.JUDGED.draft(app="flux", seqs=(), tell=Content.of(
                "Matter 1.4 est sorti", level=2), about=("user_1",), sensitivity=2)], emitter="forge",
                correlation="avant", origin=Origin.GENESIS)
            voice = VoiceProvenance(call_id="x", persona_hash="", role="initiative", model="m")
            await mind.append([rt.UTTERANCE.draft(kind="INITIATIVE", text=Content.of("Matter 1.4 est sorti !"),
                                                  target="user_1", voice=voice, visible=True,
                                                  provenance=(f"forge-news:flux:{told.seqs[-1]}",))],
                              emitter="runtime", correlation="dit", origin=Origin.KERNEL)
            # Adrien s'en va ; une trouvaille suivante, pas encore dite, prend sa place : ce qui a été dit reste su
            await disconnect(kernel, "user_1")
            await mind.append([forge_c.JUDGED.draft(app="flux", seqs=(), tell=Content.of(
                "Un thermostat qui apprend", level=2), about=("user_1",), sensitivity=2)], emitter="forge",
                correlation="ensuite", origin=Origin.GENESIS)
            await asyncio.sleep(40 * MINUTE / US)
        finally:
            forge.shutdown()
            await kernel.stop()

    run_virtual(clock, main)
    assert seen, "elle n'a pas lu la file"
    prompt = seen[0]
    assert "Ce que tu as déjà dit de cette app" in prompt and "Matter 1.4 est sorti" in prompt
    assert "pas encore dit" in prompt and "Un thermostat qui apprend" in prompt
    assert "LES CONSIGNES DU PROJET DE CETTE APP" in prompt and "Écarte la cuisine." in prompt


@needs_bwrap
def test_an_app_lives_on_her_clock(tmp_path):
    """Le bac à sable était en UTC : elle croyait ses rythmes décalés (sonde du 2026-10-13). Une app a son heure ; un
    fuseau illisible la laisse en UTC, jamais en panne."""
    code = "import time\n\ndef view(api):\n    return time.strftime('%Z')\n"
    h = ForgeHost(tmp_path / "forge")
    h.zone = lambda: "Europe/Paris"
    go(h.write("heure", "title: Heure\n", code))
    odd = ForgeHost(tmp_path / "ailleurs")
    odd.zone = lambda: "../../etc/passwd"
    go(odd.write("heure", "title: Heure\n", code))
    try:
        paris, utc = go(h.call("heure", "view")), go(odd.call("heure", "view"))
    finally:
        h.shutdown()
        odd.shutdown()
    assert paris.ok and paris.value in ("CET", "CEST")
    assert utc.ok and utc.value == "UTC"


def test_the_guide_says_an_app_tells_nothing_by_itself():
    """Deux apps écrites pour « dis-moi » et « donne-moi » rangeaient sans jamais signaler (sonde du 2026-10-13) : le
    guide le dit d'emblée, avec ses recettes."""
    assert "ne dit rien d'elle-même" in guide.topic("manifeste")
    recipes = guide.topic("veille")
    assert "à heure fixe" in recipes and "per_call: 10" in recipes and "ton fuseau" in recipes
