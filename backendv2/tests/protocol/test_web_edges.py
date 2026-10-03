"""Les bords du web, vérifiés contre le contrat réel du frontend (``frontend/src`` en
lecture : ``ChatOverlay.ts``, ``chatSync.ts``, ``SpeechPresenter.ts``,
``InnerLifePanel.ts``, ``WebSocketClient.ts``).

Ce qu'une personne verrait :

- elle envoie trois photos et la connexion reste vivante (le ping répond
  pendant qu'on les décrit) ;
- Mika choisit de se taire : « Mika écrit… » disparaît (une trame sans texte) ;
- la réponse échoue : son message reste envoyé (il est reçu), une note dit que
  la réponse ne viendra pas ; la cause en clair et où la réparer, aux seules
  opératrices ; rien n'est épinglé en bas du fil ;
- le murmure ne part qu'aux écrans de la personne à qui elle va écrire — un
  inconnu dont l'onglet est ouvert n'entend rien ; sans cible, seulement aux
  opératrices ; jamais d'identifiant de message ;
- elle s'endort : chaque écran garde son panneau (rêve, journal, identité) ;
- deux onglets ouverts : un seul parle ;
- le visage ne passe pas à une autre émotion juste après une réplique ;
- se déconnecter ou perdre son compte ferme la WebSocket en 4401 ;
- la connexion ne trahit pas qui a un compte, et l'étranglement tient par IP.
"""

from __future__ import annotations

import asyncio
import base64
import time
from collections.abc import Iterator
from typing import Any

import anyio
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from mika.adapters.llm.config import LiveGateway
from mika.adapters.llm.gateway import Gateway, UnconfiguredRole
from mika.adapters.system import RealClock
from mika.adapters.vectors import HashEmbedder
from mika.adapters.web import accounts as accounts_mod
from mika.adapters.web import protocol
from mika.adapters.web.app import LoginThrottle, WebConfig
from mika.adapters.web.hub import REPLY_HOLD_S, Hub
from mika.app.server import build
from mika.contracts import affect as affect_c
from mika.kernel.registry import ArbitrationPolicy
from mika.ports import delivery as delivery_p
from mika.ports.delivery import Delivery, EmotionView
from mika.ports.llm import LLMResponse
from mika.vocab.affect import Emotion
from mika.vocab.episodes import Role

ORIGIN = "http://localhost:3000"
WS = "ws://localhost:8001/ws"
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 100).decode()


class Fake:
    name = "fake"

    def __init__(self, reply: str = "d'accord [EMOTION:happy:0.6]", caption_s: float = 0.0,
                 fail: BaseException | None = None) -> None:
        self.calls: list[Any] = []
        self.reply = reply
        self.caption_s = caption_s
        self.fail = fail

    async def complete(self, req):
        self.calls.append(req)
        if req.role == "caption":
            await asyncio.sleep(self.caption_s)
            return LLMResponse("un chat roux")
        if req.role == "reply":
            if self.fail is not None:
                raise self.fail
            return LLMResponse(self.reply)
        return LLMResponse("{}")


@pytest.fixture
def make(tmp_path) -> Iterator[Any]:
    clients: list[TestClient] = []

    def _make(backend: Fake, *, gateway: LiveGateway | None = None, **kw: Any):
        roles = {str(r): "fake" for r in Role}
        gw = gateway or LiveGateway(Gateway({"fake": backend}, roles, clock=RealClock(), voice_roles=frozenset(),
                                            slots={"fake": 4}))
        app, live = build(tmp_path / "data", web=WebConfig(), gateway=gw, embedder=HashEmbedder(),
                          arbitration=ArbitrationPolicy(), **kw)
        client = TestClient(app, base_url="http://localhost:8001", headers={"Origin": ORIGIN})
        client.__enter__()
        clients.append(client)
        return client, live

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def csrf(client: TestClient) -> dict[str, str]:
    client.get("/auth/whoami")
    return {"X-CSRFToken": client.cookies.get("csrftoken")}


def bootstrap(client: TestClient) -> None:
    r = client.post("/auth/bootstrap", json={"username": "adrien", "password": "un-mot-de-passe-long"},
                    headers=csrf(client))
    assert r.status_code == 200, r.text


#: au-delà, une trame attendue n'est pas venue : le test échoue au lieu de figer la suite
FRAME_TIMEOUT_S = 15.0


def bound(ws) -> None:
    """Les lectures de cette WebSocket de test bornées dans le temps (``receive_json`` attend sinon
    sans fin une trame qu'une régression ne produit plus)."""
    rx = getattr(ws, "_send_rx", None)
    if rx is None:  # une autre version de Starlette : lectures non bornées
        return

    async def receive():
        with anyio.fail_after(FRAME_TIMEOUT_S):
            return await rx.receive()

    ws.receive = lambda: ws.portal.call(receive)


def opening(ws) -> None:
    bound(ws)
    assert ws.receive_json()["type"] == "history"
    assert ws.receive_json()["type"] == "emotion_update"
    # son état intérieur à la connexion (sommeil, énergie, où elle est dans sa chambre)
    state = ws.receive_json()
    assert state["type"] == "inner_state_update" and "place" in state["inner_state"]


def until(ws, kind: str, limit: int = 30) -> list[dict]:
    frames = []
    for _ in range(limit):
        frame = ws.receive_json()
        frames.append(frame)
        if frame.get("type") == kind:
            return frames
    raise AssertionError(f"pas de trame {kind} : {[f.get('type') for f in frames]}")


def second_session(client: TestClient, live, name: str = "bea", operator: bool = False) -> str:
    async def make_account() -> str:
        acc = await live.accounts.create(name, "un-mot-de-passe-long", operator=operator)
        return await live.accounts.open_session(acc)

    return client.portal.call(make_account)


# ── La connexion reste vivante pendant qu'on décrit ses photos ────────────


def test_a_ping_is_answered_while_attachments_are_being_described(make):
    client, _ = make(Fake(caption_s=1.5))
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        opening(ws)
        photos = [{"name": f"p{i}.png", "type": "image/png", "data": PNG} for i in range(3)]
        t0 = time.monotonic()
        ws.send_json({"type": "chat", "message": "regarde", "client_msg_id": "a1", "attachments": photos})
        ws.send_json({"type": "ping", "t": 7})
        frames = until(ws, "pong")
        pong_after = time.monotonic() - t0
        assert pong_after < 1.0, f"pong au bout de {pong_after:.1f} s : la lecture attendait la description"
        assert "ack" not in [f["type"] for f in frames]  # l'accusé viendra, après la perception
        ack = until(ws, "ack")[-1]
        assert ack == {"type": "ack", "client_msg_id": "a1", "status": "accepted"}


def test_messages_of_one_connection_keep_their_order(make):
    client, _ = make(Fake(caption_s=0.5))
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        opening(ws)
        ws.send_json({"type": "chat", "message": "un", "client_msg_id": "o1",
                      "attachments": [{"name": "p.png", "type": "image/png", "data": PNG}]})
        ws.send_json({"type": "chat", "message": "deux", "client_msg_id": "o2"})
        acks = []
        while len(acks) < 2:
            frame = ws.receive_json()
            if frame["type"] == "ack":
                acks.append(frame["client_msg_id"])
        assert acks == ["o1", "o2"]


# ── Une rafale : chaque bulle rattachée à sa ligne du fil ─────────────────


class SlowReply(Fake):
    """Une réponse qui prend une seconde : la rafale arrive pendant qu'elle se compose."""

    async def complete(self, req):
        if req.role == "reply":
            await asyncio.sleep(1.0)
        return await super().complete(req)


def test_a_burst_binds_every_bubble_not_only_the_last(make):
    """« salut », « t'as vu le match ? », « allo ? » : une réponse règle les trois, mais sa trame ``speech`` ne
    lie que le dernier message. Les deux autres bulles restaient sans identifiant — le curseur passait au-delà,
    aucun ``sync`` ne les renvoyait, et hors de la fenêtre initiale elles finissaient sous tout le fil
    (``chatSync.orderKey`` : sans id ⇒ +∞). Juste avant la réponse, une trame ``history`` (``catchup``) porte
    leurs lignes : ``mergeHistory`` les adopte par leur texte."""
    client, _ = make(SlowReply(reply="Oui, quel match ! [EMOTION:happy:0.6]"))
    bootstrap(client)
    burst = {"r1": "salut", "r2": "t'as vu le match hier soir ?", "r3": "allo ?"}
    with client.websocket_connect(WS) as ws:
        opening(ws)
        for cid, text in burst.items():
            ws.send_json({"type": "chat", "message": text, "client_msg_id": cid})
        frames = []
        while not any(f["type"] == "speech" and f["text"] for f in frames):
            frames.append(ws.receive_json())
    speech = next(f for f in frames if f["type"] == "speech" and f["text"])
    bound_ids = {speech["client_msg_id"]: speech["user_message_id"]}
    assert speech["client_msg_id"] == "r3"
    catchups = [f for f in frames[: frames.index(speech)] if f["type"] == "history" and f["mode"] == "catchup"]
    assert catchups, [f["type"] for f in frames]  # avant la réponse : le client les a déjà rattachées
    by_text = {m["text"]: m["id"] for c in catchups for m in c["messages"] if m["role"] == "user"}
    for cid, text in burst.items():
        if cid != "r3":
            bound_ids[cid] = by_text.get(text)
    assert all(isinstance(i, int) and i > 0 for i in bound_ids.values()), bound_ids
    assert bound_ids["r1"] < bound_ids["r2"] < bound_ids["r3"]  # l'ordre du fil, pas +∞


# ── Ce que devient une question sans réponse ──────────────────────────────


def test_when_she_chooses_silence_the_typing_bubble_goes_away(make):
    client, live = make(Fake(reply="[EMOTION:sad:0.4]"))  # rien d'autre que la balise : elle s'abstient
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        opening(ws)
        ws.send_json({"type": "chat", "message": "tu m'en veux ?", "client_msg_id": "b1"})
        frames = until(ws, "speech")
        speech = frames[-1]
        # ChatOverlay : hideTyping() ; bindServerId(cid, user_message_id) ; pas de bulle (texte vide)
        assert speech["text"] == "" and speech["speak"] is False and speech["message_id"] is None
        assert speech["client_msg_id"] == "b1" and speech["user_message_id"] > 0
        assert speech["emotion"] in {e.value for e in Emotion}  # SpeechPresenter : le visage du moment
        ws.send_json({"type": "ping", "t": 1})
        assert [f["type"] for f in until(ws, "pong")] == ["pong"]  # une seule fois


def test_a_failed_reply_keeps_the_message_sent_and_says_no_reply_is_coming(make):
    """G-1 : la réponse échoue. Son message, lui, est reçu (il est dans le fil) : la bulle ne se raye pas
    (« refusé — Mika est saturée »), un second ``ack`` ``no_reply`` dit que la réponse ne viendra pas, avec sa
    cause en un mot ; le client pose « Mika n'a pas pu répondre — réessaie » sous la bulle."""
    client, live = make(Fake(fail=RuntimeError("panne du fournisseur")))
    bootstrap(client)
    key_b = second_session(client, live, "bea")  # une personne du chat, pas une opératrice
    with client.websocket_connect(WS, headers={"cookie": f"sessionid={key_b}"}) as ws:
        opening(ws)
        ws.send_json({"type": "chat", "message": "allo ?", "client_msg_id": "f1"})
        first = until(ws, "ack")[-1]
        assert first["status"] == "accepted"
        frames = until(ws, "ack")
        speech = next(f for f in frames if f["type"] == "speech")
        assert speech["text"] == "" and speech["client_msg_id"] == "f1"  # « Mika écrit… » disparaît
        user_id = speech["user_message_id"]
        second = frames[-1]
        # chatSync.applyAck : la bulle reste « envoyée », une note dessous ; ni la cause en clair ni la console
        assert second == {"type": "ack", "client_msg_id": "f1", "status": "no_reply", "reason": "error"}
        ws.send_json({"type": "sync", "after_id": user_id - 1})
        catch = until(ws, "history")[-1]
        assert [m["text"] for m in catch["messages"] if m["id"] == user_id] == ["allo ?"]  # il est bien dans son fil
        assert not [f for f in frames if f["type"] == "speech" and f["text"]]  # aucune bulle sans id épinglée


def test_without_a_model_only_an_operator_reads_how_to_fix_it(make):
    """G-5 : sans modèle, une personne du chat ne lit jamais une consigne d'administration (« python -m mika llm
    … »), ni de la bouche de Mika ni ailleurs : seulement la note de G-1. Une opératrice lit la cause en clair et
    où la réparer — la console, pas la ligne de commande — dans l'accusé, une note de la machine (jamais une pensée
    de Mika)."""
    client, live = make(Fake(fail=UnconfiguredRole("reply")))
    bootstrap(client)  # adrien, opérateur
    key_b = second_session(client, live, "bea")

    def failed_turn(ws, cid: str) -> list[dict]:
        opening(ws)
        ws.send_json({"type": "chat", "message": "salut", "client_msg_id": cid})
        until(ws, "ack")
        frames = until(ws, "ack")
        ws.send_json({"type": "ping", "t": 9})
        return frames + until(ws, "pong")

    with client.websocket_connect(WS, headers={"cookie": f"sessionid={key_b}"}) as bea:
        seen = failed_turn(bea, "u1")
    no_reply = next(f for f in seen if f.get("status") == "no_reply")
    assert no_reply == {"type": "ack", "client_msg_id": "u1", "status": "no_reply", "reason": "no_model"}
    assert not [f for f in seen if f["type"] == "speech" and f["text"]]  # rien que Mika « dirait »
    assert "mika llm" not in str(seen) and "inspecteur" not in str(seen)

    with client.websocket_connect(WS) as adrien:
        seen = failed_turn(adrien, "u2")
    no_reply = next(f for f in seen if f.get("status") == "no_reply")
    assert no_reply["reason"] == "no_model" and no_reply["href"] == protocol.PROVIDERS_HREF
    assert "fournisseur" in no_reply["detail"] and "mika llm" not in no_reply["detail"]
    assert not [f for f in seen if f["type"] == "speech" and f["text"]]


def test_a_reply_failure_reported_by_the_outbox_is_said_once(make):
    """KER-15 : une réponse reprise (personne ne l'attend) qui échoue arrive par la file de sortie."""
    client, live = make(Fake())
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        opening(ws)
        failed = Delivery(key="e1", target="user_1", channel="web", room=None, kind=delivery_p.REPLY_FAILED,
                          reply_to=41, client_msg_id="k1", text="TimeoutError()")

        async def twice() -> tuple[bool, bool]:
            return await live.hub.deliver(failed), await live.hub.deliver(failed)

        assert client.portal.call(twice) == (True, True)
        frames = until(ws, "ack")
        assert frames[-1]["status"] == "no_reply" and frames[-1]["reason"] == "timeout"
        assert "délai" in frames[-1]["detail"]  # adrien est opérateur : la cause en clair
        ws.send_json({"type": "ping", "t": 2})
        assert [f["type"] for f in until(ws, "pong")] == ["pong"]  # dit une fois, pas deux


def test_a_question_abandoned_as_too_old_is_not_called_a_saturation(make):
    """Une question reprise au démarrage, des heures après, est abandonnée (« trop tard ») : la bulle le dit
    ainsi, pas « Mika est saturée, réessaie dans un instant »."""
    client, live = make(Fake())
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        opening(ws)
        late = Delivery(key="e2", target="user_1", channel="web", room=None, kind=delivery_p.REPLY_FAILED,
                        reply_to=42, client_msg_id="k2", text=delivery_p.TOO_LATE)
        client.portal.call(lambda: live.hub.deliver(late))
        frames = until(ws, "ack")
        assert frames[-1]["status"] == "no_reply" and frames[-1]["reason"] == "too_late"


@pytest.mark.parametrize("outcome, detail, reason", [
    ("failed", "UnconfiguredRole: aucun modèle associé au rôle « reply »", protocol.NO_MODEL),
    ("failed", "ConnectionError: Failed to connect to Ollama", protocol.UNREACHABLE),
    ("failed", "APIConnectionError: Connection error.", protocol.UNREACHABLE),
    ("failed", "ConnectError: [Errno 111] Connection refused", protocol.UNREACHABLE),
    ("timeout", "", protocol.TIMEOUT),
    ("failed", "timeout", protocol.TIMEOUT),  # la file de sortie : l'issue en guise de détail
    ("failed", "TimeoutError()", protocol.TIMEOUT),
    ("failed", "ReadTimeout: lecture trop longue", protocol.TIMEOUT),
    ("failed", delivery_p.TOO_LATE, protocol.TOO_LATE_REASON),
    ("failed", "RuntimeError: panne", protocol.ERROR),
    ("failed", "abandonnée après deux tentatives", protocol.ERROR),
])
def test_the_cause_of_a_missing_reply_is_read_from_its_detail(outcome, detail, reason):
    assert protocol.no_reply_reason(outcome, detail) == reason


def test_a_message_held_for_her_morning_does_not_leave_her_typing_all_night(make):
    """Elle dort, la personne ne peut pas la réveiller : la réponse attend son réveil. « Mika écrit… » ne
    tourne pas cinq minutes pendant sa nuit — une trame sans texte (``voice_reason`` « asleep ») l'éteint et
    rattache la bulle à sa ligne du fil ; la réponse viendra au matin."""
    client, _ = make(Fake(), reply_wait=lambda frame, seq: 0)  # elle dort : toute réponse attend son réveil
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        opening(ws)
        ws.send_json({"type": "chat", "message": "tu dors ?", "client_msg_id": "n1"})
        assert until(ws, "ack")[-1]["status"] == "accepted"
        speech = until(ws, "speech")[-1]
        assert speech["text"] == "" and speech["speak"] is False and speech["voice_reason"] == "asleep"
        assert speech["client_msg_id"] == "n1" and speech["user_message_id"] > 0
        assert speech["message_id"] is None  # rien de dit : le curseur n'avance pas


# ── Le murmure, les panneaux, les onglets ─────────────────────────────────


def murmur(target: str | None) -> Delivery:
    return Delivery(key="m1", target=target, channel=None, room=None, text="tiens, et si je lui écrivais",
                    persona="inner", emotion=EmotionView("thinking", 0.3), message_id=99, source="conscience")


def test_the_murmur_reaches_only_the_screens_of_the_person_she_is_about_to_write_to(make):
    client, live = make(Fake())
    bootstrap(client)  # adrien, opérateur
    key_b = second_session(client, live, "bea")
    with client.websocket_connect(WS) as adrien, \
            client.websocket_connect(WS, headers={"cookie": f"sessionid={key_b}"}) as bea:
        opening(adrien), opening(bea)
        client.portal.call(live.hub.deliver, murmur("user_2"))
        frames = until(bea, "speech")
        thought = frames[-1]
        assert thought["voice_persona"] == "inner" and thought["message_id"] is None  # ChatOverlay : localOnly
        assert thought["user_message_id"] is None and thought["client_msg_id"] is None
        adrien.send_json({"type": "ping", "t": 3})
        assert [f["type"] for f in until(adrien, "pong")] == ["pong"]  # l'opératrice n'entend pas ce murmure-là


def test_a_murmur_without_target_goes_only_to_operators(make):
    client, live = make(Fake())
    bootstrap(client)
    key_b = second_session(client, live, "bea")
    with client.websocket_connect(WS) as adrien, \
            client.websocket_connect(WS, headers={"cookie": f"sessionid={key_b}"}) as bea:
        opening(adrien), opening(bea)
        client.portal.call(live.hub.deliver, murmur(None))
        assert until(adrien, "speech")[-1]["voice_persona"] == "inner"
        bea.send_json({"type": "ping", "t": 4})
        assert [f["type"] for f in until(bea, "pong")] == ["pong"]  # une inconnue n'entend rien


def test_a_global_state_change_keeps_each_panel(make):
    client, live = make(Fake())
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        opening(ws)
        state = Delivery(key="s1", target=None, channel=None, room=None, kind=delivery_p.STATE)
        client.portal.call(live.hub.deliver, state)
        frame = until(ws, "inner_state_update")[-1]["inner_state"]
        # InnerLifePanel.applyInnerState rend chaque section sans condition : il faut le panneau entier
        assert frame["person_scope"] is True and frame["identity"]["known_as"] == "adrien"


def test_two_tabs_one_voice(make):
    client, _ = make(Fake())
    bootstrap(client)
    with client.websocket_connect(WS) as a:
        opening(a)
        with client.websocket_connect(WS) as b:  # ouvert ensuite (l'ouverture de b pousse un visage à a aussi)
            opening(b)
            a.send_json({"type": "chat", "message": "coucou", "client_msg_id": "t1"})
            speech_a = until(a, "speech")[-1]
            speech_b = until(b, "speech")[-1]
    assert speech_a["text"] == speech_b["text"]
    assert speech_a["speak"] is True and speech_b["speak"] is False  # pas d'écho
    assert speech_b["voice_reason"] == protocol.OTHER_TAB


# ── Le visage après une réplique ──────────────────────────────────────────


class _Port:
    def frame(self):
        raise AssertionError("non utilisé")


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def face(emotion: Emotion, intensity: float) -> affect_c.Face:
    return affect_c.Face(emotion, intensity, ((emotion, 1.0),), (emotion, intensity), (Emotion.NEUTRAL, 0.0))


async def test_the_face_does_not_contradict_the_reply_it_just_delivered():
    clock = _Clock()
    hub = Hub(_Port(), monotonic=clock)  # type: ignore[arg-type]
    sent: list[dict] = []

    async def send(frame):
        sent.append(frame)

    hub.attach(send, handle="user_1", authenticated=True)
    hub.refresh_panels = _no_panels  # type: ignore[method-assign]
    shown = {"face": face(Emotion.SAD, 0.78)}
    hub.face = lambda handle: shown["face"]  # type: ignore[method-assign]
    await hub.deliver(Delivery(key="r1", target="user_1", channel="web", room=None, text="oh.",
                               emotion=EmotionView("sad", 0.8, (("sad", 0.8),), {}, True), message_id=7))
    assert [f["type"] for f in sent] == ["speech"]
    shown["face"] = face(Emotion.LONELY, 0.21)  # une troisième émotion, effondrée
    clock.t += 3
    assert not await hub.push_face("user_1")  # trois secondes après « triste » : pas « seule »
    shown["face"] = face(Emotion.SAD, 0.6)  # la balise qui décroît : même émotion, d'autres intensités passent
    assert await hub.push_face("user_1")
    shown["face"] = face(Emotion.LONELY, 0.21)
    clock.t += REPLY_HOLD_S
    assert await hub.push_face("user_1")  # la réplique est loin : la dérive reprend
    assert [f["emotion"] for f in sent if f["type"] == "emotion_update"] == ["sad", "lonely"]


async def _no_panels(handles=None) -> int:
    return 0


def recorder(box: list[dict]):
    async def send(frame: dict) -> None:
        box.append(frame)

    return send


async def test_the_answer_speaks_where_it_was_asked_an_initiative_where_one_looks_now():
    """Deux onglets de la même personne : la réponse a la voix dans l'onglet qui a posé la question ;
    ce qu'elle dit d'elle-même, dans l'onglet ouvert en dernier (celui qu'on regarde)."""
    clock = _Clock()
    hub = Hub(_Port(), monotonic=clock)  # type: ignore[arg-type]
    hub.refresh_panels = _no_panels  # type: ignore[method-assign]
    old, new = [], []
    a = hub.attach(recorder(old), handle="user_1", authenticated=True)
    clock.t += 5
    hub.note_asked(a, "q1")
    clock.t += 5
    hub.attach(recorder(new), handle="user_1", authenticated=True)

    def said(text: str, cid: str | None) -> Delivery:
        return Delivery(key=text, target="user_1", channel="web", room=None, text=text, message_id=3,
                        client_msg_id=cid, local_hour=15)

    await hub.deliver(said("ta réponse", "q1"))
    await hub.deliver(said("tiens, au fait", None))
    assert [f["speak"] for f in old] == [True, False] and [f["speak"] for f in new] == [False, True]
    assert {f["voice_reason"] for f in old + new if not f["speak"]} == {protocol.OTHER_TAB}


async def test_a_new_pending_action_reaches_the_panel():
    hub = Hub(_StatePort())  # type: ignore[arg-type]
    pushed: list[Any] = []

    async def refresh(handles=None) -> int:
        pushed.append(handles)
        return 1

    hub.attach(_noop, handle="user_1", authenticated=True, operator=True)
    hub.refresh_panels = refresh  # type: ignore[method-assign]
    hub.push_face = _no_face  # type: ignore[method-assign]
    pending = {"now": ()}
    hub._pending_signature = lambda frame: pending["now"]  # type: ignore[method-assign]
    await hub.sync_once()
    assert pushed == []  # premier relevé : la référence
    pending["now"] = (12,)
    await hub.sync_once()
    assert pushed == [None]  # une action attend un accord : chaque panneau est rafraîchi


async def _noop(frame) -> None:
    return None


async def _no_face(handle, *, force=False) -> bool:
    return False


class _Phase:
    value = "awake"


class _StatePort:
    def frame(self):
        return self

    def get(self, key):
        return _Phase()


# ── Sessions et connexion ─────────────────────────────────────────────────


def test_logout_closes_the_open_websockets_of_that_session(make):
    client, _ = make(Fake())
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        opening(ws)
        assert client.get("/auth/logout").status_code == 403  # sans jeton CSRF : une image ne déconnecte pas
        assert client.get("/auth/logout", headers=csrf(client)).status_code == 200  # le client : GET + en-tête
        with pytest.raises(WebSocketDisconnect) as closed:
            for _ in range(5):
                ws.receive_json()
        assert closed.value.code == 4401


def test_a_deactivated_account_loses_its_websocket(make):
    client, live = make(Fake())
    bootstrap(client)
    key_b = second_session(client, live, "bea")
    with client.websocket_connect(WS, headers={"cookie": f"sessionid={key_b}"}) as bea:
        opening(bea)
        assert client.portal.call(lambda: live.accounts.update(2, active=False)) is None
        with pytest.raises(WebSocketDisconnect) as closed:
            for _ in range(5):
                bea.receive_json()
        assert closed.value.code == 4401


def test_login_costs_one_scrypt_whether_the_account_exists_or_not(make, monkeypatch):
    client, live = make(Fake())
    bootstrap(client)
    accounts_mod.decoy_hash()  # le leurre est calculé une fois, d'avance
    calls: list[int] = []
    real = accounts_mod.hashlib.scrypt

    def counting(*a, **kw):
        calls.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(accounts_mod.hashlib, "scrypt", counting)
    h = csrf(client)
    client.post("/auth/login", json={"username": "personne", "password": "un-mot-de-passe-long"}, headers=h)
    unknown = len(calls)
    calls.clear()
    client.post("/auth/login", json={"username": "adrien", "password": "faux-mot-de-passe"}, headers=h)
    assert unknown == len(calls) == 1


def test_login_is_throttled_by_address_whatever_the_name(make):
    client, _ = make(Fake())
    bootstrap(client)
    h = csrf(client)
    codes = [client.post("/auth/login", json={"username": f"nom{i}", "password": "x"}, headers=h).status_code
             for i in range(21)]
    assert codes[:20] == [401] * 20 and codes[20] == 429  # vingt noms différents, une seule adresse


def test_the_throttle_forgets_empty_windows():
    clock = _Clock()
    t = LoginThrottle(5, 60.0, monotonic=clock)
    for i in range(100):
        t.fail(f"ip:{i}")
    assert len(t) == 100
    clock.t += 61
    for i in range(100):
        assert not t.blocked(f"ip:{i}")
    assert len(t) == 0


def test_health_reports_the_channels_and_degrades_when_one_is_down(make):
    client, live = make(Fake())
    live.telegram_status = "retrying"
    body = client.get("/health").json()
    assert body["checks"]["telegram"] == "degraded" and body["status"] == "degraded"
    live.telegram_status = "running"
    assert client.get("/health").json()["checks"]["telegram"] == "ok"
