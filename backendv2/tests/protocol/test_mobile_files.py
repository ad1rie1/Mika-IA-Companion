"""Les fichiers qu'elle envoie, jusqu'au téléphone (ADR 0062), sur l'application réelle.

- la trame ``speech`` porte toujours ``attachments`` : ici, le fichier qu'elle a écrit (nom, sorte, taille,
  adresse de téléchargement, disponible) ;
- le fil relu (``history``) le rend sous son message à elle ; ceux de la personne gardent ``{name, kind}`` ;
- ``GET /files/<id>`` : avec le jeton de la personne, ses octets (à télécharger, jamais à afficher, sous une sorte
  sûre) ; avec un autre compte, le même 404 qu'un fichier inconnu ; sans compte, 401 ; un jeton à côté d'une
  ``Origin``, c'est un navigateur — seule sa session compte ; retiré, 410 ; un identifiant malformé, 404 ;
  trop de téléchargements, 429.
"""

from __future__ import annotations

import functools
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from starlette.testclient import TestClient

from mika.adapters.llm.config import LiveGateway
from mika.adapters.llm.gateway import Gateway
from mika.adapters.system import RealClock
from mika.adapters.vectors import HashEmbedder
from mika.adapters.web import app as web_app
from mika.adapters.web.app import WebConfig
from mika.app.server import build
from mika.contracts import shares as shares_c
from mika.kernel.events import Origin
from mika.kernel.registry import ArbitrationPolicy
from mika.ports.llm import LLMResponse, ToolCall
from mika.vocab.episodes import VOICE_ROLES
from tests.protocol.test_web import recv_until

CHAT = "ws://localhost:8001/ws"
ORIGIN = "http://localhost:3000"
PASSWORD = "un-mot-de-passe-long"
LIST = "# Courses\n\n- pain\n- lait\n- œufs\n"


class Sharer:
    """Le modèle : à « liste », elle prépare un fichier puis le dit ; sinon elle répond."""

    name = "fake"

    async def complete(self, req):
        if req.role != "reply":
            return LLMResponse("D'accord.")
        asked = next((m.content for m in reversed(req.messages) if m.role == "user"), "")
        if "liste" in asked and not any(m.role == "tool" for m in req.messages):
            return LLMResponse("", (ToolCall("c1", "share_text", {"name": "courses.md", "content": LIST}),),
                               stop="tool_use")
        return LLMResponse("Je te mets la liste en pièce jointe. [EMOTION:happy:0.6]")


@dataclass
class Ctx:
    client: TestClient
    live: Any

    def call(self, fn, *args, **kw):
        return self.client.portal.call(functools.partial(fn, *args, **kw))

    def phone(self, name: str) -> str:
        self.call(self.live.accounts.create, name, PASSWORD, operator=False)
        r = self.client.post("/auth/token", json={"username": name, "password": PASSWORD, "client": "mobile"})
        assert r.status_code == 200, r.text
        return r.json()["token"]


@pytest.fixture
def ctx(tmp_path) -> Iterator[Ctx]:
    roles = {str(r): "fake" for r in VOICE_ROLES}
    gateway = LiveGateway(Gateway({"fake": Sharer()}, roles, clock=RealClock(), voice_roles=frozenset(roles),
                                  slots={"fake": 1}))
    app, live = build(tmp_path / "data", web=WebConfig(), gateway=gateway, embedder=HashEmbedder(),
                      arbitration=ArbitrationPolicy(), reply_wait=None)
    with TestClient(app, base_url="http://localhost:8001") as client:  # un client natif : pas d'Origin
        yield Ctx(client, live)


def bearer(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def caught_up(ctx: Ctx, token: str) -> dict:
    """Ce qu'un ``sync`` depuis le début rend (le rattrapage, après le fil initial d'une connexion présente)."""
    with ctx.client.websocket_connect(CHAT, headers=bearer(token)) as ws:
        ws.send_json({"type": "sync", "after_id": 0})
        for _ in range(40):
            frame = ws.receive_json()
            if frame.get("type") == "history" and frame.get("mode") == "catchup":
                return frame
    raise AssertionError("pas de rattrapage")


def ask_for_the_list(ctx: Ctx, token: str) -> dict:
    with ctx.client.websocket_connect(CHAT, headers=bearer(token)) as ws:
        ws.send_json({"type": "chat", "message": "tu peux me faire la liste de courses ?", "client_msg_id": "m1"})
        return next(f for f in reversed(recv_until(ws, "speech", limit=40)) if f["type"] == "speech")


def test_the_file_reaches_the_phone_and_only_its_recipient_downloads_it(ctx, monkeypatch) -> None:
    bea = ctx.phone("bea")
    speech = ask_for_the_list(ctx, bea)
    assert speech["text"].startswith("Je te mets la liste")
    [item] = speech["attachments"]
    file = item["id"]
    assert item == {"id": file, "name": "courses.md", "kind": "file", "mime": "text/markdown",
                    "size": len(LIST.encode()), "url": f"/files/{file}", "available": True}

    history = caught_up(ctx, bea)
    mine = [m for m in history["messages"] if m["role"] == "assistant" and m["attachments"]]
    assert mine and mine[-1]["attachments"] == [item]
    assert all(m["attachments"] == [] for m in history["messages"] if m["role"] == "user")

    r = ctx.client.get(f"/files/{file}", headers=bearer(bea))
    assert r.status_code == 200 and r.content == LIST.encode()
    assert r.headers["content-disposition"] == "attachment; filename*=UTF-8''courses.md"
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
    assert r.headers["content-security-policy"] == "sandbox; default-src 'none'"
    assert r.headers["content-type"].startswith("text/markdown")

    chloe = ctx.phone("chloe")
    unknown = ctx.client.get("/files/" + "0" * 32, headers=bearer(bea))
    theirs = ctx.client.get(f"/files/{file}", headers=bearer(chloe))
    assert theirs.status_code == unknown.status_code == 404 and theirs.json() == unknown.json()
    assert ctx.client.get(f"/files/{file}").status_code == 401
    # un jeton à côté d'une Origin : un navigateur, sans session ici — refusé
    assert ctx.client.get(f"/files/{file}", headers={**bearer(bea), "origin": ORIGIN}).status_code == 401
    for bad in ("abc", "G" * 32, "0" * 31, "..%2F..%2Fmind.db"):
        assert ctx.client.get(f"/files/{bad}", headers=bearer(bea)).status_code == 404, bad

    kernel = ctx.live.kernel
    ctx.call(kernel.mind.append, [shares_c.EXPIRED.draft(files=(file,), target=speech["person_id"],
                                                                 reason=shares_c.RETENTION)],
             emitter="shares", correlation="essai", origin=Origin.PROCESS)
    assert ctx.client.get(f"/files/{file}", headers=bearer(bea)).status_code == 410
    history = caught_up(ctx, bea)
    [after] = [a for m in history["messages"] for a in m["attachments"] if a.get("id") == file]
    assert after["available"] is False

    monkeypatch.setattr(web_app, "FILES_RATE", (1, 60.0))  # un nouveau compte : une nouvelle fenêtre
    dan = ctx.phone("dan")
    assert [ctx.client.get(f"/files/{file}", headers=bearer(dan)).status_code for _ in range(2)] == [404, 429]


def test_a_browser_downloads_with_its_session(ctx) -> None:
    """Le navigateur : sa session (cookie), sans jeton ; le fichier d'une autre reste introuvable."""
    bea = ctx.phone("bea")
    file = ask_for_the_list(ctx, bea)["attachments"][0]["id"]
    browser = ctx.client
    browser.headers["origin"] = ORIGIN
    browser.get("/auth/whoami")
    r = browser.post("/auth/login", json={"username": "bea", "password": PASSWORD},
                     headers={"X-CSRFToken": browser.cookies.get("csrftoken")})
    assert r.status_code == 200, r.text
    got = browser.get(f"/files/{file}")
    assert got.status_code == 200 and hashlib.sha256(got.content).hexdigest() == hashlib.sha256(
        LIST.encode()).hexdigest()


def test_the_download_never_announces_a_dangerous_type() -> None:
    for mime, sent in (("text/markdown", "text/markdown"), ("image/png", "image/png"),
                       ("text/html", "application/octet-stream"), ("image/svg+xml", "application/octet-stream"),
                       ("text/javascript", "application/octet-stream"), ("TEXT/PLAIN; charset=x", "text/plain"),
                       ("", "application/octet-stream")):
        assert web_app.safe_mime(mime) == sent, mime


def test_the_console_shows_what_she_sent_and_an_operator_downloads_it(ctx) -> None:
    """L'onglet « Fichiers » de la fiche d'une personne, la fiche d'un fichier, son téléchargement (opérateur)."""
    ctx.call(ctx.live.accounts.create, "adrien", PASSWORD, operator=True)
    bea = ctx.phone("bea")
    speech = ask_for_the_list(ctx, bea)
    file, person = speech["attachments"][0]["id"], speech["person_id"]
    console = ctx.client
    console.headers["origin"] = ORIGIN
    console.get("/auth/whoami")
    r = console.post("/auth/login", json={"username": "adrien", "password": PASSWORD},
                     headers={"X-CSRFToken": console.cookies.get("csrftoken")})
    assert r.status_code == 200, r.text
    tab = console.get(f"/inspecteur/fiche/person/{person}?onglet=fichiers")
    assert tab.status_code == 200 and "courses.md" in tab.text and "envoyé" in tab.text
    fiche = console.get(f"/inspecteur/fiche/partage/{file}")
    assert fiche.status_code == 200 and "courses.md" in fiche.text and "Fichier envoyé" in fiche.text
    got = console.get(f"/inspecteur/telecharger/partage/{file}", params={"fichier": "courses.md"})
    assert got.status_code == 200 and got.content == LIST.encode()
    assert console.get("/inspecteur/fiche/partage/" + "0" * 32).status_code == 404


def test_every_speech_frame_says_its_attachments() -> None:
    """« Toujours présent » : même une réponse ratée (la trame de repli) porte un tableau, vide."""
    from mika.adapters.web import protocol

    frame = protocol.fallback_speech("user_1", protocol.ERROR, user_message_id=None, client_msg_id=None)
    assert frame["type"] == "speech" and frame["attachments"] == []
