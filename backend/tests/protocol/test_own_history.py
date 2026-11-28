"""Relire sa propre conversation et reprendre ses propres pièces (ADR 0215).

- ``strand_history`` avec un ``id`` vide : le fil avec elle, page par page, pour toute connexion authentifiée ; un
  compte ne lit jamais que le sien (le compte vient de la session, la trame n'en désigne aucun) ; un fil de travail
  reste à son opératrice (ADR 0164) ;
- le fil relu donne aux pièces gardées de la personne un ``url`` : elle seule les télécharge, les autres reçoivent le
  même 404 qu'un fichier inconnu ; une pièce retirée, 410 et ``available`` faux ; une pièce sans clé n'a que son nom.
"""

from __future__ import annotations

import base64
import functools
import json
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
from mika.contracts import attachments as attachments_c
from mika.contracts.entry import HistoryRow, SharedMeta
from mika.contracts.runtime import PerceptionReceived
from mika.faculties import attachments
from mika.kernel.events import Content, Origin
from mika.kernel.registry import ArbitrationPolicy
from mika.ports.llm import LLMResponse
from mika.vocab.episodes import VOICE_ROLES

CHAT = "ws://localhost:8001/ws"
PASSWORD = "un-mot-de-passe-long"
NOTE = "Liste de courses : café, pain, confiture".encode()


class Quiet:
    name = "fake"

    async def complete(self, req):
        return LLMResponse("D'accord.")


@dataclass
class Ctx:
    client: TestClient
    live: Any

    def call(self, fn, *args, **kw):
        return self.client.portal.call(functools.partial(fn, *args, **kw))

    def account(self, name: str, *, operator: bool = False) -> tuple[str, str]:
        """Un compte : son adresse, et le jeton de son téléphone."""
        created = self.call(self.live.accounts.create, name, PASSWORD, operator=operator)
        r = self.client.post("/auth/token", json={"username": name, "password": PASSWORD, "client": "mobile"})
        assert r.status_code == 200, r.text
        return created.handle, r.json()["token"]

    def say(self, handle: str, text: str, **kw: Any) -> None:
        self.call(self.live.port.perceive, PerceptionReceived(handle=handle, channel="web", text=Content.of(text),
                                                              authenticated=True, **kw))

    def socket(self, token: str):
        return self.client.websocket_connect(CHAT, headers=bearer(token))


@pytest.fixture
def ctx(tmp_path) -> Iterator[Ctx]:
    roles = {str(r): "fake" for r in VOICE_ROLES}
    gateway = LiveGateway(Gateway({"fake": Quiet()}, roles, clock=RealClock(), voice_roles=frozenset(roles),
                                  slots={"fake": 1}))
    app, live = build(tmp_path / "data", web=WebConfig(), gateway=gateway, embedder=HashEmbedder(),
                      arbitration=ArbitrationPolicy(), reply_wait=None)
    with TestClient(app, base_url="http://localhost:8001") as client:  # un client natif : pas d'Origin
        yield Ctx(client, live)


def bearer(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def frame_of(ws, kind: str, **wanted: Any) -> dict:
    """La première trame de ce type qui porte ces champs (l'ouverture et sa réponse à elle passent avant)."""
    for _ in range(80):
        frame = ws.receive_json()
        if frame.get("type") == kind and all(frame.get(k) == v for k, v in wanted.items()):
            return frame
    raise AssertionError(f"pas de trame {kind} {wanted}")


def page(ws, thread: str = "", before: int | None = None) -> dict:
    """Une page du fil demandé. Un ``ping`` la suit : sans réponse, le test échoue au lieu de rester à attendre."""
    frame: dict[str, Any] = {"type": "strand_history", "id": thread}
    if before is not None:
        frame["before"] = before
    ws.send_json(frame)
    ws.send_json({"type": "ping", "t": 4242})
    got = None
    for _ in range(80):
        one = ws.receive_json()
        if one.get("type") == "history" and one.get("mode") == "strand" and one.get("strand") == thread:
            got = one
        if one.get("type") == "pong" and one.get("t") == 4242:
            assert got is not None, f"pas de réponse pour le fil « {thread} »"
            return got
    raise AssertionError("pas de pong")


def mine(frame: dict) -> list[str]:
    return [m["text"] for m in frame["messages"] if m["role"] == "user"]


def test_a_person_reads_her_thread_back_page_by_page_and_only_hers(ctx, monkeypatch) -> None:
    monkeypatch.setattr(protocol, "HISTORY_MAX", 3)
    bea, bea_token = ctx.account("bea")
    chloe, chloe_token = ctx.account("chloe")
    for i in range(7):
        ctx.say(bea, f"bea-{i}")
    for i in range(2):
        ctx.say(chloe, f"chloe-{i}")

    with ctx.socket(bea_token) as ws:
        first = page(ws)
        assert first["more"] is True and len(first["messages"]) == 3
        seen = mine(first)
        before = first["messages"][0]["id"]
        for _ in range(6):
            got = page(ws, before=before)
            assert all(m["id"] < before for m in got["messages"])
            seen = mine(got) + seen
            if not got["more"]:
                break
            before = got["messages"][0]["id"]
        else:
            raise AssertionError("la pagination ne finit pas")
    assert seen == [f"bea-{i}" for i in range(7)]  # tout son fil, dans l'ordre ; rien de celui de Chloé

    with ctx.socket(chloe_token) as ws:
        got = page(ws)
        assert mine(got) == ["chloe-0", "chloe-1"] and got["more"] is False


def test_her_own_thread_leaves_work_strands_out_and_a_strand_stays_with_its_operator(ctx) -> None:
    ada, ada_token = ctx.account("ada", operator=True)
    bea, bea_token = ctx.account("bea")
    ctx.say(ada, "bonjour")
    ctx.say(ada, "un travail", strand="devis-1", mode="pro")
    ctx.say(ada, "bonsoir")
    ctx.say(bea, "salut")

    with ctx.socket(ada_token) as ws:
        main = page(ws)
        work = page(ws, "devis-1")
    assert mine(main) == ["bonjour", "bonsoir"] and all("strand" not in m for m in main["messages"])
    assert mine(work) == ["un travail"]

    with ctx.socket(bea_token) as ws:
        ws.send_json({"type": "strand_history", "id": "devis-1"})  # pas opératrice : rien, sans erreur
        ws.send_json({"type": "ping", "t": 7})
        frames = []
        while not frames or frames[-1].get("type") != "pong":
            frames.append(ws.receive_json())
        assert not [f for f in frames if f.get("mode") == "strand"]
        assert mine(page(ws)) == ["salut"]  # son fil, à elle, lui reste


def _send_piece(ws, name: str, data: bytes, cid: str) -> None:
    ws.send_json({"type": "chat", "message": "regarde", "client_msg_id": cid,
                  "attachments": [{"name": name, "type": "text/plain", "data": base64.b64encode(data).decode()}]})
    frame_of(ws, "speech")


def _kept(ctx: Ctx, file: str) -> None:
    deadline = time.monotonic() + 15
    while not ctx.call(ctx.live.port.pieces, (file,)):
        assert time.monotonic() < deadline, "la pièce n'a jamais été gardée"
        time.sleep(0.05)


def test_a_person_gets_her_own_piece_back_and_never_someone_elses(ctx) -> None:
    bea, bea_token = ctx.account("bea")
    _chloe, chloe_token = ctx.account("chloe")
    file = attachments.file_id(bea, NOTE)
    with ctx.socket(bea_token) as ws:
        _send_piece(ws, "note.txt", NOTE, "p1")
    _kept(ctx, file)

    with ctx.socket(bea_token) as ws:
        got = page(ws)
    [item] = next(m["attachments"] for m in got["messages"] if m["role"] == "user")
    assert item["name"] == "note.txt" and item["kind"] == "file" and item["id"] == file
    assert item["url"] == f"/files/{file}" and item["available"] is True and item["size"] == len(NOTE)

    mine_back = ctx.client.get(item["url"], headers=bearer(bea_token))
    assert mine_back.status_code == 200 and mine_back.content == NOTE
    assert mine_back.headers["content-disposition"].startswith("attachment;")
    assert mine_back.headers["x-content-type-options"] == "nosniff"

    theirs = ctx.client.get(item["url"], headers=bearer(chloe_token))
    unknown = ctx.client.get("/files/" + "0" * 32, headers=bearer(chloe_token))
    assert theirs.status_code == unknown.status_code == 404 and theirs.json() == unknown.json()
    assert ctx.client.get(item["url"]).status_code == 401

    ctx.call(ctx.live.kernel.mind.append,
             [attachments_c.EXPIRED.draft(files=(file,), handle=bea, reason=attachments_c.OPERATOR)],
             emitter="attachments", correlation="essai", origin=Origin.PROCESS)
    assert ctx.client.get(item["url"], headers=bearer(bea_token)).status_code == 410
    with ctx.socket(bea_token) as ws:
        [retired] = next(m["attachments"] for m in page(ws)["messages"] if m["role"] == "user")
    assert retired["available"] is False


ROW = HistoryRow(id=9, at=1_000, role="user", text="regarde", source="web", emotion=None, emotion_intensity=0.0,
                 attachments=json.dumps([{"name": "a.png", "kind": "image", "file": "a" * 32},
                                         {"name": "b.txt", "kind": "file", "file": "b" * 32},
                                         {"name": "c.txt", "kind": "file"}]))


def test_only_a_kept_piece_has_an_address() -> None:
    meta = SharedMeta(id="a" * 32, name="a.png", kind="image", mime="image/png", size=12)
    assert protocol.piece_ids(ROW.attachments) == ["a" * 32, "b" * 32]
    [kept, waiting, old] = protocol.history_item(ROW, pieces={meta.id: meta})["attachments"]
    assert kept == {"name": "a.png", "kind": "image", "id": "a" * 32, "mime": "image/png", "size": 12,
                    "url": f"/files/{'a' * 32}", "available": True}
    assert waiting == {"name": "b.txt", "kind": "file"}  # pas encore lue : son nom seul, l'adresse viendra
    assert old == {"name": "c.txt", "kind": "file"}  # un message d'avant les clés
    assert protocol.piece_ids("pas du json") == [] and protocol.piece_ids("{}") == []
