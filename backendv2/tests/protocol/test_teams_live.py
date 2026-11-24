"""La boîte d'envoi de Teams en direct (``/api/teams/live``, ADR 0251), par le vrai serveur.

L'extension se présente par sa clé dans le premier message, jamais dans l'adresse ; elle reçoit la boîte tout de
suite, puis à chaque changement, et un signe de vie quand rien ne change. Une clé fausse, une origine de page web,
une extension qui ne se présente pas, une clé retirée en cours de route : la connexion se ferme, avec un code qui
dit pourquoi.
"""

from __future__ import annotations

import time

import pytest
from starlette.websockets import WebSocketDisconnect

from mika.adapters.web import doors
from mika.app import teams as teams_app
from mika.ports.teams import Draft
from tests.protocol.test_teams_web import DM, EXTENSION, batch, headers, new_key
from tests.protocol.test_web import world  # noqa: F401 — fixture

LIVE = "/api/teams/live"


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    """Relue toutes les 50 ms, un signe de vie après 300 ms : le test ne dure pas."""
    monkeypatch.setattr(doors, "LIVE_EVERY_S", 0.05)
    monkeypatch.setattr(doors, "LIVE_PING_S", 0.3)
    monkeypatch.setattr(doors, "LIVE_HELLO_S", 0.5)
    monkeypatch.setattr(teams_app, "LIVE_RECHECK_S", 0.0)  # la clé revérifiée à chaque relecture


def queue(client, live, body: str) -> str:
    """Un brouillon de Mika mis dans la boîte d'envoi du compte ``principal``."""
    store = live.kernel.ports["teams"]
    draft = client.portal.call(store.save_draft, Draft(id="", conversation=DM, body=body))
    now = time.time_ns() // 1000
    shown = client.portal.call(store.preview, draft.id)
    assert client.portal.call(lambda: store.enqueue(draft.id, mode="draft", digest=shown.digest,
                                                    expires_at=now + 3_600_000_000, now=now)) == ""
    return draft.id


def closed_with(ws) -> int:
    with pytest.raises(WebSocketDisconnect) as gone:
        ws.receive_json()
    return gone.value.code


def test_the_outbox_comes_at_once_then_at_each_change_with_signs_of_life(world):  # noqa: F811
    client, live, _ = world
    key = new_key(client, live)
    assert client.post("/api/teams/inbox", json=batch(), headers=headers(key)).status_code == 202
    with client.websocket_connect(LIVE, headers={"Origin": EXTENSION}) as ws:
        ws.send_json({"type": "hello", "key": key})
        assert ws.receive_json() == {"type": "outbox", "items": []}
        draft = queue(client, live, "Oui, 14 h me va.")
        pushed = ws.receive_json()
        assert pushed["type"] == "outbox" and [i["id"] for i in pushed["items"]] == [draft]
        assert pushed["items"][0]["text"] == "Oui, 14 h me va." and pushed["items"][0]["status"] == "queued"
        # rien ne change : un signe de vie, pas la boîte redite
        assert ws.receive_json() == {"type": "ping"}
        ws.send_json({"type": "ping"})  # ce qu'elle envoie ensuite est lu, ignoré
        # posée dans Teams : l'accusé reste en HTTP, et la boîte suit
        assert client.post(f"/api/teams/outbox/{draft}", json={"result": "placed"},
                           headers=headers(key)).status_code == 200
        again = ws.receive_json()
        assert again["type"] == "outbox" and again["items"][0]["status"] == "placed"


def test_the_outbox_leaves_as_soon_as_it_changes_without_being_reread(world, monkeypatch):  # noqa: F811
    """ADR 0308 : la boîte d'envoi part à l'extension dès qu'elle change — l'écriture du cache la réveille —, pas au
    bout d'une relecture : le filet (30 s) et le signe de vie sont loin, la trame arrive quand même."""
    monkeypatch.setattr(doors, "LIVE_EVERY_S", 30.0)
    monkeypatch.setattr(doors, "LIVE_PING_S", 5.0)
    client, live, _ = world
    key = new_key(client, live)
    assert client.post("/api/teams/inbox", json=batch(), headers=headers(key)).status_code == 202
    with client.websocket_connect(LIVE, headers={"Origin": EXTENSION}) as ws:
        ws.send_json({"type": "hello", "key": key})
        assert ws.receive_json() == {"type": "outbox", "items": []}
        started = time.monotonic()
        draft = queue(client, live, "Oui, 14 h me va.")
        pushed = ws.receive_json()  # pas un signe de vie (5 s) : la boîte, aussitôt
        assert pushed["type"] == "outbox" and [i["id"] for i in pushed["items"]] == [draft]
        assert time.monotonic() - started < 2.0


def test_a_wrong_key_a_web_page_or_silence_close_the_connection(world):  # noqa: F811
    client, live, _ = world
    key = new_key(client, live)
    with client.websocket_connect(LIVE, headers={"Origin": EXTENSION}) as ws:
        ws.send_json({"type": "hello", "key": "mtk_pas_la_bonne"})
        assert closed_with(ws) == 4401
    with client.websocket_connect(LIVE, headers={"Origin": EXTENSION}) as ws:
        ws.send_text("pas du JSON")
        assert closed_with(ws) == 4400
    with client.websocket_connect(LIVE, headers={"Origin": EXTENSION}) as ws:
        assert closed_with(ws) == 4408  # ne s'est pas présentée à temps
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect(LIVE, headers={"Origin": "https://ailleurs.example"}) as ws:
            ws.receive_json()
    assert refused.value.code == 4403
    # sans origine (un client natif) ou avec celle d'une extension : la bonne clé passe
    with client.websocket_connect(LIVE) as ws:
        ws.send_json({"type": "hello", "key": key})
        assert ws.receive_json()["type"] == "outbox"


def test_a_key_withdrawn_or_teams_switched_off_closes_an_open_connection(world):  # noqa: F811
    client, live, _ = world
    key = new_key(client, live)
    with client.websocket_connect(LIVE, headers={"Origin": EXTENSION}) as ws:
        ws.send_json({"type": "hello", "key": key})
        assert ws.receive_json()["type"] == "outbox"
        client.portal.call(live.teams.revoke_key, "principal")
        while True:
            try:
                got = ws.receive_json()
            except WebSocketDisconnect as gone:
                assert gone.code == 4401
                break
            assert got["type"] == "ping"  # au plus un signe de vie avant la fermeture


def test_beyond_its_connections_a_key_gives_the_oldest_place_to_the_newest(world, monkeypatch):  # noqa: F811
    client, live, _ = world
    monkeypatch.setattr(doors, "LIVE_PER_ACCOUNT", 1)
    key = new_key(client, live)
    with client.websocket_connect(LIVE, headers={"Origin": EXTENSION}) as first:
        first.send_json({"type": "hello", "key": key})
        assert first.receive_json()["type"] == "outbox"
        with client.websocket_connect(LIVE, headers={"Origin": EXTENSION}) as second:
            second.send_json({"type": "hello", "key": key})
            assert second.receive_json()["type"] == "outbox"
            assert closed_with(first) == 4409  # une connexion morte d'un sommeil ne bloque pas la nouvelle


def test_a_key_of_the_wrong_shape_is_refused_without_reaching_the_gate(world):  # noqa: F811
    client, live, _ = world
    new_key(client, live)
    with client.websocket_connect(LIVE, headers={"Origin": EXTENSION}) as ws:
        ws.send_text('{"type": "hello", "key": "mtk_\\ud800"}')  # un demi-caractère : du JSON valide
        assert closed_with(ws) == 4401
    with client.websocket_connect(LIVE, headers={"Origin": EXTENSION}) as ws:
        ws.send_json({"type": "hello", "key": "mtk_" + "a" * 300})
        assert closed_with(ws) == 4401


def test_connections_that_have_not_presented_themselves_are_capped_per_address(world, monkeypatch):  # noqa: F811
    client, live, _ = world
    monkeypatch.setattr(doors, "LIVE_HELLO_S", 5.0)
    key = new_key(client, live)
    with client.websocket_connect(LIVE) as a, client.websocket_connect(LIVE) as b:
        with client.websocket_connect(LIVE) as third:
            assert closed_with(third) == 4429  # une trame se lit avant toute clé : pas plus de deux inconnues
        a.send_json({"type": "hello", "key": key})
        assert a.receive_json()["type"] == "outbox"
        b.send_json({"type": "hello", "key": key})
        assert b.receive_json()["type"] == "outbox"
    # présentées, elles ne comptent plus parmi les inconnues
    with client.websocket_connect(LIVE) as later:
        later.send_json({"type": "hello", "key": key})
        assert later.receive_json()["type"] == "outbox"
