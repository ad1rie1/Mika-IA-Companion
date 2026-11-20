"""Le rapprochement des données touristiques et de l'index des lieux d'OpenStreetMap (ADR 0245) : une fiche
DATAtourisme à moins de 150 m d'un lieu au nom qui se ressemble est ce lieu, dont elle enrichit la fiche ; sans
pendant, elle se trouve comme ``t:<uuid>`` — jamais en double d'un lieu de l'index ; un index reconstruit se rapproche
à nouveau ; la fiche d'un lieu montre les événements qui s'y tiennent."""

from __future__ import annotations

import pytest

from mika.adapters.maps.config import PlacesConfig, RoutingConfig
from mika.adapters.maps.datatourisme import EVENTS, PLACES
from mika.adapters.maps.desk import MapsDesk
from mika.adapters.maps.tourism import likeness, merge_places
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
