"""Une connexion n'est pas une présence (ADR 0062), sur l'application réelle.

L'application du téléphone garde sa connexion en arrière-plan pour recevoir ; personne ne regarde l'écran :

- ouverte avec ``X-Mika-Presence: away``, elle ne s'annonce pas (pas de ``presence.connected``, personne de
  présent), ne reçoit rien qu'elle n'ait demandé (ni fil initial, ni visage, ni panneau) ; ce qu'elle demande
  (``sync``) et ce qui lui est adressé (la réponse, sans voix) arrivent ;
- ``presence here:true`` : la personne est là, tout de suite, avec un visage et un panneau frais ;
  ``here:false`` : partie après la grâce — une bascule rapide n'écrit rien ; des bascules en rafale restent
  bornées et finissent dans le dernier état voulu ;
- un message envoyé depuis l'arrière-plan (une réponse depuis la notification) est perçu sur le canal du
  téléphone, sans faire croire qu'on est revenu devant l'écran ;
- une pensée à voix haute ne part jamais vers un écran que personne ne regarde.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from starlette.testclient import TestClient

from mika.adapters.llm.config import LiveGateway
from mika.adapters.llm.gateway import Gateway
from mika.adapters.system import RealClock
from mika.adapters.vectors import HashEmbedder
from mika.adapters.web import protocol
from mika.adapters.web.app import WebConfig
from mika.app.server import build
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.kernel.registry import ArbitrationPolicy
from mika.ports.delivery import Delivery
from mika.vocab import privacy, voice
from mika.vocab.episodes import VOICE_ROLES
from tests.protocol.test_web import Echo, recv_until

CHAT = "ws://localhost:8001/ws"
PASSWORD = "un-mot-de-passe-long"


@dataclass
class Ctx:
    client: TestClient
    live: Any

    def call(self, fn, *args, **kw):
        return self.client.portal.call(functools.partial(fn, *args, **kw))

    def phone(self, name: str = "bea") -> str:
        self.call(self.live.accounts.create, name, PASSWORD, operator=False)
        r = self.client.post("/auth/token", json={"username": name, "password": PASSWORD, "client": "mobile"})
        assert r.status_code == 200, r.text
        return r.json()["token"]

    def journal(self, kind) -> list[Any]:
        mind = self.live.kernel.mind
        return self.call(lambda: [mind.decode(e) for e in mind.store.read() if e.type == kind.name])

    def present(self) -> tuple[str, ...]:
        return self.call(lambda: tuple(self.live.kernel.mind.frame().get(presence_c.PRESENT)))


@pytest.fixture
def ctx(tmp_path, monkeypatch) -> Iterator[Ctx]:
    monkeypatch.setattr(protocol, "AWAY_GRACE_S", 0.1)
    roles = {str(r): "fake" for r in VOICE_ROLES}
    gateway = LiveGateway(Gateway({"fake": Echo()}, roles, clock=RealClock(), voice_roles=frozenset(roles),
                                  slots={"fake": 1}))
    app, live = build(tmp_path / "data", web=WebConfig(), gateway=gateway, embedder=HashEmbedder(),
                      arbitration=ArbitrationPolicy(), reply_wait=None)
    with TestClient(app, base_url="http://localhost:8001") as client:  # un client natif : pas d'Origin
        yield Ctx(client, live)


def headers(token: str, presence: str | None = None) -> dict[str, str]:
    out = {"authorization": f"Bearer {token}"}
    if presence is not None:
        out["x-mika-presence"] = presence
    return out


def pong(ws, t: int) -> list[dict]:
    """Tout ce qui arrive avant la réponse à ce ping (le serveur répond dans l'ordre)."""
    ws.send_json({"type": "ping", "t": t})
    frames = []
    while True:
        frame = ws.receive_json()
        if frame.get("type") == "pong" and frame.get("t") == t:
            return frames
        frames.append(frame)


def settle(seconds: float = 0.3) -> None:
    time.sleep(seconds)  # la grâce (0,1 s ici) court dans la boucle du serveur


def test_away_receives_only_what_it_asks_and_what_is_addressed(ctx) -> None:
    token = ctx.phone()
    with ctx.client.websocket_connect(CHAT, headers=headers(token, "away")) as ws:
        assert pong(ws, 1) == []  # ni fil initial, ni visage, ni panneau
        assert ctx.journal(presence_c.CONNECTED) == [] and ctx.present() == ()
        ws.send_json({"type": "sync", "after_id": 0})
        assert ws.receive_json()["type"] == "history"
        ws.send_json({"type": "chat", "message": "tu dors ?", "client_msg_id": "m1"})
        frames = recv_until(ws, "speech")
        speech = frames[-1]
        assert speech["text"] and speech["speak"] is False  # adressée, et sans voix : personne ne regarde
        assert [f["type"] for f in frames if f["type"] in ("emotion_update", "inner_state_update")] == []
        perceived = [e for e in ctx.journal(rt.PERCEPTION_RECEIVED)]
        assert perceived and perceived[-1].data.channel == privacy.MOBILE
        assert ctx.journal(presence_c.CONNECTED) == [] and ctx.present() == ()  # répondre n'est pas revenir


def test_here_then_gone_after_the_grace(ctx) -> None:
    token = ctx.phone()
    with ctx.client.websocket_connect(CHAT, headers=headers(token, "away")) as ws:
        ws.send_json({"type": "presence", "here": True})
        kinds = {f["type"] for f in pong(ws, 1)}
        assert {"emotion_update", "inner_state_update"} <= kinds  # un visage et un panneau frais
        assert ctx.present() == ("user_1",)
        [arrived] = ctx.journal(presence_c.CONNECTED)
        assert arrived.data.channel == privacy.MOBILE
        # passer à l'appareil photo et revenir : rien au journal
        ws.send_json({"type": "presence", "here": False})
        ws.send_json({"type": "presence", "here": True})
        pong(ws, 2)
        settle()
        assert ctx.journal(presence_c.DISCONNECTED) == [] and ctx.present() == ("user_1",)
        ws.send_json({"type": "presence", "here": False})
        pong(ws, 3)
        assert ctx.present() == ("user_1",)  # pas encore : la grâce
        settle()
        assert ctx.present() == () and len(ctx.journal(presence_c.DISCONNECTED)) == 1
        assert pong(ws, 4) == []  # partie : plus de panneau ni de visage


def test_a_flood_of_toggles_stays_bounded_and_ends_where_asked(ctx, monkeypatch) -> None:
    monkeypatch.setattr(protocol, "PRESENCE_RATE", (4, 1.0))
    token = ctx.phone()
    with ctx.client.websocket_connect(CHAT, headers=headers(token, "away")) as ws:
        for n in range(8):
            ws.send_json({"type": "presence", "here": True})
            pong(ws, 10 + n)
            ws.send_json({"type": "presence", "here": False})
            pong(ws, 100 + n)
            settle(0.15)
        written = len(ctx.journal(presence_c.CONNECTED)) + len(ctx.journal(presence_c.DISCONNECTED))
        assert written < 16  # 8 allers-retours sans borne en écriraient 16
        settle(1.5)
        assert ctx.present() == ()  # le dernier état voulu : partie
        ws.send_json({"type": "presence", "here": True})
        pong(ws, 999)
        settle(1.2)
        assert ctx.present() == ("user_1",)


def test_an_inner_thought_never_reaches_an_unwatched_screen(ctx) -> None:
    token = ctx.phone()
    thought = Delivery(key="pensee-1", target="user_1", channel="web", room=None, text="hmm, je me demande…",
                       persona=voice.INNER)
    with ctx.client.websocket_connect(CHAT, headers=headers(token, "away")) as ws:
        ctx.call(ctx.live.hub.deliver, thought)
        assert pong(ws, 1) == []
        ws.send_json({"type": "presence", "here": True})
        pong(ws, 2)
        ctx.call(ctx.live.hub.deliver, Delivery(key="pensee-2", target="user_1", channel="web", room=None,
                                                text="tiens, elle est là", persona=voice.INNER))
        frames = pong(ws, 3)
        assert [f["text"] for f in frames if f["type"] == "speech"] == ["tiens, elle est là"]


def test_a_screen_without_the_header_behaves_as_before(ctx) -> None:
    token = ctx.phone()
    with ctx.client.websocket_connect(CHAT, headers=headers(token)) as ws:
        first = ws.receive_json()
        assert first["type"] == "history" and first["mode"] == "initial"
        assert ctx.present() == ("user_1",)


def test_a_turn_asked_elsewhere_reaches_the_phone_with_its_question(ctx) -> None:
    """Écrit du navigateur, répondu sur le téléphone aussi : la ligne de la question arrive avant la réponse,
    sinon le curseur du téléphone la dépasserait et il ne la verrait jamais (1.F)."""
    phone = ctx.phone()
    screen = ctx.client.post("/auth/token", json={"username": "bea", "password": PASSWORD}).json()["token"]
    with ctx.client.websocket_connect(CHAT, headers=headers(phone, "away")) as away, \
            ctx.client.websocket_connect(CHAT, headers=headers(screen)) as web:
        recv_until(web, "history")
        web.send_json({"type": "chat", "message": "on mange quoi ce soir ?", "client_msg_id": "w1"})
        asked = recv_until(web, "speech")
        assert [f for f in asked if f["type"] == "history" and f["mode"] == "catchup"] == []  # rien de neuf ici
        frames = recv_until(away, "speech")
        catchups = [f for f in frames if f["type"] == "history" and f["mode"] == "catchup"]
        assert catchups, [f["type"] for f in frames]
        question = catchups[-1]["messages"]
        assert [m["text"] for m in question] == ["on mange quoi ce soir ?"]
        assert frames[-1]["user_message_id"] == question[-1]["id"]
