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
