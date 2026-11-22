"""Les réactions et les photos de profil de Teams (ADR 0300) par le vrai serveur.

- **la porte** : un message porte ses réactions, lues une à une (une réaction illisible est laissée de côté, jamais le
  message) ; un message connu qui ne change que de réactions est « connu » — rien n'est journalisé (``teams.received``),
  le tri ne se réveille pas. ``POST /api/teams/photo`` : sans clé 401 ; d'un type faux, d'octets qui mentent, trop
  grande 400 ; d'une personne que le compte ne connaît pas, ou d'une autre empreinte que celle de son profil, 404 ;
  sinon 202, une fois ;
- **l'API par personne** : le fil donne les réactions (``key``, ``emoji``, ``count``, ``mine``, ``names``) et la photo
  de chaque auteur ; ``GET …/teams/photo`` sert ses octets à qui lit le compte (``private``, ``nosniff``), à personne
  d'autre ; les contacts portent l'adresse de leur photo quand un compte Teams où l'on lit la garde.
"""

from __future__ import annotations

import base64
import time

from mika.plugins.teams import RECEIVED
from mika.ports.teams import InboxBatch, InboxProfile, PhotoIn
from tests.protocol.test_moi_contacts import ALICE, seed
from tests.protocol.test_moi_mail import API, journal, login, second_person
from tests.protocol.test_teams_web import DM, headers, new_key
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture

GILLES = "8:orgid:0b5c1a2e-0000-4000-8000-000000000001"
ME = "8:orgid:0b5c1a2e-0000-4000-8000-00000000000a"
JPEG = b"\xff\xd8\xff\xe0" + b"\x01" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def message(mid: str, text: str = "On se voit à 14 h ?", **more) -> dict:
    return {"id": mid, "conv": DM, "author": "Gilles", "author_id": GILLES, "time": int(time.time() * 1000) - 1000,
            "text": text, **more}


def push(client, key, *messages, profiles=()) -> dict:
    body = {"self": {"id": ME, "name": "Adrien"}, "conversations": [{"id": DM, "kind": "dm"}],
            "messages": list(messages)}
    if profiles:
        body["profiles"] = list(profiles)
    got = client.post("/api/teams/inbox", headers=headers(key), json=body)
    assert got.status_code == 202, got.text
    return got.json()


def photo(client, key, *, person: str = GILLES, etag: str = "e1", data: bytes = JPEG, kind: str = "image/jpeg"):
    return client.post("/api/teams/photo", headers=headers(key), json={
        "person": person, "etag": etag, "type": kind, "data": base64.b64encode(data).decode()})


LIKE = {"key": "like", "count": 2, "mine": False, "by": [GILLES, ME]}


def test_reactions_ride_with_their_message_and_a_reaction_only_change_journals_nothing(world):  # noqa: F811
    client, live, _ = world
    key = new_key(client, live)
    store = live.kernel.ports["teams"]
    first = push(client, key, message("1759000000901", reactions=[
        LIKE, {"key": "Pas une clé !", "count": 1}, {"key": "heart", "count": "beaucoup"}, "x"]))
    assert (first["accepted"], first["dropped"]) == (1, 0), "une réaction illisible ne fait pas écarter le message"
    [m] = client.portal.call(store.thread, "principal", DM, 10)
    assert [(r.key, r.count, r.mine) for r in m.reactions] == [("like", 2, True)], "la sienne, par son identifiant"
    received = len(journal(live, RECEIVED))
    receipts = live.kernel.mind.frame().state("teams").receipts
    # le même message, un cœur de plus : connu, rien de journalisé, rien à trier
    again = push(client, key, message("1759000000901", reactions=[LIKE, {"key": "heart", "count": 1, "by": [GILLES]}]))
    assert (again["accepted"], again["known"]) == (0, 1)
    assert len(journal(live, RECEIVED)) == received
    assert live.kernel.mind.frame().state("teams").receipts == receipts, "le tri ne se réveille pas"
    [m] = client.portal.call(store.thread, "principal", DM, 10)
    assert [r.key for r in m.reactions] == ["like", "heart"]


def test_the_photo_door_keeps_a_photo_once_for_a_known_profile_at_its_etag(world):  # noqa: F811
    client, live, _ = world
    key = new_key(client, live)
    assert client.post("/api/teams/photo", headers=headers("mtk_rien"), json={}).status_code == 401
    assert photo(client, key).status_code == 404, "une personne que ce compte ne connaît pas"
    push(client, key, message("1759000000911"), profiles=[{"id": GILLES, "name": "Gilles Rousseau",
                                                            "avatar": "e1"}])
    assert photo(client, key, etag="e0").status_code == 404, "une autre empreinte que celle de son profil"
    assert photo(client, key, data=b"pas une image").status_code == 400
    assert photo(client, key, data=PNG).status_code == 400, "le type ment"
    assert photo(client, key, kind="image/gif", data=b"GIF89a" + b"\x00" * 16).status_code == 400
    assert photo(client, key, data=JPEG + b"\x00" * (65 * 1024)).status_code == 400, "64 Ko au plus"
    assert photo(client, key, person="javascript:x").status_code == 400
    kept = photo(client, key)
    assert kept.status_code == 202 and kept.json()["kept"] is True
    assert photo(client, key).json()["kept"] is False, "la même empreinte redite n'en fait qu'une"
    got = client.portal.call(live.kernel.ports["teams"].photo, "principal", GILLES)
    assert (got.etag, got.data) == ("e1", JPEG)
    # rien n'est journalisé d'une photo : elle ne fait rien remarquer
    assert not [e for e in live.kernel.mind.store.read() if "photo" in e.type]


def test_the_thread_gives_reactions_and_photos_and_the_photo_is_served_behind_the_login(world):  # noqa: F811
    client, live, _ = world
    key = new_key(client, live)
    push(client, key, message("1759000000921", reactions=[LIKE, {"key": "1f44f_clappinghands", "count": 3}]),
         profiles=[{"id": GILLES, "name": "Gilles Rousseau", "avatar": "e1"}])
    assert photo(client, key).status_code == 202
    assert client.get(API + f"/teams/thread?conversation={DM}").status_code == 401, "derrière la connexion"
    bootstrap(client)
    [m] = client.get(API + f"/teams/thread?conversation={DM}").json()["messages"]
    assert m["reactions"] == [{"key": "like", "emoji": "👍", "count": 2, "mine": True, "names": ["Gilles Rousseau"]},
                              {"key": "1f44f_clappinghands", "emoji": "👏", "count": 3, "mine": False, "names": []}]
    assert m["photo"].startswith(API + "/teams/photo?account=principal&person=8%3Aorgid%3A")
    [conv] = client.get(API + "/teams/conversations").json()["items"]
    assert conv["last"]["photo"] == m["photo"] and conv["last"]["reactions"] == m["reactions"]
    got = client.get(m["photo"])
    assert got.status_code == 200 and got.content == JPEG and got.headers["content-type"] == "image/jpeg"
    assert got.headers["cache-control"].startswith("private") and got.headers["x-content-type-options"] == "nosniff"
    by_conversation = client.get(API + f"/teams/photo?conversation={DM}&person={GILLES}")
    assert by_conversation.status_code == 200 and by_conversation.content == JPEG
    assert client.get(API + f"/teams/photo?account=principal&person={ME}").status_code == 404
    assert client.get(API + f"/teams/photo?account=ailleurs&person={GILLES}").status_code == 404
    # une autre personne, qui n'a pas ce compte : rien
    second_person(client, live)
    login(client, "lea")
    assert client.get(m["photo"]).status_code == 404
    assert client.get(API + f"/teams/photo?conversation={DM}&person={GILLES}").status_code == 404


def test_a_contact_carries_its_photo_when_a_teams_account_you_read_keeps_it(world):  # noqa: F811
    client, live, ids, _adrien, _lea = seed(world)
    store = live.kernel.ports["teams"]
    now = live.kernel.mind.frame().now
    client.portal.call(store.store_batch, "equipe", InboxBatch(
        "8:orgid:adrien", "Adrien", profiles=(InboxProfile(ALICE, "Alice Durand", avatar="e1"),)), now)
    assert client.portal.call(store.keep_photo, "equipe", PhotoIn(ALICE, "e1", "image/jpeg", JPEG), now) == "kept"
    items = {c["id"]: c for c in client.get(API + "/contacts").json()["items"]}
    url = items[ids["alice"]]["photo"]
    assert url and url.startswith(API + "/teams/photo?account=equipe&")
    assert items[ids["bob"]]["photo"] is None, "pas d'identifiant Teams : ses initiales"
    assert client.get(API + f"/contacts/fiche?id={ids['alice']}").json()["photo"] == url
    nordis = client.get(API + f"/contacts/fiche?id={ids['nordis']}").json()
    assert nordis["photo"] is None, "une organisation : son carré"
    assert [(m["id"], m["photo"]) for m in nordis["members"]] == [(ids["alice"], url)], "ses personnes, en photo"
    assert client.get(url).content == JPEG
    login(client, "lea")  # « Équipe » n'est pas à elle : ni la fiche, ni la photo
    assert client.get(url).status_code == 404


GROUP = "19:projet-lumen@thread.v2"


def test_a_one_to_one_carries_the_photo_of_the_other_person_even_when_your_message_is_the_last(world):  # noqa: F811
    client, live, _ = world
    key = new_key(client, live)
    now = int(time.time() * 1000)
    got = client.post("/api/teams/inbox", headers=headers(key), json={
        "self": {"id": ME, "name": "Adrien"},
        "conversations": [{"id": DM, "kind": "dm"}, {"id": GROUP, "kind": "group", "title": "Projet Lumen"}],
        "messages": [message("1759000000931", time=now - 5000),
                     {"id": "1759000000932", "conv": DM, "author": "Adrien", "author_id": ME, "time": now - 4000,
                      "text": "Oui, à 14 h."},
                     {"id": "1759000000933", "conv": GROUP, "author": "Gilles", "author_id": GILLES,
                      "time": now - 3000, "text": "La démo tourne."}],
        "profiles": [{"id": GILLES, "name": "Gilles Rousseau", "avatar": "e1"}]})
    assert got.status_code == 202, got.text
    assert photo(client, key).status_code == 202
    bootstrap(client)
    items = {c["key"]: c for c in client.get(API + "/teams/conversations").json()["items"]}
    dm, group = items[DM], items[GROUP]
    gilles = group["last"]["photo"]
    assert gilles.startswith(API + "/teams/photo?account=principal&person=8%3Aorgid%3A")
    # le dernier message du tête-à-tête est le tien : la conversation garde la photo de l'autre
    assert dm["last"]["own"] and dm["last"]["photo"] == "" and dm["photo"] == gilles
    assert group["photo"] == "", "un groupe : pas la photo de qui y a parlé en dernier"
    assert client.get(API + f"/teams/thread?conversation={DM}").json()["photo"] == gilles
    assert client.get(API + f"/teams/thread?conversation={GROUP}").json()["photo"] == ""
    assert client.get(dm["photo"]).content == JPEG
