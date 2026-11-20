"""Les images de Teams (ADR 0258) par le vrai serveur : la porte de l'extension (`POST /api/teams/image`) —
gardée avec son message, une fois ; refusée sans message connu, d'un type faux ou d'octets qui mentent, sans clé.
Ce que le magasin en fait et la lecture : ``tests/unit/test_teams_images.py``.
"""

from __future__ import annotations

import base64
import time

from tests.protocol.test_moi_mail import API
from tests.protocol.test_teams_web import DM, headers, new_key
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def message(mid: str, text: str, *, images: int = 0, ago_ms: int = 0) -> dict:
    return {"id": mid, "conv": DM, "author": "Alice", "author_id": "8:orgid:a",
            "time": int(time.time() * 1000) - ago_ms, "text": text, "images": images}


def push(client, key, *messages) -> dict:
    got = client.post("/api/teams/inbox", headers=headers(key), json={
        "conversations": [{"id": DM, "kind": "dm"}], "messages": list(messages)})
    assert got.status_code == 202, got.text
    return got.json()


def image(client, key, mid: str, image_id: str = "0-weu-d1-abc", *, data: bytes = JPEG, kind: str = "image/jpeg",
          position: int = 0):
    return client.post("/api/teams/image", headers=headers(key), json={
        "conv": DM, "id": mid, "image": image_id, "position": position, "type": kind,
        "data": base64.b64encode(data).decode()})


def test_an_image_is_kept_with_its_message_once_and_refused_without_it(world):  # noqa: F811
    client, live, _ = world
    key = new_key(client, live)
    push(client, key, message("1759000000700", "regarde [image]", images=1))
    kept = image(client, key, "1759000000700")
    assert kept.status_code == 202 and kept.json()["kept"] is True
    again = image(client, key, "1759000000700")
    assert again.status_code == 202 and again.json()["kept"] is False, "la même image redite n'en fait qu'une"
    assert image(client, key, "1759000000799").status_code == 404, "son message n'est pas encore arrivé"
    assert image(client, key, "1759000000700", data=b"pas une image", kind="image/jpeg").status_code == 400
    assert image(client, key, "1759000000700", data=PNG, kind="image/jpeg").status_code == 400, "le type ment"
    assert image(client, key, "1759000000700", kind="application/pdf").status_code == 400
    assert client.post("/api/teams/image", headers=headers("mtk_rien"), json={}).status_code == 401
    store = live.kernel.ports["teams"]
    [seen] = client.portal.call(store.images_of, [client.portal.call(store.thread, "principal", DM, 1)[0].ref])
    assert seen.mime == "image/jpeg" and seen.size == len(JPEG)


def test_the_thread_shows_its_images_and_serves_their_bytes_behind_the_login(world):  # noqa: F811
    client, live, _ = world
    key = new_key(client, live)
    push(client, key, message("1759000000760", "[image]", images=1))
    image(client, key, "1759000000760", "0-img-vue")
    assert client.get(API + f"/teams/thread?conversation={DM}").status_code == 401, "derrière la connexion"
    bootstrap(client)
    [m] = client.get(API + f"/teams/thread?conversation={DM}").json()["messages"]
    assert [(i["id"], i["mime"]) for i in m["images"]] == [("0-img-vue", "image/jpeg")]
    got = client.get(API + f"/teams/image?message={m['ref']}&image=0-img-vue")
    assert got.status_code == 200 and got.content == JPEG and got.headers["content-type"] == "image/jpeg"
    assert got.headers["x-content-type-options"] == "nosniff"
    assert client.get(API + f"/teams/image?message={m['ref']}&image=0-autre").status_code == 404
    assert client.get(API + "/teams/image?message=t000000000000&image=0-img-vue").status_code == 404
