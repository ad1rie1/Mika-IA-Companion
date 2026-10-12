"""Le téléphone fermé est notifié par Firebase (ADR 0077), sur l'application réelle.

- l'application dit où la notifier (``POST /auth/push`` : jeton Firebase et clé) sous le jeton du téléphone,
  jamais sous un jeton d'écran ni à côté d'une ``Origin`` ; une clé illisible est refusée ; ``available`` dit si
  le serveur a une clé Firebase ;
- ce que Mika dit à la personne part scellé, au seul téléphone sans connexion ouverte, et s'ouvre avec sa clé ;
- un téléphone connecté reçoit par sa connexion, pas en double ;
- un jeton rendu, une inscription retirée, un jeton Firebase mort : plus rien ne part ;
- un même jeton Firebase ne sert qu'un jeton de l'application (une réinstallation ne notifie pas deux fois) ;
- la réponse à une question posée du téléphone revient en notification, pas celle posée d'un navigateur.
"""

from __future__ import annotations

import base64
import functools
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from mika.adapters.llm.config import LiveGateway
from mika.adapters.llm.gateway import Gateway
from mika.adapters.push import fcm, seal
from mika.adapters.system import RealClock
from mika.adapters.vectors import HashEmbedder
from mika.adapters.web import push
from mika.adapters.web.app import WebConfig
from mika.app.server import build
from mika.app.settings import PUSH_KEY_FILE
from mika.kernel.registry import ArbitrationPolicy
from mika.ports.delivery import Delivery
from mika.vocab import voice
from mika.vocab.episodes import VOICE_ROLES
from tests.protocol.test_web import Echo

CHAT = "ws://localhost:8001/ws"
PASSWORD = "un-mot-de-passe-long"
KEY = base64.b64encode(bytes(range(32))).decode()


@dataclass
class FakeFirebase:
    sent: list[tuple[str, dict[str, str]]] = field(default_factory=list)
    outcome: str = fcm.SENT

    def configured(self) -> bool:
        return True

    async def send(self, device_token: str, data: dict[str, str]) -> fcm.SendResult:
        self.sent.append((device_token, dict(data)))
        return fcm.SendResult(self.outcome)


@dataclass
class Phone:
    token: str
    token_id: int
    handle: str


@dataclass
class Ctx:
    client: TestClient
    live: Any
    firebase: FakeFirebase
    #: l'expéditeur Firebase branché par le serveur (les envois passent par le faux ; lui dit quelle clé il lit)
    fcm: Any = None

    def call(self, fn, *args, **kw):
        return self.client.portal.call(functools.partial(fn, *args, **kw))

    def phone(self, name: str = "bea", client: str = "mobile") -> Phone:
        if not any(a.username == name for a in self.call(self.live.accounts.all)):
            self.call(self.live.accounts.create, name, PASSWORD, operator=False)
        r = self.client.post("/auth/token", json={"username": name, "password": PASSWORD, "client": client})
        assert r.status_code == 200, r.text
        body = r.json()
        return Phone(body["token"], body["token_id"], body["person_id"])

    def register(self, phone: Phone, device: str = "fcm-1", key: str = KEY, **headers: str) -> Any:
        return self.client.post("/auth/push", json={"token": device, "key": key},
                                headers={"authorization": f"Bearer {phone.token}", **headers})

    def pushes(self) -> dict[int, bool]:
        """Chaque jeton de l'application : a-t-il dit où le notifier ?"""
        return {t.id: t.push for t in self.call(self.live.accounts.tokens)}

    def say(self, handle: str, text: str = "[SIGH] tu es rentrée ?", **kw: Any) -> list[tuple[str, dict]]:
        """Mika dit quelque chose à cette personne ; rend ce qui est parti par Firebase."""
        before = len(self.firebase.sent)
        d = Delivery(**({"key": f"k{before}", "target": handle, "channel": "mobile", "room": None, "text": text,
                         "message_id": 100 + before} | kw))
        self.call(self.live.hub.deliver, d)
        self.call(self.live.hub.push.drain)
        return self.firebase.sent[before:]


@pytest.fixture
def ctx(tmp_path) -> Iterator[Ctx]:
    roles = {str(r): "fake" for r in VOICE_ROLES}
    gateway = LiveGateway(Gateway({"fake": Echo()}, roles, clock=RealClock(), voice_roles=frozenset(roles),
                                  slots={"fake": 1}))
    app, live = build(tmp_path / "data", web=WebConfig(), gateway=gateway, embedder=HashEmbedder(),
                      arbitration=ArbitrationPolicy(), reply_wait=None)
    firebase = FakeFirebase()
    with TestClient(app, base_url="http://localhost:8001") as client:  # un client natif : pas d'Origin
        real, live.hub.push.sender = live.hub.push.sender, firebase
        yield Ctx(client, live, firebase, real)


def test_only_a_phone_says_where_to_notify_it(ctx) -> None:
    phone = ctx.phone()
    r = ctx.register(phone)
    assert r.status_code == 200 and r.json() == {"ok": True, "available": False}  # pas de clé Firebase ici
    assert ctx.register(phone, origin="http://localhost:3000").status_code == 403
    assert ctx.register(ctx.phone("cle", client="screen")).status_code == 403
    assert ctx.register(Phone("mw_faux", 0, "")).status_code == 401
    assert ctx.register(phone, key="pas une clé").status_code == 400
    assert ctx.register(phone, key=base64.b64encode(b"court").decode()).status_code == 400
    assert ctx.register(phone, device="").status_code == 400
    assert ctx.register(phone, device="deux mots").status_code == 400
    assert ctx.pushes()[phone.token_id] is True


def service_account(project: str) -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    return json.dumps({"type": "service_account", "project_id": project, "client_email": f"m@{project}.iam",
                       "private_key": pem})


def test_available_when_the_server_has_a_key(ctx) -> None:
    ctx.call(ctx.live.settings.save_push, service_account("p"))
    assert ctx.register(ctx.phone()).json()["available"] is True


def test_the_key_can_be_a_file_of_the_data_folder_and_the_console_wins(ctx) -> None:
    """La clé posée dans le dossier de données (``firebase-service-account.json``, à côté de ``secret.key``) sert
    sans rien coller ; une clé collée dans la console passe devant ; le fichier retiré, plus rien ne part."""
    def project() -> str | None:  # lu sur le fil du serveur (la base n'est lisible que là)
        account = ctx.call(ctx.fcm.account)
        return account.project_id if account is not None else None

    path = ctx.live.data / PUSH_KEY_FILE
    path.write_text(service_account("depuis-le-fichier"))
    path.chmod(0o600)
    assert ctx.register(ctx.phone()).json()["available"] is True
    assert project() == "depuis-le-fichier"
    ctx.call(ctx.live.settings.save_push, service_account("depuis-la-console"))
    assert project() == "depuis-la-console"
    ctx.call(ctx.live.settings.save_push, "")
    path.unlink()
    assert project() is None


def test_a_closed_phone_gets_the_sealed_message(ctx) -> None:
    phone = ctx.phone()
    ctx.register(phone, device="fcm-bea")
    sent = ctx.say(phone.handle, attachments=("f1",))
    assert [device for device, _ in sent] == ["fcm-bea"]
    body = seal.unseal(seal.key_from(KEY), sent[0][1])
    assert body["t"] == "speech" and body["text"] == "tu es rentrée ?" and body["id"] == 100
    assert body["files"] == 1 and body["ts"] > 0


def test_nothing_for_a_thought_or_without_registration(ctx) -> None:
    phone = ctx.phone()
    assert ctx.say(phone.handle) == []  # pas encore inscrit
    ctx.register(phone)
    assert ctx.say(phone.handle, persona=voice.INNER) == []
    assert ctx.say("user_999") == []  # un autre compte


def test_a_phone_watching_through_a_live_connection_is_not_notified(ctx) -> None:
    phone = ctx.phone()
    ctx.register(phone)
    with ctx.client.websocket_connect(CHAT, headers={"authorization": f"Bearer {phone.token}"}) as ws:
        ws.send_json({"type": "ping", "t": 1})
        while ws.receive_json()["type"] != "pong":  # le fil initial, le visage, le panneau, puis le pong
            pass
        assert ctx.say(phone.handle) == []  # l'application à l'écran : par sa connexion
        # muette depuis plus de LIVE_S : peut-être morte sans le dire (sortie du Wi-Fi) — notifiée quand même
        for conn in ctx.live.hub.of(phone.handle):
            conn.seen_at -= push.LIVE_S + 1
        assert len(ctx.say(phone.handle)) == 1
    assert len(ctx.say(phone.handle)) == 1  # fermée : la notification


def test_a_phone_that_left_the_screen_is_notified_anyway(ctx) -> None:
    """Quittée depuis peu (connexion « absente ») : l'application reçoit aussi par sa connexion, mais ne montre pas
    deux fois le même message — la notification part, elle ne coûte rien."""
    phone = ctx.phone()
    ctx.register(phone)
    headers = {"authorization": f"Bearer {phone.token}", "x-mika-presence": "away"}
    with ctx.client.websocket_connect(CHAT, headers=headers) as ws:
        ws.send_json({"type": "ping", "t": 1})
        assert ws.receive_json()["type"] == "pong"
        assert len(ctx.say(phone.handle)) == 1


def test_a_rotated_firebase_token_survives_the_death_of_the_old_one(ctx) -> None:
    phone = ctx.phone()
    ctx.register(phone, device="ancien")
    ctx.register(phone, device="neuf")  # Firebase a changé le jeton
    account = int(phone.handle.removeprefix("user_"))
    ctx.call(ctx.live.accounts.clear_push, phone.token_id, "ancien")  # la mort tardive de l'ancien
    assert [r.device_token for r in ctx.call(ctx.live.accounts.push_registrations, account)] == ["neuf"]


def test_nothing_is_scheduled_once_stopping(ctx) -> None:
    phone = ctx.phone()
    ctx.register(phone)
    ctx.call(ctx.live.hub.push.stop)
    assert ctx.say(phone.handle) == []


def test_a_returned_token_or_a_withdrawn_registration_stops_everything(ctx) -> None:
    phone = ctx.phone()
    ctx.register(phone)
    r = ctx.client.delete("/auth/push", headers={"authorization": f"Bearer {phone.token}"})
    assert r.status_code == 200 and ctx.say(phone.handle) == []
    ctx.register(phone)
    assert ctx.client.delete("/auth/token", headers={"authorization": f"Bearer {phone.token}"}).status_code == 200
    assert ctx.say(phone.handle) == []
    assert ctx.register(phone).status_code == 401  # un jeton rendu ne s'inscrit plus


def test_a_dead_firebase_token_is_forgotten(ctx) -> None:
    phone = ctx.phone()
    ctx.register(phone)
    ctx.firebase.outcome = fcm.GONE
    assert len(ctx.say(phone.handle)) == 1
    account = int(phone.handle.removeprefix("user_"))
    assert ctx.call(ctx.live.accounts.push_registrations, account) == []
    assert ctx.say(phone.handle) == []


def test_a_reinstalled_app_is_not_notified_twice(ctx) -> None:
    old, new = ctx.phone(), ctx.phone()
    ctx.register(old, device="meme-telephone")
    ctx.register(new, device="meme-telephone")
    assert [device for device, _ in ctx.say(new.handle)] == ["meme-telephone"]
    assert ctx.pushes()[old.token_id] is False


def test_two_phones_two_notifications(ctx) -> None:
    a, b = ctx.phone(), ctx.phone()
    ctx.register(a, device="tel-a")
    ctx.register(b, device="tel-b")
    assert sorted(device for device, _ in ctx.say(a.handle)) == ["tel-a", "tel-b"]


def test_a_reply_comes_back_to_the_phone_that_asked_not_from_a_browser(ctx) -> None:
    phone = ctx.phone()
    ctx.register(phone)
    hub = ctx.live.hub
    # la question est partie du téléphone (une réponse depuis la notification), qui a fermé sa connexion depuis
    hub._asked_from[(phone.handle, "m1")] = f"token:{phone.token_id}"
    assert len(ctx.say(phone.handle, client_msg_id="m1", reply_to=5)) == 1
    # posée du navigateur : on lit la réponse là où on l'a posée
    hub._asked_from[(phone.handle, "m2")] = "session-du-navigateur"
    assert ctx.say(phone.handle, client_msg_id="m2", reply_to=6) == []
    # une question dont on ne sait plus d'où elle venait (un redémarrage) : dans le doute, notifiée
    assert len(ctx.say(phone.handle, client_msg_id="m3", reply_to=7)) == 1
