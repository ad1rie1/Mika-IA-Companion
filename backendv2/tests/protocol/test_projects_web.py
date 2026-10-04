"""Les projets de bout en bout, par HTTP (ADR 0031).

- le panneau du frontend (``InnerLifePanel``) voit ses projets et les actions en
  attente, aux formes du frontend ; approuver par ``POST /api/projects/pending/
  <id>/<décision>`` fait partir l'action, isolée, dans l'atelier ; seul un
  opérateur décide, une seule fois ;
- le menu **Projets** : « Créer un projet » a sa page (chaque groupe, chaque
  champ expliqué, des objectifs par ligne) et mène à la fiche ;
- la fiche se pilote : chaque onglet s'ouvre, les formulaires des onglets n'encombrent
  pas l'en-tête, un objectif s'ajoute et se coche, une décision se consigne, un
  fichier se dépose (multipart) puis se lit et se télécharge, le mode et les outils
  se changent, un projet s'archive et se restaure.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import time

import pytest

from mika.contracts import projects as projects_c
from mika.contracts import runtime as rt
from mika.faculties.projects.faculty import OBJECTIVE_ADDED
from mika.kernel.events import Content, Origin
from mika.runtime.effects import with_content
from tests.protocol.test_web import WS, bootstrap, csrf, recv_until, world  # noqa: F401 — fixture

needs_bwrap = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap absent")
TABS = ("apercu", "objectifs", "executions", "decisions", "fichiers", "git", "comportement", "carnet")


def _propose(client, live) -> tuple[int, int]:
    async def go() -> tuple[int, int]:
        mind = live.kernel.mind
        created = await mind.append([projects_c.PROJECT_CREATED.draft(
            title=Content.of("Un script de bonjour", level=2), description=Content.of("Écrire bonjour.py.", level=2),
            authority=projects_c.USER, owner="user_1", address="user_1", about=("user_1",),
            schedule="cron:0 9 * * MON", source="operator", sensitivity=2)], emitter="projects", correlation="test",
            origin=Origin.GENESIS)
        pid = created.seqs[-1]
        await mind.append([OBJECTIVE_ADDED.draft(project=pid, objective=1, text=Content.of("Écrire bonjour.py", level=2),
                                                 owner="user_1", about=("user_1",))],
                          emitter="projects", correlation="test", origin=Origin.GENESIS)
        proposed = await mind.append([rt.EFFECT_PROPOSED.draft(
            capability="projects.networked", owner="projects",
            args_json=json.dumps({"project": pid, "argv": ["python3", "-c", "print('réseau ok')"]}),
            summary=Content.of("Installer une dépendance — commande : python3 -c …", level=0), approval=True,
            context=f"project:{pid}")], emitter="runtime", correlation="test", origin=Origin.TOOL)
        return pid, proposed.seqs[-1]

    return client.portal.call(go)


def _events(client, live, name):
    async def go():
        mind = live.kernel.mind
        return [with_content(mind, mind.decode(e)) for e in mind.store.read() if e.type == name]

    return client.portal.call(go)


@needs_bwrap
def test_an_operator_approves_from_the_panel_and_the_action_runs_isolated(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    pid, action = _propose(client, live)
    with client.websocket_connect(WS) as ws:
        ws.receive_json(), ws.receive_json()
        ws.send_json({"type": "chat", "message": "où en est mon projet ?", "client_msg_id": "p1"})
        recv_until(ws, "speech")
        state = ws.receive_json()["inner_state"]
        assert [p["id"] for p in state["projects"]] == [pid]
        project = state["projects"][0]
        assert project["title"] == "Un script de bonjour" and project["schedule_rule"] == "cron:0 9 * * MON"
        assert project["next_run_at"] and project["origin"] == "user" and project["emotion_policy"] == "full"
        # ce que le panneau montre, en mots (ADR 0056) : pas « full », pas « cron:0 9 * * MON »
        assert project["mode_label"] == "" and project["schedule_label"] == "le lundi à 9 h"
        assert (project["tasks_total"], project["tasks_done"]) == (1, 0)  # ses objectifs ponctuels
        assert set(project) == {"id", "title", "status", "priority", "origin", "emotion_policy", "schedule_rule",
                                "next_run_at", "tasks_total", "tasks_done", "tasks_blocked", "mode_label",
                                "schedule_label"}
        [pending] = state["pending_project_actions"]
        assert pending["id"] == action and pending["project_id"] == pid
        assert pending["project_title"] == "Un script de bonjour" and pending["payload_kind"] == "projects.networked"
        assert pending["owner_label"] == "Un script de bonjour"
        assert pending["kind_label"] == "Lancer une commande avec le réseau dans l'atelier d'un projet."
        assert "Installer une dépendance" in pending["proposal"]

        assert client.post(f"/api/projects/pending/{action}/approve", json={}).status_code == 403  # sans CSRF
        r = client.post(f"/api/projects/pending/{action}/approve", json={"note": ""}, headers=csrf(client))
        assert r.status_code == 200 and r.json() == {"ok": True, "status": "approved"}
        pushed = recv_until(ws, "inner_state_update")[-1]["inner_state"]
        assert pushed["pending_project_actions"] == []  # la file se vide aussitôt

    again = client.post(f"/api/projects/pending/{action}/reject", json={"note": "non"}, headers=csrf(client))
    assert again.status_code == 404  # une décision ne se prend qu'une fois
    for _ in range(100):
        done = _events(client, live, rt.EFFECT_EXECUTED.name)
        if done:
            break
        time.sleep(0.05)
    assert len(done) == 1 and done[0].data.ok and "réseau ok" in done[0].data.result
    assert (live.data / "ateliers" / f"projet-{pid}").is_dir()  # dans l'atelier du projet


def test_only_an_operator_decides_and_only_an_owner_sees_the_queue(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    _, action = _propose(client, live)

    async def bea() -> str:
        account = await live.accounts.create("bea", "un-mot-de-passe-long", operator=False)
        return await live.accounts.open_session(account)

    key = client.portal.call(bea)
    client.cookies.set("sessionid", key)
    r = client.post(f"/api/projects/pending/{action}/approve", json={}, headers=csrf(client))
    assert r.status_code == 403
    with client.websocket_connect(WS) as ws:
        ws.receive_json(), ws.receive_json()
        ws.send_json({"type": "chat", "message": "salut", "client_msg_id": "b1"})
        recv_until(ws, "speech")
        state = ws.receive_json()["inner_state"]
        assert "pending_project_actions" not in state and "projects" not in state
    assert not _events(client, live, rt.EFFECT_RESOLVED.name)


def _create(client, token: str, op: str, **values: str):
    fields = ["title", "description", "owner", "objectives", "constants", "cadence_hours", "mode", "tool_memory",
              "tool_email", "tool_rss", "tool_forge", "tool_forge_apps", "tool_camera", "schedule", "days", "start",
              "end", "runs_per_day", "priority", "approval", "remote", "branch", "auto_push"]
    data = {"csrf": token, "_op": op, "_retour": "/inspecteur/projets", "_sujet": "", "schedule": "manual",
            "cadence_hours": "0", "runs_per_day": "0", "priority": "normal", "mode": "persona", "days": "all",
            "branch": "main", "_champs": fields, **values}
    return client.post("/inspecteur/action/projects.creer", data=data, follow_redirects=False)


def test_a_project_is_created_on_its_own_page_and_lands_on_its_fiche(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    with client.websocket_connect(WS) as ws:  # qu'elle la connaisse : son adresse, sa personne
        ws.receive_json(), ws.receive_json()
    menu = html.unescape(client.get("/inspecteur/").text)
    assert ">Projets<" in menu and "/inspecteur/projets" in menu  # un menu à lui, à côté des buts
    listing = html.unescape(client.get("/inspecteur/projets").text)
    assert "aucun projet" in listing and "Exécutions" in listing and "Décisions techniques" in listing
    link = re.search(r'href="(/inspecteur/action/projects\.creer\?[^"]+)">Créer un projet', listing)
    assert link, "l'action à plusieurs champs mène à sa page"
    page = html.unescape(client.get(link.group(1).replace("&amp;", "&")).text)
    for legend in ("Le projet", "Ses objectifs", "Son mode et ses outils", "Son rythme", "Sa liberté",
                   "Son dépôt distant"):
        assert f"<legend>{legend}</legend>" in page, legend
    assert "Un par ligne" in page and "Améliorer la sécurité" in page and "Mika : elle y travaille" in page
    token = client.cookies.get("csrftoken")
    refused = _create(client, token, "c0", title="Un module", remote="git@github.com:moi/x.git", start="25:00")
    assert refused.status_code == 400
    errors = html.unescape(refused.text)
    assert "au moins un objectif" in errors and "une adresse https" in errors and "heure hors bornes" in errors
    done = _create(client, token, "c1", title="Outils réseau", description="Un petit outillage d'admin.",
                   objectives="Créer un module RDP\nÉcrire sa documentation", constants="Améliorer la sécurité",
                   mode="plain", tool_memory="on", days="weekdays", start="9:00", end="18h", approval="on",
                   remote="https://github.com/moi/outils.git", auto_push="on")
    assert done.status_code == 303 and done.headers["location"].startswith("/inspecteur/fiche/project/")
    pid = done.headers["location"].split("/fiche/project/", 1)[1].split("?", 1)[0]
    created = _events(client, live, projects_c.PROJECT_CREATED.name)[-1]
    assert str(created.seq) == pid and created.data.mode == projects_c.PLAIN and created.data.days == "weekdays"
    assert (created.data.start_min, created.data.end_min) == (540, 1080) and created.data.auto_push
    objectives = _events(client, live, OBJECTIVE_ADDED.name)
    assert [(e.data.project, e.data.objective, e.data.kind, e.data.text.text) for e in objectives] == [
        (int(pid), 1, "once", "Créer un module RDP"), (int(pid), 2, "once", "Écrire sa documentation"),
        (int(pid), 3, "constant", "Améliorer la sécurité")]
    for tab in TABS:
        r = client.get(f"/inspecteur/fiche/project/{pid}?onglet={tab}")
        assert r.status_code == 200 and "a échoué" not in r.text and "Action non déclarée" not in r.text, tab
    fiche = html.unescape(client.get(f"/inspecteur/fiche/project/{pid}").text)
    assert "Outils réseau" in fiche and "impersonnel" in fiche and "Créer un module RDP" in fiche
    assert "les jours ouvrés, de 9 h à 18 h" in fiche and "github.com/moi/outils" in fiche


@pytest.mark.slow
def test_the_project_fiche_is_driven_over_http(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        ws.receive_json(), ws.receive_json()
    token = client.cookies.get("csrftoken")
    done = _create(client, token, "c1", title="Un script de bonjour", objectives="Écrire bonjour.py",
                   approval="on", tool_memory="on")
    pid = done.headers["location"].split("/fiche/project/", 1)[1].split("?", 1)[0]

    def act(key: str, op: str, fixed: dict[str, str] | None = None, **values: str):
        data = {"csrf": token, "_op": op, "_retour": f"/inspecteur/fiche/project/{pid}", "_sujet": pid,
                "_champs": list(values), **values}
        if fixed:
            data |= {"_fixes": list(fixed), **fixed}
        return client.post(f"/inspecteur/action/{key}", data=data, follow_redirects=False)

    fiche = html.unescape(client.get(f"/inspecteur/fiche/project/{pid}").text)
    # en tête : ce qui vaut pour tout le projet ; les formulaires des onglets restent dans leurs onglets
    assert "Lancer maintenant" in fiche and "Mettre en pause" in fiche and "Archiver" in fiche
    for inline in ("Ajouter un objectif", "Consigner une décision", "Modifier le projet", "Enregistrer ses outils",
                   "Pousser maintenant", "Changer le statut", "Approuver"):
        assert inline not in fiche, inline
    assert "Ajouter un objectif" in html.unescape(client.get(f"/inspecteur/fiche/project/{pid}?onglet=objectifs").text)
    assert act("projects.objectif_ajouter", "o1", text="Améliorer la sécurité", kind="constant",
               cadence_hours="12").status_code == 303
    objectifs = html.unescape(client.get(f"/inspecteur/fiche/project/{pid}?onglet=objectifs").text)
    assert "Améliorer la sécurité" in objectifs and "toutes les 12 h" in objectifs and "constant" in objectifs
    assert act("projects.objectif_statut", "s1", {"objective": "1", "status": "done"}).status_code == 303
    refused = act("projects.objectif_statut", "s2", {"objective": "2", "status": "done"})
    shown = html.unescape(client.get(refused.headers["location"]).text)
    assert "Un objectif constant ne se coche pas" in shown  # il revient : on le retire, on ne le coche pas
    assert act("projects.decision_ajouter", "d1", title="Langage", choice="Python", reason="l'atelier le lance",
               context="", options="", replaces="0").status_code == 303
    decisions = html.unescape(client.get(f"/inspecteur/fiche/project/{pid}?onglet=decisions").text)
    assert "Langage" in decisions and "Python" in decisions and "en vigueur" in decisions
    assert act("projects.decision_ajouter", "d2", title="Langage", choice="Rust", reason="plus sûr", context="",
               options="", replaces="1").status_code == 303
    decisions = html.unescape(client.get(f"/inspecteur/fiche/project/{pid}?onglet=decisions&statut=toutes").text)
    assert "remplacée par D2" in decisions and "Rust" in decisions
    deposit = client.post("/inspecteur/action/projects.deposer", data={
        "csrf": token, "_op": "f1", "_retour": f"/inspecteur/fiche/project/{pid}?onglet=fichiers", "_sujet": pid,
        "folder": "donnees", "note": "Les mesures.", "_champs": ["file", "folder", "note"]},
        files={"file": ("mesures.csv", b"a,b\n1,2\n", "text/csv")}, follow_redirects=False)
    assert deposit.status_code == 303, deposit.text[:500]
    assert (live.data / "ateliers" / f"projet-{pid}" / "donnees" / "mesures.csv").read_bytes() == b"a,b\n1,2\n"
    files = html.unescape(client.get(f"/inspecteur/fiche/project/{pid}?onglet=fichiers").text)
    assert "donnees/" in files and 'enctype="multipart/form-data"' in files
    inside = html.unescape(client.get(f"/inspecteur/fiche/project/{pid}?onglet=fichiers&dossier=donnees"
                                      f"&fichier=donnees/mesures.csv").text)
    assert "1,2" in inside and "mesures.csv" in inside
    got = client.get(f"/inspecteur/telecharger/project/{pid}?fichier=donnees/mesures.csv")
    assert got.status_code == 200 and got.content == b"a,b\n1,2\n"
    assert client.get(f"/inspecteur/telecharger/project/{pid}?fichier=../../mind.db").status_code == 404
    git = html.unescape(client.get(f"/inspecteur/fiche/project/{pid}?onglet=git").text)
    assert "apport de l'opérateur : donnees/mesures.csv" in git and "atelier ouvert" in git
    sha = re.search(r"commit=([0-9a-f]{7,40})", git).group(1)
    shown = client.get(f"/inspecteur/fiche/project/{pid}?onglet=git&commit={sha}").text
    assert 'class="code diff"' in shown and "d-line d-add" in shown and "+1,2" in html.unescape(shown)
    block = shown.split('class="code diff"', 1)[1].split("</pre>", 1)[0]
    assert "</span>\n<span" not in block  # une ligne de diff par ligne, sans ligne vide entre deux
    assert act("projects.outils", "t1", tool_memory="on", tool_rss="on").status_code == 303
    behaviour = html.unescape(client.get(f"/inspecteur/fiche/project/{pid}?onglet=comportement").text)
    assert "ses flux RSS" in behaviour and "rss_" in behaviour  # le lot, et ses outils nommés
    assert act("projects.archiver", "a1").status_code == 303
    archived = html.unescape(client.get(f"/inspecteur/fiche/project/{pid}").text)
    assert "Restaurer" in archived and "Lancer maintenant" not in archived
    assert act("projects.restaurer", "r1").status_code == 303
    for tab in TABS:
        r = client.get(f"/inspecteur/fiche/project/{pid}?onglet={tab}")
        assert r.status_code == 200 and "a échoué" not in r.text, tab
    carnet = html.unescape(client.get(f"/inspecteur/fiche/project/{pid}?onglet=carnet").text)
    assert "archivé" in carnet and "restauré" in carnet and "objectif n° 1 : fait" in carnet
