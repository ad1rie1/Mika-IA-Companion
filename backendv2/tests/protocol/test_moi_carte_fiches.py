"""Les fiches, les événements et les photos de l'écran Carte par l'API par personne (ADR 0259) : à travers le vrai
serveur, sur une carte jouée en mémoire (``tests/fixtures/fake_maps.py``).

- une liste se filtre (ouvert, ce qu'un lieu offre, sa cuisine, sa note) et se range (la distance, la note) ; un lieu
  n'y porte que ce qu'on en sait ; elle dit quand les notes ont été lues ;
- « ici » est ta dernière position, jamais celle d'une autre ; chercher autour de toi précharge les avis de ta case, sans
  retenir la réponse, et le téléphone qui donne sa position aussi ;
- la fiche d'un lieu réunit ses sources, chacune avec ce qu'il faut citer (« Google Maps », l'auteur et le lien de
  chaque avis et de chaque photo, l'auteur et la date de l'office de tourisme, OpenStreetMap) ; ses photos sont des
  références servies par ce serveur ; « Actualiser » est borné par compte et dit en mots ce qui n'a pas pu se relire ;
- les événements se cherchent autour d'un point, d'une zone, d'une période, de thèmes ; leur fiche dit son auteur et
  sa date ;
- une photo se sert par sa référence seule : une référence inconnue, ou qui n'en est pas une, donne 404 et rien ne
  part ; ses octets ont leur type et des en-têtes de cache privés ;
- un paramètre faux est refusé (400), jamais ramené dans ses bornes ; ce qui ne se trouve pas, 404.
"""

from __future__ import annotations

import functools
import json
from dataclasses import replace
from datetime import datetime

from mika.app.mindport import KernelPort
from mika.contracts import trips as c
from mika.kernel.events import Content
from mika.ports.maps import ReviewsCoverage
from tests.fixtures.fake_maps import (
    CIBOULETTE,
    CONCERT,
    FETE,
    HORIZON,
    PHOTO,
    PLACES,
    PNG,
    TARTINE,
    TOURISM_PHOTO,
    FakeMaps,
)
from tests.protocol.test_moi_carte import CARTE, plugged, post
from tests.protocol.test_moi_mail import append, journal, login, second_person
from tests.protocol.test_web import world  # noqa: F401 — fixture partagée

ANNECY = "45.8992,6.1294"
RATED = (*PLACES, CIBOULETTE, TARTINE)


def ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def rated(world):  # noqa: F811
    return plugged(world, FakeMaps(places=RATED))


# ── une liste filtrée et notée ──


def test_a_list_is_filtered_sorted_and_says_when_its_ratings_were_read(world):  # noqa: F811
    client, _live, maps = rated(world)
    got = client.get(CARTE + f"/lieux?cat=manger&near={ANNECY}&open_now=1&features=terrasse,vegetarien"
                             "&cuisine=française&min_rating=4.5&sort=rating&limit=5")
    assert got.status_code == 200, got.text
    body = got.json()
    [found] = body["places"]
    assert found["id"] == "l7" and found["rating"] == 4.6 and found["reviews"] == 1203 and found["price"] == "€€€"
    assert found["open_state"] == "open" and found["open_text"] == "Ouvert · ferme à 22:30"
    assert found["photo"] == PHOTO and found["tags"] == ["terrasse", "vegetarien"] and found["cuisine"]
    [asked] = [x for x in maps.calls if x[0] == "search"]
    assert asked[6] == {"open_now": True, "features": frozenset({"terrasse", "vegetarien"}), "cuisine": "française",
                        "min_rating": 4.5, "sort": "rating"}
    # la ligne « notes Google lues le … » : ce que le cache des avis sait de l'endroit
    assert body["reviews"] == {"ready": True, "cells": 1, "loaded": 1, "oldest": ms("2026-11-18T08:00:00Z"),
                               "note": ""}
    plain = {p["id"]: p for p in client.get(CARTE + f"/lieux?cat=manger&near={ANNECY}").json()["places"]}
    assert set(plain["l8"]) == {"id", "name", "kind", "kind_fr", "category", "lat", "lon", "town", "distance_m",
                                "along_m", "osm"}  # ce qu'on ne sait pas n'y est pas
    named = client.get(CARTE + "/lieux?q=ciboulette").json()
    assert "reviews" not in named and [p["id"] for p in named["places"]] == ["l7"]  # sans endroit, sans couverture
    for bad, field in (("features=plage", "features"), ("min_rating=6", "min_rating"), ("min_rating=abc", "min_rating"),
                       ("min_rating=nan", "min_rating"), ("sort=avis", "sort"), ("cuisine=" + "x" * 41, "cuisine")):
        refused = client.get(CARTE + f"/lieux?near={ANNECY}&" + bad)
        assert refused.status_code == 400 and field in refused.json()["fields"], bad


def test_the_screen_learns_the_filters_sorts_and_themes_it_offers(world):  # noqa: F811
    client, _live, _maps = rated(world)
    info = client.get(CARTE).json()
    assert [f["id"] for f in info["features"]] == ["terrasse", "vegetarien", "vegan", "accessible", "emporter",
                                                   "livraison"]
    assert {"id": "emporter", "label": "À emporter"} in info["features"]
    assert [s["id"] for s in info["sorts"]] == ["distance", "rating"]
    assert info["themes"][0] == {"id": "concerts", "label": "Concerts"} and len(info["themes"]) == 9
    assert info["tourism"] == {"ready": True, "places": 12, "events": 2, "synced": ms("2026-11-18T03:00:00Z")}


# ── « ici », et le préchargement ──


def _locate(client, live, lat: float, lon: float, handle: str = "user_1") -> None:
    client.portal.call(functools.partial(KernelPort(live.kernel).locate, handle, lat=lat, lon=lon, accuracy_m=10,
                                         label="Le Pâquier, Annecy", age_ms=0))


def test_here_is_your_last_phone_position_never_someone_else_s(world):  # noqa: F811
    client, live, maps = rated(world)
    unknown = client.get(CARTE + "/lieux?near=ici&cat=manger")
    assert unknown.status_code == 409 and "near" in unknown.json()["fields"]
    assert "Téléphone › Position" in unknown.json()["error"] and maps.preloads == []
    _locate(client, live, 45.8995, 6.1262)
    assert maps.preloads == [(45.8995, 6.1262)]  # le téléphone a donné sa position : sa case se précharge
    got = client.get(CARTE + "/lieux?near=ici&cat=manger").json()
    assert got["here"]["lat"] == 45.8995 and got["here"]["label"] == "Le Pâquier, Annecy" and got["here"]["at"] > 0
    assert got["places"][0]["id"] == "l7" and got["places"][0]["distance_m"] < 100
    assert maps.preloads == [(45.8995, 6.1262)] * 2  # « autour de moi » : préchargé aussi
    events = client.get(CARTE + "/evenements?near=ici").json()
    assert events["here"]["lon"] == 6.1262 and [x[1] for x in maps.calls if x[0] == "events"][-1] == (45.8995, 6.1262)
    second_person(client, live)
    login(client, "lea")
    theirs = client.get(CARTE + "/lieux?near=ici")
    assert theirs.status_code == 409  # « ici » : la tienne seule — Léa n'a rien donné
    assert client.get(CARTE + "/evenements?near=ici").status_code == 409


def test_searching_around_you_preloads_your_cell_and_answers_without_waiting(world):  # noqa: F811
    client, _live, maps = rated(world)
    client.get(CARTE + f"/lieux?near={ANNECY}")
    assert maps.preloads == []  # un point de la carte n'est pas toi : rien ne se précharge
    for _ in range(12):
        assert client.get(CARTE + f"/lieux?near={ANNECY}&here=1").status_code == 200
    assert maps.preloads == [(45.8992, 6.1294)] * 10  # dix par compte et par dix minutes, puis plus rien, sans le dire


# ── la fiche d'un lieu ──


def test_a_fiche_gathers_its_sources_and_what_each_asks_to_be_cited(world):  # noqa: F811
    client, _live, maps = rated(world)
    got = client.get(CARTE + "/lieu/n700")
    assert got.status_code == 200 and got.headers["cache-control"] == "no-store"
    fiche = got.json()
    assert fiche["place"]["id"] == "l7" and fiche["place"]["open_text"] == "Ouvert · ferme à 22:30"
    osm = fiche["osm"]
    assert osm["facts"] == [{"label": "Cuisine", "value": "Française, régionale"}, {"label": "Terrasse", "value": "oui"}]
    assert osm["hours_text"].startswith("du mardi") and osm["attribution"] == "© les contributeurs d'OpenStreetMap"
    tourism = fiche["tourism"]
    assert tourism["attribution"] == "DATAtourisme · Lac Annecy Tourisme, mis à jour le 12 octobre 2026"
    assert tourism["licence"] == "Licence Ouverte 2.0" and tourism["contacts"][0]["label"] == "Téléphone"
    assert tourism["photos"][0]["ref"] == TOURISM_PHOTO and tourism["photos"][0]["licence"] == "CC BY-SA"
    google = fiche["reviews"]
    assert google["source_label"] == "Google Maps" and google["url"] == "https://maps.google.com/?cid=42"
    assert google["found"] and google["rating"] == 4.6 and google["count"] == 1203 and google["price_range"] == "40–60 €"
    assert google["facts"] == [{"label": "Végétarien", "value": "oui (selon Google)"}] and google["cached"] > 0
    first = google["reviews"][0]
    assert first["author"] == "Camille R." and first["author_url"] == "https://www.google.com/maps/contrib/1"
    assert first["relative"] == "il y a 2 semaines" and first["at"] > 0 and "\n" in first["text"]
    [pic] = google["photos"]
    assert pic["credit"] == "Camille R." and pic["credit_url"].startswith("https://www.google.com/maps/contrib/")
    assert pic["ref"] == PHOTO and pic["path"] == f"/api/moi/carte/photo/{PHOTO}"  # servie par ce serveur seul
    assert "http" not in pic["path"]
    assert [e["id"] for e in fiche["events"]] == [FETE.id, CONCERT.id] and fiche["events"][0]["free"] is True
    bare = client.get(CARTE + f"/lieu/{HORIZON.id}").json()
    assert bare["tourism"] is None and bare["reviews"] is None and bare["events"] == []
    asked = len(maps.calls)
    for ident in ("l999999", "x1", "t:pas-un-uuid", "https:%2F%2Fexample.com"):
        assert client.get(CARTE + f"/lieu/{ident}").status_code == 404, ident
    assert [x[1] for x in maps.calls[asked:]] == ["l999999"]  # une forme inconnue ne demande rien au port


def test_refresh_is_bounded_per_account_and_says_what_could_not_be_read(world):  # noqa: F811
    client, live, maps = rated(world)
    assert client.post(CARTE + "/lieu/l7/actualiser", json={}).status_code == 403  # sans CSRF
    done = post(client, CARTE + "/lieu/l7/actualiser", {})
    assert done.status_code == 200 and done.json()["ok"] and done.json()["reviews"]["rating"] == 4.6
    assert ("place_refresh", "l7") in maps.calls
    assert post(client, CARTE + "/lieu/l999/actualiser", {}).status_code == 404
    maps.refresh_fail = "Le quota du mois de Google (fiches avec avis) est atteint : il revient le 1er décembre à 09:00."
    failed = post(client, CARTE + "/lieu/l7/actualiser", {})
    assert failed.status_code == 503 and failed.json()["error"].startswith("Le quota du mois de Google")
    maps.refresh_fail = ""
    codes = [post(client, CARTE + "/lieu/l7/actualiser", {}).status_code for _ in range(8)]
    assert codes == [200] * 7 + [429]  # dix par minute et par compte, les refus compris
    second_person(client, live)
    login(client, "lea")
    assert post(client, CARTE + "/lieu/l7/actualiser", {}).status_code == 200  # la borne est par compte


def test_reading_fiches_and_events_is_bounded_per_account(world):  # noqa: F811
    client, live, _maps = rated(world)
    codes = [client.get(CARTE + ("/lieu/l7" if i % 2 else "/evenements?near=" + ANNECY)).status_code
             for i in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429
    assert client.get(CARTE + f"/lieux?near={ANNECY}").status_code == 200  # une liste, qui ne lit que les caches, non
    second_person(client, live)
    login(client, "lea")
    assert client.get(CARTE + "/lieu/l7").status_code == 200


# ── les événements ──


def test_events_are_looked_for_around_a_point_a_zone_a_period_and_themes(world):  # noqa: F811
    client, _live, maps = rated(world)
    got = client.get(CARTE + f"/evenements?near={ANNECY}&radius=12000&start=2026-11-21&end=2026-11-22"
                             "&themes=concerts,fetes&limit=10")
    assert got.status_code == 200, got.text
    body = got.json()
    assert [e["id"] for e in body["events"]] == [FETE.id, CONCERT.id]
    concert = body["events"][1]
    assert set(concert) == {"id", "name", "start", "end", "when_text", "place", "lat", "lon", "distance_m", "themes",
                            "free", "price", "photo"}
    assert concert["when_text"] == "dim. 22 nov. · 18:00–19:30" and concert["photo"] == TOURISM_PHOTO
    assert concert["free"] is False and concert["distance_m"] > 0
    assert body["coverage"] == {"ready": True, "cells": 4, "loaded": 4, "oldest": ms("2026-11-18T03:00:00Z"),
                                "note": ""}
    [asked] = [x for x in maps.calls if x[0] == "events"]
    assert asked[3] == 12_000 and str(asked[4]) == "2026-11-21" and asked[6] == frozenset({"concerts", "fetes"})
    assert ("tourism_coverage", (45.8992, 6.1294), None, 12_000, False) in maps.calls  # au même rayon
    free = client.get(CARTE + "/evenements?bbox=6.0,45.8,6.3,46.0&free=1").json()
    assert [e["id"] for e in free["events"]] == [FETE.id]
    maps.tourism_cover = replace(maps.tourism_cover, loaded=1,
                                 note="Cette zone n'est lue qu'en partie (cases lues : 1 sur 4) : la suite se lit "
                                      "à la prochaine recherche, ou ce soir.")
    partial = client.get(CARTE + f"/evenements?near={ANNECY}").json()["coverage"]
    assert partial["loaded"] == 1 and "en partie" in partial["note"]
    for bad, field in (("radius=100", "radius"), ("radius=100001", "radius"), ("start=demain", "start"),
                       ("start=2026-11-22&end=2026-11-21", "end"), ("start=2026-01-01&end=2027-06-01", "end"),
                       ("themes=cinema", "themes"), ("limit=51", "limit")):
        refused = client.get(CARTE + f"/evenements?near={ANNECY}&" + bad)
        assert refused.status_code == 400 and field in refused.json()["fields"], bad
    assert client.get(CARTE + "/evenements").status_code == 400  # ni point, ni zone, ni nom


def test_an_event_fiche_says_its_dates_where_and_who_wrote_it(world):  # noqa: F811
    client, _live, _maps = rated(world)
    fiche = client.get(CARTE + f"/evenement/{CONCERT.id}").json()
    assert fiche["event"]["name"] == "Quatuor du lac" and fiche["venue"] == "Bonlieu" and fiche["venue_place"] == "n900"
    assert fiche["dates"] == [{"start": "2026-11-22T18:00:00+01:00", "end": "2026-11-22T19:30:00+01:00",
                               "text": "dim. 22 nov. · 18:00–19:30", "days": []}]
    assert fiche["attribution"] == "DATAtourisme · Lac Annecy Tourisme, mis à jour le 10 novembre 2026"
    assert fiche["licence"] == "Licence Ouverte 2.0" and fiche["photos"][0]["path"].endswith(TOURISM_PHOTO)
    assert fiche["address"].startswith("1 rue Jean Jaurès") and fiche["merged"] == 1
    for ident in ("e:aaaaaaaa-0000-0000-0000-000000000099", "e:pas-un-uuid", "l7"):
        assert client.get(CARTE + f"/evenement/{ident}").status_code == 404, ident


# ── les photos ──


def test_a_photo_is_served_by_its_reference_alone_with_private_cache_headers(world):  # noqa: F811
    client, _live, maps = rated(world)
    got = client.get(CARTE + f"/photo/{PHOTO}")
    assert got.status_code == 200 and got.content == PNG and got.headers["content-type"] == "image/png"
    assert got.headers["cache-control"] == "private, max-age=86400"
    assert got.headers["x-content-type-options"] == "nosniff"
    asked = len(maps.calls)
    assert client.get(CARTE + f"/photo/{TOURISM_PHOTO}").status_code == 404  # aucune source ne la connaît
    for bad in ("p:123", "https:%2F%2Fevil.example%2Fx.png", "p:" + "A" * 32, "%2E%2E"):
        assert client.get(CARTE + f"/photo/{bad}").status_code == 404, bad
    assert [x for x in maps.calls[asked:] if x[0] == "photo"] == [("photo", TOURISM_PHOTO)]  # rien d'autre n'est parti
    assert "default-src 'none'" in got.headers["content-security-policy"]
    # seules des images qui ne portent rien d'actif se servent, quoi que dise la source : ni SVG, ni page
    for data, media in ((b"<svg onload=alert(1)>", "image/svg+xml"), (b"<html>", "text/html")):
        maps.photos[PHOTO] = (data, media)
        assert client.get(CARTE + f"/photo/{PHOTO}").status_code == 502, media


def test_a_coverage_without_cells_and_a_list_without_place_still_answer(world):  # noqa: F811
    client, _live, maps = rated(world)
    maps.reviews_cover = ReviewsCoverage(False, note="Les avis ne sont pas réglés (aucune clé Google).")
    body = client.get(CARTE + "/lieux?bbox=6.0,45.8,6.3,46.0&cat=manger").json()
    assert body["reviews"] == {"ready": False, "cells": 0, "loaded": 0, "oldest": 0,
                               "note": "Les avis ne sont pas réglés (aucune clé Google)."}
    assert ("reviews_coverage", None, (6.0, 45.8, 6.3, 46.0)) in maps.calls


def test_nothing_of_this_is_open_without_an_account(world):  # noqa: F811
    client, live, _backend = world
    maps = live.kernel.ports["maps"] = FakeMaps(places=RATED)
    for path in ("/lieu/l7", f"/evenements?near={ANNECY}", f"/evenement/{CONCERT.id}", f"/photo/{PHOTO}",
                 "/lieux?near=ici"):
        assert client.get(CARTE + path).status_code == 401, path
    assert client.post(CARTE + "/lieu/l7/actualiser", json={}).status_code == 401
    assert maps.calls == [] and maps.preloads == []


def test_what_she_looked_for_among_events_opens_for_you_alone(world):  # noqa: F811
    client, live, _maps = rated(world)
    found = [{"id": CONCERT.id, "name": "Quatuor du lac", "start": CONCERT.start, "end": CONCERT.end,
              "when_text": CONCERT.when_text, "place": CONCERT.place, "lat": CONCERT.lat, "lon": CONCERT.lon}]
    append(client, live, [c.LOOKED.draft(person="user_1", handle="user_1", what=c.LOOK_EVENTS,
                                         query=Content.of("Événements · ce week-end · autour de toi", level=2),
                                         found=Content.of(json.dumps(found), level=2))], emitter=c.OWNER)
    [look] = journal(live, c.LOOKED)
    got = client.get(f"{CARTE}/regards/{look.seq}").json()
    assert got["what"] == "evenements" and got["events"] == found and got["places"] == [] and got["route"] is None
    second_person(client, live)
    login(client, "lea")
    assert client.get(f"{CARTE}/regards/{look.seq}").status_code == 404
