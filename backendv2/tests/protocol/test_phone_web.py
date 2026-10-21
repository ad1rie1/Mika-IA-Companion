"""Les messages du téléphone (ADR 0120), sur l'application réelle : ``/api/phone/inbox``, ``/api/phone/settled``,
et la réponse proposée scellée pour le téléphone.

- seule l'application du téléphone d'une propriétaire y entre : sans jeton, 401 ; un jeton d'écran, une ``Origin``
  ou un compte qui n'est pas propriétaire, 403 ; un corps illisible, 400 ; trop grand, 413 ;
- un lot admis s'écrit au journal, un message dédoublonné ;
- une réponse proposée part scellée à chaque téléphone du compte (``phone_draft``), même quand l'application est
  ouverte, et s'ouvre avec sa clé ;
- la console montre le téléphone de chaque personne, conversation par conversation, et l'onglet « Son téléphone »
  de sa fiche — seulement sur la fiche de qui en a montré.
"""

from __future__ import annotations

import html

from mika.adapters.push import seal
from mika.app.server import register_accounts
from mika.contracts import phone as c
from tests.protocol.test_mobile_push import KEY, PASSWORD, Phone, ctx  # noqa: F401 — la fixture
from tests.protocol.test_web import bootstrap

THREAD, LEA = "c3" * 16, "a1" * 16


def owner(ctx, name: str = "adrien") -> Phone:  # noqa: F811
    ctx.call(ctx.live.accounts.create, name, PASSWORD, operator=True)
    ctx.call(register_accounts, ctx.live.kernel, ctx.live.accounts)
    return ctx.phone(name)


def inbox(ctx, phone: Phone, body, **headers):  # noqa: F811
    return ctx.client.post("/api/phone/inbox", json=body, headers={"authorization": f"Bearer {phone.token}",
                                                                   **headers})


def lot(*texts: str) -> dict:
    return {"messages": [{"id": f"{n + 1:032x}", "app": "whatsapp", "thread": THREAD, "sender": LEA, "name": "Léa",
                          "text": text, "time": 1_760_950_000_000 + n} for n, text in enumerate(texts)]}


def test_only_the_phone_of_an_owner_gets_in(ctx) -> None:  # noqa: F811
    adrien = owner(ctx)
    assert inbox(ctx, Phone("mw_faux", 0, ""), lot("coucou")).status_code == 401
    assert inbox(ctx, adrien, lot("coucou"), origin="http://localhost:3000").status_code == 403
    assert inbox(ctx, ctx.phone("ecran", client="screen"), lot("coucou")).status_code == 403
    assert inbox(ctx, ctx.phone("bea"), lot("coucou")).status_code == 403  # pas une propriétaire
    bad = ctx.client.post("/api/phone/inbox", content=b"[1, 2]",
                          headers={"authorization": f"Bearer {adrien.token}"})
    assert bad.status_code == 400
    huge = ctx.client.post("/api/phone/inbox", content=b"{" + b" " * (3 * 1024 * 1024) + b"}",
                           headers={"authorization": f"Bearer {adrien.token}"})
    assert huge.status_code == 413
    r = inbox(ctx, adrien, lot("Tu viens samedi ?", "On sera chez Inès"))
    assert r.status_code == 200 and r.json() == {"ok": True, "accepted": 2, "known": 0, "dropped": 0}
    again = inbox(ctx, adrien, lot("Tu viens samedi ?"))
    assert again.json()["known"] == 1
    received = ctx.call(lambda: [e for e in ctx.live.kernel.mind.store.read() if e.type == c.RECEIVED.name])
    assert len(received) == 2
    settled = ctx.client.post("/api/phone/settled", json={"items": [{"id": 1, "result": "sent"}]},
                              headers={"authorization": f"Bearer {adrien.token}"})
    assert settled.status_code == 200 and settled.json() == {"ok": True, "settled": 0, "unknown": 1}


def test_a_proposed_reply_leaves_sealed_for_every_phone(ctx) -> None:  # noqa: F811
    adrien = owner(ctx)
    assert ctx.register(adrien, device="fcm-tel").status_code == 200
    desk = ctx.live.kernel.ports["phone"]
    sent = ctx.call(desk.offer, adrien.handle, {"id": 42, "app": "whatsapp", "thread": THREAD, "to": "Léa",
                                                "text": "Oui, j'arrive vers 20 h !", "exp": 1_760_957_200_000})
    ctx.call(ctx.live.hub.push.drain)
    assert sent == 1
    [(device, data)] = ctx.firebase.sent
    body = seal.unseal(seal.key_from(KEY), data)
    assert device == "fcm-tel" and body["t"] == seal.PHONE_DRAFT and body["id"] == 42
    assert body["thread"] == THREAD and body["to"] == "Léa" and body["text"] == "Oui, j'arrive vers 20 h !"
    assert body["exp"] == 1_760_957_200_000 and body["app"] == "whatsapp" and body["ts"] > 0


def test_a_long_reply_is_clipped_to_fit_firebase() -> None:
    body = seal.phone_payload(draft=1, app="whatsapp", thread=THREAD, to="Léa", text='"\n' * 3000,
                              expires_ms=1, ts_ms=1)
    assert len(seal._plain(body)) <= seal.PLAIN_MAX_BYTES and body["text"].endswith(seal.ELLIPSIS)


def test_the_console_shows_each_phone_conversation_by_conversation(ctx) -> None:  # noqa: F811
    """Messages du téléphone : le téléphone de chaque personne, ses conversations (un contact, un groupe) en bulles ;
    sur sa fiche, l'onglet « Son téléphone », qui n'apparaît pas sur la fiche de qui n'a rien montré."""
    bootstrap(ctx.client, "adrien", PASSWORD)
    adrien = ctx.phone("adrien")
    family = {"id": f"{9:032x}", "app": "whatsapp", "thread": "d4" * 16, "group": True, "title": "Famille",
              "sender": "b2" * 16, "name": "Maman", "text": "On mange à 20 h", "time": 1_760_950_000_100}
    r = inbox(ctx, adrien, {"messages": [*lot("Tu viens samedi ?", "On sera chez Inès")["messages"], family]})
    assert r.status_code == 200, r.text
    page = html.unescape(ctx.client.get("/inspecteur/sens/messages").text)
    assert "Le téléphone de" in page and page.count('<details class="senses-conv">') == 2
    assert all(part in page for part in ("Léa", "Tu viens samedi ?", "Famille", "groupe", "On mange à 20 h"))
    fiche = ctx.client.get(f"/inspecteur/fiche/person/{adrien.handle}")
    assert fiche.status_code == 200 and "onglet=telephone" in fiche.text
    tab = html.unescape(ctx.client.get(f"{fiche.url.path}?onglet=telephone").text)
    assert "Ses conversations" in tab and "On sera chez Inès" in tab and "Ses réponses proposées" in tab
    bea = ctx.phone("bea")
    other = ctx.client.get(f"/inspecteur/fiche/person/{bea.handle}")
    assert other.status_code == 200 and "onglet=telephone" not in other.text
