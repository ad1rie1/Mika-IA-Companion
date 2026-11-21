"""Le port de la carte (ADR 0194) : chercher un lieu dans l'index local, une adresse à la Géoplateforme, calculer un
itinéraire au serveur réglé (Valhalla). Ce que la personne voit dans l'écran Carte, et ce dont Mika se sert en lui
parlant, passe par ici.

Les lieux se cherchent dans l'index du dossier de données : rien ne sort. Une adresse ne fait partir que le texte
cherché, jamais la position de la personne ; un itinéraire, que ses points. ``MapsUnavailable`` dit en mots ce qui
manque (rien de réglé, un serveur qui ne répond pas, aucun chemin).

La fiche d'un lieu (``place``, ADR 0244) réunit ce qu'en disent ses sources, chacune dans sa partie : OpenStreetMap
(l'index tiré de l'extrait de Geofabrik), les données touristiques (DATAtourisme), les avis (Google Places), et les
événements proches. Une partie qu'aucune source ne remplit reste vide ; un lieu trouvé (``PlaceHit``) porte ce qu'on
en sait pour une liste (ouvert ou fermé, cuisine, note…), ses champs facultatifs vides quand on ne le sait pas.

Les événements (``events``, ``event``, ADR 0245) se cherchent dans une base locale des données touristiques, un
cache de DATAtourisme par cases : lues chaque soir autour des personnes, et en direct quand on ouvre une case jamais
vue (la case seule part, jamais la position) ; ``tourism_coverage`` dit ce qu'on en a. Les photos (``photo``) passent
par ce serveur : le client ne joint jamais un autre hôte.

Les avis (ADR 0250, 0256) viennent d'un cache de Google Places sur ce serveur, lu par cases autour des personnes
(chaque soir, et au préchargement : ``preload``) : une liste ne lit que lui, rien ne sort ; la fiche d'un lieu lit en
direct ce qui lui manque, ``place_refresh`` relit tout ; ``reviews_coverage`` dit ce qu'on en a.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

#: comment on va d'un point à l'autre ; ce qu'un trajet peut éviter
MODES = ("voiture", "velo", "pied")
AVOIDS = ("peages", "autoroutes", "ferries")
#: les points d'un trajet, départ et arrivée compris
ROUTE_POINTS_MAX = 20


class MapsUnavailable(Exception):
    """Ce qui manque, en une phrase qu'on peut montrer à la personne comme à elle."""


class MapsNotFound(MapsUnavailable):
    """Ce qui n'existe pas, ou plus (ADR 0259) : une photo qu'aucune source ne connaît, une photo dont les droits ont
    pris fin. L'API par personne en fait un 404 ; le reste d'une ``MapsUnavailable``, un 503."""


class MapsBadMedia(MapsUnavailable):
    """Une source qui a répondu, mais pas ce qu'on attendait d'elle (ADR 0259) : une photo qui n'est pas une image
    qu'on sert. L'API par personne en fait un 502."""


#: les identifiants qu'on reçoit du dehors (un client, ses outils), avant de rien chercher (ADR 0259) : un lieu
#: (``l<n>``, son objet d'OpenStreetMap ``n123``/``w45``/``r6``, un lieu des données touristiques ``t:<uuid>``), un
#: événement (``e:<uuid>``), une photo relayée (``p:<hash>``)
PLACE_REF = re.compile(r"^(?:l\d{1,15}|[nwr]\d{1,15}|t:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$")
EVENT_REF = re.compile(r"^e:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
PHOTO_REF = re.compile(r"^p:[0-9a-f]{32}$")


#: les filtres d'un lieu qu'on sait reconnaître (``PlaceHit.tags``, ``search(features=…)``), dans l'ordre de l'écran
FEATURES = ("terrasse", "vegetarien", "vegan", "accessible", "emporter", "livraison")
#: l'ordre d'une recherche autour d'un point : la distance, ou la note (sans note connue, la distance)
SORTS = ("distance", "rating")
#: ouvert ou fermé à l'instant de la réponse (les horaires d'OpenStreetMap) ; ``unknown`` : on ne sait pas
OPEN_STATES = ("open", "closed", "unknown")


@dataclass(frozen=True, slots=True)
class PlaceHit:
    """Un lieu trouvé. ``id`` : ``l<n>`` (l'index local, qui change à chaque reconstruction : un arrêt garde son nom et
    ses coordonnées) ou ``a:<n>`` (une adresse de cette réponse). ``distance_m`` : depuis le point donné, ou jusqu'au
    trajet pour ``along`` ; ``along_m`` : où on le croise, depuis le départ.

    Le reste est facultatif, vide quand on ne le sait pas (ADR 0244) : ``osm``, l'objet d'OpenStreetMap, stable d'une
    reconstruction à l'autre (``n123``, ``w45``, ``r6``) ; ``open_state`` (``OPEN_STATES``) et ``open_text`` (« Ouvert ·
    ferme à 22:30 »), à l'instant de la réponse ; ``cuisine`` (« Flamande, régionale ») ; ``rating`` (la note, sur 5) et
    ``reviews`` (le nombre d'avis), ``price`` (« €€ ») et ``photo`` (la référence de sa première photo, ``p:<hash>``),
    quand une source d'avis les donne ; ``tags``, les filtres qu'il vérifie (``FEATURES``). Avec sa photo, ce qu'il
    faut en citer là où elle se montre (ADR 0269) : ``photo_source`` (``google``, ``datatourisme``), ``photo_credit``
    (son auteur), ``photo_credit_url`` (son lien) et ``photo_licence`` (une photo de l'office de tourisme)."""

    id: str
    name: str
    kind: str
    kind_fr: str
    category: str
    lat: float
    lon: float
    town: str = ""
    distance_m: int | None = None
    along_m: int | None = None
    osm: str = ""
    open_state: str = ""
    open_text: str = ""
    cuisine: str = ""
    rating: float | None = None
    reviews: int | None = None
    price: str = ""
    photo: str = ""
    tags: tuple[str, ...] = ()
    photo_source: str = ""
    photo_credit: str = ""
    photo_credit_url: str = ""
    photo_licence: str = ""


#: les champs d'un lieu trouvé qu'on écrit toujours ; les autres (``extras``), seulement quand on les sait
HIT_FIELDS = ("id", "name", "kind", "kind_fr", "category", "lat", "lon", "town", "distance_m", "along_m")
HIT_EXTRAS = ("osm", "open_state", "open_text", "cuisine", "rating", "reviews", "price", "photo", "tags",
              "photo_source", "photo_credit", "photo_credit_url", "photo_licence")
#: ce qu'un lieu ou un événement porte de sa première photo : d'où elle vient, son auteur, son lien, sa licence
PHOTO_CITED = ("photo_source", "photo_credit", "photo_credit_url", "photo_licence")


def extras(hit: PlaceHit) -> dict[str, object]:
    """Les champs facultatifs d'un lieu trouvé qu'on sait (ni vides, ni ``None``) ; ``tags`` en liste."""
    out: dict[str, object] = {}
    for name in HIT_EXTRAS:
        value = getattr(hit, name)
        if value is None or value == "" or value == ():
            continue
        out[name] = list(value) if isinstance(value, tuple) else value
    return out


@dataclass(frozen=True, slots=True)
class Photo:
    """Une photo d'un lieu ou d'un événement, relayée par ce serveur (``MapsPort.photo``) : le client ne joint jamais
    un autre hôte. ``source`` : ``datatourisme`` ou ``google`` ; ``credit`` et ``licence`` se montrent avec elle ;
    ``credit_url`` : le lien de son auteur (Google le demande : son nom et son lien, avec la photo)."""

    ref: str
    source: str
    credit: str = ""
    licence: str = ""
    caption: str = ""
    width: int | None = None
    height: int | None = None
    credit_url: str = ""


@dataclass(frozen=True, slots=True)
class OsmFacts:
    """Ce qu'OpenStreetMap dit d'un lieu (l'index tiré de l'extrait de Geofabrik). ``id`` : ``n123``/``w45``/``r6`` ;
    ``url`` : sa page sur openstreetmap.org (pour le corriger) ; ``hours`` : le texte d'``opening_hours`` tel quel,
    ``hours_text`` : la semaine en français (le texte tel quel s'il n'est pas compris) ; ``facts`` : la fiche, en
    paires (libellé, valeur) dans l'ordre où on les lit (« Cuisine », « Horaires », « Téléphone », « Terrasse »…),
    seulement ce qui est renseigné ; ``extract`` : la date de l'extrait (ISO 8601)."""

    id: str
    url: str
    address: str = ""
    phone: str = ""
    website: str = ""
    email: str = ""
    hours: str = ""
    hours_text: str = ""
    facts: tuple[tuple[str, str], ...] = ()
    wikidata: str = ""
    wikipedia: str = ""
    extract: str = ""


@dataclass(frozen=True, slots=True)
class TourismFacts:
    """Ce qu'en disent les données touristiques (DATAtourisme), quand le lieu y est rapproché. ``id`` : ``t:<uuid>`` ;
    ``prices`` : les tarifs en clair ; ``contacts`` : (libellé, valeur) ; ``author`` : qui l'a écrite
    (``hasBeenCreatedBy.legalName``, à citer) ; ``updated`` : sa mise à jour (ISO 8601)."""

    id: str
    description: str = ""
    labels: tuple[str, ...] = ()
    prices: str = ""
    contacts: tuple[tuple[str, str], ...] = ()
    author: str = ""
    updated: str = ""
    url: str = ""
    photos: tuple[Photo, ...] = ()


@dataclass(frozen=True, slots=True)
class Review:
    """Un avis : sa note (sur 5), son titre, son texte, qui l'a écrit (``author``, son nom chez la source, et
    ``author_url``, le lien de son profil : à montrer avec l'avis), quand (``date``, ISO 8601 ; ``relative``, en mots :
    « il y a moins d'une semaine »), en quelle compagnie, en quelle langue. Google ne donne ni titre ni compagnie."""

    rating: float
    title: str = ""
    text: str = ""
    author: str = ""
    date: str = ""
    trip: str = ""
    language: str = ""
    author_url: str = ""
    relative: str = ""


@dataclass(frozen=True, slots=True)
class ReviewFacts:
    """Ce qu'en disent les avis (Google Places, ADR 0256), quand le lieu y est rapproché. ``source`` : d'où ils
    viennent (``google``), à nommer avec eux (« Google Maps ») ; ``id`` : le leur ; vide : la source n'en a rien (pas
    trouvé sous ce nom tout près, ou pas encore cherché : ``note`` dit pourquoi) ; ``price`` : en euros (« €€ ») et
    ``price_range`` : la fourchette qu'elle donne (« 20–40 € ») ; ``summary`` : son résumé du lieu ; ``reviews`` : les
    plus pertinents (cinq au plus), en français, chacun avec son auteur et son lien ; ``photos`` : relayées, chacune
    avec son auteur et son lien ; ``facts`` : ce qu'elle dit de la fiche et qu'OpenStreetMap ne dit pas (« Terrasse »,
    « oui (selon Google) »), jamais à la place de ce qu'il dit ; ``url`` : sa page du lieu (à montrer avec son nom :
    c'est le lien vers tous les avis) ; ``cached`` : quand ce serveur a lu ce qu'on montre (ISO 8601, la plus ancienne
    de ses parties) ; ``note`` : ce qu'il faut en dire quand c'est vieux ou incomplet (« le quota du mois de Google
    (fiches avec avis) est atteint… On montre ce qu'on avait. »), ou qu'il est fermé. Google ne donne ni répartition,
    ni sous-notes, ni classement, ni distinctions : ``distribution``, ``subratings``, ``ranking`` et ``awards`` restent
    vides."""

    id: str
    rating: float | None = None
    count: int | None = None
    ranking: str = ""
    distribution: tuple[int, ...] = ()
    subratings: tuple[tuple[str, float], ...] = ()
    price: str = ""
    awards: tuple[str, ...] = ()
    reviews: tuple[Review, ...] = ()
    photos: tuple[Photo, ...] = ()
    url: str = ""
    cached: str = ""
    note: str = ""
    source: str = "google"
    summary: str = ""
    price_range: str = ""
    facts: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ReviewsCoverage:
    """Ce que le cache des avis sait d'un endroit (ADR 0250, 0256) : des cases lues autour des personnes, chaque soir
    et au préchargement. ``cells`` : les cases qui le couvrent (0 : une zone trop grande pour les compter) ; ``loaded`` :
    celles dont toutes les sortes sont lues ; ``oldest`` : la lecture la plus ancienne (ISO 8601 ; vide : aucune) ;
    ``note`` : ce qu'il faut en dire, en mots, quand c'est incomplet ; vide : rien à dire."""

    ready: bool
    cells: int = 0
    loaded: int = 0
    oldest: str = ""
    note: str = ""


#: les thèmes d'un événement, dans l'ordre de l'écran (``EventHit.themes``, ``events(themes=…)``) : (id, libellé)
THEMES: tuple[tuple[str, str], ...] = (
    ("concerts", "Concerts"), ("spectacles", "Spectacles"), ("expositions", "Expositions"), ("marches", "Marchés"),
    ("fetes", "Fêtes"), ("sport", "Sport"), ("enfants", "Enfants"), ("visites", "Visites"),
    ("conferences", "Conférences"),
)
#: au plus tant d'événements par réponse, et une période d'au plus tant de jours
EVENTS_LIMIT_MAX = 50
EVENTS_SPAN_MAX_DAYS = 366


@dataclass(frozen=True, slots=True)
class EventHit:
    """Un événement trouvé (DATAtourisme, ADR 0245). ``id`` : ``e:<uuid>`` (celui d'une fiche ; les fiches d'un même
    événement, même nom au même endroit, n'en font qu'un) ; ``start`` et ``end`` : sa prochaine séance dans la période
    demandée, en ISO 8601 (une date, ou une date et une heure à l'heure de Paris) — sa fin est celle de la séance, le
    lendemain après minuit, jamais celle d'une période (``EventDate`` la dit) ; ``when_text`` : quand, en mots
    (« ven. 20 nov. · 19:00–20:30 », « du mar. au dim. · 13:00–19:00 », « jusqu'au 10 janv. »), la prochaine date
    d'abord ; ``place`` : où, en mots (le lieu nommé d'OpenStreetMap le plus proche, ou l'adresse, et la commune) ;
    ``themes`` : parmi ``THEMES`` ; ``free`` : gratuit (deviné du prix ; ``None`` : on ne sait pas) ; ``photo`` : la
    référence de sa première photo (``p:<hash>``), avec ce qu'il faut en citer (ADR 0269, comme ``PlaceHit``) :
    ``photo_source``, ``photo_credit``, ``photo_credit_url`` et ``photo_licence``."""

    id: str
    name: str
    start: str
    end: str = ""
    when_text: str = ""
    place: str = ""
    lat: float | None = None
    lon: float | None = None
    distance_m: int | None = None
    themes: tuple[str, ...] = ()
    free: bool | None = None
    price: str = ""
    photo: str = ""
    photo_source: str = ""
    photo_credit: str = ""
    photo_credit_url: str = ""
    photo_licence: str = ""


@dataclass(frozen=True, slots=True)
class EventDate:
    """Une date à venir d'un événement : ``start`` (sa prochaine séance) et ``end`` (la fin de son occurrence : pour une
    période, son dernier jour), en ISO 8601 (comme ``EventHit``) ; ``text`` : en clair
    (« ven. 20 nov. · 19:00–20:30 », « du 3 déc. au 10 janv. · du mar. au dim. · 13:00–19:00 ») ; ``days`` : pour une
    période, les jours de la semaine où il a lieu (« mar. », « dim. »), vide : chaque jour."""

    start: str
    end: str
    text: str
    days: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EventDetail:
    """La fiche d'un événement (DATAtourisme, ADR 0245) : ``hit``, ce qu'en dit une liste ; ``description`` : son
    texte, en paragraphes, sans Markdown ; ``dates`` : toutes ses dates à venir, la prochaine d'abord (au plus
    ``DATES_SHOWN``, ``more_dates`` en plus) ; ``prices`` : les tarifs en clair ; ``contacts`` : (libellé, valeur) ;
    ``address`` et ``town`` : où, en mots ; ``venue`` : le lieu nommé d'OpenStreetMap où il a lieu, s'il est rapproché,
    et ``venue_place`` son identifiant pour ``place()`` (``n123``) ; ``author`` : qui l'a écrite
    (``hasBeenCreatedBy.legalName``, à citer avec ``updated``, sa mise à jour : Licence Ouverte 2.0) ; ``url`` : la
    fiche chez DATAtourisme ; ``photos`` : chacune avec son crédit et sa licence ; ``merged`` : combien de fiches
    DATAtourisme il réunit (le même événement, une fiche par date)."""

    hit: EventHit
    description: str = ""
    dates: tuple[EventDate, ...] = ()
    more_dates: int = 0
    prices: str = ""
    contacts: tuple[tuple[str, str], ...] = ()
    address: str = ""
    town: str = ""
    venue: str = ""
    venue_place: str = ""
    author: str = ""
    updated: str = ""
    url: str = ""
    photos: tuple[Photo, ...] = ()
    merged: int = 1


#: les dates d'une fiche d'événement, au plus
DATES_SHOWN = 60


@dataclass(frozen=True, slots=True)
class TourismCoverage:
    """Ce que la base des données touristiques sait d'un endroit (ADR 0245) : elle est un cache par cases, lues autour
    des personnes et quand on les ouvre. ``cells`` : les cases qui le couvrent (0 : une zone trop grande pour les
    compter) ; ``loaded`` : celles déjà lues ; ``oldest`` : la lecture la plus ancienne (ISO 8601 ; vide : aucune) ;
    ``note`` : ce qu'il faut en dire, en mots, quand ce qu'on montre est incomplet (« le quota de l'heure de
    DATAtourisme est atteint : il revient à 14:05 ») ; vide : rien à dire."""

    ready: bool
    cells: int = 0
    loaded: int = 0
    oldest: str = ""
    note: str = ""


@dataclass(frozen=True, slots=True)
class PlaceDetail:
    """La fiche d'un lieu : ``hit``, ce qu'en dit une liste (son nom, sa sorte, sa position, ouvert ou fermé…) ; puis
    une partie par source, vide (``None``, ou rien) quand elle ne sait rien du lieu — ``osm`` (OpenStreetMap ; ``None``
    pour un index sans détails, tiré des tuiles), ``tourism`` (DATAtourisme), ``reviews`` (Google Places) — et
    ``events``, les événements proches à venir."""

    hit: PlaceHit
    osm: OsmFacts | None = None
    tourism: TourismFacts | None = None
    reviews: ReviewFacts | None = None
    events: tuple[EventHit, ...] = ()


@dataclass(frozen=True, slots=True)
class PlaceRefresh:
    """Ce que rend « Actualiser » (ADR 0269) : la fiche (``detail``) et ce qu'il faut en dire, en mots (``said`` :
    « Fiche relue. », « Relue il y a 4 min : elle est à jour. », « Rien à relire pour ce lieu : … »)."""

    detail: PlaceDetail
    said: str


@dataclass(frozen=True, slots=True)
class Maneuver:
    """Une consigne du trajet, en français (« Prendre l'A41 vers Annecy »), et jusqu'à la suivante."""

    text: str
    distance_m: int
    duration_s: int


@dataclass(frozen=True, slots=True)
class RouteLeg:
    """D'un point au suivant. ``shape`` : le tracé, encodé en polyline à six décimales (``decode_polyline6``)."""

    distance_m: int
    duration_s: int
    shape: str
    steps: tuple[Maneuver, ...] = ()


@dataclass(frozen=True, slots=True)
class RouteResult:
    distance_m: int
    duration_s: int
    legs: tuple[RouteLeg, ...]
    has_toll: bool = False
    has_highway: bool = False
    has_ferry: bool = False
    #: qui l'a calculé, en mots (« Valhalla, serveur public de FOSSGIS »)
    provider: str = ""


class MapsPort(Protocol):
    def categories(self) -> tuple[tuple[str, str], ...]:
        """Les catégories de lieux, dans l'ordre de l'écran : ``(id, libellé)``."""
        ...

    def places_ready(self) -> bool: ...

    def places_summary(self) -> dict[str, object]:
        """L'index des lieux pour l'écran : ``ready`` (bool), ``count`` (le nombre de lieux) et ``built`` (quand il a
        été construit, en ISO 8601 ; vide sans index)."""
        ...

    def addresses_ready(self) -> bool: ...

    def routing_ready(self) -> bool: ...

    def routing_provider(self) -> str: ...

    async def search(self, text: str, *, near: tuple[float, float] | None = None,
                     bbox: tuple[float, float, float, float] | None = None, category: str = "",
                     limit: int = 20, open_now: bool = False, features: frozenset[str] = frozenset(),
                     cuisine: str = "", min_rating: float | None = None, sort: str = "distance") -> list[PlaceHit]:
        """Dans l'index local : par le nom (et la ville), d'une catégorie, près d'un point (lat, lon) ou dans une
        zone (ouest, sud, est, nord). Sans texte : les plus proches.

        Les filtres (ADR 0244) : ``open_now`` (ouvert à cet instant, d'après ses horaires : un lieu sans horaires
        lisibles n'en est pas), ``features`` (parmi ``FEATURES`` : tous ceux-là), ``cuisine`` (une clé
        d'OpenStreetMap, « italian », ou son nom, « italienne »), ``min_rating`` (une note d'au moins tant) et
        ``sort`` (``SORTS``). Un index sans détails (tiré des tuiles) ne sait rien de ce qu'on filtre : avec un filtre,
        rien. Un filtre ou un ordre inconnu lève ``ValueError``.

        La note (ADR 0250) vient du cache des avis (Google Places), qu'on lit sans rien demander à personne : chaque lieu
        rapproché porte ``rating``, ``reviews``, ``price`` et ``photo``. ``min_rating`` écarte les lieux sans note ;
        ``sort="rating"`` met les mieux notés d'abord (puis ceux qui ont le plus d'avis), ceux sans note à la fin. Avec
        l'un des deux, sans texte, les lieux les mieux notés du cache dans la zone (ou à deux kilomètres du point)
        rejoignent les plus proches : le meilleur ne manque pas parce qu'il est un peu plus loin."""
        ...

    async def place(self, place_id: str) -> PlaceDetail | None:
        """La fiche d'un lieu de l'index, par son identifiant (``l<n>``) ou son objet OpenStreetMap (``n123``,
        ``w45``, ``r6``), ou d'un lieu des données touristiques qu'OpenStreetMap n'a pas (``t:<uuid>``) ; ``None`` s'il
        n'y est pas. Sa partie ``tourism`` quand une fiche DATAtourisme lui est rapprochée, ``events`` : les événements
        à venir tout près (ADR 0245) ; ``reviews`` : ce qu'en dit Google (ADR 0256) — ce qui manque ou est vieux se lit
        en direct, si le quota le permet (le lieu pas encore rapproché se cherche tout près de lui, puis sa fiche avec
        ses avis et ses photos) ; sinon ce qu'on avait, et ``ReviewFacts.note`` dit pourquoi. Elle ne lève jamais pour
        les avis."""
        ...

    async def place_refresh(self, place_id: str) -> PlaceRefresh | None:
        """« Actualiser » (ADR 0250, 0256, 0269) : sa fiche relue tout de suite, quel que soit son âge — chez Google (la
        fiche avec ses avis et ses photos ; un lieu pas rapproché se recherche) et chez DATAtourisme (sa fiche
        rapprochée), sur la réserve du direct ; puis la fiche (``place``), et ce qu'il faut en dire (``PlaceRefresh``).
        Une source relue il y a moins de dix minutes ne repart pas ; rien à relire pour ce lieu, ou tout à jour : la
        fiche, sans rien demander, et ``said`` le dit. ``None`` : le lieu n'est pas dans l'index. Ce qui n'a pas pu se
        relire (le quota — celui du jour de tout le serveur compris —, la clé, le réseau ; aucune source réglée) :
        ``MapsUnavailable``, en mots — ce qui a pu l'être est gardé."""
        ...

    def preload(self, lat: float, lon: float) -> int:
        """Précharger les avis autour d'une position (ADR 0250 ; celle du téléphone, « Autour de moi ») : sa case de
        la grille et les huit d'à côté, celles qui sont vieilles, mises en file et lues en fond (la réserve du direct
        gardée) — seuls des cercles tirés des cases partent, jamais la position. Rend combien de lectures sont mises en file (0 : le
        préchargement est coupé, ou aucune clé)."""
        ...

    def reviews_coverage(self, *, near: tuple[float, float] | None = None,
                         bbox: tuple[float, float, float, float] | None = None) -> ReviewsCoverage:
        """Ce que le cache des avis sait autour d'un point ou dans une zone : à montrer avec une liste notée (« notes
        Google lues il y a 3 jours »)."""
        ...

    def tourism_summary(self) -> dict[str, object]:
        """La base des données touristiques pour l'écran : ``ready`` (bool), ``places`` et ``events`` (combien),
        ``synced`` (sa dernière synchronisation, en ISO 8601 ; vide : jamais)."""
        ...

    async def events(self, *, near: tuple[float, float] | None = None,
                     bbox: tuple[float, float, float, float] | None = None, radius_m: int = 20_000,
                     start: date | None = None, end: date | None = None, themes: frozenset[str] = frozenset(),
                     text: str = "", free: bool = False, limit: int = 30) -> list[EventHit]:
        """Les événements à venir de la base locale (DATAtourisme : rien ne sort), autour d'un point (à moins de
        ``radius_m``) ou dans une zone (ouest, sud, est, nord), entre ``start`` et ``end`` (des jours, à l'heure de
        Paris ; par défaut d'aujourd'hui à dans trente jours), d'un des ``themes`` (``THEMES``), dont le nom ou le
        résumé dit ``text``, gratuits seulement (``free``) — les plus tôt d'abord, puis les plus proches. Les cases
        jamais vues que le rayon touche (ou celles de la zone), les plus proches d'abord et en nombre borné, se lisent
        d'abord en direct, si le quota le permet (ADR 0259) ; sinon on rend ce qu'on a, et ``tourism_coverage`` dit
        pourquoi (une zone lue en partie compris). Un thème inconnu, une période à l'envers ou trop longue, une zone à
        l'envers : ``ValueError``. Sans base ni clé : ``MapsUnavailable``."""
        ...

    async def event(self, event_id: str) -> EventDetail | None:
        """La fiche d'un événement (``e:<uuid>``), ses fiches doubles réunies ; ``None`` s'il n'est pas dans la base."""
        ...

    def tourism_coverage(self, *, near: tuple[float, float] | None = None,
                         bbox: tuple[float, float, float, float] | None = None, radius_m: int | None = None,
                         places: bool = False) -> TourismCoverage:
        """Ce que la base sait des événements autour d'un point (sa case ; avec ``radius_m``, les cases que ce rayon
        touche, ADR 0259) ou dans une zone : à montrer avec ``events``, au même endroit et au même rayon (ce qu'on a,
        sa date, et pourquoi c'est incomplet — une zone lue en partie se dit). ``events`` et ``place`` lisent en
        direct les cases jamais vues, si le quota le permet. ``places`` : ce qu'elle sait de ses lieux, pour une liste
        (``search``), qui ne lit que les caches."""
        ...

    async def photo(self, ref: str) -> tuple[bytes, str]:
        """Une photo relayée (``p:<hash>``) : ses octets et son type (``image/jpeg``…). Seule une photo venue des
        données (une fiche DATAtourisme, le cache des avis) se relaie, jamais une adresse donnée par un client ; une
        photo DATAtourisme dont les droits ont pris fin ne se sert plus. Inconnue, ou ses droits finis :
        ``MapsNotFound`` ; trop grosse, pas une image, ou sa source muette : ``MapsUnavailable``."""
        ...

    async def along(self, line: Sequence[tuple[float, float]], *, corridor_m: int = 10_000, category: str = "",
                    limit: int = 20) -> list[PlaceHit]:
        """Dans l'index local : les lieux à moins de ``corridor_m`` de cette ligne (lat, lon), dans l'ordre où on les
        croise."""
        ...

    async def addresses(self, text: str, *, limit: int = 5) -> list[PlaceHit]:
        """Une adresse (numéro et rue, ville) : seul ce texte part."""
        ...

    async def route(self, points: Sequence[tuple[float, float]], *, mode: str = "voiture",
                    avoid: frozenset[str] = frozenset()) -> RouteResult: ...

    async def optimize(self, points: Sequence[tuple[float, float]], *, mode: str = "voiture") -> list[int]:
        """Le meilleur ordre de ces points, départ et arrivée fixes : les indices dans l'ordre où passer."""
        ...


def decode_polyline6(text: str) -> list[tuple[float, float]]:
    """Un tracé encodé (l'algorithme des polylines, six décimales) : ses points (lat, lon). Illisible : ``ValueError``."""
    points: list[tuple[float, float]] = []
    index = lat = lon = 0
    n = len(text)
    while index < n:
        deltas = []
        for _ in range(2):
            shift = result = 0
            while True:
                if index >= n:
                    raise ValueError("un tracé tronqué")
                byte = ord(text[index]) - 63
                index += 1
                if not 0 <= byte < 64:
                    raise ValueError("un tracé illisible")
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lon += deltas[1]
        points.append((lat / 1e6, lon / 1e6))
    return points


def encode_polyline6(points: Sequence[tuple[float, float]]) -> str:
    """L'inverse de ``decode_polyline6``."""
    out: list[str] = []
    last_lat = last_lon = 0
    for lat, lon in points:
        ilat, ilon = round(lat * 1e6), round(lon * 1e6)
        for delta in (ilat - last_lat, ilon - last_lon):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                out.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            out.append(chr(value + 63))
        last_lat, last_lon = ilat, ilon
    return "".join(out)
