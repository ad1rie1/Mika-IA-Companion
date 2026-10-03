"""Le protocole que parle le frontend, vérifié contre son propre code
(``frontend/src/types/messages.ts``, ``network/api.ts``, ``WebSocketClient.ts``)."""

from __future__ import annotations

import base64
from collections.abc import Iterator

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from mika.adapters.llm.config import LiveGateway
from mika.adapters.llm.gateway import Gateway
from mika.adapters.system import RealClock
from mika.adapters.vectors import HashEmbedder
from mika.adapters.web.app import WebConfig
from mika.app.server import build
from mika.kernel.registry import ArbitrationPolicy
from mika.ports.llm import LLMResponse
from mika.vocab.affect import Emotion
from mika.vocab.episodes import VOICE_ROLES

ORIGIN = "http://localhost:3000"
WS = "ws://localhost:8001/ws"
NAMES = {e.value for e in Emotion}


class Echo:
    name = "fake"

    def __init__(self) -> None:
        self.calls = []

    @property
    def replies(self) -> list:
        """Les appels d'une réponse (la vie de nuit, qui suit l'horloge réelle, n'en fait pas partie)."""
        return [c for c in self.calls if c.role == "reply"]

    async def complete(self, req):
        self.calls.append(req)
        return LLMResponse(f"J'ai bien lu [SIGH] : {req.messages[-1].content[-40:]} [EMOTION:happy:0.6]")


@pytest.fixture
def world(tmp_path) -> Iterator[tuple[TestClient, object, Echo]]:
    backend = Echo()
    roles = {str(r): "fake" for r in VOICE_ROLES}
    gateway = LiveGateway(Gateway({"fake": backend}, roles, clock=RealClock(),
                                  voice_roles=frozenset(roles), slots={"fake": 1}))
    # l'horloge est réelle : la nuit, sa réponse à un inconnu attendrait son réveil (ADR 0036) — le
    # protocole se teste à toute heure, sans cette attente
    app, live = build(tmp_path / "data", web=WebConfig(), gateway=gateway, embedder=HashEmbedder(),
                      arbitration=ArbitrationPolicy(), reply_wait=None)
    with TestClient(app, base_url="http://localhost:8001", headers={"Origin": ORIGIN}) as client:
        yield client, live, backend


def csrf(client: TestClient) -> dict[str, str]:
    client.get("/auth/whoami")
    return {"X-CSRFToken": client.cookies.get("csrftoken")}


def bootstrap(client: TestClient, username="adrien", password="un-mot-de-passe-long") -> dict:
    r = client.post("/auth/bootstrap", json={"username": username, "password": password}, headers=csrf(client))
    assert r.status_code == 200, r.text
    return r.json()


def recv_until(ws, kind: str, limit: int = 20) -> list[dict]:
    frames = []
    for _ in range(limit):
        frame = ws.receive_json()
        frames.append(frame)
        if frame.get("type") == kind:
            return frames
    raise AssertionError(f"pas de trame {kind} : {[f.get('type') for f in frames]}")


# ── HTTP ──────────────────────────────────────────────────────────────────


def test_whoami_plants_the_csrf_cookie_and_reports_the_bootstrap_window(world):
    client, _, _ = world
    r = client.get("/auth/whoami")
    body = r.json()
    assert body == {"authenticated": False, "auth_required": True, "needs_bootstrap": True}
    assert client.cookies.get("csrftoken")
    assert r.headers["access-control-allow-origin"] == ORIGIN
    assert r.headers["access-control-allow-credentials"] == "true"


def test_bootstrap_then_409_forever(world):
    client, _, _ = world
    assert client.post("/auth/bootstrap", json={"username": "a", "password": "x"}).status_code == 403  # CSRF
    me = bootstrap(client)
    assert me["authenticated"] and me["person_id"] == "user_1" and me["operator"] is True
    assert me["display_name"] == "adrien"
    again = client.post("/auth/bootstrap", json={"username": "b", "password": "un-autre-long-mdp"},
                        headers=csrf(client))
    # avec son accent : ``LoginOverlay`` lit le statut 409, plus la phrase
    assert again.status_code == 409 and again.json()["error"] == "Un compte existe déjà : connecte-toi."


def test_weak_password_refused_at_bootstrap(world):
    client, _, _ = world
    r = client.post("/auth/bootstrap", json={"username": "adrien", "password": "12345678"}, headers=csrf(client))
    assert r.status_code == 400 and r.json()["error"]


def test_login_401_then_429_after_five_failures(world):
    client, _, _ = world
    bootstrap(client)
    client.get("/auth/logout")
    h = csrf(client)
    codes = [client.post("/auth/login", json={"username": "adrien", "password": "faux"}, headers=h).status_code
             for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429
    blocked = client.post("/auth/login", json={"username": "adrien", "password": "faux"}, headers=h)
    assert blocked.headers["retry-after"] == "60"
    assert blocked.headers["access-control-allow-origin"] == ORIGIN  # CORS aussi sur les erreurs


def test_preflight_allows_credentials_and_csrf_header(world):
    client, _, _ = world
    r = client.options("/auth/login", headers={"Access-Control-Request-Method": "POST",
                                              "Access-Control-Request-Headers": "content-type,x-csrftoken"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-credentials"] == "true"
    assert "x-csrftoken" in r.headers["access-control-allow-headers"].lower()


def test_pending_actions_are_operator_only(world):
    client, live, _ = world
    assert client.post("/api/projects/pending/1/approve", headers=csrf(client)).status_code == 401


# ── WebSocket ─────────────────────────────────────────────────────────────


def test_ws_without_session_is_accepted_then_closed_4401(world):
    client, _, _ = world
    with client.websocket_connect(WS) as ws, pytest.raises(WebSocketDisconnect) as closed:
        ws.receive_json()
    assert closed.value.code == 4401


def test_ws_foreign_origin_is_refused(world):
    client, _, _ = world
    bootstrap(client)
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(WS, headers={"origin": "https://evil.test"}):
        pass


def test_ws_conversation_round_trip(world):
    client, live, backend = world
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        first = ws.receive_json()
        life = first.pop("life")
        assert first == {"type": "history", "mode": "initial", "messages": [], "last_id": 0, "truncated": False,
                         "reset": False}
        assert isinstance(life, str) and len(life) == 16  # l'empreinte de sa vie, opaque
        face = ws.receive_json()
        assert face["type"] == "emotion_update" and face["emotion"] in NAMES
        assert isinstance(face["emotion_blend"], list)
        # puis l'état intérieur, tout de suite : où elle est dans sa chambre, sans attendre un changement
        state = ws.receive_json()
        assert state["type"] == "inner_state_update" and state["inner_state"]["place"] == "center"
        ws.send_json({"type": "identify", "person_id": "user_99", "display_name": "Usurpateur"})
        ws.send_json({"type": "ping", "t": 123})
        assert ws.receive_json() == {"type": "pong", "t": 123}
        ws.send_json({"type": "chat", "message": "coucou toi", "client_msg_id": "m1", "person_id": "user_99"})
        frames = recv_until(ws, "speech")
        ack = next(f for f in frames if f["type"] == "ack")
        assert ack == {"type": "ack", "client_msg_id": "m1", "status": "accepted"}
        assert frames.index(ack) < len(frames) - 1  # l'accusé précède la réponse
        speech = frames[-1]
        assert speech["person_id"] == "user_1"  # l'indice du client est ignoré sur une session
        assert "[EMOTION" not in speech["text"] and "[SIGH]" in speech["text"]
        assert speech["emotion"] == "happy" and speech["emotion_intensity"] == 0.6
        assert isinstance(speech["emotion_blend"], list) and speech["emotion_blend"][0]["emotion"] == "happy"
        assert set(speech["voice_profile"]) == {"pitch", "rate", "gain"}
        assert speech["voice_persona"] == "speaking" and speech["speak"] is True
        assert speech["client_msg_id"] == "m1"
        assert speech["message_id"] > speech["user_message_id"] > 0
        inner = ws.receive_json()
        assert inner["type"] == "inner_state_update"
        assert inner["inner_state"]["sleep_phase"] == "awake" and inner["inner_state"]["person_scope"] is True
        state = inner["inner_state"]
        assert state["identity"]["known_as"] == "adrien" and isinstance(state["identity"]["pending_claims"], list)
        assert set(state["drives"]) == {"social", "expression", "curiosity"}
        assert all(0 <= d["tension"] <= 1 for d in state["drives"].values()) and 0 < state["estime"] < 1
        assert isinstance(state["ruminations"], list)
        profile = state["person_profile"]  # connecté avec son compte : sa fiche est ouverte
        assert isinstance(profile["topics_of_interest"], list) and isinstance(profile["sensitive_topics"], list)
        assert profile["closeness"] in ("stranger", "acquaintance", "friend", "close")
        assert profile["interaction_count"] == 1
        # rattrapage : ce qui suit le curseur
        ws.send_json({"type": "sync", "after_id": speech["user_message_id"] - 1})
        catch = recv_until(ws, "history")[-1]
        assert catch["mode"] == "catchup" and catch["reset"] is False and catch["life"] == life
        assert [m["id"] for m in catch["messages"]] == [speech["user_message_id"], speech["message_id"]]
        assert catch["messages"][1]["text"] == speech["text"].replace(" [SIGH]", "")  # sans prosodie
        assert catch["last_id"] == speech["message_id"]
    assert len(backend.replies) == 1


def test_resent_message_is_not_answered_twice(world):
    client, _, backend = world
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        ws.receive_json(), ws.receive_json()
        ws.send_json({"type": "chat", "message": "salut", "client_msg_id": "same"})
        recv_until(ws, "speech")
        ws.receive_json()  # inner_state_update
        ws.send_json({"type": "chat", "message": "salut", "client_msg_id": "same"})
        ack = recv_until(ws, "ack")[-1]
        assert ack["status"] == "accepted"
        ws.send_json({"type": "ping", "t": 1})
        assert recv_until(ws, "pong")[-1]["t"] == 1
    assert len(backend.replies) == 1


@pytest.mark.parametrize("frame, status", [
    ({"message": "   "}, "empty"),
    ({"message": "x" * 2001}, "too_long"),
    ({"message": "", "attachments": [{"name": "gros.bin", "type": "application/octet-stream",
                                       "data": base64.b64encode(b"0" * (5 * 1024 * 1024 + 10)).decode()}]},
     "attachments_rejected"),
])
def test_chat_refusals_are_said_out_loud(world, frame, status):
    client, _, backend = world
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        ws.receive_json(), ws.receive_json()
        ws.send_json({"type": "chat", "client_msg_id": "r1", **frame})
        ack = recv_until(ws, "ack")[-1]
        assert ack["status"] == status
        if status == "attachments_rejected":
            assert ack["rejected_attachments"] == [{"name": "gros.bin", "reason": "too_large"}]
    assert backend.replies == []


def test_chat_rate_limit(world):
    client, _, _ = world
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        ws.receive_json(), ws.receive_json()
        statuses = []
        for i in range(21):
            ws.send_json({"type": "chat", "message": "", "client_msg_id": f"c{i}"})
            statuses.append(recv_until(ws, "ack")[-1]["status"])
        assert statuses[:20] == ["empty"] * 20 and statuses[20] == "rate_limited"


def test_a_reply_goes_only_to_its_person(world):
    client, live, _ = world
    bootstrap(client)

    async def second_session() -> str:
        bea = await live.accounts.create("bea", "un-mot-de-passe-long", operator=False)
        return await live.accounts.open_session(bea)

    key_b = client.portal.call(second_session)
    # une seule application, deux navigateurs : le second passe sa propre session
    with client.websocket_connect(WS) as a, client.websocket_connect(WS, headers={"cookie": f"sessionid={key_b}"}) as b:
        # l'ouverture de chacun : historique, visage, état intérieur
        for ws in (a, b):
            ws.receive_json(), ws.receive_json(), ws.receive_json()
        a.send_json({"type": "chat", "message": "un secret d'Adrien", "client_msg_id": "s1"})
        speech = recv_until(a, "speech")[-1]
        assert speech["person_id"] == "user_1"
        b.send_json({"type": "ping", "t": 7})
        frames = recv_until(b, "pong")
        assert [f["type"] for f in frames] == ["pong"]  # rien de la réponse d'Adrien


def test_every_dream_kind_the_server_sends_is_one_the_frontend_names():
    """Le panneau intérieur reçoit ``last_dream.dream_type`` (``app/mindport.py``) ; une sorte que le frontend ne
    connaît pas s'affiche brute (« melancholic », en gris). Sa liste (``DREAM_TYPES``, dont le compilateur exige
    un libellé chacune) et celle du serveur sont la même."""
    import re
    from pathlib import Path

    from mika.contracts import self_ as self_c

    source = Path(__file__).resolve().parents[3] / "frontend" / "src" / "types" / "messages.ts"
    if not source.exists():
        pytest.skip("frontend absent")
    declared = re.search(r"DREAM_TYPES\s*=\s*\[(.*?)\]\s*as const", source.read_text(encoding="utf-8"), re.S)
    assert declared is not None, "DREAM_TYPES introuvable dans messages.ts"
    kinds = set(re.findall(r'"([a-z_]+)"', declared.group(1)))
    assert kinds == set(self_c.DREAM_KINDS)
