"""Les fils de travail dans le chat (ADR 0164).

Une opératrice écrit en mode pro dans un fil de travail (``chat.strand``) : sa réponse y arrive (``speech.strand``),
ses outils aussi, la liste de ses fils suit (``strands``). Elle règle un fil (``strand`` : titre, description,
archivé) et en relit les messages (``strand_history``). Le contre-exemple : sans le mode pro, ou pour qui n'est pas
opératrice, le fil désigné est ignoré — le message va au fil ordinaire, et rien de ses fils ne se montre.
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
from tests.protocol.test_web import ORIGIN, WS, bootstrap, recv_until
from tests.protocol.test_web_thread import opening


class Worker:
    name = "fake"

    def __init__(self) -> None:
        self.calls = []

    async def complete(self, req):
        self.calls.append(req)
        return LLMResponse("Voilà le travail." if req.role == "pro" else "Coucou ! [EMOTION:happy:0.4]")


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


def _speech_and_strands(ws, limit: int = 60) -> tuple[dict, dict]:
    """Sa réponse, et la liste de ses fils qui a suivi le message (dans un ordre ou dans l'autre)."""
    frames: list[dict] = []
    for _ in range(limit):
        frames.append(ws.receive_json())
        speech = [f for f in frames if f["type"] == "speech"]
        listed = [f for f in frames if f["type"] == "strands"]
        if speech and listed:
            return speech[-1], listed[-1]
    raise AssertionError(f"pas de réponse ni de liste : {[f.get('type') for f in frames]}")


def test_her_operator_works_in_a_thread_of_its_own(world):
    client, _live, backend = world
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        opening(ws)
        assert recv_until(ws, "strands", limit=10)[-1]["items"] == []  # à l'ouverture : aucun fil encore
        ws.send_json({"type": "chat", "message": "liste moi les devis", "client_msg_id": "s1", "mode": "pro",
                      "strand": "devis-1"})
        speech, listed = _speech_and_strands(ws)
        assert speech["strand"] == "devis-1" and speech["mode"] == "pro" and speech["text"] == "Voilà le travail."
        [item] = listed["items"]
        assert item["id"] == "devis-1" and item["opener"] == "liste moi les devis" and item["title"] == ""

        # régler le fil : son titre, sa description ; la liste suit
        ws.send_json({"type": "strand", "id": "devis-1", "title": "Devis IN", "description": "montants HT",
                      "archived": False})
        result = recv_until(ws, "strand_result")[-1]
        assert result == {"type": "strand_result", "id": "devis-1", "status": "ok"}
        [item] = recv_until(ws, "strands")[-1]["items"]
        assert (item["title"], item["description"], item["archived"]) == ("Devis IN", "montants HT", False)
        ws.send_json({"type": "chat", "message": "et celui de Paul ?", "client_msg_id": "s2", "mode": "pro",
                      "strand": "devis-1"})
        _speech_and_strands(ws)

        # relire le fil : ses messages seulement, chacun avec son fil
        ws.send_json({"type": "strand_history", "id": "devis-1"})
        got = recv_until(ws, "history", limit=20)[-1]
        assert got["mode"] == "strand" and got["strand"] == "devis-1" and got["more"] is False
        assert [m["text"] for m in got["messages"]] == ["liste moi les devis", "Voilà le travail.",
                                                       "et celui de Paul ?", "Voilà le travail."]
        assert {m["strand"] for m in got["messages"]} == {"devis-1"}

        # le rattrapage porte tout le compte : les lignes du fil de travail disent leur fil
        ws.send_json({"type": "sync", "after_id": 0})
        rows = recv_until(ws, "history", limit=20)[-1]["messages"]
        assert {m.get("strand") for m in rows} == {"devis-1"}
    pro = [c for c in backend.calls if c.role == "pro"]
    assert len(pro) == 2 and "Devis IN" in "".join(m.content for m in pro[1].messages)


def test_a_thread_is_honoured_only_in_pro_mode_and_for_an_operator(world):
    client, live, backend = world
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        opening(ws)
        recv_until(ws, "strands", limit=10)
        # sans le mode pro, le fil désigné est ignoré : le fil ordinaire
        ws.send_json({"type": "chat", "message": "salut", "client_msg_id": "o1", "strand": "devis-1"})
        speech = recv_until(ws, "speech", limit=40)[-1]
        assert "strand" not in speech and speech["mode"] == ""
        # un identifiant invalide, aussi
        ws.send_json({"type": "chat", "message": "et ça ?", "client_msg_id": "o2", "mode": "pro",
                      "strand": "pas un id !"})
        speech = recv_until(ws, "speech", limit=40)[-1]
        assert "strand" not in speech and speech["mode"] == "pro"

    async def bea_session() -> str:
        bea = await live.accounts.create("bea", "un-mot-de-passe-long", operator=False)
        return await live.accounts.open_session(bea)

    key_b = client.portal.call(bea_session)
    with client.websocket_connect(WS, headers={"cookie": f"sessionid={key_b}"}) as ws:
        opening(ws)
        ws.send_json({"type": "strand", "id": "devis-1", "title": "à moi", "description": "", "archived": False})
        assert recv_until(ws, "strand_result")[-1]["status"] == "forbidden"
        ws.send_json({"type": "chat", "message": "trouve le devis", "client_msg_id": "b1", "mode": "pro",
                      "strand": "devis-1"})
        frames = recv_until(ws, "speech", limit=40)
        assert "strand" not in frames[-1] and not [f for f in frames if f["type"] == "strands"]
