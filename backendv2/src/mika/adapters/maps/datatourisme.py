"""DATAtourisme (ADR 0245) : son API (``api.datatourisme.fr/v1``), jointe par ce serveur seul avec la clé de
l'opérateur, et ce qu'on lit d'une de ses fiches — un lieu touristique ou un événement — pour la base locale
(``tourism``). Rien de la personne n'y part : seulement des départements, des dates et la clé, dans un en-tête.

**La cadence** : DATAtourisme permet 1 000 demandes par heure et une dizaine par seconde ; ce client passe par le
limiteur partagé des services de la carte (``quota.Limiter``, ses compteurs dans ``cartes/quotas.db`` : le serveur et
la commande les partagent, un redémarrage ne les oublie pas), aux bornes du réglage (``tourism_limits`` : 900 par
heure et 8 par seconde par défaut, une réserve gardée au direct), relues à chaque demande, une à la fois ; un 429 le
fait reculer. **La clé** ne part que dans l'en-tête
``X-API-Key`` : jamais dans une adresse, un message d'erreur ou le journal ; une adresse de page suivante qui la
porterait en est lavée. **Les erreurs** se disent en mots (``TourismUnavailable``, une ``MapsUnavailable`` qui dit
aussi sa sorte : la clé refusée, attendre, le serveur en panne, une réponse illisible).

**Une fiche** (``read_fiche``) : son nom, ses classes (``type``, approximatives), sa position et son adresse, son texte
(du Markdown, rendu en texte propre), ses labels, ses tarifs (et s'il est gratuit, deviné), ses contacts (jamais le nom
d'une personne), son auteur et sa mise à jour (``lastUpdate`` ; pas ``lastUpdateDatatourisme``, qui bouge en masse sans
changement), ses photos (chacune son crédit, sa licence et la fin de ses droits) et, pour un événement, ses
occurrences et ses thèmes. Une fiche illisible est laissée, jamais une erreur."""

from __future__ import annotations

import asyncio
import json
import math
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from mika.adapters.maps.config import TourismConfig, tourism_key
from mika.adapters.maps.pace import client
from mika.adapters.maps.quota import Limiter, Limits, note_sent
from mika.adapters.maps.tiles import read_capped
from mika.adapters.maps.when import Occurrence, occurrence_of
from mika.ports.maps import THEMES, MapsUnavailable
from mika.ports.preprocess import visible

API_URL = "https://api.datatourisme.fr/v1"
#: les deux listes qu'on tient à jour : les lieux, les fêtes et manifestations
PLACES, EVENTS = "placeOfInterest", "entertainmentAndEvent"
ENDPOINTS = (EVENTS, PLACES)
PAGE_SIZE = 100
HOUR_S = 3600.0
#: une synchronisation attend jusqu'à une heure (et un peu) que les demandes de l'heure se libèrent
SYNC_WAIT_S = HOUR_S + 60.0
TIMEOUT_S = 60.0
#: une page de cent événements pèse quelques Mo (leurs dates) : au-delà, elle est refusée
RESPONSE_MAX_BYTES = 64 * 1024 * 1024
#: ce qu'on demande d'une fiche (``fields`` remplace la sélection par défaut) ; un événement, en plus, ses dates
_COMMON_FIELDS = ("uuid", "uri", "label", "type", "isLocatedAt.geo", "isLocatedAt.address", "hasBeenCreatedBy",
                  "lastUpdate", "hasContact", "hasReview", "hasMainRepresentation", "hasDescription", "offers")
FIELDS = {PLACES: ",".join(_COMMON_FIELDS),
          EVENTS: ",".join((*_COMMON_FIELDS, "takesPlaceAt", "hasBookingContact"))}
#: le département d'une fiche, pour les filtres
DEPARTMENT_FIELD = "isLocatedAt.address.hasAddressCity.isPartOfDepartment.insee"

# ── les erreurs ──
AUTH, BUSY, SERVER, BROKEN, REFUSED, NETWORK, CURSOR = (
    "cle", "attendre", "serveur", "illisible", "refus", "reseau", "curseur")
NO_KEY = "Aucune clé DATAtourisme n'est réglée."


class TourismUnavailable(MapsUnavailable):
    """Ce qui empêche de joindre DATAtourisme, en une phrase ; ``kind`` dit quoi (``AUTH``, ``BUSY``…), pour savoir
    quand réessayer."""

    def __init__(self, text: str, kind: str) -> None:
        super().__init__(text)
        self.kind = kind


# ── la cadence ──
#: un 429 : plus rien ne part vers DATAtourisme pendant tant de secondes
BACK_OFF_S = 900.0
#: ce qu'attend une demande en direct (une personne attend sa réponse) que le limiteur la laisse partir
LIVE_WAIT_S = 3.0
#: ce qui dit « elle n'existe plus » (``CURSOR``) : pour une page suivante, son curseur expiré (l'API rend 400, 404 ou
#: 410) ; pour une fiche, 404 et 410 seulement — un 400 y est un refus (ADR 0269)
CURSOR_GONE, FICHE_GONE = (400, 404, 410), (404, 410)


def tourism_limits(cfg: TourismConfig) -> Limits:
    """Les bornes du limiteur de DATAtourisme, d'après son réglage."""
    return Limits(per_second=cfg.per_second, per_hour=cfg.per_hour, reserve=cfg.reserve_pct / 100)


# ── le client ──
@dataclass(frozen=True, slots=True)
class Page:
    """Une page d'une liste : ses fiches brutes, l'adresse de la suivante (vide : la dernière), le total annoncé."""

    objects: list[dict[str, Any]]
    next: str = ""
    total: int = 0


class DataTourismeClient:
    """L'API de DATAtourisme, jointe une demande à la fois, avec la clé du réglage (``config``, relu à chaque demande :
    la console la change sans redémarrer ; ``tourism_key``), sous son limiteur (``limiter``, aux bornes du même
    réglage)."""

    def __init__(self, config: Callable[[], TourismConfig], limiter: Limiter, *,
                 transport: httpx.AsyncBaseTransport | None = None, base: str = API_URL) -> None:
        self.config = config
        self.limiter = limiter
        self.base = base.rstrip("/")
        self._host = urlsplit(self.base).hostname or ""
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._one = asyncio.Lock()
        #: depuis le démarrage, pour la console
        self.asked = 0
        self.failed = 0

    def key(self) -> str:
        return tourism_key(self.config())[0]

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

    async def first(self, endpoint: str, params: Mapping[str, str], *, background: bool = True,
                    wait_max: float = SYNC_WAIT_S) -> Page:
        """La première page d'une liste (``PLACES``, ``EVENTS``) ; ``background`` : un travail de fond (la réserve du
        limiteur reste au direct) ; ``wait_max`` : ce qu'elle attend, au plus, que le limiteur la laisse partir."""
        if endpoint not in ENDPOINTS:
            raise ValueError(f"une liste : {', '.join(ENDPOINTS)}")
        return _page(await self._get(f"{self.base}/{endpoint}", dict(params), wait_max=wait_max, gone=(),
                                     background=background))

    async def follow(self, url: str, *, background: bool = True, wait_max: float = SYNC_WAIT_S) -> Page:
        """La page suivante, à l'adresse que la précédente a donnée (``meta.next``, avec son curseur ``crs``), telle
        quelle — sur l'hôte de l'API seulement, en https, sans clé dans l'adresse."""
        return _page(await self._get(self.next_url(url), None, wait_max=wait_max, gone=CURSOR_GONE,
                                     background=background))

    async def fiche(self, uuid: str, *, wait_max: float = LIVE_WAIT_S) -> dict[str, Any] | None:
        """Une fiche par son identifiant (``/catalog/{uuid}``), en direct ; ``None`` si elle n'existe plus (404, 410
        seulement : un 400 est un refus, ``REFUSED``, et un 200 qui n'est pas cette fiche, ``BROKEN`` — la fiche qu'on
        a reste)."""
        if not UUID.match(uuid):
            raise ValueError("un identifiant de fiche")
        try:
            body = await self._get(f"{self.base}/catalog/{uuid}", {"lang": "fr", "fields": FIELDS[EVENTS]},
                                   wait_max=wait_max, gone=FICHE_GONE, background=False)
        except TourismUnavailable as exc:
            if exc.kind == CURSOR:  # 404, 410 : elle n'existe plus
                return None
            raise
        if isinstance(body, dict) and str(body.get("uuid", "")).lower() == uuid.lower():
            return body
        # une réponse, mais pas cette fiche (enveloppée, un champ renommé, vide) : ni « partie » ni effacée (R3-09)
        raise TourismUnavailable("DATAtourisme a rendu une fiche illisible : on garde celle qu'on avait.", BROKEN)

    def next_url(self, url: str) -> str:
        parts = urlsplit(str(url or ""))
        if parts.scheme not in ("http", "https") or parts.hostname != self._host or parts.username or parts.password:
            raise TourismUnavailable("DATAtourisme a donné une page suivante hors de son API.", BROKEN)
        query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "api_key"])
        base = urlsplit(self.base)
        return urlunsplit((base.scheme, base.netloc, parts.path, query, ""))

    async def _get(self, url: str, params: dict[str, str] | None, *, wait_max: float, gone: tuple[int, ...],
                   background: bool) -> object:
        if not tourism_key(self.config())[0]:
            raise TourismUnavailable(NO_KEY, AUTH)
        # le limiteur d'abord, hors du tour : une demande en direct n'attend pas derrière un travail de fond qui
        # patiente une heure
        await self.limiter.take(background=background, wait_max=wait_max)
        async with self._one:
            key = tourism_key(self.config())[0]
            if not key:
                raise TourismUnavailable(NO_KEY, AUTH)
            self.asked += 1
            note_sent()
            try:
                return await self._ask(url, params, key, gone)
            except TourismUnavailable:
                self.failed += 1
                raise

    async def _ask(self, url: str, params: dict[str, str] | None, key: str, gone: tuple[int, ...]) -> object:
        """Une demande ; ``gone`` : les statuts qui disent que ce qu'on demande n'existe plus (``CURSOR``) — une page
        suivante dont le curseur a expiré (400, 404, 410), une fiche partie (404, 410)."""
        headers = {"X-API-Key": key, "Accept": "application/json"}
        try:
            async with self._http().stream("GET", url, params=params, headers=headers) as r:
                status = r.status_code
                if status == 200:
                    raw = await read_capped(r, RESPONSE_MAX_BYTES)
                else:
                    said = _said(await read_capped(r, 64 * 1024), key) if status in (400, 422) else ""
        except httpx.HTTPError as exc:
            raise TourismUnavailable(f"DATAtourisme ne répond pas ({type(exc).__name__}).", NETWORK) from None
        except ValueError:
            raise TourismUnavailable("DATAtourisme a rendu une réponse démesurée.", BROKEN) from None
        if status in (401, 403):
            raise TourismUnavailable(f"DATAtourisme refuse la clé (HTTP {status}) : vérifie-la dans la console.", AUTH)
        if status == 429:
            self.limiter.back_off(BACK_OFF_S)
            raise TourismUnavailable("DATAtourisme demande d'attendre (HTTP 429) : ce qui reste reprendra plus "
                                     "tard.", BUSY)
        if status >= 500:
            raise TourismUnavailable(f"DATAtourisme est en panne (HTTP {status}).", SERVER)
        if status in gone:
            raise TourismUnavailable(f"DATAtourisme ne reconnaît plus cette page (HTTP {status}).", CURSOR)
        if status != 200:
            raise TourismUnavailable(f"DATAtourisme refuse la demande (HTTP {status}"
                                     f"{' : ' + said if said else ''}).", REFUSED)
        try:
            return json.loads(raw)
        except ValueError:
            raise TourismUnavailable("DATAtourisme a rendu une réponse illisible.", BROKEN) from None


def _said(raw: bytes, key: str) -> str:
    """Ce qu'une réponse en refus dit d'elle-même, en une ligne courte — la clé jamais recopiée."""
    try:
        body = json.loads(raw)
    except ValueError:
        return ""
    found = body.get("message") or body.get("error") or body.get("detail") if isinstance(body, dict) else None
    if not isinstance(found, str):
        return ""
    return " ".join(visible(found).replace(key, "…").split())[:200]


def _page(body: object) -> Page:
    objects = body.get("objects") if isinstance(body, dict) else None
    meta = body.get("meta") if isinstance(body, dict) else None
    if not isinstance(objects, list) or not isinstance(meta, dict):
        raise TourismUnavailable("DATAtourisme a rendu une réponse illisible.", BROKEN)
    following = meta.get("next")
    total = meta.get("total")
    return Page([o for o in objects if isinstance(o, dict)], following if isinstance(following, str) else "",
                total if isinstance(total, int) and not isinstance(total, bool) else 0)


def filters(*, department: str | None = None, zones: Sequence[str] = (), since: date | None = None,
            events_from: date | None = None, events_to: date | None = None) -> str:
    """L'expression ``filters`` : un département (``""`` : les fiches sans département), ou des zones ; ce qui a
    changé depuis ``since`` (``lastUpdate``) ; pour les événements, ceux qui ne sont pas finis à ``events_from`` et
    commencent au plus tard à ``events_to``."""
    parts = []
    if department is not None:
        parts.append(f"{DEPARTMENT_FIELD}[eq]={department}" if department else f"{DEPARTMENT_FIELD}[exists]=false")
    elif zones:
        parts.append(f"{DEPARTMENT_FIELD}[in]={','.join(zones)}")
    if since is not None:
        parts.append(f"lastUpdate[gte]={since.isoformat()}")
    if events_from is not None:
        parts.append(f"takesPlaceAt.endDate[gte]={events_from.isoformat()}")
    if events_to is not None:
        parts.append(f"takesPlaceAt.startDate[lte]={events_to.isoformat()}")
    return " AND ".join(parts)


def params(endpoint: str, expression: str, *, bounding: tuple[float, float, float, float] | None = None) -> dict[str, str]:
    """Les paramètres d'une première page ; ``bounding`` : une case (ouest, sud, est, nord), en ``geo_bounding`` (son
    coin nord-ouest, puis son coin sud-est) — jamais la position de la personne."""
    out = {"page_size": str(PAGE_SIZE), "lang": "fr", "fields": FIELDS[endpoint]}
    if expression:
        out["filters"] = expression
    if bounding is not None:
        w, s, e, n = bounding
        out["geo_bounding"] = f"{n:.6f},{w:.6f},{s:.6f},{e:.6f}"
    return out


# ── une fiche ──
PLACE, EVENT = "place", "event"
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_CLASS = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,60}$")
NAME_MAX, SUMMARY_MAX, DESCRIPTION_MAX = 200, 600, 6000
PHOTOS_MAX, CONTACTS_MAX, LABELS_MAX, OCCURRENCES_MAX = 6, 8, 12, 2000

#: les classes d'un lieu, dans l'ordre où on les préfère : sa sorte (comme celles d'OpenStreetMap), en français, et
#: sa catégorie de l'écran Carte ; une classe inconnue ne dit rien
PLACE_TYPES: tuple[tuple[str, str, str, str], ...] = (
    ("Restaurant", "restaurant", "Restaurant", "manger"),
    ("Brasserie", "restaurant", "Brasserie", "manger"),
    ("FastFoodRestaurant", "fast_food", "Restauration rapide", "manger"),
    ("BarOrPub", "bar", "Bar", "manger"),
    ("CafeOrTeahouse", "cafe", "Café", "manger"),
    ("HotelRestaurant", "restaurant", "Hôtel-restaurant", "manger"),
    ("FoodEstablishment", "restaurant", "Restauration", "manger"),
    ("Hotel", "hotel", "Hôtel", "dormir"),
    ("Camping", "camp_site", "Camping", "dormir"),
    ("CampingAndCaravanning", "camp_site", "Camping", "dormir"),
    ("Guesthouse", "guest_house", "Chambre d'hôtes", "dormir"),
    ("SelfCateringAccommodation", "apartment", "Meublé de tourisme", "dormir"),
    ("YouthHostelAndInternationalCenter", "hostel", "Auberge de jeunesse", "dormir"),
    ("HolidayResort", "hotel", "Village vacances", "dormir"),
    ("Accommodation", "hotel", "Hébergement", "dormir"),
    ("Museum", "museum", "Musée", "voir"),
    ("Castle", "castle", "Château", "voir"),
    ("ReligiousSite", "place_of_worship", "Édifice religieux", "voir"),
    ("Church", "place_of_worship", "Église", "voir"),
    ("ArcheologicalSite", "archaeological_site", "Site archéologique", "voir"),
    ("RemarkableBuilding", "attraction", "Bâtiment remarquable", "voir"),
    ("ZooAnimalPark", "zoo", "Parc animalier", "voir"),
    ("Aquarium", "aquarium", "Aquarium", "voir"),
    ("AmusementPark", "theme_park", "Parc d'attractions", "voir"),
    ("InterpretationCentre", "museum", "Centre d'interprétation", "voir"),
    ("CulturalSite", "attraction", "Site culturel", "voir"),
    ("ParkAndGarden", "park", "Parc ou jardin", "nature"),
    ("NaturalHeritage", "attraction", "Site naturel", "nature"),
    ("Theater", "theatre", "Théâtre", "sortir"),
    ("MovieTheater", "cinema", "Cinéma", "sortir"),
    ("Cinema", "cinema", "Cinéma", "sortir"),
    ("SportsAndLeisurePlace", "sports_centre", "Sports et loisirs", "sortir"),
    ("Store", "shop", "Commerce", "courses"),
    ("TouristInformationCenter", "information", "Office de tourisme", "services"),
    # la dernière : une location, une gare… qu'aucune autre classe ne dit mieux (« France Cars », R3-06)
    ("Transport", "transport", "Transport", "services"),
)
_PLACE_TYPE = {t[0]: t for t in PLACE_TYPES}
TOURISM_KIND, TOURISM_KIND_FR = "tourism", "Lieu touristique"

#: les classes d'un événement et le thème de l'écran qu'elles disent (``ports.maps.THEMES``)
EVENT_TYPES = {
    "Concert": "concerts", "MusicEvent": "concerts", "Recital": "concerts",
    "ShowEvent": "spectacles", "TheaterEvent": "spectacles", "DanceEvent": "spectacles",
    "CircusEvent": "spectacles", "ScreeningEvent": "spectacles", "Opera": "spectacles",
    "ExhibitionEvent": "expositions", "Exhibition": "expositions", "FairOrShow": "expositions",
    "Market": "marches", "GarageSale": "marches", "FleaMarket": "marches", "ChristmasMarket": "marches",
    "Festival": "fetes", "Carnival": "fetes", "Parade": "fetes", "TraditionalCelebration": "fetes",
    "LocalAnimation": "fetes", "PopularEvent": "fetes",
    "SportsEvent": "sport", "SportsCompetition": "sport", "SportsDemonstration": "sport",
    "Visit": "visites", "GuidedTour": "visites", "OpenDay": "visites",
    "Conference": "conferences", "Seminar": "conferences", "Reading": "conferences", "Congress": "conferences",
}
#: ce que disent les mots du nom (et du résumé, pour les enfants) : plus sûr que les classes, souvent trop nombreuses
THEME_WORDS: tuple[tuple[str, re.Pattern[str]], ...] = tuple((theme, re.compile(pattern, re.I)) for theme, pattern in (
    ("concerts", r"\b(concerts?|récital|fanfare|jazz|orchestre|chorale|quatuor|symphoni\w*|philharmoni\w*)\b"),
    ("spectacles", r"\b(spectacles?|théâtre|danse|cirque|opéra|humour|stand-up|marionnettes?|ballet|cinéma|"
                   r"projection|one[- ]man[- ]show)\b"),
    ("expositions", r"\b(expos?|expositions?|vernissage)\b"),
    ("marches", r"\b(marchés?|brocantes?|vide-greniers?|braderie|puces)\b"),
    ("fetes", r"\b(fêtes?|festivals?|carnaval|défilé|kermesse|feux? d'artifice|ducasse|guinguette)\b"),
    ("sport", r"\b(trail|marathon|randonnées?|marche nordique|tournoi|match|compétition|triathlon|course à pied|"
              r"course nature)\b"),
    ("visites", r"\b(visites?|balades?|portes ouvertes|promenades?)\b"),
    ("conferences", r"\b(conférences?|débat|table ronde|causerie|lecture)\b"),
))
CHILDREN = re.compile(r"\b(jeune public|en famille|pour les enfants|enfants|tout[- ]petits|dès \d+ ans|"
                      r"à partir de \d+ ans)\b", re.I)
THEME_BITS = {theme: 1 << k for k, (theme, _label) in enumerate(THEMES)}
#: au-delà de tant de thèmes tirés des classes seules, on ne garde que ceux que le texte confirme
TYPE_THEMES_MAX = 2

_FREE = re.compile(r"\b(gratuit\w*|entrée libre|accès libre|libre accès)\b", re.I)
_SOME_PAY = re.compile(r"\b(moins de|enfants?|réduit|étudiants?|-\s?\d+\s?ans)\b", re.I)
_AMOUNT = re.compile(r"\d+(?:[.,]\d+)?\s*(?:€|eur\b|euros?\b)", re.I)

_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", re.S)
_EM = re.compile(r"(?<![\w*])([*_])(?=\S)(.+?)(?<=\S)\1(?![\w*])", re.S)
_LINK = re.compile(r"\[([^\]\n]{1,300})\]\((?:https?://|mailto:)[^)\s]{1,500}\)")
_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.M)
_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!])")
_SHELTERED = re.compile("\ue000(\\d+)\ue001")
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")


def text_of(value: object, most: int = NAME_MAX) -> str:
    """Un texte d'une ligne : un ``{"@fr": …}`` (ou une liste de textes), blancs repliés, invisibles retirés."""
    if isinstance(value, dict):
        value = value.get("@fr") or next((v for v in value.values() if isinstance(v, str | list)), "")
    if isinstance(value, list):
        value = " ".join(v for v in value if isinstance(v, str))
    if not isinstance(value, str):
        return ""
    flat = " ".join(visible(value).split())
    return flat if len(flat) <= most else flat[: most - 1].rstrip() + "…"


def plain(value: object, most: int = DESCRIPTION_MAX) -> str:
    """Un texte en paragraphes, son Markdown retiré (``**gras**``, ``_italique_``, les liens, les titres) : les
    lignes gardées, les blancs repliés, au plus une ligne vide de suite."""
    if isinstance(value, dict):
        value = value.get("@fr") or ""
    if not isinstance(value, str):
        return ""
    text = visible(value.replace("\r\n", "\n").replace("\r", "\n"))
    text = _ESCAPE.sub(lambda m: f"\ue000{ord(m.group(1))}\ue001", text)  # « \_ » reste un « _ » : mis à l'abri
    text = _LINK.sub(r"\1", text)
    text = _HEADING.sub("", text)
    for _ in range(2):  # le gras dans l'italique, et l'inverse
        text = _EM.sub(r"\2", _BOLD.sub(r"\2", text))
    text = _SHELTERED.sub(lambda m: chr(int(m.group(1))), text)
    lines: list[str] = []
    for line in text.split("\n"):
        line = " ".join(line.split())
        if line or (lines and lines[-1]):
            lines.append(line)
    out = "\n".join(lines).strip()
    return out if len(out) <= most else out[: most - 1].rstrip() + "…"


def name_key(name: str) -> str:
    """Un nom pour comparer : sans accents ni casse ni ponctuation, sans ses articles ni les mots qui disent la sorte
    (« restaurant », « hôtel », « camping »…)."""
    words = plain_words(name)
    kept = [w for w in words if w not in GENERIC_WORDS]
    return " ".join(kept or words)


def plain_words(text: str) -> list[str]:
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()
    return re.findall(r"[a-z0-9]+", ascii_)


#: ce qui précède le nom d'une ville dans une rue qui le porte (« rue de Lille ») : alors, ce n'est pas la commune
_NAMED_AFTER = frozenset({"de", "d", "du", "des"})
_TOWN_WORDS_MAX = 6
_PUNCT = " ,;-–—"


def street_without_town(street: str, town: str) -> str:
    """La rue d'une adresse sans la commune que DATAtourisme y recopie souvent, et le code postal ou le « à » qui la
    précèdent (« Roubaix » seule, « 1 allée du Musée VIlleneuve-d'Ascq », « Rue Kléber Loquet 59 560 Comines », « 13 rue
    de l'Hospice à Roubaix ») ; une rue qui porte le nom d'une ville (« 12 rue de Lille », à Lille) le garde."""
    want = plain_words(town)
    words = street.split()
    while want and words:
        size = next((k for k in range(1, min(len(words), _TOWN_WORDS_MAX) + 1)
                     if plain_words(" ".join(words[-k:])) == want), 0)
        before = plain_words(words[-size - 1]) if size and len(words) > size else []
        if not size or (before and before[-1] in _NAMED_AFTER):
            break
        words = words[:-size]
        while words and (words[-1].strip(_PUNCT).isdigit() or words[-1].strip(_PUNCT).lower() in ("", "à")):
            words.pop()
    return " ".join(words).strip(_PUNCT)


#: les mots d'un nom qui ne le distinguent pas
GENERIC_WORDS = frozenset({
    "le", "la", "les", "l", "un", "une", "de", "du", "des", "d", "au", "aux", "a", "et", "en", "chez", "sur", "the",
    "restaurant", "resto", "hotel", "hotels", "cafe", "bar", "brasserie", "bistrot", "bistro", "camping", "musee",
    "gite", "gites", "chambre", "chambres", "hotes", "auberge", "residence", "sarl", "sas", "eurl", "spa",
})


@dataclass(frozen=True, slots=True)
class PhotoFacts:
    """Une photo d'une fiche : son adresse chez DATAtourisme (ou son producteur), son crédit, sa licence, sa légende,
    la fin de ses droits (ISO 8601, vide : sans fin)."""

    url: str
    credit: str = ""
    licence: str = ""
    caption: str = ""
    rights_end: str = ""


@dataclass(frozen=True, slots=True)
class Fiche:
    """Une fiche lue : ce que la base en garde."""

    uuid: str
    kind: str
    name: str
    types: tuple[str, ...] = ()
    lat: float | None = None
    lon: float | None = None
    street: str = ""
    postcode: str = ""
    town: str = ""
    insee: str = ""
    department: str = ""
    summary: str = ""
    description: str = ""
    #: (label, sa fin ISO 8601 ou vide)
    labels: tuple[tuple[str, str], ...] = ()
    prices: str = ""
    free: bool | None = None
    contacts: tuple[tuple[str, str], ...] = ()
    author: str = ""
    updated: str = ""
    uri: str = ""
    category: str = ""
    sort: str = ""
    sort_fr: str = ""
    themes: tuple[str, ...] = ()
    occurrences: tuple[Occurrence, ...] = ()
    photos: tuple[PhotoFacts, ...] = field(default_factory=tuple)


def _first(value: object) -> dict[str, Any]:
    if isinstance(value, list):
        value = next((v for v in value if isinstance(v, dict)), None)
    return value if isinstance(value, dict) else {}


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _coordinate(value: object, bound: float) -> float | None:
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return round(float(value), 6) if -bound <= value <= bound else None


def _department(city: dict[str, Any], insee: str) -> str:
    found = _first(city.get("isPartOfDepartment")).get("insee")
    if isinstance(found, str) and re.fullmatch(r"\d{2,3}|2[AB]", found):
        return found
    if re.fullmatch(r"\d{5}|2[AB]\d{3}", insee):
        return insee[:3] if insee.startswith(("97", "98")) else insee[:2]
    return ""


def _http(value: str) -> str:
    value = value.strip()
    parts = urlsplit(value)
    return value[:500] if parts.scheme in ("http", "https") and parts.hostname and " " not in value else ""


def _contacts(raw: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """Téléphones, courriels, sites (et ceux des réservations) : jamais le nom, ni le titre d'une personne."""
    out: list[tuple[str, str]] = []
    for key, booking in (("hasContact", False), ("hasBookingContact", True)):
        for contact in raw.get(key) or ():
            if not isinstance(contact, dict):
                continue
            for phone in _strings(contact.get("telephone")):
                if 6 <= len(re.sub(r"\D", "", phone)) <= 15:
                    out.append(("Réservation" if booking else "Téléphone", " ".join(phone.split())[:40]))
            for mail in _strings(contact.get("email")):
                if _EMAIL.match(mail.strip()):
                    out.append(("Courriel de réservation" if booking else "Courriel", mail.strip()))
            for site in _strings(contact.get("homepage")):
                if _http(site):
                    out.append(("Réservation en ligne" if booking else "Site", _http(site)))
    return tuple(dict.fromkeys(out))[:CONTACTS_MAX]


def _number(value: object) -> float | None:
    if isinstance(value, list):
        value = next(iter(value), None)
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value < 0:
        return None
    return float(value)


def _euros(value: float) -> str:
    return (f"{value:.2f}".rstrip("0").rstrip(".") if value % 1 else f"{value:.0f}").replace(".", ",") + " €"


def _prices(raw: Mapping[str, Any]) -> tuple[str, bool | None]:
    """Les tarifs en clair (leurs textes, sinon « de 6 à 12 € »), et s'il est gratuit — deviné : « gratuit »,
    « entrée libre » sans montant ; un montant : payant ; rien : on ne sait pas."""
    texts: list[str] = []
    lows: list[float] = []
    highs: list[float] = []
    for offer in raw.get("offers") or ():
        if not isinstance(offer, dict):
            continue
        for spec in offer.get("priceSpecification") or ():
            if not isinstance(spec, dict):
                continue
            said = text_of(spec.get("additionalInformation"), 300)
            if said:
                texts.append(said)
            low, high = _number(spec.get("minPrice")), _number(spec.get("maxPrice"))
            if low is not None:
                lows.append(low)
            if high is not None:
                highs.append(high)
    texts = list(dict.fromkeys(texts))
    if texts:
        prices = " · ".join(texts)[:400]
    elif lows or highs:
        low, high = min(lows or highs), max(highs or lows)
        prices = "gratuit" if high == 0 else _euros(low) if low == high else f"de {_euros(low)} à {_euros(high)}"
    else:
        prices = ""
    joined = " ".join(texts)
    paying = bool(_AMOUNT.search(joined)) or any(v > 0 for v in (*lows, *highs))
    if paying:
        free: bool | None = False
    elif _FREE.search(joined) or (highs and max(highs) == 0):
        free = None if _SOME_PAY.search(joined) and not re.search(r"\bpour tous\b", joined, re.I) else True
    else:
        free = None
    return prices, free


def _labels(raw: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    out = []
    for review in raw.get("hasReview") or ():
        if not isinstance(review, dict):
            continue
        label = text_of(_first(review.get("hasReviewValue")).get("label"), 80)
        ends = review.get("reviewExpirationDate")
        if label:
            out.append((label, ends[:10] if isinstance(ends, str) and re.match(r"\d{4}-\d{2}-\d{2}", ends) else ""))
    return tuple(dict.fromkeys(out))[:LABELS_MAX]


def _photos(raw: Mapping[str, Any]) -> tuple[PhotoFacts, ...]:
    out = []
    for rep in raw.get("hasMainRepresentation") or ():
        if not isinstance(rep, dict):
            continue
        url = ""
        for resource in rep.get("hasRelatedResource") or ():
            if isinstance(resource, dict):
                url = next((_http(u) for u in _strings(resource.get("locator")) if _http(u)), "")
                if url:
                    break
        if not url:
            continue
        note = _first(rep.get("hasAnnotation"))
        credit = text_of(note.get("credits"), 160).lstrip("©").strip()
        ends = note.get("rightsEndDate")
        out.append(PhotoFacts(url, credit, text_of(note.get("isCoveredBy"), 80), text_of(note.get("title"), 160),
                              ends[:10] if isinstance(ends, str) and re.match(r"\d{4}-\d{2}-\d{2}", ends) else ""))
    return tuple(dict.fromkeys(out))[:PHOTOS_MAX]


def place_sort(types: Sequence[str]) -> tuple[str, str, str]:
    """(catégorie, sorte, sorte en français) d'un lieu, d'après la première de ses classes qu'on connaît."""
    known = set(types)
    for name, sort, sort_fr, category in PLACE_TYPES:
        if name in known:
            return category, sort, sort_fr
    return "", TOURISM_KIND, TOURISM_KIND_FR


def themes_of(types: Sequence[str], name: str, summary: str) -> tuple[str, ...]:
    """Les thèmes d'un événement : ceux que son nom dit, sinon ceux de ses classes (trop nombreux : ceux que son
    résumé confirme) ; « enfants » quand son nom ou son résumé le dit."""
    said = {theme for theme, words in THEME_WORDS if words.search(name)}
    if not said:
        typed = {EVENT_TYPES[t] for t in types if t in EVENT_TYPES}
        if len(typed) > TYPE_THEMES_MAX:
            confirmed = {theme for theme, words in THEME_WORDS if theme in typed and words.search(summary)}
            typed = confirmed or typed
        said = typed
    if CHILDREN.search(name) or CHILDREN.search(summary):
        said.add("enfants")
    return tuple(theme for theme, _label in THEMES if theme in said)


def read_fiche(raw: object) -> Fiche | None:
    """Une fiche brute de l'API ; sans identifiant ou sans nom : ``None``. Ne lève jamais."""
    try:
        return _read(raw)
    except (TypeError, ValueError, AttributeError, KeyError):
        return None


def _read(raw: object) -> Fiche | None:
    if not isinstance(raw, dict):
        return None
    uuid = raw.get("uuid")
    name = text_of(raw.get("label"))
    if not isinstance(uuid, str) or not UUID.match(uuid) or not name:
        return None
    types = tuple(t for t in _strings(raw.get("type")) if _CLASS.match(t))[:40]
    located = _first(raw.get("isLocatedAt"))
    geo = located.get("geo") if isinstance(located.get("geo"), dict) else {}
    lat, lon = _coordinate(geo.get("latitude"), 90), _coordinate(geo.get("longitude"), 180)
    if lat is None or lon is None:
        lat = lon = None
    address = _first(located.get("address"))
    city = address.get("hasAddressCity") if isinstance(address.get("hasAddressCity"), dict) else {}
    insee = city.get("insee") if isinstance(city.get("insee"), str) else ""
    town = text_of(address.get("addressLocality"), 120) or text_of(city.get("label"), 120)
    described = _first(raw.get("hasDescription"))
    summary = plain(described.get("shortDescription"), SUMMARY_MAX)
    description = plain(described.get("description")) or plain(described.get("shortDescription"))
    occurrences = tuple(o for o in map(occurrence_of, (raw.get("takesPlaceAt") or ())[:OCCURRENCES_MAX])
                        if o is not None)
    kind = EVENT if "EntertainmentAndEvent" in types or raw.get("takesPlaceAt") else PLACE
    prices, free = _prices(raw)
    updated = raw.get("lastUpdate")
    uri = raw.get("uri")
    category, sort, sort_fr = ("", "event", "Événement") if kind == EVENT else place_sort(types)
    return Fiche(
        uuid=uuid, kind=kind, name=name, types=types, lat=lat, lon=lon,
        street=street_without_town(text_of(_strings(address.get("streetAddress")) and
                                           ", ".join(_strings(address.get("streetAddress"))), 200), town),
        postcode=text_of(address.get("postalCode"), 10), town=town, insee=insee[:6],
        department=_department(city, insee), summary=summary, description=description, labels=_labels(raw),
        prices=prices, free=free, contacts=_contacts(raw),
        author=text_of(_first(raw.get("hasBeenCreatedBy")).get("legalName"), 160),
        updated=updated[:10] if isinstance(updated, str) and re.match(r"\d{4}-\d{2}-\d{2}", updated) else "",
        uri=_http(uri) if isinstance(uri, str) else "", category=category, sort=sort, sort_fr=sort_fr,
        themes=themes_of(types, name, summary) if kind == EVENT else (), occurrences=occurrences,
        photos=_photos(raw))
