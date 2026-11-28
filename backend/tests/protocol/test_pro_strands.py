"""Les fils de travail dans le chat (ADR 0164).

Une opératrice écrit en mode pro dans un fil de travail (``chat.strand``) : sa réponse y arrive (``speech.strand``),
ses outils aussi, la liste de ses fils suit (``strands``). Elle règle un fil (``strand`` : titre, description,
archivé) et en relit les messages (``strand_history``). Le contre-exemple : sans le mode pro, ou pour qui n'est pas
opératrice, le fil désigné est ignoré — le message va au fil ordinaire, et rien de ses fils ne se montre.
"""

from __future__ import annotations

import html
import re
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
from mika.ports.llm_budget import LLMLimits
from mika.vocab.episodes import VOICE_ROLES
from tests.fixtures.console_html import ConsoleHTML
from tests.protocol.test_web import ORIGIN, WS, bootstrap, recv_until
from tests.protocol.test_web_thread import opening


class Worker:
    name = "fake"

    def __init__(self) -> None:
        self.calls = []
        self.pro_text = "Voilà le travail."

    async def complete(self, req):
        self.calls.append(req)
        return LLMResponse(self.pro_text if req.role == "pro" else "Coucou ! [EMOTION:happy:0.4]")


#: le mode pro est le « mode Claude Code » (ADR 0116), et il tient dans le plus petit budget qu'un fournisseur Claude
#: ait eu en service : 43 200 caractères (un contexte déclaré de 24 000 jetons, dont la moitié réservée à la sortie).
#: Sur ses 61 outils déclarés, 54 sont à la demande et ne partent pas avec la requête : comptés quand même, ils
#: remplissaient ce budget à eux seuls (53 701 caractères, ``PromptBudgetError`` sur un fil vide, 2026-11-17 ;
#: ADR 0239)
PRO_WINDOW = LLMLimits(context_tokens=8_192 + 12_000)


@pytest.fixture
def world(tmp_path) -> Iterator[tuple[TestClient, object, Worker]]:
    backend = Worker()
    roles = {str(r): "fake" for r in VOICE_ROLES}
    gateway = LiveGateway(Gateway({"fake": backend}, roles, clock=RealClock(),
                                  voice_roles=frozenset(roles), slots={"fake": 1}, limits={"fake": PRO_WINDOW}))
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


#: une réponse de travail comme le modèle les écrit : du Markdown
PRO_MARKDOWN = "Voilà **le travail** :\n\n## Les devis\n\n| client | montant |\n|---|---|\n| Paul | 1 200 € |"


def test_the_console_shows_each_conversation_apart_and_her_answers_as_the_chat_does(world):
    """L'onglet Échanges de sa fiche (ADR 0241) : le fil avec elle par défaut, ses fils de travail listés à côté avec
    leur titre et leur compte, chacun à part avec sa description ; ses réponses du mode pro s'y lisent rendues comme
    dans le chat, jamais leur Markdown brut."""
    client, _live, backend = world
    backend.pro_text = PRO_MARKDOWN
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        opening(ws)
        recv_until(ws, "strands", limit=10)
        ws.send_json({"type": "chat", "message": "salut toi", "client_msg_id": "o1"})
        recv_until(ws, "speech", limit=40)
        ws.send_json({"type": "chat", "message": "liste moi les devis", "client_msg_id": "s1", "mode": "pro",
                      "strand": "devis-1"})
        _speech_and_strands(ws)
        ws.send_json({"type": "strand", "id": "devis-1", "title": "Devis IN", "description": "montants HT",
                      "archived": False})
        recv_until(ws, "strand_result")

    page = "/admin/fiche/person/user_1?onglet=echanges"
    ordinary = client.get(page)
    assert ordinary.status_code == 200
    ConsoleHTML(ordinary.text).check()
    text = html.unescape(ordinary.text)
    assert "salut toi" in text and "liste moi les devis" not in text and "le travail" not in text
    assert 'class="hm-workspace person-threads"' in text and "Fils du mode pro" in text
    assert re.search(r'<a class="on" href="/admin/fiche/person/user_1\?onglet=echanges" aria-current="page">'
                     r'<span>Leur conversation</span><span class="hm-count">2</span>', text)
    assert re.search(r'href="/admin/fiche/person/user_1\?onglet=echanges&travail=devis-1">'
                     r'<span>Devis IN</span><span class="hm-count">2</span>', text)

    work = client.get(f"{page}&travail=devis-1")
    assert work.status_code == 200
    ConsoleHTML(work.text).check()
    text = html.unescape(work.text)
    assert "liste moi les devis" in text and "salut toi" not in text
    assert "<h2>Devis IN</h2><p>montants HT</p>" in text
    assert "<strong>le travail</strong>" in text and "<h3>Les devis</h3>" in text and "document-grid" in text
    assert "**le travail**" not in text and "|---|" not in text
