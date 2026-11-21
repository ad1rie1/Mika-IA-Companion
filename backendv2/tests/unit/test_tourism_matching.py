"""Le rapprochement des données touristiques et de l'index des lieux d'OpenStreetMap (ADR 0245) : une fiche
DATAtourisme à moins de 150 m d'un lieu au nom qui se ressemble est ce lieu, dont elle enrichit la fiche ; sans
pendant, elle se trouve comme ``t:<uuid>`` — jamais en double d'un lieu de l'index ; un index reconstruit se rapproche
à nouveau ; la fiche d'un lieu montre les événements qui s'y tiennent."""

from __future__ import annotations

import sqlite3

import pytest

from mika.adapters.maps.config import PlacesConfig, RoutingConfig
from mika.adapters.maps.datatourisme import EVENTS, PLACES
from mika.adapters.maps.desk import MapsDesk
from mika.adapters.maps.tourism import TourismBase, likeness, merge_places
from mika.ports.maps import PlaceHit
from tests.fixtures import tourism as tf

LILLE = (50.6365, 3.0635)


@pytest.fixture
async def world(tmp_path):
    index = tf.write_index(tmp_path / "cartes" / "lieux.db")
    sync, tourism, clock, _cfg = tf.make_sync(
        tmp_path, tf.FakeApi({EVENTS: tf.events(), PLACES: tf.restaurants()}), index=index)
    report = await sync.run()
    desk = MapsDesk(tmp_path, PlacesConfig, RoutingConfig, clock=clock)
    yield desk, sync, report, index
    await desk.close()


async def test_a_tourism_place_joins_its_osm_twin_and_enriches_its_fiche(world):
    desk, _sync, report, _index = world
    assert report.twins == 2 and report.venues >= 3
    resort = await desk.place("w100")
    assert resort.osm is not None and resort.hit.name == "Hôtel Barrière Lille"
    assert resort.tourism.id == f"t:{tf.RESORT}" and resort.tourism.author == "Hauts-de-France Tourisme"
    assert "Accueil Vélo" in resort.tourism.labels and resort.tourism.description
    [photo] = resort.tourism.photos
    assert photo.ref.startswith("p:") and photo.credit == "Patrick Messina" and photo.licence == "By-NC-ND 4.0"
    krevette = await desk.place("n101")
    assert krevette.tourism.id == f"t:{tf.KREVETTE}"
    bakery = await desk.place("n102")  # près du Mama Shelter, mais un autre nom : rien
    assert bakery.tourism is None


async def test_a_tourism_place_without_twin_is_found_once_as_t(world):
    desk, _sync, _report, _index = world
    around = await desk.around(LILLE[0], LILLE[1], 5_000, limit=50)
    ids = [h.id for h in around]
    assert f"t:{tf.HILTON}" in ids and f"t:{tf.MAMA}" in ids
    assert f"t:{tf.RESORT}" not in ids and f"t:{tf.KREVETTE}" not in ids  # leur pendant est déjà là
    assert ids.count("l1") == 1  # l'Hôtel Barrière, une fois
    distances = [h.distance_m for h in around]
    assert distances == sorted(distances)
    assert [h.id for h in await desk.search("Barrière", near=LILLE)] == ["l1"]
    [hilton] = await desk.search("Hilton", near=LILLE)
    assert hilton.id == f"t:{tf.HILTON}" and hilton.category == "manger" and hilton.distance_m
    # un filtre que DATAtourisme ne sait pas juger : rien d'elle
    assert all(not h.id.startswith("t:") for h in await desk.around(LILLE[0], LILLE[1], 5_000, limit=50,
                                                                     features=frozenset({"terrasse"})))
    assert all(h.category == "dormir" for h in await desk.search("", near=LILLE, category="dormir"))


async def test_the_fiche_of_a_t_place_is_its_own_or_its_twins(world):
    desk, _sync, _report, _index = world
    hilton = await desk.place(f"t:{tf.HILTON}")
    assert hilton.osm is None and hilton.hit.id == f"t:{tf.HILTON}" and hilton.tourism.id == f"t:{tf.HILTON}"
    resort = await desk.place(f"t:{tf.RESORT}")
    assert resort.hit.id == "l1" and resort.osm is not None and resort.tourism.id == f"t:{tf.RESORT}"
    assert await desk.place("t:00000000-0000-0000-0000-000000000000") is None
    assert await desk.place("t:pas-un-uuid") is None


async def test_a_venue_fiche_shows_the_events_held_there(world):
    desk, _sync, _report, _index = world
    lam = await desk.place("w103")
    names = [e.name for e in lam.events]
    assert "Obsession" in names and names.count("Obsession") == 1
    starts = [e.start for e in lam.events]
    assert starts == sorted(starts)
    colisee = await desk.place("n104")
    assert {"Julien Clerc", "Fabrice Éboué"} <= {e.name for e in colisee.events}


async def test_a_rebuilt_index_is_matched_again(world):
    desk, sync, _report, index = world
    tf.write_index(index, [r for r in tf.LILLE_PLACES if r[0] != "w100"], built="2026-11-18T09:00:00Z")
    assert await sync.rematch()
    ids = [h.id for h in await desk.around(LILLE[0], LILLE[1], 5_000, limit=50)]
    assert f"t:{tf.RESORT}" in ids  # son pendant a disparu de l'index : il revient en ``t:``
    assert not await sync.rematch()  # déjà fait pour cet index
    tf.write_index(index, built="2026-11-18T11:00:00Z")
    assert await sync.rematch()
    assert f"t:{tf.RESORT}" not in [h.id for h in await desk.around(LILLE[0], LILLE[1], 5_000, limit=50)]


def test_a_place_not_yet_matched_never_doubles_one_of_the_list():
    osm = [PlaceHit("l1", "Hôtel Barrière Lille", "hotel", "Hôtel", "dormir", 50.63665, 3.07725, distance_m=900)]
    tourism = [PlaceHit("t:a", "Resort Barrière Lille", "restaurant", "Restaurant", "manger", 50.63659, 3.07717,
                        distance_m=890),
               PlaceHit("t:b", "Hilton Lille", "hotel", "Hôtel", "dormir", 50.63997, 3.07580, distance_m=1200)]
    assert [h.id for h in merge_places(osm, tourism, near=True, limit=10)] == ["l1", "t:b"]
    assert [h.id for h in merge_places(osm, tourism, near=False, limit=1)] == ["l1"]


#: les vrais cas de la sonde du 2026-11-20 (``sonde/data3``, R1-02) : des lieux de l'index aux positions réelles
SONDE_LIEUX = (
    ("n302942324", "Rihour", "station", "services", 50.6356918, 3.0630331),
    ("n8745537418", "Lille-Europe", "station", "services", 50.638983, 3.075714),
    ("n10683165885", "Power Dot - Ibis Styles - Marcq-en-Baroeul", "charging_station", "route", 50.675552, 3.1169334),
    ("n1372584412", "Magasin", "bicycle_rental", "services", 50.6461773, 3.0535298),
    ("n5620628420", "La Place", "cafe", "manger", 50.6369234, 3.0641169),
    ("n9548393322", "Le Septentrion", "restaurant", "manger", 50.7075258, 3.1124489),
    ("n9001441423", "Barrière Lille", "restaurant", "manger", 50.6367635, 3.0772599),
    ("w45911888", "Coq Hardi", "restaurant", "manger", 50.6374053, 3.063623),
    ("n4846431902", "Méert", "pastry", "courses", 50.6377451, 3.0619182),
    ("w94965208", "Euralille", "mall", "courses", 50.6372709, 3.0742867),
    ("w84922920", "Hôtel Casino Barrière Lille", "hotel", "dormir", 50.6364761, 3.0773328),
)
#: les fiches de la sonde : (uuid, nom, classes, lat, lon, le pendant attendu — '' : aucun, elle reste ``t:``)
SONDE_FICHES = (
    ("6c4fb7cf-9afb-30c0-adf5-102682de07ca", "Bouillon Rihour", ["Restaurant", "FoodEstablishment"], 50.635186,
     3.062703, ""),                                                                       # pas la station de métro
    ("74afb398-c11c-3333-8e46-191fadaaef7d", "Novotel Suites Lille Europe", ["Hotel", "Accommodation"], 50.638604,
     3.076783, ""),                                                                       # pas la gare
    ("8cc1fd48-116f-3dde-800e-1b0120a7d050", "Ibis Styles Lille Marcq-en-Baroeul", ["Restaurant"], 50.675534,
     3.116652, ""),                                                                       # pas la borne
    ("b5167bcc-0797-34ae-bf59-c99c52b44043", "Au Chat Qui Dort Lille - Magasin", ["Accommodation"], 50.64592,
     3.05455, ""),                                                                        # pas la location de vélos
    ("8618c6cb-572a-38e7-bcfa-34187ca871bb", "Friterie Meunier - Grand Place", ["Restaurant"], 50.637568, 3.063313,
     ""),                                                                                 # « place » n'est qu'un lieu
    ("ccde72f7-6b50-3a7b-9d5d-c29713cc0f7f", "Parc de la Fondation Prouvost-Septentrion", ["CulturalSite"], 50.70642,
     3.11342, ""),                                                                        # pas le restaurant
    ("51c8f7a1-25e0-3a9f-82b0-136e8d7d05de", "Resort Barrière Lille", ["Hotel", "Restaurant"], 50.636586, 3.077169,
     "n9001441423"),
    ("849e88e9-0ccc-36a6-b151-020738370b6b", "Le Coq Hardi", ["Restaurant"], 50.637383, 3.063598, "w45911888"),
    ("3e50f17b-704f-3337-97bb-d9bc3d7f8bf9", "Restaurant Méert", ["Restaurant"], 50.637718, 3.06187, "n4846431902"),
    ("a7c753ca-bf73-37d6-b53a-a2ac6acfbf0d", "Westfield Euralille", ["FoodEstablishment", "Store"], 50.637194,
     3.074159, "w94965208"),
    ("5570eb99-0dfd-3069-bd47-ed12d9babbea", "Casino Barrière Lille", ["SportsAndLeisurePlace"], 50.636451, 3.077058,
     "w84922920"),                                                                        # le même nom : lui
)


def _place_fiche(uuid: str, name: str, types: list[str], lat: float, lon: float, town: str = "Lille") -> dict:
    """Une fiche de lieu telle que l'API de DATAtourisme la rend (réduite)."""
    return {"uuid": uuid, "label": {"@fr": name}, "type": [*types, "PlaceOfInterest", "PointOfInterest"],
            "isLocatedAt": [{"geo": {"latitude": lat, "longitude": lon},
                             "address": [{"streetAddress": ["1 rue Esquermoise"], "postalCode": "59800",
                                          "addressLocality": town,
                                          "hasAddressCity": {"insee": "59350", "label": {"@fr": town}}}]}],
            "hasBeenCreatedBy": {"legalName": "Hello Lille"}, "lastUpdate": "2025-06-03"}


async def test_a_fiche_never_joins_a_place_of_another_sort_under_a_like_name(tmp_path):
    """La sonde (R1-02) : « Bouillon Rihour » avait pris la station « Rihour », un hôtel la gare de Lille-Europe, un
    autre une borne de recharge — une station, une gare, une borne, une location ne sont le pendant de rien ; sous des
    noms qui ne sont pas les mêmes, la sorte doit aller, et un nom qui n'a en commun qu'un mot de rue (« place ») ne
    suffit pas. Ces fiches restent ``t:``, trouvables ; les bons rapprochements tiennent."""
    index = tf.write_index(tmp_path / "cartes" / "lieux.db", SONDE_LIEUX)
    api = tf.FakeApi({PLACES: [_place_fiche(u, n, t, la, lo) for u, n, t, la, lo, _twin in SONDE_FICHES]},
                     page_size=100)
    cells, tourism, _clock, _cfg = tf.make_cells(tmp_path, api, index=index)
    for cell in {cells.cell(la, lo).key: cells.cell(la, lo) for *_r, la, lo, _t in SONDE_FICHES}.values():
        await cells.load(cell, PLACES, background=True, pages_max=5)
    conn = sqlite3.connect(tourism.path)
    try:
        found = dict(conn.execute("SELECT uuid, twin FROM fiche"))
    finally:
        conn.close()
    assert found == {uuid: twin for uuid, *_r, twin in SONDE_FICHES}
    rihour = PlaceHit("t:6c4f", "Bouillon Rihour", "restaurant", "Restaurant", "manger", 50.635186, 3.062703)
    station = PlaceHit("l1", "Rihour", "station", "Station", "services", 50.6356918, 3.0630331)
    assert [h.id for h in merge_places([station], [rihour], near=False, limit=10)] == ["l1", "t:6c4f"]


#: R3-06 : le cas réel de la sonde (``sonde/data3``) — une agence de location, de la seule classe ``Transport`` ; et,
#: tout près d'autres services, une boutique (d'une sorte inconnue) et une fiche qui ne fait que contenir le nom d'une gare
FRANCE_CARS_LIEUX = (
    ("w77109657", "France Cars", "car_rental", "services", 50.6397202, 3.121817),
    ("n1372584412", "Magasin", "bicycle_rental", "services", 50.6461773, 3.0535298),
    ("n8745537418", "Lille-Europe", "station", "services", 50.638983, 3.075714),
)
FRANCE_CARS, ATELIER, TAXI = ("ef51a71a-68ec-3f6b-b796-15a998a4e45e", "1f2ceb62-a8a0-3bc5-90fc-c7121b0ef8d7",
                              "33333333-0000-4000-8000-000000000001")
FRANCE_CARS_AT = (50.63948, 3.12159)


async def test_a_service_joins_the_service_of_its_name_its_town_aside(tmp_path):
    """R3-06 : « France Cars Villeneuve d'Ascq » était le pendant de « France Cars », une location, au même endroit ;
    la règle 2 l'avait perdu (une location n'est le pendant de rien, et une sorte inconnue jamais sous un nom seulement
    contenu) — deux lignes dans une liste. Un service (une location, un office de tourisme) est le pendant d'un service
    de l'index sous son nom même, la commune qu'il y ajoute mise à part ; jamais sous un nom qui ne fait que contenir
    l'autre (« Taxi Lille Europe » n'est pas la gare), jamais une fiche d'une autre sorte (« Atelier boutique le
    Magasin », cas réel aussi, n'est pas la location de vélos « Magasin »). Une fiche lue avant qu'on connaisse sa
    classe se rejuge à sa sorte d'aujourd'hui."""
    index = tf.write_index(tmp_path / "cartes" / "lieux.db", FRANCE_CARS_LIEUX)
    api = tf.FakeApi({PLACES: [
        _place_fiche(FRANCE_CARS, "France Cars Villeneuve d'Ascq", ["Transport"], *FRANCE_CARS_AT,
                     town="Villeneuve-d'Ascq"),
        _place_fiche(ATELIER, "Atelier boutique le Magasin", ["LocalBusiness", "TastingProvider", "Producer"],
                     50.646007, 3.054946),
        _place_fiche(TAXI, "Taxi Lille Europe", ["Transport"], 50.63905, 3.07560)]}, page_size=100)
    cells, tourism, clock, _cfg = tf.make_cells(tmp_path, api, index=index)
    for at in (FRANCE_CARS_AT, (50.646007, 3.054946), (50.63905, 3.07560)):
        await cells.load(cells.cell(*at), PLACES, background=True, pages_max=5)

    def twins() -> dict[str, str]:
        conn = sqlite3.connect(tourism.path)
        try:
            return dict(conn.execute("SELECT uuid, twin FROM fiche"))
        finally:
            conn.close()

    assert twins() == {FRANCE_CARS: "w77109657", ATELIER: "", TAXI: ""}
    desk = MapsDesk(tmp_path, PlacesConfig, RoutingConfig, clock=clock)
    try:
        assert [h.name for h in await desk.around(*FRANCE_CARS_AT, 300, limit=20)] == ["France Cars"]
    finally:
        await desk.close()
    # une base d'avant : la fiche lue sans sorte (``Transport`` inconnu), rejugée quand la règle change
    conn = sqlite3.connect(tourism.path)
    try:
        conn.execute("UPDATE fiche SET category = '', sort = 'tourism'")
        TourismBase.match(conn, index, everything=True)
        assert dict(conn.execute("SELECT uuid, twin FROM fiche")) == {FRANCE_CARS: "w77109657", ATELIER: "", TAXI: ""}
    finally:
        conn.close()


#: le LaM dans l'index de la sonde (R1-08) : une relation, placée au centre de ses contours, à 154 m du point de ses
#: événements ; et une salle sans adresse dans l'index
LAM_VENUES = (
    ("r17508558", "LaM Lille Métropole - Musée d'Art Moderne, d'Art Comptemporain et d'Art Brut", "museum", "voir",
     50.6375223, 3.150778),
    ("n9000001", "L'Aéronef", "arts_centre", "sortir", 50.636554, 3.074244),
)
LAM_TAGS = '{"addr:housenumber": "1", "addr:street": "Allée du Musée", "addr:city": "Villeneuve-d\'Ascq"}'
OBSESSION_LAM, SINGULIERES, NOEL_LAM, AERONEF, POTERIE = (f"22222222-0000-4000-8000-00000000000{k}"
                                                          for k in range(1, 6))


async def test_a_venue_a_little_further_is_kept_when_the_event_names_it_or_shares_its_address(tmp_path):
    """R1-08 : le LaM est loin du point de ses événements (154 m, au-delà des 60 m) : ils n'avaient pas de lieu. Plus
    loin (300 m au plus), un lieu qui accueille du public reste le leur quand l'événement le nomme en entier
    (« … à l'Aéronef ») ou qu'il est à la même adresse (« 1 allée du Musée », le numéro et la rue de l'index) — jamais
    un autre sans cela, jamais pour un marché."""
    index = tf.write_index(tmp_path / "cartes" / "lieux.db", LAM_VENUES)
    db = sqlite3.connect(index)
    db.execute("UPDATE place SET tags = ? WHERE osm = 'r17508558'", (LAM_TAGS,))
    db.commit()
    db.close()
    lam = (50.637583, 3.148595, "1 allée du Musée VIlleneuve-d'Ascq")
    near_aeronef = (50.6383, 3.0742)
    api = tf.FakeApi({EVENTS: [
        _fiche(OBSESSION_LAM, 'Exposition "Obsession" au LaM', ["FairOrShow"], *lam),
        _fiche(SINGULIERES, "Singulières : artistes, autodidactes, affranchies", ["FairOrShow"], *lam),
        _fiche(NOEL_LAM, "Marché de Noël des créateurs", ["ChristmasMarket"], *lam),
        _fiche(AERONEF, "Concert de Noël à l'Aéronef", ["Concert"], *near_aeronef, "168 avenue Willy Brandt"),
        _fiche(POTERIE, "Exposition de poterie", ["Exhibition"], *near_aeronef, "170 avenue Willy Brandt")]},
        page_size=100)
    cells, tourism, _clock, _cfg = tf.make_cells(tmp_path, api, index=index)
    for at in ((lam[0], lam[1]), near_aeronef):
        await cells.load(cells.cell(*at), EVENTS, background=True, pages_max=5)
    found = {uuid: await tourism.event(uuid) for uuid in (OBSESSION_LAM, SINGULIERES, NOEL_LAM, AERONEF, POTERIE)}
    assert {u: d.venue_place for u, d in found.items()} == {OBSESSION_LAM: "r17508558", SINGULIERES: "r17508558",
                                                            NOEL_LAM: "", AERONEF: "n9000001", POTERIE: ""}
    assert found[SINGULIERES].hit.place.startswith("LaM Lille Métropole")


@pytest.mark.parametrize(("a", "b", "same"), [
    ("Resort Barrière Lille", "Hôtel Barrière Lille", True),
    ("La Table de la Treille", "Restaurant La Table de la Treille", True),
    ("Le Colisée", "Colisée Roubaix", True),
    ("Krevette", "KREVETTE", True),
    ("Mama Shelter", "Boulangerie Paul", False),
    ("Le Bistrot du Coin", "La Petite Table", False),
    ("Hôtel", "Hôtel de Ville", False),
])
def test_names_that_look_alike(a, b, same):
    assert (likeness(a, b) >= 0.75) is same


#: le cas réel de la sonde du 2026-11-18 (ADR 0259) : autour de la place du Concert et de la Grand-Place de Lille
VIEUX_LILLE = (
    ("w1446859731", "La chapelle Notre-Dame d'Annay", "place_of_worship", "voir", 50.6423021, 3.0602179),
    ("r11371717", "Opéra de Lille", "theatre", "sortir", 50.6375261, 3.0651522),
    ("w37545143", "Palais Rihour", "castle", "voir", 50.6355305, 3.0619426),
    ("r1654934", "Place du Général de Gaulle", "attraction", "voir", 50.636933, 3.0640703),
)


def _fiche(uuid: str, name: str, types: list[str], lat: float, lon: float, street: str) -> dict:
    """Une fiche d'événement telle que l'API de DATAtourisme la rend (réduite)."""
    return {"uuid": uuid, "label": {"@fr": name}, "type": [*types, "EntertainmentAndEvent", "Event"],
            "isLocatedAt": [{"geo": {"latitude": lat, "longitude": lon},
                             "address": [{"streetAddress": [street], "postalCode": "59800", "addressLocality": "Lille",
                                          "hasAddressCity": {"insee": "59350", "label": {"@fr": "Lille"}}}]}],
            "takesPlaceAt": [{"startDate": "2026-11-20", "endDate": "2026-12-31", "startTime": "10:00",
                              "endTime": "12:00"}],
            "hasBeenCreatedBy": {"legalName": "Hello Lille"}, "lastUpdate": "2023-12-05"}


MARCHE = "9e2c421b-3db2-3ff8-b109-4bdb1b1cea75"
FAURE = "11111111-0000-4000-8000-000000000001"
OPERA = "11111111-0000-4000-8000-000000000002"
RIHOUR = "11111111-0000-4000-8000-000000000003"
LIVRES = "11111111-0000-4000-8000-000000000004"


async def test_an_event_meets_only_a_place_that_hosts_the_public_never_a_market(tmp_path):
    """« Marché du Vieux-Lille » (place du Concert) avait été rapproché de « La chapelle Notre-Dame d'Annay » : un
    marché, une fête de plein air ne se tiennent dans aucun lieu ; à une adresse qui nomme une place, seul un lieu que
    l'événement nomme est le sien ; ailleurs, le plus proche qui accueille du public (une scène, un château…), jamais
    une place ni une « attraction »."""
    index = tf.write_index(tmp_path / "cartes" / "lieux.db", VIEUX_LILLE)
    api = tf.FakeApi({EVENTS: [
        _fiche(MARCHE, "Marché du Vieux-Lille", ["Market", "SaleEvent"], 50.6425201, 3.0606324, "Place du Concert"),
        _fiche(FAURE, "Fauré en miroir", ["Concert", "MusicEvent"], 50.642575, 3.061549, "Place du concert"),
        _fiche(OPERA, "Visites-concerts de l'opéra autour de l'heure bleue", ["Concert", "Visit"], 50.637375, 3.064694,
               "Place du théâtre"),
        _fiche(RIHOUR, "Rencontre et dédicace avec Guillaume Bonte", ["Congress"], 50.635524, 3.061981, "Palais Rihour"),
        _fiche(LIVRES, "Marché aux livres", ["Market"], 50.63705, 3.06401,
               "Cour intérieure de la Vieille Bourse, Place du Général de Gaulle")]}, page_size=100)
    cells, tourism, _clock, _cfg = tf.make_cells(tmp_path, api, index=index)
    await cells.load(cells.cell(*LILLE), EVENTS, background=True, pages_max=5)
    found = {uuid: await tourism.event(uuid) for uuid in (MARCHE, FAURE, OPERA, RIHOUR, LIVRES)}
    assert {u: d.venue for u, d in found.items()} == {MARCHE: "", FAURE: "", OPERA: "Opéra de Lille",
                                                      RIHOUR: "Palais Rihour", LIVRES: ""}
    assert found[MARCHE].hit.place == "Place du Concert, Lille"  # son adresse dit où il est
    assert found[LIVRES].hit.place.startswith("Cour intérieure de la Vieille Bourse")
    assert found[OPERA].venue_place == "r11371717" and found[OPERA].hit.place == "Opéra de Lille, Lille"
    assert tourism.info().venues == 2
