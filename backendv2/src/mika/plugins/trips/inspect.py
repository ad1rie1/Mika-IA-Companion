"""La console des voyages (ADR 0195, 0204) : l'onglet « Voyages » de la fiche d'une personne, seulement si elle en a.

Chaque voyage, du plus récemment changé : son titre, son départ, comment on s'y déplace, ce qu'il évite, s'il a été
préparé avec elle ; ses arrêts jour par jour (ce qu'elle y a ajouté se dit, sous son nom) ; et « Supprimer »
(``trips.supprimer`` : confirmé, audité), le seul geste de la console sur un voyage — il se prépare à deux, dans
l'écran Carte et en conversation. Un texte oublié se dit « (oublié) ».

``read`` est ce que lit aussi l'onglet dessiné (``app/handmade/person/voyages.py``, qui sert le GPX) ; cette vue reste
la source de la console en MCP et du repli.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from mika.contracts import self_ as self_c
from mika.contracts import trips as c
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Block,
    Column,
    InspectContext,
    Note,
    Pager,
    Ref,
    Row,
    Table,
    Text,
    When,
    day_fr,
)
from mika.plugins.trips import TRIPS, TripsState, days_of, trips_of

FORGOTTEN = "(oublié)"
#: comment on s'y déplace, ce qu'il évite (``mika.ports.maps.MODES``, ``AVOIDS``), en mots
MODE_FR = {"voiture": "en voiture", "velo": "à vélo", "pied": "à pied"}
AVOID_FR = {"peages": "péages", "autoroutes": "autoroutes", "ferries": "ferries"}
#: le seul geste de la console sur un voyage (ADR 0204)
REMOVE = "trips.supprimer"
#: les pages de ses voyages et de leurs arrêts : tout tient sur une (au plus ``TRIPS_MAX`` voyages, ``STOPS_MAX``
#: arrêts) — chaque voyage garde son formulaire « Supprimer »
TRIPS_PAGE, STOPS_PAGE = "page_voyages", "page_arrets"


@dataclass(frozen=True, slots=True)
class StopSeen:
    """Un arrêt tel que la console le montre ; ``hers`` : elle l'a ajouté."""

    id: str
    name: str
    kind: str
    coords: str
    note: str
    hers: bool


@dataclass(frozen=True, slots=True)
class DaySeen:
    """Un jour du voyage : son numéro, sa date (si le voyage en a une), ses arrêts dans l'ordre."""

    n: int
    date: date | None
    stops: tuple[StopSeen, ...]


@dataclass(frozen=True, slots=True)
class TripSeen:
    """Un voyage tel que la console le montre : ses textes lus au magasin ; ``with_her`` : préparé avec elle."""

    id: str
    title: str
    start: date | None
    mode: str
    avoid: tuple[str, ...]
    days: tuple[DaySeen, ...]
    stops: int
    with_her: bool
    created: int
    updated: int


def _start(text: str) -> date | None:
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def read(s: TripsState | None, get: Callable[[Any], Any], content: Callable[[list[str]], Mapping[str, str]],
         person: str) -> list[TripSeen]:
    """Les voyages de cette personne (``trips_of`` : jamais ceux d'une autre), le plus récemment changé d'abord ; leurs
    textes lus d'un coup au magasin (``content``), « (oublié) » quand ils n'y sont plus."""
    trips = trips_of(s, get, person)
    refs = [r for t in trips for r in (t.title_ref, *(x for st in t.stops
                                                      for x in (st.name_ref, st.coords_ref, st.kind_ref, st.note_ref)))
            if r]
    texts = content(refs) if refs else {}

    def text(ref: str) -> str:
        return texts.get(ref, FORGOTTEN) if ref else ""

    out = []
    for t in trips:
        first = _start(t.start)
        days = tuple(DaySeen(n, first + timedelta(days=n - 1) if first else None,
                             tuple(StopSeen(x.id, text(x.name_ref), text(x.kind_ref), text(x.coords_ref),
                                            text(x.note_ref), x.by == c.BY_HER) for x in stops))
                     for n, stops in days_of(t))
        out.append(TripSeen(t.id, text(t.title_ref), first, t.mode, t.avoid, days, len(t.stops), t.mika_touched,
                            t.created_at, t.updated_at))
    return out


def mode_words(mode: str) -> str:
    return MODE_FR.get(mode, mode)


def avoid_words(avoid: Collection[str]) -> str:
    """Ce qu'il évite (« péages, ferries ») ; rien : « rien »."""
    return ", ".join(AVOID_FR.get(a, a) for a in avoid) or "rien"


def day_words(day: date | None) -> str:
    """Un jour du voyage (« sam. 3 avr. 2027 ») ; sans date : vide."""
    return day_fr(day.year, day.month, day.day, day.weekday(), with_year=True) if day is not None else ""


def _stops(t: TripSeen, her: str) -> Table:
    rows: list[Row] = []
    for d in t.days:
        when = f"jour {d.n}" + (f" · {day_words(d.date)}" if d.date else "")
        if not d.stops:
            rows.append(Row((when, Text("aucun arrêt", "muted"), "", "", "", "")))
        rows += [Row((when, Text(x.name, emphasis=True), x.kind or "—", Text(x.note or "—", clamp=200),
                      Text(x.coords, "mono"), her if x.hers else "")) for x in d.stops]
    return Table((Column("jour", "fit"), Column("arrêt", role="title"), "sorte", "note", Column("coordonnées", "fit"),
                  Column("ajouté par", "fit")), tuple(rows), title="Ses arrêts, jour par jour", empty="aucun arrêt",
                 pager=Pager(param=STOPS_PAGE, size=c.STOPS_MAX + c.DAYS_MAX))


def _has_trips(s: TripsState, person: str, frame: Frame) -> bool:
    return bool(trips_of(s, frame.get, person))


@TRIPS.inspect("voyages", title="Voyages", subject="person", order=68, shown=_has_trips,
               description="Les voyages que cette personne prépare, dans l'écran Carte ou avec elle en conversation : "
                           "leur départ, comment on s'y déplace, ce qu'ils évitent, leurs arrêts jour par jour. Ils se "
                           "préparent à deux : la console ne les modifie pas ; un opérateur peut en supprimer un "
                           "(confirmé, audité).")
def _person_tab(s: TripsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    seen = read(s, frame.get, ctx.store.content, ctx.subject)
    if not seen:
        return [Note("Cette personne n'a aucun voyage.", tone="muted")]
    her = self_c.name_of(frame.get(self_c.PERSONA))
    rows = tuple(Row((Text(t.title, emphasis=True), day_words(t.start) or "sans date", mode_words(t.mode),
                      avoid_words(t.avoid), len(t.days), t.stops, f"avec {her}" if t.with_her else "", When(t.updated),
                      Ref("event", t.id, f"#{t.id}")),
                     detail=(_stops(t, her), ActionSlot(REMOVE, initial=(("trip", t.id),), title="Supprimer ce voyage",
                                                        compact=True)))
                 for t in seen)
    return [Table((Column("voyage", role="title"), Column("départ", "fit"), Column("comment", "fit"), "évite",
                   Column("jours", "num"), Column("arrêts", "num"), Column("préparé", "fit"), Column("changé", "fit"),
                   Column("journal", "fit")), rows, title="Ses voyages", empty="aucun",
                  pager=Pager(param=TRIPS_PAGE, size=c.TRIPS_MAX))]
