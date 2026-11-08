"""Ses outils sur la carte, en conversation (ADR 0195, 0196) : chercher des lieux et des adresses, calculer un trajet,
préparer un voyage avec la personne qui lui parle, montrer une carte.

- **À qui** : en tête-à-tête, avec une personne qui a un compte (``offered``), pour elle seule — ses voyages, jamais
  ceux d'une autre ; le gestionnaire revérifie par la règle de la porte (``here_allowed``). Jamais dans un salon,
  jamais dans une initiative (l'outil n'y est même pas offert).
- **Les points** : l'identifiant d'un lieu qu'elle a trouvé (« l123 », « a:1 », ce que ses derniers regards ont
  vu, ceux de cet épisode d'abord), « ici » (la dernière position que son téléphone a donnée, ``location.fix`` —
  un regard sur sa position, qui se voit, et que les droits de ``location_where`` gouvernent), des coordonnées
  « latitude,longitude », ou un nom (le premier lieu trouvé dans l'index).
- **Ce qui se voit** : chaque recherche et chaque trajet s'écrivent (``trips.looked``) et son message en emporte la
  note (``look:<seq>``) ; un voyage créé ou changé, ``trip:<id>`` ; une carte montrée, ``map:<seq>``. Ce qu'elle
  ajoute à un voyage porte ``by = BY_HER`` : rose dans l'écran, retirable d'un geste.
- **Ce qu'elle lit** : les noms viennent d'OpenStreetMap — rendus inertes (``inert``), sous une ligne qui dit que ce
  sont des données. Ses phrases sont dans sa voix (``trips.*``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.contracts import location as location_c
from mika.contracts import trips as c
from mika.kernel.events import Content
from mika.kernel.faculty import ToolResult
from mika.kernel.guards import Superseded
from mika.plugins.trips import BUNDLE, TRIPS, Stop, Trip, days_of, geo, looks_of, trip_of, trips_of, unchanged
from mika.ports.maps import (
    AVOIDS,
    ROUTE_POINTS_MAX,
    MapsPort,
    MapsUnavailable,
    PlaceHit,
    RouteLeg,
    RouteResult,
)
from mika.ports.preprocess import inert
from mika.vocab.circadian import day_fr
from mika.vocab.episodes import Kind, is_work_target
from mika.vocab.phrasebook import family, phrase
from mika.vocab.privacy import ChannelTrust, Sensitivity
from mika.vocab.rights import here_allowed

#: ce qu'elle lit au plus d'un nom (OpenStreetMap, une adresse), d'une consigne de trajet, d'une note
NAME_SHOWN, STEP_SHOWN, NOTE_SHOWN = 120, 160, 300
#: ses appels par épisode : la recherche, le reste
SEARCH_CALLS, OTHER_CALLS = 6, 3
#: ce qu'elle cherche le long d'un voyage : à tant du trajet
SUGGEST_CORRIDOR_M = 5_000
#: combien de lieux elle propose le long d'un voyage, combien de grandes routes elle lit d'un trajet
SUGGESTED, ROADS = 8, 3
#: « ici » : là où est la personne
HERE_WORDS = frozenset({"ici", "here"})
#: l'identifiant d'un lieu qu'elle a trouvé : l'index local (« l123 »), une adresse (« a:1 »)
PLACE_ID = re.compile(r"^(?:l\d{1,12}|a:\d{1,3})$")

Mode = Literal["voiture", "velo", "pied"]
Avoid = Literal["peages", "autoroutes", "ferries"]


def offered(audience: Any) -> bool:
    """Seulement en tête-à-tête, avec quelqu'un qui a un compte : jamais dans un salon, jamais à un inconnu."""
    return audience is not None and bool(getattr(audience, "persons", ())) and not audience.public \
        and not getattr(audience, "room", None) and audience.trust == ChannelTrust.AUTHENTICATED.value


def kept(text: str) -> Content:
    return Content.of(text, level=int(Sensitivity.PERSONAL))


@dataclass(slots=True)
class _Call:
    """Un appel d'outil pour la personne en face : son adresse, sa personne, ce que son message emportera."""

    ctx: Any
    target: str
    person: str
    attach: list[str] = field(default_factory=list)
    known: dict[str, Point] | None = None

    @property
    def port(self) -> MapsPort | None:
        return self.ctx.ports.get("maps")

    def note(self, ref: str) -> None:
        if ref not in self.attach:
            self.attach.append(ref)

    def done(self, content: str) -> ToolResult:
        return ToolResult(content=content, attach=tuple(self.attach))

    def failed(self, exc: Exception) -> ToolResult:
        """Un échec du service, dit en mots — avec ce qu'elle a déjà regardé : « ici » lu, sa bulle 📍 reste, même
        quand le trajet n'a pas abouti (la position est partie vers le serveur d'itinéraires)."""
        return ToolResult(ok=False, content=phrase("trips.tools.failed", error=inert(str(exc), 300)),
                          attach=tuple(self.attach))


def _open(ctx: Any, tool: str, *, acts: bool = False) -> _Call | ToolResult:
    frame = ctx.frame
    ep, aud = frame.episode, frame.audience
    target = ep.target if ep is not None else None
    if not target or is_work_target(target) or not offered(aud) or target not in aud.persons \
            or not here_allowed(frame, BUNDLE, tool, acts=acts):
        return ToolResult(ok=False, content=phrase("trips.tools.not_here"))
    return _Call(ctx, target, str(frame.get(identity_c.PERSON(target)) or target))


def _refused(text: str) -> ToolResult:
    return ToolResult(ok=False, content=text)


def _failed(exc: Exception) -> ToolResult:
    return _refused(phrase("trips.tools.failed", error=inert(str(exc), 300)))


def _texts(ctx: Any, refs: list[str]) -> dict[str, str]:
    wanted = [r for r in dict.fromkeys(refs) if r]
    store = ctx.ports.get("store")
    return dict(store.content(wanted)) if wanted and store is not None else {}


# ── les points ──


@dataclass(frozen=True, slots=True)
class Point:
    """Un point d'un trajet, d'un voyage ou d'une carte, tel qu'il s'écrit (son nom tel quel : il est rendu inerte
    quand elle le lit)."""

    name: str
    lat: float
    lon: float
    kind: str = ""
    town: str = ""
    here: bool = False

    @property
    def at(self) -> geo.Point:
        return (self.lat, self.lon)


class _Miss(Exception):
    """Un point qu'elle n'a pas pu situer : ce qu'elle en lit."""


def _from_item(item: Any) -> Point | None:
    """Un lieu gardé par un regard (``Looked.found``) ; ``None`` s'il est illisible."""
    if not isinstance(item, dict):
        return None
    try:
        lat, lon = float(item["lat"]), float(item["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not geo.valid(lat, lon):
        return None
    return Point(str(item.get("name") or ""), lat, lon, str(item.get("kind_fr") or ""), str(item.get("town") or ""))


def place_items(text: str | None) -> list[dict[str, Any]]:
    """Les lieux d'un regard ou d'une carte (leur JSON gardé) ; illisible ou oublié : aucun."""
    try:
        got = json.loads(text) if text else []
    except ValueError:
        return []
    return [x for x in got if isinstance(x, dict)] if isinstance(got, list) else []


def _known(call: _Call) -> dict[str, Point]:
    """Les lieux de ses derniers regards pour cette personne, par identifiant : ceux de cet épisode d'abord, puis du
    plus récent au plus ancien (le premier vu gagne)."""
    if call.known is None:
        looks = [x for x in looks_of(call.ctx.state, call.person, call.ctx.episode_id) if x.what == c.LOOK_PLACES]
        texts = _texts(call.ctx, [x.found_ref for x in looks])
        out: dict[str, Point] = {}
        for look in looks:
            for item in place_items(texts.get(look.found_ref)):
                ident = str(item.get("id") or "").lower()
                point = _from_item(item)
                if ident and point is not None and ident not in out:
                    out[ident] = point
        call.known = out
    return call.known


def _here(call: _Call) -> Point:
    """« Ici » : la dernière position que son téléphone a donnée — un regard sur elle, qui se voit (sa bulle 📍), et
    que les droits de ``location_where`` gouvernent."""
    frame = call.ctx.frame
    if not here_allowed(frame, location_c.BUNDLE, location_c.WHERE_TOOL):
        raise _Miss(phrase("trips.tools.here_closed"))
    fix = frame.get(location_c.FIX(call.target))
    texts = _texts(call.ctx, [fix.coords_ref, fix.label_ref]) if fix is not None else {}
    at = geo.parse_coords(texts.get(fix.coords_ref)) if fix is not None else None
    if fix is None or at is None:  # jamais dite, effacée, ou oubliée
        raise _Miss(phrase("trips.tools.here_unknown"))
    call.note(location_c.note_ref(fix.seq))
    label = " ".join(str(texts.get(fix.label_ref) or "").split())[:c.NAME_MAX]
    return Point(label or phrase("trips.tools.here_name"), at[0], at[1], here=True)


def _from_hit(hit: PlaceHit) -> Point:
    return Point(hit.name[:c.NAME_MAX], hit.lat, hit.lon, hit.kind_fr[:c.KIND_MAX], hit.town[:c.NAME_MAX])


async def _point(call: _Call, text: str) -> Point:
    raw = " ".join(str(text or "").split())
    key = raw.lower()
    if not raw:
        raise _Miss(phrase("trips.tools.place_missing"))
    if key in HERE_WORDS:
        return _here(call)
    at = geo.parse_coords(raw)
    if at is not None:
        return Point(f"{at[0]:.5f}, {at[1]:.5f}", at[0], at[1])
    if PLACE_ID.match(key):
        found = _known(call).get(key)
        if found is None:
            raise _Miss(phrase("trips.tools.unknown_id", id=inert(raw, 20)))
        return found
    port = call.port
    if port is None or not port.places_ready():
        raise _Miss(phrase("trips.tools.no_places"))
    try:
        hits = await port.search(raw[:200], limit=1)
    except MapsUnavailable as exc:
        raise _Miss(phrase("trips.tools.failed", error=inert(str(exc), 300))) from None
    if not hits:
        raise _Miss(phrase("trips.tools.unknown_place", place=inert(raw, 80)))
    return _from_hit(hits[0])


async def _points(call: _Call, texts: list[str]) -> tuple[list[Point], list[str]]:
    """Chaque point situé, ou ce qui manque (en mots) — tous lus avant que rien ne s'écrive."""
    points, problems = [], []
    for text in texts:
        try:
            points.append(await _point(call, text))
        except _Miss as miss:
            problems.append(str(miss))
    return points, problems


# ── ce qu'elle lit, ce qui s'écrit ──


def _what(kind: str, town: str) -> str:
    kind, town = inert(kind, 60), inert(town, 80)
    return f"{kind}, {town}" if kind and town else kind or town or "—"


def _line(item: dict[str, Any]) -> str:
    """Un lieu trouvé, tel qu'elle le lit."""
    ident = str(item.get("id") or "—")
    name = inert(str(item.get("name") or ""), NAME_SHOWN) or "—"
    what = _what(str(item.get("kind_fr") or ""), str(item.get("town") or ""))
    distance, along = item.get("distance_m"), item.get("along_m")
    if isinstance(distance, int | float) and isinstance(along, int | float):
        return phrase("trips.tools.places.line_along", id=ident, name=name, what=what,
                      distance=geo.km_text(distance), at=geo.km_text(along))
    if isinstance(distance, int | float):
        return phrase("trips.tools.places.line_at", id=ident, name=name, what=what, distance=geo.km_text(distance))
    return phrase("trips.tools.places.line", id=ident, name=name, what=what)


def hit_item(hit: PlaceHit) -> dict[str, Any]:
    """Ce qu'un regard garde d'un lieu trouvé (``Looked.found``) — ce que l'écran Carte montre aussi."""
    return {"id": hit.id[:20], "name": hit.name[:c.NAME_MAX], "kind": hit.kind[:c.KIND_MAX],
            "kind_fr": hit.kind_fr[:c.KIND_MAX], "category": hit.category[:40], "lat": round(hit.lat, 6),
            "lon": round(hit.lon, 6), "town": hit.town[:c.NAME_MAX], "distance_m": hit.distance_m,
            "along_m": hit.along_m}


def point_item(p: Point) -> dict[str, Any]:
    return {"id": "", "name": p.name[:c.NAME_MAX], "kind": "", "kind_fr": p.kind[:c.KIND_MAX], "category": "",
            "lat": round(p.lat, 6), "lon": round(p.lon, 6), "town": p.town[:c.NAME_MAX], "distance_m": None,
            "along_m": None}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


async def _look(call: _Call, what: str, query: str, found: Any) -> None:
    """Son regard s'écrit ; son message en emportera la note."""
    draft = c.LOOKED.draft(person=call.person, handle=call.target, what=what, query=kept(query[:200] or "—"),
                           found=kept(_json(found)))
    commit = await call.ctx.emit(draft)
    if commit.seqs:
        call.note(c.note_ref(c.NOTE_LOOK, commit.seqs[0]))


def _categories(port: MapsPort, asked: str) -> tuple[str, str] | ToolResult:
    """(identifiant, libellé) d'une catégorie demandée (vide : toutes), ou le refus qui dit celles qui existent."""
    wanted = asked.strip().lower()
    if not wanted:
        return "", ""
    known = port.categories()
    label = dict(known).get(wanted)
    if label is None:
        return _refused(phrase("trips.tools.unknown_category", category=inert(asked, 40),
                               known=", ".join(f"{k} ({v})" for k, v in known)))
    return wanted, label


def _modes() -> dict[str, str]:
    return dict(family("trips.modes"))


def _count(n: int) -> str:
    if n == 0:
        return phrase("trips.tools.stops_none")
    return phrase("trips.tools.stops_one") if n == 1 else phrase("trips.tools.stops_many", n=n)


def _start(trip: Trip) -> date | None:
    try:
        return date.fromisoformat(trip.start) if trip.start else None
    except ValueError:
        return None


def _summary(trip: Trip) -> str:
    days = max((s.day for s in trip.stops), default=1)
    parts = [phrase("trips.tools.days_one") if days == 1 else phrase("trips.tools.days_many", n=days),
             _count(len(trip.stops))]
    first = _start(trip)
    if first is not None:
        parts.append(phrase("trips.tools.start", date=day_fr(first)))
    parts.append(_modes().get(trip.mode, trip.mode))
    return ", ".join(parts)


# ── chercher ──


class PlacesArgs(BaseModel):
    text: str = Field(default="", max_length=200, description=phrase("trips.tools.places.text"))
    category: str = Field(default="", max_length=40, description=phrase("trips.tools.places.category"))
    near: str = Field(default="", max_length=200, description=phrase("trips.tools.places.near"))
    radius_km: float = Field(default=10.0, ge=0.1, le=200.0, description=phrase("trips.tools.places.radius_km"))
    limit: int = Field(default=8, ge=1, le=c.FOUND_MAX, description=phrase("trips.tools.places.limit"))


@TRIPS.tool("places_search", description=phrase("trips.tools.places.description"),
            label=phrase("trips.tools.places.label"), args=PlacesArgs, bundle=BUNDLE,
            episodes=[Kind.REPLY], max_calls_per_episode=SEARCH_CALLS, when=offered, needs="maps")
async def places_search(args: PlacesArgs, ctx: Any) -> Any:
    call = _open(ctx, "places_search")
    if isinstance(call, ToolResult):
        return call
    port = call.port
    if port is None or not port.places_ready():
        return _refused(phrase("trips.tools.no_places"))
    category = _categories(port, args.category)
    if isinstance(category, ToolResult):
        return category
    text = " ".join(args.text.split())
    near: Point | None = None
    if args.near.strip():
        try:
            near = await _point(call, args.near)
        except _Miss as miss:
            return _refused(str(miss))
    if not text and near is None:
        return _refused(phrase("trips.tools.places.ask"))
    radius = args.radius_km * 1_000
    try:
        hits = await port.search(text, near=near.at if near else None,
                                 bbox=geo.box(near.at, radius) if near else None, category=category[0],
                                 limit=args.limit)
    except MapsUnavailable as exc:
        return _failed(exc)
    if near is not None:
        hits = [h for h in hits if h.distance_m is None or h.distance_m <= radius]
    if not hits:
        return call.done(phrase("trips.tools.places.nothing"))
    found = [hit_item(h) for h in hits[:c.FOUND_MAX]]
    where = "" if near is None else phrase("trips.look.here") if near.here else phrase("trips.look.near",
                                                                                         place=near.name)
    query = " · ".join(p for p in (text, category[1], where) if p)
    try:
        await _look(call, c.LOOK_PLACES, query, found)
    except Superseded:
        return _refused(phrase("trips.tools.moved"))
    return call.done("\n".join([phrase("trips.tools.data"), *(_line(x) for x in found),
                                phrase("trips.tools.places.then")]))


class AddressArgs(BaseModel):
    text: str = Field(min_length=3, max_length=200, description=phrase("trips.tools.address.text"))


@TRIPS.tool("address_search", description=phrase("trips.tools.address.description"),
            label=phrase("trips.tools.address.label"), args=AddressArgs,
            bundle=BUNDLE, episodes=[Kind.REPLY], max_calls_per_episode=SEARCH_CALLS, when=offered, needs="maps")
async def address_search(args: AddressArgs, ctx: Any) -> Any:
    call = _open(ctx, "address_search")
    if isinstance(call, ToolResult):
        return call
    port = call.port
    if port is None or not port.addresses_ready():
        return _refused(phrase("trips.tools.no_addresses"))
    text = " ".join(args.text.split())
    try:
        hits = await port.addresses(text, limit=5)
    except MapsUnavailable as exc:
        return _failed(exc)
    if not hits:
        return call.done(phrase("trips.tools.address.nothing"))
    found = [hit_item(h) for h in hits[:c.FOUND_MAX]]
    try:
        await _look(call, c.LOOK_PLACES, text, found)
    except Superseded:
        return _refused(phrase("trips.tools.moved"))
    return call.done("\n".join([phrase("trips.tools.data"), *(_line(x) for x in found),
                                phrase("trips.tools.places.then")]))


# ── un trajet ──


def _roads(route: RouteResult) -> str:
    """Les grandes routes d'un trajet : ses consignes les plus longues, dans l'ordre où on les suit."""
    steps = [(i, s) for i, s in enumerate(x for leg in route.legs for x in leg.steps) if s.text.strip()]
    longest = sorted(sorted(steps, key=lambda p: -p[1].distance_m)[:ROADS], key=lambda p: p[0])
    return " ; ".join(f"{inert(s.text, STEP_SHOWN)} ({geo.km_text(s.distance_m)})" for _, s in longest)


def _uses(route: RouteResult) -> str:
    """Ce que le trajet emprunte (des péages, de l'autoroute, un ferry), en mots ; rien : vide."""
    words = family("trips.uses")
    used = [words[k] for k, flag in (("peages", route.has_toll), ("autoroutes", route.has_highway),
                                     ("ferries", route.has_ferry)) if flag and k in words]
    return phrase("trips.tools.route.uses", what=", ".join(used)) if used else ""


class RouteArgs(BaseModel):
    points: list[Annotated[str, Field(max_length=200)]] = Field(min_length=2, max_length=ROUTE_POINTS_MAX,
                                                                description=phrase("trips.tools.route.points"))
    mode: Mode = Field(default="voiture", description=phrase("trips.tools.route.mode"))
    avoid: list[Avoid] = Field(default_factory=list, max_length=len(AVOIDS),
                               description=phrase("trips.tools.route.avoid"))


@TRIPS.tool("route_plan", description=phrase("trips.tools.route.description"),
            label=phrase("trips.tools.route.label"), args=RouteArgs, bundle=BUNDLE,
            episodes=[Kind.REPLY], max_calls_per_episode=OTHER_CALLS, when=offered, needs="maps")
async def route_plan(args: RouteArgs, ctx: Any) -> Any:
    call = _open(ctx, "route_plan")
    if isinstance(call, ToolResult):
        return call
    port = call.port
    if port is None or not port.routing_ready():
        return _refused(phrase("trips.tools.no_routing"))
    points, problems = await _points(call, args.points)
    if problems:
        return _refused("\n".join(problems))
    try:
        route = await geo.chain(port, [p.at for p in points], mode=args.mode, avoid=frozenset(args.avoid))
    except MapsUnavailable as exc:
        return call.failed(exc)
    names = [inert(p.name, 60) or "—" for p in points]
    found = {"distance_m": route.distance_m, "duration_s": route.duration_s, "mode": args.mode,
             "avoid": [a for a in AVOIDS if a in args.avoid],
             "points": [point_item(p) for p in points], "shape": await geo.summary(route)}
    try:
        await _look(call, c.LOOK_ROUTE, " → ".join(p.name for p in points)[:200], found)
    except Superseded:
        return _refused(phrase("trips.tools.moved"))
    lines = [phrase("trips.tools.data"),
             phrase("trips.tools.route.result", points=" → ".join(names), distance=geo.km_text(route.distance_m),
                    duration=geo.duration_text(route.duration_s), how=_modes().get(args.mode, args.mode))]
    if len(points) > 2:
        lines += [phrase("trips.tools.route.leg", start=names[i], end=names[i + 1],
                         distance=geo.km_text(leg.distance_m), duration=geo.duration_text(leg.duration_s))
                  for i, leg in enumerate(route.legs[:len(points) - 1])]
    roads = _roads(route)
    if roads:
        lines.append(phrase("trips.tools.route.roads", roads=roads))
    if uses := _uses(route):
        lines.append(uses)
    return call.done("\n".join(lines))


# ── ses voyages ──


class NoArgs(BaseModel):
    pass


@TRIPS.tool("trip_list", description=phrase("trips.tools.list.description"),
            label=phrase("trips.tools.list.label"), args=NoArgs, bundle=BUNDLE,
            episodes=[Kind.REPLY], max_calls_per_episode=OTHER_CALLS, when=offered)
async def trip_list(args: NoArgs, ctx: Any) -> Any:
    call = _open(ctx, "trip_list")
    if isinstance(call, ToolResult):
        return call
    trips = trips_of(ctx.state, ctx.frame.get, call.person)
    if not trips:
        return call.done(phrase("trips.tools.list.none"))
    texts = _texts(ctx, [t.title_ref for t in trips])
    lines = [phrase("trips.tools.list.line", id=t.id, title=inert(texts.get(t.title_ref, ""), 120) or "—",
                    summary=_summary(t)) for t in trips]
    return call.done("\n".join([phrase("trips.tools.list.head"), *lines]))


class TripArgs(BaseModel):
    trip: str = Field(min_length=1, max_length=20, description=phrase("trips.tools.trip"))


def _mine(call: _Call, trip: str) -> Trip | ToolResult:
    found = trip_of(call.ctx.state, call.ctx.frame.get, call.person, trip)
    return found if found is not None else _refused(phrase("trips.tools.unknown_trip", trip=inert(trip, 20)))


def _stop_texts(call: _Call, trip: Trip) -> dict[str, str]:
    return _texts(call.ctx, [trip.title_ref, *(r for s in trip.stops for r in (s.name_ref, s.coords_ref, s.kind_ref,
                                                                                 s.note_ref))])


def stop_point(stop: Stop, texts: dict[str, str]) -> Point | None:
    """Un arrêt tel qu'un trajet le prend ; ``None`` sans ses coordonnées (oubliées)."""
    at = geo.parse_coords(texts.get(stop.coords_ref))
    return Point(texts.get(stop.name_ref, ""), at[0], at[1], texts.get(stop.kind_ref, "")) if at else None


async def _legs(call: _Call, trip: Trip, texts: dict[str, str]) -> tuple[dict[str, RouteLeg], str]:
    """Le trajet d'un arrêt au suivant, par arrêt d'arrivée — ou ce qui l'empêche, en mots (vide : rien à dire)."""
    port = call.port
    if len(trip.stops) < 2:
        return {}, ""
    if port is None or not port.routing_ready():
        return {}, phrase("trips.tools.read.no_routing")
    points = [stop_point(s, texts) for s in trip.stops]
    if any(p is None for p in points):
        return {}, ""
    try:
        route = await geo.chain(port, [p.at for p in points if p is not None], mode=trip.mode,
                                avoid=frozenset(trip.avoid))
    except MapsUnavailable as exc:
        return {}, phrase("trips.tools.failed", error=inert(str(exc), 300))
    return {trip.stops[i + 1].id: leg for i, leg in enumerate(route.legs[:len(trip.stops) - 1])}, ""


@TRIPS.tool("trip_read", description=phrase("trips.tools.read.description"),
            label=phrase("trips.tools.read.label"), args=TripArgs, bundle=BUNDLE,
            episodes=[Kind.REPLY], max_calls_per_episode=OTHER_CALLS, when=offered)
async def trip_read(args: TripArgs, ctx: Any) -> Any:
    call = _open(ctx, "trip_read")
    if isinstance(call, ToolResult):
        return call
    trip = _mine(call, args.trip)
    if isinstance(trip, ToolResult):
        return trip
    texts = _stop_texts(call, trip)
    legs, said = await _legs(call, trip, texts)
    first = _start(trip)
    lines = [phrase("trips.tools.data"), phrase("trips.tools.read.head", id=trip.id, summary=_summary(trip),
                                                title=inert(texts.get(trip.title_ref, ""), 120) or "—")]
    for n, stops in days_of(trip):
        lines.append(phrase("trips.tools.read.day_dated", n=n, date=day_fr(first + timedelta(days=n - 1)))
                     if first is not None else phrase("trips.tools.read.day", n=n))
        if not stops:
            lines.append(phrase("trips.tools.read.empty_day"))
        for i, s in enumerate(stops, 1):
            parts = [phrase("trips.tools.read.stop", n=i, id=s.id, name=inert(texts.get(s.name_ref, ""), NAME_SHOWN)
                            or "—")]
            if kind := inert(texts.get(s.kind_ref, ""), 60):
                parts.append(kind)
            if s.by == c.BY_HER:
                parts.append(phrase("trips.tools.read.by_you"))
            if s.id in legs:
                parts.append(phrase("trips.tools.read.leg", distance=geo.km_text(legs[s.id].distance_m),
                                    duration=geo.duration_text(legs[s.id].duration_s)))
            if note := inert(texts.get(s.note_ref, ""), NOTE_SHOWN):
                parts.append(phrase("trips.tools.read.note", note=note))
            lines.append(" · ".join(parts))
    if said:
        lines.append(said)
    lines.append(phrase("trips.tools.read.then"))
    return call.done("\n".join(lines))


class StopIn(BaseModel):
    place: str = Field(min_length=1, max_length=200, description=phrase("trips.tools.stop.place"))
    day: int = Field(default=1, ge=1, le=c.DAYS_MAX, description=phrase("trips.tools.stop.day"))
    index: int | None = Field(default=None, ge=0, le=c.STOPS_MAX, description=phrase("trips.tools.stop.index"))
    note: str = Field(default="", max_length=c.NOTE_MAX, description=phrase("trips.tools.stop.note"))


class CreateArgs(BaseModel):
    title: str = Field(min_length=1, max_length=c.TITLE_MAX, description=phrase("trips.tools.create.title"))
    start: str = Field(default="", max_length=10, description=phrase("trips.tools.create.start"))
    mode: Mode = Field(default="voiture", description=phrase("trips.tools.route.mode"))
    stops: list[StopIn] = Field(default_factory=list, max_length=ROUTE_POINTS_MAX,
                                description=phrase("trips.tools.create.stops"))


def _date(text: str) -> str | None:
    """Une date ``AAAA-MM-JJ`` (vide : aucune) ; ``None`` : illisible, ou d'une année hors de ``c.YEARS``."""
    if not text.strip():
        return ""
    try:
        got = date.fromisoformat(text.strip())
    except ValueError:
        return None
    return got.isoformat() if got.year in c.YEARS else None


def _stop_drafts(trip: str, person: str, stops: list[tuple[StopIn, Point]]) -> list[Any]:
    """Ses arrêts, ajoutés par elle (``BY_HER``)."""
    out = []
    for given, point in stops:
        note = given.note.strip()
        out.append(c.STOP_ADDED.draft(trip=trip, person=person, by=c.BY_HER, name=kept(point.name or "—"),
                                      coords=kept(geo.coords_text(point.lat, point.lon)),
                                      kind=kept(point.kind) if point.kind else None, day=given.day,
                                      index=-1 if given.index is None else given.index,
                                      note=kept(note) if note else None))
    return out


def _names(points: list[Point]) -> str:
    shown = [inert(p.name, 60) or "—" for p in points[:8]]
    return ", ".join(shown) + (" …" if len(points) > 8 else "")


@TRIPS.tool("trip_create", acts=True, description=phrase("trips.tools.create.description"),
            label=phrase("trips.tools.create.label"), args=CreateArgs,
            bundle=BUNDLE, episodes=[Kind.REPLY], max_calls_per_episode=OTHER_CALLS, when=offered)
async def trip_create(args: CreateArgs, ctx: Any) -> Any:
    call = _open(ctx, "trip_create", acts=True)
    if isinstance(call, ToolResult):
        return call
    if len(trips_of(ctx.state, ctx.frame.get, call.person)) >= c.TRIPS_MAX:
        return _refused(phrase("trips.tools.too_many_trips", n=c.TRIPS_MAX))
    start, title = _date(args.start), " ".join(args.title.split())
    if start is None:
        return _refused(phrase("trips.tools.bad_date"))
    if not title:
        return _refused(phrase("trips.tools.create.no_title"))
    points, problems = await _points(call, [s.place for s in args.stops])
    if problems:
        return _refused("\n".join(problems))
    try:
        commit = await ctx.emit(c.CREATED.draft(person=call.person, title=kept(title), by=c.BY_HER, mode=args.mode,
                                                start=start))
        trip = str(commit.seqs[0])
        if points:
            await ctx.emit(*_stop_drafts(trip, call.person, list(zip(args.stops, points, strict=True))),
                           guard=unchanged(trip))
    except Superseded:
        return _refused(phrase("trips.tools.moved"))
    call.note(c.note_ref(c.NOTE_TRIP, trip))
    return call.done(phrase("trips.tools.create.done", id=trip, title=inert(title, 120), stops=_count(len(points))))


class MoveIn(BaseModel):
    stop: str = Field(min_length=1, max_length=20, description=phrase("trips.tools.stop.stop"))
    day: int = Field(ge=1, le=c.DAYS_MAX, description=phrase("trips.tools.stop.day"))
    index: int | None = Field(default=None, ge=0, le=c.STOPS_MAX, description=phrase("trips.tools.stop.index"))


class EditArgs(BaseModel):
    trip: str = Field(min_length=1, max_length=20, description=phrase("trips.tools.trip"))
    title: str | None = Field(default=None, max_length=c.TITLE_MAX, description=phrase("trips.tools.edit.title"))
    start: str | None = Field(default=None, max_length=10, description=phrase("trips.tools.edit.start"))
    mode: Mode | None = Field(default=None, description=phrase("trips.tools.edit.mode"))
    avoid: list[Avoid] | None = Field(default=None, max_length=len(AVOIDS),
                                      description=phrase("trips.tools.edit.avoid"))
    add: list[StopIn] = Field(default_factory=list, max_length=ROUTE_POINTS_MAX,
                              description=phrase("trips.tools.edit.add"))
    remove: list[Annotated[str, Field(max_length=20)]] = Field(default_factory=list, max_length=c.STOPS_MAX,
                                                               description=phrase("trips.tools.edit.remove"))
    move: list[MoveIn] = Field(default_factory=list, max_length=c.STOPS_MAX,
                               description=phrase("trips.tools.edit.move"))


@TRIPS.tool("trip_edit", acts=True, description=phrase("trips.tools.edit.description"),
            label=phrase("trips.tools.edit.label"), args=EditArgs, bundle=BUNDLE,
            episodes=[Kind.REPLY], max_calls_per_episode=OTHER_CALLS, when=offered)
async def trip_edit(args: EditArgs, ctx: Any) -> Any:
    call = _open(ctx, "trip_edit", acts=True)
    if isinstance(call, ToolResult):
        return call
    trip = _mine(call, args.trip)
    if isinstance(trip, ToolResult):
        return trip
    texts = _stop_texts(call, trip)
    ids = {s.id for s in trip.stops}
    removed = list(dict.fromkeys(x.strip() for x in args.remove if x.strip()))
    problems = [phrase("trips.tools.unknown_stop", stop=inert(x, 20)) for x in removed if x not in ids]
    problems += [phrase("trips.tools.unknown_stop", stop=inert(m.stop, 20)) for m in args.move
                 if m.stop.strip() not in ids or m.stop.strip() in removed]
    title = " ".join(args.title.split()) if args.title is not None else None
    start = _date(args.start) if args.start is not None else ""
    if args.start is not None and start is None:
        problems.append(phrase("trips.tools.bad_date"))
    if title is not None and not title:
        problems.append(phrase("trips.tools.create.no_title"))
    points, missing = await _points(call, [s.place for s in args.add])
    problems += missing
    if len(trip.stops) - len(removed) + len(points) > c.STOPS_MAX:
        problems.append(phrase("trips.tools.too_many_stops", n=c.STOPS_MAX))
    if problems:
        return _refused("\n".join(problems))
    drafts: list[Any] = []
    said: list[str] = []
    if title is not None or args.start is not None or args.mode is not None or args.avoid is not None:
        drafts.append(c.CHANGED.draft(trip=trip.id, person=trip.person, by=c.BY_HER,
                                      title=kept(title) if title else None, mode=args.mode,
                                      avoid=tuple(a for a in AVOIDS if a in args.avoid) if args.avoid is not None
                                      else None, start=start if args.start is not None else None))
        said.append(phrase("trips.tools.edit.changed"))
    name = {s.id: texts.get(s.name_ref, "") for s in trip.stops}
    drafts += [c.STOP_REMOVED.draft(trip=trip.id, stop=x, person=trip.person, by=c.BY_HER) for x in removed]
    if removed:
        said.append(phrase("trips.tools.edit.removed", names=", ".join(inert(name[x], 60) or x for x in removed)))
    drafts += [c.STOP_MOVED.draft(trip=trip.id, stop=m.stop.strip(), person=trip.person, by=c.BY_HER, day=m.day,
                                  index=-1 if m.index is None else m.index) for m in args.move]
    if args.move:
        said.append(phrase("trips.tools.edit.moved", names=", ".join(inert(name[m.stop.strip()], 60) or m.stop
                                                                     for m in args.move)))
    drafts += _stop_drafts(trip.id, trip.person, list(zip(args.add, points, strict=True)))
    if points:
        said.append(phrase("trips.tools.edit.added", names=_names(points)))
    if not drafts:
        return _refused(phrase("trips.tools.edit.nothing"))
    try:
        await ctx.emit(*drafts, guard=unchanged(trip.id))
    except Superseded:
        return _refused(phrase("trips.tools.moved"))
    call.note(c.note_ref(c.NOTE_TRIP, trip.id))
    return call.done(phrase("trips.tools.edit.done", id=trip.id, what=" ; ".join(said),
                            title=inert(title or texts.get(trip.title_ref, ""), 120) or "—"))


class SuggestArgs(BaseModel):
    trip: str = Field(min_length=1, max_length=20, description=phrase("trips.tools.trip"))
    category: str = Field(min_length=1, max_length=40, description=phrase("trips.tools.places.category"))
    day: int = Field(default=0, ge=0, le=c.DAYS_MAX, description=phrase("trips.tools.suggest.day"))


def along_points(trip: Trip, texts: dict[str, str], day: int) -> list[Point]:
    """Les points du trajet d'un jour (avec le dernier arrêt du jour d'avant : on en repart), ou de tout le voyage
    (``day`` 0) ; un arrêt sans coordonnées (oubliées) n'y est pas."""
    if day:
        before = [s for s in trip.stops if s.day < day][-1:]
        stops = before + [s for s in trip.stops if s.day == day]
    else:
        stops = list(trip.stops)
    return [p for p in (stop_point(s, texts) for s in stops) if p is not None]


@TRIPS.tool("trip_suggest", description=phrase("trips.tools.suggest.description"),
            label=phrase("trips.tools.suggest.label"), args=SuggestArgs, bundle=BUNDLE,
            episodes=[Kind.REPLY], max_calls_per_episode=OTHER_CALLS, when=offered, needs="maps")
async def trip_suggest(args: SuggestArgs, ctx: Any) -> Any:
    call = _open(ctx, "trip_suggest")
    if isinstance(call, ToolResult):
        return call
    port = call.port
    if port is None or not port.places_ready():
        return _refused(phrase("trips.tools.no_places"))
    trip = _mine(call, args.trip)
    if isinstance(trip, ToolResult):
        return trip
    category = _categories(port, args.category)
    if isinstance(category, ToolResult):
        return category
    texts = _stop_texts(call, trip)
    points = along_points(trip, texts, args.day)
    if len(points) < 2:
        return _refused(phrase("trips.tools.suggest.short"))
    line, routed = await geo.follow(port, [p.at for p in points], mode=trip.mode, avoid=frozenset(trip.avoid))
    try:
        hits = await port.along(line, corridor_m=SUGGEST_CORRIDOR_M, category=category[0], limit=SUGGESTED)
    except MapsUnavailable as exc:
        return _failed(exc)
    if not hits:
        return call.done(phrase("trips.tools.places.nothing"))
    found = [hit_item(h) for h in hits[:c.FOUND_MAX]]
    query = " · ".join(p for p in (category[1], phrase("trips.look.along", trip=texts.get(trip.title_ref, "")[:80]))
                       if p)
    try:
        await _look(call, c.LOOK_PLACES, query, found)
    except Superseded:
        return _refused(phrase("trips.tools.moved"))
    lines = [phrase("trips.tools.data"), *(_line(x) for x in found)]
    if not routed:
        lines.append(phrase("trips.tools.suggest.straight"))
    return call.done("\n".join([*lines, phrase("trips.tools.places.then")]))


# ── une carte dans son message ──


class ShowArgs(BaseModel):
    title: str = Field(min_length=1, max_length=c.TITLE_MAX, description=phrase("trips.tools.show.title"))
    places: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=c.FOUND_MAX,
                                                                description=phrase("trips.tools.show.places"))
    route: bool = Field(default=False, description=phrase("trips.tools.show.route"))
    #: vide : celui du voyage montré (sinon en voiture)
    mode: Mode | None = Field(default=None, description=phrase("trips.tools.show.mode"))
    trip: str = Field(default="", max_length=20, description=phrase("trips.tools.show.trip"))


@TRIPS.tool("map_show", description=phrase("trips.tools.show.description"),
            label=phrase("trips.tools.show.label"), args=ShowArgs, bundle=BUNDLE,
            episodes=[Kind.REPLY], max_calls_per_episode=OTHER_CALLS, when=offered)
async def map_show(args: ShowArgs, ctx: Any) -> Any:
    call = _open(ctx, "map_show")
    if isinstance(call, ToolResult):
        return call
    trip: Trip | None = None
    if args.trip.strip():
        got = _mine(call, args.trip)
        if isinstance(got, ToolResult):
            return got
        trip = got
    points, problems = await _points(call, args.places)
    if problems:
        return _refused("\n".join(problems))
    if not points and trip is not None:
        points = along_points(trip, _stop_texts(call, trip), 0)[:c.FOUND_MAX]
    if not points:
        return _refused(phrase("trips.tools.show.empty"))
    title = " ".join(args.title.split()) or "—"
    # un voyage se trace comme il se fait (son mode, ce qu'il évite), sauf un mode demandé
    mode = args.mode or (trip.mode if trip is not None else c.DEFAULT_MODE)
    avoid = frozenset(trip.avoid) if trip is not None else frozenset()
    line: dict[str, Any] | None = None
    said = ""
    if args.route and len(points) >= 2:
        port = call.port
        if port is not None and port.routing_ready():
            try:
                route = await geo.chain(port, [p.at for p in points], mode=mode, avoid=avoid)
                line = {"distance_m": route.distance_m, "duration_s": route.duration_s,
                        "shape": await geo.summary(route)}
            except MapsUnavailable as exc:
                said = phrase("trips.tools.failed", error=inert(str(exc), 300))
        else:
            said = phrase("trips.tools.show.no_line")
    draft = c.SHOWN.draft(person=call.person, handle=call.target, title=kept(title),
                          places=kept(_json([point_item(p) for p in points])), trip=trip.id if trip else "",
                          route=args.route, mode=mode, line=kept(_json(line)) if line else None)
    try:
        commit = await ctx.emit(draft)
    except Superseded:
        return _refused(phrase("trips.tools.moved"))
    if commit.seqs:
        call.note(c.note_ref(c.NOTE_MAP, commit.seqs[0]))
    done = phrase("trips.tools.show.done", title=inert(title, 120), places=_names(points))
    return call.done(f"{done} {said}".strip())
