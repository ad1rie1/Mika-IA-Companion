"""Carte, lieux, itinéraires et voyages par l'API par personne (ADR 0194, 0195, 0196) : à travers le vrai serveur, sur
une carte jouée en mémoire (``tests/fixtures/fake_maps.py``).

- ce qui n'est pas branché se dit (503, en mots) ; ce qui l'est passe par le port de la carte, et par lui seul ;
- un paramètre faux est refusé (400), jamais ramené dans ses bornes ;
- un voyage est à qui l'a créé : une autre personne ne le voit ni ne le touche (le même 404) ; ce qu'on en fait passe
  par les actions de la console, dédoublonné par la clé d'envoi ; ce qu'elle y a ajouté se dit ``"by": "mika"`` ;
- un jour se réordonne au meilleur ordre, un voyage a ses tronçons, ses lieux sur la route, son GPX ;
- ce qu'elle a cherché ou montré s'ouvre pour toi seule, et plus une fois oublié.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from mika.contracts import trips as c
from mika.kernel.events import Content
from mika.ports.maps import decode_polyline6
from tests.fixtures.fake_maps import BUILT_MS, HORIZON, TALLOIRES, FakeMaps
from tests.protocol.test_moi_mail import API, append, journal, login, second_person
from tests.protocol.test_web import bootstrap, csrf, world  # noqa: F401 — fixture partagée

CARTE, VOYAGES = API + "/carte", API + "/voyages"
LAC = "45.8992,6.1294;45.8406,6.2128"


def plugged(world, maps: FakeMaps | None = None):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    live.kernel.ports["maps"] = maps if maps is not None else FakeMaps()
    return client, live, live.kernel.ports["maps"]


def post(client, path: str, body: dict, key: str = ""):
    headers = csrf(client)
    if key:
        headers["Idempotency-Key"] = key
    return client.post(path, json=body, headers=headers)


def new_trip(client, title: str = "Les Alpes", **more) -> str:
    r = post(client, VOYAGES, {"title": title, "start": "2027-04-03", "mode": "voiture", **more})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def stop(client, trip: str, name: str, lat: float, lon: float, day: int = 1, **more) -> str:
    r = post(client, f"{VOYAGES}/{trip}/arrets", {"name": name, "lat": lat, "lon": lon, "day": day, **more})
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ── la carte ──


def test_what_is_not_plugged_says_so(world):  # noqa: F811
    client, live, _ = world
    assert client.get(CARTE).status_code == 401
    bootstrap(client)
    # le serveur tel qu'il démarre : ni adresses ni itinéraires (rien ne sort sans le choix d'un opérateur)
    started = client.get(CARTE).json()
    assert started["addresses"] == {"ready": False} and started["routing"]["ready"] is False
    assert client.get(CARTE + f"/itineraire?points={LAC}").status_code == 503
    maps = live.kernel.ports["maps"] = FakeMaps(places_on=False, addresses_on=False, routing_on=False)
    got = client.get(CARTE)
    body = got.json()
    assert got.headers["cache-control"] == "no-store"
    assert body["places"]["ready"] is False and body["addresses"] == {"ready": False}
    assert body["routing"] == {"ready": False, "provider": "", "modes": ["voiture", "velo", "pied"],
                               "avoid": ["peages", "autoroutes", "ferries"]}
    places = client.get(CARTE + "/lieux?q=Annecy")
    assert places.status_code == 503 and "Lieux et adresses" in places.json()["error"]
    route = client.get(CARTE + f"/itineraire?points={LAC}")
    assert route.status_code == 503
    assert route.json()["error"] == "Les itinéraires ne sont pas réglés : Réglages › Canaux › Itinéraires."
    assert client.get(CARTE + "/adresses?q=Place de la Concorde").status_code == 503
    assert maps.calls == []  # rien n'est parti
    live.kernel.ports.pop("maps")
    bare = client.get(CARTE).json()
    assert bare["places"] == {"ready": False, "count": 0, "built": 0} and bare["categories"] == []
    unplugged = client.get(CARTE + "/lieux?q=Annecy")
    assert unplugged.status_code == 503 and unplugged.json()["error"] == "La carte n'est pas branchée sur ce serveur."


def test_places_addresses_routes_and_orders_come_from_this_server(world):  # noqa: F811
    client, live, maps = plugged(world)
    info = client.get(CARTE).json()
    assert info["places"] == {"ready": True, "count": 6, "built": BUILT_MS}
    assert info["routing"]["ready"] and info["routing"]["provider"] == "Valhalla (essai)"
    assert {"id": "dormir", "label": "Dormir"} in info["categories"]
    near = client.get(CARTE + "/lieux?cat=dormir&near=45.8406,6.2128&limit=5").json()["places"]
    assert [p["id"] for p in near] == ["l4", "l3"] and near[1]["distance_m"] > 0 and near[1]["town"] == "Sévrier"
    zone = client.get(CARTE + "/lieux?cat=dormir&bbox=6.0,45.7,6.4,46.0").json()["places"]
    assert {p["id"] for p in zone} == {"l3", "l4"}
    named = client.get(CARTE + "/lieux?q=camping horizon").json()["places"]
    assert [p["name"] for p in named] == [HORIZON.name]
    for bad, field in (("q=" + "x" * 201, "q"), ("q=Annecy&cat=plage", "cat"), ("bbox=6,45,7", "bbox"),
                       ("q=Annecy&limit=0", "limit"), ("near=45.8,abc", "near")):
        refused = client.get(CARTE + "/lieux?" + bad)
        assert refused.status_code == 400 and field in refused.json()["fields"], bad
    assert client.get(CARTE + "/lieux").status_code == 400  # ni nom, ni point, ni zone
    address = client.get(CARTE + "/adresses?q=Place de la Concorde Paris").json()["places"]
    assert address[0]["id"] == "a:1" and address[0]["kind"] == "address"
    assert client.get(CARTE + "/adresses?q=ab").status_code == 400

    route = client.get(CARTE + f"/itineraire?points={LAC}&mode=velo&avoid=peages").json()
    assert route["distance_m"] > 0 and route["has_toll"] is False and route["provider"] == "Valhalla (essai)"
    assert len(decode_polyline6(route["legs"][0]["shape"])) == 3 and route["legs"][0]["steps"][0]["text"]
    assert ("route", ((45.8992, 6.1294), (45.8406, 6.2128)), "velo", frozenset({"peages"})) in maps.calls
    for bad in ("points=45.8,6.1", "points=" + ";".join(["45.8,6.1"] * 21), f"points={LAC}&mode=avion",
                f"points={LAC}&avoid=metro"):
        assert client.get(CARTE + "/itineraire?" + bad).status_code == 400, bad

    four = "45.0,6.0;45.3,6.3;45.1,6.1;45.4,6.4"
    assert client.get(CARTE + f"/ordre?points={four}").json() == {"order": [0, 2, 1, 3]}
    maps.order = [1, 0, 2, 3]  # le départ n'est plus à sa place : illisible
    assert client.get(CARTE + f"/ordre?points={four}").status_code == 502

    along = client.get(CARTE + f"/le-long?points={HORIZON.lat},{HORIZON.lon};{TALLOIRES.lat},{TALLOIRES.lon}"
                               "&cat=voir").json()
    assert along["route"] is True and [p["id"] for p in along["places"]] == ["l5"]
    assert along["places"][0]["along_m"] is not None and along["places"][0]["distance_m"] <= 5_000
    maps.routing_on = False
    line = f"points={HORIZON.lat},{HORIZON.lon};{TALLOIRES.lat},{TALLOIRES.lon}&cat=voir"
    straight = client.get(CARTE + f"/le-long?{line}&corridor=200").json()
    assert straight["route"] is False and straight["places"] == []  # à vol d'oiseau, et un couloir étroit
    narrow = client.get(CARTE + f"/le-long?{line}&corridor=100")
    assert narrow.status_code == 400 and "corridor" in narrow.json()["fields"]  # refusé, jamais ramené à 200


# ── tes voyages ──


def test_your_trips_are_yours_alone(world):  # noqa: F811
    client, live, _ = plugged(world)
    assert client.post(VOYAGES, json={"title": "Sans jeton"}).status_code == 403  # sans CSRF
    first = post(client, VOYAGES, {"title": "Les Alpes", "start": "2027-04-03", "avoid": ["peages"]}, key="k-1")
    again = post(client, VOYAGES, {"title": "Les Alpes", "start": "2027-04-03", "avoid": ["peages"]}, key="k-1")
    assert first.status_code == again.status_code == 200, first.text
    trip = first.json()["id"]
    assert again.json()["deduped"] is True and again.json()["id"] == trip  # redit : le même voyage
    assert len(journal(live, c.CREATED)) == 1
    listed = client.get(VOYAGES).json()["trips"]
    assert listed == [{"id": trip, "title": "Les Alpes", "start": "2027-04-03", "mode": "voiture",
                       "avoid": ["peages"], "days": 1, "stops": 0, "updated": listed[0]["updated"], "mika": False}]
    detail = client.get(f"{VOYAGES}/{trip}").json()
    assert detail["days"] == [{"n": 1, "date": "2027-04-03", "stops": []}] and detail["title"] == "Les Alpes"
    assert post(client, f"{VOYAGES}/{trip}", {"title": "Les Alpes du sud", "avoid": []}).status_code == 200
    changed = client.get(f"{VOYAGES}/{trip}").json()
    assert changed["title"] == "Les Alpes du sud" and changed["avoid"] == [] and changed["start"] == "2027-04-03"
    assert post(client, f"{VOYAGES}/{trip}", {"title": "  "}).status_code == 400
    assert post(client, f"{VOYAGES}/{trip}", {}).status_code == 400
    late = post(client, f"{VOYAGES}/{trip}", {"start": "demain"})
    assert late.status_code == 400 and "start" in late.json()["fields"]
    assert post(client, VOYAGES, {"title": "x" * 121}).status_code == 400

    second_person(client, live)
    login(client, "lea")
    assert client.get(VOYAGES).json() == {"trips": []}
    assert client.get(f"{VOYAGES}/{trip}").status_code == 404
    for path, body in ((f"{VOYAGES}/{trip}", {"title": "À moi"}), (f"{VOYAGES}/{trip}/supprimer", {}),
                       (f"{VOYAGES}/{trip}/arrets", {"name": "Lyon", "lat": 45.76, "lon": 4.83, "day": 1})):
        assert post(client, path, body).status_code == 404, path
    assert client.get(f"{VOYAGES}/{trip}/gpx").status_code == 404
    login(client, "adrien")
    assert client.get(f"{VOYAGES}/abc").status_code == 404
    assert post(client, f"{VOYAGES}/{trip}/supprimer", {}).status_code == 200
    assert client.get(f"{VOYAGES}/{trip}").status_code == 404 and client.get(VOYAGES).json() == {"trips": []}


def test_stops_are_added_moved_noted_ordered_and_removed(world):  # noqa: F811
    client, live, maps = plugged(world)
    trip = new_trip(client)
    a = stop(client, trip, "Annecy", 45.0, 6.0)
    b = stop(client, trip, "Le <b>Belvédère</b> & co", 45.3, 6.3, note="Au lever du soleil")
    cc = stop(client, trip, "Sévrier", 45.1, 6.1)
    d = stop(client, trip, "Talloires", 45.4, 6.4, kind="Village")
    for bad in ({"name": "Ailleurs", "lat": 95, "lon": 0, "day": 1}, {"name": "Ailleurs", "lat": "45", "lon": 6},
                {"name": "Ailleurs", "lat": 45, "lon": 6, "day": 31}, {"name": "", "lat": 45, "lon": 6}):
        assert post(client, f"{VOYAGES}/{trip}/arrets", bad).status_code == 400, bad

    order = post(client, f"{VOYAGES}/{trip}/ordre", {"day": 1})
    assert order.status_code == 200 and order.json()["order"] == [a, cc, b, d]  # départ et arrivée fixes
    day = client.get(f"{VOYAGES}/{trip}").json()["days"][0]["stops"]
    assert [s["id"] for s in day] == [a, cc, b, d] and day[2]["note"] == "Au lever du soleil"
    assert day[3]["kind"] == "Village" and day[0]["by"] == "toi" and day[0]["lat"] == 45.0

    both = post(client, f"{VOYAGES}/{trip}/arrets/{b}", {"day": 2, "index": 0, "note": "Le soir"}, key="geste-1")
    assert both.status_code == 200, both.text
    moved = client.get(f"{VOYAGES}/{trip}").json()["days"]
    assert [s["id"] for s in moved[1]["stops"]] == [b] and moved[1]["stops"][0]["note"] == "Le soir"
    assert moved[1]["date"] == "2027-04-04"
    assert post(client, f"{VOYAGES}/{trip}/arrets/{b}", {}).status_code == 400
    # un paramètre refusé ne laisse rien à moitié fait : ni déplacé, ni noté
    half = post(client, f"{VOYAGES}/{trip}/arrets/{b}", {"day": 1, "index": 0, "note": "x" * 501})
    assert half.status_code == 400 and "note" in half.json()["fields"]
    assert [s["id"] for s in client.get(f"{VOYAGES}/{trip}").json()["days"][1]["stops"]] == [b]
    assert post(client, f"{VOYAGES}/{trip}/arrets/999/retirer", {}).status_code == 404

    legs = client.get(f"{VOYAGES}/{trip}/trajet").json()
    assert [len(x["legs"]) for x in legs["days"]] == [2, 1] and legs["distance_m"] > 0
    assert legs["days"][1]["legs"][0]["from"] == d and legs["days"][1]["legs"][0]["to"] == b
    assert legs["provider"] == "Valhalla (essai)" and legs["has_toll"] is True
    along = client.get(f"{VOYAGES}/{trip}/sur-la-route?cat=villes&corridor=50000").json()
    assert along["route"] is True and isinstance(along["places"], list)
    assert client.get(f"{VOYAGES}/{trip}/sur-la-route?day=99").status_code == 400

    gpx = client.get(f"{VOYAGES}/{trip}/gpx")
    assert gpx.status_code == 200 and gpx.headers["content-type"].startswith("application/gpx+xml")
    assert gpx.headers["content-disposition"] == f'attachment; filename="voyage-{trip}.gpx"'
    root = ET.fromstring(gpx.content)  # bien formé : le nom échappé
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    names = [w.findtext("g:name", namespaces=ns) for w in root.findall("g:rte/g:rtept", ns)]
    assert names == ["Annecy", "Sévrier", "Talloires", "Le <b>Belvédère</b> & co"]  # ses arrêts, dans l'ordre
    assert root.findtext("g:metadata/g:name", namespaces=ns) == "Les Alpes"
    assert len(root.findall("g:trk/g:trkseg/g:trkpt", ns)) > 4  # et son tracé

    assert post(client, f"{VOYAGES}/{trip}/arrets/{cc}/retirer", {}).status_code == 200
    left = [s["id"] for x in client.get(f"{VOYAGES}/{trip}").json()["days"] for s in x["stops"]]
    assert left == [a, d, b]
    maps.routing_on = False
    assert client.get(f"{VOYAGES}/{trip}/trajet").status_code == 503
    assert len(ET.fromstring(client.get(f"{VOYAGES}/{trip}/gpx").content).findall("g:trk", ns)) == 0


def test_what_she_added_is_pink_and_yours_to_remove(world):  # noqa: F811
    client, live, _ = plugged(world)
    trip = new_trip(client)
    level = 2
    append(client, live, [c.STOP_ADDED.draft(trip=trip, person="user_1", by=c.BY_HER,
                                             name=Content.of("Monastère royal de Brou", level=level),
                                             coords=Content.of("46.199000,5.240000", level=level), day=1,
                                             note=Content.of("sur la route, ça vaut le détour", level=level))],
           emitter=c.OWNER)
    detail = client.get(f"{VOYAGES}/{trip}").json()
    [hers] = detail["days"][0]["stops"]
    assert hers["by"] == "mika" and hers["note"] == "sur la route, ça vaut le détour" and detail["mika"] is True
    assert client.get(VOYAGES).json()["trips"][0]["mika"] is True
    assert post(client, f"{VOYAGES}/{trip}/arrets/{hers['id']}/retirer", {}).status_code == 200
    assert client.get(f"{VOYAGES}/{trip}").json()["days"][0]["stops"] == []


def test_what_she_looked_for_or_showed_opens_for_you_alone(world):  # noqa: F811
    client, live, _ = plugged(world)
    trip = new_trip(client)
    level = 2
    found = [{"id": "l3", "name": HORIZON.name, "kind": "camp_site", "kind_fr": "Camping", "category": "dormir",
              "lat": HORIZON.lat, "lon": HORIZON.lon, "town": "Sévrier", "distance_m": 3800, "along_m": None}]
    route = {"distance_m": 5200, "duration_s": 900, "mode": "velo", "avoid": ["ferries", "inconnu"],
             "shape": "_ibE_seK_seK_seK", "points": found}
    append(client, live, [
        c.LOOKED.draft(person="user_1", handle="user_1", what=c.LOOK_PLACES, query=Content.of("Dormir", level=level),
                       found=Content.of(json.dumps(found), level=level)),
        c.LOOKED.draft(person="user_1", handle="user_1", what=c.LOOK_ROUTE,
                       query=Content.of("Sévrier → Talloires", level=level),
                       found=Content.of(json.dumps(route), level=level)),
        c.SHOWN.draft(person="user_1", handle="user_1", title=Content.of("Où dormir", level=level),
                      places=Content.of(json.dumps(found), level=level), trip=trip, route=True, mode="pied")],
           emitter=c.OWNER)
    places_look, route_look = journal(live, c.LOOKED)
    [shown] = journal(live, c.SHOWN)
    got = client.get(f"{CARTE}/regards/{places_look.seq}").json()
    assert got == {"kind": "look", "title": "Dormir", "what": "lieux", "places": found, "route": None, "trip": "",
                   "at": got["at"]} and got["at"] > 0
    traced = client.get(f"{CARTE}/regards/{route_look.seq}").json()
    assert traced["what"] == "trajet" and traced["route"] == {"mode": "velo", "distance_m": 5200,
                                                              "duration_s": 900, "shape": "_ibE_seK_seK_seK",
                                                              "avoid": ["ferries"]}  # ce qu'elle a évité
    assert traced["places"] == found
    a_map = client.get(f"{CARTE}/regards/{shown.seq}").json()
    assert a_map["kind"] == "map" and a_map["title"] == "Où dormir" and a_map["trip"] == trip
    assert a_map["route"] == {"mode": "pied"}  # un parcours demandé, sans tracé calculé
    assert client.get(f"{CARTE}/regards/{trip}").status_code == 404  # un voyage n'est pas un regard
    second_person(client, live)
    login(client, "lea")
    assert client.get(f"{CARTE}/regards/{places_look.seq}").status_code == 404
    login(client, "adrien")
    client.portal.call(live.kernel.mind.forget, "user_1")
    assert client.get(f"{CARTE}/regards/{places_look.seq}").status_code == 404  # oublié
    assert client.get(VOYAGES).json() == {"trips": []}


def test_numbers_zones_and_dates_out_of_their_bounds_are_refused_in_words(world):  # noqa: F811
    """Un nombre infini, un nombre qui n'est pas entier, une zone plate ou retournée, une date de l'an 9999, une note
    au numéro démesuré : refusés en mots (400, 404) — jamais un 500, jamais une valeur ramenée sans le dire."""
    client, live, _maps = plugged(world)
    trip = new_trip(client)
    for body in ({"day": float("inf")}, {"day": 2.9}):
        got = client.post(f"{VOYAGES}/{trip}/arrets", headers=csrf(client),
                          content=json.dumps({"name": "x", "lat": 45.9, "lon": 6.1, **body}, allow_nan=True))
        assert got.status_code == 400 and "nombre entier" in got.json()["error"], (body, got.text)
    for bbox in ("6,45,5,46", "5,45,6,45", "5,45,5,46"):
        got = client.get(CARTE + f"/lieux?cat=dormir&bbox={bbox}")
        assert got.status_code == 400 and got.json()["fields"] == {"bbox": "ouest,sud,est,nord"}, bbox
    late = post(client, VOYAGES, {"title": "Un jour, peut-être", "start": "9999-12-31"})
    assert late.status_code == 400 and "entre 1900 et 2200" in late.json()["error"]
    changed = post(client, f"{VOYAGES}/{trip}", {"start": "9999-12-31"})
    assert changed.status_code == 400
    assert client.get(CARTE + "/regards/99999999999999999999").status_code == 404


def test_a_day_of_more_stops_than_a_route_takes_is_not_sent_to_be_ordered(world):  # noqa: F811
    client, live, maps = plugged(world)
    trip = new_trip(client)
    for i in range(c.STOPS_MAX // 3 + 1):  # 21 arrêts le même jour
        stop(client, trip, f"Arrêt {i}", 45.80 + i * 0.005, 6.10 + i * 0.005)
    asked = len(maps.calls)
    got = post(client, f"{VOYAGES}/{trip}/ordre", {"day": 1})
    assert got.status_code == 400 and "20 arrêts au plus" in got.json()["error"]
    assert len(maps.calls) == asked  # rien n'est parti


def test_one_person_cannot_hold_the_public_route_server_for_everyone(world):  # noqa: F811
    """Le serveur d'itinéraires public répond une fois par seconde pour tout ce serveur : une personne qui en demande
    à la chaîne est arrêtée (429) bien avant d'en priver les autres, et ses outils à elle."""
    client, live, maps = plugged(world)
    codes = [client.get(CARTE + f"/itineraire?points={LAC}&mode=voiture").status_code for _ in range(21)]
    assert codes[:20] == [200] * 20 and codes[20] == 429
    # une adresse a sa propre borne, plus large : une saisie en cours n'use pas celle des trajets
    assert client.get(CARTE + "/adresses?q=Place de la Concorde").status_code == 200
    second_person(client, live)
    login(client, "lea")
    assert client.get(CARTE + f"/itineraire?points={LAC}").status_code == 200  # la borne est par compte
    typed = [client.get(CARTE + f"/adresses?q=Rue n{i}").status_code for i in range(61)]
    assert typed[:60] == [200] * 60 and typed[60] == 429
    assert client.get(CARTE + f"/itineraire?points={LAC}").status_code == 200  # ses trajets, eux, restent
