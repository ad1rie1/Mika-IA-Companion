"""Les fichiers du chat, sur l'application réelle (ADR 0312) : ``GET /api/moi/chat/fichiers``.

- toute la conversation, pas seulement ce qu'un écran a chargé : les pièces de la personne et les fichiers que Mika lui
  a envoyés, du plus récent au plus ancien, page par page ; chercher par nom (sans casse ni accents), par sorte, par
  qui l'a envoyé ; ceux d'un seul message (``message``) ;
- ce qui se télécharge porte l'adresse que ``/files/<id>`` rend à ce compte ; un fichier retiré dit pourquoi, sans
  adresse ; un autre compte ne voit rien ;
- le fil avec elle laisse ses fils de travail de côté ; un fil de travail se liste à part (``fil``).
"""

from __future__ import annotations

import asyncio
import base64
import functools
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from starlette.testclient import TestClient

from mika.adapters.llm.config import LiveGateway
from mika.adapters.llm.gateway import Gateway
from mika.adapters.preprocess import LocalPreprocessor
from mika.adapters.system import RealClock
from mika.adapters.vectors import HashEmbedder
from mika.adapters.web.app import WebConfig
from mika.app.server import build
from mika.contracts import attachments as attachments_c
from mika.contracts.runtime import AttachmentMeta, PerceptionReceived
from mika.faculties import attachments
from mika.kernel.events import Content, Origin
from mika.kernel.registry import ArbitrationPolicy
from mika.ports.llm import LLMResponse, ToolCall
from mika.vocab.episodes import VOICE_ROLES
from tests.protocol.test_web import recv_until

CHAT = "ws://localhost:8001/ws"
FILES = "/api/moi/chat/fichiers"
PASSWORD = "un-mot-de-passe-long"
NOTE = "Réunion : relire le bail".encode()
TABLE = b"poste;montant\nplomberie;2480\n"
LIST = "# Courses\n\n- pain\n- lait\n"


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
        return LLMResponse("D'accord, je regarde.")


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

    def files(self, token: str, **params: Any) -> dict[str, Any]:
        r = self.client.get(FILES, params=params, headers=bearer(token))
        assert r.status_code == 200, r.text
        return r.json()


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


def _piece(name: str, mime: str, data: bytes) -> dict[str, str]:
    return {"name": name, "type": mime, "data": base64.b64encode(data).decode()}


def _kept(ctx: Ctx, *files: str) -> None:
    """Chaque pièce lue de près (sa ligne écrite) : ``port.pieces`` rend aussi celles qui attendent leur lecture."""
    store = ctx.live.kernel.ports["store"]
    deadline = time.monotonic() + 15
    while len(ctx.call(attachments.rows, store, files)) < len(files):
        assert time.monotonic() < deadline, "une pièce n'a jamais été lue"
        time.sleep(0.05)


def _converse(ctx: Ctx, token: str) -> None:
    """Deux pièces dans un message, puis la liste qu'elle envoie."""
    with ctx.client.websocket_connect(CHAT, headers=bearer(token)) as ws:
        ws.send_json({"type": "chat", "message": "regarde", "client_msg_id": "p1",
                      "attachments": [_piece("note.txt", "text/plain", NOTE),
                                      _piece("Dépenses.csv", "text/csv", TABLE)]})
        recv_until(ws, "speech", limit=40)
        ws.send_json({"type": "chat", "message": "tu peux me faire la liste de courses ?", "client_msg_id": "p2"})
        recv_until(ws, "speech", limit=40)


def test_the_conversation_lists_her_pieces_and_what_mika_sent_page_by_page(ctx) -> None:
    bea, token = ctx.account("bea")
    _converse(ctx, token)
    note, table = attachments.file_id(bea, NOTE), attachments.file_id(bea, TABLE)
    _kept(ctx, note, table)

    got = ctx.files(token)
    assert [(i["name"], i["from"], i["sorte"]) for i in got["items"]] == [
        ("courses.md", "mika", "texte"), ("note.txt", "toi", "texte"), ("Dépenses.csv", "toi", "tableau")]
    assert got["total"] == 3 and got["page"] == 1 and got["pages"] == 1 and got["unavailable"] == 0
    assert got["counts"] == {"": 3, "image": 0, "pdf": 0, "texte": 2, "tableau": 1, "autre": 0}
    hers, first, second = got["items"]
    assert first["id"] == note and first["url"] == f"/files/{note}" and first["size"] == len(NOTE)
    assert first["index"] == 0 and second["index"] == 1 and first["message"] == second["message"]
    assert hers["message"] > first["message"] and first["at"] > 1_600_000_000_000  # des millisecondes
    for item in got["items"]:
        assert item["available"] is True and "reason" not in item
        r = ctx.client.get(item["url"], headers=bearer(token))
        assert r.status_code == 200 and r.content in (NOTE, TABLE, LIST.encode())

    # page par page ; une page au-delà de la dernière rend la dernière
    one = ctx.files(token, par=2)
    assert [i["name"] for i in one["items"]] == ["courses.md", "note.txt"] and one["pages"] == 2
    assert [i["name"] for i in ctx.files(token, par=2, page=2)["items"]] == ["Dépenses.csv"]
    assert ctx.files(token, par=2, page=99)["page"] == 2
    # chercher : par nom, sans casse ni accents ; par sorte ; par qui l'a envoyé
    assert [i["name"] for i in ctx.files(token, q="NOTE")["items"]] == ["note.txt"]
    assert [i["name"] for i in ctx.files(token, q="depenses")["items"]] == ["Dépenses.csv"]
    assert ctx.files(token, q="bail")["total"] == 0  # le contenu ne se cherche pas, le nom seulement
    assert [i["name"] for i in ctx.files(token, sorte="tableau")["items"]] == ["Dépenses.csv"]
    mika = ctx.files(token, de="mika")
    assert [i["name"] for i in mika["items"]] == ["courses.md"] and mika["counts"][""] == 1
    assert ctx.files(token, de="toi", sorte="texte")["counts"] == {
        "": 2, "image": 0, "pdf": 0, "texte": 1, "tableau": 1, "autre": 0}
    # ceux d'un message
    assert [i["name"] for i in ctx.files(token, message=first["message"])["items"]] == ["note.txt", "Dépenses.csv"]

    # un autre compte ne voit rien de tout ça, même en nommant le message
    _chloe, theirs = ctx.account("chloe")
    assert ctx.files(theirs)["items"] == [] and ctx.files(theirs)["total"] == 0
    assert ctx.files(theirs, message=first["message"])["items"] == []
    assert ctx.client.get(FILES).status_code == 401


def test_the_same_piece_sent_twice_is_two_lines_of_the_list(ctx) -> None:
    bea, token = ctx.account("bea")
    with ctx.client.websocket_connect(CHAT, headers=bearer(token)) as ws:
        for cid, name in (("a1", "photo.txt"), ("a2", "vacances.txt")):
            ws.send_json({"type": "chat", "message": "tiens", "client_msg_id": cid,
                          "attachments": [_piece(name, "text/plain", NOTE)]})
            recv_until(ws, "speech", limit=40)
    _kept(ctx, attachments.file_id(bea, NOTE))
    second, first = ctx.files(token)["items"]
    assert (first["name"], second["name"]) == ("photo.txt", "vacances.txt") and first["id"] == second["id"]
    assert first["key"] != second["key"] and first["message"] < second["message"]
    [only] = ctx.files(token, message=first["message"])["items"]
    assert only["name"] == "photo.txt"


def test_a_removed_piece_says_why_and_has_no_address(ctx) -> None:
    bea, token = ctx.account("bea")
    _converse(ctx, token)
    note = attachments.file_id(bea, NOTE)
    _kept(ctx, note, attachments.file_id(bea, TABLE))
    ctx.call(ctx.live.kernel.mind.append,
             [attachments_c.EXPIRED.draft(files=(note,), handle=bea, reason=attachments_c.OPERATOR)],
             emitter="attachments", correlation="essai", origin=Origin.PROCESS)
    got = ctx.files(token)
    [removed] = [i for i in got["items"] if i["id"] == note]
    assert removed["available"] is False and removed["reason"] == "operator" and "url" not in removed
    assert got["unavailable"] == 1


def test_work_strands_are_listed_apart(ctx) -> None:
    ada, token = ctx.account("ada", operator=True)
    data = b"un devis"
    [file] = ctx.call(ctx.live.port.keep_attachments, ada, [data])
    assert file is not None
    ctx.call(ctx.live.port.perceive, PerceptionReceived(
        handle=ada, channel="web", text=Content.of("le devis"), authenticated=True, typed_chars=len("le devis"),
        attachments=(AttachmentMeta(name="devis.txt", kind="file", mime="text/plain", file=file),),
        strand="devis-1", mode="pro"))
    _kept(ctx, file)
    assert ctx.files(token)["items"] == []
    [item] = ctx.files(token, fil="devis-1")["items"]
    assert item["name"] == "devis.txt" and item["url"] == f"/files/{file}"


async def _stuck(self, upload, *, max_chars):
    """Une lecture de près qui ne finit pas (un modèle retenu par son quota, injoignable…)."""
    await asyncio.Event().wait()


def test_a_piece_is_yours_again_before_she_has_read_it(ctx, monkeypatch) -> None:
    monkeypatch.setattr(LocalPreprocessor, "study", _stuck)
    bea, token = ctx.account("bea")
    data = b"une photo, pas encore lue"
    [file] = ctx.call(ctx.live.port.keep_attachments, bea, [data])
    ctx.call(ctx.live.port.perceive, PerceptionReceived(
        handle=bea, channel="web", text=Content.of("regarde"), authenticated=True, typed_chars=len("regarde"),
        attachments=(AttachmentMeta(name="photo.txt", kind="file", mime="text/plain", file=file),)))
    [item] = ctx.files(token)["items"]
    assert item["available"] is True and item["url"] == f"/files/{file}" and item["size"] == 0
    assert ctx.call(ctx.live.port.pieces, (file,))[0].available  # le fil relu lui donne déjà son adresse
    assert not ctx.call(ctx.live.port.pieces, ("0" * 32,))
    r = ctx.client.get(item["url"], headers=bearer(token))
    assert r.status_code == 200 and r.content == data
    _chloe, theirs = ctx.account("chloe")
    assert ctx.client.get(item["url"], headers=bearer(theirs)).status_code == 404


def test_wrong_filters_are_refused(ctx) -> None:
    _bea, token = ctx.account("bea")
    for params, field in (({"sorte": "musique"}, "sorte"), ({"de": "lea"}, "de"), ({"message": "abc"}, "message"),
                          ({"message": "²"}, "message")):
        r = ctx.client.get(FILES, params=params, headers=bearer(token))
        assert r.status_code == 400 and field in r.json()["fields"], params
