"""L'effort de réflexion réglé depuis le chat (ADR 0287).

Une opératrice force l'effort des réponses qu'elle reçoit (trame ``effort``) : pour toute sa conversation, ou pour un
fil de travail. Le serveur dit le sort (``effort_result``) puis le réglage entier (``efforts``), à l'ouverture aussi,
avec ce que « auto » vaut en ce moment (l'effort réglé pour le rôle). L'appel qui lui répond part à cet effort ; en
auto, à celui du rôle. Le contre-exemple : qui n'est pas opératrice ne règle rien et ne reçoit pas le réglage.
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
from mika.ports.llm import LLMResponse
from mika.vocab.episodes import VOICE_ROLES
from tests.protocol.test_pro_strands import PRO_WINDOW
from tests.protocol.test_web import ORIGIN, WS, bootstrap, recv_until
from tests.protocol.test_web_thread import opening


class Worker:
    name = "fake"

    def __init__(self) -> None:
        self.calls = []

    async def complete(self, req):
        self.calls.append(req)
        return LLMResponse("Voilà le travail." if req.role == "pro" else "Coucou ! [EMOTION:happy:0.4]")

    def efforts(self, role: str) -> list[str]:
        return [c.effort for c in self.calls if c.role == role]


@pytest.fixture
def world(tmp_path) -> Iterator[tuple[TestClient, object, Worker]]:
    backend = Worker()
    roles = {str(r): "fake" for r in VOICE_ROLES}
    # le rôle qui répond a son effort réglé (« Qui sert quoi », ADR 0285) : ce que « auto » vaut
    gateway = LiveGateway(Gateway({"fake": backend}, roles, clock=RealClock(), voice_roles=frozenset(roles),
                                  slots={"fake": 1}, limits={"fake": PRO_WINDOW}, efforts={"reply": "medium"}))
    app, live = build(tmp_path / "data", web=WebConfig(), gateway=gateway, embedder=HashEmbedder(),
                      arbitration=ArbitrationPolicy(), reply_wait=None)
    with TestClient(app, base_url="http://localhost:8001", headers={"Origin": ORIGIN}) as client:
        yield client, live, backend


def _set(ws, effort: str, strand: str | None = None) -> tuple[dict, dict]:
    """Le réglage envoyé, puis son sort et le réglage entier qui suit."""
    ws.send_json({"type": "effort", "effort": effort} | ({"strand": strand} if strand is not None else {}))
    result = recv_until(ws, "effort_result")[-1]
    return result, recv_until(ws, "efforts")[-1]


def test_her_operator_forces_the_effort_of_the_conversation_and_of_a_work_thread(world):
    client, _live, backend = world
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        opening(ws)
        # à l'ouverture : rien de forcé ; auto vaut l'effort réglé pour le rôle qui répond ; celui du mode pro n'a
        # pas le sien : le défaut du modèle
        assert recv_until(ws, "efforts", limit=12)[-1] == {
            "type": "efforts", "conversation": "", "strands": {}, "auto": {"chat": "medium", "pro": ""}}
        ws.send_json({"type": "chat", "message": "salut", "client_msg_id": "e0"})
        recv_until(ws, "speech", limit=40)

        result, efforts = _set(ws, "high")
        assert result == {"type": "effort_result", "strand": "", "effort": "high", "status": "ok"}
        assert (efforts["conversation"], efforts["strands"]) == ("high", {})
        ws.send_json({"type": "chat", "message": "explique-moi les marées", "client_msg_id": "e1"})
        recv_until(ws, "speech", limit=40)

        result, efforts = _set(ws, "max", strand="devis-1")
        assert result["status"] == "ok" and result["strand"] == "devis-1"
        assert (efforts["conversation"], efforts["strands"]) == ("high", {"devis-1": "max"})
        ws.send_json({"type": "chat", "message": "compare ces devis", "client_msg_id": "e2", "mode": "pro",
                      "strand": "devis-1"})
        recv_until(ws, "speech", limit=40)
        ws.send_json({"type": "chat", "message": "et ce script ?", "client_msg_id": "e3", "mode": "pro",
                      "strand": "nas-2"})
        recv_until(ws, "speech", limit=40)

        # auto : le fil suit la conversation, la conversation le rôle
        _result, efforts = _set(ws, "", strand="devis-1")
        assert efforts["strands"] == {}
        _result, efforts = _set(ws, "")
        assert (efforts["conversation"], efforts["strands"]) == ("", {})
        ws.send_json({"type": "chat", "message": "merci", "client_msg_id": "e4"})
        recv_until(ws, "speech", limit=40)

        # un niveau inconnu, un fil mal nommé : la trame est ignorée, rien ne change
        ws.send_json({"type": "effort", "effort": "colossal"})
        ws.send_json({"type": "effort", "effort": "low", "strand": "pas un id !"})
        ws.send_json({"type": "ping", "t": 1})
        frames = recv_until(ws, "pong", limit=10)
        assert not [f for f in frames if f["type"] in ("effort_result", "efforts")]
    # sans rien de forcé, l'effort du rôle ; forcé, celui de la conversation ; puis de nouveau celui du rôle
    assert backend.efforts("reply") == ["medium", "high", "medium"]
    # le fil qui a le sien, puis celui qui suit la conversation
    assert backend.efforts("pro") == ["max", "high"]


def test_only_an_operator_forces_the_effort(world):
    client, live, backend = world
    bootstrap(client)

    async def bea_session() -> str:
        bea = await live.accounts.create("bea", "un-mot-de-passe-long", operator=False)
        return await live.accounts.open_session(bea)

    key_b = client.portal.call(bea_session)
    with client.websocket_connect(WS, headers={"cookie": f"sessionid={key_b}"}) as ws:
        opening(ws)
        ws.send_json({"type": "effort", "effort": "max"})
        assert recv_until(ws, "effort_result")[-1]["status"] == "forbidden"
        ws.send_json({"type": "chat", "message": "bonjour", "client_msg_id": "b1"})
        frames = recv_until(ws, "speech", limit=40)
        # ni le réglage à l'ouverture, ni après son essai
        assert not [f for f in frames if f["type"] == "efforts"]
    assert backend.efforts("reply") == ["medium"]
