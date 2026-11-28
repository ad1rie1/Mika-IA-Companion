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
from dataclasses import replace
from types import SimpleNamespace

from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.faculties.projects.actions import OTHER_RULE, CreateArgs, ModifyArgs
from mika.faculties.projects.faculty import DEPOSITED, NUDGED, OBJECTIVE_ADDED, REFRAMED, Objective, Project
from mika.faculties.projects.inspect import (
    WHY_WORDS,
    _progress,
    _who,
    forget_note,
    objectives_progress,
    tab_counts,
)
from mika.faculties.projects.work import Why, next_run_at
from mika.inspector.formview import action_view
from mika.inspector.pages.actions import per_row
from mika.kernel.clock import MINUTE, US
from mika.kernel.events import Content, Origin
from mika.kernel.forms import Upload, describe
from mika.kernel.inspect import (
    ActionSlot,
    Code,
    Disclosure,
    Download,
    Fields,
    Grid,
    Head,
    Nav,
    Row,
    Section,
    Stats,
    Table,
    Toolbar,
)
from mika.ports.workshop import Commit, Hosted, Ticket
from mika.runtime import decisions
from mika.runtime.inspection import Inspection
from mika.runtime.operations import initial_values, offered, perform
from mika.sim.llm.persona import _section
from mika.sim.outside import FakeFeeds
from tests.fixtures.atelier import STAMP, Atelier, Host
from tests.unit.test_goals_console import field, flat, nested
from tests.unit.test_projects import create, events, form, live, wait

#: les onglets de la fiche, dans l'ordre de leurs vues (ADR 0281) : la fiche dessinée réunit « objectifs » sous
#: « apercu » et « acces » sous « comportement », et range les trois derniers sous « Plus »
TABS = ["apercu", "objectifs", "tickets", "git", "fichiers", "documentation", "decisions", "executions", "carnet",
        "liens", "suivi", "comportement", "acces"]  # l'ordre de l'écran Projets (ADR 0297)


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
    assert row.cells[4] == "—"  # rien ne t'y attend (ADR 0281)
    assert row.cells[5].text.endswith("/2 ponctuels faits · 1 constant")  # ses deux ponctuels, son constant, accordés
    assert row.cells[10] == "les jours ouvrés, de 9 h à 18 h" and "github.com/moi/outils" in row.cells[13].text
    stats = next(b for b in listing if isinstance(b, Stats))
    counts = {st.label: st.value for st in stats.items}
    assert counts["Actifs"] == 1 and counts["Exécutions (24 h)"] >= 1 and counts["Archivés"] == 0
    # ses ponctuels ouverts et ses constants, accordés à leur nombre — jamais « constant(s) »
    opened = "ponctuel ouvert" if counts["Objectifs"] < 2 else "ponctuels ouverts"
    assert {st.label: st.sub for st in stats.items}["Objectifs"] == f"{opened} · 1 constant"
    assert "aucun projet avec ces filtres" in flat(alive["archived"])
    runs = tables(alive["runs"])["Les exécutions"]
    assert runs.rows and runs.rows[0].cells[1].text == "Outils réseau" and runs.rows[0].cells[3].text == "fait"
    assert "n° " in runs.rows[0].cells[2].text and runs.rows[0].cells[6].kind == "subject"  # le commit, ouvrable
    assert "aucune exécution avec ces filtres" in flat(alive["runs_filtered"])
    head = alive["head"]
    assert isinstance(head, Head) and head.key == str(pid) and head.title == "Outils réseau"
    # la vue d'un objet (la maquette) : son état en étiquette, son mode et à qui il est en faits
    assert [b.text for b in head.badges][:1] == ["actif"] and head.default_tab == "apercu"
    assert dict((k, getattr(v, "text", v)) for k, v in head.facts)["mode"] == "impersonnel"
    assert [f.key for f in alive["by_title"]] == [str(pid)] == [f.key for f in alive["by_number"]]
    assert "Outils réseau" in flat(alive["person"])
    # avant d'oublier quelqu'un, sa fiche dit ce que l'oubli n'atteint pas : l'atelier de ses projets (PRJ-9)
    # (un seul projet : « ce projet », « son atelier », accordés — jamais « ces 1 projet(s) »)
    assert "ce que sa vie garde de ce projet" in flat(alive["person"]) and "pas son atelier" in flat(alive["person"])
    assert "Vider le stockage" in flat(alive["person"])


# ── Créer ─────────────────────────────────────────────────────────────────


def test_creating_says_what_is_wrong_field_by_field_and_leads_to_the_fiche(tmp_path):
    async def scenario(kernel, llm):
        bad = await perform(kernel, "projects.creer", form(
            title=" ", schedule="autre", schedule_rule="tous les jours", start="25:00", end="midi", owner="personne_x",
            mode="persona", days="all", remote="http://github.com/x", branch="../main", cadence_hours="0",
            runs_per_day="0", priority="normal"), by="user_1", nonce="b1")
        ok = await perform(kernel, "projects.creer", form(
            ("approval", "auto_push"), title="Un module", objectives="Écrire le module\n\n", constants="Le tenir à jour",
            cadence_hours="6", mode="persona", schedule="interval:2h", days="all", start="", end="", runs_per_day="5",
            priority="high", branch="main", tool_memory="on", tool_rss="on"), by="user_1", nonce="b2")
        return bad, ok, events(kernel, c.PROJECT_CREATED), events(kernel, OBJECTIVE_ADDED), events(kernel, rt.OPERATED)

    bad, ok, created, objectives, audit = live(tmp_path, scenario)
    assert not bad.ok
    # la règle écrite sous « une autre règle… » : refusée sur son champ
    assert set(bad.errors) == {"title", "objectives", "schedule_rule", "start", "end", "owner", "remote", "branch"}
    assert "une adresse https" in bad.errors["remote"] and "au moins un objectif" in bad.errors["objectives"]
    assert ok.ok and ok.go is not None and ok.go.key == f"project/{created[0].seq}"  # créé : on arrive sur sa fiche
    [p] = created
    assert p.origin is Origin.EXTERNAL and p.data.source == "operator" and p.data.owner == "user_1"
    assert p.data.approval is False and p.data.schedule == "interval:2h" and p.data.runs_per_day == 5
    assert set(p.data.bundles) == {"projects", "workshop", "memory", "rss", "mcp.web"}  # le web, coché d'office
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
        # Code s'ouvre sur ses fichiers (ADR 0297) : l'atelier face au distant est sa sous-vue « distant »
        tabs["git"] = await tab(kernel, "git", str(pid), vue="distant")
        tabs["commit"] = await tab(kernel, "git", str(pid), vue="distant", commit=commits[0].sha)
        tabs["file"] = await tab(kernel, "fichiers", str(pid), fichier="JOURNAL.md")
        ins = Inspection(kernel)
        specs = [a for a in ins.actions_for(subject="project")]
        head = [a.key for a in specs if not a.inline and not per_row(a) and offered(kernel, a, str(pid))]
        return tabs, head, pid, ins.find("projects", "decisions").title

    tabs, head, pid, decisions_title = live(tmp_path, scenario, atelier=atelier)
    # en tête : ce qui vaut pour tout le projet (les formulaires des onglets, et les lignes, n'y sont pas)
    # la principale, puis la consigne ; la pause et le reste sous « ⋯ » (la maquette)
    assert head == ["projects.lancer", "projects.consigne", "projects.pause", "projects.archiver"]
    overview = tabs["apercu"]
    assert "À décider (1)" in flat(overview) and "installer requests" in flat(overview)
    # la fiche ne décide plus ses demandes sur place (ADR 0177) : ni la vue d'ensemble (servie en MCP, au repli) ni le
    # Carnet ne portent Approuver ou Refuser, mais un lien vers la file, ouverte sur la demande
    pending = next(r for r in tables(tabs["carnet"])["Ce qui sort de la machine"].rows if r.tone == "warn")
    for where, blocks in (("apercu", overview), ("carnet", pending.detail)):
        assert not {b.action for b in nested(blocks) if isinstance(b, ActionSlot)} & {
            "projects.approuver", "projects.refuser"}, where
        links = [v for b in nested(blocks) if isinstance(b, Fields) for k, v in b.pairs if k == "ton accord"]
        assert [(v.kind, v.key, dict(v.params)) for v in links] == [("approvals", "en_attente",
                                                                     {"demande": links[0].params[0][1]})], where
        assert links[0].params[0][1].isdigit()
        # ni « » » ni « valider » seul à la ligne : des espaces insécables, fines dans les guillemets
        assert links[0].text == "La décider dans «\u202fÀ\u00a0valider\u202f»"
    # une bande de chiffres, puis des tuiles (ADR 0176) ; l'avancement des objectifs, compté et accordé par la vue
    band = next(b for b in overview if isinstance(b, Stats))
    assert band.title == "Où il en est"
    told = {st.label: st for st in band.items}
    assert (told["Objectifs"].value, told["Objectifs"].sub, told["Objectifs"].tone) == (
        "1/1", "ponctuel fait · 1 constant", "")
    assert told["Dernier commit"].sub == ""  # le distant se dit une fois, dans la tuile « Son dépôt »
    # ce qui t'attend en tête (ADR 0281), puis ses missions et ses objectifs en cours, une ligne chacun
    [waiting] = tables(overview)["Ce qui t'attend (1)"].rows  # la demande qui attend ton accord, et où la décider
    assert waiting.cells[0].text == "ton accord" and "installer requests" in waiting.cells[1].text
    assert (waiting.cells[4].kind, waiting.cells[4].key) == ("approvals", "en_attente")
    missions = tables(overview)["Missions"]
    assert [c.label for c in missions.columns] == ["n°", "mission", "état", "revient", "déclenchée par",
                                                   "dernier passage", "ce qui l'a éveillée"]
    assert len(missions.rows) == 1 and not tables(overview)["Objectifs en cours"].rows  # son ponctuel est fait
    grids = [b for b in overview if isinstance(b, Grid)]
    assert [[f.title for f in g.items] for g in grids] == [["Prochaine exécution", "Le cadre", "Son dépôt"]]
    # chaque fait une fois : le mode et la plage sont dans l'en-tête, le dernier commit dans la bande
    tiles = {f.title: [k for k, _ in f.pairs] for f in grids[0].items if isinstance(f, Fields)}
    assert tiles == {"Prochaine exécution": ["quand", "sur quoi"],
                     "Son dépôt": ["dépôt distant", "dernier échange", "l'histoire complète"]}
    assert "Dernières exécutions" in flat(overview) and "Décisions en vigueur (les dernières)" in flat(overview)
    # par défaut, ce qui vit (le ponctuel fait se filtre) ; tous : ce qui revient d'abord
    assert [r.cells[2].text for r in tables(tabs["objectifs"])["Ses objectifs"].rows] == ["constant"]
    objectifs = tables(tabs["tous les objectifs"])["Ses objectifs"]
    assert [r.cells[2].text for r in objectifs.rows] == ["constant", "ponctuel"]
    assert any(isinstance(b, ActionSlot) and b.action == "projects.objectif_ajouter" for b in nested(tabs["objectifs"]))
    runs = tables(tabs["executions"])["Ses exécutions"]
    assert runs.rows and runs.rows[-1].cells[1] == "elle-même" and runs.rows[-1].cells[4].text == "fait"
    assert (runs.rows[-1].cells[3].text, runs.rows[-1].cells[3].tone) == ("terminé", "ok")  # les mots de la page Épisodes
    assert runs.rows[-1].cells[10].params == (("onglet", "prompt"),)
    decisions = tables(tabs["decisions"])["Ses décisions (1 en vigueur)"]
    assert decisions.rows[0].cells[0] == "D1" and decisions.rows[0].cells[2].text == "Python"
    # « Décisions », sur la fiche d'un but, ce sont les pesées de l'arbitre : celles d'un projet se disent techniques,
    # comme sa vue de section ; la clé de l'onglet reste « decisions » (la fiche dessinée et les liens la lisent)
    assert decisions_title == "Décisions techniques"
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
    assert {r[0].text for r in tools.rows} == {"ses outils de projet", "son atelier", "sa mémoire (souvenirs, croyances)",
                                             "le web (chercher, lire des pages)"}
    assert any("ws_write" in r[2].text for r in tools.rows)
    carnet = tabs["carnet"]
    assert "objectif n° 1 ajouté" in flat(carnet) and "attend ton accord" in flat(carnet)


def test_the_next_run_says_when_then_why_not_sooner(tmp_path):
    """La prochaine exécution datée se dit comme la prochaine séance d'un but : la date, puis la raison entre
    parenthèses — son agenda la fixe plus tard, ou sa plage de travail n'est pas ouverte —, jamais « (pas encore) ».
    La raison est un code de la faculté ; chacune a ses mots à la console."""
    async def scenario(kernel, llm):
        later = await create(kernel, "p1", title="Le bilan", objectives="Écrire le bilan", mode="plain",
                             schedule="cron:0 9 * * *")  # son agenda : demain à 9 h
        outside = await create(kernel, "p2", title="Le module", objectives="Écrire le module", mode="plain",
                               start="3:00", end="4:00")  # hors de sa plage : rien ne part tout seul
        frame = kernel.mind.frame()
        s = frame.state("projects")
        return {pid: (next_run_at(s.projects[pid], s, frame), frame.now,
                      field(await tab(kernel, "apercu", str(pid)), "quand")) for pid in (later, outside)}, later, outside

    out, later, outside = live(tmp_path, scenario)
    at, now, said = out[later]
    assert at > now and said == f"{at} (son agenda ou l'espacement des exécutions la fixe plus tard)"
    at, now, said = out[outside]
    assert at > now and said == f"{at} (hors de sa plage de travail)"
    assert set(WHY_WORDS) == set(Why)  # chaque raison a ses mots


def test_an_agenda_reads_in_words_in_the_list_and_in_the_fiche(tmp_path):
    """L'agenda d'un projet se dit en mots dans la liste comme dans sa fiche, par la fonction de la faculté que le
    panneau du client web lit aussi : une valeur proposée garde son libellé, une règle hors de la liste se traduit —
    jamais « cron:… » brut à la console."""
    async def scenario(kernel, llm):
        proposed = await create(kernel, "p1", title="Le bilan", objectives="Écrire le bilan", mode="plain",
                                schedule="cron:0 9 * * MON-FRI")  # une des valeurs proposées
        own = await create(kernel, "p2", title="Le module", objectives="Écrire le module", mode="plain",
                           schedule="autre", schedule_rule="cron:30 8 * * MON-FRI")  # écrite à la main, hors liste
        listed = {r.href.key: r.cells[11] for r in tables(await tab(kernel, "tous"))["Projets"].rows}
        said = {}
        for pid in (proposed, own):
            said[pid] = (listed[f"project/{pid}"], field(await tab(kernel, "comportement", str(pid)), "agenda"))
        return said, proposed, own

    said, proposed, own = live(tmp_path, scenario)
    assert said[proposed] == ("les jours ouvrés à 9 h",) * 2
    assert said[own] == ("les jours ouvrés à 8 h 30",) * 2


def test_the_agenda_is_chosen_in_words_and_a_rule_of_her_own_survives_a_change(tmp_path):
    """L'Agenda se choisit par ses mots (la valeur envoyée reste la règle), dans les deux formulaires ; « une autre
    règle… » ouvre un champ libre, aidé en mots. Un projet dont l'agenda est hors de la liste se modifie sans le
    perdre : le formulaire le montre sous « une autre règle… », la règle dans le champ libre — un sélecteur hors de
    ses choix se poserait sur « dès que possible », et l'enregistrement remettrait l'agenda à zéro."""
    for args in (CreateArgs, ModifyArgs):
        fields = {f.path: f for f in describe(args)}
        agenda, rule = fields["schedule"], fields["schedule_rule"]
        assert agenda.kind == "select" and dict(agenda.choices)["manual"] == "dès que possible", args
        assert agenda.choices[-1] == (OTHER_RULE, "une autre règle…") and agenda.default == "manual"
        assert rule.kind == "text" and rule.only == (("schedule", (OTHER_RULE,)),) and not rule.required
        assert "manual" not in agenda.help and "manual" not in rule.help and "les jours ouvrés à 8 h 30" in rule.help

    async def scenario(kernel, llm):
        pid = str(await create(kernel, "p1", title="Le bilan", objectives="Écrire le bilan", schedule="autre",
                               schedule_rule="cron:30 8 * * MON-FRI"))
        spec = kernel.registry.actions["projects.modifier"]
        out = {"initial": initial_values(kernel, spec, pid)}
        out["view"] = {f["path"]: f for f in action_view(spec, csrf="x", back="/", subject=pid,
                                                          initial=out["initial"])["fields"]}
        values = {k: str(v) for k, v in out["initial"].items() if k != "approval"}
        out["paced"] = await perform(kernel, "projects.modifier", form(("approval",), **{**values, "priority": "high"}),
                                     by="user_1", subject=pid, nonce="m1")
        out["kept"] = kernel.mind.frame().state("projects").projects[int(pid)]
        out["blank"] = await perform(kernel, "projects.modifier", form(("approval",), **{
            **values, "schedule_rule": " "}), by="user_1", subject=pid, nonce="m2")
        out["listed"] = await perform(kernel, "projects.modifier", form(("approval",), **{
            **values, "schedule": "interval:2h", "schedule_rule": "cron:30 8 * * MON-FRI"}), by="user_1", subject=pid,
            nonce="m3")  # une valeur proposée : le champ libre, masqué, ne compte pas
        out["again"] = initial_values(kernel, spec, pid)
        out["raw"] = await perform(kernel, "projects.creer", form(
            title="Un projet", objectives="Un objectif", schedule="cron:0 7 * * *", mode="persona", days="all",
            cadence_hours="0", runs_per_day="0", priority="normal", branch="main"), by="user_1", nonce="r1")
        return out, pid

    out, pid = live(tmp_path, scenario)
    initial = out["initial"]
    assert (initial["schedule"], initial["schedule_rule"]) == (OTHER_RULE, "cron:30 8 * * MON-FRI")
    view = out["view"]
    assert view["schedule"]["value"] == OTHER_RULE and view["schedule_rule"]["value"] == "cron:30 8 * * MON-FRI"
    assert view["schedule_rule"]["only"] == f"schedule={OTHER_RULE}"
    assert out["paced"].ok, out["paced"]
    assert (out["kept"].schedule, out["kept"].priority) == ("cron:30 8 * * MON-FRI", c.HIGH)  # son agenda, gardé
    assert not out["blank"].ok and set(out["blank"].errors) == {"schedule_rule"}
    assert out["listed"].ok and (out["again"]["schedule"], out["again"]["schedule_rule"]) == ("interval:2h", "")
    # une règle brute dans « Agenda » n'est pas un des choix : le formulaire la refuse, elle passe par le champ libre
    assert not out["raw"].ok and "choix inconnu" in out["raw"].errors["schedule"]


def test_the_progress_of_objectives_is_counted_once_and_agreed():
    """L'avancement de ses objectifs se compte à un seul endroit (``objectives_progress``) : la Stat de la vue
    d'ensemble, que la fiche dessinée lit telle quelle, et la jauge des listes — accordé, jamais « ponctuel(s) »."""
    def project(*objectives: tuple[str, str]) -> Project:
        return Project(1, "t", "operator", 0, objectives=tuple(
            Objective(n, f"o{n}", kind, status) for n, (kind, status) in enumerate(objectives, start=1)))

    once, constant = c.ONCE, c.CONSTANT
    assert objectives_progress(project()) == ("aucun", "", "") and _progress(project()).text == "aucun objectif"
    assert objectives_progress(project((once, c.DONE), (once, c.OPEN), (constant, c.OPEN))) == (
        "1/2", "ponctuels faits · 1 constant", "")
    assert objectives_progress(project((once, c.OPEN), (once, c.DROPPED))) == ("0/1", "ponctuel fait", "")
    # un objectif bloqué : la Stat « Objectifs » de la vue d'ensemble (MCP, repli, la fiche dessinée) passe en alerte
    assert objectives_progress(project((constant, c.OPEN), (constant, c.OPEN), (once, c.BLOCKED))) == (
        "0/1", "ponctuel fait · 2 constants · 1 bloqué", "warn")
    assert objectives_progress(project((constant, c.OPEN), (constant, c.OPEN))) == ("2", "constants", "")
    # ses seuls constants sont bloqués : leur nombre, jamais « 0 constant · 1 bloqué »
    assert objectives_progress(project((constant, c.BLOCKED))) == ("1", "bloqué", "warn")
    assert objectives_progress(project((constant, c.BLOCKED), (constant, c.BLOCKED), (constant, c.DROPPED))) == (
        "2", "bloqués", "warn")
    assert objectives_progress(project((constant, c.OPEN), (constant, c.BLOCKED))) == (
        "1", "constant · 1 bloqué", "warn")
    assert (_progress(project((constant, c.BLOCKED))).text, _progress(project((constant, c.BLOCKED))).tone) == (
        "1 bloqué", "warn")
    gauge = _progress(project((once, c.DONE), (once, c.BLOCKED), (constant, c.OPEN), (constant, c.OPEN)))
    assert (gauge.ratio, gauge.text, gauge.tone) == (0.5, "1/2 ponctuels faits · 2 constants · 1 bloqué", "warn")
    # ce que ses onglets comptent : ses objectifs hors retirés, ses exécutions, ses décisions en vigueur
    # — et son registre (ADR 0268) : ses tickets ouverts, ce qui reste ouvert dans ses listes de suivi
    assert tab_counts(project((once, c.DROPPED), (once, c.OPEN))) == {"objectifs": 1, "executions": 0,
                                                                      "decisions": 0, "tickets": 0, "suivi": 0}
    # l'oubli d'une personne, accordé au nombre de ses projets
    assert "garde de ce projet" in forget_note(1) and "pas son atelier" in forget_note(1)
    assert "garde de ces 3 projets" in forget_note(3) and "pas leurs ateliers" in forget_note(3)


def test_who_asked_for_a_project_is_said_by_a_cleaned_name_and_by_the_key_without_one():
    """« demandé par » et les auteurs des décisions disent le prénom par la règle commune (``identity.person_name``) :
    blancs repliés, guillemets retirés ; sans prénom, la clé (au survol ou dans le lien)."""
    def frame(name):
        return SimpleNamespace(get=lambda key: SimpleNamespace(name=name))

    assert _who(frame(' "Léa"\t\t Dupont '), "user_1") == "Léa Dupont"
    assert _who(frame(""), "user_1") == "user_1"
    assert _who(frame("Léa"), None) == "—"


# ── Modifier, ses outils ──────────────────────────────────────────────────


def test_modifying_starts_from_what_it_is_and_the_next_run_reads_the_new_frame(tmp_path):
    async def scenario(kernel, llm):
        # elle suit des flux : leurs outils s'offrent (ADR 0266)
        kernel.ports["feeds"] = kernel.runner.ports["feeds"] = FakeFeeds()
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
                          for k in ("objectif_statut", "objectif_modifier", "lancer_objectif", "objectif_ajouter",
                                    "lancer")}
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
                              "objectif_ajouter": False, "lancer": False}


# ── Décider, déposer, pousser ─────────────────────────────────────────────


def test_a_project_request_is_decided_once_in_the_queue_and_the_fiche_tells_it(tmp_path):
    """Une demande d'un projet se décide dans la file « À valider », par ``runtime.decisions.decide`` (ADR 0177) :
    une seule fois (la seconde est « inconnue »). La fiche n'a aucune action pour le faire ; sa vue d'ensemble compte
    ce qui attend, puis plus rien, et le Carnet dit le refus."""
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
        mind, ports = kernel.mind, kernel.ports
        out = {"apercu": await tab(kernel, "apercu", pid),
               "yes": await decisions.decide(mind, ports, yes, True, by="user_1"),
               "twice": await decisions.decide(mind, ports, yes, True, by="user_1"),
               "no": await decisions.decide(mind, ports, no, False, by="user_1", note="pas de réseau"),
               "no_again": await decisions.decide(mind, ports, no, True, by="user_1"),
               "actions": set(kernel.registry.actions)}
        await kernel.lanes.join()
        out["resolved"] = [(e.data.proposal, e.data.approved, e.data.by, e.data.said())
                           for e in events(kernel, rt.EFFECT_RESOLVED)]
        out["ids"] = (yes, no)
        out["apercu_after"] = await tab(kernel, "apercu", pid)
        out["carnet"] = await tab(kernel, "carnet", pid)
        return out

    out = live(tmp_path, scenario)
    yes, no = out["ids"]
    # la file est le seul lieu où elle se décide : la fiche n'a plus d'action pour approuver ni refuser
    assert not {"projects.approuver", "projects.refuser"} & out["actions"]
    assert "À décider (2)" in flat(out["apercu"]) and "installer requests" in flat(out["apercu"])
    assert (out["yes"].status, out["no"].status) == (decisions.APPROVED, decisions.REJECTED)
    # une décision ne se prend qu'une fois, dans un sens comme dans l'autre
    assert out["twice"].status == out["no_again"].status == decisions.UNKNOWN
    assert out["resolved"] == [(yes, True, "user_1", ""), (no, False, "user_1", "pas de réseau")]
    assert "À décider" not in flat(out["apercu_after"])  # décidées : la fiche n'en compte plus
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
        await wait(65)  # son premier passage vient une cadence après sa naissance (ADR 0161)
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
        first = tables(await tab(kernel, "git", str(pid), vue="distant"))["Historique"]
        last = tables(await tab(kernel, "git", str(pid), vue="distant", page_commits="23"))["Historique"]
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
        out["git"] = await tab(kernel, "git", pid, vue="distant")
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


def test_the_git_tab_faces_the_workshop_with_its_github_remote(tmp_path):
    """ADR 0183 : l'écart entre l'atelier et le distant (compté par l'atelier, sinon par l'hôte), l'histoire du
    distant, ses issues et pull requests ; un hôte qui ne répond pas se dit, sans chiffres inventés."""
    atelier = Atelier()

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Outils", objectives="Écrire l'outil", start="3:00", end="4:00",
                           remote="https://github.com/moi/outils.git")
        for n in range(3):
            await atelier.write(pid, "a.py", f"x = {n}")
            await atelier.commit(pid, f"pas {n}")
        pushed = atelier.commits_[pid][1][0]  # le distant s'est arrêté à « pas 0 »
        page = "https://github.com/moi/outils"
        hosted = Hosted("moi/outils", page, "main", head=pushed, commits=(Commit(pushed, STAMP, "pas 0", "adrien"),),
                        issues=(Ticket(7, "Un bogue", f"{page}/issues/7", "bea", STAMP, ("bug",), 2),),
                        pulls=(Ticket(8, "Une PR", f"{page}/pull/8", "bea", STAMP, head="f", base="main", draft=True),),
                        open_issues=1, open_pulls=1, read_at=STAMP)
        host = kernel.ports["repo_host"] = Host(hosted)
        out = {"ahead": await tab(kernel, "git", str(pid), vue="distant", frais="1")}
        host.hosted, host.gap = replace(hosted, head="f" * 40, commits=(Commit("f" * 40, STAMP, "d'ailleurs"),)), (2, 1)
        out["diverged"] = await tab(kernel, "git", str(pid), vue="distant")
        host.hosted = replace(hosted, error="GitHub ne répond pas", head="", commits=(), issues=(), pulls=())
        out["down"] = await tab(kernel, "git", str(pid), vue="distant")
        out["asked"] = host.asked
        return out

    out = live(tmp_path, scenario, atelier=atelier)
    assert out["asked"][0] == ("https://github.com/moi/outils.git", "main", True, 0)  # « relire » : une lecture neuve
    ahead = out["ahead"]
    gap = {st.label: st for st in next(b for b in ahead if isinstance(b, Stats)).items}["Avec le distant"]
    assert (gap.value, gap.tone) == ("2 à pousser", "warn")  # l'atelier connaît la tête du distant : il compte
    history = tables(ahead)["Historique"]
    assert [r.cells[7].text for r in history.rows] == ["à pousser", "à pousser", "sur le distant", "sur le distant"]
    remote = tables(ahead)["Sur le distant"]
    assert remote.rows[0].cells[0].key.startswith("https://github.com/moi/outils/commit/")  # vers l'hôte
    assert remote.rows[0].cells[4].text == "dans l'atelier"
    assert tables(ahead)["Issues ouvertes"].rows[0].cells[0].key == "https://github.com/moi/outils/issues/7"
    assert tables(ahead)["Pull requests ouvertes"].rows[0].cells[3].text == "brouillon"
    assert "au bout de la branche" in flat(ahead) and "issues ouvertes" in flat(ahead)
    diverged = out["diverged"]
    gap = {st.label: st for st in next(b for b in diverged if isinstance(b, Stats)).items}["Avec le distant"]
    assert (gap.value, gap.sub, gap.tone) == ("2 à pousser · 1 à récupérer", "les deux histoires ont divergé", "danger")
    assert tables(diverged)["Sur le distant"].rows[0].cells[4].text == "à récupérer"  # l'hôte a compté
    down = out["down"]
    assert "Sur le distant" not in tables(down) and "Issues ouvertes" not in tables(down)
    gap = {st.label: st for st in next(b for b in down if isinstance(b, Stats)).items}["Avec le distant"]
    assert gap.value == "—" and gap.sub == "écart inconnu"  # pas de chiffres inventés
    assert "GitHub ne répond pas." in flat(down)
    assert any(isinstance(b, ActionSlot) and b.action == "projects.pousser" for b in nested(down))  # pousser reste


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
        out["git"] = await tab(kernel, "git", str(pid), vue="distant")
        return out

    out = live(tmp_path, scenario, atelier=atelier)
    assert not out["exists"].ok and "existe déjà" in out["exists"].message  # rien n'est écrasé sans le dire
    assert out["replace"].ok
    assert out["pending"] == ["nouveau.py"]  # le dépôt n'a enregistré que lui-même : le travail en cours reste
    assert [r.cells[0].text for r in tables(out["src"])["/src"].rows] == ["m0.py", "m1.py", "m2.py"]
    stats = next(b for b in out["git"] if isinstance(b, Stats))
    assert dict((st.label, st.value) for st in stats.items)["Non enregistré"] == "1 fichier"


def test_stale_pages_cannot_undo_a_replacement_and_the_queue_cannot_approve_for_an_archived_project(tmp_path):
    async def scenario(kernel, llm):
        pid = str(await create(kernel, "p1", title="Le module", objectives="Écrire le module", approval="on",
                               start="3:00", end="4:00"))
        for i, (choice, replaces) in enumerate((("Python", "0"), ("Rust", "1"))):
            await perform(kernel, "projects.decision_ajouter", form(title="Langage", choice=choice, reason="",
                                                                    context="", options="", replaces=replaces),
                          by="user_1", subject=pid, nonce=f"d{i}")
        stale = await perform(kernel, "projects.decision_statut", row_form({"decision": "1", "status": "withdrawn"}),
                              by="user_1", subject=pid, nonce="s1")
        proposed = await kernel.mind.append([rt.EFFECT_PROPOSED.draft(
            capability="projects.networked", owner="projects", args_json=f'{{"project": {pid}, "argv": ["true"]}}',
            summary=Content.of("installer", level=0), approval=True, context=f"project:{pid}")],
            emitter="runtime", correlation="t", origin=Origin.TOOL)
        await perform(kernel, "projects.archiver", form(), by="user_1", subject=pid, nonce="a1")
        proposal = proposed.seqs[-1]
        approve = await decisions.decide(kernel.mind, kernel.ports, proposal, True, by="user_1")
        refuse = await decisions.decide(kernel.mind, kernel.ports, proposal, False, by="user_1")
        return stale, approve, refuse

    stale, approve, refuse = live(tmp_path, scenario)
    assert not stale.ok and "remplacée" in stale.message
    # un projet archivé ne fait plus rien sortir : la file ne l'approuve pas (son aperçu le dit) ; refuser, si
    assert approve.status == decisions.BLOCKED and approve.draft is None and "archivé" in approve.message
    assert refuse.status == decisions.REJECTED


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
    """« Pousser maintenant » fait sortir quelque chose : une confirmation, marquée comme telle (« Approuver » une
    demande vit dans la file, qui se confirme aussi : tests/protocol/test_console_operator.py) ; pousser une amorce
    seule est refusé. « Déposer » sur le nom d'un dossier est refusé en français, avant d'écrire."""
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
        out["push"] = kernel.registry.actions["projects.pousser"]
        return out

    out = live(tmp_path, scenario, atelier=atelier)
    assert out["push"].confirm and out["push"].danger
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
