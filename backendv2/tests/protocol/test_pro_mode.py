"""Le mode pro dans le chat (ADR 0116).

Une opératrice envoie un message en mode pro (``chat.mode``) : pendant qu'elle travaille, ses outils arrivent en
direct (trames ``tool`` : un outil parti, le même fini, ce qu'elle écrit entre deux, la fin), puis sa réponse
(``speech.mode``, sans voix) ; l'historique garde le mode des deux messages et les noms de ses outils. Une connexion
qui n'est pas d'opératrice ne peut pas le demander : son message est ordinaire, et rien ne se montre en direct.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from starlette.testclient import TestClient

from mika.adapters.llm.config import LiveGateway
from mika.adapters.llm.gateway import Gateway
from mika.adapters.system import RealClock
from mika.adapters.vectors import HashEmbedder
from mika.adapters.web.app import WebConfig
from mika.app.server import build
from mika.kernel.registry import ArbitrationPolicy
from mika.ports.llm import LLMResponse, ToolCall
from mika.vocab.episodes import VOICE_ROLES
from tests.protocol.test_console_operator import html_of
from tests.protocol.test_web import ORIGIN, WS, bootstrap, recv_until
from tests.protocol.test_web_thread import opening

ANSWER = "**Trouvé.**\n\n```sh\ngrep -n devis  boite.txt\n```"


class Worker:
    """Un faux modèle : en mode pro, un outil d'abord, puis sa réponse en Markdown ; sinon, une réplique."""

    name = "fake"

    def __init__(self) -> None:
        self.calls = []

    async def complete(self, req):
        self.calls.append(req)
        if req.role == "pro" and not any(m.role == "tool" for m in req.messages):
            return LLMResponse("Je cherche.", tool_calls=(ToolCall("t1", "memory_search", {"query": "devis"}),))
        if req.role == "pro":
            return LLMResponse(ANSWER)
        return LLMResponse("Coucou ! [EMOTION:happy:0.4]")


@pytest.fixture
def world(tmp_path) -> Iterator[tuple[TestClient, object, Worker]]:
    backend = Worker()
    roles = {str(r): "fake" for r in VOICE_ROLES}
    gateway = LiveGateway(Gateway({"fake": backend}, roles, clock=RealClock(),
                                  voice_roles=frozenset(roles), slots={"fake": 1}))
    app, live = build(tmp_path / "data", web=WebConfig(), gateway=gateway, embedder=HashEmbedder(),
                      arbitration=ArbitrationPolicy(), reply_wait=None)
    with TestClient(app, base_url="http://localhost:8001", headers={"Origin": ORIGIN}) as client:
        yield client, live, backend


def _until_done(ws, limit: int = 40) -> list[dict]:
    """Les trames jusqu'à sa réponse et la fin de son travail : la parole part de la file de sortie dès son commit, la
    fin juste après le règlement — l'une ou l'autre arrive d'abord."""
    frames: list[dict] = []
    for _ in range(limit):
        frames.append(ws.receive_json())
        if any(f["type"] == "speech" for f in frames) and any(
                f["type"] == "tool" and f["phase"] == "done" for f in frames):
            return frames
    raise AssertionError(f"pas de réponse ni de fin : {[f.get('type') for f in frames]}")


def test_her_operator_asks_in_pro_mode_and_watches_her_tools_live(world):
    client, _live, backend = world
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        opening(ws)
        ws.send_json({"type": "chat", "message": "trouve le devis", "client_msg_id": "p1", "mode": "pro"})
        frames = _until_done(ws)
        speech = next(f for f in frames if f["type"] == "speech")
        tools = [f for f in frames if f["type"] == "tool"]
        assert [(f["phase"], f.get("name")) for f in tools] == [("note", None), ("start", "memory_search"),
                                                                 ("end", "memory_search"), ("done", None)]
        note, start, end, done = tools
        assert note["text"] == "Je cherche." and '"devis"' in start["args"] and end["ok"] is True
        assert done["outcome"] == "done" and isinstance(end["duration_ms"], int)
        assert {f["reply_to"] for f in tools} == {speech["user_message_id"]} and len({f["episode"] for f in tools}) == 1
        # sa réponse : du Markdown tel qu'écrit, en mode pro, jamais dite à voix haute
        assert speech["mode"] == "pro" and speech["text"] == ANSWER
        assert speech["speak"] is False and speech["voice_reason"] == "pro"
        ws.send_json({"type": "sync", "after_id": 0})
        rows = {m["id"]: m for m in recv_until(ws, "history", limit=40)[-1]["messages"]}
        mine, hers = rows[speech["user_message_id"]], rows[speech["message_id"]]
        assert mine["mode"] == "pro" and "tools" not in mine
        assert hers["mode"] == "pro" and hers["tools"] == [{"name": "memory_search", "ok": True}]
    assert [c.role for c in backend.calls if c.role in ("pro", "reply")] == ["pro", "pro"]
    assert "un travail demandé" in html_of(client.get(f"/inspecteur/parole/{speech['message_id']}"))


def test_only_an_operator_can_ask_in_pro_mode(world):
    client, live, backend = world
    bootstrap(client)

    async def bea_session() -> str:
        bea = await live.accounts.create("bea", "un-mot-de-passe-long", operator=False)
        return await live.accounts.open_session(bea)

    key_b = client.portal.call(bea_session)
    with client.websocket_connect(WS, headers={"cookie": f"sessionid={key_b}"}) as ws:
        opening(ws)
        ws.send_json({"type": "chat", "message": "trouve le devis", "client_msg_id": "b1", "mode": "pro"})
        frames = recv_until(ws, "speech", limit=40)
        speech = frames[-1]
        assert not [f for f in frames if f["type"] == "tool"]
        assert speech["mode"] == "" and speech["text"] == "Coucou !"
        ws.send_json({"type": "sync", "after_id": 0})
        rows = recv_until(ws, "history", limit=40)[-1]["messages"]
        assert rows and not any("mode" in m for m in rows)
    assert not [c for c in backend.calls if c.role == "pro"]
