"""Les profils joints aux lots de l'extension (ADR 0298, lot 2), par le vrai serveur.

Un lot peut joindre le profil des auteurs et des personnes mentionnées de ses messages (``profiles``) ; chacun est lu
seul, comme un message : un profil illisible est laissé de côté, jamais le lot, et ne compte pas dans ``dropped``
(l'extension y lit des messages refusés). Une adresse mal formée est laissée vide ; un numéro sans assez de chiffres,
écarté. Un lot sans profils répond comme avant ; l'historique en joint aussi. Plus de 200 profils : le lot est refusé.
"""

from __future__ import annotations

from mika.app.teams import profile_of
from tests.protocol.test_teams_web import batch, headers, new_key
from tests.protocol.test_web import world  # noqa: F401 — fixture

GILLES = "8:orgid:0b5c1a2e-0000-4000-8000-000000000001"
LEA = "8:orgid:0b5c1a2e-0000-4000-8000-000000000002"


def gilles(**more) -> dict:
    return {"id": GILLES, "name": "Gilles Rousseau", "email": "gilles@nordis.fr", "title": "Chef de projet",
            "company": "Nordis", "department": "Achats", "tenant": "Nordis", "phones": ["+33 6 12 34 56 78"],
            **more}


def test_profiles_ride_with_a_batch_and_are_read_one_by_one(world):  # noqa: F811
    client, live, _ = world
    key = new_key(client, live)
    store = live.kernel.ports["teams"]
    body = batch()
    body["profiles"] = [
        gilles(),
        {"id": LEA, "name": " Léa   Martin\x00", "email": "pas une adresse", "phones": ["12", "06 11 22 33 44"]},
        {"id": "8:orgid:pas-un-guid", "name": "Forme inconnue"},  # un identifiant que l'extension ne reconnaît pas
        gilles(id="8:live:trop.long", name="x" * 121),  # au-delà de sa borne
        "pas un profil",
        {"id": "8:live:vide"},  # rien de dit sur la personne
    ]
    got = client.post("/api/teams/inbox", json=body, headers=headers(key))
    assert got.status_code == 202, got.text
    assert got.json() == {"ok": True, "accepted": 1, "known": 0, "twins": 0, "dropped": 0, "profiles": 2}
    kept = {p.id: p for p in client.portal.call(store.profiles_since, 0, 10).profiles}
    assert set(kept) == {GILLES, LEA}
    assert (kept[GILLES].account, kept[GILLES].company, kept[GILLES].phones) == ("principal", "Nordis",
                                                                                  ("+33 6 12 34 56 78",))
    lea = kept[LEA]
    assert (lea.name, lea.email, lea.phones) == ("Léa Martin", "", ("06 11 22 33 44",))
    # redits tels quels : reçus, rien de changé
    again = client.post("/api/teams/inbox", json=body, headers=headers(key))
    assert again.json()["profiles"] == 0 and again.json()["known"] == 1


def test_a_batch_without_profiles_answers_as_before_and_history_carries_them_too(world):  # noqa: F811
    client, live, _ = world
    key = new_key(client, live)
    store = live.kernel.ports["teams"]
    plain = client.post("/api/teams/inbox", json=batch(), headers=headers(key))
    assert "profiles" not in plain.json()
    old = batch(text="un vieux message")
    old["messages"][0].update(id="1600000000000", time=1_600_000_000_000)
    old.update(history=True, profiles=[gilles(title="Acheteur")])
    got = client.post("/api/teams/inbox", json=old, headers=headers(key))
    assert got.status_code == 202 and got.json()["profiles"] == 1
    assert [p.title for p in client.portal.call(store.profiles_since, 0, 10).profiles] == ["Acheteur"]


def test_too_many_profiles_refuse_the_batch_before_anything_is_stored(world):  # noqa: F811
    client, live, _ = world
    key = new_key(client, live)
    store = live.kernel.ports["teams"]
    body = batch()
    body["profiles"] = [gilles(id=f"8:live:p{n}") for n in range(201)]
    assert client.post("/api/teams/inbox", json=body, headers=headers(key)).status_code == 400
    assert client.portal.call(store.profiles_since, 0, 10).profiles == ()
    assert client.portal.call(store.last_batch, "principal") == 0


def test_a_profile_is_read_like_the_extension_writes_it():
    p = profile_of({"id": " " + GILLES.upper() + " ", "name": "  Gilles   Rousseau ", "email": "Gilles@Nordis.FR",
                    "phones": ["+33 6 12 34 56 78", "+33 6 12 34 56 78", 612345678], "extra": "ignoré"})
    assert p is None  # un numéro qui n'est pas un texte : illisible, comme un champ d'un message
    p = profile_of({"id": GILLES.upper(), "name": "  Gilles   Rousseau ", "email": "Gilles@Nordis.FR",
                    "phones": ["+33 6 12 34 56 78", "+33 6 12 34 56 78"], "extra": "ignoré"})
    assert p is not None and (p.id, p.name, p.email, p.phones) == (GILLES, "Gilles Rousseau", "gilles@nordis.fr",
                                                                    ("+33 6 12 34 56 78",))
    assert profile_of({"id": "8:teamsvisitor:" + "a" * 32, "company": "Prestatech"}).company == "Prestatech"
    assert profile_of({"id": GILLES, "name": "G", "phones": ["1"] * 4}) is None  # trois numéros au plus
    assert profile_of({"id": GILLES, "email": "x@y", "name": ""}) is None  # rien d'autre qu'une adresse mal formée
