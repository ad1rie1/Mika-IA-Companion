"""Teams (ADR 0069) par le vrai serveur : la porte de l'extension, sa clé, la file.

Sans clé, rien ne passe ; une clé absente et une fausse se répondent pareil (401), et trop d'échecs d'une adresse :
429. Une origine d'extension (ou aucune) passe, une page web d'ailleurs non (403). Un lot illisible ou trop grand
est refusé avant que rien ne soit rangé. La file rend ce qui doit repartir ; un accusé se rejoue sans rien changer,
un accusé impossible est refusé (409), un élément inconnu aussi (404). La clé en clair n'est gardée nulle part.
"""

from __future__ import annotations

import time

from mika.adapters.teams import TeamsConfig
from mika.ports.teams import Draft
from tests.protocol.test_web import world  # noqa: F401 — fixture

EXTENSION = "chrome-extension://abcdefghijklmnop"
DM = "19:alice_adrien@unq.gbl.spaces"


def headers(key: str, origin: str | None = EXTENSION) -> dict[str, str]:
    out = {"Authorization": f"Bearer {key}"}
    if origin is not None:
        out["Origin"] = origin
    return out


def batch(n: int = 1, *, conv: str = DM, text: str = "On se voit à 14 h ?") -> dict:
    now = int(time.time() * 1000)
    return {"self": {"id": "8:orgid:adrien", "name": "Adrien"},
            "conversations": [{"id": conv, "title": "", "kind": "dm"}],
            "messages": [{"id": f"{1_759_000_000_000 + i}", "conv": conv, "author": "Alice", "author_id": "8:orgid:a",
                          "time": now - i, "text": text, "own": False, "mentions_me": False} for i in range(n)]}


def new_key(client, live) -> str:
    return client.portal.call(live.teams.new_key, "test")


def test_the_extension_gets_in_only_with_its_key_and_from_an_extension(world):  # noqa: F811
    client, live, _ = world
    assert client.post("/api/teams/inbox", json=batch(), headers=headers("mtk_rien")).status_code == 401
    key = new_key(client, live)
    ok = client.post("/api/teams/inbox", json=batch(2), headers=headers(key))
    assert ok.status_code == 202 and ok.headers["cache-control"] == "no-store"
    assert ok.json() == {"ok": True, "accepted": 2, "known": 0}
    again = client.post("/api/teams/inbox", json=batch(2), headers=headers(key, origin=None))  # aucune origine : passe
    assert again.status_code == 202 and again.json()["known"] == 2
    missing = client.post("/api/teams/inbox", json=batch(), headers={"Origin": EXTENSION})
    wrong = client.post("/api/teams/inbox", json=batch(), headers=headers(key[:-2] + "xy"))
    assert missing.status_code == wrong.status_code == 401 and missing.json() == wrong.json()
    foreign = client.post("/api/teams/inbox", json=batch(), headers=headers(key, origin="https://ailleurs.example"))
    assert foreign.status_code == 403
    # une nouvelle clé rend l'ancienne inutile ; retirée, plus rien ne passe
    newer = new_key(client, live)
    assert client.get("/api/teams/outbox", headers=headers(key)).status_code == 401
    assert client.get("/api/teams/outbox", headers=headers(newer)).status_code == 200
    client.portal.call(live.teams.revoke_key, "test")
    assert client.get("/api/teams/outbox", headers=headers(newer)).status_code == 401
    # la clé en clair n'est gardée nulle part dans les réglages
    stored = str(client.portal.call(live.kernel.mind.store.query_mind, "SELECT value FROM settings", ()))
    assert key not in stored and newer not in stored


def test_a_bad_batch_is_refused_before_anything_is_stored(world):  # noqa: F811
    client, live, _ = world
    key = new_key(client, live)
    store = live.kernel.ports["teams"]
    bad_conv = batch(conv="<script>")
    assert client.post("/api/teams/inbox", json=bad_conv, headers=headers(key)).status_code == 400
    future = batch()
    future["messages"][0]["time"] = int(time.time() * 1000) + 3 * 86_400_000
    assert client.post("/api/teams/inbox", json=future, headers=headers(key)).status_code == 400
    assert client.post("/api/teams/inbox", content=b"[1, 2]", headers=headers(key)).status_code == 400
    assert client.post("/api/teams/inbox", content=b"{" * 100_000, headers=headers(key)).status_code == 400
    huge = client.post("/api/teams/inbox", content=b" " * (600 * 1024), headers=headers(key))
    assert huge.status_code == 413
    assert client.portal.call(store.conversations, 10) == [] and not client.portal.call(store.configured)
    # Teams désactivé : refusé (403), rien de rangé
    client.portal.call(live.settings.save_teams, TeamsConfig(enabled=False))
    assert client.post("/api/teams/inbox", json=batch(), headers=headers(key)).status_code == 403
    assert not client.portal.call(store.configured)


def test_the_outbox_gives_what_must_leave_and_acks_replay_safely(world):  # noqa: F811
    client, live, _ = world
    key = new_key(client, live)
    assert client.post("/api/teams/inbox", json=batch(), headers=headers(key)).status_code == 202
    store = live.kernel.ports["teams"]
    # le magasin lit ses réglages (la signature) dans la base : depuis le fil du serveur
    draft = client.portal.call(store.save_draft, Draft(id="", conversation=DM, body="Oui, 14 h me va."))
    now = time.time_ns() // 1000
    shown = client.portal.call(store.preview, draft.id)
    assert client.portal.call(lambda: store.enqueue(draft.id, mode="draft", digest=shown.digest,
                                                    expires_at=now + 3_600_000_000, now=now)) == ""
    [item] = client.get("/api/teams/outbox", headers=headers(key)).json()["items"]
    assert item["id"] == draft.id and item["mode"] == "draft" and item["status"] == "queued"
    assert item["text"] == "Oui, 14 h me va." and item["title"] == "Alice"

    def ack(result, **more):
        return client.post(f"/api/teams/outbox/{draft.id}", json={"result": result, **more}, headers=headers(key))

    placed = ack("placed")
    assert placed.status_code == 200 and placed.json()["status"] == "pose"
    assert ack("placed").status_code == 200  # rejoué : rien ne change
    sent = ack("sent", text="Oui, 14 h me va très bien.")
    assert sent.status_code == 200 and sent.json()["status"] == "parti" and client.portal.call(store.draft, draft.id).edited
    assert ack("placed").status_code == 409  # posé, après être parti : impossible
    assert ack("sent").status_code == 200
    assert client.get("/api/teams/outbox", headers=headers(key)).json()["items"] == []
    assert client.post("/api/teams/outbox/t000000000000", json={"result": "sent"},
                       headers=headers(key)).status_code == 404
    assert client.post(f"/api/teams/outbox/{draft.id}", json={"result": "envoyé"},
                       headers=headers(key)).status_code == 400
