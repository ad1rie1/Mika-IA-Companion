"""L'index des lieux tiré de l'extrait OpenStreetMap de Geofabrik (ADR 0244) : ``mika carte lieux --depuis
cartes/france-latest.osm.pbf`` écrit ``cartes/lieux.db`` au schéma 2 — les lieux de ``places.CATEGORIES``, leur objet
d'OpenStreetMap, et ce qu'en dit une fiche (cuisine, horaires, téléphone, site, terrasse, végétarien,
accessibilité…, ``tags.KEPT``). Lu par pyosmium (l'extra ``cartes``).

**La mémoire reste bornée** (la France : 530 millions de nœuds, qu'aucun index complet des positions ne tient en
3 Go) — l'extrait se lit en plusieurs passes, chacune filtrée par pyosmium avant que Python ne voie rien :

1. les relations (multipolygones, parcs nationaux) d'une sorte connue et nommées : leurs voies extérieures sont
   notées ;
2. les nœuds et les voies d'une sorte connue (``OSM_KINDS``, filtrés par paires clé=valeur) : un nœud s'écrit à sa
   place ; une voie s'écrit sans position, notée ;
3. les voies notées (les lieux, et les contours des relations) : leurs nœuds sont rangés sur le disque, par tranche
   d'identifiants (``NODE_SLICE``) ;
4. une passe par tranche : seuls les nœuds de la tranche gardent leur position (un ensemble d'identifiants de quelques
   centaines de Mo, un index de 16 octets par nœud gardé), chaque voie en reçoit ce qu'elle a dans la tranche.

Une voie fermée se place au centre de ses nœuds, une voie ouverte sur son nœud du milieu, une relation au centre des
nœuds de ses contours. Puis : un lieu cartographié deux fois (son point et son bâtiment) ne compte qu'une, la
commune de chacun, le texte intégral, l'arbre R. Le fichier s'écrit à côté (``….partiel``) et ne prend la place de
l'ancien qu'entier."""

from __future__ import annotations

import math
import re
import sqlite3
import time
import types
from array import array
from bisect import bisect_left
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mika.adapters.maps import tags as osm_tags
from mika.adapters.maps.places import (
    BATCH,
    CATEGORIES,
    DETAILED_SCHEMA,
    DETAILED_VERSION,
    OSM_INDEX,
    PLACE_KINDS,
    POI_CATEGORY,
    TOWNS,
    BuildFailed,
    seal,
    towns,
)

try:  # l'extra « cartes » : sans lui, la construction le dit, le reste du moteur l'ignore
    import osmium
except ImportError:  # pragma: no cover - dépend de l'installation
    osmium = None  # type: ignore[assignment]

MISSING = ("pyosmium n'est pas installé : il lit l'extrait OpenStreetMap (pip install -e '.[cartes]', l'extra "
           "« cartes » du paquet)")

# ── ce qu'on garde ──
#: (clé, {valeur : sorte de l'index}) d'OpenStreetMap, dans l'ordre où on les essaie : un hôtel qui a aussi un
#: restaurant est un hôtel, un musée dans un château est un musée
OSM_KINDS: tuple[tuple[str, dict[str, str]], ...] = (
    ("tourism", {v: v for v in ("hotel", "motel", "guest_house", "hostel", "chalet", "apartment", "camp_site",
                                "caravan_site", "alpine_hut", "wilderness_hut", "attraction", "viewpoint", "museum",
                                "gallery", "theme_park", "zoo", "aquarium", "artwork", "picnic_site")}),
    ("amenity", {v: v for v in ("restaurant", "cafe", "fast_food", "bar", "pub", "biergarten", "ice_cream",
                                "food_court", "fuel", "charging_station", "parking", "toilets", "drinking_water",
                                "shelter", "marketplace", "pharmacy", "hospital", "clinic", "doctors", "dentist",
                                "veterinary", "cinema", "theatre", "arts_centre", "nightclub", "library",
                                "post_office", "atm", "bank", "townhall", "police", "car_rental", "bicycle_rental",
                                "bus_station", "ferry_terminal", "fountain", "place_of_worship", "lavoir")}),
    ("historic", {v: v for v in ("castle", "manor", "ruins", "archaeological_site", "monument", "memorial", "fort",
                                 "city_gate")}),
    ("shop", {v: v for v in ("supermarket", "convenience", "bakery", "pastry", "butcher", "greengrocer", "deli",
                             "cheese", "wine", "beverages", "mall", "department_store", "farm", "seafood", "chocolate",
                             "confectionery", "laundry")}),
    ("leisure", {v: v for v in ("park", "garden", "nature_reserve", "swimming_pool", "water_park", "sports_centre",
                                "stadium", "golf_course", "horse_riding")}),
    ("natural", {v: v for v in ("peak", "saddle", "volcano", "cave_entrance", "spring", "beach", "bay", "cape",
                                "glacier", "wood", "water")}),
    ("waterway", {"waterfall": "waterfall"}),
    ("landuse", {"forest": "forest"}),
    ("boundary", {"national_park": "national_park"}),
    ("man_made", {"lighthouse": "lighthouse"}),
    ("railway", {"station": "station", "halt": "station"}),
    ("aeroway", {"aerodrome": "aerodrome"}),
    ("highway", {"rest_area": "rest_area", "services": "services"}),
    ("place", {v: v for v in PLACE_KINDS}),
)
#: une relation n'est un lieu que comme surface (un multipolygone), ou comme parc national ; jamais un lieu habité,
#: que son nœud dit déjà (une limite administrative porte souvent ``place=*`` : son centre n'est pas le lieu)
RELATION_TYPES = frozenset({"multipolygon", "boundary"})
BOUNDARY_KINDS = frozenset({"national_park"})
#: les voies d'une relation qui la dessinent
OUTER_ROLES = frozenset({"outer", ""})

# ── l'importance (``place.weight`` : l'ordre d'une grande zone, un peu du rang d'une recherche par le nom) ──
PLACE_WEIGHT = {"city": 14, "town": 11, "village": 8, "suburb": 7, "quarter": 5, "neighbourhood": 4, "hamlet": 3,
                "locality": 2}
NOTABLE = frozenset({"museum", "castle", "zoo", "aquarium", "theme_park", "national_park", "nature_reserve", "peak",
                     "volcano", "waterfall", "glacier", "lighthouse", "attraction", "airport", "fort", "cape",
                     "archaeological_site", "station"})
POI_WEIGHT = 2

# ── la mémoire ──
#: une tranche d'identifiants de nœuds : son ensemble tient en ``NODE_SLICE / 8`` octets au plus (500 Mo)
NODE_SLICE = 4_000_000_000
#: les nœuds rangés sur le disque, par paquets de tant
REFS_CHUNK = 1 << 20
#: deux lieux du même nom et de la même catégorie à moins de tant de mètres : un seul (son point et son bâtiment)
SAME_PLACE_M = 150.0
#: un lieu habité du même nom à moins de tant (son nœud et le contour d'un quartier) : le même
SAME_TOWN_M = 3_000.0
#: la marge autour de la zone de l'extrait (en degrés)
ZONE_MARGIN = 0.05
M_PER_DEG = 111_195.0
SAY_EVERY = 500_000


@dataclass(frozen=True, slots=True)
class OsmBuilt:
    path: Path
    count: int
    categories: dict[str, int]
    #: les nœuds, voies et relations gardés comme lieux
    nodes: int
    ways: int
    relations: int
    #: d'une sorte connue mais sans nom ; sans position (hors de l'extrait) ; comptés deux fois
    unnamed: int
    unplaced: int
    twins: int
    #: les nœuds dont il a fallu la position, et en combien de tranches
    needed: int
    slices: int
    #: la date de l'extrait (ISO 8601), si son en-tête la dit
    extract: str
    seconds: float


# ── lire un objet ──

def pick(tags: Mapping[str, str]) -> tuple[str, str] | None:
    """``(sorte, nom)`` d'un objet d'OpenStreetMap, ou ``None`` : sans nom, ou d'aucune sorte connue."""
    name = osm_tags.clean(tags.get("name:fr") or tags.get("name") or "", 200)
    if not name:
        return None
    for key, kinds in OSM_KINDS:
        value = tags.get(key)
        if value is not None and value in kinds:
            kind = kinds[value]
            if kind == "aerodrome" and tags.get("iata"):
                kind = "airport"
            return kind, name
    return None


def kind_of(tags: Mapping[str, str]) -> str | None:
    """La sorte seule (``pick`` sans le nom)."""
    for key, kinds in OSM_KINDS:
        value = tags.get(key)
        if value is not None and value in kinds:
            return kinds[value]
    return None


def weight(kind: str, tags: Mapping[str, str]) -> int:
    if kind in PLACE_WEIGHT:
        bonus = 0
        population = re.sub(r"[\s ]", "", str(tags.get("population", "")))
        if population.isdigit() and int(population) > 0:
            bonus = min(8, int(math.log10(int(population))))
        return PLACE_WEIGHT[kind] + bonus + (2 if tags.get("capital") in ("yes", "2", "4") else 0)
    return POI_WEIGHT + (3 if kind in NOTABLE else 0) + (3 if tags.get("wikidata") else 0) + \
        (2 if tags.get("wikipedia") else 0)


def row(kind: str, name: str, tags: Mapping[str, str], osm: str, lat: float,
        lon: float) -> tuple[Any, ...]:
    """Une ligne de ``place`` (sans son identifiant) : ce que la recherche et la fiche liront."""
    category = TOWNS if kind in PLACE_KINDS else POI_CATEGORY.get(kind, "")
    hours = osm_tags.clean(tags.get("opening_hours", ""), osm_tags.HOURS_MAX)
    return (name, kind, category, round(lat, 7), round(lon, 7), weight(kind, tags), "", osm,
            osm_tags.features_of(tags), osm_tags.cuisine_of(tags), hours, osm_tags.kept(tags))


def _tags(obj: Any) -> dict[str, str]:
    return {t.k: t.v for t in obj.tags}


def _pairs() -> list[tuple[str, str]]:
    return [(key, value) for key, kinds in OSM_KINDS for value in kinds]


# ── écrire ──

class _Writer:
    """Les lignes de ``place``, écrites par lots ; chacune reçoit son identifiant tout de suite."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db
        self.rows: list[tuple[Any, ...]] = []
        self.last = 0

    def add(self, values: tuple[Any, ...]) -> int:
        self.last += 1
        self.rows.append((self.last, *values))
        if len(self.rows) >= BATCH:
            self.flush()
        return self.last

    def flush(self) -> None:
        if self.rows:
            self.db.executemany("INSERT INTO place(id, name, kind, category, lat, lon, weight, town, osm, features, "
                                "cuisine, hours, tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", self.rows)
            self.db.commit()
            self.rows.clear()


# ── lire l'extrait ──

def _read(source: Path, entities: Any, *handlers: Any) -> Iterator[Any]:
    """Les objets de l'extrait qui passent ``handlers`` (des filtres et gestionnaires de pyosmium, appliqués dans
    l'ordre, avant Python) ; chacun gardé vivant le temps de la lecture."""
    pool = osmium.io.ThreadPool()
    with osmium.io.Reader(str(source), entities, thread_pool=pool) as reader:
        yield from osmium.OsmFileIterator(reader, *handlers)


class _Lookup:
    """Des identifiants (dans l'ordre où on les a vus) et la place de chacun, par recherche dichotomique."""

    def __init__(self, ids: array) -> None:
        ordered = all(ids[i] < ids[i + 1] for i in range(len(ids) - 1))
        self.order = None if ordered else sorted(range(len(ids)), key=ids.__getitem__)
        self.keys = ids if ordered else array("q", (ids[i] for i in self.order))  # type: ignore[union-attr]

    def find(self, key: int) -> int:
        at = bisect_left(self.keys, key)
        if at >= len(self.keys) or self.keys[at] != key:
            return -1
        return at if self.order is None else self.order[at]


def build(source: Path, out: Path, say: Callable[[str], None] = lambda _text: None) -> OsmBuilt:
    """L'index des lieux de cet extrait OpenStreetMap (``.osm.pbf``), écrit dans ``out`` au schéma 2."""
    if osmium is None:
        raise BuildFailed(MISSING)
    if not source.is_file():
        raise BuildFailed(f"l'extrait {source.name} n'est pas là")
    started = time.monotonic()
    partial = out.with_name(out.name + ".partiel")
    work = out.with_name(out.name + ".noeuds")
    db: sqlite3.Connection | None = None
    try:
        try:
            with osmium.io.Reader(str(source), osmium.osm.NOTHING) as reader:
                header = reader.header()
            extract = str(header.get("osmosis_replication_timestamp", "") or header.get("timestamp", "") or "")
            inside = _zone(header.box())
        except RuntimeError:
            raise BuildFailed(f"{source.name} n'est pas un extrait OpenStreetMap lisible (.osm.pbf)") from None
        partial.unlink(missing_ok=True)
        db = sqlite3.connect(partial)
        db.execute("PRAGMA journal_mode=OFF")
        db.execute("PRAGMA synchronous=OFF")
        db.execute("PRAGMA cache_size=-65536")
        db.executescript(DETAILED_SCHEMA)
        writer = _Writer(db)
        got = _passes(source, writer, work, say, inside)
        writer.flush()
        unplaced = _place(db, got, inside)
        say(f"{got.nodes + got.ways + got.relations} lieux lus, {unplaced} sans position ; ceux comptés deux fois…")
        twins = _twins(db)
        say("près de quelle ville est chacun…")
        towns(db)
        db.execute("INSERT INTO place_box(id, lat0, lat1, lon0, lon1) SELECT id, lat, lat, lon, lon FROM place")
        count = db.execute("SELECT count(*) FROM place").fetchone()[0]
        categories = dict(db.execute("SELECT category, count(*) FROM place GROUP BY category").fetchall())
        w, s, e, n = db.execute("SELECT min(lon), min(lat), max(lon), max(lat) FROM place").fetchone()
        bounds = ",".join(f"{v:.5f}" for v in (w or 0.0, s or 0.0, e or 0.0, n or 0.0))
        seal(db, partial, out, say, [("version", DETAILED_VERSION), ("source", source.name), ("count", str(count)),
                                     ("extract", extract), ("bounds", bounds)], more=(OSM_INDEX,))
        db = None
    except RuntimeError as exc:  # pyosmium : un extrait tronqué, abîmé
        raise BuildFailed(f"l'extrait ne se lit plus ({str(exc)[:200]})") from None
    except sqlite3.Error as exc:
        raise BuildFailed(f"l'index ne s'écrit pas ({exc})") from None
    except OSError as exc:
        raise BuildFailed(f"l'extrait ne se lit plus ({exc.strerror or exc})") from None
    finally:
        if db is not None:
            db.close()
        partial.unlink(missing_ok=True)
        _clear(work)
    order = [key for key, _label, _kinds in CATEGORIES]
    return OsmBuilt(out, count, {k: categories[k] for k in order if k in categories}, got.nodes, got.ways,
                    got.relations, got.unnamed, unplaced, twins, got.needed, got.slices, extract,
                    round(time.monotonic() - started, 1))


def _ints() -> array:
    return array("q")


def _floats() -> array:
    return array("d")


@dataclass
class _Read:
    """Ce que les passes ont trouvé : les lignes à placer et les positions de leurs voies."""

    nodes: int = 0
    ways: int = 0
    relations: int = 0
    unnamed: int = 0
    needed: int = 0
    slices: int = 0
    #: les lignes des voies gardées (leur identifiant de voie, leur ligne), et celles des relations (par rang)
    way_ids: array = field(default_factory=_ints)
    way_rows: array = field(default_factory=_ints)
    rel_rows: array = field(default_factory=_ints)
    #: chaque voie d'une relation : son identifiant, le rang de la relation
    member_ids: array = field(default_factory=_ints)
    member_of: array = field(default_factory=_ints)
    #: les voies notées, dans l'ordre de l'extrait (leur « place »), et ce que les tranches en ont tiré : la somme des
    #: positions de leurs nœuds, combien, et la position du nœud du milieu d'une voie ouverte (``mid_at`` : son rang)
    slot_ids: array = field(default_factory=_ints)
    sum_lat: array = field(default_factory=_floats)
    sum_lon: array = field(default_factory=_floats)
    seen: array = field(default_factory=_ints)
    mid_at: array = field(default_factory=_ints)
    mid_lat: array = field(default_factory=_floats)
    mid_lon: array = field(default_factory=_floats)


def _zone(box: Any) -> Callable[[float, float], bool]:
    """La zone que l'extrait dit couvrir (son en-tête), à ``ZONE_MARGIN`` près : un extrait de Geofabrik porte aussi
    les nœuds lointains d'une voie qui en sort (un bac vers l'Irlande) — pas des lieux de la zone. Sans zone dite :
    partout."""
    if box is None or not box.valid():
        return lambda _lat, _lon: True
    w, s = box.bottom_left.lon - ZONE_MARGIN, box.bottom_left.lat - ZONE_MARGIN
    e, n = box.top_right.lon + ZONE_MARGIN, box.top_right.lat + ZONE_MARGIN
    return lambda lat, lon: s <= lat <= n and w <= lon <= e


def _passes(source: Path, writer: _Writer, work: Path, say: Callable[[str], None],
            inside: Callable[[float, float], bool]) -> _Read:
    NODE, WAY, RELATION = osmium.osm.NODE, osmium.osm.WAY, osmium.osm.RELATION
    got = _Read()
    noted = osmium.IdTracker()  # les voies dont il faut la position

    # 1. les relations
    say("les relations…")
    wanted = osmium.filter.TagFilter(*_pairs())
    for rel in _read(source, RELATION, wanted):
        tags = _tags(rel)
        if tags.get("type") not in RELATION_TYPES:
            continue
        found = pick(tags)
        if found is None:
            got.unnamed += kind_of(tags) is not None
            continue
        kind, name = found
        if kind in PLACE_KINDS or (tags.get("type") == "boundary" and kind not in BOUNDARY_KINDS):
            continue
        index = len(got.rel_rows)
        got.rel_rows.append(writer.add(row(kind, name, tags, f"r{rel.id}", 0.0, 0.0)))
        for member in rel.members:
            if member.type == "w" and member.role in OUTER_ROLES:
                noted.add_way(member.ref)
                got.member_ids.append(member.ref)
                got.member_of.append(index)
    got.relations = len(got.rel_rows)

    # 2. les nœuds et les voies d'une sorte connue
    say(f"{got.relations} relations ; les nœuds et les voies…")
    wanted = osmium.filter.TagFilter(*_pairs())
    next_say = SAY_EVERY
    for obj in _read(source, NODE | WAY, wanted):
        tags = _tags(obj)
        found = pick(tags)
        if found is None:
            got.unnamed += kind_of(tags) is not None
            continue
        kind, name = found
        if obj.is_node():
            loc = obj.location
            if not loc.valid() or not inside(loc.lat, loc.lon):
                continue
            writer.add(row(kind, name, tags, f"n{obj.id}", loc.lat, loc.lon))
            got.nodes += 1
        else:
            got.way_rows.append(writer.add(row(kind, name, tags, f"w{obj.id}", 0.0, 0.0)))
            got.way_ids.append(obj.id)
            noted.add_way(obj.id)
            got.ways += 1
        if got.nodes + got.ways >= next_say:
            say(f"{got.nodes} nœuds et {got.ways} voies gardés")
            next_say += SAY_EVERY
    writer.flush()

    # 3. les voies notées : leurs nœuds, rangés sur le disque par tranche
    say(f"{got.nodes} nœuds et {got.ways} voies ; les nœuds des voies…")
    work.mkdir(exist_ok=True)
    files: dict[int, Any] = {}
    buffers: dict[int, array] = {}
    only_noted = noted.id_filter()
    try:
        for way in _read(source, WAY, only_noted):
            got.slot_ids.append(way.id)
            refs = [nd.ref for nd in way.nodes]
            closed = len(refs) > 3 and refs[0] == refs[-1]
            if closed:
                refs.pop()
            got.mid_at.append(-1 if closed or not refs else len(refs) // 2)
            for ref in refs:
                if ref <= 0:
                    continue
                part = ref // NODE_SLICE
                buf = buffers.get(part)
                if buf is None:
                    buf = buffers[part] = array("q")
                buf.append(ref)
                if len(buf) >= REFS_CHUNK:
                    _spill(work, files, part, buf)
        for part, buf in buffers.items():
            _spill(work, files, part, buf)
    finally:
        for f in files.values():
            f.close()
    slots = len(got.slot_ids)
    got.sum_lat, got.sum_lon = array("d", [0.0]) * slots, array("d", [0.0]) * slots
    got.seen = array("q", [0]) * slots
    got.mid_lat, got.mid_lon = array("d", [math.nan]) * slots, array("d", [math.nan]) * slots

    # 4. une passe par tranche : la position des nœuds de la tranche, que chaque voie reçoit
    parts = sorted(files)
    got.slices = len(parts)
    for number, part in enumerate(parts, 1):
        tracker = osmium.IdTracker()
        with (work / f"{part}.bin").open("rb") as f:
            while True:
                chunk = array("q")
                try:
                    chunk.fromfile(f, REFS_CHUNK)
                except EOFError:
                    pass
                if not chunk:
                    break
                tracker.add_references(types.SimpleNamespace(nodes=chunk))
        needed = len(tracker.node_ids())
        got.needed += needed
        say(f"tranche {number} sur {len(parts)} : {needed} nœuds à placer…")
        _slice(source, tracker, noted, got)
        del tracker
    return got


def _spill(work: Path, files: dict[int, Any], part: int, buf: array) -> None:
    if not buf:
        return
    f = files.get(part)
    if f is None:
        f = files[part] = (work / f"{part}.bin").open("wb")
    buf.tofile(f)
    del buf[:]


def _slice(source: Path, tracker: Any, noted: Any, got: _Read) -> None:
    """Une tranche : les nœuds notés gardent leur position (et eux seuls), chaque voie notée la reçoit — Python ne
    voit que les voies."""
    NODE, WAY = osmium.osm.NODE, osmium.osm.WAY
    nodes_only = tracker.id_filter()
    nodes_only.enable_for(NODE)
    ways_only = noted.id_filter()
    ways_only.enable_for(WAY)
    store = osmium.index.create_map("sparse_mem_array")
    locations = osmium.NodeLocationsForWays(store)
    locations.ignore_errors()
    no_nodes = osmium.filter.EntityFilter(WAY)
    slot_ids, sum_lat, sum_lon, seen = got.slot_ids, got.sum_lat, got.sum_lon, got.seen
    mid_at, mid_lat, mid_lon = got.mid_at, got.mid_lat, got.mid_lon
    k = 0
    for way in _read(source, NODE | WAY, nodes_only, ways_only, locations, no_nodes):
        if k >= len(slot_ids) or way.id != slot_ids[k]:
            raise BuildFailed("l'extrait a changé pendant la lecture : relance la construction")
        nodes = way.nodes
        lat = lon = 0.0
        n = 0
        for nd in nodes:
            loc = nd.location
            if loc.valid():
                lat += loc.lat
                lon += loc.lon
                n += 1
        count = len(nodes)
        if n and count > 3 and nodes[0].ref == nodes[count - 1].ref:  # fermée : son premier nœud n'y compte qu'une fois
            loc = nodes[0].location
            if loc.valid():
                lat -= loc.lat
                lon -= loc.lon
                n -= 1
        if n:
            sum_lat[k] += lat
            sum_lon[k] += lon
            seen[k] += n
            mid = mid_at[k]
            if mid >= 0:
                loc = nodes[mid].location
                if loc.valid():
                    mid_lat[k], mid_lon[k] = loc.lat, loc.lon
        k += 1


def _place(db: sqlite3.Connection, got: _Read, inside: Callable[[float, float], bool]) -> int:
    """La position des voies et des relations gardées ; celles qui n'en ont pas, ou hors de la zone de l'extrait,
    s'effacent. Rend combien se sont effacées."""
    lookup = _Lookup(got.slot_ids)
    moves: list[tuple[float, float, int]] = []
    gone: list[tuple[int]] = []

    def put(lat: float, lon: float, row_id: int) -> None:
        if inside(lat, lon):
            moves.append((round(lat, 7), round(lon, 7), row_id))
        else:
            gone.append((row_id,))

    for way_id, row_id in zip(got.way_ids, got.way_rows, strict=True):
        k = lookup.find(way_id)
        if k < 0 or not got.seen[k]:
            gone.append((row_id,))
        elif not math.isnan(got.mid_lat[k]):
            put(got.mid_lat[k], got.mid_lon[k], row_id)
        else:
            put(got.sum_lat[k] / got.seen[k], got.sum_lon[k] / got.seen[k], row_id)
    relations = len(got.rel_rows)
    lat, lon, seen = array("d", [0.0]) * relations, array("d", [0.0]) * relations, array("q", [0]) * relations
    for way_id, index in zip(got.member_ids, got.member_of, strict=True):
        k = lookup.find(way_id)
        if k >= 0 and got.seen[k]:
            lat[index] += got.sum_lat[k]
            lon[index] += got.sum_lon[k]
            seen[index] += got.seen[k]
    for index, row_id in enumerate(got.rel_rows):
        if seen[index]:
            put(lat[index] / seen[index], lon[index] / seen[index], row_id)
        else:
            gone.append((row_id,))
    for start in range(0, len(moves), BATCH):
        db.executemany("UPDATE place SET lat = ?, lon = ? WHERE id = ?", moves[start:start + BATCH])
    db.executemany("DELETE FROM place WHERE id = ?", gone)
    db.commit()
    return len(gone)


#: à renseignements égaux, on garde un nœud (posé par qui a cartographié) plutôt que le centre d'une voie ou d'une
#: relation
OBJECT_RANK = {"n": 0, "w": 1, "r": 2}


def _twins(db: sqlite3.Connection) -> int:
    """Un lieu cartographié deux fois (son point et son bâtiment, son nœud et sa relation) : même nom (à la casse
    près), même catégorie, à moins de ``SAME_PLACE_M`` (``SAME_TOWN_M`` pour un lieu habité) — on garde le plus
    renseigné, puis le plus important, puis un nœud. Rend combien sont partis."""
    gone: list[tuple[int]] = []
    group: list[tuple[int, float, float, tuple[int, int, int, int]]] = []
    current: tuple[str, str] | None = None

    def settle(radius: float) -> None:
        if len(group) < 2:
            return
        #: ceux qu'on garde, rangés par cases de ``radius`` (« Parking » en compte des milliers)
        cells: dict[tuple[int, int], list[tuple[float, float]]] = {}
        for pid, lat, lon, _rank in sorted(group, key=lambda g: g[3]):
            y = lat * M_PER_DEG
            x = lon * M_PER_DEG * max(0.05, math.cos(math.radians(lat)))
            cy, cx = int(y // radius), int(x // radius)
            if any(math.hypot(y - a, x - b) < radius for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                   for a, b in cells.get((cy + dy, cx + dx), ())):
                gone.append((pid,))
            else:
                cells.setdefault((cy, cx), []).append((y, x))

    rows = db.execute("SELECT id, name, category, lat, lon, length(tags), weight, osm FROM place "
                      "ORDER BY category, name COLLATE NOCASE, id")
    for pid, name, category, lat, lon, rich, weight_, osm in rows:
        key = (category, name.casefold())
        if key != current:
            if current is not None:
                settle(SAME_TOWN_M if current[0] == TOWNS else SAME_PLACE_M)
            group = []
            current = key
        group.append((pid, lat, lon, (-rich, -weight_, OBJECT_RANK.get(osm[:1], 3), pid)))
    if current is not None:
        settle(SAME_TOWN_M if current[0] == TOWNS else SAME_PLACE_M)
    db.executemany("DELETE FROM place WHERE id = ?", gone)
    db.commit()
    return len(gone)


def _clear(work: Path) -> None:
    if not work.is_dir():
        return
    for f in work.glob("*.bin"):
        f.unlink(missing_ok=True)
    try:
        work.rmdir()
    except OSError:
        pass
