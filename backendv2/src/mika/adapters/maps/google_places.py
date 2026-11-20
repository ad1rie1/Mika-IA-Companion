"""Google Places (ADR 0256) : l'API officielle Places (New) (``places.googleapis.com/v1``), jointe par ce serveur seul
avec la clé de l'opérateur, et ce qu'on lit de ses réponses — un lieu, sa fiche avec ses avis, ses photos — pour le
cache des avis (``reviews``). Aucune page de Google n'est lue : seulement l'API, avec sa clé.

**Ce qui part** : le centre et le rayon d'un cercle tiré d'une case de la grille, ou la position d'un lieu de l'index
(jamais celle d'une personne) ; l'identifiant d'un lieu chez Google ; le nom d'une photo ; la clé dans l'en-tête
``X-Goog-Api-Key`` seul — jamais dans une adresse, un message d'erreur ou le journal.

**Le masque décide du prix** (``X-Goog-FieldMask``) : Google facture chaque appel au niveau le plus haut des champs
demandés (``tier``). Une recherche à proximité (``nearby``) ne demande que ce qu'une liste montre — note, nombre d'avis,
prix, horaires, photos : le SKU « Nearby Search Enterprise » (``SEARCH_FIELDS``), jamais un champ « Atmosphere » ; les
avis ne se demandent qu'à la fiche d'un lieu (``details``, ``DETAILS_FIELDS`` : « Place Details Enterprise +
Atmosphere ») ; une photo (``photo_uri``) : « Place Details Photos ». Les prix et les quotas offerts chaque mois sont
dans ``SKUS`` (vérifiés le 2026-11-20 sur la grille de Google).

**La cadence et la facture** : chaque appel passe par le limiteur partagé des services de la carte — celui de Google
(``quota.Limiter`` « google » : par seconde, sur 24 heures glissantes) et celui de son SKU (le mois de Google, qui
commence à minuit, heure du Pacifique), compté au mois dès qu'il part (``take(book=True)``) : deux appels en même temps
ne passent jamais tous deux sous le plafond, et une erreur compte aussi — le compteur ne sous-estime jamais la facture.
Un 429 fait reculer le limiteur de ce SKU (chaque méthode a son quota par minute chez Google), le temps que Google dit
(``Retry-After``) ou une minute.

**Les erreurs** se disent en mots (``PlacesUnavailable``, une ``MapsUnavailable`` qui dit aussi sa sorte) : la clé
refusée (400 « API key not valid », 401), l'API non activée ou la clé restreinte (403), attendre (429), une demande
refusée (400, avec le message de Google), un lieu ou une photo qu'il ne connaît plus (404), le serveur en panne (5xx),
une réponse illisible.

**Une réponse lue** (``read_place``, ``read_review``, ``read_photos``) ne garde que ce que la fiche montre : jamais une
adresse qui ne soit pas chez Google ; le texte sans caractères invisibles, borné. Ce qu'on ne lit pas est laissé,
jamais une erreur."""

from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

import httpx

from mika.adapters.maps.config import ReviewsConfig, reviews_key
from mika.adapters.maps.pace import client
from mika.adapters.maps.quota import Limiter, Limits
from mika.adapters.maps.tiles import read_capped
from mika.ports.maps import MapsUnavailable, Review
from mika.ports.preprocess import visible

log = logging.getLogger("mika.maps.google")

API_URL = "https://places.googleapis.com/v1"
LANGUAGE = "fr"
#: Google remet ses quotas offerts à zéro le premier du mois, à minuit, heure du Pacifique
GOOGLE_MONTH = ZoneInfo("America/Los_Angeles")

# ── les sortes : ce que le cache tient au chaud, dans cet ordre ──
EAT, SEE, SLEEP = "manger", "voir", "dormir"
SORTS = (EAT, SEE, SLEEP)
SORT_FR = {EAT: "restaurants", SEE: "lieux à voir", SLEEP: "hébergements"}
#: la sorte d'une catégorie de l'écran Carte ; les autres (une pharmacie, une station) n'ont pas d'avis ici
FOR_CATEGORY = {"manger": EAT, "dormir": SLEEP, "voir": SEE, "nature": SEE}
#: … et des sortes d'autres catégories que Google tient pour l'une des nôtres (« Méert », une pâtisserie, se mange)
FOR_KIND = {"bakery": EAT, "pastry": EAT, "chocolate": EAT, "confectionery": EAT, "deli": EAT,
            "theatre": SEE, "arts_centre": SEE}
#: les types premiers de Google de chaque sorte (``includedPrimaryTypes`` : le type premier seul, jamais un type
#: secondaire — un centre commercial typé aussi « restaurant » ne remonte pas ; un type général ne vaut pas ses
#: sous-types, d'où les listes) ; au plus ``TYPES_MAX`` chacune, toutes de la table A de Google
PRIMARY_TYPES: dict[str, tuple[str, ...]] = {
    EAT: (
        "restaurant", "french_restaurant", "italian_restaurant", "pizza_restaurant", "bistro",
        "fine_dining_restaurant", "family_restaurant", "fast_food_restaurant", "hamburger_restaurant",
        "sandwich_shop", "japanese_restaurant", "sushi_restaurant", "ramen_restaurant", "chinese_restaurant",
        "asian_restaurant", "vietnamese_restaurant", "thai_restaurant", "korean_restaurant", "indian_restaurant",
        "lebanese_restaurant", "middle_eastern_restaurant", "mediterranean_restaurant", "greek_restaurant",
        "turkish_restaurant", "kebab_shop", "moroccan_restaurant", "african_restaurant", "spanish_restaurant",
        "tapas_restaurant", "portuguese_restaurant", "mexican_restaurant", "american_restaurant",
        "belgian_restaurant", "seafood_restaurant", "steak_house", "vegetarian_restaurant", "vegan_restaurant",
        "brunch_restaurant", "breakfast_restaurant", "buffet_restaurant", "gastropub", "bar_and_grill", "cafe",
        "coffee_shop", "tea_house", "bakery", "pastry_shop", "ice_cream_shop", "bar", "pub",
    ),
    SEE: (
        "tourist_attraction", "museum", "art_museum", "history_museum", "art_gallery", "historical_place",
        "historical_landmark", "cultural_landmark", "monument", "castle", "church", "synagogue", "mosque",
        "buddhist_temple", "hindu_temple", "fountain", "sculpture", "plaza", "park", "city_park", "garden",
        "botanical_garden", "national_park", "state_park", "hiking_area", "zoo", "aquarium", "wildlife_park",
        "amusement_park", "water_park", "observation_deck", "ferris_wheel", "planetarium",
        "performing_arts_theater", "opera_house", "concert_hall", "philharmonic_hall", "cultural_center",
        "visitor_center", "marina", "amphitheatre",
    ),
    SLEEP: (
        "hotel", "lodging", "motel", "hostel", "inn", "bed_and_breakfast", "guest_house", "resort_hotel",
        "extended_stay_hotel", "campground", "camping_cabin", "cottage", "farmstay", "private_guest_room", "rv_park",
    ),
}
TYPES_MAX = 50
#: une recherche à proximité rend au plus vingt lieux, sans page suivante
RESULTS_MAX = 20
RADIUS_MAX_M = 50_000.0
POPULARITY, DISTANCE = "POPULARITY", "DISTANCE"
#: un lieu de l'index pas encore rapproché : on le cherche tout près de lui, les plus proches d'abord
PROBE_RADIUS_M = 100.0
PROBE_COUNT = 10
#: la largeur des photos demandées (Google les rend à cette largeur au plus)
PHOTO_WIDTH = 800
TIMEOUT_S = 20.0
RESPONSE_MAX_BYTES = 8 * 1024 * 1024
#: ce qu'attend une demande en direct (une personne attend sa réponse) que le limiteur la laisse partir
LIVE_WAIT_S = 3.0
#: un 429 sans ``Retry-After`` : plus rien de ce SKU ne part pendant tant de secondes
BACK_OFF_S = 60.0
BACK_OFF_MAX_S = 86_400.0
#: les hôtes de Google : seule une adresse chez eux se garde (la page d'un lieu, le profil d'un auteur)
HOSTS = ("google.com",)
#: … et ceux de ses images (``photoUri``) : le relais ne va chercher une photo que là
PHOTO_HOSTS = ("googleusercontent.com", "ggpht.com")
_PLACE_ID = re.compile(r"^[A-Za-z0-9_-]{8,300}$")
_PHOTO_NAME = re.compile(r"^places/[A-Za-z0-9_-]{8,300}/photos/[A-Za-z0-9_-]{8,1200}$")

# ── les masques et les SKU ──
#: les champs de chaque niveau facturé, tels que les pages de Google les listent (Nearby Search et Place Details
#: (New), 2026-11-20) : le niveau « Pro » (ou « Essentials ») pour le reste
ENTERPRISE_FIELDS = frozenset({
    "currentOpeningHours", "currentSecondaryOpeningHours", "internationalPhoneNumber", "nationalPhoneNumber",
    "priceLevel", "priceRange", "rating", "regularOpeningHours", "regularSecondaryOpeningHours", "transitStation",
    "userRatingCount", "websiteUri"})
ATMOSPHERE_FIELDS = frozenset({
    "allowsDogs", "curbsidePickup", "delivery", "dineIn", "editorialSummary", "evChargeAmenitySummary",
    "evChargeOptions", "fuelOptions", "generativeSummary", "goodForChildren", "goodForGroups", "goodForWatchingSports",
    "liveMusic", "menuForChildren", "neighborhoodSummary", "parkingOptions", "paymentOptions", "outdoorSeating",
    "reservable", "restroom", "reviews", "reviewSummary", "routingSummaries", "servesBeer", "servesBreakfast",
    "servesBrunch", "servesCocktails", "servesCoffee", "servesDessert", "servesDinner", "servesLunch",
    "servesVegetarianFood", "servesWine", "takeout"})
PRO, ENTERPRISE, ATMOSPHERE = "pro", "enterprise", "atmosphere"
#: ce qu'une liste montre d'un lieu : le niveau « Enterprise » (note, nombre d'avis, prix, horaires, photos)
SEARCH_FIELDS = ("id", "displayName", "location", "primaryType", "formattedAddress", "googleMapsUri",
                 "businessStatus", "photos", "rating", "userRatingCount", "priceLevel", "priceRange",
                 "regularOpeningHours")
#: … et la fiche d'un lieu : le niveau « Enterprise + Atmosphere » (ses avis, son résumé, ce qu'il sert)
ATTRIBUTES = ("outdoorSeating", "servesVegetarianFood", "takeout", "delivery", "reservable")
DETAILS_FIELDS = (*SEARCH_FIELDS, "reviews", "editorialSummary", *ATTRIBUTES)
SEARCH_MASK = ",".join(f"places.{f}" for f in SEARCH_FIELDS)
DETAILS_MASK = ",".join(DETAILS_FIELDS)


def tier(mask: str) -> str:
    """Le niveau qu'un masque fait facturer : le plus haut de ses champs (``places.rating`` compte comme ``rating``)."""
    fields = {f.strip().removeprefix("places.").split(".")[0] for f in mask.split(",") if f.strip()}
    return ATMOSPHERE if fields & ATMOSPHERE_FIELDS else ENTERPRISE if fields & ENTERPRISE_FIELDS else PRO


@dataclass(frozen=True, slots=True)
class Sku:
    """Un niveau facturé par Google : ``service``, le nom de son compteur (``cartes/quotas.db``) ; ``name``, le sien
    chez Google ; ``label`` et ``unit``, en mots ; ``free``, combien sont offerts chaque mois ; ``price``, en dollars
    les mille au premier palier (jusqu'à 100 000 par mois)."""

    service: str
    name: str
    label: str
    unit: str
    free: int
    price: float

    def billed(self, used: int) -> float:
        """Ce que Google facturerait pour ``used`` appels dans le mois (en dollars), d'après nos comptes."""
        return max(0, used - self.free) * self.price / 1000


NEARBY = Sku("google-recherches", "Nearby Search Enterprise", "recherches à proximité", "recherches", 1000, 35.0)
DETAILS = Sku("google-fiches", "Place Details Enterprise + Atmosphere", "fiches avec avis", "fiches", 1000, 25.0)
PHOTO = Sku("google-photos", "Place Details Photos", "photos", "photos", 1000, 7.0)
SKUS = (NEARBY, DETAILS, PHOTO)
#: quand on a vérifié les prix et les quotas offerts sur la grille de Google
PRICES_CHECKED = "2026-11-20"

# ── les erreurs ──
AUTH, FORBIDDEN, BUSY, REFUSED, MISSING, SERVER, BROKEN, NETWORK = (
    "cle", "offre", "attendre", "refus", "absent", "serveur", "illisible", "reseau")
NO_KEY = "Aucune clé Google n'est réglée."


class PlacesUnavailable(MapsUnavailable):
    """Ce qui empêche de joindre Google, en une phrase ; ``kind`` dit quoi (``AUTH``, ``BUSY``…), pour savoir quand
    réessayer."""

    def __init__(self, text: str, kind: str) -> None:
        super().__init__(text)
        self.kind = kind


def reviews_limits(cfg: ReviewsConfig) -> Limits:
    """Les bornes de Google pour tous ses appels, d'après son réglage : par seconde, sur 24 heures, la réserve gardée
    au direct."""
    return Limits(per_second=cfg.per_second, per_day=cfg.per_day, reserve=cfg.reserve_pct / 100)


def sku_limits(cfg: ReviewsConfig, sku: Sku) -> Limits:
    """Le plafond du mois d'un SKU, d'après son réglage, et la réserve gardée au direct."""
    month = {NEARBY.service: cfg.searches_per_month, DETAILS.service: cfg.details_per_month,
             PHOTO.service: cfg.photos_per_month}[sku.service]
    return Limits(per_month=month, reserve=cfg.reserve_pct / 100)


class PlacesClient:
    """L'API Places (New), avec la clé du réglage (``config``, relu à chaque appel : la console la change sans
    redémarrer ; ``reviews_key``), sous le limiteur de Google (``limiter``) et celui de chaque SKU (``skus``, par
    ``Sku.service``)."""

    def __init__(self, config: Callable[[], ReviewsConfig], limiter: Limiter, skus: Mapping[str, Limiter], *,
                 transport: httpx.AsyncBaseTransport | None = None, base: str = API_URL) -> None:
        self.config = config
        self.limiter = limiter
        self.skus = dict(skus)
        self.base = base.rstrip("/")
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        #: depuis le démarrage, pour la console
        self.asked = 0
        self.failed = 0
        self.last_error = ""

    def key(self) -> str:
        return reviews_key(self.config())[0]

    def ready(self) -> bool:
        return bool(self.key())

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = client(TIMEOUT_S, self._transport)
        return self._client

    # ── les appels ──
    async def nearby(self, lat: float, lon: float, radius_m: float, sort: str, *, rank: str = POPULARITY,
                     count: int = RESULTS_MAX, background: bool = False,
                     wait_max: float = LIVE_WAIT_S) -> list[dict[str, Any]]:
        """Les lieux de cette sorte dans ce cercle (son centre et son rayon : un cercle d'une case, ou un lieu de
        l'index — jamais une personne), les plus connus d'abord (``POPULARITY``) ou les plus proches (``DISTANCE``),
        vingt au plus : une recherche « Nearby Search Enterprise »."""
        if sort not in SORTS or rank not in (POPULARITY, DISTANCE):
            raise ValueError("une sorte de lieu, et l'ordre de la popularité ou de la distance")
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("un point du monde")
        body = {"includedPrimaryTypes": list(PRIMARY_TYPES[sort]),
                "maxResultCount": max(1, min(RESULTS_MAX, int(count))), "rankPreference": rank,
                "languageCode": LANGUAGE,
                "locationRestriction": {"circle": {"center": {"latitude": round(lat, 6), "longitude": round(lon, 6)},
                                                   "radius": round(max(1.0, min(RADIUS_MAX_M, float(radius_m))), 1)}}}
        found = await self._call(NEARBY, "POST", "/places:searchNearby", mask=SEARCH_MASK, body=body,
                                 background=background, wait_max=wait_max)
        places = found.get("places", []) if isinstance(found, dict) else None
        if not isinstance(places, list):
            raise PlacesUnavailable("Google a rendu une réponse illisible.", BROKEN)
        return [p for p in places if isinstance(p, dict)]

    async def details(self, place_id: str, *, background: bool = False,
                      wait_max: float = LIVE_WAIT_S) -> dict[str, Any]:
        """La fiche d'un lieu avec ses avis, son résumé, ses photos, ce qu'il sert : un appel « Place Details
        Enterprise + Atmosphere »."""
        if not _PLACE_ID.match(place_id or ""):
            raise ValueError("un identifiant de lieu de Google")
        found = await self._call(DETAILS, "GET", f"/places/{place_id}", mask=DETAILS_MASK,
                                 params={"languageCode": LANGUAGE}, background=background, wait_max=wait_max)
        if not isinstance(found, dict):
            raise PlacesUnavailable("Google a rendu une réponse illisible.", BROKEN)
        return found

    async def photo_uri(self, name: str, *, background: bool = False, wait_max: float = LIVE_WAIT_S) -> str:
        """L'adresse de l'image d'une photo (son nom, tiré d'une réponse ; il peut avoir expiré : 400 ou 404), à
        ``PHOTO_WIDTH`` pixels de large, sur un hôte de Google : un appel « Place Details Photos »."""
        if not _PHOTO_NAME.match(name or ""):
            raise ValueError("un nom de photo de Google")
        found = await self._call(PHOTO, "GET", f"/{quote(name, safe='/')}/media",
                                 params={"maxWidthPx": str(PHOTO_WIDTH), "skipHttpRedirect": "true"},
                                 background=background, wait_max=wait_max)
        uri = found.get("photoUri") if isinstance(found, dict) else None
        if not isinstance(uri, str) or not _on(uri, PHOTO_HOSTS):
            raise PlacesUnavailable("Google a rendu une adresse de photo qu'on ne joint pas.", BROKEN)
        return uri

    async def _call(self, sku: Sku, method: str, path: str, *, mask: str = "", body: object = None,
                    params: Mapping[str, str] | None = None, background: bool, wait_max: float) -> object:
        if not self.key():
            raise PlacesUnavailable(NO_KEY, AUTH)
        # le jour et la seconde de tout Google, puis le mois de ce SKU, compté dès qu'il part (le dernier : un appel
        # retenu ailleurs ne lui coûte rien)
        await self.limiter.take(background=background, wait_max=wait_max)
        await self.skus[sku.service].take(background=background, wait_max=0.0, book=True)
        key = self.key()
        if not key:
            raise PlacesUnavailable(NO_KEY, AUTH)
        self.asked += 1
        try:
            raw = await self._ask(method, path, key, mask=mask, body=body, params=params, sku=sku)
            try:
                return json.loads(raw)
            except ValueError:
                raise PlacesUnavailable("Google a rendu une réponse illisible.", BROKEN) from None
        except PlacesUnavailable as exc:
            self.failed += 1
            self.last_error = str(exc)
            log.info("google : %s en échec (%s)", sku.name, exc.kind)  # jamais la clé, ni ce qui est parti
            raise

    async def _ask(self, method: str, path: str, key: str, *, mask: str, body: object,
                   params: Mapping[str, str] | None, sku: Sku) -> bytes:
        headers = {"X-Goog-Api-Key": key, "Accept": "application/json"}
        if mask:
            headers["X-Goog-FieldMask"] = mask
        try:
            async with self._http().stream(method, self.base + path, params=dict(params or {}), json=body,
                                           headers=headers) as r:
                status = r.status_code
                wait = r.headers.get("retry-after", "")
                if status == 200:
                    return await read_capped(r, RESPONSE_MAX_BYTES)
                said = _said(await read_capped(r, 64 * 1024), key) if 400 <= status < 500 else ""
        except httpx.HTTPError as exc:
            raise PlacesUnavailable(f"Google ne répond pas ({type(exc).__name__}).", NETWORK) from None
        except ValueError:
            raise PlacesUnavailable("Google a rendu une réponse démesurée.", BROKEN) from None
        tail = f" : {said}" if said else ""
        if status == 401 or (status == 400 and "api key" in said.lower()):
            raise PlacesUnavailable(f"Google refuse la clé (HTTP {status}{tail}) : vérifie-la dans la console.", AUTH)
        if status == 403:
            raise PlacesUnavailable("Google refuse cette demande : l'API Places (New) n'est pas activée sur ce projet, "
                                    "sa facturation n'est pas ouverte, ou la clé est restreinte à autre chose "
                                    f"(HTTP 403{tail}).", FORBIDDEN)
        if status == 429:
            self.skus[sku.service].back_off(_retry_after(wait))
            raise PlacesUnavailable("Google demande d'attendre (HTTP 429) : ce qui reste reprendra plus tard.", BUSY)
        if status == 404:
            raise PlacesUnavailable(f"Google ne connaît pas (ou plus) ce lieu ou cette photo (HTTP 404{tail}).",
                                    MISSING)
        if status >= 500:
            raise PlacesUnavailable(f"Google est en panne (HTTP {status}).", SERVER)
        raise PlacesUnavailable(f"Google refuse la demande (HTTP {status}{tail}).", REFUSED)


def _retry_after(value: str) -> float:
    """Ce que dit ``Retry-After`` en secondes, borné ; une date, illisible ou absent : ``BACK_OFF_S``."""
    value = value.strip()
    return max(1.0, min(BACK_OFF_MAX_S, float(value))) if value.isdigit() else BACK_OFF_S


def _said(raw: bytes, key: str) -> str:
    """Ce qu'une réponse en refus dit d'elle-même (``error.message``), en une ligne courte — la clé jamais recopiée."""
    try:
        body = json.loads(raw)
    except ValueError:
        return ""
    error = body.get("error") if isinstance(body, dict) else None
    found = error.get("message") if isinstance(error, dict) else None
    if not isinstance(found, str):
        return ""
    flat = " ".join(visible(found).split())
    return (flat.replace(key, "…") if key else flat)[:200]


def _on(url: str, hosts: Iterable[str]) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and not parts.username and not parts.password and " " not in url and \
        any(host == h or host.endswith("." + h) for h in hosts)


def google_url(value: object) -> str:
    """Une adresse en https chez Google (la page d'un lieu, le profil d'un auteur), telle quelle ; ailleurs, ou
    illisible : vide."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    return value[:600] if _on(value, HOSTS) else ""


# ── ce qu'on lit d'une réponse ──
#: le prix d'un lieu (``priceLevel``) en euros
PRICE = {"PRICE_LEVEL_INEXPENSIVE": "€", "PRICE_LEVEL_MODERATE": "€€", "PRICE_LEVEL_EXPENSIVE": "€€€",
         "PRICE_LEVEL_VERY_EXPENSIVE": "€€€€"}
OPERATIONAL, CLOSED_TEMPORARILY, CLOSED_PERMANENTLY = "OPERATIONAL", "CLOSED_TEMPORARILY", "CLOSED_PERMANENTLY"
NAME_MAX, TEXT_MAX, AUTHOR_MAX, SUMMARY_MAX = 200, 4000, 80, 400
REVIEWS_MAX, PHOTOS_MAX = 5, 10
#: ce que dit la fiche (Atmosphere), sous le libellé de la fiche d'OpenStreetMap, et ses mots pour oui et non
ATTRIBUTE_FR = {"outdoorSeating": ("Terrasse", "oui", "non"), "servesVegetarianFood": ("Végétarien", "oui", "non"),
                "takeout": ("À emporter", "oui", "non"), "delivery": ("Livraison", "oui", "non"),
                "reservable": ("Réservation", "possible", "non")}


@dataclass(frozen=True, slots=True)
class SpotPhoto:
    """Une photo d'un lieu : son nom chez Google (``places/…/photos/…`` : il peut expirer, on le relit avec la fiche),
    ses dimensions, son auteur (son nom et le lien de son profil, à montrer avec elle)."""

    name: str
    width: int | None = None
    height: int | None = None
    author: str = ""
    author_url: str = ""


@dataclass(frozen=True, slots=True)
class Spot:
    """Un lieu de Google tel que le cache le garde : son identifiant, son nom, sa sorte (``SORTS`` ; vide : inconnue),
    sa position, son type premier ; sa note (sur 5), le nombre de ses avis, son prix en euros et la fourchette qu'il
    donne, sa page chez Google, s'il est ouvert (``OPERATIONAL``…), son adresse, ses horaires en clair, ses photos ; et,
    lu à sa fiche seulement (``detailed``), son résumé, ce qu'il sert (``ATTRIBUTES`` : oui ou non) et ses avis."""

    id: str
    name: str
    sort: str
    lat: float
    lon: float
    kind: str = ""
    rating: float | None = None
    count: int | None = None
    price: str = ""
    price_range: str = ""
    url: str = ""
    status: str = ""
    address: str = ""
    hours: tuple[str, ...] = ()
    photos: tuple[SpotPhoto, ...] = ()
    detailed: bool = False
    summary: str = ""
    attributes: tuple[tuple[str, bool], ...] = ()
    reviews: tuple[Review, ...] = ()


def _text(value: object, most: int) -> str:
    if not isinstance(value, str):
        return ""
    flat = " ".join(visible(value).split())
    return flat if len(flat) <= most else flat[: most - 1].rstrip() + "…"


def _paragraphs(value: object, most: int) -> str:
    """Un texte en paragraphes : ses lignes gardées, leurs blancs repliés, au plus une ligne vide de suite."""
    if not isinstance(value, str):
        return ""
    lines: list[str] = []
    for line in visible(value.replace("\r\n", "\n").replace("\r", "\n")).split("\n"):
        line = " ".join(line.split())
        if line or (lines and lines[-1]):
            lines.append(line)
    out = "\n".join(lines).strip()
    return out if len(out) <= most else out[: most - 1].rstrip() + "…"


def _localized(value: object) -> tuple[str, str]:
    """Un texte de Google (``{text, languageCode}``) et sa langue ; illisible : rien."""
    if not isinstance(value, dict) or not isinstance(value.get("text"), str):
        return "", ""
    return value["text"], str(value.get("languageCode") or "")[:8]


def _int(value: object) -> int | None:
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value < 0:
        return None
    return int(value)


def _rating(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return round(float(value), 1) if 0 <= value <= 5 else None


def _coordinate(value: object, bound: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return round(float(value), 6) if -bound <= value <= bound else None


def price_range(value: object) -> str:
    """« 20–40 € » (``priceRange``) ; sans fin, « 100 € et plus » ; une autre monnaie, son code ; illisible : vide."""
    if not isinstance(value, dict):
        return ""
    start = value.get("startPrice") if isinstance(value.get("startPrice"), dict) else {}
    end = value.get("endPrice") if isinstance(value.get("endPrice"), dict) else {}
    low, high = _int(start.get("units")), _int(end.get("units"))
    currency = str(start.get("currencyCode") or end.get("currencyCode") or "")
    sign = "€" if currency == "EUR" else currency if re.fullmatch(r"[A-Z]{3}", currency) else ""
    if low is None or not sign:
        return ""
    if high is not None and high > low:
        return f"{low}–{high} {sign}"
    return f"{low} {sign} et plus" if high is None else f"{low} {sign}"


def read_photos(value: object) -> tuple[SpotPhoto, ...]:
    """Les photos d'un lieu (``photos``), chacune avec son premier auteur, au plus ``PHOTOS_MAX`` ; un nom illisible
    est laissé."""
    out: list[SpotPhoto] = []
    for raw in value if isinstance(value, list) else ():
        if not isinstance(raw, dict) or not _PHOTO_NAME.match(str(raw.get("name") or "")):
            continue
        authors = [a for a in raw.get("authorAttributions") or () if isinstance(a, dict)]
        first = authors[0] if authors else {}
        out.append(SpotPhoto(raw["name"], _int(raw.get("widthPx")), _int(raw.get("heightPx")),
                             _text(first.get("displayName"), AUTHOR_MAX), google_url(first.get("uri"))))
        if len(out) >= PHOTOS_MAX:
            break
    return tuple(out)


def read_review(raw: object) -> Review | None:
    """Un avis : sa note (1 à 5), son texte (en français : Google le traduit au besoin) et sa langue, son auteur (son
    nom et le lien de son profil), quand (le jour, et en mots). Sans note : ``None``. Ne lève jamais."""
    if not isinstance(raw, dict):
        return None
    try:
        rating = _rating(raw.get("rating"))
        if rating is None or rating < 1:
            return None
        text, language = _localized(raw.get("text"))
        if not text:
            text, language = _localized(raw.get("originalText"))
        author = raw.get("authorAttribution") if isinstance(raw.get("authorAttribution"), dict) else {}
        published = raw.get("publishTime")
        day = published[:10] if isinstance(published, str) and re.match(r"\d{4}-\d{2}-\d{2}", published) else ""
        return Review(rating=rating, text=_paragraphs(text, TEXT_MAX), author=_text(author.get("displayName"),
                                                                                     AUTHOR_MAX),
                      date=day, language=language, author_url=google_url(author.get("uri")),
                      relative=_text(raw.get("relativePublishTimeDescription"), 60))
    except (TypeError, ValueError, AttributeError, KeyError):
        return None


def read_place(raw: object, sort: str = "", *, detailed: bool = False) -> Spot | None:
    """Un lieu d'une réponse : un résultat d'une recherche à proximité, ou une fiche (``detailed`` : ses avis, son
    résumé, ce qu'il sert) ; ``sort`` : la sorte qu'on cherchait. Sans identifiant, nom ou position : ``None``. Ne lève
    jamais."""
    try:
        return _place(raw, sort, detailed)
    except (TypeError, ValueError, AttributeError, KeyError):
        return None


def _place(raw: object, sort: str, detailed: bool) -> Spot | None:
    if not isinstance(raw, dict):
        return None
    pid = raw.get("id") if isinstance(raw.get("id"), str) and _PLACE_ID.match(raw["id"]) else ""
    name = _text(_localized(raw.get("displayName"))[0], NAME_MAX)
    where = raw.get("location") if isinstance(raw.get("location"), dict) else {}
    lat, lon = _coordinate(where.get("latitude"), 90), _coordinate(where.get("longitude"), 180)
    if not pid or not name or lat is None or lon is None:
        return None
    hours = raw.get("regularOpeningHours") if isinstance(raw.get("regularOpeningHours"), dict) else {}
    week = tuple(_text(d, 80) for d in hours.get("weekdayDescriptions") or () if isinstance(d, str))[:7]
    attributes: tuple[tuple[str, bool], ...] = ()
    reviews: tuple[Review, ...] = ()
    summary = ""
    if detailed:
        attributes = tuple((f, raw[f]) for f in ATTRIBUTES if isinstance(raw.get(f), bool))
        reviews = tuple(r for r in map(read_review, raw.get("reviews") or ()) if r is not None)[:REVIEWS_MAX]
        summary = _text(_localized(raw.get("editorialSummary"))[0], SUMMARY_MAX)
    return Spot(
        id=pid, name=name, sort=sort if sort in SORTS else "", lat=lat, lon=lon,
        kind=_text(raw.get("primaryType"), 60), rating=_rating(raw.get("rating")),
        count=_int(raw.get("userRatingCount")), price=PRICE.get(str(raw.get("priceLevel") or ""), ""),
        price_range=price_range(raw.get("priceRange")), url=google_url(raw.get("googleMapsUri")),
        status=_text(raw.get("businessStatus"), 30), address=_text(raw.get("formattedAddress"), 200), hours=week,
        photos=read_photos(raw.get("photos")), detailed=detailed, summary=summary, attributes=attributes,
        reviews=reviews)


def attribute_facts(attributes: Sequence[Sequence[object]]) -> tuple[tuple[str, str], ...]:
    """Ce qu'une fiche dit du lieu (``Spot.attributes``), sous les libellés de la fiche d'OpenStreetMap, la source
    citée : (« Terrasse », « oui (selon Google) »)."""
    out = []
    for field, value in attributes:
        said = ATTRIBUTE_FR.get(str(field))
        if said is not None and isinstance(value, bool):
            out.append((said[0], f"{said[1] if value else said[2]} (selon Google)"))
    return tuple(out)
