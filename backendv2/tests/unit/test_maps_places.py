"""L'index des lieux (ADR 0194) : tiré des tuiles d'une archive (``mika carte lieux``), cherché sans que rien ne
sorte — par le nom, autour d'un point, dans une zone, le long d'un trajet. Des tuiles écrites à la main (un petit
encodeur du format Mapbox Vector Tile) : des points d'intérêt, des lieux habités, un calque à sauter, un point qui
déborde de sa tuile, une suite de tuiles qui partagent leur contenu, une tuile abîmée."""

from __future__ import annotations

import gzip
import math
import os
import sqlite3
import struct
from pathlib import Path

import pytest
from pmtiles.tile import Compression, TileType, tileid_to_zxy, zxy_to_tileid
from pmtiles.writer import Writer

from mika.adapters.maps import places as pl
from mika.adapters.maps.config import PlacesConfig
from mika.adapters.maps.mvt import read_points
from mika.ports.maps import MapsUnavailable

Z = 15
EXTENT = 4096


# ── un petit encodeur du format Mapbox Vector Tile ──

def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b, n = n & 0x7F, n >> 7
        out.append(b | 0x80 if n else b)
        if not n:
            return bytes(out)


def _field(number: int, wire: int, payload: bytes | int) -> bytes:
    key = _varint(number << 3 | wire)
    if wire == 0:
        return key + _varint(payload)  # type: ignore[arg-type]
    return key + _varint(len(payload)) + payload  # type: ignore[arg-type]


def _zigzag(n: int) -> int:
    return n << 1 if n >= 0 else (-n << 1) - 1


def _value(v: object) -> bytes:
    if isinstance(v, str):
        return _field(1, 2, v.encode())
    if isinstance(v, bool):
        return _field(7, 0, int(v))
    if isinstance(v, int):
        return _field(5, 0, v)
    return _varint(3 << 3 | 1) + struct.pack("<d", v)


def layer(name: str, features: list[tuple[dict[str, object], list[tuple[int, int]], int]],
          extent: int = EXTENT) -> bytes:
    keys: list[str] = []
    values: list[object] = []
    body = b""
    for props, points, kind in features:
        tags: list[int] = []
        for k, v in props.items():
            if k not in keys:
                keys.append(k)
            if (type(v), v) not in [(type(x), x) for x in values]:
                values.append(v)
            tags += [keys.index(k), [(type(x), x) for x in values].index((type(v), v))]
        geometry = [1 | len(points) << 3] if kind == 1 else [1 | 1 << 3]
        cursor = (0, 0)
        for i, (x, y) in enumerate(points):
            if kind != 1 and i == 1:
                geometry.append(2 | (len(points) - 1) << 3)
            geometry += [_zigzag(x - cursor[0]), _zigzag(y - cursor[1])]
            cursor = (x, y)
        if kind == 3:
            geometry.append(7 | 1 << 3)
        feature = _field(2, 2, b"".join(_varint(t) for t in tags)) + _field(3, 0, kind) + \
            _field(4, 2, b"".join(_varint(g) for g in geometry))
        body += _field(2, 2, feature)
    body = _field(15, 0, 2) + _field(1, 2, name.encode()) + body + \
        b"".join(_field(3, 2, k.encode()) for k in keys) + b"".join(_field(4, 2, _value(v)) for v in values) + \
        _field(5, 0, extent)
    return _field(3, 2, body)


def tile_of(lat: float, lon: float) -> tuple[int, int, int, int]:
    """La tuile du zoom 15 d'un point, et sa place dans la tuile."""
    n = 2 ** Z
    fx = (lon + 180) / 360 * n
    fy = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    x, y = int(fx), int(fy)
    return x, y, int((fx - x) * EXTENT), int((fy - y) * EXTENT)


SEVRIER = (45.8640, 6.1420)
ANNECY = (45.8992, 6.1294)
CAMPING = (45.8601, 6.1450)
#: à 40 km de tout : la plage d'une suite de tuiles qui partagent leur contenu
FAR = (45.5, 6.6)


def poi(name: str | None, kind: str, at: tuple[int, int], min_zoom: int = 15, **more: object):
    props: dict[str, object] = {"kind": kind, "min_zoom": min_zoom, **more}
    if name is not None:
        props["name"] = name
    return props, [at], 1


def place(name: str, kind: str, detail: str, at: tuple[int, int], min_zoom: int, rank: int):
    return {"name": name, "kind": kind, "kind_detail": detail, "min_zoom": min_zoom, "population_rank": rank,
            "population": 0}, [at], 1


def tiles() -> dict[int, bytes]:
    """Les tuiles du zoom 15 (par identifiant), en clair."""
    out: dict[int, bytes] = {}
    sx, sy, spx, spy = tile_of(*SEVRIER)
    cx, cy, cpx, cpy = tile_of(*CAMPING)
    assert (sx, sy) == (cx, cy), "le camping et le village dans la même tuile"
    out[zxy_to_tileid(Z, sx, sy)] = (
        layer("buildings", [({"kind": "building"}, [(10, 10), (20, 10), (20, 20)], 3)]) +
        layer("pois", [poi("Camping de l'Horizon", "camp_site", (cpx, cpy), 14),
                       poi("Boulangerie Dupont", "bakery", (cpx + 40, cpy + 40)),
                       poi("Café du Lac", "cafe", (spx + 30, spy - 30), 16, **{"name:fr": "Café du Lac"}),
                       poi(None, "tree", (100, 100)),  # sans nom : laissé
                       poi("Le Grand Chêne", "tree", (120, 100)),  # nommé, d'une sorte qu'on ne garde pas
                       poi("École du Lac", "school", (140, 100)),
                       poi("Débord", "restaurant", (200, -40))]) +  # dans la marge d'une voisine : compte chez elle
        layer("places", [place("Sévrier", "locality", "village", (spx, spy), 11, 7),
                         place("Les Hameaux", "locality", "hamlet", (spx + 300, spy + 300), 13, 2),
                         place("La Maison", "locality", "isolated_dwelling", (spx - 300, spy), 14, 1)]))
    ax, ay, apx, apy = tile_of(*ANNECY)
    out[zxy_to_tileid(Z, ax, ay)] = (
        layer("places", [place("Annecy", "locality", "city", (apx, apy), 6, 12)]) +
        layer("pois", [poi("Musée-Château d'Annecy", "museum", (apx + 50, apy + 80), 13)]))
    # trois tuiles qui se suivent, d'un seul contenu : sa plage dans chacune
    fx, fy, _px, _py = tile_of(*FAR)
    first = zxy_to_tileid(Z, fx, fy)
    shared = layer("pois", [poi("Plage des Mouettes", "beach", (2048, 2048), 12)])
    for t in range(3):
        out[first + t] = shared
    out[first + 10] = b"\x1a\xff\xff\xff"  # abîmée : comptée, laissée
    return out


def write_archive(path: Path, content: dict[int, bytes], *, kind: TileType = TileType.MVT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        w = Writer(f)
        for tile_id, data in sorted(content.items()):
            w.write_tile(tile_id, gzip.compress(data, mtime=0))
        w.finalize({"tile_type": kind, "tile_compression": Compression.GZIP, "min_lon_e7": int(6.0e7),
                    "min_lat_e7": int(45.4e7), "max_lon_e7": int(6.7e7), "max_lat_e7": int(46.0e7),
                    "center_zoom": 12, "center_lon_e7": int(6.13e7), "center_lat_e7": int(45.9e7)}, {})
    return path


@pytest.fixture
def index(tmp_path) -> pl.Places:
    src = write_archive(tmp_path / "cartes" / "alpes.pmtiles", tiles())
    pl.build(src, tmp_path / "cartes" / "lieux.db")
    return pl.Places(tmp_path, lambda: PlacesConfig())


# ── le lecteur de tuiles ──

def test_a_tile_gives_the_points_of_the_layers_asked_and_skips_the_rest():
    raw = layer("buildings", [({"kind": "building"}, [(1, 1), (5, 1), (5, 5)], 3)]) + \
        layer("pois", [poi("Ici", "cafe", (10, 20)), poi("Là", "bar", (4095, 0)), poi("Dehors", "bar", (4096, 7)),
                       poi("Avant", "bar", (-1, 7))])
    got = read_points(raw, ("pois",))
    assert [(p.x, p.y, p.props["name"]) for p in got] == [(10, 20, "Ici"), (4095, 0, "Là")]  # le débord : laissé
    assert all(p.layer == "pois" and p.extent == EXTENT for p in got)
    only = read_points(raw, ("pois",), keys={"name"}, accept=lambda _layer, props: props["name"] == "Là")
    assert [p.props for p in only] == [{"name": "Là"}]  # seulement les clés demandées, seulement ce qu'on garde
    assert read_points(raw, ("roads",)) == []
    for broken in (raw[:-3], b"\x1a\x05abc", b"\x1b"):
        with pytest.raises(ValueError):
            read_points(broken, ("pois",))


# ── construire ──

def test_the_index_keeps_named_places_of_known_kinds_once_each(tmp_path, index):
    db = pl._connect(tmp_path / "cartes" / "lieux.db")
    rows = {name: (kind, category, lat, lon, weight, town) for name, kind, category, lat, lon, weight, town in
            db.execute("SELECT name, kind, category, lat, lon, weight, town FROM place WHERE name != "
                       "'Plage des Mouettes'")}
    beaches = db.execute("SELECT lat, lon, town FROM place WHERE name = 'Plage des Mouettes' ORDER BY lon").fetchall()
    meta = dict(db.execute("SELECT key, value FROM meta").fetchall())
    db.close()
    assert set(rows) == {"Camping de l'Horizon", "Boulangerie Dupont", "Café du Lac", "Sévrier", "Les Hameaux",
                         "Annecy", "Musée-Château d'Annecy"}  # ni l'arbre, ni l'école, ni la maison isolée, ni le débord
    kind, category, lat, lon, weight, town = rows["Camping de l'Horizon"]
    assert (kind, category, town) == ("camp_site", "dormir", "Sévrier") and weight == 3
    assert (lat, lon) == pytest.approx(CAMPING, abs=1e-4)
    assert rows["Sévrier"][:2] == ("village", "villes") and rows["Sévrier"][5] == ""  # un village : près de rien
    assert rows["Sévrier"][4] == 17 - 11 + 7  # l'importance : le zoom où il paraît, sa population
    assert rows["Les Hameaux"][5] == "Sévrier"  # un hameau : près d'une commune
    assert rows["Annecy"][4] > rows["Sévrier"][4]
    assert len({(lat, lon) for lat, lon, _town in beaches}) == 3  # une plage par tuile de la suite, chacune à sa place
    assert all(town == "" for _lat, _lon, town in beaches)  # rien d'habité à moins de 15 km
    assert meta["count"] == "10" and meta["version"] == pl.SCHEMA_VERSION and meta["source"] == "alpes.pmtiles"


def test_a_build_says_its_progress_what_it_left_out_and_what_it_could_not_read(tmp_path):
    src = write_archive(tmp_path / "cartes" / "alpes.pmtiles", tiles())
    said: list[str] = []
    got = pl.build(src, tmp_path / "cartes" / "lieux.db", say=said.append)
    assert got.count == 10 and got.zoom == Z and got.broken == 1 and got.tiles == 6
    assert got.categories == {"dormir": 1, "courses": 1, "manger": 1, "villes": 3, "voir": 1, "nature": 3}
    assert ("pois:tree", 1) in got.skipped and ("places:isolated_dwelling", 1) in got.skipped
    assert said and "6 tuiles au zoom 15" in said[0]
    assert not (tmp_path / "cartes" / "lieux.db.partiel").exists()


def test_a_failed_build_leaves_the_index_in_place(tmp_path):
    out = tmp_path / "cartes" / "lieux.db"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"l'ancien")
    with pytest.raises(pl.BuildFailed, match="pas là"):
        pl.build(tmp_path / "cartes" / "absente.pmtiles", out)
    images = write_archive(tmp_path / "cartes" / "images.pmtiles", {0: b"png"}, kind=TileType.PNG)
    with pytest.raises(pl.BuildFailed, match="vectorielles"):
        pl.build(images, out)
    (tmp_path / "cartes" / "pas-une-carte.pmtiles").write_bytes(b"rien" * 100)
    with pytest.raises(pl.BuildFailed, match="PMTiles"):
        pl.build(tmp_path / "cartes" / "pas-une-carte.pmtiles", out)
    assert out.read_bytes() == b"l'ancien" and not out.with_name("lieux.db.partiel").exists()


# ── chercher ──

async def test_a_place_is_found_by_its_name_without_its_accents(index):
    got = await index.search("sevrier")
    assert got[0].name == "Sévrier" and got[0].kind_fr == "Village" and got[0].category == "villes"
    assert got[0].id.startswith("l") and got[0].distance_m is None
    by_town = await index.search("boulangerie sevrier")  # le nom, et la ville où il est
    assert [h.name for h in by_town] == ["Boulangerie Dupont"]
    assert (await index.search("annecy"))[0].name == "Annecy"  # la ville avant ce qui porte son nom
    assert await index.search("introuvable") == []


async def test_an_unreadable_query_finds_nothing_and_never_raises(index):
    for text in ('"', 'camp" OR NEAR(', "AND", "*", "l'", "-", "(((", "camp*ing", "NOT camping"):
        assert isinstance(await index.search(text), list)
    assert [h.name for h in await index.search("l'horizon")] == ["Camping de l'Horizon"]


async def test_the_nearest_come_first_and_a_category_filters(index):
    near = await index.search("", near=SEVRIER, category="dormir")
    assert [h.name for h in near] == ["Camping de l'Horizon"] and 300 < near[0].distance_m < 600
    anything = await index.search("", near=SEVRIER, limit=3)
    assert anything[0].name == "Sévrier" and anything[0].distance_m < 5
    assert [h.distance_m for h in anything] == sorted(h.distance_m for h in anything)
    assert await index.search("", near=SEVRIER, category="inconnue") == []
    framed = await index.search("", bbox=(6.12, 45.89, 6.14, 45.91))  # ouest, sud, est, nord : Annecy
    assert {h.name for h in framed} == {"Annecy", "Musée-Château d'Annecy"}
    assert (await index.search("", category="villes"))[0].name == "Annecy"  # sans rien d'autre : les plus importants
    whole = await index.search("", bbox=(-5.0, 41.0, 10.0, 51.0), category="villes")  # la France : par importance
    assert [h.name for h in whole][:1] == ["Annecy"]
    with pytest.raises(ValueError):
        await index.search("", bbox=(6.2, 45.8, 6.1, 45.9))


async def test_around_a_point_within_a_radius(index):
    got = await index.around(*SEVRIER, 600)
    assert {h.name for h in got} >= {"Sévrier", "Camping de l'Horizon", "Café du Lac"}
    assert all(h.distance_m <= 600 for h in got) and "Annecy" not in {h.name for h in got}


async def test_along_a_route_in_the_order_they_are_met(index):
    line = [ANNECY, (45.88, 6.135), SEVRIER, (45.85, 6.15)]
    got = await index.along(line, corridor_m=1500)
    names = [h.name for h in got]
    assert names.index("Musée-Château d'Annecy") < names.index("Camping de l'Horizon")
    assert "Plage des Mouettes" not in names  # à 40 km
    assert [h.along_m for h in got] == sorted(h.along_m for h in got)
    assert all(h.distance_m <= 1500 for h in got)
    camping = next(h for h in got if h.name == "Camping de l'Horizon")
    assert camping.along_m > 3000  # après les 4 km d'Annecy à Sévrier, à peu près
    assert [h.name for h in await index.along(line, corridor_m=1500, category="dormir")] == ["Camping de l'Horizon"]
    assert await index.along([], corridor_m=1500) == []


def test_a_long_line_is_simplified_to_a_few_hundred_points():
    line = [(45.0 + i * 1e-4, 6.0 + math.sin(i / 50) * 1e-3) for i in range(4000)]
    kept = pl.simplify(line, 5.0, most=100)
    assert kept[0] == 0 and kept[-1] == len(line) - 1 and len(kept) <= 100
    assert kept == sorted(set(kept))


async def test_without_an_index_the_search_says_how_to_build_it(tmp_path):
    places = pl.Places(tmp_path, lambda: PlacesConfig())
    assert not places.ready() and places.summary() == {"ready": False, "count": 0, "built": ""}
    with pytest.raises(MapsUnavailable, match="mika carte lieux"):
        await places.search("camping")
    (tmp_path / "cartes").mkdir()
    (tmp_path / "cartes" / "lieux.db").write_bytes(b"pas une base" * 100)
    assert not places.ready() and "illisible" in places.info().reason


async def test_a_rebuilt_index_is_read_at_the_next_search(tmp_path, index):
    assert (await index.search("camping"))[0].name == "Camping de l'Horizon"
    sx, sy, spx, spy = tile_of(*SEVRIER)
    src = write_archive(tmp_path / "cartes" / "autre.pmtiles", {
        zxy_to_tileid(Z, sx, sy): layer("pois", [poi("Camping des Pins", "camp_site", (spx, spy))])})
    pl.build(src, tmp_path / "cartes" / "lieux.db")
    os.utime(tmp_path / "cartes" / "lieux.db", ns=(1, 1))
    assert [h.name for h in await index.search("camping")] == ["Camping des Pins"]
    assert index.summary()["count"] == 1


def test_the_console_says_what_the_index_holds(index):
    facts = dict(index.describe())
    assert "10 lieux" in facts["Index des lieux"].replace(" ", " ") and "alpes.pmtiles" in facts["Index des lieux"]
    assert facts["Construit"].startswith("le ") and "Zone (ouest, sud → est, nord)" in facts
    summary = index.summary()
    assert summary["ready"] is True and summary["count"] == 10 and str(summary["built"]).endswith("Z")


def test_every_category_kind_has_its_french_name():
    assert [key for key, _label in pl.LABELS] == ["manger", "dormir", "voir", "nature", "route", "courses", "sante",
                                                  "sortir", "services", "villes"]
    missing = [kind for _key, _label, kinds in pl.CATEGORIES for kind in kinds if kind not in pl.KIND_FR]
    assert not missing
    seen: dict[str, str] = {}
    for key, _label, kinds in pl.CATEGORIES:
        for kind in kinds:
            assert kind not in seen, f"{kind} dans {seen.get(kind)} et {key}"
            seen[kind] = key


def test_tile_ids_of_a_run_follow_each_other():
    """La suite de tuiles du jeu d'essai se suit bien (sinon le test de la suite ne prouverait rien)."""
    fx, fy, _px, _py = tile_of(*FAR)
    first = zxy_to_tileid(Z, fx, fy)
    assert len({tileid_to_zxy(first + t) for t in range(3)}) == 3


async def test_what_was_found_nearby_is_kept_when_the_search_widens(tmp_path, monkeypatch):
    """Trop peu de résultats tout près : la recherche s'élargit, et garde ce qu'elle avait trouvé — un nom long (moins
    bien noté par le texte) à côté ne se perd pas parmi les noms courts d'ailleurs."""
    sx, sy, spx, spy = tile_of(*SEVRIER)
    fx, fy, _px, _py = tile_of(*FAR)
    src = write_archive(tmp_path / "cartes" / "plages.pmtiles", {
        zxy_to_tileid(Z, sx, sy): layer("pois", [poi("Petite plage municipale de Sévrier au bord du lac", "beach",
                                                     (spx, spy))]),
        zxy_to_tileid(Z, fx, fy): layer("pois", [poi("Plage", "beach", (100, 100)), poi("Plage Sud", "beach",
                                                                                         (300, 300))])})
    pl.build(src, tmp_path / "cartes" / "lieux.db")
    places = pl.Places(tmp_path, lambda: PlacesConfig())
    monkeypatch.setattr(pl, "TEXT_CANDIDATES", 1)
    monkeypatch.setattr(pl, "TEXT_RADII_KM", (1,))
    got = await places.search("plage", near=SEVRIER, limit=3)
    assert got[0].name.startswith("Petite plage municipale") and got[0].distance_m < 50
    assert "Plage" in [h.name for h in got]  # et ce que la zone élargie a trouvé


async def test_a_place_mapped_twice_is_kept_once(tmp_path):
    """OpenStreetMap porte parfois un lieu deux fois (son point, son bâtiment) : même nom, même catégorie, à quelques
    mètres — un seul lieu ; deux homonymes éloignés, ou d'une autre catégorie, restent deux."""
    sx, sy, spx, spy = tile_of(*SEVRIER)
    src = write_archive(tmp_path / "cartes" / "doubles.pmtiles", {zxy_to_tileid(Z, sx, sy): layer("pois", [
        poi("Musée de l'Hospice Comtesse", "museum", (1000, 1000)),
        poi("Musée de l'hospice comtesse", "museum", (1010, 1005)),  # le même, son bâtiment
        poi("Musée de l'Hospice Comtesse", "museum", (3000, 3000)),  # un homonyme, loin
        poi("Musée de l'Hospice Comtesse", "cafe", (1004, 1000))])})  # son café : une autre catégorie
    got = pl.build(src, tmp_path / "cartes" / "lieux.db")
    assert got.count == 3 and got.categories == {"voir": 2, "manger": 1}


async def test_along_a_long_straight_leg_finds_what_lies_on_the_route(tmp_path):
    """Lille → Paris à vol d'oiseau (sans itinéraires) : un seul tronçon de 200 km. Sa grande boîte compte des
    centaines d'hôtels plus importants, loin de la route ; ceux du couloir, plus modestes, sont trouvés quand même —
    le tronçon se cherche par morceaux de la taille du couloir."""
    out = tmp_path / "cartes" / "lieux.db"
    out.parent.mkdir(parents=True)
    db = sqlite3.connect(out)
    db.executescript(pl.SCHEMA)
    rows, n = [], 0
    for i in range(400):  # les importants, dans la boîte du tronçon mais loin de la route : ses deux coins
        n += 1
        lat, lon = (50.1 + (i % 20) * 0.025, 2.36 + (i // 20) * 0.01) if i < 200 else \
            (48.88 + (i % 20) * 0.025, 2.85 + ((i - 200) // 20) * 0.02)
        rows.append((n, f"Grand Hôtel {i}", "hotel", "dormir", lat, lon, 12))
    for i in range(6):  # les modestes, sur la route
        n += 1
        t = (i + 1) / 7
        rows.append((n, f"Auberge de la route {i}", "guest_house", "dormir", 50.63 + (48.86 - 50.63) * t,
                     3.06 + (2.35 - 3.06) * t, 2))
    db.executemany("INSERT INTO place(id, name, kind, category, lat, lon, weight) VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    db.executemany("INSERT INTO place_box(id, lat0, lat1, lon0, lon1) VALUES (?, ?, ?, ?, ?)",
                   [(r[0], r[4], r[4], r[5], r[5]) for r in rows])
    db.execute("INSERT INTO place_text(place_text) VALUES ('rebuild')")
    db.execute(pl.RANK_INDEX)
    db.executemany("INSERT INTO meta(key, value) VALUES (?, ?)", [
        ("version", pl.SCHEMA_VERSION), ("count", str(len(rows))), ("built", "2026-11-05T00:00:00"),
        ("source", "cartes/essai.pmtiles"), ("zoom", "15"), ("bounds", "2.0,48.0,5.0,51.0")])
    db.commit()
    db.close()
    places = pl.Places(tmp_path, lambda: PlacesConfig())
    got = await places.along([(50.63, 3.06), (48.86, 2.35)], corridor_m=5_000, category="dormir", limit=10)
    assert sorted(h.name for h in got) == [f"Auberge de la route {i}" for i in range(6)]
    assert [h.along_m for h in got] == sorted(h.along_m for h in got)
