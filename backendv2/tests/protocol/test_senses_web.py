"""Ce que le frontend envoie en plus des mots : des fichiers (lus au bord,
avant d'entrer dans sa vie), et des images de caméra (opérateurs seulement)."""

from __future__ import annotations

import base64

import pytest
from starlette.websockets import WebSocketDisconnect

from mika.contracts.sensors import SENSED
from mika.runtime.effects import with_content
from tests.protocol.test_web import WS, bootstrap, csrf, recv_until, world  # noqa: F401 — fixture


def test_a_text_attachment_is_read_at_the_edge(world):  # noqa: F811
    client, live, backend = world
    bootstrap(client)
    data = base64.b64encode("Liste de courses : café, pain, confiture".encode()).decode()
    with client.websocket_connect(WS) as ws:
        ws.receive_json(), ws.receive_json()
        ws.send_json({"type": "chat", "message": "regarde ma liste", "client_msg_id": "f1",
                      "attachments": [{"name": "courses.txt", "type": "text/plain", "data": data}]})
        frames = recv_until(ws, "speech")
    assert next(f for f in frames if f["type"] == "ack")["status"] == "accepted"
    prompt = backend.calls[-1].messages[-1].content
    assert "regarde ma liste" in prompt and "café, pain, confiture" in prompt and "courses.txt" in prompt


def test_camera_frames_need_an_operator(world):  # noqa: F811
    client, live, _ = world
    frame = base64.b64encode(b"\xff\xd8" + b"image" * 50).decode()
    with client.websocket_connect("ws://localhost:8001/ws/camera?device=bureau") as ws, \
            pytest.raises(WebSocketDisconnect) as closed:
        ws.send_json({"type": "frame", "mime": "image/jpeg", "data": frame})  # (une régression répondrait « ack »)
        ws.receive_json()
    assert closed.value.code == 4401
    bootstrap(client)  # un opérateur
    with client.websocket_connect("ws://localhost:8001/ws/camera?device=bureau") as ws:
        ws.send_json({"type": "frame", "mime": "image/jpeg", "data": frame})
        assert ws.receive_json() == {"type": "ack", "ok": True}
        ws.send_json({"type": "frame", "mime": "text/html", "data": frame})
        assert ws.receive_json() == {"type": "ack", "ok": False}  # seulement des images


def _sensed(client, live):
    async def go():
        mind = live.kernel.mind
        return [with_content(mind, mind.decode(e)).data for e in mind.store.read() if e.type == SENSED.name]

    return client.portal.call(go)


def test_a_device_signals_through_the_perceptions_route(world):  # noqa: F811
    client, live, _ = world
    body = {"device": "sonnette", "text": "Quelqu'un sonne à la porte", "pertinence": 0.8, "emotion": "surprised"}
    assert client.post("/api/perceptions", json=body).status_code == 403  # ni jeton, ni CSRF
    assert client.post("/api/perceptions", json=body, headers=csrf(client)).status_code == 401  # personne
    assert client.post("/api/perceptions", json=body, headers={"Authorization": "Bearer faux"}).status_code == 403
    token = client.portal.call(live.settings.new_sensors_token)
    ok = client.post("/api/perceptions", json=body, headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 202 and ok.json()["ok"]
    [sensed] = _sensed(client, live)
    assert sensed.source == "appareil:sonnette" and sensed.summary.text == "Quelqu'un sonne à la porte"
    assert sensed.emotion == "surprised" and sensed.pertinence == 0.8
    too_long = client.post("/api/perceptions", json={**body, "text": "x" * 500},
                           headers={"Authorization": f"Bearer {token}"})
    assert too_long.status_code == 400
    codes = [client.post("/api/perceptions", json=body, headers={"Authorization": f"Bearer {token}"}).status_code
             for _ in range(31)]
    assert codes[-1] == 429  # un appareil ne l'inonde pas
    bootstrap(client)  # un opérateur connecté, avec CSRF
    assert client.post("/api/perceptions", json={**body, "device": "script"}, headers=csrf(client)).status_code == 202
