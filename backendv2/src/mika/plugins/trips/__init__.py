"""Le plugin ``trips`` : les voyages qu'une personne prépare, et ce qu'elle cherche ou montre sur la carte pour elle
(ADR 0194, 0195, 0196).

- **Un voyage** est à la personne qui l'a créé : un titre, une date de départ, un mode, ce qu'il évite, ses arrêts
  jour par jour. Il vit au journal (``trips.*``) ; ce qu'on en garde de textes (le titre, le nom, les coordonnées, la
  sorte et la note d'un arrêt) est un contenu, la personne pour sujet — la tranche n'en voit que les références.
  L'identifiant d'un voyage est le ``seq`` de sa création, celui d'un arrêt le ``seq`` de son ajout.
- **La personne** le prépare dans l'écran Carte, par les actions de la console (``actions.py``, au nom de qui agit),
  que l'API par personne appelle (``app/moi/carte.py``) ; **elle**, en conversation, quand on le lui demande
  (``tools.py``). Ce qu'elle a fait porte ``by = BY_HER`` : l'écran le montre en rose, et on le retire d'un geste.
- **La console** le montre sur la fiche de la personne, onglet Voyages (``inspect.py``, ADR 0204) : un opérateur peut
  l'y supprimer, rien de plus.
- **Ses regards** : des lieux cherchés, un trajet calculé (``trips.looked``), une carte qu'elle montre
  (``trips.shown``) ; son message en emporte la note (``look:``, ``map:``, ``trip:``). Ses derniers regards restent
  dans la tranche, par personne : un lieu qu'elle a trouvé se reprend par son identifiant (« l123 »).
- **L'oubli** : oublier la personne efface ses voyages et ses regards de la tranche (leurs contenus, déjà, par leurs
  sujets) ; la note d'un message disparaît avec eux.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import trips as c
from mika.kernel.builtin import SUBJECT_FORGOTTEN
from mika.kernel.faculty import Faculty
from mika.kernel.guards import Guard
from mika.kernel.state import FrozenDict
from mika.ports.maps import AVOIDS, MODES
from mika.vocab.phrasebook import phrase

BUNDLE = "trips"
#: ses derniers regards gardés, par personne : ce qu'un identifiant rendu par une recherche (« l123 ») retrouve
LOOKS_KEPT = 12


@dataclass(frozen=True, slots=True)
class Stop:
    """Un arrêt : ses contenus par référence (une tranche ne voit jamais de texte) ; ``by`` : qui l'a ajouté."""

    id: str
    name_ref: str
    coords_ref: str
    kind_ref: str
    day: int
    note_ref: str
    by: str


@dataclass(frozen=True, slots=True)
class Trip:
    """Un voyage. ``stops`` : rangés par jour, puis dans l'ordre du jour ; ``stamp`` : le ``seq`` du dernier geste qui
    l'a changé ; ``mika_touched`` : elle y a fait quelque chose (« préparé avec elle »)."""

    id: str
    person: str
    title_ref: str
    mode: str
    avoid: tuple[str, ...]
    start: str
    stops: tuple[Stop, ...]
    created_at: int
    updated_at: int
    stamp: int
    mika_touched: bool
    by: str = ""


@dataclass(frozen=True, slots=True)
class Look:
    """Un de ses regards sur la carte : pour qui, dans quel épisode, ce qu'elle a vu (``found_ref``)."""

    seq: int
    person: str
    handle: str
    episode: str
    what: str
    found_ref: str
    at: int


@dataclass(frozen=True, slots=True)
class TripsState:
    trips: FrozenDict[str, Trip] = field(default_factory=FrozenDict)
    #: ses derniers regards, par personne, le plus récent d'abord (``LOOKS_KEPT`` au plus)
    looks: FrozenDict[str, tuple[Look, ...]] = field(default_factory=FrozenDict)


TRIPS = Faculty("trips", state=TripsState, init=lambda p: TripsState())
TRIPS.bundle(BUNDLE, phrase("trips.bundle"))
TRIPS.declare(*c.ALL)


# ── réduire ──


def _mode(value: str | None, default: str) -> str:
    return value if value in MODES else default


def _avoid(values: Iterable[str] | None) -> tuple[str, ...]:
    wanted = set(values or ())
    return tuple(a for a in AVOIDS if a in wanted)


def _day(n: int) -> int:
    return max(1, min(c.DAYS_MAX, int(n)))


def _ref(content: Any) -> str:
    return (content.ref or "") if content is not None else ""


def place(stops: Iterable[Stop], stop: Stop, day: int, index: int) -> tuple[Stop, ...]:
    """Les arrêts, avec ``stop`` mis au jour ``day``, à la place ``index`` de ce jour (``-1``, ou au-delà : à la
    fin) ; les autres jours gardent leur ordre."""
    others = [s for s in stops if s.id != stop.id]
    row = [s for s in others if s.day == day]
    at = len(row) if index < 0 or index > len(row) else index
    row.insert(at, replace(stop, day=day))
    return tuple(sorted([s for s in others if s.day != day] + row, key=lambda s: s.day))


def _edit(s: TripsState, e: Any, change: Callable[[Trip, Any], Trip | None]) -> TripsState:
    """Un geste sur un voyage qui existe (et qui est bien à cette personne) : son empreinte suit ; sinon rien."""
    d = e.data
    trip = s.trips.get(d.trip)
    if trip is None or trip.person != d.person:
        return s
    got = change(trip, d)
    if got is None:
        return s
    got = replace(got, updated_at=e.at, stamp=e.seq, mika_touched=got.mika_touched or d.by == c.BY_HER)
    return replace(s, trips=s.trips.set(trip.id, got))


@TRIPS.reducer(c.CREATED)
def _created(s: TripsState, e, cx) -> TripsState:
    d = e.data
    trip = Trip(id=str(e.seq), person=d.person, title_ref=_ref(d.title), mode=_mode(d.mode, c.DEFAULT_MODE),
                avoid=_avoid(d.avoid), start=d.start, stops=(), created_at=e.at, updated_at=e.at, stamp=e.seq,
                mika_touched=d.by == c.BY_HER, by=d.by)
    return replace(s, trips=s.trips.set(trip.id, trip))


@TRIPS.reducer(c.CHANGED)
def _changed(s: TripsState, e, cx) -> TripsState:
    def change(t: Trip, d: Any) -> Trip:
        return replace(t, title_ref=_ref(d.title) if d.title is not None else t.title_ref,
                       mode=_mode(d.mode, t.mode), avoid=_avoid(d.avoid) if d.avoid is not None else t.avoid,
                       start=d.start if d.start is not None else t.start)

    return _edit(s, e, change)


@TRIPS.reducer(c.STOP_ADDED)
def _stop_added(s: TripsState, e, cx) -> TripsState:
    def change(t: Trip, d: Any) -> Trip:
        stop = Stop(str(e.seq), _ref(d.name), _ref(d.coords), _ref(d.kind), _day(d.day), _ref(d.note), d.by)
        return replace(t, stops=place(t.stops, stop, stop.day, int(d.index)))

    return _edit(s, e, change)


def _stop(t: Trip, stop: str) -> Stop | None:
    return next((x for x in t.stops if x.id == stop), None)


@TRIPS.reducer(c.STOP_MOVED)
def _stop_moved(s: TripsState, e, cx) -> TripsState:
    def change(t: Trip, d: Any) -> Trip | None:
        stop = _stop(t, d.stop)
        return replace(t, stops=place(t.stops, stop, _day(d.day), int(d.index))) if stop is not None else None

    return _edit(s, e, change)


@TRIPS.reducer(c.STOP_NOTED)
def _stop_noted(s: TripsState, e, cx) -> TripsState:
    def change(t: Trip, d: Any) -> Trip | None:
        stop = _stop(t, d.stop)
        if stop is None:
            return None
        noted = replace(stop, note_ref=_ref(d.note))
        return replace(t, stops=tuple(noted if x.id == stop.id else x for x in t.stops))

    return _edit(s, e, change)


@TRIPS.reducer(c.STOP_REMOVED)
def _stop_removed(s: TripsState, e, cx) -> TripsState:
    def change(t: Trip, d: Any) -> Trip | None:
        return replace(t, stops=tuple(x for x in t.stops if x.id != d.stop)) if _stop(t, d.stop) else None

    return _edit(s, e, change)


@TRIPS.reducer(c.REMOVED)
def _removed(s: TripsState, e, cx) -> TripsState:
    trip = s.trips.get(e.data.trip)
    if trip is None or trip.person != e.data.person:
        return s
    return replace(s, trips=s.trips.delete(trip.id))


@TRIPS.reducer(c.LOOKED)
def _looked(s: TripsState, e, cx) -> TripsState:
    d = e.data
    look = Look(e.seq, d.person, d.handle, e.correlation or "", d.what, _ref(d.found), e.at)
    return replace(s, looks=s.looks.set(d.person, (look, *s.looks.get(d.person, ()))[:LOOKS_KEPT]))


@TRIPS.reducer(SUBJECT_FORGOTTEN)
def _forgotten(s: TripsState, e, cx) -> TripsState:
    """Oublier une personne efface ses voyages et ses regards : leurs contenus, déjà, par leurs sujets."""
    who = e.data.subject
    trips = s.trips.without(lambda key: s.trips[key].person == who)
    looks = FrozenDict({person: kept for person, seen in s.looks.items() if person != who
                        and (kept := tuple(x for x in seen if x.handle != who))})
    if trips is s.trips and looks == s.looks:
        return s
    return replace(s, trips=trips, looks=looks)


@TRIPS.fact(c.STAMP)
def _stamp(s: TripsState, cx, trip: str) -> int:
    found = s.trips.get(trip)
    return found.stamp if found is not None else 0


# ── lire ──

Get = Callable[[Any], Any]


def owner_key(get: Get, person: str) -> str:
    """La personne d'un voyage, telle que l'identité la relie maintenant (une adresse reliée depuis à une personne)."""
    return str(get(identity_c.PERSON(person)) or person)


def trips_of(s: TripsState | None, get: Get, person: str) -> list[Trip]:
    """Les voyages de cette personne (sa clé, telle que ``identity.person`` la donne), le plus récemment changé
    d'abord — jamais ceux d'une autre."""
    if s is None:
        return []
    mine = [t for t in s.trips.values() if owner_key(get, t.person) == person]
    return sorted(mine, key=lambda t: (-t.updated_at, -t.stamp))


def trip_of(s: TripsState | None, get: Get, person: str, trip: str) -> Trip | None:
    """Ce voyage, s'il est à cette personne (sinon : il n'existe pas pour elle)."""
    found = s.trips.get(str(trip).strip()) if s is not None else None
    return found if found is not None and owner_key(get, found.person) == person else None


def days_of(trip: Trip) -> list[tuple[int, list[Stop]]]:
    """Ses jours, du premier au dernier où il y a un arrêt (un jour vide entre deux compris) ; un voyage sans arrêt a
    un jour, vide."""
    last = max((s.day for s in trip.stops), default=1)
    return [(n, [s for s in trip.stops if s.day == n]) for n in range(1, last + 1)]


def unchanged(trip: str) -> Guard:
    """Ce qu'un geste suppose encore vrai au moment où il s'écrit : le voyage tel qu'il a été lu."""
    return Guard(f"voyage {trip}", reads=(c.STAMP(trip),))


def looks_of(s: TripsState | None, person: str, episode: str = "") -> list[Look]:
    """Ses derniers regards pour cette personne : ceux de cet épisode d'abord, puis les autres, du plus récent au
    plus ancien."""
    seen = list(s.looks.get(person, ())) if s is not None else []
    return [x for x in seen if episode and x.episode == episode] + [x for x in seen if not episode
                                                                   or x.episode != episode]


from mika.plugins.trips import actions as actions  # noqa: E402 — s'enregistrent sur TRIPS
from mika.plugins.trips import inspect as inspect  # noqa: E402 — s'enregistre sur TRIPS
from mika.plugins.trips import tools as tools  # noqa: E402

__all__ = ["BUNDLE", "TRIPS", "Look", "Stop", "Trip", "TripsState", "days_of", "looks_of", "owner_key", "place",
           "trip_of", "trips_of", "unchanged"]
