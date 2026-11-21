"""L'index des lieux tiré de l'extrait OpenStreetMap (ADR 0244) : ``mika carte lieux --depuis …osm.pbf`` écrit le
schéma 2 — un lieu par objet nommé d'une sorte connue (nœud, voie fermée ou ouverte, multipolygone), placé sans
garder la position de tous les nœuds (des tranches), cartographié deux fois compté une, ce qui déborde de la zone
laissé ; puis la recherche filtrée (ouvert maintenant, terrasse, végétarien, cuisine) et la fiche d'un lieu.

Un petit extrait écrit au vol par pyosmium, autour de Lille ; « maintenant » est un mardi soir de novembre."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import osmium
import pytest

from mika.adapters.maps import osm as om
from mika.adapters.maps import places as pl
from mika.adapters.maps import tags as osm_tags
from mika.adapters.maps.config import PlacesConfig
from mika.adapters.maps.desk import MapsDesk
from mika.adapters.maps.hours import PARIS
from mika.app import cli
from mika.ports.maps import PlaceHit, extras

TUESDAY_EVENING = datetime(2026, 11, 17, 20, 15, tzinfo=PARIS)
LILLE = (50.6365, 3.0635)
STAMP = "2026-11-16T21:22:36Z"

RESTAURANT_HOURS = "Tu-Sa 12:00-14:00,19:00-22:30; Su 12:00-14:30; Mo off"
#: les nœuds non étiquetés des voies : leurs identifiants tombent dans des tranches différentes (``NODE_SLICE`` réduit)
PARK = {101: (50.640, 3.040), 1102: (50.640, 3.050), 2103: (50.646, 3.050), 3104: (50.646, 3.040)}
VIEW = {105: (50.630, 3.060), 106: (50.632, 3.064), 1107: (50.633, 3.070)}
MARGAUX = {110: (50.6390, 3.0705), 111: (50.6390, 3.0707), 112: (50.6392, 3.0707), 113: (50.6392, 3.0705)}
MUSEUM_BUILDING = {120: (50.6412, 3.0650), 121: (50.6412, 3.0653), 122: (50.6414, 3.0653)}
WOOD_A = {130: (50.700, 3.000), 131: (50.700, 3.010), 1132: (50.710, 3.010)}
WOOD_B = {1133: (50.710, 3.000), 2134: (50.705, 2.995)}


def node(nid: int, at: tuple[float, float], **tags: str) -> osmium.osm.mutable.Node:
    return osmium.osm.mutable.Node(id=nid, location=(at[1], at[0]), tags=tags, version=1)


def way(wid: int, refs: list[int], **tags: str) -> osmium.osm.mutable.Way:
    return osmium.osm.mutable.Way(id=wid, nodes=refs, tags=tags, version=1)


def write_extract(path: Path, *, box: tuple[float, float, float, float] | None = (2.9, 50.55, 3.2, 50.75)) -> Path:
    """Un extrait : des lieux habités, des points d'intérêt, des voies fermées et ouvertes, un multipolygone, un bac
    lointain, des objets sans nom ou d'une sorte qu'on ne garde pas."""
    path.parent.mkdir(parents=True, exist_ok=True)
    header = osmium.io.Header()
    if box is not None:
        header.add_box(osmium.osm.Box(*box))
    header.set("osmosis_replication_timestamp", STAMP)
    pois = [
        node(1, (50.6365, 3.0635), place="city", name="Lille", population="236234"),
        node(2, (50.6500, 3.0250), place="town", name="Lambersart"),
        node(10, (50.6408, 3.0628), amenity="restaurant", name="La Table de la Treille", cuisine="regional;french",
             opening_hours=RESTAURANT_HOURS, outdoor_seating="yes", **{"diet:vegetarian": "limited"},
             wheelchair="yes", phone="+33 3 20 00 00 00", website="table-treille.exemple.fr",
             **{"addr:housenumber": "12", "addr:street": "Rue de la Monnaie", "addr:postcode": "59800",
                "addr:city": "Lille"}),
        node(11, (50.6345, 3.0590), amenity="restaurant", name="Pizzeria Il Gabbiano", cuisine="italian;pizza",
             opening_hours="Mo-Su 11:30-14:00,18:30-23:00", outdoor_seating="yes", takeaway="yes",
             **{"diet:vegetarian": "yes"}),
        node(12, (50.6430, 3.0560), amenity="cafe", name="Café des Remparts", opening_hours="Mo-Fr 08:00-18:00"),
        node(13, (50.6380, 3.0600), natural="tree", name="Le Grand Chêne"),  # une sorte qu'on ne garde pas
        node(14, (50.6370, 3.0610), amenity="restaurant"),  # sans nom
        node(15, (52.2538, -6.3366), amenity="ferry_terminal", name="Berth 2"),  # le bout d'un bac, en Irlande
        node(16, (50.6413, 3.0651), tourism="museum", name="Musée de l'Hospice Comtesse", wikidata="Q3329717",
             wikipedia="fr:Musée de l'Hospice Comtesse", opening_hours="We-Su 10:00-18:00; Mo 14:00-18:00"),
    ]
    loose = {**PARK, **VIEW, **MARGAUX, **MUSEUM_BUILDING, **WOOD_A, **WOOD_B}
    nodes = sorted([*pois, *(node(nid, at) for nid, at in loose.items())], key=lambda n: n.id)
    ways = [
        way(30, [101, 1102, 2103, 3104, 101], leisure="park", name="Parc de la Citadelle"),
        way(31, [105, 106, 1107], tourism="viewpoint", name="Belvédère de la Deûle"),  # ouverte : son milieu
        way(32, [110, 111, 112, 113, 110], amenity="restaurant", name="Chez Margaux", cuisine="french",
            opening_hours="Tu-Sa 19:00-23:00", **{"diet:vegan": "yes"}, building="yes"),
        way(33, [120, 121, 122, 120], tourism="museum", name="Musée de l'hospice Comtesse", building="yes"),
        way(34, [9001, 9002, 9003, 9001], amenity="parking", name="Parking Fantôme"),  # ses nœuds manquent
        way(50, [130, 131, 1132]),
        way(51, [1132, 1133, 2134, 130]),
    ]
    relations = [
        osmium.osm.mutable.Relation(id=60, members=[("w", 50, "outer"), ("w", 51, "outer")], version=1,
                                    tags={"type": "multipolygon", "natural": "wood", "name": "Bois de la Deûle"}),
        osmium.osm.mutable.Relation(id=61, members=[("w", 31, "")], version=1,
                                    tags={"type": "route", "tourism": "attraction", "name": "Un parcours"}),
    ]
    return write_objects(path, nodes, ways, relations, header)


def write_objects(path: Path, nodes: list, ways: list, relations: list, header: osmium.io.Header | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with osmium.SimpleWriter(str(path), header=header or osmium.io.Header(), overwrite=True) as w:
        for obj in nodes:
            w.add_node(obj)
        for obj in ways:
            w.add_way(obj)
        for obj in relations:
            w.add_relation(obj)
    return path


@pytest.fixture
def built(tmp_path, monkeypatch) -> om.OsmBuilt:
    monkeypatch.setattr(om, "NODE_SLICE", 1_000)  # trois tranches pour quelques nœuds
    src = write_extract(tmp_path / "cartes" / "lille.osm.pbf")
    return om.build(src, tmp_path / "cartes" / "lieux.db")


@pytest.fixture
def index(tmp_path, built) -> pl.Places:
    return pl.Places(tmp_path, lambda: PlacesConfig(), now=lambda: TUESDAY_EVENING)


def _rows(tmp_path: Path) -> dict[str, tuple]:
    db = sqlite3.connect(tmp_path / "cartes" / "lieux.db")
    try:
        return {r[0]: r[1:] for r in db.execute(
            "SELECT name, kind, category, lat, lon, weight, town, osm, features, cuisine, hours, tags FROM place")}
    finally:
        db.close()


# ── construire ──

def test_named_objects_of_known_kinds_are_kept_once_each_where_they_are(tmp_path, built):
    rows = _rows(tmp_path)
    assert set(rows) == {"Lille", "Lambersart", "La Table de la Treille", "Pizzeria Il Gabbiano",
                         "Café des Remparts", "Musée de l'Hospice Comtesse", "Parc de la Citadelle",
                         "Belvédère de la Deûle", "Chez Margaux", "Bois de la Deûle"}
    # ni l'arbre, ni le restaurant sans nom, ni le bac en Irlande, ni le parking sans nœuds, ni le parcours
    park = rows["Parc de la Citadelle"]
    assert park[:2] == ("park", "nature") and park[6] == "w30"
    assert (park[2], park[3]) == pytest.approx((50.643, 3.045), abs=1e-6)  # le centre de ses quatre coins
    view = rows["Belvédère de la Deûle"]
    assert (view[2], view[3]) == pytest.approx(VIEW[106], abs=1e-6)  # une voie ouverte : son nœud du milieu
    wood = rows["Bois de la Deûle"]
    assert wood[6] == "r60" and wood[:2] == ("wood", "nature")
    # le centre des nœuds de ses deux contours (leurs jointures comptent pour chacun)
    corners = [WOOD_A[130], WOOD_A[131], WOOD_A[1132], WOOD_A[1132], WOOD_B[1133], WOOD_B[2134], WOOD_A[130]]
    assert (wood[2], wood[3]) == pytest.approx((sum(p[0] for p in corners) / 7, sum(p[1] for p in corners) / 7),
                                               abs=1e-6)
    museum = rows["Musée de l'Hospice Comtesse"]  # son point et son bâtiment : un lieu, le plus renseigné
    assert museum[6] == "n16" and museum[:2] == ("museum", "voir")
    treille = rows["La Table de la Treille"]
    assert treille[5] == "Lille" and treille[8] == "regional;french" and treille[9] == RESTAURANT_HOURS
    assert json.loads(treille[10])["addr:street"] == "Rue de la Monnaie"
    assert rows["Lille"][4] > rows["Lambersart"][4] > rows["Café des Remparts"][4]  # l'importance
    assert rows["Musée de l'Hospice Comtesse"][4] > rows["Café des Remparts"][4]


def test_a_build_says_what_it_read_left_out_and_how_it_placed_ways(tmp_path, built):
    assert built.count == 10 and built.nodes == 6 and built.ways == 5 and built.relations == 1
    assert built.unnamed == 1 and built.unplaced == 1 and built.twins == 1
    assert built.slices == 5 and built.needed == len({*PARK, *VIEW, *MARGAUX, *MUSEUM_BUILDING, *WOOD_A, *WOOD_B,
                                                       9001, 9002, 9003})
    assert built.categories == {"manger": 4, "voir": 2, "nature": 2, "villes": 2}
    assert built.extract == STAMP
    db = sqlite3.connect(tmp_path / "cartes" / "lieux.db")
    meta = dict(db.execute("SELECT key, value FROM meta").fetchall())
    boxes = db.execute("SELECT count(*) FROM place_box").fetchone()[0]
    db.close()
    assert meta["version"] == pl.DETAILED_VERSION and meta["extract"] == STAMP and meta["count"] == "10"
    assert meta["source"] == "lille.osm.pbf" and boxes == 10
    w, s, e, n = (float(v) for v in meta["bounds"].split(","))
    assert 2.99 < w and e < 3.08 and 50.62 < s and n < 50.72  # la zone de ses lieux, sans le bac
    assert not list((tmp_path / "cartes").glob("lieux.db.*"))  # ni le partiel, ni les nœuds rangés


def test_a_town_comes_from_its_node_never_from_a_boundary(tmp_path):
    """Un lieu habité vient de son nœud : la limite administrative d'un quartier (``type=boundary`` avec
    ``place=suburb``) n'en fait pas un second, et le contour d'un quartier à un kilomètre de son nœud non plus."""
    ring = {201: (50.620, 3.040), 202: (50.620, 3.055), 203: (50.630, 3.055), 204: (50.630, 3.040)}
    old_town = {211: (50.648, 3.062), 212: (50.648, 3.072), 213: (50.656, 3.072)}
    nodes = [node(1, (50.6248, 3.0512), place="suburb", name="Wazemmes"),
             node(2, (50.6441, 3.0603), place="suburb", name="Vieux-Lille"),
             *(node(nid, at) for nid, at in sorted({**ring, **old_town}.items()))]
    ways = [way(40, [201, 202, 203, 204, 201]),
            way(41, [211, 212, 213, 211], place="neighbourhood", name="Vieux-Lille")]
    boundary = osmium.osm.mutable.Relation(id=70, members=[("w", 40, "outer")], version=1, tags={
        "type": "boundary", "boundary": "administrative", "admin_level": "10", "place": "suburb",
        "name": "Wazemmes"})
    got = om.build(write_objects(tmp_path / "cartes" / "quartiers.osm.pbf", nodes, ways, [boundary]),
                   tmp_path / "cartes" / "lieux.db")
    assert got.relations == 0 and got.twins == 1 and got.count == 2
    rows = _rows(tmp_path)
    assert {name: row[6] for name, row in rows.items()} == {"Wazemmes": "n1", "Vieux-Lille": "n2"}


def test_an_extract_without_a_zone_keeps_everything_it_places(tmp_path):
    src = write_extract(tmp_path / "cartes" / "sans-zone.osm.pbf", box=None)
    got = om.build(src, tmp_path / "cartes" / "lieux.db")
    assert got.count == 11 and got.slices == 1  # le bac aussi ; une seule tranche, sans la réduire


def test_a_failed_build_leaves_the_index_in_place(tmp_path, monkeypatch):
    out = tmp_path / "cartes" / "lieux.db"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"l'ancien")
    with pytest.raises(pl.BuildFailed, match="pas là"):
        om.build(tmp_path / "cartes" / "absent.osm.pbf", out)
    (tmp_path / "cartes" / "abime.osm.pbf").write_bytes(b"\x00\x00\x00\x0dpas un extrait" * 50)
    with pytest.raises(pl.BuildFailed, match="extrait"):
        om.build(tmp_path / "cartes" / "abime.osm.pbf", out)
    monkeypatch.setattr(om, "osmium", None)
    with pytest.raises(pl.BuildFailed, match="pyosmium") as missing:
        om.build(write_extract(tmp_path / "cartes" / "lille.osm.pbf"), out)
    assert "cartes" in str(missing.value)
    assert out.read_bytes() == b"l'ancien" and not out.with_name("lieux.db.partiel").exists()


def test_the_kind_table_speaks_the_kinds_the_engine_knows():
    known = {kind for _key, _label, kinds in pl.CATEGORIES for kind in kinds} | {"airport"}
    for key, kinds in om.OSM_KINDS:
        assert set(kinds.values()) <= known, key
    assert om.pick({"amenity": "restaurant", "name": "  Chez\nToi  "}) == ("restaurant", "Chez Toi")
    assert om.pick({"tourism": "hotel", "amenity": "restaurant", "name": "Hôtel du Lac"})[0] == "hotel"
    assert om.pick({"aeroway": "aerodrome", "iata": "LIL", "name": "Lille-Lesquin"})[0] == "airport"
    assert om.pick({"name:fr": "Bruges", "name": "Brugge", "place": "city"}) == ("city", "Bruges")
    assert om.pick({"amenity": "bench", "name": "Banc"}) is None and om.pick({"amenity": "cafe"}) is None


# ── chercher ──

async def test_open_now_keeps_what_its_hours_say_is_open(index):
    hits = await index.search("", near=LILLE, category="manger", limit=10, open_now=True)
    assert {h.name for h in hits} == {"La Table de la Treille", "Pizzeria Il Gabbiano", "Chez Margaux"}
    treille = next(h for h in hits if h.name == "La Table de la Treille")
    assert (treille.open_state, treille.open_text) == ("open", "Ouvert · ferme à 22:30")
    everything = await index.search("", near=LILLE, category="manger", limit=10)
    cafe = next(h for h in everything if h.name == "Café des Remparts")
    assert (cafe.open_state, cafe.open_text) == ("closed", "Fermé · ouvre demain 08:00")
    assert [h.distance_m for h in everything] == sorted(h.distance_m for h in everything)


async def test_features_and_cuisine_filter_in_the_index(index):
    terrace = await index.search("", near=LILLE, limit=10, features=frozenset({"terrasse"}))
    assert {h.name for h in terrace} == {"La Table de la Treille", "Pizzeria Il Gabbiano"}
    both = await index.search("", near=LILLE, limit=10, features=frozenset({"terrasse", "emporter"}))
    assert [h.name for h in both] == ["Pizzeria Il Gabbiano"]
    vegan = await index.around(*LILLE, 5_000, features=frozenset({"vegan"}))
    assert [h.name for h in vegan] == ["Chez Margaux"]
    for asked in ("italian", "italienne", "Italienne", "pizza"):
        assert [h.name for h in await index.search("", near=LILLE, cuisine=asked)] == ["Pizzeria Il Gabbiano"]
    assert await index.search("", near=LILLE, cuisine="japonaise") == []
    named = await index.search("treille", features=frozenset({"accessible"}), open_now=True)
    assert [h.name for h in named] == ["La Table de la Treille"]
    with pytest.raises(ValueError, match="filtre inconnu"):
        await index.search("", near=LILLE, features=frozenset({"piscine"}))


async def test_a_hit_says_what_the_index_knows_of_it(index):
    hit = (await index.search("gabbiano"))[0]
    assert hit.osm == "n11" and hit.cuisine == "Italienne, pizza"
    assert hit.tags == ("terrasse", "vegetarien", "emporter")
    assert hit.rating is None and hit.reviews is None and hit.price == "" and hit.photo == ""
    town = (await index.search("lille", category="villes"))[0]
    assert town.open_state == "" and extras(town) == {"osm": "n1"}  # sans horaires : rien à dire


async def test_a_place_reads_its_osm_facts_in_french(index):
    hit = (await index.search("treille"))[0]
    detail = await index.place(hit.id)
    assert detail is not None and detail.hit.name == "La Table de la Treille" and detail.hit.open_state == "open"
    facts = detail.osm
    assert facts is not None and facts.id == "n10" and facts.url == "https://www.openstreetmap.org/node/10"
    assert facts.address == "12 Rue de la Monnaie, 59800 Lille" and facts.phone == "03 20 00 00 00"
    assert facts.website == "https://table-treille.exemple.fr" and facts.extract == STAMP
    assert facts.hours == RESTAURANT_HOURS
    assert facts.hours_text == "mar.–sam. 12:00–14:00, 19:00–22:30 · dim. 12:00–14:30 · lun. fermé"
    assert dict(facts.facts) == {"Cuisine": "régionale, française", "Horaires": facts.hours_text,
                                 "Adresse": facts.address, "Téléphone": "03 20 00 00 00", "Site": facts.website,
                                 "Terrasse": "oui", "Végétarien": "quelques plats", "Fauteuil roulant": "accessible"}
    assert [k for k, _v in facts.facts][:2] == ["Cuisine", "Horaires"]
    assert detail.tourism is None and detail.reviews is None and detail.events == ()  # les autres sources : vides


async def test_a_place_is_found_by_its_osm_object_too(index):
    museum = await index.place("n16")
    assert museum is not None and museum.osm is not None
    assert museum.osm.wikidata == "Q3329717"
    assert museum.osm.wikipedia == "https://fr.wikipedia.org/wiki/Musée_de_l'Hospice_Comtesse"
    park = await index.place("w30")
    assert park is not None and park.hit.name == "Parc de la Citadelle" and park.osm.url.endswith("/way/30")
    assert (await index.place("r60")).hit.name == "Bois de la Deûle"
    for unknown in ("n13", "w34", "l99999", "x1", "", "l1; DROP TABLE place"):
        assert await index.place(unknown) is None


async def test_without_any_rating_min_rating_keeps_nothing_and_sort_keeps_the_distance(tmp_path, built):
    desk = MapsDesk(tmp_path, lambda: PlacesConfig(), lambda: None, clock=lambda: TUESDAY_EVENING)  # type: ignore
    plain = await desk.search("", near=LILLE, category="manger", limit=10)
    ranked = await desk.search("", near=LILLE, category="manger", limit=10, sort="rating")
    assert [h.id for h in ranked] == [h.id for h in plain]  # aucune note (ADR 0250) : l'ordre de la distance
    assert await desk.search("", near=LILLE, category="manger", limit=10, min_rating=4.0) == []  # sans note : écarté
    assert [h.name for h in await desk.around(*LILLE, 5_000, open_now=True, cuisine="french")] == \
        ["La Table de la Treille", "Chez Margaux"]
    assert (await desk.place("n11")).hit.name == "Pizzeria Il Gabbiano"
    with pytest.raises(ValueError, match="ordre"):
        await desk.search("", near=LILLE, sort="prix")
    with pytest.raises(ValueError, match="note"):
        await desk.search("", near=LILLE, min_rating=7)
    await desk.close()


def test_the_console_says_the_index_has_details(index):
    facts = dict(index.describe())
    assert "10 lieux" in facts["Index des lieux"].replace(" ", " ") and "lille.osm.pbf" in facts["Index des lieux"]
    assert "16 novembre 2026" in facts["Index des lieux"] and "horaires" in facts["Détails"]
    assert index.detailed() and index.info().schema == 2


def test_the_command_reads_the_format_from_the_extension(tmp_path, capsys, monkeypatch):
    write_extract(tmp_path / "cartes" / "france-latest.osm.pbf")
    assert cli.main(["--data", str(tmp_path), "carte", "lieux"]) == 0  # sans --depuis : l'extrait, puisqu'il est là
    said = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert said["ok"] is True and said["lieux"] == 10 and said["source"] == "france-latest.osm.pbf"
    assert said["extrait"] == STAMP and said["tranches"] == 1 and said["mémoire_max_mo"] > 0
    (tmp_path / "cartes" / "notes.txt").write_text("rien")
    assert cli.main(["--data", str(tmp_path), "carte", "lieux", "--depuis", "cartes/notes.txt"]) == 1
    said = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert said["ok"] is False and ".osm.pbf" in said["erreur"]


# ── un lieu, sérialisé ──

def test_a_hit_carries_its_extras_only_when_known():
    bare = PlaceHit("l1", "Annecy", "town", "Ville", "villes", 45.9, 6.13)
    assert extras(bare) == {}
    full = PlaceHit("l2", "Gabbiano", "restaurant", "Restaurant", "manger", 50.6, 3.06, osm="n11", open_state="open",
                    open_text="Ouvert · ferme à 23:00", cuisine="Italienne", rating=4.5, reviews=612, price="€€",
                    photo="p:abc", tags=("terrasse",))
    assert extras(full) == {"osm": "n11", "open_state": "open", "open_text": "Ouvert · ferme à 23:00",
                            "cuisine": "Italienne", "rating": 4.5, "reviews": 612, "price": "€€", "photo": "p:abc",
                            "tags": ["terrasse"]}


@pytest.mark.parametrize(("tags", "named"), [
    ({"diet:vegan": "only"}, ("vegetarien", "vegan")), ({"diet:vegan": "yes"}, ("vegetarien", "vegan")),
    ({"diet:vegan": "limited"}, ("vegetarien", "vegan")), ({"diet:vegetarian": "yes"}, ("vegetarien",)),
    ({"diet:vegan": "no"}, ()), ({"diet:vegan": "only", "diet:vegetarian": "no"}, ("vegan",)),
])
def test_what_is_vegan_is_vegetarian_too(tags, named):
    """R1-15 : « végétarien » écartait un lieu tagué ``diet:vegan=only`` sans ``diet:vegetarian`` (l'usage d'OSM pour
    un lieu vegan) : tout plat vegan est végétarien. Un ``diet:vegetarian=no`` explicite reste ce qu'il dit."""
    assert osm_tags.features_named(osm_tags.features_of(tags)) == named
