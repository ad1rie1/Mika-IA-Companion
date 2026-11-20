"""De quoi essayer les avis (ADR 0256) sans réseau : les réponses réelles réduites de l'API Places (New) de Google
(``tests/fixtures/google/``, autour de la Grand-Place de Lille, le 20/11/2026 ; les noms des auteurs des avis et des
photos, leurs liens et les noms des photos remplacés par des valeurs fictives), une fausse API qui cherche dans un
cercle comme Google (les types premiers seuls, vingt au plus, par popularité ou par distance), ne rend que les champs
du masque et compte ses appels par SKU, et un cache des avis monté sur elle, avec une horloge qu'on avance."""

from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from mika.adapters.maps.cells import cell_of
from mika.adapters.maps.config import PlacesConfig, ReviewsConfig, RoutingConfig
from mika.adapters.maps.desk import MapsDesk
from mika.adapters.maps.google_places import (
    GOOGLE_MONTH,
    SKUS,
    PlacesClient,
    reviews_limits,
    sku_limits,
)
from mika.adapters.maps.quota import QUOTAS_FILE, Limiter, QuotaStore
from mika.adapters.maps.reviews import Reviews
from mika.adapters.maps.reviews_cells import ReviewsCells
from tests.fixtures.tourism import Clock, index_of, write_index

HERE = Path(__file__).parent / "google"
KEY = "cle-google-de-test-0123456789"
HOST = "places.googleapis.com"
#: la Grand-Place de Lille, et les trois lieux de la réponse réelle
GRAND_PLACE = (50.637, 3.063)
WESTFIELD, MEERT, BELLEZZA = "ChIJf4-ExorVwkcRumZKrEYj17w", "ChIJCZfCw4fVwkcRqvwNk2JOxks", "ChIJ-QA9R-vVwkcRvkZx8mgJpss"
NEARBY, DETAILS, MEDIA = "nearby", "details", "media"


def raw(name: str) -> Any:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def nearby() -> list[dict[str, Any]]:
    """Les trois lieux de la réponse réelle (``places:searchNearby``) : un centre commercial (son type premier :
    ``shopping_mall``), une pâtisserie, un restaurant italien."""
    return raw("nearby-lille.json")["places"]


def details() -> dict[str, Any]:
    """La fiche réelle de « La Bellezza Lille », avec ses avis (trois, réduits) et ce qu'elle sert."""
    return raw("details-avis.json")


def place(pid: str, name: str, lat: float, lon: float, *, rating: float | None = 4.0, count: int = 100,
          primary: str = "restaurant", price: str = "PRICE_LEVEL_MODERATE") -> dict[str, Any]:
    """Un lieu d'une recherche à proximité, sur le modèle de la réponse réelle (« La Bellezza Lille »)."""
    out = copy.deepcopy(next(p for p in nearby() if p["id"] == BELLEZZA))
    out.update(id=pid, displayName={"text": name, "languageCode": "fr"}, location={"latitude": lat, "longitude": lon},
               userRatingCount=count, primaryType=primary, types=[primary, "point_of_interest", "establishment"],
               googleMapsUri=f"https://maps.google.com/?cid={sum(map(ord, pid)) * 7919}")
    if rating is None:
        out.pop("rating", None)
    else:
        out["rating"] = rating
    if price:
        out["priceLevel"] = price
    else:
        out.pop("priceLevel", None)
    for k, photo in enumerate(out["photos"], start=1):
        photo["name"] = f"places/{pid}/photos/AV-photo-fictive-{k:02d}"
    return out


def many(count: int, *, primary: str = "restaurant", start: int = 1000, near: tuple[float, float] = GRAND_PLACE,
         cell_km: float = 3) -> list[dict[str, Any]]:
    """``count`` lieux dans la case de ``near``, des plus connus aux moins connus, notés de 5 à 1."""
    cell = cell_of(near[0], near[1], cell_km)
    rows = []
    for k in range(count):
        lat = cell.south + (cell.north - cell.south) * (0.1 + 0.8 * ((k * 37) % 100) / 100)
        lon = cell.west + (cell.east - cell.west) * (0.1 + 0.8 * ((k * 61) % 100) / 100)
        rating = round(5 - 4 * k / max(1, count - 1), 1)
        rows.append(place(f"ChIJlieu{primary[:4]}{start + k:06d}", f"Lieu {primary} {k}", lat, lon, rating=rating,
                          count=10_000 - k, primary=primary))
    return rows


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(min(1.0, math.sqrt(a)))


def _at(p: dict[str, Any]) -> tuple[float, float]:
    return p["location"]["latitude"], p["location"]["longitude"]


def _masked(item: dict[str, Any], fields: set[str]) -> dict[str, Any]:
    return {k: copy.deepcopy(v) for k, v in item.items() if k in fields}


def _error(status: int, message: str, code: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": status, "message": message, "status": code}})


@dataclass
class FakeGoogle:
    """L'API Places (New) jouée : ``places`` (des lieux d'une recherche à proximité), leurs fiches (``fiches`` : la
    réelle de « La Bellezza », par défaut ; un autre lieu : ce qu'en dit la recherche, sans avis) ; ``statuses`` : des
    réponses forcées, dans l'ordre (``None`` : la vraie ; ``"broken"`` : du JSON cassé) ; ``expired`` : des noms de
    photos qui ne valent plus ; ``requests`` : tout ce qu'elle a reçu."""

    places: list[dict[str, Any]] = field(default_factory=nearby)
    fiches: dict[str, dict[str, Any]] = field(default_factory=lambda: {BELLEZZA: details()})
    statuses: list[int | str | None] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    expired: set[str] = field(default_factory=set)
    requests: list[httpx.Request] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.statuses:
            forced = self.statuses.pop(0)
            if forced == "broken":
                return httpx.Response(200, text="{pas du json")
            if forced is not None:
                return _error(int(forced), f"refus {forced} {request.headers.get('x-goog-api-key')}", "FORCED")
        if request.headers.get("x-goog-api-key") != KEY:
            return _error(400, "API key not valid. Please pass a valid API key.", "INVALID_ARGUMENT")
        path = request.url.path
        if request.method == "POST" and path == "/v1/places:searchNearby":
            return self._nearby(request)
        found = re.fullmatch(r"/v1/(places/[^/]+/photos/[^/]+)/media", path)
        if request.method == "GET" and found:
            return self._media(request, found.group(1))
        found = re.fullmatch(r"/v1/places/([^/:]+)", path)
        if request.method == "GET" and found:
            return self._details(request, found.group(1))
        return _error(404, "Method not found.", "NOT_FOUND")

    def _mask(self, request: httpx.Request, prefix: str) -> set[str] | httpx.Response:
        mask = request.headers.get("x-goog-fieldmask", "")
        if not mask:
            return _error(400, "FieldMask is a required parameter.", "INVALID_ARGUMENT")
        return {f.removeprefix(prefix) for f in mask.split(",")}

    def _nearby(self, request: httpx.Request) -> httpx.Response:
        fields = self._mask(request, "places.")
        if isinstance(fields, httpx.Response):
            return fields
        body = json.loads(request.content)
        types = body.get("includedPrimaryTypes") or []
        count = body.get("maxResultCount", 20)
        if not 1 <= count <= 20:
            return _error(400, "maxResultCount must be between 1 and 20.", "INVALID_ARGUMENT")
        if len(types) > 50 or "includedTypes" in body:
            return _error(400, "Too many types.", "INVALID_ARGUMENT")
        if body.get("languageCode") != "fr":
            return _error(400, "languageCode expected.", "INVALID_ARGUMENT")
        circle = body["locationRestriction"]["circle"]
        center = (circle["center"]["latitude"], circle["center"]["longitude"])
        kept = [p for p in self.places if p.get("primaryType") in types
                and _distance_m(*center, *_at(p)) <= circle["radius"]]
        if body.get("rankPreference") == "DISTANCE":
            kept.sort(key=lambda p: _distance_m(*center, *_at(p)))
        else:
            kept.sort(key=lambda p: -p.get("userRatingCount", 0))
        chunk = [_masked(p, fields) for p in kept[:count]]
        return httpx.Response(200, json={"places": chunk} if chunk else {})

    def _details(self, request: httpx.Request, pid: str) -> httpx.Response:
        fields = self._mask(request, "")
        if isinstance(fields, httpx.Response):
            return fields
        if request.url.params.get("languageCode") != "fr":
            return _error(400, "languageCode expected.", "INVALID_ARGUMENT")
        fiche = self.fiches.get(pid) or next((p for p in self.places if p["id"] == pid), None)
        if fiche is None:
            return _error(404, f"Place '{pid}' not found.", "NOT_FOUND")
        return httpx.Response(200, json=_masked(fiche, fields))

    def _media(self, request: httpx.Request, name: str) -> httpx.Response:
        params = request.url.params
        if params.get("skipHttpRedirect") != "true" or not params.get("maxWidthPx"):
            return _error(400, "maxWidthPx or maxHeightPx is required.", "INVALID_ARGUMENT")
        if name in self.expired:
            return _error(400, "The photo resource in the request is invalid.", "INVALID_ARGUMENT")
        return httpx.Response(200, json={"name": name + "/media", "photoUri":
                                         f"https://lh3.googleusercontent.com/place-photos/{name.rsplit('/', 1)[1]}"})

    def rotate(self) -> None:
        """Google change le nom des photos : ceux d'avant ne valent plus (400), une nouvelle lecture rend les neufs."""
        for item in [*self.places, *self.fiches.values()]:
            for photo in item.get("photos", []):
                self.expired.add(photo["name"])
                photo["name"] += "v2"

    def calls(self, kind: str) -> int:
        """Combien d'appels de ce SKU (``NEARBY``, ``DETAILS``, ``MEDIA``) elle a reçus."""
        return sum(1 for r in self.requests if _kind(r) == kind)

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if _kind(r) == NEARBY]


def _kind(request: httpx.Request) -> str:
    path = request.url.path
    return NEARBY if path.endswith(":searchNearby") else MEDIA if path.endswith("/media") else DETAILS


@dataclass
class Rig:
    """Le cache des avis monté sur la fausse API : ``config[0]`` se change en cours de test."""

    cells: ReviewsCells
    reviews: Reviews
    client: PlacesClient
    clock: Clock
    config: list[ReviewsConfig]
    api: FakeGoogle


def limiters(data: Path, config: list[ReviewsConfig], clock: Clock) -> tuple[Limiter, dict[str, Limiter]]:
    store = QuotaStore(data / QUOTAS_FILE)
    main = Limiter("google", store, lambda: reviews_limits(config[0]), label="Google", unit="appels",
                   now=clock.stamp, sleep=clock.sleep)
    skus = {sku.service: Limiter(sku.service, store, lambda sku=sku: sku_limits(config[0], sku),
                                 label=f"Google ({sku.label})", unit=sku.unit, now=clock.stamp, sleep=clock.sleep,
                                 month_zone=GOOGLE_MONTH) for sku in SKUS}
    return main, skus


def rig(data: Path, api: FakeGoogle | None = None, *, cfg: ReviewsConfig | None = None, clock: Clock | None = None,
        index: Path | None = None, tourism: Path | None = None) -> Rig:
    api = api if api is not None else FakeGoogle()
    clock = clock or Clock()
    config = [cfg or ReviewsConfig(api_key=KEY)]
    main, skus = limiters(data, config, clock)
    client = PlacesClient(lambda: config[0], main, skus, transport=httpx.MockTransport(api))
    reviews = Reviews(data)
    cells = ReviewsCells(reviews, lambda: config[0], client, index=index_of(index), tourism=lambda: tourism,
                         clock=clock)
    return Rig(cells, reviews, client, clock, config, api)


#: des lieux d'OpenStreetMap autour de la Grand-Place (schéma 2) : (osm, nom, sorte, catégorie, lat, lon)
GRAND_PLACE_PLACES = (
    ("n301", "La Bellezza", "restaurant", "manger", 50.63898, 3.05881),         # « La Bellezza Lille », à ~1 m
    ("n302", "Méert", "pastry", "courses", 50.63771, 3.06200),                  # « Maison Méert », à ~1 m
    ("w303", "Westfield Euralille", "mall", "courses", 50.63722, 3.07429),       # un centre commercial : pas d'avis ici
    ("n304", "La Chicorée", "restaurant", "manger", 50.63720, 3.06330),         # pas chez Google
    ("w305", "Pharmacie de la Grand-Place", "pharmacy", "sante", 50.63690, 3.06350),
    ("n306", "Lille", "city", "villes", 50.6365, 3.0635),
)

#: une image JPEG minimale : ce que rendent les hôtes des images de Google
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


@dataclass
class Outside:
    """Tout ce qui sort du serveur, vu d'ici : l'API de Google (``api``), les hôtes de ses images ; ``seen`` : chaque
    demande, dans l'ordre."""

    api: FakeGoogle
    seen: list[httpx.Request] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        if request.url.host == HOST:
            return self.api(request)
        if request.url.host == "lh3.googleusercontent.com":
            return httpx.Response(200, content=JPEG)
        return httpx.Response(404)

    def hosts(self) -> list[str]:
        return [r.url.host for r in self.seen]


def desk(data: Path, api: FakeGoogle | None = None, *, cfg: ReviewsConfig | None = None, clock: Clock | None = None,
         places: tuple[tuple[str, str, str, str, float, float], ...] = GRAND_PLACE_PLACES,
         ) -> tuple[MapsDesk, Outside, Clock, list[ReviewsConfig]]:
    """Le vrai ``MapsDesk`` sur ``data``, son index des lieux autour de la Grand-Place, ses avis réglés (``config[0]``
    se change en cours de test) ; tout ce qui sort passe par ``outside``. Rend (desk, outside, clock, config)."""
    clock = clock or Clock()
    config = [cfg or ReviewsConfig(api_key=KEY)]
    if places:
        write_index(data / "cartes" / "lieux.db", places)
    outside = Outside(api if api is not None else FakeGoogle())
    maps = MapsDesk(data, lambda: PlacesConfig(), lambda: RoutingConfig(), reviews=lambda: config[0],
                    transport=httpx.MockTransport(outside), clock=clock, quota_now=clock.stamp,
                    quota_sleep=clock.sleep)
    return maps, outside, clock, config
