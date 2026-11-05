"""Contrat du plugin ``trips`` : les voyages qu'une personne prépare — seule, dans l'écran Carte, ou avec elle en
conversation (ADR 0195) — et ce qu'elle cherche ou montre sur la carte pour elle (ADR 0196).

Un voyage est à la personne qui l'a créé (``person`` : la clé de sa personne, celle de son compte) : un titre, une
date de départ, comment on s'y déplace, ce qu'il évite, et ses arrêts, jour par jour. Il s'écrit au journal comme le
reste de sa vie : elle s'en souvient, elle peut en reparler ; oublier la personne l'efface (ses textes sont des
contenus, la personne pour sujet). Son identifiant est le ``seq`` de sa création, celui d'un arrêt le ``seq`` de son
ajout : rien de tiré au hasard. ``by`` dit qui a fait chaque geste : l'adresse d'une personne (``user_N``), ou elle
(``BY_HER``) — ce qu'elle a ajouté se voit en rose, et se retire d'un geste.

Ses regards (``looked`` : des lieux cherchés, un trajet calculé) et les cartes qu'elle montre (``shown``) sont des
notes de ses messages (``look:<seq>``, ``map:<seq>``), comme ``trip:<id>`` quand elle crée ou change un voyage : une
petite carte dans le fil, qui disparaît quand la personne est oubliée ou le voyage supprimé.
"""

from __future__ import annotations

from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily
from mika.ports.maps import MODES

OWNER = "trips"
#: qui a fait un geste quand c'est elle (``by``) ; une personne y met son adresse (``user_N``)
BY_HER = "mika"
#: comment on se déplace par défaut (``mika.ports.maps.MODES`` ; ce qu'on évite : ``AVOIDS``)
DEFAULT_MODE = MODES[0]

# ── les bornes ──
#: au plus tant de voyages par personne, d'arrêts par voyage, de jours par voyage
TRIPS_MAX = 50
STOPS_MAX = 60
DAYS_MAX = 30
#: les années d'une date de départ (ses jours se comptent depuis elle : au-delà, ils déborderaient du calendrier)
YEARS = range(1900, 2201)
#: un titre, une note d'arrêt, le nom d'un arrêt, sa sorte (en caractères)
TITLE_MAX = 120
NOTE_MAX = 500
NAME_MAX = 200
KIND_MAX = 60
#: ce qu'un regard ou une carte garde de lieux (``Looked.found``, ``Shown.places``)
FOUND_MAX = 20

#: ce qu'elle a regardé (``Looked.what``) : des lieux (un nom, une catégorie, autour d'un point, le long d'un trajet)
#: ou un trajet
LOOK_PLACES = "lieux"
LOOK_ROUTE = "trajet"

# ── les notes de ses messages (``MessageNote.kind``, ``ToolResult.attach``) ──
NOTE_TRIP = "trip"
NOTE_MAP = "map"
NOTE_LOOK = "look"
NOTE_KINDS = (NOTE_TRIP, NOTE_MAP, NOTE_LOOK)


class Created(Payload):
    """Un voyage naît. ``start`` : la date du premier jour (``AAAA-MM-JJ``), ou vide ; ``mode`` : ``MODES`` ;
    ``avoid`` : parmi ``AVOIDS``."""

    person: str
    title: Content
    by: str
    mode: str = DEFAULT_MODE
    avoid: tuple[str, ...] = ()
    start: str = ""


class Changed(Payload):
    """Ce qui change d'un voyage (``None`` : inchangé ; ``start`` vide : plus de date)."""

    trip: str
    person: str
    by: str
    title: Content | None = None
    mode: str | None = None
    avoid: tuple[str, ...] | None = None
    start: str | None = None


class StopAdded(Payload):
    """Un arrêt, au jour ``day`` (à partir de 1), à la place ``index`` dans ce jour (``-1`` : à la fin).
    ``coords`` : « latitude,longitude » (six décimales) ; ``kind`` : sa sorte, en mots (« Camping »)."""

    trip: str
    person: str
    by: str
    name: Content
    coords: Content
    kind: Content | None = None
    day: int = 1
    index: int = -1
    note: Content | None = None


class StopMoved(Payload):
    """Un arrêt va au jour ``day``, à la place ``index`` (``-1`` : à la fin du jour)."""

    trip: str
    stop: str
    person: str
    by: str
    day: int
    index: int = -1


class StopNoted(Payload):
    """La note d'un arrêt (``None`` : plus de note)."""

    trip: str
    stop: str
    person: str
    by: str
    note: Content | None = None


class StopRemoved(Payload):
    trip: str
    stop: str
    person: str
    by: str


class Removed(Payload):
    """Le voyage est supprimé (ses textes restent au journal jusqu'à l'oubli de la personne)."""

    trip: str
    person: str
    by: str


class Looked(Payload):
    """Elle a regardé la carte pour la personne qui lui parle (par ``handle``) : ``query``, ce qu'elle a cherché, en
    mots ; ``found``, ce qu'elle a vu, en JSON — pour des lieux (``LOOK_PLACES``), une liste d'au plus ``FOUND_MAX``
    lieux (``id``, ``name``, ``kind``, ``kind_fr``, ``category``, ``lat``, ``lon``, ``town``, ``distance_m``,
    ``along_m``) ; pour un trajet (``LOOK_ROUTE``), ``{distance_m, duration_s, mode, points, shape}`` (ses points
    nommés, son tracé résumé en polyline à six décimales)."""

    person: str
    handle: str
    what: str
    query: Content
    found: Content


class Shown(Payload):
    """Une carte qu'elle propose dans la conversation : ``title`` ; ``places``, en JSON, au plus ``FOUND_MAX`` lieux
    (comme ``Looked.found``) ; ``trip`` : le voyage qu'elle montre, s'il y en a un ; ``route`` : un parcours, d'un
    lieu au suivant, calculé ``mode`` ; ``line`` : ce parcours résumé (JSON : ``distance_m``, ``duration_s``,
    ``shape``), quand les itinéraires l'ont calculé."""

    person: str
    handle: str
    title: Content
    places: Content
    trip: str = ""
    route: bool = False
    mode: str = DEFAULT_MODE
    line: Content | None = None


CREATED = event_type("trips.created", OWNER, Created, content=("title",), subjects=("person",))
CHANGED = event_type("trips.changed", OWNER, Changed, content=("title",), subjects=("person",))
STOP_ADDED = event_type("trips.stop_added", OWNER, StopAdded, content=("name", "coords", "kind", "note"),
                        subjects=("person",))
STOP_MOVED = event_type("trips.stop_moved", OWNER, StopMoved, subjects=("person",))
STOP_NOTED = event_type("trips.stop_noted", OWNER, StopNoted, content=("note",), subjects=("person",))
STOP_REMOVED = event_type("trips.stop_removed", OWNER, StopRemoved, subjects=("person",))
REMOVED = event_type("trips.removed", OWNER, Removed, subjects=("person",))
LOOKED = event_type("trips.looked", OWNER, Looked, content=("query", "found"), subjects=("person", "handle"))
SHOWN = event_type("trips.shown", OWNER, Shown, content=("title", "places", "line"), subjects=("person", "handle"))
ALL = (CREATED, CHANGED, STOP_ADDED, STOP_MOVED, STOP_NOTED, STOP_REMOVED, REMOVED, LOOKED, SHOWN)
#: ce qui change un voyage (son empreinte, ``STAMP``, suit chacun)
EDITS = (CHANGED, STOP_ADDED, STOP_MOVED, STOP_NOTED, STOP_REMOVED)

#: ``STAMP(voyage)`` : le ``seq`` du dernier geste qui l'a changé (0 : il n'existe pas) — ce qu'une garde relit pour
#: qu'un geste fait sur un voyage lu ne s'applique pas à un voyage changé entre-temps
STAMP = FactFamily("trips.stamp", arg=str, type=int)


def note_ref(kind: str, ident: int | str) -> str:
    """La référence qu'emporte un de ses messages : ``trip:<voyage>``, ``map:<seq>``, ``look:<seq>``."""
    return f"{kind}:{ident}"


def note_of(ref: str) -> tuple[str, str] | None:
    """(sorte, identifiant) d'une référence emportée par un de ses messages (``None`` : pas une des nôtres)."""
    if not isinstance(ref, str):
        return None
    kind, sep, tail = ref.partition(":")
    if not sep or kind not in NOTE_KINDS or not tail.isdigit() or len(tail) > 18:
        return None
    return kind, tail
