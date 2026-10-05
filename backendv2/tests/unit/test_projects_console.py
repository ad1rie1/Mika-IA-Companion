"""La console des projets, par ses intentions (ADR 0031).

- le menu **Projets** se lit neuf (il dit comment commencer) puis vivant : ses
  cartes de compte, la liste, toutes les exécutions, toutes les décisions ;
- **créer** dit champ par champ ce qui ne va pas, journalise le projet puis ses
  objectifs (qui portent son numéro) et mène à sa fiche ;
- la **fiche** gouverne : chaque onglet lit le vrai état ; les formulaires d'onglet
  ne sont pas proposés en tête ; une action par ligne non plus ;
- **modifier** part de ce qu'il est et l'exécution suivante lit le nouveau cadre ;
  un projet qu'elle a ouvert d'elle-même se pilote sans se réécrire ;
- ses **outils** se choisissent et l'exécution suivante les a en main ;
- ses **objectifs** se tiennent : ajouter, cocher, modifier, lancer celui-ci ;
- **décider** depuis la fiche est la décision des Approbations, une seule fois ;
- **déposer** met le fichier dans l'atelier, enregistré à part, et l'exécution
  suivante le sait ; le dépôt git se lit, un commit s'ouvre en diff ;
- archiver, restaurer, reprendre après une panne : sans qu'elle en ressente rien.
"""

from __future__ import annotations

import asyncio

from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.faculties.projects.faculty import DEPOSITED, NUDGED, OBJECTIVE_ADDED, REFRAMED
from mika.inspector.pages.routes import per_row
from mika.kernel.clock import MINUTE, US
from mika.kernel.events import Content, Origin
from mika.kernel.forms import Upload
from mika.kernel.inspect import (
    ActionSlot,
    Code,
    Disclosure,
    Download,
    Grid,
    Head,
    Nav,
    Row,
    Section,
    Stats,
    Table,
    Toolbar,
)
from mika.runtime.inspection import Inspection
from mika.runtime.operations import initial_values, offered, perform
from mika.sim.llm.persona import _section
from tests.fixtures.atelier import Atelier
from tests.unit.test_goals_console import field, flat, nested
from tests.unit.test_projects import create, events, form, live, wait

TABS = ["apercu", "objectifs", "executions", "decisions", "fichiers", "git", "comportement", "carnet"]


def row_form(fixed: dict[str, str], **values: str) -> dict[str, list[str]]:
    return {**form(**values), "_fixes": list(fixed), **{k: [v] for k, v in fixed.items()}}


async def tab(kernel, name: str, subject: str = "", **params: str) -> list:
    ins = Inspection(kernel)
    spec = ins.find("projects", name)
    assert spec is not None, name
    blocks = await ins.arun(spec, params, subject=subject)
    failed = [b.text for b in nested(blocks) if hasattr(b, "text") and str(b.text).startswith("Cette vue a échoué")]
    assert not failed, failed
    return blocks


def tables(blocks) -> dict[str, Table]:
    out = {}
    for b in nested(blocks):
        if isinstance(b, Table):
            out[b.title] = b
        if isinstance(b, Row):
            out |= tables(b.detail)
    return out


def prompt(llm) -> str:
    return next((_section(r, "CE PROJET") for r in reversed(llm.calls) if r.role in ("project", "job")), "")


# ── Le menu, neuf puis vivant ─────────────────────────────────────────────


def test_the_projects_menu_fresh_then_alive(tmp_path):
    async def scenario(kernel, llm):
        ins = Inspection(kernel)
        fresh = {"views": [v.name for v in ins.in_section("projets")], "tabs": [v.name for v in ins.tabs("project")],
                 "list": await tab(kernel, "tous"), "runs": await tab(kernel, "toutes_executions"),
                 "decisions": await tab(kernel, "toutes_decisions"), "head": ins.head("project", "1"),
                 "search": ins.search("project", "")}
        pid = await create(kernel, "p1", title="Outils réseau", objectives="Créer un module RDP\nSa documentation",
                           constants="Améliorer la sécurité", mode="plain", days="weekdays", start="9:00", end="18:00",
                           remote="https://github.com/moi/outils.git")
        await wait(40)
        await kernel.lanes.join()
        alive = {"list": await tab(kernel, "tous"), "runs": await tab(kernel, "toutes_executions"),
                 "runs_filtered": await tab(kernel, "toutes_executions", projet=str(pid), verdict="blocked"),
                 "archived": await tab(kernel, "tous", etat="archived"), "head": ins.head("project", f"#{pid}"),
                 "by_title": ins.search("project", "RÉSEAU"), "by_number": ins.search("project", f"#{pid}"),
                 "person": await ins.arun(next(v for v in ins.tabs("person") if v.owner == "projects"), {},
                                          subject="user_1")}
        return fresh, alive, pid

    fresh, alive, pid = live(tmp_path, scenario)
    assert fresh["views"] == ["tous", "toutes_executions", "toutes_decisions"]
    assert fresh["tabs"] == TABS
    assert "aucun projet" in flat(fresh["list"]) and "Créer un projet" in flat(fresh["list"])
    assert "aucune exécution encore" in flat(fresh["runs"]) and "aucune décision" in flat(fresh["decisions"])
    assert fresh["head"] is None and fresh["search"] == []
    # vivant : les cartes, la liste
    listing = alive["list"]
    row = tables(listing)["Projets"].rows[0]
    assert row.href.key == f"project/{pid}" and row.cells[0].text == "Outils réseau"
    assert row.cells[1].text == "impersonnel"
    assert row.cells[4].text.endswith(" / 2 ponctuel(s), 1 constant(s)")  # ses deux ponctuels, son constant
    assert row.cells[9] == "les jours ouvrés, de 9 h à 18 h" and "github.com/moi/outils" in row.cells[12].text
    stats = next(b for b in listing if isinstance(b, Stats))
    counts = {st.label: st.value for st in stats.items}
    assert counts["Actifs"] == 1 and counts["Exécutions (24 h)"] >= 1 and counts["Archivés"] == 0
    assert "aucun projet avec ces filtres" in flat(alive["archived"])
    runs = tables(alive["runs"])["Les exécutions"]
    assert runs.rows and runs.rows[0].cells[1].text == "Outils réseau" and runs.rows[0].cells[3].text == "fait"
    assert "n° " in runs.rows[0].cells[2].text and runs.rows[0].cells[6].kind == "subject"  # le commit, ouvrable
    assert "aucune exécution avec ces filtres" in flat(alive["runs_filtered"])
    head = alive["head"]
    assert isinstance(head, Head) and head.key == str(pid) and head.title == "Outils réseau"
    assert [b.text for b in head.badges][:3] == ["impersonnel", "actif", "confié"] and head.default_tab == "apercu"
    assert [f.key for f in alive["by_title"]] == [str(pid)] == [f.key for f in alive["by_number"]]
    assert "Outils réseau" in flat(alive["person"])
    # avant d'oublier quelqu'un, sa fiche dit ce que l'oubli n'atteint pas : l'atelier de ses projets (PRJ-9)
    assert "pas leurs ateliers" in flat(alive["person"]) and "Vider le stockage" in flat(alive["person"])


# ── Créer ─────────────────────────────────────────────────────────────────


def test_creating_says_what_is_wrong_field_by_field_and_leads_to_the_fiche(tmp_path):
    async def scenario(kernel, llm):
        bad = await perform(kernel, "projects.creer", form(
            title=" ", schedule="tous les jours", start="25:00", end="midi", owner="personne_x", mode="persona",
            days="all", remote="http://github.com/x", branch="../main", cadence_hours="0", runs_per_day="0",
            priority="normal"), by="user_1", nonce="b1")
        ok = await perform(kernel, "projects.creer", form(
            ("approval", "auto_push"), title="Un module", objectives="Écrire le module\n\n", constants="Le tenir à jour",
            cadence_hours="6", mode="persona", schedule="interval:2h", days="all", start="", end="", runs_per_day="5",
            priority="high", branch="main", tool_memory="on", tool_rss="on"), by="user_1", nonce="b2")
        return bad, ok, events(kernel, c.PROJECT_CREATED), events(kernel, OBJECTIVE_ADDED), events(kernel, rt.OPERATED)

    bad, ok, created, objectives, audit = live(tmp_path, scenario)
    assert not bad.ok
    assert set(bad.errors) == {"title", "objectives", "schedule", "start", "end", "owner", "remote", "branch"}
    assert "une adresse https" in bad.errors["remote"] and "au moins un objectif" in bad.errors["objectives"]
    assert ok.ok and ok.go is not None and ok.go.key == f"project/{created[0].seq}"  # créé : on arrive sur sa fiche
    [p] = created
    assert p.origin is Origin.EXTERNAL and p.data.source == "operator" and p.data.owner == "user_1"
    assert p.data.approval is False and p.data.schedule == "interval:2h" and p.data.runs_per_day == 5
    assert set(p.data.bundles) == {"projects", "workshop", "memory", "rss"}
    # ses objectifs suivent aussitôt, sous son numéro (lignes vides ignorées)
    assert [(o.data.project, o.data.objective, o.data.kind, o.data.cadence_us) for o in objectives] == [
        (p.seq, 1, c.ONCE, 0), (p.seq, 2, c.CONSTANT, 6 * 3600 * US)]
    [done] = [e for e in audit if e.data.outcome == "done"]
    assert done.data.action == "projects.creer" and set(done.data.seqs) >= {p.seq, *(o.seq for o in objectives)}


# ── La fiche ──────────────────────────────────────────────────────────────


def test_every_tab_reads_a_project_that_lived_and_the_forms_stay_in_their_tabs(tmp_path):
    atelier = Atelier()

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le module", objectives="Écrire le module", approval="on",
                           constants="Le relire", remote="https://github.com/moi/module.git")
        await perform(kernel, "projects.decision_ajouter", form(title="Langage", choice="Python", reason="simple",
                                                                context="", options="", replaces="0"),
                      by="user_1", subject=str(pid), nonce="d1")
        await wait(40)
        await kernel.lanes.join()
        await kernel.mind.append([rt.EFFECT_PROPOSED.draft(
            capability="projects.networked", owner="projects", args_json=f'{{"project": {pid}, "argv": ["true"]}}',
            summary=Content.of("installer requests", level=0), approval=True, context=f"project:{pid}")],
            emitter="runtime", correlation="t", origin=Origin.TOOL)
        tabs = {name: await tab(kernel, name, str(pid)) for name in TABS}
        tabs["tous les objectifs"] = await tab(kernel, "objectifs", str(pid), objectifs="tous")
        commits = await atelier.commits(pid, 1)
        tabs["commit"] = await tab(kernel, "git", str(pid), commit=commits[0].sha)
        tabs["file"] = await tab(kernel, "fichiers", str(pid), fichier="JOURNAL.md")
        ins = Inspection(kernel)
        specs = [a for a in ins.actions_for(subject="project")]
        head = [a.key for a in specs if not a.inline and not per_row(a) and offered(kernel, a, str(pid))]
        return tabs, head, pid

    tabs, head, pid = live(tmp_path, scenario, atelier=atelier)
    # en tête : ce qui vaut pour tout le projet (les formulaires des onglets, et les lignes, n'y sont pas)
    assert head == ["projects.lancer", "projects.pause", "projects.consigne", "projects.archiver"]
    overview = tabs["apercu"]
    assert "À décider (1)" in flat(overview) and "installer requests" in flat(overview)
    grid = next(b for b in overview if isinstance(b, Grid))
    assert [f.title for f in grid.items] == ["Où il en est", "Prochaine exécution", "Son dépôt"]
    assert "Dernières exécutions" in flat(overview) and "Décisions en vigueur (les dernières)" in flat(overview)
    # par défaut, ce qui vit (le ponctuel fait se filtre) ; tous : ce qui revient d'abord
    assert [r.cells[2].text for r in tables(tabs["objectifs"])["Ses objectifs"].rows] == ["constant"]
    objectifs = tables(tabs["tous les objectifs"])["Ses objectifs"]
    assert [r.cells[2].text for r in objectifs.rows] == ["constant", "ponctuel"]
    assert any(isinstance(b, ActionSlot) and b.action == "projects.objectif_ajouter" for b in nested(tabs["objectifs"]))
    runs = tables(tabs["executions"])["Ses exécutions"]
    assert runs.rows and runs.rows[-1].cells[1] == "Mika" and runs.rows[-1].cells[4].text == "fait"
    assert runs.rows[-1].cells[10].params == (("onglet", "prompt"),)
    decisions = tables(tabs["decisions"])["Ses décisions (1 en vigueur)"]
    assert decisions.rows[0].cells[0] == "D1" and decisions.rows[0].cells[2].text == "Python"
    files = tables(tabs["fichiers"])["Le dossier du projet"]
    assert [r.cells[0].text for r in files.rows] == ["JOURNAL.md"]
    git = tabs["git"]
    history = tables(git)["Historique"]
    assert history.rows[-1].cells[1].text == "atelier ouvert" and history.rows[-1].cells[6] == "amorce"
    assert history.rows[0].cells[6].kind == "episode"  # le commit d'une exécution mène à elle
    remote = next(b for b in nested(git) if isinstance(b, Section) and b.title == "Son dépôt distant")
    assert "github.com/moi/module" in flat([remote]) and any(
        isinstance(b, ActionSlot) and b.action == "projects.pousser" for b in nested([remote]))
    opened = next(b for b in nested(tabs["commit"]) if isinstance(b, Code))
    assert opened.lang == "diff" and "+après" in opened.text
    shown = next(b for b in tabs["file"] if isinstance(b, Code))
    assert shown.title == "JOURNAL.md" and "Travail" in shown.text
    behaviour = tabs["comportement"]
    assert isinstance(behaviour[0], ActionSlot) and behaviour[0].action == "projects.modifier"
    tools = tables(behaviour)["Ce qu'elle a en main pendant une exécution"]
    assert {r[0].text for r in tools.rows} == {"ses outils de projet", "son atelier", "sa mémoire (souvenirs, croyances)"}
    assert any("ws_write" in r[2].text for r in tools.rows)
    carnet = tabs["carnet"]
    assert "objectif n° 1 ajouté" in flat(carnet) and "attend ton accord" in flat(carnet)


# ── Modifier, ses outils ──────────────────────────────────────────────────


def test_modifying_starts_from_what_it_is_and_the_next_run_reads_the_new_frame(tmp_path):
    async def scenario(kernel, llm):
        pid = str(await create(kernel, "p1", title="Ranger les notes", description="Les classer par date.",
                               constants="Les garder rangées", cadence_hours="1", start="8:00", end="20:00"))
        spec = kernel.registry.actions["projects.modifier"]
        out = {"initial": initial_values(kernel, spec, pid)}
        values = {k: str(v) for k, v in out["initial"].items() if k != "approval"}
        out["unchanged"] = await perform(kernel, "projects.modifier", form(("approval",), **values), by="user_1",
                                         subject=pid, nonce="m0")
        out["ok"] = await perform(kernel, "projects.modifier", form(
            **{**values, "description": "Les classer par sujet, pas par date.", "mode": "plain", "priority": "high",
               "days": "weekend", "approval": "on"}), by="user_1", subject=pid, nonce="m1")
        out["tools"] = await perform(kernel, "projects.outils", form(tool_memory="on", tool_rss="on"), by="user_1",
                                     subject=pid, nonce="t1")
        await perform(kernel, "projects.lancer", form(), by="user_1", subject=pid, nonce="l1")
        await wait(15)
        await kernel.lanes.join()
        out["prompt"] = prompt(llm)
        out["offered"] = {t.name for r in llm.calls if r.role == "job" for t in r.tools}
        out["reframed"] = events(kernel, REFRAMED)
        out["project"] = kernel.mind.frame().state("projects").projects[int(pid)]
        return out

    out = live(tmp_path, scenario, start=at_saturday())
    initial = out["initial"]
    assert initial["description"] == "Les classer par date." and initial["start"] == "08:00" and initial["end"] == "20:00"
    assert initial["mode"] == "persona" and initial["approval"] is False
    assert not out["unchanged"].ok and "Rien n'a changé" in out["unchanged"].message
    assert out["ok"].ok and out["tools"].ok
    p = out["project"]
    assert (p.mode, p.priority, p.days, p.approval) == (c.PLAIN, c.HIGH, c.WEEKEND, True)
    assert "rss" in p.bundles and "workshop" in p.bundles
    assert "Les classer par sujet, pas par date." in out["prompt"] and "Mode impersonnel" in out["prompt"]
    assert "rss_read" in out["offered"] or "rss_list" in out["offered"]  # ses nouveaux outils, en main
    assert all(e.origin is Origin.EXTERNAL and e.data.by == "user_1" for e in out["reframed"])


def at_saturday() -> int:
    from tests.fixtures.mika import at_paris

    return at_paris(2026, 10, 3, 10, 0)


def test_her_own_project_is_driven_but_not_rewritten(tmp_path):
    async def scenario(kernel, llm):
        created = await kernel.mind.append([c.PROJECT_CREATED.draft(
            title=Content.of("Son carnet de jeux", level=0), authority=c.SELF, source="conversation", sensitivity=0)],
            emitter="projects", correlation="genese", origin=Origin.GENESIS)
        pid = str(created.seqs[-1])
        values = {k: str(v) for k, v in initial_values(kernel, kernel.registry.actions["projects.modifier"], pid).items()
                  if k != "approval"}
        renamed = await perform(kernel, "projects.modifier", form(("approval",), **{**values, "title": "Autre chose"}),
                                by="user_1", subject=pid, nonce="m1")
        paced = await perform(kernel, "projects.modifier", form(("approval",), **{**values, "priority": "low"}),
                              by="user_1", subject=pid, nonce="m2")
        return renamed, paced, await tab(kernel, "comportement", pid)

    renamed, paced, behaviour = live(tmp_path, scenario)
    assert not renamed.ok and "on le pilote, on ne le renomme pas" in renamed.errors["title"]
    assert paced.ok  # son rythme, oui
    assert "ni son titre ni ce qu'elle veut en faire" in flat(behaviour)


# ── Ses objectifs ─────────────────────────────────────────────────────────


def test_objectives_are_kept_from_the_fiche(tmp_path):
    async def scenario(kernel, llm):
        pid = str(await create(kernel, "p1", title="Le module", objectives="Écrire le module", start="3:00",
                               end="4:00"))  # hors de sa plage : rien ne part tout seul
        out = {
            "added": await perform(kernel, "projects.objectif_ajouter", form(text="Améliorer la sécurité",
                                                                            kind="constant", cadence_hours="12"),
                                   by="user_1", subject=pid, nonce="a1"),
            "done": await perform(kernel, "projects.objectif_statut", row_form({"objective": "1", "status": "done"}),
                                  by="user_1", subject=pid, nonce="s1"),
            "constant_done": await perform(kernel, "projects.objectif_statut",
                                           row_form({"objective": "2", "status": "done"}), by="user_1", subject=pid,
                                           nonce="s2"),
            "edit": await perform(kernel, "projects.objectif_modifier", row_form(
                {"objective": "2"}, text="Durcir la sécurité", kind="constant", cadence_hours="24"), by="user_1",
                subject=pid, nonce="e1"),
            "launch": await perform(kernel, "projects.lancer_objectif", row_form({"objective": "2"}), by="user_1",
                                    subject=pid, nonce="l1"),
            "launch_done": await perform(kernel, "projects.lancer_objectif", row_form({"objective": "1"}),
                                         by="user_1", subject=pid, nonce="l2"),
        }
        before = kernel.mind.frame().get(self_c.ESTEEM)
        await wait(10)
        await kernel.lanes.join()
        out["esteem"] = (before, kernel.mind.frame().get(self_c.ESTEEM))
        out["project"] = kernel.mind.frame().state("projects").projects[int(pid)]
        out["nudged"] = events(kernel, NUDGED)
        out["prompt"] = prompt(llm)
        out["per_row"] = {k: per_row(kernel.registry.actions[f"projects.{k}"])
                          for k in ("objectif_statut", "objectif_modifier", "lancer_objectif", "approuver",
                                    "objectif_ajouter", "lancer")}
        return out

    out = live(tmp_path, scenario)
    assert out["added"].ok and out["done"].ok and out["edit"].ok and out["launch"].ok
    assert not out["constant_done"].ok and "ne se coche pas" in out["constant_done"].message
    assert not out["launch_done"].ok
    o1, o2 = out["project"].objectives
    assert o1.status == c.DONE and (o2.kind, o2.cadence_us) == (c.CONSTANT, 24 * 3600 * US)
    assert out["esteem"][0] == out["esteem"][1]  # cocher pour elle ne la rend pas fière
    assert [e.data.objective for e in out["nudged"]] == [2]
    assert "L'objectif de cette exécution :\n- n° 2 [constant" in out["prompt"] and "Durcir la sécurité" in out["prompt"]
    assert out["per_row"] == {"objectif_statut": True, "objectif_modifier": True, "lancer_objectif": True,
                              "approuver": True, "objectif_ajouter": False, "lancer": False}


# ── Décider, déposer, pousser ─────────────────────────────────────────────


def test_deciding_from_the_fiche_is_the_approvals_decision_once(tmp_path):
    async def scenario(kernel, llm):
        pid = str(await create(kernel, "p1", title="Le module", objectives="Écrire le module", approval="on"))
        await perform(kernel, "projects.pause", form(), by="user_1", subject=pid, nonce="p")

        async def propose(what: str) -> int:
            got = await kernel.mind.append([rt.EFFECT_PROPOSED.draft(
                capability="projects.networked", owner="projects", args_json=f'{{"project": {pid}, "argv": ["true"]}}',
                summary=Content.of(what, level=0), approval=True, context=f"project:{pid}")], emitter="runtime",
                correlation="t", origin=Origin.TOOL)
            return got.seqs[-1]

        yes, no = await propose("installer requests"), await propose("télécharger un jeu de données")
        out = {"apercu": await tab(kernel, "apercu", pid),
               "yes": await perform(kernel, "projects.approuver", row_form({"proposal": str(yes)}), by="user_1",
                                    subject=pid, nonce="y"),
               "twice": await perform(kernel, "projects.approuver", row_form({"proposal": str(yes)}), by="user_1",
                                      subject=pid, nonce="y2"),
               "no": await perform(kernel, "projects.refuser", row_form({"proposal": str(no)}, note="pas de réseau"),
                                   by="user_1", subject=pid, nonce="n"),
               "offered": offered(kernel, kernel.registry.actions["projects.approuver"], pid)}
        await kernel.lanes.join()
        out["resolved"] = [(e.data.proposal, e.data.approved, e.data.by, e.data.said())
                           for e in events(kernel, rt.EFFECT_RESOLVED)]
        out["ids"] = (yes, no)
        out["carnet"] = await tab(kernel, "carnet", pid)
        return out

    out = live(tmp_path, scenario)
    yes, no = out["ids"]
    assert "À décider (2)" in flat(out["apercu"]) and "installer requests" in flat(out["apercu"])
    assert out["yes"].ok and out["no"].ok and not out["twice"].ok  # une décision ne se prend qu'une fois
    assert out["resolved"] == [(yes, True, "user_1", ""), (no, False, "user_1", "pas de réseau")]
    assert out["offered"] is False
    assert "refusé" in flat(out["carnet"])


def test_a_deposited_file_lands_in_the_workshop_and_the_next_run_knows(tmp_path):
    atelier = Atelier()

    async def scenario(kernel, llm):
        pid = str(await create(kernel, "p1", title="Le module", constants="Analyser les mesures", cadence_hours="1"))
        await perform(kernel, "projects.pause", form(), by="user_1", subject=pid, nonce="p")

        def upload(**values):
            data = {"_champs": ["file", "folder", "note"], "folder": [values.get("folder", "")],
                    "note": [values.get("note", "")]}
            if "file" in values:
                data["file"] = [values["file"]]
            return data

        out = {
            "none": await perform(kernel, "projects.deposer", upload(), by="user_1", subject=pid, nonce="d0"),
            "big": await perform(kernel, "projects.deposer", upload(file=Upload(name="x.bin", too_big=True)),
                                 by="user_1", subject=pid, nonce="d1"),
            "escape": await perform(kernel, "projects.deposer", upload(file=Upload(name="x.csv", data=b"a"),
                                                                        folder="../ailleurs"),
                                    by="user_1", subject=pid, nonce="d2"),
            "ok": await perform(kernel, "projects.deposer", upload(file=Upload(name="../../mesures.csv",
                                                                               data=b"a,b\n1,2"),
                                                                   folder="entree", note="Les mesures de mars."),
                                by="user_1", subject=pid, nonce="d3"),
        }
        await perform(kernel, "projects.reprendre", form(), by="user_1", subject=pid, nonce="r")
        await wait(15)
        await kernel.lanes.join()
        out["prompt"] = prompt(llm)
        out["events"] = events(kernel, DEPOSITED)
        out["download"] = await Inspection(kernel).download("project", pid, "entree/mesures.csv")
        out["outside"] = await Inspection(kernel).download("project", pid, "../mind.db")
        out["files"] = await tab(kernel, "fichiers", pid)
        out["folder"] = await tab(kernel, "fichiers", pid, dossier="entree")
        out["pid"] = int(pid)
        return out

    out = live(tmp_path, scenario, atelier=atelier)
    assert not out["none"].ok and "file" in out["none"].errors
    assert not out["big"].ok and "trop gros" in out["big"].errors["file"]
    assert not out["escape"].ok
    assert out["ok"].ok, out["ok"]
    assert atelier.files[out["pid"]]["entree/mesures.csv"] == "a,b\n1,2"  # le nom perd ses dossiers
    assert atelier.commits_[out["pid"]][1][1] == "apport de l'opérateur : entree/mesures.csv"
    [deposited] = out["events"]
    assert deposited.data.name == "entree/mesures.csv" and deposited.data.size == 7
    assert "entree/mesures.csv" in out["prompt"] and "Les mesures de mars." in out["prompt"]
    assert isinstance(out["download"], Download) and out["download"].data == b"a,b\n1,2"
    assert not isinstance(out["outside"], Download)
    root = tables(out["files"])["Le dossier du projet"]
    assert [r.cells[0].text for r in root.rows] == ["entree/", "JOURNAL.md"]  # les dossiers d'abord
    nav = next(b for b in out["folder"] if isinstance(b, Nav))
    assert [i.text for i in nav.items] == ["racine", "entree"] and nav.items[-1].active
    assert [r.cells[0].text for r in tables(out["folder"])["/entree"].rows] == ["mesures.csv"]


def test_git_history_pages_beyond_five_hundred_commits(tmp_path):
    atelier = Atelier()

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Historique", objectives="Vérifier les versions", start="3:00",
                           end="4:00")
        await atelier.write(pid, "notes.txt", "exemple")
        atelier.commits_[pid] = [(f"c{i:06}", f"Version {i}") for i in range(555)]
        first = tables(await tab(kernel, "git", str(pid)))["Historique"]
        last = tables(await tab(kernel, "git", str(pid), page_commits="23"))["Historique"]
        return first, last

    first, last = live(tmp_path, scenario, atelier=atelier)
    assert len(first.rows) == 25 and first.pager.total == 555 and first.rows[0].cells[1].text == "Version 554"
    assert len(last.rows) == 5 and last.rows[-1].cells[1].text == "Version 0"


def test_pushing_and_pulling_from_the_git_tab(tmp_path):
    atelier = Atelier(token="ghp_secret")

    async def scenario(kernel, llm):
        pid = str(await create(kernel, "p1", title="Outils", objectives="Écrire l'outil", start="3:00", end="4:00"))
        out = {"no_remote": offered(kernel, kernel.registry.actions["projects.pousser"], pid)}
        out["bad"] = await perform(kernel, "projects.depot_distant", form(remote="https://moi:pw@github.com/x.git",
                                                                         branch="main"), by="user_1", subject=pid,
                                   nonce="r0")
        out["set"] = await perform(kernel, "projects.depot_distant", form(remote="https://github.com/moi/x.git",
                                                                         branch="dev", auto_push="on"),
                                   by="user_1", subject=pid, nonce="r1")
        out["pull"] = await perform(kernel, "projects.recuperer", form(), by="user_1", subject=pid, nonce="u1")
        await asyncio.sleep(MINUTE / US)
        out["push"] = await perform(kernel, "projects.pousser", form(), by="user_1", subject=pid, nonce="u2")
        await asyncio.sleep(MINUTE / US)
        out["git"] = await tab(kernel, "git", pid)
        out["executed"] = events(kernel, rt.EFFECT_EXECUTED)
        out["journal"] = "".join(str(e.data) for e in events(kernel, rt.EFFECT_PROPOSED, rt.EFFECT_EXECUTED))
        return out

    out = live(tmp_path, scenario, atelier=atelier)
    assert out["no_remote"] is False  # sans dépôt distant, rien à pousser
    assert not out["bad"].ok and "pas d'identifiants" in out["bad"].errors["remote"]
    assert out["set"].ok and out["pull"].ok and out["push"].ok
    assert atelier.pulled and atelier.pushed == [(atelier.pulled[0][0], "https://github.com/moi/x.git", "dev")]
    assert [e.data.ok for e in out["executed"]] == [True, True]
    assert "ghp_secret" not in out["journal"]  # le jeton ne passe jamais par le journal
    git = out["git"]
    assert "depuis le distant" in flat(git) and "pousser vers le dépôt distant" in flat(git)


# ── Pause, archive, panne ─────────────────────────────────────────────────


def test_archiving_restoring_and_resuming_after_a_breakdown_feel_like_nothing(tmp_path):
    async def scenario(kernel, llm):
        llm.fail["project"] = 3
        pid = str(await create(kernel, "p1", title="Le module", objectives="Écrire le module"))
        await wait(90)
        await kernel.lanes.join()
        frame = kernel.mind.frame()
        out = {"broken": frame.state("projects").projects[int(pid)], "esteem": frame.get(self_c.ESTEEM),
               "apercu": await tab(kernel, "apercu", pid)}
        out["resume"] = await perform(kernel, "projects.reprendre", form(), by="user_1", subject=pid, nonce="r1")
        out["archive"] = await perform(kernel, "projects.archiver", form(), by="user_1", subject=pid, nonce="a1")
        out["archived_tab"] = await tab(kernel, "comportement", pid)
        out["offered"] = {k: offered(kernel, kernel.registry.actions[f"projects.{k}"], pid)
                          for k in ("lancer", "pause", "reprendre", "archiver", "restaurer", "modifier")}
        out["restore"] = await perform(kernel, "projects.restaurer", form(), by="user_1", subject=pid, nonce="x1")
        out["status"] = kernel.mind.frame().get(c.STATUS(int(pid)))
        out["esteem_after"] = kernel.mind.frame().get(self_c.ESTEEM)
        out["carnet"] = await tab(kernel, "carnet", pid)
        return out

    out = live(tmp_path, scenario)
    broken = out["broken"]
    assert broken.status == c.PAUSED and "en panne" in broken.pause_reason
    assert "en panne" in flat(out["apercu"]) and "Reprendre" in flat(out["apercu"])
    assert out["resume"].ok and out["archive"].ok and out["restore"].ok
    assert "archivé ne se modifie plus" in flat(out["archived_tab"])
    assert out["offered"] == {"lancer": False, "pause": False, "reprendre": False, "archiver": False,
                              "restaurer": True, "modifier": False}
    assert out["status"] == c.PAUSED  # restauré, il revient en pause
    assert out["esteem"] == out["esteem_after"]  # piloter ne lui fait rien ressentir
    assert "archivé" in flat(out["carnet"]) and "restauré" in flat(out["carnet"])


def test_tab_forms_and_row_buttons_carry_their_row(tmp_path):
    async def scenario(kernel, llm):
        pid = str(await create(kernel, "p1", title="Le module", objectives="Écrire le module", start="3:00",
                               end="4:00"))
        await perform(kernel, "projects.decision_ajouter", form(title="Langage", choice="Python", reason="",
                                                                context="", options="", replaces="0"),
                      by="user_1", subject=pid, nonce="d1")
        return await tab(kernel, "objectifs", pid), await tab(kernel, "decisions", pid)

    objectifs, decisions = live(tmp_path, scenario)
    row = tables(objectifs)["Ses objectifs"].rows[0]
    slots = [b for b in nested(row.detail) if isinstance(b, ActionSlot)]
    assert {(b.action, dict(b.initial).get("status", "")) for b in slots} >= {
        ("projects.objectif_statut", "done"), ("projects.objectif_statut", "dropped"),
        ("projects.objectif_modifier", "")}
    assert all(dict(b.initial).get("objective") == "1" for b in slots)
    toolbar = next(b for b in nested(row.detail) if isinstance(b, Toolbar))
    assert toolbar.title == "Cet objectif"
    drow = tables(decisions)["Ses décisions (1 en vigueur)"].rows[0]
    replace_form = next(b for b in nested(drow.detail) if isinstance(b, Disclosure))
    [slot] = [b for b in nested(replace_form.items) if isinstance(b, ActionSlot)]
    assert slot.action == "projects.decision_ajouter" and dict(slot.initial)["replaces"] == "1"
    assert field(drow.detail, "pourquoi").text == "—"


# ── Ce que la relecture a trouvé ──────────────────────────────────────────


def test_diff_lines_are_classified_by_where_they_are():
    from mika.inspector.render import diff_kinds

    lines = ["commit abc", "    - une puce du message", "diff --git a/x.sql b/x.sql", "--- a/x.sql", "+++ b/x.sql",
             "@@ -1,2 +1,2 @@", "-- un commentaire SQL retiré", "++compteur;", " contexte", "\\ No newline at end of file"]
    assert diff_kinds(lines) == ["", "", "meta", "meta", "meta", "hunk", "del", "add", "", ""]


def test_files_git_and_deposits_tell_the_truth(tmp_path):
    atelier = Atelier()

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le module", objectives="Écrire le module", start="3:00", end="4:00")
        for i in range(3):
            await atelier.write(pid, f"src/m{i}.py", "x")
        await atelier.write(pid, "README.md", "lisez-moi")
        await atelier.commit(pid, "début")
        await atelier.write(pid, "nouveau.py", "pas encore suivi")  # du travail en cours, non enregistré

        def upload(name, data, **values):
            return {"_champs": ["file", "folder", "note", "replace"], "folder": [values.get("folder", "")],
                    "note": [""], "file": [Upload(name=name, data=data)], **(
                        {"replace": ["on"]} if values.get("replace") else {})}

        out = {"exists": await perform(kernel, "projects.deposer", upload("README.md", b"autre"), by="user_1",
                                       subject=str(pid), nonce="d1"),
               "replace": await perform(kernel, "projects.deposer", upload("README.md", b"autre", replace=True),
                                        by="user_1", subject=str(pid), nonce="d2")}
        out["pending"] = await atelier.pending(pid)
        out["src"] = await tab(kernel, "fichiers", str(pid), dossier="src")
        out["git"] = await tab(kernel, "git", str(pid))
        return out

    out = live(tmp_path, scenario, atelier=atelier)
    assert not out["exists"].ok and "existe déjà" in out["exists"].message  # rien n'est écrasé sans le dire
    assert out["replace"].ok
    assert out["pending"] == ["nouveau.py"]  # le dépôt n'a enregistré que lui-même : le travail en cours reste
    assert [r.cells[0].text for r in tables(out["src"])["/src"].rows] == ["m0.py", "m1.py", "m2.py"]
    stats = next(b for b in out["git"] if isinstance(b, Stats))
    assert dict((st.label, st.value) for st in stats.items)["Non enregistré"] == "1 fichier(s)"


def test_stale_pages_cannot_undo_a_replacement_nor_approve_an_archived_project(tmp_path):
    async def scenario(kernel, llm):
        pid = str(await create(kernel, "p1", title="Le module", objectives="Écrire le module", approval="on",
                               start="3:00", end="4:00"))
        for i, (choice, replaces) in enumerate((("Python", "0"), ("Rust", "1"))):
            await perform(kernel, "projects.decision_ajouter", form(title="Langage", choice=choice, reason="",
                                                                    context="", options="", replaces=replaces),
                          by="user_1", subject=pid, nonce=f"d{i}")
        stale = await perform(kernel, "projects.decision_statut", row_form({"decision": "1", "status": "withdrawn"}),
                              by="user_1", subject=pid, nonce="s1")
        await kernel.mind.append([rt.EFFECT_PROPOSED.draft(
            capability="projects.networked", owner="projects", args_json=f'{{"project": {pid}, "argv": ["true"]}}',
            summary=Content.of("installer", level=0), approval=True, context=f"project:{pid}")],
            emitter="runtime", correlation="t", origin=Origin.TOOL)
        await perform(kernel, "projects.archiver", form(), by="user_1", subject=pid, nonce="a1")
        specs = kernel.registry.actions
        return stale, offered(kernel, specs["projects.approuver"], pid), offered(kernel, specs["projects.refuser"], pid)

    stale, approve, refuse = live(tmp_path, scenario)
    assert not stale.ok and "remplacée" in stale.message
    assert approve is False and refuse is True  # un projet archivé ne fait plus rien sortir ; refuser, si


def test_her_project_with_a_forgotten_title_can_still_be_driven(tmp_path):
    async def scenario(kernel, llm):
        created = await kernel.mind.append([c.PROJECT_CREATED.draft(
            title=Content.of("Le carnet d'Alice", level=1), authority=c.SELF, about=("user_9",),
            source="conversation", sensitivity=1)], emitter="projects", correlation="genese", origin=Origin.GENESIS)
        pid = str(created.seqs[-1])
        await kernel.forget("user_9")
        values = {k: str(v) for k, v in initial_values(kernel, kernel.registry.actions["projects.modifier"], pid).items()
                  if k != "approval"}
        return values["title"], await perform(kernel, "projects.modifier", form(("approval",), **{
            **values, "priority": "high"}), by="user_1", subject=pid, nonce="m1")

    title, paced = live(tmp_path, scenario)
    assert title == "" and paced.ok  # le titre oublié reste oublié, le reste se pilote


# ── Ce qui sort, et les gardes de la fiche (CON-13, CON-15, CON-24) ───────


def test_what_leaves_the_machine_is_confirmed_guarded_and_said_true(tmp_path):
    """« Pousser maintenant » et « Approuver » font sortir quelque chose : une confirmation, marquées comme telles ;
    pousser une amorce seule est refusé. « Déposer » sur le nom d'un dossier est refusé en français, avant d'écrire."""
    atelier = Atelier(token="ghp_x")

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Outils", objectives="Écrire l'outil", start="3:00", end="4:00",
                           remote="https://github.com/moi/outils.git")
        await atelier.write(pid, "src/a.py", "x")  # une amorce, puis du travail non enregistré
        out = {"seed": await perform(kernel, "projects.pousser", form(), by="user_1", subject=str(pid), nonce="u1")}
        await atelier.commit(pid, "première version")
        out["pushed"] = await perform(kernel, "projects.pousser", form(), by="user_1", subject=str(pid), nonce="u2")
        upload = {"_champs": ["file", "folder", "note", "replace"], "folder": [""], "note": [""],
                  "file": [Upload(name="src", data=b"pas un dossier")], "replace": ["on"]}
        out["folder"] = await perform(kernel, "projects.deposer", upload, by="user_1", subject=str(pid), nonce="d1")
        out["specs"] = {n: kernel.registry.actions[f"projects.{n}"] for n in ("pousser", "approuver")}
        return out

    out = live(tmp_path, scenario, atelier=atelier)
    for name in ("pousser", "approuver"):
        assert out["specs"][name].confirm and out["specs"][name].danger
    assert not out["seed"].ok and "amorce" in out["seed"].message  # rien d'enregistré : rien ne part
    assert out["pushed"].ok
    assert not out["folder"].ok and "est un dossier" in out["folder"].message


def test_living_objectives_stay_capped_whatever_the_path_and_launch_is_offered_only_when_it_can_start(tmp_path):
    async def scenario(kernel, llm):
        many = "\n".join(f"Objectif {i}" for i in range(1, 61))
        pid = str(await create(kernel, "p1", title="Plein", objectives=many, start="3:00", end="4:00"))
        out = {"done": await perform(kernel, "projects.objectif_statut", row_form({"objective": "1", "status": "done"}),
                                     by="user_1", subject=pid, nonce="s1")}
        await perform(kernel, "projects.objectif_ajouter", form(text="Un de plus", kind="once"), by="user_1",
                      subject=pid, nonce="a1")
        # retiré → bloqué → ouvert : le plafond tient à chaque passage vers un objectif vivant
        out["blocked"] = await perform(kernel, "projects.objectif_statut",
                                       row_form({"objective": "1", "status": "blocked"}), by="user_1", subject=pid,
                                       nonce="s2")
        out["constant"] = await perform(kernel, "projects.objectif_modifier",
                                        row_form({"objective": "1"}, text="Objectif 1", kind="constant",
                                                 cadence_hours="2"), by="user_1", subject=pid, nonce="m1")
        one = str(await create(kernel, "p2", title="Fini", objectives="Une chose", start="3:00", end="4:00"))
        await perform(kernel, "projects.objectif_statut", row_form({"objective": "1", "status": "done"}),
                      by="user_1", subject=one, nonce="s3")
        out["launch"] = offered(kernel, kernel.registry.actions["projects.lancer"], one)
        return out

    out = live(tmp_path, scenario)
    assert out["done"].ok
    assert not out["blocked"].ok and "60" in out["blocked"].message
    assert not out["constant"].ok and "constant" in out["constant"].message
    assert out["launch"] is False  # rien ne pourrait partir : « Lancer » n'est pas offert
