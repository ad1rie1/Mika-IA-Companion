"""L'API par personne, ses partages (ADR 0188) : le propriétaire partage une boîte, un compte Teams, un service ; la
personne le voit dans son propre Mika, à son nom, et n'y fait que ce que son niveau ouvre ; retirer le partage le lui
retire."""

from __future__ import annotations

import json

from mika.adapters.mail.config import MailAccount, MailConfig
from mika.contracts import email as email_c
from mika.contracts import runtime as rt
from mika.kernel.events import Content
from mika.ports.mail import Draft as MailDraft
from tests.fixtures.courrier import mailbox
from tests.protocol.test_moi_mail import API, PROJET, append, journal, login, post, second_person
from tests.protocol.test_moi_mcp import SERVICE, servers
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def share(client, kind: str, key: str, person: str, level: str) -> object:
    return post(client, "/shares/set", {"kind": kind, "key": key, "person": person, "level": level})


def test_a_shared_box_shows_in_her_mika_and_opens_only_her_level(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    live.kernel.ports["mail"] = mailbox(3)
    # les boîtes du courrier simulé, rangées aussi dans les réglages (le vrai port les y lit) : leurs partages s'y
    # écrivent
    client.portal.call(live.settings.save_email, MailConfig(accounts={
        "perso": MailAccount(label="Personnel", address="adrien@example.test"),
        "pro": MailAccount(label="Atelier", address="atelier@example.test")}))
    lea = second_person(client, live)
    people = client.get(API + "/people").json()["items"]
    assert [p["person"] for p in people] == [lea]  # tout le monde sauf toi
    assert share(client, "mail", "pro", "inconnue", "lire").status_code == 400
    assert share(client, "mail", "pro", lea, "tout").status_code == 400
    assert share(client, "mail", "pro", lea, "lire").status_code == 200
    given = client.get(API + "/shares").json()["given"]
    assert given == [{"kind": "mail", "key": "pro", "title": "Atelier", "person": lea, "name": "Léa Martin",
                      "level": "lire"}]

    login(client, "lea")
    boxes = client.get(API + "/mail/boxes").json()["boxes"]
    assert [(b["key"], b["level"]) for b in boxes] == [("pro", "lire")] and boxes[0]["owner_name"] == "adrien"
    assert client.get(API + "/shares").json()["received"][0]["level"] == "lire"
    assert client.get(API + f"/mail/message?ref={PROJET}").status_code == 200  # elle la lit
    assert client.get(API + "/mail/drafts").json()["items"] == []  # ses brouillons pour Adrien : pas pour une lectrice
    assert client.get(API).json()["counts"]["mail"] >= 0
    reply = {"ref": PROJET, "to": "lea@example.test", "subject": "Re", "body": "Merci"}
    assert post(client, "/mail/reply", reply).status_code == 403  # sans y écrire
    assert post(client, "/mail/tidy", {"refs": [PROJET], "gesture": "read"}).status_code == 403  # ni la ranger
    assert post(client, "/mail/prefill", {"ref": PROJET}).status_code == 403
    assert client.get(API + "/mail/box?box=pro").status_code == 403  # ni la régler
    assert share(client, "mail", "pro", "user_1", "servir").status_code == 403  # ni la repartager

    login(client, "adrien")
    assert share(client, "mail", "pro", lea, "preparer").status_code == 200
    login(client, "lea")
    asked = post(client, "/mail/prefill", {"ref": PROJET})
    assert asked.status_code == 200, asked.text
    assert journal(live, email_c.DRAFT_ASKED)[-1].data.by == lea
    assert post(client, "/mail/reply", reply).status_code == 403
    box = live.kernel.ports["mail"]
    draft = box.save_draft(MailDraft(id="", account="pro", to="lea@example.test", subject="Re", body="Merci",
                                     reply_to=PROJET))
    append(client, live, [rt.EFFECT_PROPOSED.draft(
        capability="email.send", owner="email", summary=Content.of("Répondre"), context="email",
        args_json=json.dumps({"draft": draft.id, "account": "pro", "mail": PROJET}))])
    assert post(client, "/mail/draft/send", {"id": draft.id}).status_code == 403  # c'est son propriétaire qui décide

    login(client, "adrien")
    assert share(client, "mail", "pro", lea, "servir").status_code == 200
    login(client, "lea")
    assert post(client, "/mail/reply", reply).status_code == 200  # s'en servir : comme le propriétaire

    login(client, "adrien")
    assert share(client, "mail", "pro", lea, "").status_code == 200
    login(client, "lea")
    assert client.get(API + "/mail/boxes").json()["boxes"] == []
    assert client.get(API + f"/mail/message?ref={PROJET}").status_code == 404


def test_a_shared_service_gets_her_an_access_line(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    lea = second_person(client, live)
    assert post(client, "/mcp/plug", SERVICE).status_code == 200
    assert share(client, "mcp", "factures", lea, "preparer").status_code == 400  # un service : lire ou s'en servir
    assert share(client, "mcp", "factures", lea, "lire").status_code == 200
    lines = servers(client, live)["factures"].access
    assert [tuple(a.who) for a in lines] == [("personne:user_1",), ("personne:" + lea,)]
    assert (lines[1].read, lines[1].act) == ("seule", "non")
    assert share(client, "mcp", "factures", lea, "servir").status_code == 200
    lines = servers(client, live)["factures"].access
    assert len(lines) == 2 and (lines[1].read, lines[1].act) == ("seule", "carte")
    login(client, "lea")
    received = client.get(API + "/shares").json()["received"]
    assert received == [{"kind": "mcp", "key": "factures", "title": "factures", "level": "servir",
                         "owner_name": "adrien"}]
    login(client, "adrien")
    assert share(client, "mcp", "factures", lea, "").status_code == 200
    assert [tuple(a.who) for a in servers(client, live)["factures"].access] == [("personne:user_1",)]


def test_a_share_to_a_closed_account_still_comes_off(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    client.portal.call(live.settings.save_email, MailConfig(accounts={
        "pro": MailAccount(label="Atelier", address="atelier@example.test")}))
    live.kernel.ports["mail"] = mailbox(1)
    lea = second_person(client, live)
    assert share(client, "mail", "pro", lea, "lire").status_code == 200
    account = next(a for a in client.portal.call(live.accounts.all) if a.username == "lea")
    client.portal.call(lambda: live.accounts.update(account.id, active=False))
    assert share(client, "mail", "pro", lea, "servir").status_code == 400  # plus à une personne sans compte actif
    assert share(client, "mail", "pro", lea, "").status_code == 200  # mais il se retire toujours
    assert client.get(API + "/shares").json()["given"] == []


def test_nothing_is_shared_with_yourself_nor_with_one_who_owns_it_already(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    client.portal.call(live.settings.save_email, MailConfig(accounts={
        "pro": MailAccount(label="Atelier", address="atelier@example.test")}))
    live.kernel.ports["mail"] = mailbox(1)
    lea = second_person(client, live)
    bea = client.portal.call(lambda: live.accounts.create("bea", "un-mot-de-passe-long", operator=True,
                                                          full_name="Béa Martin"))
    people = {p["person"]: p["owner"] for p in client.get(API + "/people").json()["items"]}
    assert people == {lea: False, bea.handle: True}
    assert share(client, "mail", "pro", "user_1", "lire").status_code == 400  # à toi-même
    assert share(client, "mail", "pro", bea.handle, "lire").status_code == 400  # « à toi » : déjà la sienne
    assert post(client, "/mcp/plug", SERVICE).status_code == 200
    assert share(client, "mcp", "factures", "user_1", "").status_code == 400  # ni retirer sa propre ligne
    assert [tuple(a.who) for a in servers(client, live)["factures"].access] == [("personne:user_1",)]
    assert share(client, "mcp", "factures", lea, "lire").status_code == 200
    login(client, "lea")  # un service qu'on te partage : refusé, comme une boîte (pas introuvable)
    assert share(client, "mcp", "factures", "user_1", "lire").status_code == 403
    assert share(client, "mcp", "inconnu", "user_1", "lire").status_code == 404


def test_a_writing_native_token_is_refused(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    origin = client.headers.pop("origin")  # sans Origin : un client natif
    try:
        r = client.post("/auth/token", json={"username": "adrien", "password": "un-mot-de-passe-long",
                                             "client": "screen"})
        token = r.json().get("token")
        assert token, r.text
        bearer = {"Authorization": f"Bearer {token}"}
        assert client.get(API, headers=bearer).status_code == 200  # il lit
        client.cookies.set("csrftoken", "forge")
        w = client.post(API + "/account/name", json={"name": "Pirate"}, headers={**bearer, "X-CSRFToken": "forge"})
        assert w.status_code == 403  # mais n'écrit pas, même avec un CSRF qu'il pose lui-même
    finally:
        client.headers["origin"] = origin
    assert client.get(API).json()["name"] != "Pirate"
