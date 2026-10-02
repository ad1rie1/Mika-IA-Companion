"""La Forge dans la console : chaque app est une fiche, ses vues déclarées s'y
rendent, ses actions et ses réglages s'y exécutent.

- une app a un en-tête, une recherche et ses onglets (état, vues, réglages,
  code, journal, vécu) ;
- l'onglet « Vues » rend une vraie vue (table paginée, courbe, formulaires)
  depuis le bac à sable ; une vue lente, trop grosse ou invalide devient une
  note, **jamais journalisée, jamais comptée par le disjoncteur** ;
- « agir » exécute une action déclarée, champs vérifiés un par un en
  français ; ce qu'elle émet ou signale est journalisé comme venant de
  l'opérateur (``EXTERNAL`` + ``runtime.operated``), sans jamais compter
  contre l'app ;
- « régler » enregistre ce que l'app lit par ``api.config`` ; un secret est
  scellé au repos et jamais montré ;
- effacer exige de retaper le nom ; « tester » montre la vue décodée en place ;
- l'exemple de ``forge_help`` est valide (son enveloppe se décode).
"""

from __future__ import annotations

import asyncio
import copy
import html
import json
import re
import shutil
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from mika.adapters.forge import ForgeHost, read_manifest
from mika.adapters.forge.manifest import coherence, signatures
from mika.app.server import ForgeSettingsStore
from mika.app.settings import SecretBox, Settings
from mika.contracts import forge as forge_c
from mika.contracts import runtime as rt
from mika.kernel.events import Origin
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Chart,
    Code,
    Fields,
    Filters,
    Head,
    Note,
    Ref,
    Stats,
    Table,
    walk_blocks,
)
from mika.plugins.forge import (
    EMITTED,
    SWITCHED,
    WRITTEN,
    HelpArgs,
    _test_view,
    action_verdict,
    forge_help,
    written_draft,
)
from mika.plugins.forge.guide import EXAMPLE_CODE, EXAMPLE_MANIFEST, TOPICS
from mika.plugins.forge.views import decode_view, is_invalid
from mika.runtime.inspection import Inspection, find
from mika.runtime.operations import dynamic_fields, offered, perform
from mika.sim.clock import run_virtual
from tests.fixtures.console_html import ConsoleHTML
from tests.fixtures.mika import boot, build, reply
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

needs_bwrap = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap absent")


# ── Outils ────────────────────────────────────────────────────────────────


def mind_with_forge(tmp_path: Path):
    """Un noyau, un hôte réel et le magasin de réglages du serveur (secrets scellés)."""
    store = ForgeSettingsStore(None)  # type: ignore[arg-type] — relié au magasin une fois le noyau bâti
    forge = ForgeHost(tmp_path / "forge", config=lambda app: store.values(app))
    store.host = forge
    kernel, clock, _, _ = build(tmp_path, reply("d'accord [EMOTION:neutral:0.3]"),
                                ports={"forge": forge, "forge_settings": store})
    store.settings = Settings(kernel.mind.store, SecretBox(Fernet.generate_key()))
    return kernel, clock, forge, store


def run(tmp_path: Path, scenario):
    kernel, clock, forge, store = mind_with_forge(tmp_path)

    async def main():
        await boot(kernel)
        await store.settings.open()
        try:
            return await scenario(kernel, forge, store)
        finally:
            forge.shutdown()
            await kernel.stop()

    return run_virtual(clock, main)


async def install(kernel, forge, app: str, manifest: str, code: str):
    await forge.write(app, manifest, code)
    info = forge.info(app)
    await kernel.mind.append([written_draft(info)], emitter="forge", correlation="genese", origin=Origin.GENESIS)
    return info


def form(values: dict[str, str], fixed: dict[str, str] | None = None) -> dict[str, list[str]]:
    out = {"_champs": [k for k in values if not k.startswith("_")], **{k: [v] for k, v in values.items()}}
    if fixed:
        out["_fixes"] = list(fixed)
        out.update({k: [v] for k, v in fixed.items()})
    return out


def walk(blocks):
    yield from walk_blocks(blocks)


def of(blocks, kind):
    return [b for b in walk(blocks) if isinstance(b, kind)]


def events(kernel, *types):
    names = {getattr(t, "name", t) for t in types}
    return [kernel.mind.decode(s) for s in list(kernel.mind.store.read(types=names))]


async def tab(kernel, name: str, app: str, **params: str):
    return await Inspection(kernel).arun(find(kernel, "forge", name), params, subject=app)


def meteo_ajout(ville="Paris", temperature="-12", note="gel") -> dict[str, list[str]]:
    return form({"ville": ville, "temperature": temperature, "note": note},
                {"app": "meteo", "vue": "releves", "action": "ajouter"})


# ── La fiche ──────────────────────────────────────────────────────────────


@needs_bwrap
def test_an_app_is_an_object_with_a_head_a_search_and_its_tabs(tmp_path):
    async def scenario(kernel, forge, store):
        await install(kernel, forge, "meteo", EXAMPLE_MANIFEST, EXAMPLE_CODE)
        await install(kernel, forge, "veille", "title: Veille café\nschedule: interval:10m\n",
                      "def tick(api):\n    return 1\n")
        ins = Inspection(kernel)
        out = {"head": ins.head("app", "meteo"), "inconnue": ins.head("app", "inconnue"),
               "évasion": ins.head("app", "../../etc"), "cherche": ins.search("app", "MÉTÉO"),
               "tout": ins.search("app", ""), "onglets": [t.name for t in ins.tabs("app")],
               "apps": await ins.arun(find(kernel, "forge", "apps"), {})}
        out["rendus"] = {t.name: await tab(kernel, t.name, "meteo") for t in ins.tabs("app")}
        out["sans fiche"] = await tab(kernel, "vues", "")
        return out

    got = run(tmp_path, scenario)
    head = got["head"]
    assert isinstance(head, Head) and (head.key, head.title) == ("meteo", "Carnet météo")
    assert head.badges == (Badge("active", "ok"),) and dict(head.facts)["version"] == 1
    assert got["inconnue"] is None and got["évasion"] is None
    assert [f.key for f in got["cherche"]] == ["meteo"] and {f.key for f in got["tout"]} == {"meteo", "veille"}
    assert got["onglets"] == ["etat", "vues", "reglages", "code", "journal", "vecu"]
    for name, blocks in got["rendus"].items():
        assert blocks and not [n for n in of(blocks, Note) if n.tone == "danger"], name
    assert "Carnet météo" in repr(got["rendus"]["etat"]) and of(got["rendus"]["code"], Code)
    assert "sur la fiche d'une app" in of(got["sans fiche"], Note)[0].text
    [listing] = [b for b in got["apps"] if isinstance(b, Table)]
    rows = {r.cells[0].text: r for r in listing.rows}
    meteo = rows["meteo"].cells
    assert meteo[0] == Ref.subject("app", "meteo", "meteo") and meteo[4] == Badge("active", "ok")
    assert rows["meteo"].href == Ref.subject("app", "meteo", "meteo")  # la ligne entière mène à la fiche


@needs_bwrap
def test_the_views_tab_renders_a_real_app_view(tmp_path):
    async def scenario(kernel, forge, store):
        await install(kernel, forge, "meteo", EXAMPLE_MANIFEST, EXAMPLE_CODE)
        await install(kernel, forge, "ancienne", "title: Ancienne\n", "def view(api):\n    return {'n': 3}\n")
        for i in range(12):
            done = await perform(kernel, "forge.agir", meteo_ajout(temperature=str(i - 3)), by="user_1",
                                 subject="meteo", nonce=f"a{i}")
            assert done.ok, done
        await perform(kernel, "forge.agir", meteo_ajout(ville="Lyon", temperature="20"), by="user_1",
                      subject="meteo", nonce="lyon")
        return (await tab(kernel, "vues", "meteo", vue="releves", ville="Paris"),
                await tab(kernel, "vues", "meteo", vue="Relevés", ville="Paris", page="2"),
                await tab(kernel, "vues", "meteo", vue="nulle-part"),
                await tab(kernel, "vues", "ancienne"))

    page1, page2, unknown, legacy = run(tmp_path, scenario)
    assert not [n for n in of(page1, Note) if n.tone == "danger"]
    [stats] = of(page1, Stats)
    assert stats.items[0].value == 12
    [chart] = of(page1, Chart)
    assert len(chart.series[0].points) == 12 and chart.title == "Température à Paris"
    table = next(t for t in of(page1, Table) if t.title == "Relevés à Paris")
    assert len(table.rows) == 10 and (table.pager.total, table.pager.number, table.pager.pages) == (12, 1, 2)
    second = next(t for t in of(page2, Table) if t.title == "Relevés à Paris")  # le libellé de la vue est compris
    assert len(second.rows) == 2 and second.pager.number == 2
    # les liens restent dans l'app : sa fiche, l'onglet « Vues », les seuls paramètres déclarés
    cities = next(t for t in of(page1, Table) if t.title == "Les villes")
    assert {r[0] for r in cities.rows} == {
        Ref("subject", "app/meteo", v, (("onglet", "vues"), ("vue", "releves"), ("ville", v))) for v in ("Paris", "Lyon")}
    # ses formulaires deviennent ceux de « forge.agir », l'app, la vue et l'action y étant fixées
    forms = of(page1, ActionSlot)
    assert {f.action for f in forms} == {"forge.agir"}
    add = dict(forms[0].initial)
    assert add == {"action": "ajouter", "app": "meteo", "vue": "releves", "_bouton": "Ajouter un relevé",
                   "ville": "Paris"}
    assert dict(forms[1].initial)["_bouton"] == "⚠ Effacer cette ville"
    # Les paramètres deviennent un formulaire natif, dans le contexte de la bonne app/vue.
    [filters] = of(page1, Filters)
    assert dict(filters.keep) == {"onglet": "vues", "vue": "releves"}
    assert {p.kind for p in filters.params} >= {"search", "bool"}
    assert dict(filters.values)["ville"] == "Paris"
    assert "Vue « nulle-part » inconnue (au choix : releves)" in of(unknown, Note)[0].text
    assert of(unknown, Chart)  # retombe sur la première vue
    raw = of(legacy, Code)
    assert raw and json.loads(raw[0].text) == {"n": 3}  # une ancienne vue : sa donnée brute, citée


FRAGILE = """\
title: Fragile
views:
  - {key: lente, label: Lente}
  - {key: grosse, label: Grosse}
  - {key: invalide, label: Invalide}
  - {key: formulaire, label: Formulaire}
  - {key: panne, label: Panne}
  - {key: vivante, label: Vivante}
"""
FRAGILE_CODE = '''\
def view_lente(api, params):
    while True:
        pass

def view_grosse(api, params):
    return {"version": 2, "blocks": [{"type": "prose", "text": "x" * 9000}] * 40}

def view_invalide(api, params):
    return {"version": 2, "blocks": [{"type": "note", "text": "ok"}, {"type": "table", "columns": ["a"],
            "rows": [["x", "y"]]}]}

def view_formulaire(api, params):
    return {"version": 2, "blocks": [{"type": "form", "action": "pirater"}]}

def view_panne(api, params):
    raise ValueError("la page a changé")

def view_vivante(api, params):
    return {"version": 2, "blocks": [{"type": "note", "text": "vivante"}]}
'''


@needs_bwrap
def test_a_view_that_fails_is_a_note_never_journaled_nor_counted_against_the_app(tmp_path):
    async def scenario(kernel, forge, store):
        await install(kernel, forge, "fragile", FRAGILE, FRAGILE_CODE)
        head = kernel.mind.head
        shown = {k: await tab(kernel, "vues", "fragile", vue=k)
                 for k in ("lente", "grosse", "invalide", "formulaire", "panne", "vivante")}
        after = kernel.mind.head
        app = kernel.mind.frame().state("forge").apps["fragile"]
        await kernel.mind.append([SWITCHED.draft(app="fragile", state="broken", reason="le disjoncteur")],
                                 emitter="forge", correlation="t", origin=Origin.EXTERNAL)
        return shown, head, after, app, await tab(kernel, "vues", "fragile", vue="vivante")

    shown, head, after, app, broken = run(tmp_path, scenario)
    assert after == head  # rendre des vues n'écrit rien au journal
    assert app.failures == 0 and app.enabled and not app.broken  # ni le disjoncteur

    def last(k):
        return of(shown[k], Note)[-1]

    assert last("lente").title == "Vue trop lente" and "plus de 3 s" in last("lente").text
    assert last("grosse").title == "Vue trop grosse"
    assert last("invalide").title == "Vue invalide" and "blocks[1].rows[0] : 2 cellules pour 1 colonnes" in \
        last("invalide").text
    assert not [n for n in of(shown["invalide"], Note) if n.text == "ok"]  # jamais un rendu partiel
    assert "le formulaire « pirater » désigne une action que la vue « formulaire » ne déclare pas" in \
        last("formulaire").text
    assert last("panne").title == "Vue en panne" and "la page a changé" in last("panne").text
    assert last("vivante") == Note("vivante")
    assert "cassée" in of(broken, Note)[-1].text and not [n for n in of(broken, Note) if n.text == "vivante"]


# ── Agir ──────────────────────────────────────────────────────────────────

IDEES = """\
title: Boîte à idées
views:
  - key: idees
    label: Idées
    actions:
      - key: noter
        label: Noter une idée
        fields:
          - {key: texte, type: text, required: true, max_length: 20}
          - {key: contact, type: email}
          - {key: lien, type: url}
          - {key: n, type: int, min: 1, max: 5}
      - {key: casser, label: Casser, confirm: "Tout casser ?"}
      - {key: mal, label: Mal répondre}
"""
IDEES_CODE = '''\
def view_idees(api, params):
    return {"version": 2, "blocks": [
        {"type": "table", "columns": ["idée"], "rows": [[i] for i in api.kv_get("idees", [])]},
        {"type": "form", "action": "noter"}]}

def action_idees_noter(api, data):
    api.kv_set("idees", api.kv_get("idees", []) + [data["texte"]])
    api.emit("idee", {"texte": data["texte"]})
    api.signal("une nouvelle idée : " + data["texte"], pertinence=0.3)
    return {"ok": True, "message": "Notée : " + data["texte"] + " " + repr(sorted(data.items()))}

def action_idees_casser(api, data):
    raise ValueError("cassée exprès")

def action_idees_mal(api, data):
    return "d'accord"
'''
FIXED = {"app": "idees", "vue": "idees", "action": "noter"}


@needs_bwrap
def test_agir_runs_the_declared_action_checks_each_field_and_journals_what_it_emits(tmp_path):
    async def scenario(kernel, forge, store):
        await install(kernel, forge, "idees", IDEES, IDEES_CODE)
        spec = kernel.registry.actions["forge.agir"]
        out = {"champs": [f.path for f in dynamic_fields(kernel, spec, "idees", {"vue": "idees", "action": "noter"})]}
        good = {"texte": "un jardin", "contact": "", "lien": "https://exemple.fr/jardin", "n": "3"}
        out["ok"] = await perform(kernel, "forge.agir", form(good, FIXED), by="user_1", subject="idees", nonce="n1")
        for key, value in (("texte", ""), ("texte", "x" * 30), ("contact", "pas-un-mail"), ("lien", "javascript:x"),
                           ("n", "9"), ("n", "trois")):
            out[f"{key}={value[:5]}"] = await perform(kernel, "forge.agir", form({**good, key: value}, FIXED),
                                                      by="user_1", subject="idees", nonce=f"bad-{key}-{value[:5]}")
        casser = {**FIXED, "action": "casser"}
        out["sans confirmer"] = await perform(kernel, "forge.agir", form({}, casser), by="user_1", subject="idees",
                                              nonce="c0")
        for i in range(6):  # une action qui échoue n'ouvre jamais le disjoncteur
            out["casse"] = await perform(kernel, "forge.agir", form({"confirmer": "on"}, casser), by="user_1",
                                         subject="idees", nonce=f"c{i + 1}")
        out["mal"] = await perform(kernel, "forge.agir", form({}, {**FIXED, "action": "mal"}), by="user_1",
                                   subject="idees", nonce="m1")
        out["autre app"] = await perform(kernel, "forge.agir", form(good, {**FIXED, "app": "meteo"}), by="user_1",
                                         subject="idees", nonce="x1")
        out["app"] = kernel.mind.frame().state("forge").apps["idees"]
        out["vue"] = await tab(kernel, "vues", "idees")
        return out

    got = run(tmp_path, scenario)  # (le magasin et le noyau vivent le temps du scénario)
    assert got["champs"] == ["texte", "contact", "lien", "n"]
    ok = got["ok"]
    assert ok.ok and ok.message.startswith("Notée : un jardin") and "('n', 3)" in ok.message and ok.seqs
    errors = {k: v.errors for k, v in got.items() if "=" in k}
    assert errors == {"texte=": {"texte": "valeur requise"}, "texte=xxxxx": {"texte": "trop long : 20 caractères au plus"},
                      "contact=pas-u": {"contact": "une adresse e-mail est attendue (nom@exemple.fr)"},
                      "lien=javas": {"lien": "une adresse http(s)://… est attendue"},
                      "n=9": {"n": "doit être entre 1 et 5"}, "n=trois": {"n": "doit être un nombre entier"}}
    assert got["sans confirmer"].errors == {"confirmer": "coche pour confirmer : Tout casser ?"}
    assert got["casse"].ok and got["casse"].tone == "danger" and "cassée exprès" in got["casse"].message
    assert got["mal"].tone == "warn" and "{ok, message}" in got["mal"].message
    assert not got["autre app"].ok
    app = got["app"]
    assert app.failures == 0 and app.enabled and not app.broken
    rows = next(t for t in got["vue"] if isinstance(t, Table)).rows
    assert rows == (("un jardin",),)  # une seule idée : chaque formulaire invalide n'a rien fait


@needs_bwrap
def test_what_an_action_emits_is_journaled_as_coming_from_the_operator(tmp_path):
    async def scenario(kernel, forge, store):
        await install(kernel, forge, "idees", IDEES, IDEES_CODE)
        done = await perform(kernel, "forge.agir", form({"texte": "un jardin"}, FIXED), by="user_1",
                             subject="idees", nonce="n1")
        return done, events(kernel, EMITTED, forge_c.SIGNALED, rt.OPERATED)

    done, evs = run(tmp_path, scenario)
    emitted = [e for e in evs if e.type.name == EMITTED.name]
    signaled = [e for e in evs if e.type.name == forge_c.SIGNALED.name]
    audit = [e for e in evs if e.type.name == rt.OPERATED.name]
    assert [(e.data.type, json.loads(e.data.data)) for e in emitted] == [("idee", {"texte": "un jardin"})]
    assert len(signaled) == 1 and signaled[0].data.app == "idees"
    assert all(e.origin is Origin.EXTERNAL and e.correlation.startswith("opérateur:forge.agir")
               for e in emitted + signaled)
    assert [(a.data.action, a.data.by, a.data.subject, a.data.outcome) for a in audit] == \
        [("forge.agir", "user_1", "idees", "done")]
    assert set(done.seqs) == {e.seq for e in emitted + signaled}


# ── Régler ────────────────────────────────────────────────────────────────

REGLAGES = """\
title: Réglée
config:
  - {key: ville, type: str, label: Ville, default: Paris}
  - {key: cle, type: secret, label: Clé d'API}
  - {key: n, type: int, label: Combien, min: 1, max: 9, default: 3}
  - {key: actif, type: bool, label: Active, default: true}
  - {key: villes, type: lines, label: Villes, default: [Paris, Lyon]}
views:
  - {key: lire, label: Ce qu'elle lit}
"""
REGLAGES_CODE = '''\
def view_lire(api, params):
    lu = {k: api.config(k) for k in ("ville", "cle", "n", "actif", "villes")}
    return {"version": 2, "blocks": [{"type": "code", "text": repr(sorted(lu.items()))}]}
'''
SECRET = "sk-TRES-SECRET-42"


@needs_bwrap
def test_regler_saves_what_the_app_reads_and_seals_its_secrets(tmp_path):
    async def scenario(kernel, forge, store):
        await install(kernel, forge, "reglee", REGLAGES, REGLAGES_CODE)
        out = {"avant": await forge.call("reglee", "view_lire", {"page": 1})}
        settings = {"ville": "Lyon", "cle": SECRET, "n": "7", "actif": "non", "villes": "Nice\nBrest"}
        out["réglé"] = await perform(kernel, "forge.regler", form(settings), by="user_1", subject="reglee", nonce="r1")
        out["au repos"] = store.settings.forge_config("reglee")
        out["après"] = await forge.call("reglee", "view_lire", {"page": 1})
        out["onglet"] = await tab(kernel, "reglages", "reglee")
        out["hors bornes"] = await perform(kernel, "forge.regler", form({"n": "12"}), by="user_1", subject="reglee",
                                           nonce="r2")
        # un secret laissé vide reste ; un nombre vidé revient au défaut
        again = {"ville": "Lyon", "cle": "", "n": "", "actif": "oui", "villes": "Nice"}
        out["encore"] = await perform(kernel, "forge.regler", form(again), by="user_1", subject="reglee", nonce="r3")
        out["enfin"] = await forge.call("reglee", "view_lire", {"page": 1})
        out["info"] = repr(forge.info("reglee"))
        return out

    got = run(tmp_path, scenario)

    def read(r):
        assert r.ok, r.error
        return r.value["blocks"][0]["text"]

    assert read(got["avant"]) == repr(sorted({"ville": "Paris", "cle": None, "n": 3, "actif": True,
                                              "villes": ["Paris", "Lyon"]}.items()))
    assert got["réglé"].ok
    assert read(got["après"]) == repr(sorted({"ville": "Lyon", "cle": SECRET, "n": 7, "actif": False,
                                              "villes": ["Nice", "Brest"]}.items()))
    stored = got["au repos"]
    assert SECRET not in json.dumps(stored) and stored["cle"].startswith("gAAAA")  # scellé au repos
    assert stored["villes"] == "Nice\nBrest" and stored["n"] == 7
    shown = repr(got["onglet"])
    assert SECRET not in shown and "Badge(text='défini', tone='ok')" in shown
    [slot] = [b for b in got["onglet"] if isinstance(b, ActionSlot)]
    assert slot.action == "forge.regler" and dict(slot.initial)["cle"] == "1"  # « défini », jamais la valeur
    assert got["hors bornes"].errors == {"n": "doit être entre 1 et 9"}
    assert read(got["enfin"]) == repr(sorted({"ville": "Lyon", "cle": SECRET, "n": 3, "actif": True,
                                              "villes": ["Nice"]}.items()))
    assert SECRET not in got["info"]


# ── Les commandes ─────────────────────────────────────────────────────────


@needs_bwrap
def test_the_commands_switch_roll_back_reset_reload_and_erase_with_retyping(tmp_path):
    async def scenario(kernel, forge, store):
        await install(kernel, forge, "meteo", EXAMPLE_MANIFEST, EXAMPLE_CODE)

        def offers():
            return {n for n in ("activer", "arreter", "promouvoir", "retrograder")
                    if offered(kernel, kernel.registry.actions[f"forge.{n}"], "meteo")}

        out = {"offre": offers()}
        out["arrêt"] = await perform(kernel, "forge.arreter", form({}), by="user_1", subject="meteo", nonce="s1")
        await perform(kernel, "forge.promouvoir", form({}), by="user_1", subject="meteo", nonce="s2")
        out["offre après"] = offers()
        await perform(kernel, "forge.agir", meteo_ajout(), by="user_1", subject="meteo", nonce="a1")
        out["vidé"] = await perform(kernel, "forge.vider", form({}), by="user_1", subject="meteo", nonce="v1")
        await forge.write("meteo", EXAMPLE_MANIFEST.replace("Carnet météo", "Carnet météo v2"), EXAMPLE_CODE)
        out["tête périmée"] = Inspection(kernel).head("app", "meteo")
        out["rechargé"] = await perform(kernel, "forge.recharger", form({}), by="user_1", subject="meteo", nonce="l1")
        out["revenu"] = await perform(kernel, "forge.revenir", form({}), by="user_1", subject="meteo", nonce="b1")
        out["état"] = kernel.mind.frame().state("forge").apps["meteo"]
        out["sans retaper"] = await perform(kernel, "forge.effacer", form({}), by="user_1", subject="meteo",
                                            nonce="e1")
        out["mal retapé"] = await perform(kernel, "forge.effacer", form({"_confirmer": "meteo2"}), by="user_1",
                                          subject="meteo", nonce="e2")
        out["encore là"] = forge.info("meteo") is not None
        out["effacé"] = await perform(kernel, "forge.effacer", form({"_confirmer": "meteo"}), by="user_1",
                                      subject="meteo", nonce="e3")
        out["après"] = (forge.info("meteo"), "meteo" in kernel.mind.frame().state("forge").apps)
        out["évts"] = events(kernel, SWITCHED, WRITTEN)
        return out

    got = run(tmp_path, scenario)
    assert got["offre"] == {"arreter", "promouvoir"}
    assert got["arrêt"].ok and got["offre après"] == {"activer", "retrograder"}
    assert got["vidé"].ok and "Stockage vidé (2 clés)" in got["vidé"].message
    assert Badge("à recharger", "warn") in got["tête périmée"].badges  # le disque a une autre version
    assert got["rechargé"].ok and "version 2 est dans sa vie" in got["rechargé"].message
    assert got["revenu"].ok and "version 3" in got["revenu"].message
    state = got["état"]
    # arrêtée par l'opérateur, elle le reste à travers deux nouvelles versions ; la promotion, elle, retombe
    # dès la version suivante ; l'opérateur qui recharge ou remet une version la valide
    assert state.version == 3 and state.title == "Carnet météo" and not state.enabled and state.held
    assert not state.promoted and state.trusted == state.fingerprint != ""
    assert got["sans retaper"].errors == {"_confirmer": "Retape « meteo » pour confirmer."}
    assert not got["mal retapé"].ok and got["encore là"]
    assert got["effacé"].ok and got["effacé"].go == Ref("view", "forge/apps", "Apps forgées")
    assert got["après"] == (None, False)
    states = [e.data.state for e in got["évts"] if e.type.name == SWITCHED.name]
    assert states == ["disabled", "promoted", "trusted", "reset", "erased"]
    versions = [e.data.version for e in got["évts"] if e.type.name == WRITTEN.name]
    assert versions[-2:] == [2, 3] and set(versions) == {1, 2, 3}  # (la découverte au démarrage peut redire la 1)
    assert all(e.origin is Origin.EXTERNAL for e in got["évts"] if e.correlation.startswith("opérateur"))


@needs_bwrap
def test_tester_shows_the_decoded_view_in_place(tmp_path):
    async def scenario(kernel, forge, store):
        await install(kernel, forge, "meteo", EXAMPLE_MANIFEST, EXAMPLE_CODE)
        await install(kernel, forge, "fragile", FRAGILE, FRAGILE_CODE)
        spec = kernel.registry.actions["forge.tester"]
        choices = dynamic_fields(kernel, spec, "meteo", {})[0].choices
        vue = await perform(kernel, "forge.tester", form({"fonction": "view_releves", "args": '{"ville": "Paris"}'}),
                            by="user_1", subject="meteo", nonce="t1")
        act = await perform(kernel, "forge.tester", form({"fonction": "action_releves_ajouter",
                                                          "args": '{"ville": "Nice", "temperature": 18}'}),
                            by="user_1", subject="meteo", nonce="t2")
        bad = await perform(kernel, "forge.tester", form({"fonction": "view_invalide", "args": "{}"}), by="user_1",
                            subject="fragile", nonce="t3")
        unknown = await perform(kernel, "forge.tester", form({"fonction": "tick", "args": "{}"}), by="user_1",
                                subject="meteo", nonce="t4")
        garbled = await perform(kernel, "forge.tester", form({"fonction": "view_releves", "args": "{pas du json"}),
                                by="user_1", subject="meteo", nonce="t5")
        return choices, vue, act, bad, unknown, garbled, list(kernel.mind.store.read(types={EMITTED.name}))

    choices, vue, act, bad, unknown, garbled, emitted = run(tmp_path, scenario)
    assert [v for v, _ in choices] == ["action_releves_ajouter", "action_releves_vider", "view_releves"]
    assert vue.ok and vue.message.startswith("view_releves : enveloppe valide")
    assert isinstance(vue.show[0], Fields) and of(vue.show, Chart) and of(vue.show, Table)
    assert not of(vue.show, ActionSlot)  # un résultat de test n'offre pas de formulaire vivant
    assert act.ok and '"ok": true' in next(b for b in act.show if isinstance(b, Code)).text
    assert bad.tone == "danger" and "blocks[1].rows[0]" in repr(bad.show)
    assert unknown.errors == {"fonction": "choix inconnu : « tick »"}
    assert "JSON illisible" in garbled.errors["args"]
    assert emitted == []  # tester ne journalise rien de ce que l'app fait


@needs_bwrap
def test_forge_test_decodes_a_view_and_names_the_faulty_path(tmp_path):
    h = ForgeHost(tmp_path / "forge")

    async def scenario():
        await h.write("fragile", FRAGILE, FRAGILE_CODE)
        await h.write("meteo", EXAMPLE_MANIFEST, EXAMPLE_CODE)
        return (await _test_view(h, "fragile", "view_invalide", {}),
                await _test_view(h, "meteo", "view_releves", {"ville": "Paris", "froid": True}),
                await _test_view(h, "meteo", "view_nulle", {}))

    try:
        bad, good, missing = asyncio.run(scenario())
    finally:
        h.shutdown()
    assert not bad.ok and "Invalide : blocks[1].rows[0] : 2 cellules pour 1 colonnes" in bad.content
    assert good.ok and "enveloppe valide" in good.content and "formulaires : ajouter, vider" in good.content
    assert not missing.ok and "Pas de vue déclarée pour view_nulle" in missing.content
    assert action_verdict({"ok": True, "message": "Relevé ajouté."}) == "Réponse d'action valide."
    assert action_verdict("d'accord").startswith("Invalide : une action doit rendre")


# ── Le mode d'emploi ──────────────────────────────────────────────────────


class FakeApi:
    """L'api d'une app, en mémoire (pour exécuter l'exemple sans bac à sable)."""

    def __init__(self, config):
        self.store, self.cfg, self.signals = {}, dict(config), []

    def kv_get(self, key, default=None):
        return copy.deepcopy(self.store.get(key, default))

    def kv_set(self, key, value):
        self.store[key] = json.loads(json.dumps(value))
        return True

    def kv_delete(self, key):
        self.store.pop(key, None)
        return True

    def config(self, key, default=None):
        return self.cfg.get(key, default)

    def signal(self, summary, pertinence=0.3, emotion=""):
        self.signals.append(summary)

    def log(self, *parts):
        pass


def test_the_forge_help_example_is_valid_and_its_view_decodes_cleanly(tmp_path):
    manifest, problems = read_manifest(EXAMPLE_MANIFEST)
    code_problems, functions = signatures(EXAMPLE_CODE)
    assert problems == [] and code_problems == [] and coherence(manifest, functions) == []
    host = ForgeHost(tmp_path / "forge", bwrap="")
    asyncio.run(host.write("meteo", EXAMPLE_MANIFEST, EXAMPLE_CODE))
    info = host.info("meteo")
    [spec] = info.views
    api = FakeApi({f.path: f.default for f in info.config_fields})
    app: dict = {}
    exec(compile(EXAMPLE_CODE, "main.py", "exec"), app)  # noqa: S102 — l'exemple lui-même
    for i in range(15):
        answer = app["action_releves_ajouter"](api, {"ville": "Paris", "temperature": float(i - 12), "note": ""})
        assert answer["ok"] is True
    value = json.loads(json.dumps(app["view_releves"](api, {"ville": "Paris", "froid": False, "page": 2})))
    blocks = decode_view(value, "meteo", info, spec)
    assert not is_invalid(blocks), blocks
    [chart] = of(blocks, Chart)
    table = next(t for t in of(blocks, Table) if t.title == "Relevés à Paris")
    assert len(chart.series[0].points) == 15 and table.pager.total == 15 and table.pager.number == 2
    assert {s.action for s in of(blocks, ActionSlot)} == {"forge.agir"} and api.signals  # il gèle fort
    complex_view = {"version": 2, "blocks": [{"type": "workspace", "sidebar": [
        {"type": "toolbar", "items": [{"type": "form", "action": "ajouter", "presentation": "button"}]}],
        "items": value["blocks"]}]}
    nested = decode_view(complex_view, "meteo", info, spec)
    assert not is_invalid(nested), nested
    slots = of(nested, ActionSlot)
    assert len(slots) > 1 and all(s.action == "forge.agir" for s in slots)
    assert slots[0].presentation == "button" and dict(slots[0].initial)["app"] == "meteo"
    for sujet in TOPICS:
        assert len(asyncio.run(forge_help(HelpArgs(sujet=sujet), None))) > 200
    assert "view_releves" in asyncio.run(forge_help(HelpArgs(sujet="exemple"), None))


# ── Par la vraie console (HTML, jeton de formulaire, magasin du serveur) ──


@needs_bwrap
def test_the_app_fiche_renders_and_its_forms_post_through_the_console(world, tmp_path):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    forge, kernel = live.kernel.ports["forge"], live.kernel
    for app, manifest, code in (("meteo", EXAMPLE_MANIFEST, EXAMPLE_CODE), ("reglee", REGLAGES, REGLAGES_CODE)):
        client.portal.call(forge.write, app, manifest, code)
        draft = written_draft(forge.info(app))
        client.portal.call(lambda d=draft: kernel.mind.append([d], emitter="forge", correlation="t",
                                                               origin=Origin.GENESIS))
    fiche = "/inspecteur/fiche/app/meteo?onglet=vues&vue=releves&ville=Paris"
    page = client.get(fiche)
    body = html.unescape(page.text)
    assert page.status_code == 200 and "Température à Paris" in body and "Carnet météo" in body
    ConsoleHTML(page.text).check()
    filters = re.search(r'<form class="filters".*?</form>', body, re.S).group(0)
    assert 'name="onglet" value="vues"' in filters and 'name="vue" value="releves"' in filters
    assert '<input name="ville" value="Paris" type="search"' in filters
    assert '<select name="froid">' in filters and 'name="page"' not in filters
    assert "Paramètres de la vue" not in body
    searched = html.unescape(client.get(fiche.replace("ville=Paris", "ville=Lyon&froid=oui")).text)
    assert 'value="Lyon" type="search"' in searched and 'value="oui" selected' in searched
    assert "Relevés à Lyon" in searched
    assert 'action="/inspecteur/action/forge.agir"' in body and "Ajouter un relevé" in body
    assert "/inspecteur/action/forge.effacer" not in body and "/inspecteur/action/forge.tester" not in body
    management = html.unescape(client.get("/inspecteur/fiche/app/meteo?onglet=etat").text)
    assert "Arrêter" in management and "Effacer" in management and "Tester" in management
    token = client.cookies.get("csrftoken")
    add = {"csrf": token, "_op": "p1", "_retour": fiche, "_sujet": "meteo", "_fixes": ["app", "vue", "action"],
           "app": "meteo", "vue": "releves", "action": "ajouter", "_champs": ["ville", "temperature", "note"],
           "ville": "Paris", "temperature": "-3", "note": "brume"}
    done = client.post("/inspecteur/action/forge.agir", data=add)
    assert done.status_code == 200 and "Relevé ajouté pour Paris." in html.unescape(done.text)
    assert "brume" in html.unescape(client.get(fiche).text)
    bad = client.post("/inspecteur/action/forge.agir", data={**add, "_op": "p2", "temperature": "99"})
    assert bad.status_code == 400 and "doit être entre -60 et 60" in html.unescape(bad.text)
    for tab_name in ("etat", "reglages", "code", "journal", "vecu"):
        r = client.get(f"/inspecteur/fiche/app/meteo?onglet={tab_name}")
        assert r.status_code == 200 and "a échoué" not in html.unescape(r.text), tab_name
        ConsoleHTML(r.text).check()
    assert "/inspecteur/fiche/app/meteo" in html.unescape(client.get("/inspecteur/apps").text)
    # régler : le secret part scellé au repos, l'app le lit, la console n'en dit que « défini »
    settle = {"csrf": token, "_op": "p3", "_retour": "/inspecteur/fiche/app/reglee?onglet=reglages",
              "_sujet": "reglee", "_champs": ["ville", "cle", "n"], "ville": "Lyon", "cle": SECRET, "n": "4"}
    saved = client.post("/inspecteur/action/forge.regler", data=settle)
    assert saved.status_code == 200 and "Réglages enregistrés" in html.unescape(saved.text)
    stored = client.portal.call(live.settings.forge_config, "reglee")
    assert stored["ville"] == "Lyon" and stored["n"] == 4 and SECRET not in json.dumps(stored)
    read = client.portal.call(forge.call, "reglee", "view_lire", {"page": 1})
    assert read.ok and f"('cle', '{SECRET}')" in read.value["blocks"][0]["text"]
    settings_page = html.unescape(client.get("/inspecteur/fiche/app/reglee?onglet=reglages").text)
    assert SECRET not in settings_page and "défini" in settings_page
    # Documents en lecture seule pour la revue visuelle, avec les seules données fictives du test.
    out = tmp_path / "review"
    out.mkdir()
    for name, url in (("forge-vues", fiche), ("forge-reglages", "/inspecteur/fiche/app/reglee?onglet=reglages")):
        rendered = client.get(url).text.replace('/inspecteur/static/', 'static/')
        rendered = rendered.replace('method="post"', 'method="dialog"').replace(' data-vitals="/inspecteur/_vitals"', '')
        (out / (name + ".html")).write_text(rendered)
