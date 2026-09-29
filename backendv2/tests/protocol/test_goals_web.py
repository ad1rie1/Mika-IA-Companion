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

