"""Les itinéraires (ADR 0194) : un serveur Valhalla — le public de FOSSGIS, relayé par ce serveur, ou le tien (sur le
portable : ``deploy/README.md``) —, en voiture, à vélo ou à pied, péages, autoroutes ou ferries évitables, consignes
en français, le meilleur ordre des arrêts, et le GPX d'un voyage. Vers lui ne partent que les points du trajet.

Le serveur de FOSSGIS demande au plus une demande par seconde, pour tout ce serveur (``FOSSGIS_PACE``, partagé par
tout le processus), et ne garantit rien ; chaque trajet calculé est gardé un jour (``CACHE_SIZE`` trajets) : un
trajet redemandé ne repart pas, et deux demandes du même trajet en même temps n'en font qu'une."""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from typing import Any
from xml.sax.saxutils import escape, quoteattr

import httpx

from mika.adapters.maps.config import FOSSGIS, FOSSGIS_PER_SECOND, NO_ROUTING, VALHALLA, RoutingConfig
from mika.adapters.maps.pace import Pace, client
from mika.adapters.maps.tiles import USER_AGENT, read_capped
from mika.ports.maps import (
    AVOIDS,
    MODES,
    ROUTE_POINTS_MAX,
    Maneuver,
    MapsUnavailable,
    RouteLeg,
    RouteResult,
    decode_polyline6,
    encode_polyline6,
)
from mika.ports.preprocess import inert

__all__ = ["CACHE_SIZE", "FOSSGIS_PACE", "Router", "decode_polyline6", "encode_polyline6", "gpx"]

TIMEOUT_S = 20.0
CACHE_SIZE = 128
CACHE_TTL_S = 86_400.0
RESPONSE_MAX_BYTES = 16 * 1024 * 1024
#: comment chaque mode se dit chez Valhalla
COSTING = {"voiture": "auto", "velo": "bicycle", "pied": "pedestrian"}
MODE_FR = {"voiture": "en voiture", "velo": "à vélo", "pied": "à pied"}
NOT_SET = "Les itinéraires ne sont pas réglés : Réglages › Canaux › Itinéraires."
BUSY = "Le serveur d'itinéraires est très demandé : réessaie dans un instant."
#: le Valhalla public de FOSSGIS : une demande par seconde au plus, pour tout le processus
FOSSGIS_PACE = Pace(FOSSGIS_PER_SECOND, wait_max=20.0, busy=BUSY)
#: un tracé encodé (polyline) : des caractères de « ? » à « ~ »
_POLYLINE = re.compile(r"[?-~]*")


def _check(points: Sequence[tuple[float, float]], mode: str,
           avoid: frozenset[str] = frozenset()) -> list[tuple[float, float]]:
    """Les points d'un trajet (lat, lon), arrondis comme le tracé (six décimales) ; ce qui ne va pas : ``ValueError``,
    en mots (les appelants vérifient avant : c'est une erreur de programmation)."""
    if mode not in MODES:
        raise ValueError(f"un mode : {', '.join(MODES)}")
    if not avoid <= set(AVOIDS):
        raise ValueError(f"ce qu'un trajet évite : {', '.join(AVOIDS)}")
    if not 2 <= len(points) <= ROUTE_POINTS_MAX:
        raise ValueError(f"un trajet va de 2 à {ROUTE_POINTS_MAX} points")
    out = []
    for lat, lon in points:
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("un point : une latitude entre -90 et 90, une longitude entre -180 et 180")
        out.append((round(float(lat), 6), round(float(lon), 6)))
    return out


def _body(points: Sequence[tuple[float, float]], mode: str, avoid: frozenset[str]) -> dict[str, Any]:
    costing = COSTING[mode]
    options: dict[str, float] = {}
    if "peages" in avoid and mode == "voiture":
        options["use_tolls"] = 0
    if "autoroutes" in avoid and mode == "voiture":
        options["use_highways"] = 0
    if "ferries" in avoid:
        options["use_ferry"] = 0
    body: dict[str, Any] = {"locations": [{"lat": lat, "lon": lon, "type": "break"} for lat, lon in points],
                            "costing": costing,
                            "directions_options": {"units": "kilometers", "language": "fr-FR"}}
    if options:
        body["costing_options"] = {costing: options}
    return body


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError("un nombre")
    return float(value)


def _route(data: object, provider: str) -> RouteResult:
    """Un trajet de Valhalla (``trip`` : ses tronçons, leur tracé encodé, leurs consignes ; longueurs en km)."""
    trip = data.get("trip") if isinstance(data, dict) else None
    if not isinstance(trip, dict) or not isinstance(trip.get("legs"), list) or not trip["legs"]:
        raise ValueError("pas de trajet")
    legs = []
    for leg in trip["legs"]:
        summary, shape = leg.get("summary"), leg.get("shape")
        if not isinstance(summary, dict) or not isinstance(shape, str) or not _POLYLINE.fullmatch(shape):
            raise ValueError("un tronçon illisible")
        steps = []
        for m in leg.get("maneuvers") or ():
            if isinstance(m, dict) and isinstance(m.get("instruction"), str):
                km, seconds = _number(m.get("length", 0)), _number(m.get("time", 0))
                steps.append(Maneuver(text=inert(m["instruction"], 300), distance_m=round(km * 1000),
                                      duration_s=round(seconds)))
        legs.append(RouteLeg(distance_m=round(_number(summary.get("length")) * 1000),
                             duration_s=round(_number(summary.get("time"))), shape=shape, steps=tuple(steps)))
    total = trip.get("summary")
    if not isinstance(total, dict):
        raise ValueError("pas de résumé")
    return RouteResult(distance_m=round(_number(total.get("length")) * 1000),
                       duration_s=round(_number(total.get("time"))), legs=tuple(legs),
                       has_toll=bool(total.get("has_toll")), has_highway=bool(total.get("has_highway")),
                       has_ferry=bool(total.get("has_ferry")), provider=provider)


def _order(data: object, count: int) -> list[int]:
    """L'ordre d'un trajet optimisé : les indices d'origine (``trip.locations[].original_index``)."""
    trip = data.get("trip") if isinstance(data, dict) else None
    locations = trip.get("locations") if isinstance(trip, dict) else None
    if not isinstance(locations, list):
        raise ValueError("pas d'ordre")
    order = [loc.get("original_index") for loc in locations if isinstance(loc, dict)]
    if sorted(o for o in order if isinstance(o, int)) != list(range(count)) or len(order) != count:
        raise ValueError("un ordre qui ne reprend pas chaque point une fois")
    return [int(o) for o in order]


def _refused(data: object, mode: str) -> str:
    """Un refus de Valhalla (HTTP 400, ``error_code``), dit en mots."""
    code = data.get("error_code") if isinstance(data, dict) else None
    if code in (170, 442):
        return f"Aucun chemin {MODE_FR[mode]} ne relie ces points."
    if code == 171:
        return "Un des points est trop loin d'une route ou d'un chemin."
    if code == 154:
        return "Ce trajet est trop long pour ce serveur d'itinéraires : coupe-le en étapes."
    if code == 150:
        return "Trop de points pour ce serveur d'itinéraires."
    said = data.get("error") if isinstance(data, dict) else None
    return "Le serveur d'itinéraires refuse ce trajet" + (f" ({inert(said, 160)})." if isinstance(said, str) else ".")


class Router:
    """Les itinéraires du serveur réglé (``config`` relu à chaque fois : la console le change sans redémarrer)."""

    def __init__(self, config: Callable[[], RoutingConfig], *, transport: httpx.AsyncBaseTransport | None = None,
                 pace: Pace | None = None, now: Callable[[], float] = time.monotonic) -> None:
        self.config = config
        self._transport = transport
        self._pace = pace
        self._now = now
        self._own: tuple[tuple[str, float], Pace] | None = None
        self._client: httpx.AsyncClient | None = None
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._pending: dict[str, asyncio.Future[Any]] = {}
        #: depuis le démarrage, pour la console
        self.asked = 0
        self.cached = 0
        self.failed = 0
        self.last_error = ""

    def ready(self) -> bool:
        return self.config().source != NO_ROUTING

    def provider(self) -> str:
        source = self.config().source
        return "Valhalla, serveur public de FOSSGIS" if source == FOSSGIS else "Valhalla" if source == VALHALLA \
            else ""

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = client(TIMEOUT_S, self._transport)
        return self._client

    def _turns(self, cfg: RoutingConfig) -> Pace:
        if self._pace is not None:
            return self._pace
        if cfg.source == FOSSGIS:
            return FOSSGIS_PACE
        key = (cfg.base, cfg.rate)
        if self._own is None or self._own[0] != key:
            self._own = (key, Pace(cfg.rate, wait_max=10.0, busy=BUSY))
        return self._own[1]

    async def route(self, points: Sequence[tuple[float, float]], *, mode: str = "voiture",
                    avoid: frozenset[str] = frozenset()) -> RouteResult:
        """D'un point au suivant (lat, lon), départ et arrivée compris : la distance, la durée, chaque tronçon et
        son tracé (polyline à six décimales), les consignes."""
        cfg = self.config()
        avoid = frozenset(avoid)
        body = _body(_check(points, mode, avoid), mode, avoid)
        provider = self.provider()
        return await self._ask(cfg, "/route", body, mode, lambda data: _route(data, provider))

    async def optimize(self, points: Sequence[tuple[float, float]], *, mode: str = "voiture") -> list[int]:
        """Le meilleur ordre de ces points, le départ et l'arrivée fixes : les indices dans l'ordre où passer."""
        cfg = self.config()
        checked = _check(points, mode)
        if len(checked) <= 3:  # rien à ranger entre le départ et l'arrivée
            if cfg.source == NO_ROUTING:
                raise MapsUnavailable(NOT_SET)
            return list(range(len(checked)))
        body = _body(checked, mode, frozenset())
        return list(await self._ask(cfg, "/optimized_route", body, mode, lambda data: _order(data, len(checked))))

    async def _ask(self, cfg: RoutingConfig, endpoint: str, body: dict[str, Any], mode: str,
                   read: Callable[[object], Any]) -> Any:
        if cfg.source == NO_ROUTING:
            raise MapsUnavailable(NOT_SET)
        key = json.dumps([cfg.base, endpoint, body], sort_keys=True)
        kept = self._cache.get(key)
        if kept is not None and self._now() - kept[0] < CACHE_TTL_S:
            self._cache.move_to_end(key)
            self.cached += 1
            return kept[1]
        pending = self._pending.get(key)
        if pending is None:  # le premier le demande ; les autres attendent sa réponse
            pending = asyncio.ensure_future(self._fetch(cfg, endpoint, body, mode, read, key))
            self._pending[key] = pending
            pending.add_done_callback(lambda done, key=key: self._settled(key, done))
        else:
            self.cached += 1
        return await asyncio.shield(pending)

    def _settled(self, key: str, done: asyncio.Future[Any]) -> None:
        self._pending.pop(key, None)
        if not done.cancelled():
            done.exception()  # lue : une demande que plus personne n'attendait ne se plaint pas au journal

    async def _fetch(self, cfg: RoutingConfig, endpoint: str, body: dict[str, Any], mode: str,
                     read: Callable[[object], Any], key: str) -> Any:
        await self._turns(cfg).turn()
        self.asked += 1
        try:
            data = await self._post(cfg.base + endpoint, body, mode)
            try:
                got = read(data)
            except (ValueError, KeyError, TypeError, AttributeError):
                raise MapsUnavailable("Le serveur d'itinéraires a rendu une réponse illisible.") from None
        except MapsUnavailable as exc:
            self.failed += 1
            self.last_error = str(exc)
            raise
        self._cache[key] = (self._now(), got)
        self._cache.move_to_end(key)
        while len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return got

    async def _post(self, url: str, body: dict[str, Any], mode: str) -> object:
        try:
            async with self._http().stream("POST", url, json=body) as r:
                status = r.status_code
                if status == 429:
                    raise MapsUnavailable("Le serveur d'itinéraires demande d'attendre : réessaie dans un instant.")
                if status not in (200, 400):  # 400 : un refus de Valhalla, qui dit pourquoi
                    raise MapsUnavailable(f"Le serveur d'itinéraires a répondu HTTP {status}.")
                raw = await read_capped(r, RESPONSE_MAX_BYTES)
        except httpx.HTTPError as exc:
            raise MapsUnavailable(f"Le serveur d'itinéraires ne répond pas ({type(exc).__name__}).") from None
        except ValueError:
            raise MapsUnavailable("Le serveur d'itinéraires a rendu une réponse démesurée.") from None
        try:
            data = json.loads(raw)
        except ValueError:
            raise MapsUnavailable("Le serveur d'itinéraires a rendu une réponse illisible.") from None
        if status == 400:
            raise MapsUnavailable(_refused(data, mode))
        return data


# ── le GPX d'un voyage ──
_NOT_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def _xml(text: str, limit: int = 200) -> str:
    return escape(_NOT_XML.sub("", " ".join(str(text).split()))[:limit])


def _segments(shape: Sequence[Any]) -> list[list[tuple[float, float]]]:
    """Une suite de points (lat, lon), ou une suite de suites (une par tronçon, par jour) : des segments."""
    if not shape:
        return []
    first = shape[0]
    if len(first) == 2 and all(isinstance(v, int | float) for v in first):
        return [[(float(lat), float(lon)) for lat, lon in shape]]
    return [[(float(lat), float(lon)) for lat, lon in part] for part in shape if part]


def gpx(name: str, stops: Sequence[tuple[str, float, float]],
        shape_points: Sequence[tuple[float, float]] | Sequence[Sequence[tuple[float, float]]] = ()) -> str:
    """Un voyage en GPX 1.1 : ses arrêts dans l'ordre (``<rte>``, chacun son nom), et son tracé (``<trk>``) — une
    suite de points (lat, lon), ou une suite par tronçon ou par jour. Les noms sont échappés."""
    segments = _segments(shape_points)
    title = _xml(name) or "Voyage"
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<gpx version="1.1" creator={quoteattr(USER_AGENT.split(" ")[0])} '
           'xmlns="http://www.topografix.com/GPX/1/1">',
           f"  <metadata><name>{title}</name></metadata>",
           f"  <rte><name>{title}</name>"]
    for stop_name, lat, lon in stops:
        out.append(f'    <rtept lat="{lat:.6f}" lon="{lon:.6f}"><name>{_xml(stop_name)}</name></rtept>')
    out.append("  </rte>")
    if segments:
        out.append(f"  <trk><name>{title}</name>")
        for segment in segments:
            out.append("    <trkseg>")
            out.extend(f'      <trkpt lat="{lat:.6f}" lon="{lon:.6f}"/>' for lat, lon in segment)
            out.append("    </trkseg>")
        out.append("  </trk>")
    out.append("</gpx>")
    return "\n".join(out) + "\n"
