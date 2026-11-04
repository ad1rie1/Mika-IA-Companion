"""L'API par personne, Mail (ADR 0187, 0191) : à travers le vrai serveur, sur un courrier simulé. Une personne ne voit
que ses boîtes — les tiennes si elle est une de ses propriétaires, celles à son nom sinon — et rien de ce qui est
ailleurs n'existe pour elle (le même 404) ; ce qu'elle fait passe par les actions de la console, en son nom."""

from __future__ import annotations

import json

from mika.app.moi import PROBES
from mika.contracts import email as email_c
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.kernel.events import Content, Origin
from mika.plugins.email import EmailParams
from mika.ports.mail import Draft as MailDraft
from mika.ports.mail import File, Mail, Sent
from tests.fixtures.courrier import NOW, mailbox
from tests.protocol.test_web import bootstrap, csrf, world  # noqa: F401 — fixture partagée

API = "/api/moi"
PROJET = "pro:<projet@example.test>"


def with_mail(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    box = mailbox(5)
    live.kernel.ports["mail"] = box
    return client, live, box


def post(client, path: str, body: dict) -> object:
    return client.post(API + path, json=body, headers=csrf(client))


def append(client, live, drafts, emitter: str = "runtime") -> None:
    client.portal.call(lambda: live.kernel.mind.append(drafts, emitter=emitter, correlation="moi",
                                                       origin=Origin.EXTERNAL))


def journal(live, kind) -> list:
    mind = live.kernel.mind
    return [mind.decode(e) for e in mind.store.read() if e.type == kind.name]


def second_person(client, live, username: str = "lea") -> str:
    """Un deuxième compte, sans droits d'opérateur ; rend la clé de sa personne. La session reste la première."""
    account = client.portal.call(lambda: live.accounts.create(username, "un-mot-de-passe-long", operator=False,
                                                              full_name="Léa Martin"))
    return str(live.kernel.mind.frame().get(identity_c.PERSON(account.handle)) or account.handle)


def login(client, username: str) -> None:
    r = client.post("/auth/login", json={"username": username, "password": "un-mot-de-passe-long"},
                    headers=csrf(client))
    assert r.status_code == 200, r.text


def owners(client, live, **by_box: str) -> None:
    client.portal.call(live.kernel.set_params, "email", EmailParams(owners=by_box))


# ── qui ──


def test_it_needs_a_session_and_says_who_is_connected(world):  # noqa: F811
    client, live, _ = world
    assert client.get(API).status_code == 401
    assert client.get(API + "/mail/boxes").status_code == 401
    bootstrap(client)
    me = client.get(API).json()
    assert me["username"] == "adrien" and me["operator"] is True and me["owner"] is True
    assert me["handle"] == "user_1" and set(me["counts"]) == {"mail", "teams", "phone"}
    assert client.get(API).headers["cache-control"] == "no-store"


def test_writing_needs_the_csrf_token(world):  # noqa: F811
    client, _, _ = with_mail(world)
    r = client.post(API + "/mail/tidy", json={"refs": [PROJET], "gesture": "read"})
    assert r.status_code == 403 and "CSRF" in r.json()["error"]


# ── ses boîtes ──


def test_an_owner_sees_your_boxes_and_a_person_only_hers(world):  # noqa: F811
    client, live, box = with_mail(world)
    got = client.get(API + "/mail/boxes").json()
    assert [b["key"] for b in got["boxes"]] == ["perso", "pro"] and got["read_on_open"]
    pro = next(b for b in got["boxes"] if b["key"] == "pro")
    assert pro["level"] == "proprietaire" and pro["can_send"] and "Archives" in {f["name"] for f in pro["folders"]}

    lea = second_person(client, live)
    owners(client, live, pro="personne:" + lea)
    assert [b["key"] for b in client.get(API + "/mail/boxes").json()["boxes"]] == ["perso"]  # la sienne n'est plus à toi
    login(client, "lea")
    assert client.get(API).json()["owner"] is False
    assert [b["key"] for b in client.get(API + "/mail/boxes").json()["boxes"]] == ["pro"]
    listed = client.get(API + "/mail/messages").json()
    assert listed["total"] == 2 and {m["box"] for m in listed["items"]} == {"pro"}
    # le courrier d'une autre boîte n'existe pas pour elle : le même 404 qu'un mail inconnu
    perso = next(m.ref for m in box.inbox if m.account == "perso" and not m.seen)
    for path in (f"/mail/message?ref={perso}", "/mail/messages?box=perso", "/mail/sent?box=perso",
                 "/mail/message?ref=perso:<inconnu@x>"):
        r = client.get(API + path)
        assert r.status_code == 404 and r.json() == {"error": "Introuvable."}, path
    assert post(client, "/mail/reply", {"ref": perso, "to": "camille@example.test", "subject": "Re", "body": "x"}
                ).status_code == 404
    assert post(client, "/mail/tidy", {"refs": [perso], "gesture": "read"}).status_code == 404
    assert box.sent == [] and not box.cached_one(perso).seen


# ── lire ──


def test_a_list_pages_filters_and_says_what_she_did(world):  # noqa: F811
    client, live, box = with_mail(world)
    page = client.get(API + "/mail/messages?box=perso&folder=INBOX&size=2").json()
    assert page["total"] == 5 and len(page["items"]) == 2 and page["size"] == 2
    first = page["items"][0]
    assert first["from"] == {"name": "Camille", "address": "camille@example.test"} and first["box"] == "perso"
    assert first["date"] > 0 and first["snippet"].startswith("Bonjour Adrien") and first["her"] is None
    unread = client.get(API + "/mail/messages?box=perso&state=unread").json()
    assert unread["total"] == 3 and all(not m["seen"] for m in unread["items"])
    assert client.get(API + "/mail/messages?q=maquettes").json()["total"] == 1
    assert client.get(API + "/mail/messages?state=bof").status_code == 400

    # ce qu'elle a remarqué : son importance, la réponse attendue, sa lecture à part de la tienne
    append(client, live, [email_c.NOTICED.draft(
        source="email", kind="mail", summary=Content.of("Léa envoie les maquettes, retour attendu jeudi."),
        pertinence=0.9, sensitivity=1, bundle="email", mail=PROJET, sender="Léa Martin <lea@example.test>",
        address="lea@example.test", importance=0.9, needs_reply=True, account="pro", folder="INBOX")], "email")
    noticed = client.get(API + "/mail/messages?state=noticed").json()
    assert [m["ref"] for m in noticed["items"]] == [PROJET]
    her = noticed["items"][0]["her"]
    assert her["noticed"] and her["important"] and her["needs_reply"] and not her["read"]
    read = client.get(API + f"/mail/message?ref={PROJET}").json()
    assert read["her"]["summary"] == "Léa envoie les maquettes, retour attendu jeudi."
    assert "FIN DU MESSAGE LONG" in read["body"] and read["cc"] == [{"name": "", "address": "equipe@example.test"}]
    assert read["attachments"] == [{"part": "0", "name": "maquettes.pdf", "mime": "application/pdf", "size": 153600}]
    assert read["html"] and read["images"] == {"remote": True, "shown": False}


def test_an_html_mail_is_served_framed_and_a_file_as_a_download(world):  # noqa: F811
    client, _, box = with_mail(world)
    framed = client.get(API + f"/mail/frame?ref={PROJET}")
    assert framed.status_code == 200 and "Les maquettes sont prêtes" in framed.text
    assert "<script" not in framed.text and "tracker.example.test" not in framed.text  # rien qui agisse ou piste
    policy = framed.headers["content-security-policy"]
    assert "frame-ancestors 'self' http://localhost:3000" in policy and "img-src data:;" in policy
    shown = client.get(API + f"/mail/frame?ref={PROJET}&images=1")
    assert "tracker.example.test" in shown.text and "img-src data: https: http:;" in \
        shown.headers["content-security-policy"]
    plain = box.inbox[0].ref
    assert client.get(API + f"/mail/frame?ref={plain}").status_code == 404  # pas de HTML : rien à cadrer

    assert client.get(API + f"/mail/file?ref={PROJET}&part=0").status_code == 404  # plus sur le serveur
    box.files[(PROJET, "0")] = File("maquettes.pdf", "application/pdf", b"%PDF-1.4 maquettes")
    got = client.get(API + f"/mail/file?ref={PROJET}&part=0")
    assert got.status_code == 200 and got.headers["content-disposition"].startswith("attachment;")
    assert got.headers["x-content-type-options"] == "nosniff" and got.headers["content-type"] == "application/pdf"
    assert client.get(API + f"/mail/file?ref={PROJET}&part=3").status_code == 404


def test_contacts_and_sent_mails_are_those_of_her_boxes(world):  # noqa: F811
    client, live, _ = with_mail(world)
    contacts = client.get(API + "/mail/contacts?q=lea").json()["items"]
    assert [c["address"] for c in contacts] == ["lea@example.test"]
    sent = client.get(API + "/mail/sent").json()["items"]
    assert {s["box"] for s in sent} == {"pro", "perso"}
    owners(client, live, pro="personne:" + second_person(client, live))
    assert {s["box"] for s in client.get(API + "/mail/sent").json()["items"]} == {"perso"}


# ── écrire, ranger ──


def test_a_reply_leaves_at_once_in_her_name_and_she_knows(world):  # noqa: F811
    client, live, box = with_mail(world)
    r = post(client, "/mail/reply", {"ref": PROJET, "to": "lea@example.test", "subject": "Re: Maquettes",
                                     "body": "Merci, je regarde jeudi.", "quote": True, "nonce": "r1"})
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert len(box.sent) == 1 and box.sent[0][0] == "lea@example.test"
    known = journal(live, email_c.SENT)
    assert len(known) == 1 and known[0].data.by == "user_1" and known[0].data.in_reply_to == PROJET
    again = post(client, "/mail/reply", {"ref": PROJET, "to": "lea@example.test", "subject": "Re: Maquettes",
                                         "body": "Merci, je regarde jeudi.", "quote": True, "nonce": "r1"})
    assert again.json()["deduped"] and len(box.sent) == 1  # un double clic ne renvoie pas


def test_a_new_mail_needs_a_box_that_sends_and_valid_addresses(world):  # noqa: F811
    client, _, box = with_mail(world)
    bad = post(client, "/mail/send", {"box": "pro", "to": "pas une adresse", "subject": "Bonjour", "body": "Texte"})
    assert bad.status_code in (400, 409) and box.sent == []
    ok = post(client, "/mail/send", {"box": "pro", "to": "lea@example.test", "subject": "Bonjour", "body": "Texte"})
    assert ok.status_code == 200, ok.text
    assert box.sent and box.sent[-1][0] == "lea@example.test"
    assert post(client, "/mail/send", {"box": "ailleurs", "to": "lea@example.test", "subject": "x", "body": "x"}
                ).status_code == 404


def test_tidying_marks_on_the_server(world):  # noqa: F811
    client, _, box = with_mail(world)
    unread = [m.ref for m in box.inbox if m.account == "perso" and not m.seen]
    r = post(client, "/mail/tidy", {"refs": unread[:2], "gesture": "read"})
    assert r.status_code == 200, r.text
    assert all(box.cached_one(ref).seen for ref in unread[:2]) and not box.cached_one(unread[2]).seen
    assert post(client, "/mail/tidy", {"refs": unread[:1], "gesture": "brûler"}).status_code == 400


# ── ses brouillons ──


def propose(client, live, box, **more) -> str:
    draft = box.save_draft(MailDraft(id="", account="pro", to="lea@example.test", subject="Re: Maquettes",
                                     body="Merci Léa, retour jeudi.", reply_to=PROJET, **more))
    append(client, live, [rt.EFFECT_PROPOSED.draft(
        capability="email.send", owner="email", summary=Content.of("Répondre à Léa"), context="email",
        args_json=json.dumps({"draft": draft.id, "account": "pro", "mail": PROJET}))])
    return draft.id


def test_her_drafts_are_read_where_they_will_leave_and_decided_there(world):  # noqa: F811
    client, live, box = with_mail(world)
    first = propose(client, live, box)
    items = client.get(API + "/mail/drafts").json()["items"]
    assert [d["id"] for d in items] == [first]
    d = items[0]
    assert d["state"] == "attend" and d["preview"]["text"] and d["preview"]["digest"]
    assert d["original"] == {"subject": "Maquettes du projet · retour pour jeudi", "from": "Léa Martin"}
    assert client.get(API + "/mail/messages?box=pro").json()["items"][0]["her"]["draft"] == first

    refused = post(client, "/mail/draft/refuse", {"id": first, "note": "trop sec"})
    assert refused.status_code == 200, refused.text
    assert client.get(API + "/mail/drafts").json()["items"][0]["state"] == "refuse"
    assert post(client, "/mail/draft/refuse", {"id": first}).status_code == 409  # plus rien à décider

    second = propose(client, live, box)
    seen = next(d for d in client.get(API + "/mail/drafts").json()["items"] if d["id"] == second)["preview"]["digest"]
    sent = post(client, "/mail/draft/send", {"id": second, "seen": seen})
    assert sent.status_code == 200, sent.text
    assert post(client, "/mail/draft/send", {"id": "inconnu"}).status_code == 404


def test_prefill_asks_her_once(world):  # noqa: F811
    client, live, box = with_mail(world)
    r = post(client, "/mail/prefill", {"ref": PROJET, "instruction": "dis que jeudi me va"})
    assert r.status_code == 200 and r.json()["asked"], r.text
    asked = journal(live, email_c.DRAFT_ASKED)
    assert len(asked) == 1 and asked[0].data.by == "user_1" and asked[0].data.mail == PROJET
    again = post(client, "/mail/prefill", {"ref": PROJET}).json()
    assert again["asked"] and again["message"] == "Elle y travaille déjà." and len(journal(live, email_c.DRAFT_ASKED)) == 1
    waiting = propose(client, live, box)
    assert post(client, "/mail/prefill", {"ref": PROJET}).json()["draft"] == waiting  # la saisie reprend le sien


def test_replying_yourself_withdraws_her_waiting_draft_for_that_mail(world):  # noqa: F811
    client, live, box = with_mail(world)
    waiting = propose(client, live, box)
    r = post(client, "/mail/reply", {"ref": PROJET, "to": "lea@example.test", "subject": "Re: Maquettes",
                                     "body": "Je réponds moi-même.", "quote": False})
    assert r.status_code == 200, r.text
    states = {d["id"]: d["state"] for d in client.get(API + "/mail/drafts").json()["items"]}
    assert states[waiting] == "refuse"  # rien ne partira deux fois
    assert client.get(API).json()["counts"]["mail"] == sum(1 for m in box.inbox if not m.seen and m.folder == "INBOX")


def test_whoever_replies_by_hand_withdraws_her_waiting_draft(world):  # noqa: F811
    client, live, box = with_mail(world)
    waiting = propose(client, live, box)
    lea = second_person(client, live)
    client.portal.call(live.kernel.set_params, "email", EmailParams(shares={"pro": {"personne:" + lea: "servir"}}))
    login(client, "lea")  # elle s'en sert : elle répond comme son propriétaire
    r = post(client, "/mail/reply", {"ref": PROJET, "to": "lea@example.test", "subject": "Re: Maquettes",
                                     "body": "Je m'en occupe.", "quote": False})
    assert r.status_code == 200, r.text
    login(client, "adrien")
    decided = {d["id"]: d for d in client.get(API + "/mail/drafts").json()["items"]}
    assert decided[waiting]["state"] == "refuse" and decided[waiting]["by"] == lea  # rien ne part deux fois


def test_a_received_copy_of_your_own_mail_is_replied_to(world):  # noqa: F811
    client, _, box = with_mail(world)
    # une copie à soi (en copie cachée, un dossier « Envoyés » relevé) : le même mail, reçu et parti à la fois
    box.outgoing.append(Sent("<projet@example.test>", "lea@example.test", "Maquettes", "…", 0, account="pro"))
    assert box.sent_mail(PROJET) is not None and box.cached_one(PROJET) is not None
    shown = client.get(API + f"/mail/message?ref={PROJET}").json()
    assert shown["sent"] and shown["received"]  # le client y offre « Répondre »
    r = post(client, "/mail/reply", {"ref": PROJET, "to": "lea@example.test", "subject": "Re: Maquettes",
                                     "body": "Et j'ajoute ceci.", "quote": False})
    assert r.status_code == 200, r.text
    # mais elle ne prépare pas de réponse à un mail parti de ta boîte (le client ne l'offre pas)
    asked = post(client, "/mail/prefill", {"ref": PROJET})
    assert asked.status_code == 409 and asked.json()["error"] == "Ce mail est parti de ta boîte : elle n'y prépare pas de réponse."


def test_a_mail_kept_only_in_sent_left_your_box_and_is_not_replied_to(world):  # noqa: F811
    client, _, box = with_mail(world)
    # écrit depuis un autre client : sa copie est rangée dans « Envoyés », sans envoi qu'elle sache
    box.deliver(Mail("<ailleurs@example.test>", "Adrien <atelier@example.test>", "atelier@example.test", "Devis signé",
                     NOW, "Le voici.", account="pro", to="lea@example.test", folder="Envoyés"))
    ref = "pro:<ailleurs@example.test>"
    assert box.sent_mail(ref) is None and box.cached_one(ref) is not None
    shown = client.get(API + f"/mail/message?ref={ref}").json()
    assert shown["sent"] and not shown["received"]  # parti de ta boîte, sans copie reçue
    r = post(client, "/mail/reply", {"ref": ref, "to": "lea@example.test", "subject": "Re: Devis", "body": "x"})
    assert r.status_code == 409 and box.sent == []  # on le transfère
    assert post(client, "/mail/prefill", {"ref": ref}).status_code == 409


def test_the_list_says_what_she_thinks_awaits_a_reply(world):  # noqa: F811
    client, live, _ = with_mail(world)
    append(client, live, [email_c.NOTICED.draft(
        source="email", kind="mail", summary=Content.of("Léa attend un retour."), pertinence=0.9, sensitivity=1,
        bundle="email", mail=PROJET, sender="Léa Martin <lea@example.test>", address="lea@example.test",
        importance=0.4, needs_reply=True, account="pro", folder="INBOX")], "email")
    got = client.get(API + "/mail/messages?state=needs_reply").json()
    assert [m["ref"] for m in got["items"]] == [PROJET] and got["items"][0]["her"]["needs_reply"]


def test_a_sent_mail_is_never_replied_to_and_a_too_long_field_is_refused(world):  # noqa: F811
    client, _, box = with_mail(world)
    sent = box.outgoing[0].ref
    assert client.get(API + f"/mail/message?ref={sent}").json()["sent"]
    r = post(client, "/mail/reply", {"ref": sent, "to": "lea@example.test", "subject": "Re", "body": "x"})
    assert r.status_code == 409 and box.sent == []  # un envoi n'a pas de boîte où répondre
    long = post(client, "/mail/send", {"box": "pro", "to": "lea@example.test", "subject": "x" * 201, "body": "Texte"})
    assert long.status_code == 400 and long.json()["fields"] == {"subject": "200 caractères au plus"}
    assert box.sent == []  # jamais coupé : refusé
    both = client.get(API + "/mail/sent").json()["items"]
    assert {s["box"] for s in both} == {"pro", "perso"}


def test_always_showing_a_senders_images_is_for_her_owners_only(world):  # noqa: F811
    client, live, _ = with_mail(world)
    lea = second_person(client, live)
    owners(client, live, pro="personne:" + lea)
    login(client, "lea")
    r = post(client, "/mail/images", {"ref": PROJET, "shown": True})
    assert r.status_code == 403  # le choix vaut pour tout le serveur : l'affaire de ses propriétaires
    assert client.get(API + f"/mail/message?ref={PROJET}").json()["images"]["shown"] is False
    assert "tracker.example.test" in client.get(API + f"/mail/frame?ref={PROJET}&images=1").text  # cette fois, oui


def test_polling_is_bounded_per_account(world):  # noqa: F811
    client, _, _ = with_mail(world)
    for _ in range(PROBES[0]):  # chaque relève fait joindre ses serveurs : bornée par compte
        assert post(client, "/mail/poll", {"box": "pro"}).status_code != 429
    assert post(client, "/mail/poll", {"box": "pro"}).status_code == 429


def test_a_mail_says_whether_it_left_your_box_and_whether_a_copy_came_back(world):  # noqa: F811
    client, _, box = with_mail(world)
    gone = client.get(API + f"/mail/message?ref={box.outgoing[0].ref}").json()
    assert gone["sent"] and not gone["received"]  # parti, sans copie reçue : on le transfère
    got = client.get(API + f"/mail/message?ref={PROJET}").json()
    assert not got["sent"] and got["received"]
    shown = {b["key"]: b["common"] for b in client.get(API + "/mail/boxes").json()["boxes"]}
    assert shown == {"perso": True, "pro": True}  # « à toi » : communes à ses propriétaires
