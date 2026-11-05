"""L'index des lieux (ADR 0194) : les points d'intérêt et les lieux habités de la carte, tirés une fois des tuiles de
l'archive (``mika carte lieux``), cherchés ensuite dans un fichier SQLite du dossier de données — par le nom (texte
intégral), autour d'un point, dans une zone, le long d'un trajet (arbre R). Rien ne sort : la recherche ne joint
personne.

**Construire** (``build``) : les tuiles du zoom le plus fin de l'archive (le 15 de Protomaps, où ``pois`` et
``places`` sont complets), chaque contenu décodé une fois, ses points nommés d'une sorte connue (``CATEGORIES``)
écrits par lots dans un fichier à côté (``….partiel``), qui ne prend la place de l'ancien qu'entier — le serveur
l'ouvre alors de lui-même. La mémoire reste bornée : des tableaux pour les entrées de l'archive, des lots de 10 000
lignes, une grille des villes (quelques dizaines de milliers) pour dire près de quoi est chaque lieu.

**Chercher** (``Places``) : une connexion en lecture seule par requête, dans un fil à part (la boucle ne s'arrête
pas) ; un fichier remplacé se lit à la requête suivante, celles en cours finissent sur l'ancien."""

from __future__ import annotations

import asyncio
import math
import os
import re
import sqlite3
import time
import zlib
from array import array
from collections import Counter, OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pmtiles.tile import Compression, TileType, deserialize_header, tileid_to_zxy, zxy_to_tileid

from mika.adapters.maps.config import PlacesConfig
from mika.adapters.maps.mvt import read_points
from mika.adapters.maps.tiles import BROKEN, DIR_MAX_BYTES, read_directory
from mika.ports.maps import MapsUnavailable, PlaceHit

# ── ce qu'on garde ──
#: les lieux habités (calque ``places``, leur ``kind_detail``) : jamais une maison isolée ni une ferme
PLACE_KINDS = ("city", "town", "village", "hamlet", "suburb", "neighbourhood", "quarter", "locality")
#: les catégories, dans l'ordre des puces de l'écran : (id, libellé, sortes OpenStreetMap)
CATEGORIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("manger", "Manger", ("restaurant", "cafe", "fast_food", "bar", "pub", "biergarten", "ice_cream", "food_court")),
    ("dormir", "Dormir", ("hotel", "motel", "guest_house", "hostel", "chalet", "apartment", "camp_site",
                          "caravan_site", "alpine_hut", "wilderness_hut")),
    ("voir", "À voir", ("attraction", "viewpoint", "museum", "gallery", "castle", "manor", "ruins",
                        "archaeological_site", "monument", "memorial", "artwork", "fort", "city_gate", "lighthouse",
                        "place_of_worship", "theme_park", "zoo", "aquarium", "fountain", "lavoir")),
    ("nature", "Nature", ("peak", "saddle", "volcano", "cave_entrance", "spring", "waterfall", "beach", "bay", "cape",
                          "glacier", "nature_reserve", "national_park", "park", "garden", "forest", "wood", "water",
                          "picnic_site")),
    ("route", "En route", ("fuel", "charging_station", "parking", "rest_area", "services", "toilets",
                           "drinking_water", "shelter")),
    ("courses", "Courses", ("supermarket", "convenience", "marketplace", "bakery", "pastry", "butcher", "greengrocer",
                            "deli", "cheese", "wine", "beverages", "mall", "department_store", "farm", "seafood",
                            "chocolate", "confectionery")),
    ("sante", "Santé", ("pharmacy", "hospital", "clinic", "doctors", "dentist", "veterinary")),
    ("sortir", "Sortir", ("cinema", "theatre", "arts_centre", "nightclub", "swimming_pool", "water_park",
                          "sports_centre", "stadium", "golf_course", "horse_riding", "library")),
    ("services", "Services", ("post_office", "atm", "bank", "townhall", "police", "laundry", "car_rental",
                              "bicycle_rental", "station", "bus_station", "ferry_terminal", "aerodrome", "airport")),
    ("villes", "Villes et lieux-dits", PLACE_KINDS),
)
TOWNS = "villes"
LABELS: tuple[tuple[str, str], ...] = tuple((key, label) for key, label, _kinds in CATEGORIES)
#: la catégorie de chaque sorte du calque ``pois``
POI_CATEGORY = {kind: key for key, _label, kinds in CATEGORIES if key != TOWNS for kind in kinds}
#: chaque sorte en français
KIND_FR = {
    "restaurant": "Restaurant", "cafe": "Café", "fast_food": "Restauration rapide", "bar": "Bar", "pub": "Pub",
    "biergarten": "Biergarten", "ice_cream": "Glacier", "food_court": "Aire de restauration",
    "hotel": "Hôtel", "motel": "Motel", "guest_house": "Chambre d'hôtes", "hostel": "Auberge de jeunesse",
    "chalet": "Chalet", "apartment": "Meublé de tourisme", "camp_site": "Camping",
    "caravan_site": "Aire de camping-cars", "alpine_hut": "Refuge", "wilderness_hut": "Cabane",
    "attraction": "Attraction", "viewpoint": "Point de vue", "museum": "Musée", "gallery": "Galerie",
    "castle": "Château", "manor": "Manoir", "ruins": "Ruines", "archaeological_site": "Site archéologique",
    "monument": "Monument", "memorial": "Mémorial", "artwork": "Œuvre d'art", "fort": "Fort",
    "city_gate": "Porte de ville", "lighthouse": "Phare", "place_of_worship": "Lieu de culte",
    "theme_park": "Parc d'attractions", "zoo": "Zoo", "aquarium": "Aquarium", "fountain": "Fontaine",
    "lavoir": "Lavoir",
    "peak": "Sommet", "saddle": "Col", "volcano": "Volcan", "cave_entrance": "Grotte", "spring": "Source",
    "waterfall": "Cascade", "beach": "Plage", "bay": "Baie", "cape": "Cap", "glacier": "Glacier",
    "nature_reserve": "Réserve naturelle", "national_park": "Parc national", "park": "Parc", "garden": "Jardin",
    "forest": "Forêt", "wood": "Bois", "water": "Plan d'eau", "picnic_site": "Aire de pique-nique",
    "fuel": "Station-service", "charging_station": "Borne de recharge", "parking": "Parking",
    "rest_area": "Aire de repos", "services": "Aire de services", "toilets": "Toilettes",
    "drinking_water": "Eau potable", "shelter": "Abri",
    "supermarket": "Supermarché", "convenience": "Épicerie", "marketplace": "Marché", "bakery": "Boulangerie",
    "pastry": "Pâtisserie", "butcher": "Boucherie", "greengrocer": "Primeur", "deli": "Traiteur",
    "cheese": "Fromagerie", "wine": "Caviste", "beverages": "Boissons", "mall": "Centre commercial",
    "department_store": "Grand magasin", "farm": "Vente à la ferme", "seafood": "Poissonnerie",
    "chocolate": "Chocolatier", "confectionery": "Confiserie",
    "pharmacy": "Pharmacie", "hospital": "Hôpital", "clinic": "Clinique", "doctors": "Médecin",
    "dentist": "Dentiste", "veterinary": "Vétérinaire",
    "cinema": "Cinéma", "theatre": "Théâtre", "arts_centre": "Centre culturel", "nightclub": "Boîte de nuit",
    "swimming_pool": "Piscine", "water_park": "Parc aquatique", "sports_centre": "Centre sportif",
    "stadium": "Stade", "golf_course": "Golf", "horse_riding": "Équitation", "library": "Bibliothèque",
    "post_office": "Bureau de poste", "atm": "Distributeur de billets", "bank": "Banque", "townhall": "Mairie",
    "police": "Police", "laundry": "Laverie", "car_rental": "Location de voitures",
    "bicycle_rental": "Location de vélos", "station": "Gare", "bus_station": "Gare routière",
    "ferry_terminal": "Gare maritime", "aerodrome": "Aérodrome", "airport": "Aéroport",
    "city": "Ville", "town": "Ville", "village": "Village", "hamlet": "Hameau", "suburb": "Quartier",
    "neighbourhood": "Quartier", "quarter": "Quartier", "locality": "Lieu-dit",
}
#: les lieux habités près desquels on dit qu'est un point d'intérêt ; un quartier, un hameau, un lieu-dit se disent
#: près d'une commune (``COMMUNES``) ; une ville, un village ne se disent près de rien
NEAR_KINDS = ("city", "town", "village", "suburb")
COMMUNES = ("city", "town", "village")
TOWN_RADIUS_M = 15_000

# ── le fichier ──
SCHEMA_VERSION = "1"
SCHEMA = """
CREATE TABLE place (id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, category TEXT NOT NULL,
                    lat REAL NOT NULL, lon REAL NOT NULL, weight INTEGER NOT NULL, town TEXT NOT NULL DEFAULT '');
CREATE VIRTUAL TABLE place_text USING fts5(name, town, content='place', content_rowid='id',
                                           tokenize='unicode61 remove_diacritics 2');
CREATE VIRTUAL TABLE place_box USING rtree(id, lat0, lat1, lon0, lon1);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""
#: posé une fois les lieux écrits : les plus importants d'abord, dans une grande zone (la France entière, de loin)
RANK_INDEX = "CREATE INDEX place_weight ON place(weight)"
BATCH = 10_000
SAY_EVERY = 50_000
#: les contenus décodés gardés (l'océan, les terres vides : des tuiles qui partagent le leur, sans suite)
CONTENTS_KEPT = 256
LAYERS = ("pois", "places")
KEYS = frozenset({"name", "name:fr", "kind", "kind_detail", "min_zoom", "population_rank"})
NAME_MAX = 200
#: une tuile plus grosse ne se lit pas (compressée, puis ouverte) : celles de Protomaps font quelques centaines de Ko
BUILD_TILE_MAX = 16 * 1024 * 1024
BUILD_PLAIN_MAX = 64 * 1024 * 1024
#: deux points d'une tuile plus proches que cette part de son côté (au zoom 15, une centaine de mètres) : un même lieu
#: s'ils ont le même nom et la même catégorie
SAME_PLACE = 0.1

# ── chercher ──
LIMIT_MAX = 50
WORDS_MAX = 8
#: les mots qui ne disent rien d'un nom (« Lac de la Forêt ») : écartés quand il en reste d'autres
STOPWORDS = frozenset({"le", "la", "les", "l", "de", "du", "des", "d", "et", "à", "a", "au", "aux", "en", "sur",
                       "sous", "un", "une", "the", "of"})
#: une zone plus grande que tant de degrés carrés se lit par ordre d'importance, pas par l'arbre R (qui y
#: énumérerait des millions de lieux)
WIDE_DEG2 = 1.0
#: bm25 : le nom pèse plus que la ville
BM25 = "bm25(place_text, 10.0, 2.0)"
#: les rayons essayés autour d'un point (km) : d'abord tout près
NEAR_RADII_KM = (1, 5, 25, 100, 400)
TEXT_RADII_KM = (3, 20, 100, 500)
TEXT_CANDIDATES = 300
#: le long d'un trajet : sa ligne simplifiée à tant de points, et au plus tant de lieux lus par tronçon
ALONG_POINTS = 300
ALONG_PER_SEGMENT = 200
#: un tronçon se cherche par morceaux d'au plus deux couloirs de long : chaque boîte reste de la taille du couloir
#: (une boîte grande comme un tronçon de 200 km ne rendrait que ses lieux les plus importants, souvent loin de la
#: route) ; au plus tant de boîtes pour tout le trajet (au-delà, les morceaux s'allongent)
ALONG_BOXES_MAX = 1_500
#: mètres par degré de latitude (sphère de rayon moyen)
M_PER_DEG = 6_371_008.8 * math.pi / 180
#: ouest, sud, est, nord : partout
WORLD = (-180.0, -90.0, 180.0, 90.0)


class BuildFailed(Exception):
    """L'index ne s'est pas construit : dit en mots ; celui en place reste tel quel."""


@dataclass(frozen=True, slots=True)
class Built:
    path: Path
    count: int
    #: les tuiles parcourues (du zoom le plus fin) et celles qui ne se lisaient pas
    tiles: int
    broken: int
    zoom: int
    categories: dict[str, int]
    #: les sortes nommées laissées de côté, les plus fréquentes d'abord (pour régler ``CATEGORIES``)
    skipped: list[tuple[str, int]]
    seconds: float


# ── construire ──

def _clean(text: object) -> str:
    """Un nom tel qu'on le range : sur une ligne, sans caractère invisible, borné."""
    flat = " ".join(str(text).split())
    if not flat.isprintable():
        flat = "".join(ch for ch in flat if ch.isprintable())
    return flat[:NAME_MAX]


def _int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float) and math.isfinite(value):
        return int(value)
    return default


def _pread(fd: int, offset: int, length: int) -> bytes:
    data = os.pread(fd, length, offset)
    if len(data) != length:
        raise ValueError("l'archive est tronquée")
    return data


def _latlon(z: int, x: float, y: float) -> tuple[float, float]:
    n = 1 << z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    return round(lat, 6), round(lon, 6)


def _zoom_entries(fd: int, h: Mapping[str, Any], zoom: int) -> tuple[array, array, array, array]:
    """Les entrées du zoom ``zoom`` (identifiant, suite, où est le contenu, sa longueur), dans l'ordre des
    identifiants : la racine, puis les feuilles qui touchent ce zoom, chacune lue une fois et lâchée."""
    lo, hi = zxy_to_tileid(zoom, 0, 0), zxy_to_tileid(zoom + 1, 0, 0)
    ids, runs, offsets, lengths = array("Q"), array("I"), array("Q"), array("I")

    def walk(offset: int, length: int, end: int, depth: int) -> None:
        if not 0 < length <= DIR_MAX_BYTES:
            raise ValueError("un répertoire hors des bornes")
        found = read_directory(_pread(fd, offset, length))
        for i in range(len(found)):
            tile_id, run = found.ids[i], found.runs[i]
            if run == 0:  # une feuille : les identifiants de la sienne à la suivante
                stop = found.ids[i + 1] if i + 1 < len(found) else end
                if tile_id < hi and stop > lo and depth < 3:
                    walk(h["leaf_directory_offset"] + found.offsets[i], found.lengths[i], stop, depth + 1)
                continue
            first, last = max(tile_id, lo), min(tile_id + run, hi)
            if first < last:
                ids.append(first)
                runs.append(last - first)
                offsets.append(found.offsets[i])
                lengths.append(found.lengths[i])

    walk(h["root_offset"], h["root_length"], 1 << 64, 0)
    return ids, runs, offsets, lengths


def _open_tile(raw: bytes, compression: Compression) -> bytes:
    if compression is Compression.NONE:
        return raw
    unzip = zlib.decompressobj(wbits=31)
    plain = unzip.decompress(raw, BUILD_PLAIN_MAX)
    if not unzip.eof:
        raise ValueError("une tuile tronquée ou démesurée")
    return plain


class _Rows:
    """Ce qu'un contenu de tuile apporte à l'index : ses points gardés, en fractions de la tuile."""

    def __init__(self, skipped: Counter[str]) -> None:
        self.skipped = skipped

    def accept(self, layer: str, props: Mapping[str, object]) -> bool:
        name = props.get("name:fr") or props.get("name")
        if not isinstance(name, str) or not name.strip():
            return False
        if layer == "pois":
            kind = props.get("kind")
            if kind in POI_CATEGORY:
                return True
            self.skipped[f"pois:{kind}"] += 1
            return False
        kind = props.get("kind_detail") or props.get("kind")
        if kind in PLACE_KINDS:
            return True
        self.skipped[f"places:{kind}"] += 1
        return False

    def of(self, plain: bytes) -> list[tuple[float, float, str, str, str, int]]:
        out = []
        #: un lieu cartographié deux fois (son point et son bâtiment : « Musée de l'Hospice Comtesse » et « … de
        #: l'hospice comtesse ») ne compte qu'une : même nom, même catégorie, à quelques dizaines de mètres
        seen: dict[tuple[str, str], list[tuple[float, float]]] = {}
        for p in read_points(plain, LAYERS, keys=KEYS, accept=self.accept):
            props = p.props
            name = _clean(props.get("name:fr") or props.get("name"))
            if not name:
                continue
            reach = max(0, min(17, 17 - _int(props.get("min_zoom"), 15)))
            if p.layer == "pois":
                kind = str(props["kind"])
                category, weight = POI_CATEGORY[kind], reach
            else:
                kind = str(props.get("kind_detail") or props.get("kind"))
                category, weight = TOWNS, reach + max(0, min(20, _int(props.get("population_rank"), 0)))
            u, v = p.x / p.extent, p.y / p.extent
            twins = seen.setdefault((name.casefold(), category), [])
            if any(abs(u - a) < SAME_PLACE and abs(v - b) < SAME_PLACE for a, b in twins):
                continue
            twins.append((u, v))
            out.append((u, v, name, kind, category, weight))
        return out


def build(archive: Path, out: Path, say: Callable[[str], None] = lambda _text: None) -> Built:
    """L'index des lieux de cette archive PMTiles (vectorielle, au schéma Protomaps), écrit dans ``out``."""
    started = time.monotonic()
    try:
        fd = os.open(archive, os.O_RDONLY)
    except OSError:
        raise BuildFailed(f"l'archive {archive.name} n'est pas là") from None
    partial = out.with_name(out.name + ".partiel")
    db: sqlite3.Connection | None = None
    try:
        try:
            h = deserialize_header(_pread(fd, 0, 127))
        except BROKEN:
            raise BuildFailed("ce n'est pas une archive PMTiles (version 3) lisible") from None
        if h["tile_type"] is not TileType.MVT:
            raise BuildFailed("ses tuiles ne sont pas vectorielles : aucun lieu à y lire")
        if h["tile_compression"] not in (Compression.GZIP, Compression.NONE):
            raise BuildFailed("ses tuiles sont compressées autrement qu'en gzip : refais-la avec mika carte extraire")
        if h["internal_compression"] is not Compression.GZIP:
            raise BuildFailed("ses répertoires sont rangés autrement qu'en gzip : refais-la avec mika carte extraire")
        zoom = h["max_zoom"]
        try:
            ids, runs, offsets, lengths = _zoom_entries(fd, h, zoom)
        except BROKEN:
            raise BuildFailed("un répertoire de l'archive est abîmé") from None
        total = sum(runs)
        say(f"{total} tuiles au zoom {zoom}" + ("" if zoom >= 15 else
            " (le plus fin de l'archive : sous le 15, des lieux manquent)"))
        partial.unlink(missing_ok=True)
        db = sqlite3.connect(partial)
        db.execute("PRAGMA journal_mode=OFF")
        db.execute("PRAGMA synchronous=OFF")
        db.execute("PRAGMA cache_size=-65536")
        db.executescript(SCHEMA)
        skipped: Counter[str] = Counter()
        rows = _Rows(skipped)
        kept: OrderedDict[int, list[tuple[float, float, str, str, str, int]]] = OrderedDict()
        places: list[tuple[int, str, str, str, float, float, int]] = []
        categories: Counter[str] = Counter()
        count = broken = done = 0
        next_say = SAY_EVERY
        data_at = h["tile_data_offset"]
        for k in range(len(ids)):
            offset, length = offsets[k], lengths[k]
            found = kept.get(offset)
            if found is None:
                try:
                    if length > BUILD_TILE_MAX:
                        raise ValueError("une tuile démesurée")
                    found = rows.of(_open_tile(_pread(fd, data_at + offset, length), h["tile_compression"]))
                except (ValueError, zlib.error, OSError):
                    broken += 1
                    found = []
                kept[offset] = found
                if len(kept) > CONTENTS_KEPT:
                    kept.popitem(last=False)
            else:
                kept.move_to_end(offset)
            if found:
                for t in range(runs[k]):  # une suite partage son contenu : ses points dans chacune de ses tuiles
                    z, x, y = tileid_to_zxy(ids[k] + t)
                    for u, v, name, kind, category, weight in found:
                        lat, lon = _latlon(z, x + u, y + v)
                        count += 1
                        places.append((count, name, kind, category, lat, lon, weight))
                        categories[category] += 1
                if len(places) >= BATCH:
                    _write(db, places)
            done += runs[k]
            if done >= next_say:
                say(f"{done} tuiles sur {total} : {count} lieux")
                next_say += SAY_EVERY
        _write(db, places)
        say(f"{done} tuiles lues : {count} lieux ; près de quelle ville est chacun…")
        _towns(db)
        say("l'index du texte…")
        db.execute("INSERT INTO place_text(place_text) VALUES ('rebuild')")
        db.execute("INSERT INTO place_text(place_text) VALUES ('optimize')")
        db.execute(RANK_INDEX)
        db.execute("ANALYZE")
        bounds = (h["min_lon_e7"] / 1e7, h["min_lat_e7"] / 1e7, h["max_lon_e7"] / 1e7, h["max_lat_e7"] / 1e7)
        built = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        db.executemany("INSERT INTO meta(key, value) VALUES (?, ?)", [
            ("version", SCHEMA_VERSION), ("source", archive.name), ("built", built), ("count", str(count)),
            ("zoom", str(zoom)), ("bounds", ",".join(f"{v:.5f}" for v in bounds))])
        db.commit()
        db.close()
        db = None
        with partial.open("rb") as f:
            os.fsync(f.fileno())
        os.replace(partial, out)
    except sqlite3.Error as exc:
        raise BuildFailed(f"l'index ne s'écrit pas ({exc})") from None
    except OSError as exc:
        raise BuildFailed(f"l'archive ne se lit plus ({exc.strerror or exc})") from None
    finally:
        os.close(fd)
        if db is not None:
            db.close()
        partial.unlink(missing_ok=True)
    return Built(out, count, done, broken, zoom, dict(categories), skipped.most_common(25),
                 round(time.monotonic() - started, 1))


def _write(db: sqlite3.Connection, places: list[tuple[int, str, str, str, float, float, int]]) -> None:
    if not places:
        return
    db.executemany("INSERT INTO place(id, name, kind, category, lat, lon, weight) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   places)
    db.executemany("INSERT INTO place_box(id, lat0, lat1, lon0, lon1) VALUES (?, ?, ?, ?, ?)",
                   [(p[0], p[4], p[4], p[5], p[5]) for p in places])
    db.commit()
    places.clear()


#: la grille des villes : des cases de tant de degrés
CELL_DEG = 0.05


class _Grid:
    """Les lieux habités, rangés par cases : le plus proche d'un point, à moins de ``TOWN_RADIUS_M``."""

    def __init__(self, towns: Sequence[tuple[str, str, float, float]], kinds: Sequence[str]) -> None:
        self.cells: dict[tuple[int, int], list[tuple[float, float, str]]] = {}
        for name, kind, lat, lon in towns:
            if kind in kinds:
                self.cells.setdefault((math.floor(lat / CELL_DEG), math.floor(lon / CELL_DEG)), []).append(
                    (lat, lon, name))

    def nearest(self, lat: float, lon: float, *, besides: str = "") -> str:
        ci, cj = math.floor(lat / CELL_DEG), math.floor(lon / CELL_DEG)
        cos = max(0.05, math.cos(math.radians(lat)))
        step = CELL_DEG * M_PER_DEG * cos  # au moins tant de mètres entre ce point et le dehors de l'anneau k
        best, best_d2 = "", float(TOWN_RADIUS_M) ** 2
        k = 0
        while True:
            for di in range(-k, k + 1):
                for dj in range(-k, k + 1):
                    if max(abs(di), abs(dj)) != k:
                        continue  # seulement l'anneau k
                    for t_lat, t_lon, name in self.cells.get((ci + di, cj + dj), ()):
                        if name == besides:
                            continue
                        dy = (t_lat - lat) * M_PER_DEG
                        dx = (t_lon - lon) * M_PER_DEG * cos
                        d2 = dx * dx + dy * dy
                        if d2 < best_d2:
                            best, best_d2 = name, d2
            reach = k * step
            if reach * reach >= best_d2 or reach >= TOWN_RADIUS_M:
                return best
            k += 1


def _towns(db: sqlite3.Connection) -> None:
    """``town`` : la ville, le village (ou le quartier) le plus proche de chaque lieu, à moins de 15 km."""
    towns = db.execute(f"SELECT name, kind, lat, lon FROM place WHERE category = '{TOWNS}' AND kind IN "
                       f"({', '.join(repr(k) for k in NEAR_KINDS)})").fetchall()
    near, communes = _Grid(towns, NEAR_KINDS), _Grid(towns, COMMUNES)
    last = 0
    while True:
        batch = db.execute("SELECT id, name, kind, category, lat, lon FROM place WHERE id > ? ORDER BY id LIMIT ?",
                           (last, BATCH)).fetchall()
        if not batch:
            return
        updates = []
        for pid, name, kind, category, lat, lon in batch:
            if category != TOWNS:
                town = near.nearest(lat, lon)
            elif kind in COMMUNES:
                town = ""  # une ville, un village : près de rien
            else:
                town = communes.nearest(lat, lon, besides=name)
            if town:
                updates.append((town, pid))
        db.executemany("UPDATE place SET town = ? WHERE id = ?", updates)
        db.commit()
        last = batch[-1][0]


# ── chercher ──

def _words(text: str) -> list[str]:
    """Les mots cherchés : des lettres et des chiffres seulement (ni guillemets ni opérateurs : une requête du texte
    intégral ne lève jamais) ; « le », « de »… et une lettre seule ne comptent que s'ils sont tout ce qu'on cherche."""
    words = [w[:40] for w in re.findall(r"[^\W_]+", text.lower())][:WORDS_MAX * 3]
    meaningful = [w for w in words if w not in STOPWORDS and len(w) > 1]
    return (meaningful or words)[:WORDS_MAX]


def _match(words: Sequence[str]) -> str:
    """La requête du texte intégral : tous les mots (ET), chacun en début de mot — sauf un mot de deux lettres, exact
    (« ay » ne cherche pas tout ce qui commence par « ay »)."""
    return " ".join(f'"{w}"' if len(w) <= 2 else f'"{w}"*' for w in words)


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(min(1.0, math.sqrt(a)))


def _expand(south: float, west: float, north: float, east: float, margin_m: float) -> tuple[float, float, float, float]:
    """Ouest, sud, est, nord d'une boîte élargie de ``margin_m`` de chaque côté — en longitude, à la latitude où un
    degré est le plus court (la marge n'y manque nulle part)."""
    dlat = margin_m / M_PER_DEG
    cos = max(0.01, min(math.cos(math.radians(south)), math.cos(math.radians(north))))
    dlon = margin_m / (M_PER_DEG * cos)
    return west - dlon, max(-90.0, south - dlat), east + dlon, min(90.0, north + dlat)


def _box(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """Ouest, sud, est, nord autour d'un point."""
    return _expand(lat, lon, lat, lon, radius_m)


def _hit(row: Sequence[Any], *, distance_m: float | None = None, along_m: float | None = None) -> PlaceHit:
    pid, name, kind, category, lat, lon, _weight, town = row[:8]
    return PlaceHit(id=f"l{pid}", name=name, kind=kind, kind_fr=KIND_FR.get(kind, kind.replace("_", " ").capitalize()),
                    category=category, lat=lat, lon=lon, town=town,
                    distance_m=None if distance_m is None else round(distance_m),
                    along_m=None if along_m is None else round(along_m))


COLUMNS = "p.id, p.name, p.kind, p.category, p.lat, p.lon, p.weight, p.town"


def _in_box(conn: sqlite3.Connection, box: tuple[float, float, float, float], category: str, *, limit: int,
            closest_to: tuple[float, float] | None = None, tree: bool = False) -> list[tuple[Any, ...]]:
    """Ce qui est dans la boîte (par l'arbre R) : les plus importants d'abord, ou les plus proches de ``closest_to``
    (une distance approchée, l'ordre exact se refait ensuite) ; au plus ``limit``. ``tree`` : toujours par l'arbre
    R, même pour une boîte plus grande que ``WIDE_DEG2`` (un morceau de trajet près des pôles)."""
    w, s, e, n = box
    if closest_to is None and not tree and (e - w) * (n - s) > WIDE_DEG2:
        # une grande zone : les plus importants d'abord, sans énumérer tout ce qu'elle contient
        sql = (f"SELECT {COLUMNS} FROM place p INDEXED BY place_weight "
               "WHERE p.lat BETWEEN ? AND ? AND p.lon BETWEEN ? AND ?")
        wide: list[Any] = [s, n, w, e]
        if category:
            sql += " AND p.category = ?"
            wide.append(category)
        return conn.execute(sql + " ORDER BY p.weight DESC LIMIT ?", [*wide, limit]).fetchall()
    sql = (f"SELECT {COLUMNS} FROM place_box b JOIN place p ON p.id = b.id "
           "WHERE b.lat0 <= ? AND b.lat1 >= ? AND b.lon0 <= ? AND b.lon1 >= ?")
    params: list[Any] = [n, s, e, w]
    if category:
        sql += " AND p.category = ?"
        params.append(category)
    if closest_to is None:
        sql += " ORDER BY p.weight DESC LIMIT ?"
    else:
        lat, lon = closest_to
        cos2 = math.cos(math.radians(lat)) ** 2
        sql += " ORDER BY (p.lat - ?) * (p.lat - ?) + (p.lon - ?) * (p.lon - ?) * ? LIMIT ?"
        params += [lat, lat, lon, lon, cos2]
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def _around(conn: sqlite3.Connection, lat: float, lon: float, radius_m: float, category: str,
            limit: int) -> list[PlaceHit]:
    near = []
    for row in _in_box(conn, _box(lat, lon, radius_m), category, limit=3 * limit + 50, closest_to=(lat, lon)):
        d = _distance_m(lat, lon, row[4], row[5])
        if d <= radius_m:
            near.append((d, -row[6], row))
    near.sort(key=lambda t: (t[0], t[1]))
    return [_hit(row, distance_m=d) for d, _w, row in near[:limit]]


def _nearest(conn: sqlite3.Connection, lat: float, lon: float, category: str, limit: int) -> list[PlaceHit]:
    """Les plus proches, de plus en plus loin jusqu'à en avoir assez."""
    found: list[PlaceHit] = []
    for km in NEAR_RADII_KM:
        found = _around(conn, lat, lon, km * 1000, category, limit)
        if len(found) >= limit:
            break
    return found


def _text(conn: sqlite3.Connection, words: list[str], near: tuple[float, float] | None,
          bbox: tuple[float, float, float, float] | None, category: str, limit: int) -> list[PlaceHit]:
    """Par le texte : chaque mot (en début de mot) dans le nom ou la ville ; puis la pertinence, l'importance du
    lieu et la distance au point donné. Autour d'un point : d'abord tout près, puis de plus en plus loin."""
    match = _match(words)
    boxes: list[tuple[float, float, float, float] | None]
    if bbox is not None:
        boxes = [bbox]
    elif near is not None:
        boxes = [_box(near[0], near[1], km * 1000) for km in TEXT_RADII_KM] + [None]
    else:
        boxes = [None]
    #: ce qu'ont trouvé les zones déjà lues : gardé quand on élargit (le plus proche ne se perd pas parmi les
    #: meilleurs textes d'une zone plus grande)
    found: dict[int, tuple[Any, ...]] = {}
    for box in boxes:
        sql = f"SELECT {COLUMNS}, {BM25} FROM place_text JOIN place p ON p.id = place_text.rowid " \
              "WHERE place_text MATCH ?"
        params: list[Any] = [match]
        if category:
            sql += " AND p.category = ?"
            params.append(category)
        if box is not None:
            sql += " AND p.lat BETWEEN ? AND ? AND p.lon BETWEEN ? AND ?"
            params += [box[1], box[3], box[0], box[2]]
        sql += f" ORDER BY {BM25} LIMIT ?"
        params.append(TEXT_CANDIDATES)
        try:
            for row in conn.execute(sql, params).fetchall():
                found.setdefault(row[0], row)
        except sqlite3.OperationalError:  # une requête illisible malgré tout : rien trouvé, jamais une erreur
            return []
        if len(found) >= limit:
            break
    rows = list(found.values())
    if not rows:
        return []
    best = max(-row[8] for row in rows) or 1.0
    scored = []
    for row in rows:
        d = _distance_m(near[0], near[1], row[4], row[5]) if near is not None else None
        score = 3.0 * (-row[8] / best) + 0.1 * row[6] - (0.8 * math.log1p(d / 1000) if d is not None else 0.0)
        scored.append((score, d, row))
    scored.sort(key=lambda t: -t[0])
    return [_hit(row, distance_m=d) for _s, d, row in scored[:limit]]


def _project(points: Sequence[tuple[float, float]], lat0: float) -> list[tuple[float, float]]:
    cos = math.cos(math.radians(lat0))
    return [(lon * M_PER_DEG * cos, lat * M_PER_DEG) for lat, lon in points]


def _segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> tuple[float, float]:
    """La distance d'un point à un segment, et où il s'y projette (0 au début, 1 à la fin)."""
    vx, vy = bx - ax, by - ay
    span = vx * vx + vy * vy
    t = 0.0 if span == 0 else max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / span))
    dx, dy = px - (ax + t * vx), py - (ay + t * vy)
    return math.hypot(dx, dy), t


def simplify(line: Sequence[tuple[float, float]], tolerance_m: float, most: int = ALONG_POINTS) -> list[int]:
    """Les indices des points d'une ligne (lat, lon) qu'on garde (Douglas-Peucker, à ``tolerance_m`` près) : au plus
    ``most``, la tolérance doublée tant qu'il en faut moins."""
    if len(line) <= 2:
        return list(range(len(line)))
    xy = _project(line, sum(p[0] for p in line) / len(line))
    while True:
        keep = {0, len(line) - 1}
        stack = [(0, len(line) - 1)]
        while stack:
            a, b = stack.pop()
            far, far_d = -1, tolerance_m
            for i in range(a + 1, b):
                d, _t = _segment(*xy[i], *xy[a], *xy[b])
                if d > far_d:
                    far, far_d = i, d
            if far >= 0:
                keep.add(far)
                stack += [(a, far), (far, b)]
        if len(keep) <= most:
            return sorted(keep)
        tolerance_m *= 2


def _along(conn: sqlite3.Connection, line: Sequence[tuple[float, float]], corridor_m: float, category: str,
           limit: int) -> list[PlaceHit]:
    """Le long d'une ligne : pour chaque tronçon de la ligne simplifiée, ce qui est dans sa boîte élargie du couloir ;
    la distance exacte à la ligne, et où on le croise ; puis les meilleurs, répartis sur le trajet, dans l'ordre."""
    # d'abord les points trop proches les uns des autres (un tracé en compte des dizaines de milliers) ; la distance
    # parcourue se mesure sur ce qui reste (assez dense pour suivre la route), pas sur la ligne simplifiée
    thin = [line[0]]
    walked = [0.0]
    step = max(10.0, corridor_m / 20)
    for p in line[1:]:
        d = _distance_m(*thin[-1], *p)
        if d >= step or p is line[-1]:
            thin.append(p)
            walked.append(walked[-1] + d)
    kept_at = simplify(thin, max(25.0, corridor_m / 5))
    kept = [thin[i] for i in kept_at]
    cumulative = [walked[i] for i in kept_at]
    if len(kept) == 1:
        return _around(conn, kept[0][0], kept[0][1], corridor_m, category, limit)
    lat0 = sum(p[0] for p in kept) / len(kept)
    xy = _project(kept, lat0)
    best: dict[int, tuple[float, float, tuple[Any, ...]]] = {}
    lengths = [_distance_m(*kept[i], *kept[i + 1]) for i in range(len(kept) - 1)]
    piece_m = max(2.0 * corridor_m, 1_000.0, sum(lengths) / ALONG_BOXES_MAX)
    for i in range(len(kept) - 1):
        (a_lat, a_lon), (b_lat, b_lon) = kept[i], kept[i + 1]
        pieces = max(1, math.ceil(lengths[i] / piece_m))
        for k in range(pieces):
            # un morceau du tronçon, sa boîte élargie du couloir : petite, elle se lit par l'arbre R
            t0, t1 = k / pieces, (k + 1) / pieces
            lat_a, lon_a = a_lat + (b_lat - a_lat) * t0, a_lon + (b_lon - a_lon) * t0
            lat_b, lon_b = a_lat + (b_lat - a_lat) * t1, a_lon + (b_lon - a_lon) * t1
            box = _expand(min(lat_a, lat_b), min(lon_a, lon_b), max(lat_a, lat_b), max(lon_a, lon_b), corridor_m)
            for row in _in_box(conn, box, category, limit=ALONG_PER_SEGMENT, tree=True):
                px, py = _project([(row[4], row[5])], lat0)[0]
                d, t = _segment(px, py, *xy[i], *xy[i + 1])
                if d <= corridor_m and (row[0] not in best or d < best[row[0]][0]):
                    best[row[0]] = (d, cumulative[i] + t * (cumulative[i + 1] - cumulative[i]), row)
    if not best:
        return []
    # répartis : le meilleur de chaque part du trajet, puis les meilleurs qui restent
    total = cumulative[-1] or 1.0

    def merit(item: tuple[float, float, tuple[Any, ...]]) -> float:
        return item[2][6] - 2.0 * item[0] / max(corridor_m, 1.0)

    ranked = sorted(best.values(), key=merit, reverse=True)
    chosen: dict[int, tuple[float, float, tuple[Any, ...]]] = {}
    parts: set[int] = set()
    for item in ranked:
        part = min(limit - 1, int(item[1] / total * limit))
        if part not in parts:
            parts.add(part)
            chosen[item[2][0]] = item
    for item in ranked:
        if len(chosen) >= limit:
            break
        chosen.setdefault(item[2][0], item)
    ordered = sorted(chosen.values(), key=lambda item: item[1])[:limit]
    return [_hit(row, distance_m=d, along_m=at) for d, at, row in ordered]


@dataclass(frozen=True, slots=True)
class IndexInfo:
    ready: bool
    reason: str = ""
    count: int = 0
    built: str = ""
    source: str = ""
    zoom: int = 0
    bounds: tuple[float, float, float, float] | None = None
    size: int = 0


class Places:
    """L'index réglé (``config`` relu à chaque fois : la console le change sans redémarrer), dans ``data``."""

    def __init__(self, data: Path, config: Callable[[], PlacesConfig]) -> None:
        self.data = data
        self.config = config
        self._info: tuple[tuple[object, ...], IndexInfo] | None = None

    def _file(self) -> tuple[Path, tuple[str, int, int]] | None:
        path = self.data / self.config().index
        try:
            st = path.stat()
        except OSError:
            return None
        return path, (str(path), st.st_mtime_ns, st.st_size)

    def info(self) -> IndexInfo:
        """Ce que l'index dit de lui (relu quand le fichier change)."""
        found = self._file()
        if found is None:
            return IndexInfo(False, f"L'index des lieux n'est pas construit ({self.config().index}) : mika carte "
                                    "lieux (deploy/README.md, « La carte de sa position »).")
        path, key = found
        if self._info is not None and self._info[0] == key:
            return self._info[1]
        try:
            conn = _connect(path)
            try:
                meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
            finally:
                conn.close()
            if meta.get("version") != SCHEMA_VERSION:
                raise ValueError("une autre version")
            w, s, e, n = (float(v) for v in meta.get("bounds", "").split(","))
            got = IndexInfo(True, count=int(meta.get("count", "0")), built=meta.get("built", ""),
                            source=meta.get("source", ""), zoom=int(meta.get("zoom", "0")), bounds=(w, s, e, n),
                            size=key[2])
        except (sqlite3.Error, ValueError):
            got = IndexInfo(False, "L'index des lieux est illisible : refais-le (mika carte lieux).")
        self._info = (key, got)
        return got

    def ready(self) -> bool:
        return self.info().ready

    def _ready_path(self) -> Path:
        found = self._file()
        if found is None or not self.info().ready:
            raise MapsUnavailable(self.info().reason)
        return found[0]

    async def _run(self, fn: Callable[[sqlite3.Connection], Any]) -> Any:
        path = self._ready_path()

        def run() -> Any:
            conn = _connect(path)
            try:
                return fn(conn)
            finally:
                conn.close()

        try:
            return await asyncio.to_thread(run)
        except sqlite3.DatabaseError:
            raise MapsUnavailable("L'index des lieux est illisible : refais-le (mika carte lieux).") from None

    async def search(self, text: str, *, near: tuple[float, float] | None = None,
                     bbox: tuple[float, float, float, float] | None = None, category: str = "",
                     limit: int = 20) -> list[PlaceHit]:
        limit = max(1, min(LIMIT_MAX, int(limit)))
        if category and category not in dict(LABELS):
            return []
        if bbox is not None:
            w, s, e, n = bbox
            if not (w < e and s < n):
                raise ValueError("une zone : ouest < est, sud < nord")
        words = _words(text or "")
        if words:
            return await self._run(lambda conn: _text(conn, words, near, bbox, category, limit))
        if bbox is not None:
            if near is None:
                return await self._run(lambda conn: [_hit(r) for r in _in_box(conn, bbox, category, limit=limit)])

            def framed(conn: sqlite3.Connection) -> list[PlaceHit]:
                rows = _in_box(conn, bbox, category, limit=3 * limit + 50, closest_to=near)
                ranked = sorted((_distance_m(near[0], near[1], r[4], r[5]), r) for r in rows)[:limit]
                return [_hit(r, distance_m=d) for d, r in ranked]

            return await self._run(framed)
        if near is not None:
            return await self._run(lambda conn: _nearest(conn, near[0], near[1], category, limit))

        return await self._run(lambda conn: [_hit(r) for r in _in_box(conn, WORLD, category, limit=limit)])

    async def around(self, lat: float, lon: float, radius_m: float, category: str = "",
                     limit: int = 20) -> list[PlaceHit]:
        limit = max(1, min(LIMIT_MAX, int(limit)))
        radius_m = max(1.0, min(500_000.0, float(radius_m)))
        return await self._run(lambda conn: _around(conn, lat, lon, radius_m, category, limit))

    async def along(self, line: Sequence[tuple[float, float]], *, corridor_m: int = 10_000, category: str = "",
                    limit: int = 20) -> list[PlaceHit]:
        limit = max(1, min(LIMIT_MAX, int(limit)))
        corridor = max(100.0, min(50_000.0, float(corridor_m)))
        points = [(float(a), float(b)) for a, b in line if math.isfinite(a) and math.isfinite(b)]
        if category and category not in dict(LABELS):
            return []
        if not points:
            return []
        return await self._run(lambda conn: _along(conn, points, corridor, category, limit))

    def summary(self) -> dict[str, object]:
        info = self.info()
        return {"ready": info.ready, "count": info.count, "built": info.built}

    def describe(self) -> list[tuple[str, str]]:
        info = self.info()
        index = self.config().index
        if not info.ready:
            return [("Index des lieux", f"{index} : {info.reason}")]
        facts = [("Index des lieux", f"{index} : {_count_fr(info.count)} lieux, tirés de {info.source} (zoom "
                                     f"{info.zoom})"), ("Construit", _when_fr(info.built))]
        if info.bounds is not None:
            w, s, e, n = info.bounds
            facts.append(("Zone (ouest, sud → est, nord)", f"{w:.2f}, {s:.2f} → {e:.2f}, {n:.2f}"))
        facts.append(("Taille", f"{max(1, round(info.size / 1e6))} Mo"))
        return facts


def _connect(path: Path) -> sqlite3.Connection:
    """En lecture seule : la recherche ne change jamais l'index."""
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def _count_fr(n: int) -> str:
    return f"{n:,}".replace(",", " ")


MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
          "novembre", "décembre")


def _when_fr(iso: str) -> str:
    try:
        at = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso or "inconnu"
    return f"le {at.day} {MONTHS[at.month - 1]} {at.year}"
