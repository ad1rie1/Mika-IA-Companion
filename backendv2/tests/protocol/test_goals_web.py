"""L'approbation de bout en bout, telle que le frontend la fait
(``InnerLifePanel.resolvePending`` : ``POST /api/projects/pending/<id>/<décision>``
avec le jeton CSRF, puis le serveur pousse un ``inner_state_update``).

- une propriétaire voit ses projets et les actions en attente dans son
  panneau (``projects``, ``pending_project_actions``, aux formes du frontend) ;
  quelqu'un d'autre ne les voit pas ;
- seul un opérateur décide ; une décision ne se prend qu'une fois ;
- approuvée, l'action part (isolée, dans l'atelier) et son résultat est
  journalisé ; la file se vide chez tout le monde.
"""

from __future__ import annotations

import json
import shutil
import time

import pytest

from mika.contracts import goals as goals_c
from mika.contracts import runtime as rt
from mika.kernel.events import Content, Origin
from mika.runtime.effects import with_content
from tests.protocol.test_web import WS, bootstrap, csrf, recv_until, world  # noqa: F401 — fixture

needs_bwrap = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap absent")


def _propose(client, live) -> tuple[int, int]:
    async def go() -> tuple[int, int]:
        mind = live.kernel.mind
        opened = await mind.append([goals_c.GOAL_OPENED.draft(
            kind=goals_c.PROJECT, authority=goals_c.USER, title=Content.of("Un script de bonjour", level=2),
            details=Content.of("Écrire bonjour.py et le tester.", level=2), owner="user_1", address="user_1",
            about=("user_1",), bundles=("goals", "memory", "workshop"), max_steps=3, schedule="cron:0 9 * * MON",
            source="operator", sensitivity=2)], emitter="goals", correlation="test", origin=Origin.GENESIS)
        gid = opened.seqs[-1]
        proposed = await mind.append([rt.EFFECT_PROPOSED.draft(
            capability="goals.networked", owner="goals",
            args_json=json.dumps({"goal": gid, "argv": ["python3", "-c", "print('réseau ok')"]}),
            summary=Content.of("Installer une dépendance — commande : python3 -c …", level=0), approval=True,
            context=f"goal:{gid}")], emitter="runtime", correlation="test", origin=Origin.TOOL)
        return gid, proposed.seqs[-1]

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
    gid, action = _propose(client, live)
    with client.websocket_connect(WS) as ws:
        ws.receive_json(), ws.receive_json()
        ws.send_json({"type": "chat", "message": "où en est mon projet ?", "client_msg_id": "p1"})
        recv_until(ws, "speech")
        state = ws.receive_json()["inner_state"]
        assert [p["id"] for p in state["projects"]] == [gid]
        project = state["projects"][0]
        assert project["title"] == "Un script de bonjour" and project["schedule_rule"] == "cron:0 9 * * MON"
        assert project["next_run_at"] and project["origin"] == "user"
        assert set(project) == {"id", "title", "status", "priority", "origin", "emotion_policy", "schedule_rule",
                                "next_run_at", "tasks_total", "tasks_done", "tasks_blocked"}
        [pending] = state["pending_project_actions"]
        assert pending["id"] == action and pending["project_id"] == gid
        assert pending["project_title"] == "Un script de bonjour" and pending["payload_kind"] == "goals.networked"
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
    resolved = _events(client, live, rt.EFFECT_RESOLVED.name)
    assert [(e.data.proposal, e.data.approved, e.data.by) for e in resolved] == [(action, True, "user_1")]


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
    reject = client.post(f"/api/projects/pending/{action}/nope", json={}, headers=csrf(client))
    assert reject.status_code == 403  # toujours pas opératrice
    assert not _events(client, live, rt.EFFECT_RESOLVED.name)



def test_a_project_is_confided_on_its_own_page_and_read_on_its_fiche(world):  # noqa: F811
    """« Confier un projet » : une page à elle (pas un panneau), chaque champ expliqué, un calendrier pour
    l'échéance, des agendas proposés, la personne choisie parmi celles qu'elle connaît ; enregistré, on
    arrive sur la fiche du projet, dont chaque onglet s'ouvre — cadre, décisions, prompts compris."""
    import html
    import re

    client, live, _ = world
    bootstrap(client)
    with client.websocket_connect(WS) as ws:  # qu'elle la connaisse : sa poignée, sa personne
        ws.receive_json(), ws.receive_json()
    listing = html.unescape(client.get("/inspecteur/buts").text)
    assert "Projets en cours" in listing  # l'onglet Projets vient en premier
    link = re.search(r'<a class="[^"]*\bbtn\b[^"]*" href="(/inspecteur/action/goals\.confier\?[^"]+)">Confier un projet',
                     listing)
    assert link, "l'action à plusieurs champs mène à sa page"
    page = html.unescape(client.get(link.group(1).replace("&amp;", "&")).text)
    assert "<legend>Le projet</legend>" in page and "<legend>Son rythme</legend>" in page
    assert 'type="datetime-local" name="due"' in page and '<datalist id=' in page
    assert re.search(r'<select name="owner"[^>]*>.*?<option value="user_1"', page, re.S)
    assert "rien ne part sans que tu l'approuves" in page
    done = client.post("/inspecteur/action/goals.confier", data={
        "csrf": client.cookies.get("csrftoken"), "_op": "confier-1", "_retour": "/inspecteur/buts/projets", "_sujet": "",
        "title": "Un script de bonjour", "details": "Écrire bonjour.py.", "owner": "user_1",
        "due": "2027-03-02T18:00", "schedule": "interval:2h", "max_steps": "4", "approval": "on",
        "_champs": ["title", "details", "owner", "due", "schedule", "max_steps", "approval"]})
    assert done.status_code == 200, re.findall(r'class="(?:error|flash danger)"[^>]*>([^<]+)', html.unescape(done.text))
    gid = _events(client, live, goals_c.GOAL_OPENED.name)[-1].seq
    for tab in ("resume", "politique", "pas", "carnet", "effets", "decisions", "episodes", "atelier"):
        r = client.get(f"/inspecteur/fiche/goal/{gid}?onglet={tab}")
        assert r.status_code == 200 and "a échoué" not in r.text, tab
    policy = html.unescape(client.get(f"/inspecteur/fiche/goal/{gid}?onglet=politique").text)
    assert "toutes les 2 h (interval:2h)" in policy and "0 faits sur 4 au plus" in policy
    projects = html.unescape(client.get("/inspecteur/buts/projets").text)
    assert "Un script de bonjour" in projects and "sort avec ton accord" in projects
