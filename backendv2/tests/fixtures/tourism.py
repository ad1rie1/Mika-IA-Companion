"""De quoi essayer les données touristiques (ADR 0245) sans réseau : les fiches réelles réduites de DATAtourisme
(``tests/fixtures/datatourisme/``, 17/11/2026, Licence Ouverte 2.0 ; les noms de contacts remplacés), une fausse API
qui pagine par ``next`` (des curseurs ``crs``) et filtre par département et par ``lastUpdate``, une horloge qu'on
avance, et un petit index des lieux d'OpenStreetMap (schéma 2) autour de Lille."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from mika.adapters.maps import places as pl
from mika.adapters.maps.config import TourismConfig
from mika.adapters.maps.datatourisme import DataTourismeClient, tourism_limits
from mika.adapters.maps.hours import PARIS
from mika.adapters.maps.quota import QUOTAS_FILE, Limiter, QuotaStore
from mika.adapters.maps.tourism import Tourism
from mika.adapters.maps.tourism_cells import TourismCells
from mika.adapters.maps.tourism_sync import TourismSync

HERE = Path(__file__).parent / "datatourisme"
#: le mercredi 18 novembre 2026, 10:00 à Paris : le lendemain des réponses réelles
NOW = datetime(2026, 11, 18, 10, 0, tzinfo=PARIS)
KEY = "cle-de-test-0123456789"
API = "https://api.datatourisme.fr/v1"
#: les identifiants des fiches qu'on cite
OBSESSION = ("05b31009-501b-36e0-a24a-cbb1f7144b61", "2bf5e5f0-e514-35eb-a378-eefeeeb78539",
             "63e5d569-d0fa-3f53-bcf4-84d410893512", "b5b247c7-7aec-3bfa-9bcb-a4e180d28dcc",
             "e8185770-bfa8-339d-b835-25df465b4773")
JULIEN_CLERC = "04c86f1e-6878-3d44-b732-1b8703baf69d"
POULENC = "2feb11ea-5038-35cf-bbe6-7646ef3c4f9e"
WAZEMMES = "978e8490-d4e0-3122-a8d2-d503b3886040"
RESORT = "51c8f7a1-25e0-3a9f-82b0-136e8d7d05de"
KREVETTE = "b0663d02-a762-3620-8838-e8e7ab0ec8ad"
MAMA = "0ace7ea5-f85e-3dca-b899-c05e1cdfd16c"
HILTON = "404cff43-9a3f-34f5-8e1b-fca6325eac8c"


def objects(name: str) -> list[dict[str, Any]]:
    return json.loads((HERE / name).read_text(encoding="utf-8"))["objects"]


def events() -> list[dict[str, Any]]:
    return objects("evenements-lille.json")


def restaurants() -> list[dict[str, Any]]:
    return objects("restaurants-lille.json")


def markets() -> list[dict[str, Any]]:
    return objects("evenements-annecy.json")


class Clock:
    """Une horloge qu'on avance (UTC) ; ``sleep`` l'avance d'autant, sans attendre."""

    def __init__(self, at: datetime = NOW) -> None:
        self.at = at.astimezone(PARIS)
        self.slept: list[float] = []

    def __call__(self) -> datetime:
        return self.at

    def stamp(self) -> float:
        return self.at.timestamp()

    def advance(self, **delta: float) -> None:
        self.at += timedelta(**delta)

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.at += timedelta(seconds=seconds)


def _department(o: dict[str, Any]) -> str:
    city = o["isLocatedAt"][0]["address"][0].get("hasAddressCity") or {}
    found = (city.get("isPartOfDepartment") or {}).get("insee")
    return found or (city.get("insee") or "")[:2]


def _inside(o: dict[str, Any], bounding: str) -> bool:
    if not bounding:
        return True
    n, w, s, e = (float(v) for v in bounding.split(","))
    geo = o["isLocatedAt"][0].get("geo") or {}
    lat, lon = geo.get("latitude"), geo.get("longitude")
    return lat is not None and s <= lat <= n and w <= lon <= e


def _keeps(o: dict[str, Any], expression: str) -> bool:
    for part in [p for p in expression.split(" AND ") if p]:
        name, op, value = re.match(r"^(.+?)\[(\w+)\]=(.*)$", part).groups()
        if name.endswith("isPartOfDepartment.insee"):
            dept = _department(o)
            if (op == "eq" and dept != value) or (op == "in" and dept not in value.split(",")) or \
                    (op == "exists" and bool(dept) != (value == "true")):
                return False
        elif name == "lastUpdate" and op == "gte" and o.get("lastUpdate", "") < value:
            return False
    return True


@dataclass
class FakeApi:
    """L'API de DATAtourisme jouée : ``fiches`` par liste, ``page_size`` par page (petit : plusieurs pages), un
    ``next`` qui porte un curseur ``crs`` — et ``api_key`` comme l'exemple de leur documentation, que le client doit
    laver ; ``statuses`` : des réponses forcées, dans l'ordre (``None`` : la vraie)."""

    fiches: dict[str, list[dict[str, Any]]]
    page_size: int = 3
    statuses: list[int | str | None] = field(default_factory=list)
    requests: list[httpx.Request] = field(default_factory=list)
    cursors: dict[str, tuple[str, str, str, int]] = field(default_factory=dict)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.statuses:
            forced = self.statuses.pop(0)
            if forced == "broken":
                return httpx.Response(200, text="{pas du json")
            if forced is not None:
                return httpx.Response(int(forced), json={"message": f"refus {forced} {request.headers.get('x-api-key')}"})
        if request.headers.get("x-api-key") != KEY:
            return httpx.Response(401, json={"message": "Invalid API key"})
        catalog = re.fullmatch(r"/v1/catalog/([0-9a-f-]{36})", request.url.path)
        if catalog:  # une fiche par son identifiant
            found = next((o for kept in self.fiches.values() for o in kept if o.get("uuid") == catalog.group(1)), None)
            return httpx.Response(200, json=found) if found else httpx.Response(404, json={"message": "Not found"})
        params = dict(request.url.params)
        if "crs" in params:
            state = self.cursors.get(params["crs"])
            if state is None:
                return httpx.Response(404, json={"message": "cursor expired"})
        else:
            state = (request.url.path.rsplit("/", 1)[1], params.get("filters", ""), params.get("geo_bounding", ""), 0)
        endpoint, expression, bounding, offset = state
        kept = [o for o in self.fiches.get(endpoint, []) if _keeps(o, expression) and _inside(o, bounding)]
        page = kept[offset:offset + self.page_size]
        following = None
        if offset + self.page_size < len(kept):
            token = f"c{len(self.cursors)}"
            self.cursors[token] = (endpoint, expression, bounding, offset + self.page_size)
            following = f"http://api.datatourisme.fr/v1/{endpoint}?page_size=100&lang=fr&crs={token}&api_key=FUITE"
        return httpx.Response(200, json={"objects": page, "meta": {"total": len(kept), "page": 1,
                                                                   "page_size": self.page_size, "next": following}})

    def urls(self) -> list[str]:
        return [str(r.url) for r in self.requests]

    def filters(self) -> list[str]:
        return [dict(r.url.params).get("filters", "") for r in self.requests if "crs" not in r.url.params]


def limiter(data: Path, config: list[TourismConfig], clock: Clock) -> Limiter:
    return Limiter("datatourisme", QuotaStore(data / QUOTAS_FILE), lambda: tourism_limits(config[0]),
                   label="DATAtourisme", now=clock.stamp, sleep=clock.sleep)


def index_of(index: Path | None):  # noqa: ANN201
    def lieux() -> tuple[Path, str] | None:
        if index is None or not index.exists():
            return None
        conn = sqlite3.connect(index)
        try:
            return index, conn.execute("SELECT value FROM meta WHERE key = 'built'").fetchone()[0]
        finally:
            conn.close()

    return lieux


def make_sync(data: Path, api: FakeApi, *, cfg: TourismConfig | None = None, clock: Clock | None = None,
              index: Path | None = None) -> tuple[TourismSync, Tourism, Clock, list[TourismConfig]]:
    """Une synchronisation des départements sur ``data`` contre la fausse API ; ``config[0]`` se change en cours de
    test."""
    clock = clock or Clock()
    config = [cfg or TourismConfig(api_key=KEY, zones=("59",))]
    tourism = Tourism(data, now=clock)
    client = DataTourismeClient(lambda: config[0], limiter(data, config, clock), transport=httpx.MockTransport(api))
    return TourismSync(tourism, lambda: config[0], client, index=index_of(index), clock=clock), tourism, clock, config


def make_cells(data: Path, api: FakeApi, *, cfg: TourismConfig | None = None, clock: Clock | None = None,
               index: Path | None = None) -> tuple[TourismCells, Tourism, Clock, list[TourismConfig]]:
    """Le cache par cases sur ``data`` contre la fausse API."""
    clock = clock or Clock()
    config = [cfg or TourismConfig(api_key=KEY)]
    tourism = Tourism(data, now=clock)
    client = DataTourismeClient(lambda: config[0], limiter(data, config, clock), transport=httpx.MockTransport(api))
    return TourismCells(tourism, lambda: config[0], client, index=index_of(index), clock=clock), tourism, clock, config


#: des lieux d'OpenStreetMap autour de Lille (schéma 2) : (osm, nom, sorte, catégorie, lat, lon)
LILLE_PLACES = (
    ("w100", "Hôtel Barrière Lille", "hotel", "dormir", 50.63665, 3.07725),   # le pendant du Resort, à ~10 m
    ("n101", "Krevette", "restaurant", "manger", 50.62510, 3.06800),          # le même, à ~15 m
    ("n102", "Boulangerie Paul", "bakery", "courses", 50.63900, 3.07100),      # près du Mama Shelter, un autre nom
    ("w103", "LaM", "museum", "voir", 50.63770, 3.14870),                     # le lieu d'Obsession, à ~15 m
    ("n104", "Le Colisée", "theatre", "sortir", 50.69060, 3.16340),            # celui de Julien Clerc et d'Éboué
    ("n105", "Kebab du Colisée", "fast_food", "manger", 50.69070, 3.16352),     # plus près, mais pas un lieu de scène
    ("n106", "Lille", "city", "villes", 50.6365, 3.0635),
)


def write_index(path: Path, rows=LILLE_PLACES, *, built: str = "2026-11-17T10:00:00Z") -> Path:
    """Un index des lieux de schéma 2, comme ``mika carte lieux`` l'écrit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    db = sqlite3.connect(path)
    db.executescript(pl.DETAILED_SCHEMA)
    for k, (osm, name, kind, category, lat, lon) in enumerate(rows, start=1):
        db.execute("INSERT INTO place(id, name, kind, category, lat, lon, weight, town, osm) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (k, name, kind, category, lat, lon, 1, "Lille", osm))
        db.execute("INSERT INTO place_box(id, lat0, lat1, lon0, lon1) VALUES (?, ?, ?, ?, ?)", (k, lat, lat, lon, lon))
    db.execute("INSERT INTO place_text(place_text) VALUES ('rebuild')")
    db.execute(pl.RANK_INDEX)
    db.execute(pl.OSM_INDEX)
    db.executemany("INSERT INTO meta(key, value) VALUES (?, ?)",
                   [("version", pl.DETAILED_VERSION), ("source", "essai.osm.pbf"), ("count", str(len(rows))),
                    ("bounds", "2.9,50.5,3.3,50.8"), ("built", built), ("extract", "2026-11-16T21:00:00Z")])
    db.commit()
    db.close()
    return path
