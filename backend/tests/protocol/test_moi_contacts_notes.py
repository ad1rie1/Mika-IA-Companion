"""L'API par personne, Contacts › ce que Mika en sait (ADR 0298, lot 6) : à travers le vrai serveur. Les faits qu'elle a
tirés des derniers messages d'un contact ne se lisent que par qui voit le compte d'où ils viennent ; un fait d'un
compte à toi s'oublie un à un (l'action de la console, auditée depuis ton espace), un fait d'un compte qu'on te
partage ou à Mika non (403), un fait que tu ne vois pas n'existe pas (404)."""

from __future__ import annotations

from mika.contracts import runtime as rt
from mika.ports.contacts import MAIL, TEAMS, Note, Portrait
from tests.protocol.test_moi_contacts import seed, sheet
from tests.protocol.test_moi_mail import journal, login, post
from tests.protocol.test_web import world  # noqa: F401 — fixture partagée


def learn(client, live, cid: int, source: str, account: str, *texts: str) -> None:
    store = live.kernel.ports["contacts"]
    now = live.kernel.mind.frame().now
    client.portal.call(lambda: store.portrayed(Portrait(cid, source, account, now, now, 3, call_id="run#1"), [
        Note(0, cid, source, account, text, "topic", 0.75, "ref", "dans le groupe « Projet »", now, now, "run#1")
        for text in texts]))


def notes(client, cid: int) -> list[dict]:
    got = sheet(client, cid)
    assert got.status_code == 200, got.text
    return [f for f in got.json()["facts"] if f["kind"] == "note"]


def taught(world):  # noqa: F811
    client, live, ids, adrien, lea = seed(world)
    learn(client, live, ids["alice"], TEAMS, "equipe", "Elle suit le budget du projet Nordis.")
    learn(client, live, ids["bob"], MAIL, "perso", "Il organise la rando du dimanche.")
    learn(client, live, ids["bob"], MAIL, "pro", "Il envoie les devis signés.")
    learn(client, live, ids["rousseau"], MAIL, "siens", "Il écrit pour la mairie.")
    return client, live, ids


def test_each_person_reads_only_the_facts_of_the_accounts_she_sees(world):  # noqa: F811
    client, _live, ids = taught(world)
    (alice,) = notes(client, ids["alice"])
    assert alice["value"] == "Elle suit le budget du projet Nordis." and alice["confidence"] == 0.75
    assert alice["from"] == "ses messages dans Teams" and alice["place"] == "dans le groupe « Projet »"
    assert alice["sort"] == "topic" and alice["forget"] is True and alice["id"] and alice["at"]
    assert [n["value"] for n in notes(client, ids["bob"])] == ["Il organise la rando du dimanche."]
    assert notes(client, ids["bob"])[0]["from"] == "ses mails à Personnel"
    (mika,) = notes(client, ids["rousseau"])  # une boîte à Mika : à tout le monde, mais pas à toi de l'oublier
    assert mika["forget"] is False
    login(client, "lea")
    assert [n["value"] for n in notes(client, ids["bob"])] == ["Il envoie les devis signés."]


def test_a_fact_of_your_own_account_is_forgotten_one_by_one_and_audited(world):  # noqa: F811
    client, live, ids = taught(world)
    (fact,) = notes(client, ids["alice"])
    assert client.post("/api/moi/contacts/fact/forget", json={"id": fact["id"]}).status_code == 403  # sans CSRF
    done = post(client, "/contacts/fact/forget", {"id": fact["id"]})
    assert done.status_code == 200, done.text
    assert done.json()["ok"] and done.json()["id"] == fact["id"] and "Elle suit le budget" in done.json()["message"]
    assert notes(client, ids["alice"]) == []
    audited = [(e.data.action, e.data.by, e.data.subject) for e in journal(live, rt.OPERATED)]
    assert ("moi.contacts.oublier_fait", "user_1", f"contact:{ids['alice']}") in audited
    assert post(client, "/contacts/fact/forget", {"id": fact["id"]}).status_code == 404  # déjà oublié


def test_a_fact_you_do_not_own_is_refused_and_one_you_do_not_see_does_not_exist(world):  # noqa: F811
    client, _live, ids = taught(world)
    (mika,) = notes(client, ids["rousseau"])
    refused = post(client, "/contacts/fact/forget", {"id": mika["id"]})
    assert refused.status_code == 403 and "n'est pas à toi" in refused.json()["error"]
    (alice,) = notes(client, ids["alice"])
    assert post(client, "/contacts/fact/forget", {"id": 999_999}).status_code == 404
    login(client, "lea")
    assert post(client, "/contacts/fact/forget", {"id": alice["id"]}).status_code == 404  # le Teams d'Adrien
    login(client, "adrien")
    assert [n["value"] for n in notes(client, ids["alice"])] == ["Elle suit le budget du projet Nordis."]
