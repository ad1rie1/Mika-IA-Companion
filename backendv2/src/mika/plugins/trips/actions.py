"""Ce qu'on fait d'un voyage depuis l'écran Carte : les actions de la console (``@TRIPS.action``), au nom de qui agit
(``ctx.by``), que l'API par personne appelle (``app/moi/carte.py``) — journalisées, dédoublonnées et auditées comme
toute action. Pas encore de page de console pour elles (ADR 0195).

Chacune vérifie que le voyage est à la personne qui agit (sinon : il n'existe pas) et les bornes du contrat ; un
geste sur un voyage relu porte sa garde (``unchanged``) : changé entre-temps, rien ne s'écrit.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.contracts import trips as c
from mika.kernel.events import Content
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.operate import Done, Refused
from mika.plugins.trips import TRIPS, Trip, TripsState, trip_of, trips_of, unchanged
from mika.plugins.trips.geo import coords_text, valid
from mika.ports.maps import AVOIDS, MODES
from mika.vocab.privacy import Sensitivity

#: les modes, tels qu'un formulaire les propose ; « inchangé » pour une modification
MODE_CHOICES = tuple((m, m) for m in MODES)
KEEP = "__inchangé__"
GONE = "Ce voyage n'existe pas."
NO_STOP = "Cet arrêt n'est pas dans ce voyage."


def kept(text: str) -> Content:
    """Un texte gardé pour la personne : un contenu personnel, qu'oublier la personne efface."""
    return Content.of(text, level=int(Sensitivity.PERSONAL))


def who(frame: Frame, by: str) -> str:
    """La personne qui agit (par son adresse)."""
    return str(frame.get(identity_c.PERSON(by)) or by)


def check_start(start: str) -> str:
    """Une date de départ : ``AAAA-MM-JJ``, ou vide ; ``Refused`` sinon."""
    text = start.strip()
    if not text:
        return ""
    try:
        got = date.fromisoformat(text)
    except ValueError:
        raise Refused("La date de départ s'écrit AAAA-MM-JJ.", {"start": "une date AAAA-MM-JJ"}) from None
    if got.year not in c.YEARS:  # ses jours se comptent depuis elle : une année démesurée les ferait déborder
        raise Refused(f"La date de départ est entre {c.YEARS.start} et {c.YEARS.stop - 1}.",
                      {"start": f"une année de {c.YEARS.start} à {c.YEARS.stop - 1}"})
    return got.isoformat()


def check_avoid(values: tuple[str, ...]) -> tuple[str, ...]:
    bad = [v for v in values if v not in AVOIDS]
    if bad:
        raise Refused(f"On évite : {', '.join(AVOIDS)}.", {"avoid": f"inconnu : {bad[0][:20]}"})
    return tuple(a for a in AVOIDS if a in values)


def mine(s: TripsState, frame: Frame, by: str, trip: str) -> Trip:
    found = trip_of(s, frame.get, who(frame, by), trip)
    if found is None:
        raise Refused(GONE)
    return found


def _title(text: str) -> str:
    title = " ".join(text.split())
    if not title:
        raise Refused("Un voyage a un titre.", {"title": "un titre"})
    return title


# ── un voyage ──


class CreateArgs(BaseModel):
    title: Annotated[str, Knob(label="Titre", advanced=False)] = Field(min_length=1, max_length=c.TITLE_MAX)
    start: Annotated[str, Knob(label="Départ", help="AAAA-MM-JJ, ou vide.", advanced=False)] = \
        Field(default="", max_length=10)
    mode: Annotated[str, Knob(label="Comment", choices=MODE_CHOICES, advanced=False)] = c.DEFAULT_MODE
    avoid: Annotated[tuple[str, ...], Knob(label="Éviter", help=", ".join(AVOIDS), advanced=False)] = \
        Field(default=(), max_length=len(AVOIDS))


@TRIPS.action("creer", title="Créer un voyage", args=CreateArgs, emits=[c.CREATED])
def _create(s: TripsState, frame: Frame, args: CreateArgs, ctx: Any) -> Done:
    person = who(frame, ctx.by)
    if len(trips_of(s, frame.get, person)) >= c.TRIPS_MAX:
        raise Refused(f"{c.TRIPS_MAX} voyages au plus : supprimes-en un d'abord.")
    if args.mode not in MODES:
        raise Refused("Un mode inconnu.", {"mode": "voiture, velo ou pied"})
    draft = c.CREATED.draft(person=person, title=kept(_title(args.title)), by=ctx.by, mode=args.mode,
                            avoid=check_avoid(args.avoid), start=check_start(args.start))
    return Done(drafts=(draft,), message="Voyage créé.")


class ChangeArgs(BaseModel):
    trip: Annotated[str, Knob(label="Voyage", widget="hidden")] = Field(min_length=1, max_length=20)
    title: Annotated[str, Knob(label="Titre", advanced=False)] = Field(default=KEEP, max_length=c.TITLE_MAX)
    start: Annotated[str, Knob(label="Départ", help="AAAA-MM-JJ, ou vide.", advanced=False)] = \
        Field(default=KEEP, max_length=20)
    mode: Annotated[str, Knob(label="Comment", choices=(("", "inchangé"), *MODE_CHOICES), advanced=False)] = ""
    avoid: Annotated[tuple[str, ...] | None, Knob(label="Éviter", help=", ".join(AVOIDS), advanced=False)] = \
        Field(default=None, max_length=len(AVOIDS))


@TRIPS.action("modifier", title="Modifier un voyage", args=ChangeArgs, emits=[c.CHANGED])
def _change(s: TripsState, frame: Frame, args: ChangeArgs, ctx: Any) -> Done:
    trip = mine(s, frame, ctx.by, args.trip)
    if args.mode and args.mode not in MODES:
        raise Refused("Un mode inconnu.", {"mode": "voiture, velo ou pied"})
    title = _title(args.title) if args.title != KEEP else None
    start = check_start(args.start) if args.start != KEEP else None
    avoid = check_avoid(args.avoid) if args.avoid is not None else None
    if title is None and start is None and not args.mode and avoid is None:
        return Done(message="Rien à changer.", tone="info")
    draft = c.CHANGED.draft(trip=trip.id, person=trip.person, by=ctx.by, title=kept(title) if title else None,
                            mode=args.mode or None, avoid=avoid, start=start)
    return Done(drafts=(draft,), message="Voyage modifié.", guard=unchanged(trip.id))


class TripArgs(BaseModel):
    trip: Annotated[str, Knob(label="Voyage", widget="hidden")] = Field(min_length=1, max_length=20)


@TRIPS.action("supprimer", title="Supprimer un voyage", args=TripArgs, emits=[c.REMOVED], danger=True,
              confirm="Supprimer ce voyage et tous ses arrêts ?")
def _remove(s: TripsState, frame: Frame, args: TripArgs, ctx: Any) -> Done:
    trip = mine(s, frame, ctx.by, args.trip)
    return Done(drafts=(c.REMOVED.draft(trip=trip.id, person=trip.person, by=ctx.by),), message="Voyage supprimé.")


# ── ses arrêts ──


class AddStopArgs(BaseModel):
    trip: Annotated[str, Knob(label="Voyage", widget="hidden")] = Field(min_length=1, max_length=20)
    name: Annotated[str, Knob(label="Nom", advanced=False)] = Field(min_length=1, max_length=c.NAME_MAX)
    lat: Annotated[float, Knob(label="Latitude", advanced=False)] = Field(ge=-90, le=90)
    lon: Annotated[float, Knob(label="Longitude", advanced=False)] = Field(ge=-180, le=180)
    kind: Annotated[str, Knob(label="Sorte", advanced=False)] = Field(default="", max_length=c.KIND_MAX)
    day: Annotated[int, Knob(label="Jour", advanced=False)] = Field(default=1, ge=1, le=c.DAYS_MAX)
    index: Annotated[int, Knob(label="Place dans le jour", help="0 : la première ; -1 : à la fin.",
                               advanced=False)] = Field(default=-1, ge=-1, le=c.STOPS_MAX)
    note: Annotated[str, Knob(label="Note", widget="textarea", advanced=False)] = Field(default="",
                                                                                      max_length=c.NOTE_MAX)


@TRIPS.action("ajouter_arret", title="Ajouter un arrêt", args=AddStopArgs, emits=[c.STOP_ADDED])
def _add_stop(s: TripsState, frame: Frame, args: AddStopArgs, ctx: Any) -> Done:
    trip = mine(s, frame, ctx.by, args.trip)
    if len(trip.stops) >= c.STOPS_MAX:
        raise Refused(f"{c.STOPS_MAX} arrêts au plus dans un voyage.")
    name = " ".join(args.name.split())
    if not name:
        raise Refused("Un arrêt a un nom.", {"name": "un nom"})
    if not valid(args.lat, args.lon):
        raise Refused("Des coordonnées hors de la Terre.", {"lat": "entre -90 et 90", "lon": "entre -180 et 180"})
    kind, note = " ".join(args.kind.split()), args.note.strip()
    draft = c.STOP_ADDED.draft(trip=trip.id, person=trip.person, by=ctx.by, name=kept(name),
                               coords=kept(coords_text(args.lat, args.lon)), kind=kept(kind) if kind else None,
                               day=args.day, index=args.index, note=kept(note) if note else None)
    return Done(drafts=(draft,), message="Arrêt ajouté.", guard=unchanged(trip.id))


class MoveStopArgs(BaseModel):
    trip: Annotated[str, Knob(label="Voyage", widget="hidden")] = Field(min_length=1, max_length=20)
    stop: Annotated[str, Knob(label="Arrêt", widget="hidden")] = Field(min_length=1, max_length=20)
    day: Annotated[int, Knob(label="Jour", advanced=False)] = Field(ge=1, le=c.DAYS_MAX)
    index: Annotated[int, Knob(label="Place dans le jour", help="0 : la première ; -1 : à la fin.",
                               advanced=False)] = Field(default=-1, ge=-1, le=c.STOPS_MAX)


def _stop_of(trip: Trip, stop: str) -> str:
    if not any(x.id == stop for x in trip.stops):
        raise Refused(NO_STOP)
    return stop


@TRIPS.action("deplacer_arret", title="Déplacer un arrêt", args=MoveStopArgs, emits=[c.STOP_MOVED])
def _move_stop(s: TripsState, frame: Frame, args: MoveStopArgs, ctx: Any) -> Done:
    trip = mine(s, frame, ctx.by, args.trip)
    draft = c.STOP_MOVED.draft(trip=trip.id, stop=_stop_of(trip, args.stop), person=trip.person, by=ctx.by,
                               day=args.day, index=args.index)
    return Done(drafts=(draft,), message="Arrêt déplacé.", guard=unchanged(trip.id))


class NoteStopArgs(BaseModel):
    trip: Annotated[str, Knob(label="Voyage", widget="hidden")] = Field(min_length=1, max_length=20)
    stop: Annotated[str, Knob(label="Arrêt", widget="hidden")] = Field(min_length=1, max_length=20)
    note: Annotated[str, Knob(label="Note", widget="textarea", help="Vide : plus de note.", advanced=False)] = \
        Field(default="", max_length=c.NOTE_MAX)


@TRIPS.action("noter_arret", title="Noter un arrêt", args=NoteStopArgs, emits=[c.STOP_NOTED])
def _note_stop(s: TripsState, frame: Frame, args: NoteStopArgs, ctx: Any) -> Done:
    trip = mine(s, frame, ctx.by, args.trip)
    note = args.note.strip()
    draft = c.STOP_NOTED.draft(trip=trip.id, stop=_stop_of(trip, args.stop), person=trip.person, by=ctx.by,
                               note=kept(note) if note else None)
    return Done(drafts=(draft,), message="Note enregistrée." if note else "Note retirée.", guard=unchanged(trip.id))


class StopArgs(BaseModel):
    trip: Annotated[str, Knob(label="Voyage", widget="hidden")] = Field(min_length=1, max_length=20)
    stop: Annotated[str, Knob(label="Arrêt", widget="hidden")] = Field(min_length=1, max_length=20)


@TRIPS.action("retirer_arret", title="Retirer un arrêt", args=StopArgs, emits=[c.STOP_REMOVED])
def _remove_stop(s: TripsState, frame: Frame, args: StopArgs, ctx: Any) -> Done:
    trip = mine(s, frame, ctx.by, args.trip)
    draft = c.STOP_REMOVED.draft(trip=trip.id, stop=_stop_of(trip, args.stop), person=trip.person, by=ctx.by)
    return Done(drafts=(draft,), message="Arrêt retiré.", guard=unchanged(trip.id))


class OrderArgs(BaseModel):
    trip: Annotated[str, Knob(label="Voyage", widget="hidden")] = Field(min_length=1, max_length=20)
    day: Annotated[int, Knob(label="Jour", advanced=False)] = Field(ge=1, le=c.DAYS_MAX)
    order: Annotated[tuple[str, ...], Knob(label="Ordre", help="Les arrêts du jour, un par ligne, dans l'ordre.",
                                           advanced=False)] = Field(max_length=c.STOPS_MAX)


def moves(current: list[str], order: list[str]) -> list[tuple[str, int]]:
    """Les déplacements qui mènent de ``current`` à ``order`` (les mêmes arrêts) : chacun mis à sa place, l'un après
    l'autre, comme le réducteur les applique ; un arrêt déjà à sa place ne bouge pas."""
    now, out = list(current), []
    for i, stop in enumerate(order):
        if now[i] != stop:
            now.remove(stop)
            now.insert(i, stop)
            out.append((stop, i))
    return out


@TRIPS.action("ordonner_jour", title="Réordonner un jour", args=OrderArgs, emits=[c.STOP_MOVED])
def _order_day(s: TripsState, frame: Frame, args: OrderArgs, ctx: Any) -> Done:
    trip = mine(s, frame, ctx.by, args.trip)
    current = [x.id for x in trip.stops if x.day == args.day]
    order = [x.strip() for x in args.order if x.strip()]
    if sorted(order) != sorted(current):
        raise Refused("L'ordre doit nommer chaque arrêt de ce jour, une fois.", {"order": "les arrêts du jour"})
    drafts = tuple(c.STOP_MOVED.draft(trip=trip.id, stop=stop, person=trip.person, by=ctx.by, day=args.day, index=i)
                   for stop, i in moves(current, order))
    if not drafts:
        return Done(message="Déjà dans cet ordre.", tone="info")
    return Done(drafts=drafts, message="Jour réordonné.", guard=unchanged(trip.id))
