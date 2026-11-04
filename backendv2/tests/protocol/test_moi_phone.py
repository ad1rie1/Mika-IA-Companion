"""L'API par personne, Téléphone (ADR 0187, 0190) : à travers le vrai serveur et la vraie porte du téléphone. Une
personne ne lit que les messages que son téléphone a poussés, rangés par conversation, sa propre position, ses
propres téléphones — qu'elle révoque elle-même — et télécharge l'application derrière sa connexion."""

from __future__ import annotations

from tests.protocol.test_mobile_push import PASSWORD, ctx  # noqa: F401 — la fixture
from tests.protocol.test_phone_web import LEA, THREAD, inbox, lot, owner

API = "/api/moi"


def bearer(phone) -> dict[str, str]:
    return {"authorization": f"Bearer {phone.token}"}


def session(ctx, name: str) -> dict[str, str]:  # noqa: F811
    """Une session de navigateur pour ce compte ; rend l'en-tête CSRF à joindre aux écritures."""
    ctx.client.get("/auth/whoami")
    headers = {"X-CSRFToken": ctx.client.cookies.get("csrftoken")}
    r = ctx.client.post("/auth/login", json={"username": name, "password": PASSWORD}, headers=headers)
    assert r.status_code == 200, r.text
    return headers


def test_her_conversations_and_threads_come_from_her_phone(ctx) -> None:  # noqa: F811
    adrien = owner(ctx)
    assert inbox(ctx, adrien, lot("Tu viens dimanche ?", "Départ 8 h 30", "Dis-moi vite")).status_code == 200
    got = ctx.client.get(API + "/phone/conversations", headers=bearer(adrien)).json()["items"]
    assert len(got) == 1
    conv = got[0]
    assert conv["key"] == f"whatsapp|{THREAD}" and conv["app"] == "whatsapp" and conv["title"] == "Léa"
    assert conv["count"] == 3 and conv["last"]["text"] == "Dis-moi vite" and conv["her"] is None
    thread = ctx.client.get(API + f"/phone/thread?conversation=whatsapp|{THREAD}", headers=bearer(adrien)).json()
    assert [m["text"] for m in thread["messages"]] == ["Tu viens dimanche ?", "Départ 8 h 30", "Dis-moi vite"]
    assert thread["messages"][0]["sender"] == "Léa" and not thread["messages"][0]["own"] and thread["offers"] == []
    assert ctx.client.get(API + "/phone/thread?conversation=whatsapp|ailleurs", headers=bearer(adrien)
                          ).status_code == 404
    assert ctx.client.get(API, headers=bearer(adrien)).json()["counts"]["phone"] == 0

    bea = ctx.phone("bea")  # un autre compte : rien de ce téléphone n'est à elle
    assert ctx.client.get(API + "/phone/conversations", headers=bearer(bea)).json()["items"] == []
    assert ctx.client.get(API + f"/phone/thread?conversation=whatsapp|{THREAD}", headers=bearer(bea)
                          ).status_code == 404
    assert LEA not in ctx.client.get(API + "/phone/conversations", headers=bearer(bea)).text


def test_her_position_is_hers_only(ctx) -> None:  # noqa: F811
    adrien, bea = owner(ctx), ctx.phone("bea")
    assert ctx.client.get(API + "/phone/position", headers=bearer(adrien)).json() == {"known": False}
    ctx.call(ctx.live.port.locate, adrien.handle, lat=50.6365, lon=3.0635, accuracy_m=12,
             label="rue Nationale, Lille", age_ms=0)
    where = ctx.client.get(API + "/phone/position", headers=bearer(adrien)).json()
    assert where["known"] and where["label"] == "rue Nationale, Lille" and where["accuracy_m"] == 12
    assert abs(where["coords"]["lat"] - 50.6365) < 1e-6 and where["at"] > 0
    assert ctx.client.get(API + "/phone/position", headers=bearer(bea)).json() == {"known": False}


def test_she_sees_and_revokes_her_own_phones(ctx) -> None:  # noqa: F811
    adrien = owner(ctx)
    other = ctx.phone("bea")
    assert inbox(ctx, adrien, lot("coucou")).status_code == 200
    listed = ctx.client.get(API + "/phone/phones", headers=bearer(adrien)).json()
    assert [p["id"] for p in listed["items"]] == [adrien.token_id] and not listed["items"][0]["revoked"]
    assert listed["items"][0]["last_used"] > 0  # vu quand il a poussé ses messages
    assert listed["apk"] is False
    csrf = session(ctx, "adrien")
    assert ctx.client.post(API + "/phone/revoke", json={"id": other.token_id}, headers=csrf).status_code == 404
    assert ctx.client.post(API + "/phone/revoke", json={"id": adrien.token_id}).status_code == 403  # sans CSRF
    r = ctx.client.post(API + "/phone/revoke", json={"id": adrien.token_id}, headers=csrf)
    assert r.status_code == 200, r.text
    assert ctx.client.get(API + "/phone/phones").json()["items"][0]["revoked"]
    assert ctx.client.post(API + "/phone/revoke", json={"id": adrien.token_id}, headers=csrf).status_code == 409
    assert inbox(ctx, adrien, lot("encore ?")).status_code == 401  # révoqué : son application n'entre plus
    assert ctx.client.get(API + "/phone/phones", headers=bearer(other)).json()["items"][0]["id"] == other.token_id


def test_the_application_is_downloaded_behind_the_login(ctx) -> None:  # noqa: F811
    adrien = owner(ctx)
    assert ctx.client.get(API + "/phone/apk").status_code == 401
    assert ctx.client.get(API + "/phone/apk", headers=bearer(adrien)).status_code == 404  # pas encore déposée
    target = ctx.live.data / "telephone" / "mika.apk"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"PK\x03\x04 une application")
    got = ctx.client.get(API + "/phone/apk", headers=bearer(adrien))
    assert got.status_code == 200 and got.content.startswith(b"PK")
    assert got.headers["content-type"] == "application/vnd.android.package-archive"
    assert 'filename="mika.apk"' in got.headers["content-disposition"]
    assert ctx.client.get(API + "/phone/phones", headers=bearer(adrien)).json()["apk"] is True
