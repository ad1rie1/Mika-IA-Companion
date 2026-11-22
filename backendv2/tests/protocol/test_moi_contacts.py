"""L'API par personne, Contacts (ADR 0298) : à travers le vrai serveur. Chacune ne voit que ses contacts — ceux de ses
comptes, de ceux qu'on lui partage, de son téléphone, de ce qu'elle a raconté, et ceux d'un compte qui n'est à
personne —, jamais de qui d'autre ils sont le contact, ni la valeur d'une clé du téléphone ou d'un nom raconté ; un
contact d'une autre n'existe pas (le même 404) ; elle n'oublie que ce qui ne vient que de ses comptes."""

from __future__ import annotations

from mika.adapters.teams import TeamsAccount, TeamsConfig
from mika.contracts import runtime as rt
from mika.plugins.email import EmailParams
from mika.ports.contacts import (
    COMPANY,
    EMAIL,
    MAIL,
    PHONE,
    PHONE_APP,
    PHONE_SOURCE,
    TEAMS,
    TEAMS_ID,
    TOLD,
    TOLD_NAME,
    Observation,
)
from mika.ports.mail import AccountInfo, Mail
from mika.ports.teams import InboxBatch, InboxConversation, InboxMessage, conversation_key
from mika.sim.outside import FakeMail
from tests.fixtures.courrier import NOW, PERSO, PRO
from tests.protocol.test_moi_mail import API, journal, login, post, second_person
from tests.protocol.test_now_page import chat
from tests.protocol.test_web import bootstrap, csrf, world  # noqa: F401 — fixture partagée

HOUR = 3_600_000_000
HERS = AccountInfo("siens", "Mika", "mika@example.test", ready=True, can_send=True)
ALICE = "8:orgid:a"
DM = "19:alice_adrien@unq.gbl.spaces"
#: son tête-à-tête avec Adrien, dans le compte Teams « equipe »
ALICE_DM = conversation_key("equipe", DM)
DIGEST = "abc123def"
TOLD_KEY = "name:p1:ines"


def seed(world):  # noqa: F811
    """Adrien (opératrice, une des propriétaires) : le compte Teams « Équipe » et la boîte « Personnel » sont à
    lui ; « Atelier » est à Léa ; « Mika » est à elle (à tout le monde). Alice (Teams, son profil : e-mail, numéro,
    Nordis), Bob (vu chez Adrien comme chez Léa, sous deux noms), Camille (chez Léa), G. Rousseau (dans la boîte de
    Mika), Maman (le WhatsApp d'Adrien), Inès (qu'Adrien lui a racontée), Léa (qui lui parle : reliée), et la fiche
    d'Adrien lui-même."""
    client, live, _ = world
    bootstrap(client)
    adrien = client.get(API).json()["person"]
    lea = second_person(client, live)
    client.portal.call(lambda: live.settings.save_teams(TeamsConfig(accounts={"equipe": TeamsAccount(
        label="Équipe")})))
    # l'historique d'il y a trois jours, rangé déjà lu : rien n'est remarqué, la collecte de l'annuaire ne passe pas
    old = NOW // 1000 - 3 * 24 * 3_600_000
    client.portal.call(live.kernel.ports["teams"].store_batch, "equipe", InboxBatch(
        "8:orgid:adrien", "Adrien", (InboxConversation(DM, "", "dm"),),
        tuple(InboxMessage(f"m{i}", DM, "Alice", ALICE, old + i, "On se voit à 14 h ?") for i in range(2)),
        history=True), NOW)
    box = FakeMail(boxes=[PERSO, PRO, HERS], now=lambda: NOW)
    box.deliver(Mail("<rando@example.net>", "Bob Martin <bob.martin@gmail.com>", "bob.martin@gmail.com", "Rando dimanche",
                     NOW - HOUR, "On part à 8 h 30.", account="perso", to=PERSO.address))
    box.deliver(Mail("<devis@example.net>", "Robert Martin <bob.martin@gmail.com>", "bob.martin@gmail.com", "Le devis",
                     NOW - 2 * HOUR, "Le devis signé.", account="pro", to=PRO.address))
    live.kernel.ports["mail"] = box
    client.portal.call(live.kernel.set_params, "email", EmailParams(owners={"pro": "personne:" + lea,
                                                                            "siens": "elle"}))
    store = live.kernel.ports["contacts"]
    now = live.kernel.mind.frame().now
    teams, perso, pro, hers = (TEAMS, "equipe"), (MAIL, "perso"), (MAIL, "pro"), (MAIL, "siens")
    client.portal.call(lambda: store.observe([
        Observation(TEAMS_ID, ALICE, *teams, "Alice Durand", 2, now - 9 * HOUR, now - HOUR // 2,
                    title="Cheffe de projet"),
        Observation(EMAIL, "alice@nordis.fr", *teams, "Alice Durand", 0, now - HOUR, now - HOUR,
                    joins=(TEAMS_ID, ALICE), proof=True),
        Observation(PHONE, "+33612345678", *teams, "Alice Durand", 0, now - HOUR, now - HOUR, joins=(TEAMS_ID, ALICE)),
        Observation(COMPANY, "Nordis", *teams, "Nordis", 0, now - HOUR, now - HOUR, joins=(TEAMS_ID, ALICE)),
        Observation(TEAMS_ID, "8:orgid:adrien", *teams, "Adrien", 0, now - HOUR, now - HOUR, own=True),
        Observation(EMAIL, "bob.martin@gmail.com", *perso, "Bob Martin", 2, now - 5 * HOUR, now - HOUR),
        Observation(EMAIL, "bob.martin@gmail.com", *pro, "Robert Martin", 5, now - 9 * HOUR, now - 2 * HOUR),
        Observation(EMAIL, "camille.roux@gmail.com", *pro, "Camille Roux", 3, now - 9 * HOUR, now - 3 * HOUR),
        Observation(EMAIL, "g.rousseau@gmail.com", *hers, "G. Rousseau", 4, now - 9 * HOUR, now - 4 * HOUR),
        Observation(EMAIL, "lea.martin@laposte.net", *perso, "Léa Martin", 1, now - 9 * HOUR, now - 5 * HOUR),
        Observation(PHONE_APP, f"whatsapp:{DIGEST}", PHONE_SOURCE, adrien, "Maman", 4, now - 9 * HOUR,
                    now - 6 * HOUR, thread="t1"),
        Observation(TOLD_NAME, TOLD_KEY, TOLD, adrien, "Inès", 2, now - 9 * HOUR, now - 7 * HOUR),
    ]))
    ids = {name: store.contact_of(kind, value) for name, kind, value in (
        ("alice", TEAMS_ID, ALICE), ("adrien", TEAMS_ID, "8:orgid:adrien"), ("bob", EMAIL, "bob.martin@gmail.com"),
        ("camille", EMAIL, "camille.roux@gmail.com"), ("rousseau", EMAIL, "g.rousseau@gmail.com"),
        ("lea", EMAIL, "lea.martin@laposte.net"), ("maman", PHONE_APP, f"whatsapp:{DIGEST}"), ("ines", TOLD_NAME, TOLD_KEY),
        ("nordis", COMPANY, "nordis"))}
    assert all(ids.values()), ids
    assert store.link(ids["adrien"], adrien) and store.link(ids["lea"], lea)
    return client, live, ids, adrien, lea


def listed(client, query: str = "") -> dict:
    got = client.get(API + "/contacts" + query)
    assert got.status_code == 200, got.text
    return got.json()


def names(client, query: str = "") -> set[str]:
    return {c["name"] for c in listed(client, query)["items"]}


def sheet(client, cid: int):
    return client.get(API + f"/contacts/fiche?id={cid}")


# ── à qui ──


def test_each_person_sees_her_own_contacts_and_those_of_nobody(world):  # noqa: F811
    client, live, ids, _adrien, _lea = seed(world)
    got = listed(client)
    mine = {c["name"]: c for c in got["items"]}
    assert set(mine) == {"Alice Durand", "Bob Martin", "G. Rousseau", "Léa Martin", "Maman", "Inès", "Nordis"}
    assert got["total"] == 7 and got["counts"] == {"all": 7, "person": 6, "org": 1}
    alice = mine["Alice Durand"]
    assert alice["kind"] == "person" and alice["title"] == "Cheffe de projet" and not alice["linked"]
    assert alice["organisation"] == {"id": ids["nordis"], "name": "Nordis"}
    assert alice["sources"] == [{"source": "teams", "label": "Teams", "count": 2}]
    assert {"kind": "email", "value": "alice@nordis.fr"} in alice["identifiers"]
    assert mine["Nordis"]["kind"] == "org" and mine["Nordis"]["members"] == 1
    assert mine["Nordis"]["identifiers"] == [{"kind": "domain", "value": "nordis.fr"}]  # l'entreprise est son nom
    assert mine["Léa Martin"]["linked"]  # elle parle aussi à Mika
    assert mine["Maman"]["sources"] == [{"source": "whatsapp", "label": "WhatsApp", "count": 4}]
    assert mine["Inès"]["sources"] == [{"source": "told", "label": "Raconté", "count": 2}]
    # Bob : dans sa boîte à lui seulement, sous le nom qu'elle y lit
    assert mine["Bob Martin"]["sources"] == [{"source": "mail", "account": "perso", "label": "Personnel", "count": 2}]
    # le plus récent d'abord
    order = [c["name"] for c in got["items"]]
    assert order[0] == "Alice Durand" and order[-4:] == ["G. Rousseau", "Léa Martin", "Maman", "Inès"]

    login(client, "lea")
    theirs = names(client)
    assert theirs == {"Robert Martin", "Camille Roux", "G. Rousseau"}  # sa fiche à elle (Léa Martin) n'y est pas
    assert listed(client)["counts"] == {"all": 3, "person": 3, "org": 0}


def test_a_shared_box_brings_its_contacts_but_never_her_own_sheet(world):  # noqa: F811
    client, live, ids, _adrien, lea = seed(world)
    client.portal.call(live.kernel.set_params, "email", EmailParams(
        owners={"pro": "personne:" + lea, "siens": "elle"}, shares={"perso": {"personne:" + lea: "lire"}}))
    login(client, "lea")
    got = {c["id"]: c for c in listed(client)["items"]}
    assert ids["bob"] in got and ids["lea"] not in got  # Léa Martin, c'est elle
    assert {s["account"] for s in got[ids["bob"]]["sources"]} == {"perso", "pro"}
    assert ids["maman"] not in got and ids["ines"] not in got and ids["alice"] not in got
    assert sheet(client, ids["lea"]).status_code == 404


def test_nothing_says_whose_contact_it_is_besides_you(world):  # noqa: F811
    client, live, ids, _adrien, lea = seed(world)
    for text in (client.get(API + "/contacts").text, sheet(client, ids["bob"]).text):
        assert "Robert" not in text and "Atelier" not in text and "personne:" not in text and lea not in text
    bob = sheet(client, ids["bob"]).json()
    assert bob["name"] == "Bob Martin" and [s["label"] for s in bob["sources"]] == ["Personnel"]
    assert [i["where"] for i in bob["identifiers"]] == [["Personnel"]]
    # jugé sur ce qu'il voit : rien ne laisse deviner que Bob est aussi le contact d'une autre (relecture I3)
    assert bob["privacy"] == "mine" and bob["forget"] == {"allowed": True, "reason": ""}
    assert sheet(client, ids["rousseau"]).json()["privacy"] == "shared"  # la boîte de Mika
    login(client, "lea")
    robert = sheet(client, ids["bob"])
    assert robert.status_code == 200 and "Bob Martin" not in robert.text and "Personnel" not in robert.text


def test_a_phone_key_or_a_told_name_never_shows(world):  # noqa: F811
    client, live, ids, _adrien, _lea = seed(world)
    maman, ines = sheet(client, ids["maman"]), sheet(client, ids["ines"])
    for text in (client.get(API + "/contacts").text, maman.text, ines.text):
        assert DIGEST not in text and TOLD_KEY not in text and "whatsapp:" not in text
    assert maman.json()["identifiers"] == [{"kind": "phone_app", "label": "Contact WhatsApp", "value": "",
                                            "name": "Maman", "where": ["ton téléphone"], "generic": False}]
    assert maman.json()["places"] == [{"source": "phone", "conversation": "whatsapp|t1", "app": "whatsapp",
                                       "app_name": maman.json()["places"][0]["app_name"], "title": "",
                                       "group": False, "count": 4, "last": maman.json()["places"][0]["last"]}]
    assert maman.json()["message"] == "whatsapp|t1" and maman.json()["write"] is None
    assert ines.json()["identifiers"] == [] and ines.json()["places"] == []
    assert names(client, f"?q={DIGEST}") == set() and names(client, "?q=p1") == set()


def test_a_contact_of_someone_else_does_not_exist(world):  # noqa: F811
    client, live, ids, _adrien, _lea = seed(world)
    unknown = sheet(client, 999_999)
    assert unknown.status_code == 404 and unknown.json() == {"error": "Introuvable."}
    assert sheet(client, ids["adrien"]).status_code == 404  # sa propre fiche n'est pas un de ses contacts
    assert client.get(API + "/contacts/fiche?id=abc").status_code == 404
    login(client, "lea")
    for name in ("alice", "maman", "ines", "nordis"):
        r = sheet(client, ids[name])
        assert r.status_code == 404 and r.json() == unknown.json(), name
    assert post(client, "/contacts/forget", {"id": ids["alice"]}).status_code == 404


def test_search_and_kinds(world):  # noqa: F811
    client, live, ids, _adrien, _lea = seed(world)
    assert names(client, "?q=alice%40nordis") == {"Alice Durand"}
    assert names(client, "?q=06%2012%2034%2056%2078") == {"Alice Durand"}  # un numéro, comme il se range
    assert names(client, "?q=durand") == {"Alice Durand"}
    assert names(client, "?kind=org") == {"Nordis"}
    assert "Nordis" not in names(client, "?kind=person")
    assert listed(client, "?q=durand")["counts"]["all"] == 7  # les choix comptent sans la recherche
    assert client.get(API + "/contacts?kind=groupe").status_code == 400
    first, second = listed(client, "?size=4&page=1"), listed(client, "?size=4&page=2")
    assert first["total"] == second["total"] == 7 and len(first["items"]) == 4 and len(second["items"]) == 3
    assert not {c["id"] for c in first["items"]} & {c["id"] for c in second["items"]}


# ── la fiche ──


def test_a_sheet_says_what_identifies_them_what_she_knows_and_where_you_meet(world):  # noqa: F811
    client, live, ids, _adrien, _lea = seed(world)
    alice = sheet(client, ids["alice"]).json()
    kinds = {i["kind"]: i for i in alice["identifiers"]}
    assert set(kinds) == {"teams", "email", "phone"}
    assert kinds["email"]["value"] == "alice@nordis.fr" and kinds["email"]["where"] == ["son profil Teams"]
    assert kinds["teams"]["where"] == ["Teams"] and kinds["teams"]["label"] == "Identifiant Teams"
    assert [(f["kind"], f["value"]) for f in alice["facts"]] == [("title", "Cheffe de projet"),
                                                                 ("organisation", "Nordis")]
    assert alice["facts"][1]["from"] == "son adresse e-mail"
    conversations = [p for p in alice["places"] if p["source"] == "teams"]
    assert [p["conversation"] for p in conversations] == [ALICE_DM] and conversations[0]["kind"] == "dm"
    assert conversations[0]["count"] == 2 and conversations[0]["title"] == "Alice" and alice["teams"] == ALICE_DM
    assert alice["write"] == {"address": "alice@nordis.fr", "name": "Alice Durand"}  # sa boîte envoie
    assert alice["forget"] == {"allowed": True, "reason": ""}
    bob = sheet(client, ids["bob"]).json()
    [mail] = bob["places"]
    assert mail["source"] == "mail" and mail["box"] == "perso" and mail["box_name"] == "Personnel"
    assert mail["ref"].startswith("perso:") and mail["subject"] == "Rando dimanche"  # jamais celui de l'Atelier
    rousseau = sheet(client, ids["rousseau"]).json()
    assert rousseau["places"] == [] and rousseau["identifiers"][0]["where"] == ["Mika"]  # sa boîte : dite, sans y mener
    nordis = sheet(client, ids["nordis"]).json()
    assert nordis["kind"] == "org" and nordis["members_total"] == 1
    # son entreprise est rangée repliée (« nordis ») : elle se dit sous le nom de la fiche
    assert {(i["kind"], i["value"]) for i in nordis["identifiers"]} == {("domain", "nordis.fr"), ("company", "Nordis")}
    assert [(m["id"], m["name"], m["title"]) for m in nordis["members"]] == [(ids["alice"], "Alice Durand",
                                                                              "Cheffe de projet")]
    assert sheet(client, ids["lea"]).json()["linked"] is True


# ── oublier ──


def test_forgetting_reaches_only_what_comes_from_your_accounts_and_says_nothing_of_the_rest(world):  # noqa: F811
    """Relecture I3 : Adrien ne connaît Bob que par sa boîte ; Bob est aussi dans la boîte de Léa. Avant, la fiche
    disait ``privacy: mine`` et ``forget.allowed: false`` (« ne vient pas que de tes comptes ») : Adrien en déduisait
    qu'une autre le connaît. L'oubli se juge maintenant sur ce qu'il voit ; il n'efface que sa part quand le reste est
    ailleurs, avec la même réponse — Léa garde son contact. Ce qui vient d'un compte à Mika se refuse, sans autre
    motif que ce que la fiche montre déjà."""
    client, live, ids, _adrien, _lea = seed(world)
    assert client.post(API + "/contacts/forget", json={"id": ids["maman"]}).status_code == 403  # sans CSRF
    done = post(client, "/contacts/forget", {"id": ids["maman"]})
    assert done.status_code == 200 and done.json()["ok"] and "Maman" in done.json()["message"]
    assert sheet(client, ids["maman"]).status_code == 404 and "Maman" not in names(client)
    audited = [(e.data.action, e.data.by, e.data.subject) for e in journal(live, rt.OPERATED)]
    assert ("moi.oublier.contact", "user_1", f"contact:{ids['maman']}") in audited
    bob = post(client, "/contacts/forget", {"id": ids["bob"]})  # vu aussi chez Léa : sa part seulement
    assert bob.status_code == 200 and set(bob.json()) == set(done.json()) == {"ok", "message"}
    assert bob.json()["message"] == done.json()["message"].replace("Maman", "Bob Martin")
    assert sheet(client, ids["bob"]).status_code == 404 and "Bob Martin" not in names(client)
    assert ("moi.oublier.contact", "user_1", f"contact:{ids['bob']}") in [
        (e.data.action, e.data.by, e.data.subject) for e in journal(live, rt.OPERATED)]
    refused = post(client, "/contacts/forget", {"id": ids["rousseau"]})  # dans la boîte de Mika
    assert refused.status_code == 403 and "ses comptes à elle" in refused.json()["error"]
    rousseau = sheet(client, ids["rousseau"]).json()
    assert rousseau["forget"] == {"allowed": False, "reason": refused.json()["error"]}
    assert post(client, "/contacts/forget", {"id": ids["adrien"]}).status_code == 404
    login(client, "lea")
    robert = sheet(client, ids["bob"])  # pour Léa, rien n'a changé
    assert robert.status_code == 200 and robert.json()["name"] == "Robert Martin"
    assert [s["account"] for s in robert.json()["sources"]] == ["pro"]


def test_the_mail_correspondents_stay_for_writing(world):  # noqa: F811
    """Mail › Contacts quitte l'écran, pas l'API : écrire propose encore ses correspondants (web et Android)."""
    client, live, _ids, _adrien, _lea = seed(world)
    got = client.get(API + "/mail/contacts?q=bob", headers=csrf(client))
    assert got.status_code == 200 and [c["address"] for c in got.json()["items"]] == ["bob.martin@gmail.com"]


def test_linked_says_she_talks_to_mika_only_when_she_wrote_to_her(world):  # noqa: F811
    """Relecture, mineur 1 : « parle aussi à Mika » se disait de toute fiche reliée à une personne de l'identité —
    Adrien apprenait que sa collègue est une interlocutrice de Mika même quand elle n'a qu'un compte. ``talks`` ne
    vaut que si elle lui a écrit."""
    client, live, ids, _adrien, _lea = seed(world)
    lea = {c["name"]: c for c in listed(client)["items"]}["Léa Martin"]
    assert lea["linked"] and not lea["talks"]  # un compte, jamais un mot à Mika
    assert sheet(client, ids["lea"]).json()["talks"] is False
    assert not {c["name"]: c for c in listed(client)["items"]}["Alice Durand"]["talks"]
    login(client, "lea")
    chat(client, "bonjour Mika")
    login(client, "adrien")
    assert {c["name"]: c for c in listed(client)["items"]}["Léa Martin"]["talks"]
    assert sheet(client, ids["lea"]).json()["talks"] is True
