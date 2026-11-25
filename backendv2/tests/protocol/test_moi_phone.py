"""L'API par personne, Téléphone (ADR 0187, 0190) : à travers le vrai serveur et la vraie porte du téléphone. Une
personne ne lit que les messages que son téléphone a poussés, rangés par conversation, sa propre position, ses
propres téléphones — qu'elle révoque elle-même — et télécharge l'application derrière sa connexion. Chaque
conversation dit la réponse de Mika qui y compte : en chemin, ou partie (et son sort) tant qu'aucun message n'a suivi."""

from __future__ import annotations

from mika.app.domains.phone.api import _her
from mika.contracts import phone as c
from mika.kernel.events import Content, Origin
from mika.plugins.phone import LEVEL, Msg, Offer
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


def draft(ctx, text: str) -> int:  # noqa: F811
    """Mika prépare une réponse au dernier message de la conversation (comme ``phone_draft``) : son ``seq``."""
    async def write() -> int:
        mind = ctx.live.kernel.mind
        m = max(mind.frame().state(c.OWNER).messages.values(), key=lambda m: m.seq)
        commit = await mind.append([c.DRAFTED.draft(
            handle=m.handle, person=m.person, thread=m.thread, source=m.source, reply_to=m.seq,
            body=Content.of(text, level=LEVEL))], emitter=c.OWNER, correlation="test-reponse", origin=Origin.TOOL)
        return commit.seqs[-1]

    return ctx.call(write)


def her_of(ctx, phone) -> dict | None:  # noqa: F811
    [conv] = ctx.client.get(API + "/phone/conversations", headers=bearer(phone)).json()["items"]
    return conv["her"]


def later(ctx, text: str, n: int) -> dict:  # noqa: F811
    """Un message de Léa, écrit maintenant (après ce que Mika a proposé)."""
    now_ms = ctx.live.kernel.mind.clock.now() // 1000
    return {"messages": [{"id": f"{100 + n:032x}", "app": "whatsapp", "thread": THREAD, "sender": LEA, "name": "Léa",
                          "text": text, "time": now_ms + n}]}


def test_her_reply_that_left_shows_until_a_new_message_comes(ctx) -> None:  # noqa: F811
    """Sa réponse partie se lit dans la liste, avec son sort et quand (audit du 2026-11-05, F3-01) ; un message reçu
    ensuite la rend caduque. Une réponse en chemin, elle, reste : elle attend le geste."""
    adrien = owner(ctx)
    assert inbox(ctx, adrien, lot("Tu viens dimanche ?")).status_code == 200
    first = draft(ctx, "Oui, j'arrive vers 20 h !")
    assert her_of(ctx, adrien) == {"state": c.PREPARED, "id": first, "decided_at": 0}
    settled = ctx.client.post("/api/phone/settled", json={"items": [{"id": first, "result": "sent"}]},
                              headers=bearer(adrien))
    assert settled.status_code == 200 and settled.json()["settled"] == 1
    her = her_of(ctx, adrien)
    assert her is not None and her["state"] == "sent" and her["id"] == first and her["decided_at"] > 0
    assert inbox(ctx, adrien, later(ctx, "Super, à tout à l'heure", 1)).status_code == 200
    assert her_of(ctx, adrien) is None  # une réponse à un message d'avant n'est plus une nouvelle
    second = draft(ctx, "À tout !")
    assert inbox(ctx, adrien, later(ctx, "Tu prends du pain ?", 2)).status_code == 200
    assert her_of(ctx, adrien) == {"state": c.PREPARED, "id": second, "decided_at": 0}  # elle attend ton geste


def test_an_offered_reply_stays_after_a_new_message_and_a_settled_one_goes() -> None:
    """La règle seule : offerte, elle reste quoi qu'il arrive ; réglée, elle suit le dernier message reçu ou s'efface ;
    la plus récente compte."""
    msg = Msg(5, "h", "p", "t", "whatsapp", "s", False, False, at=2_000)
    old = Offer(3, "h", "p", "t", "whatsapp", 2, "", at=1_000, state="sent", decided_at=1_500_000)
    waiting = Offer(4, "h", "p", "t", "whatsapp", 2, "", at=1_100, state=c.OFFERED)
    assert _her([old, waiting], msg) == {"state": c.OFFERED, "id": 4, "decided_at": 0}
    assert _her([old], msg) is None
    assert _her([old], None) == {"state": "sent", "id": 3, "decided_at": 1_500}
    newer = Offer(6, "h", "p", "t", "whatsapp", 5, "", at=3_000, state="failed", decided_at=4_000_000)
    assert _her([newer, old], msg) == {"state": "failed", "id": 6, "decided_at": 4_000}
