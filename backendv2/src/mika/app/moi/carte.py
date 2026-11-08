"""Carte, lieux, itinéraires et voyages, pour qui est connecté (ADR 0194, 0195, 0196).

- **La carte** : ce qui est branché (l'index des lieux, les adresses, les itinéraires) ; chercher un lieu dans
  l'index local (rien ne sort), une adresse (seul le texte cherché part), un itinéraire (seuls ses points partent),
  le meilleur ordre de quelques points, les lieux le long d'un trajet ; et ce qu'elle a cherché ou montré pour toi
  (un regard, une carte, par leur ``seq``). Tout passe par le port de la carte (``kernel.ports["maps"]``,
  ``mika.ports.maps``) : le navigateur ne joint jamais un autre hôte que ce serveur.
- **Tes voyages** : les tiens seulement — un voyage d'une autre personne n'existe pas (le même 404). Ce qu'on y fait
  passe par les actions du plugin ``trips`` (``call.act``), au nom de qui est connecté : journalisées, dédoublonnées
  (``Idempotency-Key``) comme dans la console, auditées depuis son espace (``moi.<action>``). Ce qu'elle y a ajouté
  porte ``"by": "mika"``, ce que tu y as fait ``"toi"``.

Le contrat, route par route : ``docs/protocole-moi.md``, § 10.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import math
import re
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from typing import Any

from starlette.responses import Response
from starlette.routing import Route

from mika.adapters.maps import gpx
from mika.app.moi import Call, Denied, MeApi, done, form, missing
from mika.contracts import trips as c
from mika.kernel.events import EventType
from mika.plugins import trips as trips_p
from mika.plugins.trips import Stop, Trip, TripsState, days_of, geo
from mika.plugins.trips.tools import along_points, place_items, stop_point
from mika.ports.maps import AVOIDS, MODES, ROUTE_POINTS_MAX, MapsUnavailable, PlaceHit, RouteLeg, RouteResult
from mika.runtime.effects import with_content
from mika.runtime.operations import SPACE, Outcome, perform

CARTE = "/carte"
VOYAGES = "/voyages"
#: un texte cherché ; combien de lieux au plus ; d'un trajet, à quelle distance chercher (en mètres)
QUERY_MAX = 200
LIMIT_MAX = 50
CORRIDOR_MIN, CORRIDOR_MAX, CORRIDOR = 200, 50_000, 5_000
#: qui a fait un geste, pour l'écran : elle (rose), ou toi
HERS, YOURS = c.BY_HER, "toi"

NOT_PLUGGED = "La carte n'est pas branchée sur ce serveur."
#: ce qui n'est pas prêt : ce que la personne en lit, puis ce qu'une opératrice en lit. Une personne n'a pas la
#: console : ce qui manque et où le régler ne se dit qu'à qui peut le faire
NOT_READY = {
    "places": ("La recherche de lieux n'est pas encore prête sur ce serveur.",
               "L'index des lieux n'est pas construit : Réglages › Carte et téléphone › Lieux et adresses "
               "(mika carte lieux)."),
    "addresses": ("La recherche d'adresses n'est pas encore prête sur ce serveur.",
                  "Les adresses ne sont pas branchées : Réglages › Carte et téléphone › Lieux et adresses."),
    "routing": ("Les itinéraires ne sont pas encore prêts sur ce serveur.",
                "Les itinéraires ne sont pas réglés : Réglages › Carte et téléphone › Itinéraires."),
}
_DIGITS = re.compile(r"^\d{1,18}$")


def _ms(us: int) -> int:
    return us // 1000 if us else 0


def _maps(call: Call, need: str = "") -> Any:
    """Le port de la carte, et ce dont la route a besoin (``places``, ``addresses``, ``routing``) : sinon 503, dit."""
    port = call.port("maps")
    if port is None:
        raise Denied(503, NOT_PLUGGED)
    if (need == "places" and not port.places_ready()) or (need == "addresses" and not port.addresses_ready()) \
            or (need == "routing" and not port.routing_ready()):
        person, operator = NOT_READY[need]
        raise Denied(503, operator if call.me.operator else person)
    return port


def _unavailable(exc: MapsUnavailable) -> Denied:
    return Denied(503, str(exc)[:300] or NOT_PLUGGED)


def _texts(call: Call, refs: list[str]) -> dict[str, str]:
    wanted = [r for r in dict.fromkeys(refs) if r]
    store = call.port("store")
    return dict(store.content(wanted)) if wanted and store is not None else {}


def _state(call: Call) -> TripsState:
    return call.frame.state(trips_p.TRIPS.name)


# ── lire les paramètres ──


def _int(call: Call, name: str, default: int, low: int, high: int) -> int:
    """Un nombre entier, de la requête ou du corps : refusé hors de ses bornes, jamais ramené dedans."""
    raw = call.request.query_params.get(name)
    got: Any = raw if raw is not None else call.data.get(name, default)
    if isinstance(got, bool) or (isinstance(got, float) and not got.is_integer()):
        # un flottant qui n'est pas entier (2.9) est refusé, jamais tronqué ; ``Infinity`` (que json accepte) aussi
        raise Denied(400, f"« {name} » : un nombre entier.", {name: "un nombre entier"})
    try:
        value = int(got)
    except (TypeError, ValueError, OverflowError):
        raise Denied(400, f"« {name} » : un nombre entier.", {name: "un nombre entier"}) from None
    if not low <= value <= high:
        raise Denied(400, f"« {name} » : de {low} à {high}.", {name: f"de {low} à {high}"})
    return value


def _coords(text: str, name: str) -> geo.Point:
    got = geo.parse_coords(text)
    if got is None:
        raise Denied(400, f"« {name} » : latitude,longitude.", {name: "latitude,longitude"})
    return got


def _points(call: Call) -> list[geo.Point]:
    """``points=lat,lon;lat,lon…`` : de deux à ``ROUTE_POINTS_MAX`` points."""
    parts = [p for p in call.arg("points", limit=ROUTE_POINTS_MAX * 40).split(";") if p.strip()]
    if not 2 <= len(parts) <= ROUTE_POINTS_MAX:
        raise Denied(400, f"« points » : de 2 à {ROUTE_POINTS_MAX} points « latitude,longitude » séparés par « ; ».",
                     {"points": f"de 2 à {ROUTE_POINTS_MAX} points"})
    return [_coords(p, "points") for p in parts]


def _mode(call: Call) -> str:
    mode = call.arg("mode", limit=20) or c.DEFAULT_MODE
    if mode not in MODES:
        raise Denied(400, f"« mode » : {', '.join(MODES)}.", {"mode": ", ".join(MODES)})
    return mode


def _avoid(call: Call) -> list[str]:
    """Ce qu'un trajet évite : ``avoid=peages,autoroutes`` dans la requête, une liste dans un corps."""
    raw = call.data.get("avoid") if call.request.query_params.get("avoid") is None else None
    if isinstance(raw, list):
        got = call.strings("avoid", limit=len(AVOIDS), size=20)
    else:
        got = [a.strip() for a in call.arg("avoid", limit=60).split(",") if a.strip()]
    bad = [a for a in got if a not in AVOIDS]
    if bad:
        raise Denied(400, f"« avoid » : {', '.join(AVOIDS)}.", {"avoid": ", ".join(AVOIDS)})
    return [a for a in AVOIDS if a in got]


def _category(call: Call, port: Any) -> str:
    cat = call.arg("cat", limit=40).strip()
    if cat and cat not in {k for k, _ in port.categories()}:
        raise Denied(400, "« cat » : une des catégories de GET /api/moi/carte.", {"cat": "une catégorie connue"})
    return cat


def _bbox(text: str) -> tuple[float, float, float, float]:
    try:
        west, south, east, north = (float(x) for x in text.split(","))
    except ValueError:
        raise Denied(400, "« bbox » : ouest,sud,est,nord.", {"bbox": "ouest,sud,est,nord"}) from None
    # une zone plate ou retournée (ouest ≥ est, sud ≥ nord) ne se cherche pas : refusée, comme le port le veut
    if not (geo.valid(south, west) and geo.valid(north, east)) or south >= north or west >= east:
        raise Denied(400, "« bbox » : ouest,sud,est,nord (ouest < est, sud < nord).", {"bbox": "ouest,sud,est,nord"})
    return west, south, east, north


# ── ce qu'on rend ──


def _hit(hit: PlaceHit) -> dict[str, Any]:
    return dataclasses.asdict(hit)


def _leg(leg: RouteLeg) -> dict[str, Any]:
    return {"distance_m": leg.distance_m, "duration_s": leg.duration_s, "shape": leg.shape,
            "steps": [{"text": s.text, "distance_m": s.distance_m, "duration_s": s.duration_s} for s in leg.steps]}


def _route(route: RouteResult) -> dict[str, Any]:
    return {"distance_m": route.distance_m, "duration_s": route.duration_s, "legs": [_leg(x) for x in route.legs],
            "has_toll": route.has_toll, "has_highway": route.has_highway, "has_ferry": route.has_ferry,
            "provider": route.provider}


def _order(got: Any, n: int) -> list[int]:
    """L'ordre rendu par le serveur d'itinéraires : chaque point une fois, le départ et l'arrivée à leur place."""
    try:
        order = [int(i) for i in got]
    except (TypeError, ValueError):
        order = []
    if sorted(order) != list(range(n)) or (n and (order[0] != 0 or order[-1] != n - 1)):
        raise Denied(502, "Le serveur d'itinéraires a rendu un ordre illisible.")
    return order


# ── la carte ──


def _index(port: Any) -> tuple[int, int]:
    """Combien de lieux a l'index, et quand il a été construit (ms) : ce que le port en dit, s'il sait le dire
    (``places_summary``, en plus du port : ``built`` en ISO 8601) ; sinon rien (0)."""
    summary = getattr(port, "places_summary", None)
    got = summary() if callable(summary) else None
    if not isinstance(got, Mapping):
        return 0, 0
    try:
        count = max(0, int(got.get("count") or 0))
    except (TypeError, ValueError):
        count = 0
    try:
        built = int(datetime.fromisoformat(str(got.get("built") or "")).timestamp() * 1000)
    except ValueError:
        built = 0
    return count, max(0, built)


async def info(call: Call) -> dict[str, Any]:
    """Ce qui est branché : l'index des lieux, les adresses, les itinéraires (qui les calcule), les catégories."""
    port = call.port("maps")
    routing = {"modes": list(MODES), "avoid": list(AVOIDS)}
    if port is None:
        return {"places": {"ready": False, "count": 0, "built": 0}, "addresses": {"ready": False},
                "routing": {"ready": False, "provider": "", **routing}, "categories": []}
    count, built = _index(port)
    ready = port.routing_ready()
    return {"places": {"ready": port.places_ready(), "count": count, "built": built},
            "addresses": {"ready": port.addresses_ready()},
            "routing": {"ready": ready, "provider": port.routing_provider() if ready else "", **routing},
            "categories": [{"id": k, "label": v} for k, v in port.categories()]}


async def places(call: Call) -> dict[str, Any]:
    """Des lieux de l'index local : par le nom (``q``), d'une catégorie (``cat``), près d'un point (``near``), dans une
    zone (``bbox``)."""
    port = _maps(call, "places")
    text = " ".join(call.arg("q", limit=QUERY_MAX).split())
    category = _category(call, port)
    near_text, bbox_text = call.arg("near", limit=60), call.arg("bbox", limit=120)
    near = _coords(near_text, "near") if near_text.strip() else None
    bbox = _bbox(bbox_text) if bbox_text.strip() else None
    if not text and near is None and bbox is None:
        raise Denied(400, "Cherche un nom (q), ou autour d'un point (near), ou dans une zone (bbox).")
    limit = _int(call, "limit", 20, 1, LIMIT_MAX)
    try:
        hits = await port.search(text, near=near, bbox=bbox, category=category, limit=limit)
    except MapsUnavailable as exc:
        raise _unavailable(exc) from None
    return {"places": [_hit(h) for h in hits[:limit]]}


async def addresses(call: Call) -> dict[str, Any]:
    """Une adresse, à la Géoplateforme : seul ce texte part."""
    port = _maps(call, "addresses")
    text = " ".join(call.arg("q", limit=QUERY_MAX).split())
    if len(text) < 3:
        raise Denied(400, "« q » : trois caractères au moins.", {"q": "trois caractères au moins"})
    limit = _int(call, "limit", 5, 1, 10)
    call.outbound(addresses=True)
    try:
        hits = await port.addresses(text, limit=limit)
    except MapsUnavailable as exc:
        raise _unavailable(exc) from None
    return {"places": [_hit(h) for h in hits[:limit]]}


async def itinerary(call: Call) -> dict[str, Any]:
    port = _maps(call, "routing")
    points, mode, avoid = _points(call), _mode(call), frozenset(_avoid(call))
    call.outbound()
    try:
        route = await port.route(points, mode=mode, avoid=avoid)
    except MapsUnavailable as exc:
        raise _unavailable(exc) from None
    return _route(route)


async def best_order(call: Call) -> dict[str, Any]:
    """Le meilleur ordre de ces points, le départ et l'arrivée fixes."""
    port = _maps(call, "routing")
    points, mode = _points(call), _mode(call)
    call.outbound()
    try:
        got = await port.optimize(points, mode=mode)
    except MapsUnavailable as exc:
        raise _unavailable(exc) from None
    return {"order": _order(got, len(points))}


async def along(call: Call) -> dict[str, Any]:
    """Les lieux le long d'un trajet entre ces points (à vol d'oiseau sans itinéraires : ``route`` faux)."""
    port = _maps(call, "places")
    points, category = _points(call), _category(call, port)
    corridor = _int(call, "corridor", CORRIDOR, CORRIDOR_MIN, CORRIDOR_MAX)
    limit = _int(call, "limit", 20, 1, LIMIT_MAX)
    mode, avoid = _mode(call), frozenset(_avoid(call))
    if port.routing_ready():
        call.outbound()
    line, routed = await geo.follow(port, points, mode=mode, avoid=avoid)
    try:
        hits = await port.along(line, corridor_m=corridor, category=category, limit=limit)
    except MapsUnavailable as exc:
        raise _unavailable(exc) from None
    return {"places": [_hit(h) for h in hits[:limit]], "route": routed}


def _json(text: str | None) -> Any:
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


async def look(call: Call) -> dict[str, Any]:
    """Ce qu'elle a cherché (``look``) ou montré (``map``) pour toi, par son ``seq`` : la note d'un de ses messages.
    Oublié, ou pour quelqu'un d'autre : 404."""
    seq = int(call.request.path_params["seq"])
    if not 0 < seq < 2 ** 63:  # au-delà, la base ne lit rien : ce n'est pas une de ses notes
        raise missing()
    mind = call.kernel.mind
    rows = mind.store.get_events([seq])
    ev = mind.decode(rows[0]) if rows else None
    if ev is None or ev.type.name not in (c.LOOKED.name, c.SHOWN.name):
        raise missing()
    d = ev.data
    if trips_p.owner_key(call.frame.get, d.person) != call.me.person and d.handle != call.me.handle:
        raise missing()
    d = with_content(mind, ev).data
    if ev.type.name == c.LOOKED.name:
        if d.query.text is None or d.found.text is None:  # oublié
            raise missing()
        found = _json(d.found.text)
        if d.what == c.LOOK_ROUTE and isinstance(found, dict):
            route = {k: found.get(k) for k in ("mode", "distance_m", "duration_s", "shape")}
            route["avoid"] = [a for a in AVOIDS if a in (found.get("avoid") or [])]  # vide pour un regard d'avant
            points = found.get("points")
            return {"kind": c.NOTE_LOOK, "title": d.query.text, "what": d.what, "route": route, "trip": "",
                    "places": [x for x in points if isinstance(x, dict)] if isinstance(points, list) else [],
                    "at": _ms(ev.at)}
        return {"kind": c.NOTE_LOOK, "title": d.query.text, "what": d.what, "places": place_items(d.found.text),
                "route": None, "trip": "", "at": _ms(ev.at)}
    if d.title.text is None or d.places.text is None:
        raise missing()
    line = _json(d.line.text) if d.line is not None else None
    route = {"mode": d.mode, **({k: line.get(k) for k in ("distance_m", "duration_s", "shape")}
                                if isinstance(line, dict) else {})} if d.route else None
    trip = trips_p.trip_of(_state(call), call.frame.get, call.me.person, d.trip) if d.trip else None
    return {"kind": c.NOTE_MAP, "title": d.title.text, "what": "", "places": place_items(d.places.text),
            "route": route, "trip": trip.id if trip is not None else "", "at": _ms(ev.at)}


# ── tes voyages ──


def _trip(call: Call) -> Trip:
    ident = str(call.request.path_params["trip"])
    trip = trips_p.trip_of(_state(call), call.frame.get, call.me.person, ident) if _DIGITS.match(ident) else None
    if trip is None:
        raise missing()
    return trip


def _refs(trip: Trip) -> list[str]:
    return [trip.title_ref, *(r for s in trip.stops for r in (s.name_ref, s.coords_ref, s.kind_ref, s.note_ref))]


def _start(trip: Trip) -> date | None:
    try:
        return date.fromisoformat(trip.start) if trip.start else None
    except ValueError:
        return None


def _stop(stop: Stop, texts: dict[str, str]) -> dict[str, Any]:
    at = geo.parse_coords(texts.get(stop.coords_ref))
    return {"id": stop.id, "name": texts.get(stop.name_ref, ""), "kind": texts.get(stop.kind_ref, ""),
            "lat": at[0] if at else None, "lon": at[1] if at else None, "note": texts.get(stop.note_ref, ""),
            "by": HERS if stop.by == c.BY_HER else YOURS}


async def trips_list(call: Call) -> dict[str, Any]:
    mine = trips_p.trips_of(_state(call), call.frame.get, call.me.person)
    texts = _texts(call, [t.title_ref for t in mine])
    return {"trips": [{"id": t.id, "title": texts.get(t.title_ref, ""), "start": t.start, "mode": t.mode,
                       "avoid": list(t.avoid), "days": len(days_of(t)), "stops": len(t.stops),
                       "updated": _ms(t.updated_at), "mika": t.mika_touched} for t in mine]}


async def trip_read(call: Call) -> dict[str, Any]:
    trip = _trip(call)
    texts = _texts(call, _refs(trip))
    first = _start(trip)
    return {"id": trip.id, "title": texts.get(trip.title_ref, ""), "start": trip.start, "mode": trip.mode,
            "avoid": list(trip.avoid), "updated": _ms(trip.updated_at), "mika": trip.mika_touched,
            "days": [{"n": n, "date": (first + timedelta(days=n - 1)).isoformat() if first else "",
                      "stops": [_stop(s, texts) for s in stops]} for n, stops in days_of(trip)]}


def _created(call: Call, outcome: Outcome, kind: EventType[Any]) -> str:
    """Ce que l'action a créé (son ``seq``) — retrouvé par sa clé d'envoi quand l'envoi est redit."""
    if outcome.seqs:
        return str(outcome.seqs[0])
    nonce = call.nonce()
    seq = call.kernel.mind.store.find_dedupe(kind.name, f"op:{nonce}:0") if nonce else None
    return str(seq) if seq is not None else ""


def _settings(call: Call) -> dict[str, Any]:
    """Ce qu'un voyage reçoit de réglé : seulement ce que le corps nomme (le reste ne change pas)."""
    values: dict[str, Any] = {}
    if "title" in call.data:
        values["title"] = call.arg("title", limit=c.TITLE_MAX)
    if "start" in call.data:
        values["start"] = call.arg("start", limit=10)
    if "mode" in call.data:
        values["mode"] = _mode(call)
    if "avoid" in call.data:
        values["avoid"] = _avoid(call)
    return values


async def trip_create(call: Call) -> dict[str, Any]:
    got = await call.act("trips.creer", form(**{"title": "", **_settings(call)}))
    return {**done(got), "id": _created(call, got, c.CREATED)}


async def trip_change(call: Call) -> dict[str, Any]:
    trip = _trip(call)
    values = _settings(call)
    if "title" in values and not values["title"].strip():
        raise Denied(400, "Un voyage a un titre.", {"title": "un titre"})
    if not values:
        raise Denied(400, "Rien à changer : title, start, mode ou avoid.")
    return done(await call.act("trips.modifier", form(fixed={"trip": trip.id}, **values)))


async def trip_remove(call: Call) -> dict[str, Any]:
    trip = _trip(call)
    return done(await call.act("trips.supprimer", form(fixed={"trip": trip.id})))


def _number(call: Call, name: str, bound: float) -> float:
    got = call.data.get(name)
    if isinstance(got, bool) or not isinstance(got, int | float) or not math.isfinite(got) or abs(got) > bound:
        raise Denied(400, f"« {name} » : un nombre, de -{bound:g} à {bound:g}.", {name: f"de -{bound:g} à {bound:g}"})
    return float(got)


async def stop_add(call: Call) -> dict[str, Any]:
    trip = _trip(call)
    values = {"name": call.arg("name", limit=c.NAME_MAX), "lat": _number(call, "lat", 90),
              "lon": _number(call, "lon", 180), "kind": call.arg("kind", limit=c.KIND_MAX),
              "day": _int(call, "day", 1, 1, c.DAYS_MAX), "index": _int(call, "index", -1, -1, c.STOPS_MAX),
              "note": call.arg("note", limit=c.NOTE_MAX)}
    got = await call.act("trips.ajouter_arret", form(fixed={"trip": trip.id}, **values))
    return {**done(got), "id": _created(call, got, c.STOP_ADDED)}


def _stop_of(call: Call, trip: Trip) -> Stop:
    ident = str(call.request.path_params["stop"])
    found = next((s for s in trip.stops if s.id == ident), None)
    if found is None:
        raise missing()
    return found


async def stop_change(call: Call) -> dict[str, Any]:
    """Déplacer un arrêt (``day``, ``index``), le noter (``note``), ou les deux."""
    trip = _trip(call)
    stop = _stop_of(call, trip)
    moving, noting = "day" in call.data or "index" in call.data, "note" in call.data
    if not moving and not noting:
        raise Denied(400, "« day » et « index » pour le déplacer, « note » pour le noter.")
    fixed = {"trip": trip.id, "stop": stop.id}
    # tout se lit avant le premier geste : un paramètre refusé ne laisse rien à moitié fait
    move = form(fixed=fixed, day=_int(call, "day", stop.day, 1, c.DAYS_MAX),
                index=_int(call, "index", -1, -1, c.STOPS_MAX)) if moving else None
    note = form(fixed=fixed, note=call.arg("note", limit=c.NOTE_MAX)) if noting else None
    answer: dict[str, Any] = {}
    if move is not None:
        answer = done(await call.act("trips.deplacer_arret", move))
    if note is not None:
        nonce = call.nonce()
        # deux gestes d'un même envoi : chacun sa clé, sinon le second passerait pour le premier redit ; audité comme
        # ``call.act`` le fait, depuis son espace
        answer = done(await perform(call.kernel, "trips.noter_arret", note, by=call.me.handle, via=SPACE,
                                    nonce=f"{nonce}:note" if nonce and move is not None else nonce))
    return answer


async def stop_remove(call: Call) -> dict[str, Any]:
    trip = _trip(call)
    stop = _stop_of(call, trip)
    return done(await call.act("trips.retirer_arret", form(fixed={"trip": trip.id, "stop": stop.id})))


def _stop_points(call: Call, trip: Trip) -> list[Any]:
    texts = _texts(call, _refs(trip))
    return [stop_point(s, texts) for s in trip.stops]


async def trip_route(call: Call) -> dict[str, Any]:
    """Les tronçons d'un arrêt au suivant, rangés par le jour où l'on arrive."""
    trip = _trip(call)
    port = _maps(call, "routing")
    points = _stop_points(call, trip)
    call.outbound()
    route: RouteResult | None = None
    arriving: dict[str, tuple[str, RouteLeg]] = {}
    if len(points) >= 2 and all(p is not None for p in points):
        try:
            route = await geo.chain(port, [p.at for p in points], mode=trip.mode, avoid=frozenset(trip.avoid))
        except MapsUnavailable as exc:
            raise _unavailable(exc) from None
        arriving = {trip.stops[i + 1].id: (trip.stops[i].id, leg)
                    for i, leg in enumerate(route.legs[:len(trip.stops) - 1])}
    days = []
    for n, stops in days_of(trip):
        legs = [{"from": arriving[s.id][0], "to": s.id, **_leg(arriving[s.id][1])} for s in stops if s.id in arriving]
        days.append({"n": n, "distance_m": sum(x["distance_m"] for x in legs),
                     "duration_s": sum(x["duration_s"] for x in legs), "legs": legs})
    return {"days": days, "distance_m": route.distance_m if route else 0, "duration_s": route.duration_s if route else 0,
            "has_toll": bool(route and route.has_toll), "has_highway": bool(route and route.has_highway),
            "has_ferry": bool(route and route.has_ferry),
            "provider": route.provider if route is not None else port.routing_provider()}


async def trip_order(call: Call) -> dict[str, Any]:
    """L'ordre optimisé d'un jour, appliqué : son premier et son dernier arrêt restent à leur place."""
    trip = _trip(call)
    day = _int(call, "day", 1, 1, c.DAYS_MAX)
    stops = [s for s in trip.stops if s.day == day]
    if len(stops) < 3:
        return {"ok": True, "message": "Rien à réordonner : il faut trois arrêts ce jour-là.", "deduped": False,
                "order": [s.id for s in stops]}
    if len(stops) > ROUTE_POINTS_MAX:
        # le serveur d'itinéraires ne range pas plus de points d'un coup : refusé en mots, avant de le demander
        raise Denied(400, f"L'ordre se calcule pour {ROUTE_POINTS_MAX} arrêts au plus dans un jour : ce jour en a "
                          f"{len(stops)}. Répartis-les sur deux jours.", {"day": f"{ROUTE_POINTS_MAX} arrêts au plus"})
    port = _maps(call, "routing")
    call.outbound()
    texts = _texts(call, _refs(trip))
    points = [stop_point(s, texts) for s in stops]
    if any(p is None for p in points):
        raise Denied(409, "Un arrêt de ce jour n'a plus ses coordonnées.")
    try:
        got = await port.optimize([p.at for p in points if p is not None], mode=trip.mode)
    except MapsUnavailable as exc:
        raise _unavailable(exc) from None
    order = [stops[i].id for i in _order(got, len(stops))]
    outcome = await call.act("trips.ordonner_jour", form(fixed={"trip": trip.id}, day=day, order=order))
    return {**done(outcome), "order": order}


async def trip_along(call: Call) -> dict[str, Any]:
    """Les lieux le long du trajet (d'un jour, ou de tout le voyage : ``day`` 0) ; ``route`` faux : à vol d'oiseau."""
    trip = _trip(call)
    port = _maps(call, "places")
    category = _category(call, port)
    day = _int(call, "day", 0, 0, c.DAYS_MAX)
    corridor = _int(call, "corridor", CORRIDOR, CORRIDOR_MIN, CORRIDOR_MAX)
    limit = _int(call, "limit", 20, 1, LIMIT_MAX)
    points = along_points(trip, _texts(call, _refs(trip)), day)
    if len(points) < 2:
        return {"places": [], "route": False}
    if port.routing_ready():
        call.outbound()
    line, routed = await geo.follow(port, [p.at for p in points], mode=trip.mode, avoid=frozenset(trip.avoid))
    try:
        hits = await port.along(line, corridor_m=corridor, category=category, limit=limit)
    except MapsUnavailable as exc:
        raise _unavailable(exc) from None
    return {"places": [_hit(h) for h in hits[:limit]], "route": routed}


async def gpx_document(port: Any, trip: Trip, content: Callable[[list[str]], Mapping[str, str]],
                       outbound: Callable[[], None]) -> str:
    """Le voyage en GPX (``adapters.maps.gpx``) : ses arrêts, et le tracé quand les itinéraires le calculent (sinon,
    ou en panne, ses arrêts seuls). ``content`` lit ses textes au magasin ; ``outbound``, appelé avant de joindre le
    serveur d'itinéraires, y compte la demande dans la borne du compte qui la fait (``OUTBOUND``) et lève au-delà —
    jamais facultatif : la console sert le même document, sur la fiche de la personne, dans la même borne (ADR 0204)."""
    texts = content(_refs(trip))
    stops = [(texts.get(s.name_ref, ""), p.lat, p.lon) for s in trip.stops if (p := stop_point(s, texts)) is not None]
    track: list[geo.Point] = []
    if port is not None and port.routing_ready() and len(stops) >= 2:
        outbound()
        try:
            track = await geo.line_of_async(await geo.chain(port, [(lat, lon) for _, lat, lon in stops],
                                                            mode=trip.mode, avoid=frozenset(trip.avoid)))
        except MapsUnavailable:
            track = []  # les arrêts seuls : le GPX reste utile
    # un long tracé s'écrit hors de la boucle d'événements (des centaines de milliers de points sur un long voyage)
    title = texts.get(trip.title_ref, "")
    return gpx(title, stops, track) if len(track) <= geo.LINE_KEPT * 4 else \
        await asyncio.to_thread(gpx, title, stops, track)


def gpx_response(trip: Trip, body: str) -> Response:
    """Le GPX d'un voyage, en pièce jointe ``voyage-<id>.gpx``, jamais gardé en cache."""
    return Response(body, media_type="application/gpx+xml",
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                             "Content-Disposition": f'attachment; filename="voyage-{trip.id}.gpx"'})


async def trip_gpx(call: Call) -> Response:
    """Le voyage en GPX : ses arrêts, et le tracé quand les itinéraires le calculent."""
    trip = _trip(call)
    return gpx_response(trip, await gpx_document(call.port("maps"), trip, lambda refs: _texts(call, refs),
                                                 call.outbound))


def routes(api: MeApi) -> list[Route]:
    r = api.route
    trip, stop = VOYAGES + "/{trip}", VOYAGES + "/{trip}/arrets/{stop}"
    return [r(CARTE, info), r(CARTE + "/lieux", places), r(CARTE + "/adresses", addresses),
            r(CARTE + "/itineraire", itinerary), r(CARTE + "/ordre", best_order), r(CARTE + "/le-long", along),
            r(CARTE + "/regards/{seq:int}", look),
            r(VOYAGES, trips_list), r(VOYAGES, trip_create, write=True),
            r(trip, trip_read), r(trip, trip_change, write=True), r(trip + "/supprimer", trip_remove, write=True),
            r(trip + "/arrets", stop_add, write=True), r(stop, stop_change, write=True),
            r(stop + "/retirer", stop_remove, write=True), r(trip + "/trajet", trip_route),
            r(trip + "/ordre", trip_order, write=True), r(trip + "/sur-la-route", trip_along),
            r(trip + "/gpx", trip_gpx, raw=True)]
