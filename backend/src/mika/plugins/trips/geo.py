"""La géométrie des voyages, sans un mot : des coordonnées lues et écrites, des distances, des tracés résumés, et un
trajet calculé d'un bout à l'autre quand il a plus de points qu'une requête n'en prend.

Pur, sauf ``chain`` qui demande au port de la carte (``mika.ports.maps``) : le plugin et l'API par personne s'en
servent tous les deux.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Sequence

from mika.ports.maps import (
    ROUTE_POINTS_MAX,
    MapsPort,
    MapsUnavailable,
    RouteResult,
    decode_polyline6,
    encode_polyline6,
)

Point = tuple[float, float]

#: « 45.764043,4.835659 », « 45.76, 4.83 » : deux nombres, une virgule entre eux
_COORDS = re.compile(r"^\s*([+-]?\d{1,3}(?:\.\d+)?)\s*,\s*([+-]?\d{1,3}(?:\.\d+)?)\s*$")
#: le rayon moyen de la Terre, en mètres
EARTH_M = 6_371_000.0
#: ce qu'un regard garde d'un tracé (des points), ce qu'on donne au port pour chercher le long d'un trajet
SHAPE_KEPT = 200
LINE_KEPT = 1_000
#: un tracé plus long (en caractères encodés, quelques milliers de points) se décode hors de la boucle d'événements :
#: un long voyage en fait des centaines de milliers, qui figeraient le chat et les autres requêtes
DECODE_THREAD_CHARS = 20_000


def valid(lat: float, lon: float) -> bool:
    return math.isfinite(lat) and math.isfinite(lon) and -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def coords_text(lat: float, lon: float) -> str:
    """Ce qu'un contenu garde d'un point : « latitude,longitude », six décimales (une dizaine de centimètres)."""
    return f"{lat:.6f},{lon:.6f}"


def parse_coords(text: str | None) -> Point | None:
    """Un point écrit « latitude,longitude » ; ``None`` s'il n'en est pas un (ou hors des bornes)."""
    found = _COORDS.match(text or "")
    if found is None:
        return None
    lat, lon = float(found.group(1)), float(found.group(2))
    return (lat, lon) if valid(lat, lon) else None


def distance_m(a: Point, b: Point) -> float:
    """La distance à vol d'oiseau, en mètres (haversine)."""
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_M * math.asin(min(1.0, math.sqrt(h)))


def box(center: Point, radius_m: float) -> tuple[float, float, float, float]:
    """La zone (ouest, sud, est, nord) qui contient le cercle de ce rayon autour de ce point."""
    lat, lon = center
    dlat = radius_m / 111_320.0
    dlon = radius_m / max(1.0, 111_320.0 * math.cos(math.radians(lat)))
    return (max(-180.0, lon - dlon), max(-90.0, lat - dlat), min(180.0, lon + dlon), min(90.0, lat + dlat))


def thin(points: Sequence[Point], most: int) -> list[Point]:
    """Au plus ``most`` points d'une ligne, pris à intervalles réguliers, ses deux bouts gardés."""
    if len(points) <= most or most < 2:
        return list(points)
    step = (len(points) - 1) / (most - 1)
    return [points[round(i * step)] for i in range(most)]


def line_of(route: RouteResult) -> list[Point]:
    """Le tracé d'un trajet, d'un bout à l'autre (ses tronçons mis bout à bout) ; un tronçon illisible manque."""
    out: list[Point] = []
    for leg in route.legs:
        try:
            points = decode_polyline6(leg.shape)
        except ValueError:
            continue
        if out and points and points[0] == out[-1]:
            points = points[1:]
        out.extend(points)
    return out


async def line_of_async(route: RouteResult) -> list[Point]:
    """``line_of``, dans un fil à part quand le tracé est long (``DECODE_THREAD_CHARS``)."""
    if sum(len(leg.shape) for leg in route.legs) <= DECODE_THREAD_CHARS:
        return line_of(route)
    return await asyncio.to_thread(line_of, route)


async def summary(route: RouteResult) -> str:
    """Un tracé résumé (``SHAPE_KEPT`` points), encodé : ce qu'une carte miniature dessine."""
    return encode_polyline6(thin(await line_of_async(route), SHAPE_KEPT))


async def chain(port: MapsPort, points: Sequence[Point], *, mode: str, avoid: frozenset[str]) -> RouteResult:
    """Le trajet d'un point au suivant, jusqu'au dernier : en plusieurs requêtes quand il y a plus de points qu'une
    n'en prend (chacune repart du dernier point de la précédente), ses tronçons dans l'ordre. Moins de deux points :
    ``ValueError`` ; ce que le port dit d'un échec (``MapsUnavailable``) remonte."""
    if len(points) < 2:
        raise ValueError("un trajet a au moins deux points")
    legs, toll, highway, ferry, provider = [], False, False, False, ""
    start = 0
    while start < len(points) - 1:
        part = list(points[start:start + ROUTE_POINTS_MAX])
        got = await port.route(part, mode=mode, avoid=avoid)
        legs.extend(got.legs)
        toll, highway, ferry = toll or got.has_toll, highway or got.has_highway, ferry or got.has_ferry
        provider = got.provider or provider
        start += len(part) - 1
    return RouteResult(sum(leg.distance_m for leg in legs), sum(leg.duration_s for leg in legs), tuple(legs),
                       toll, highway, ferry, provider)


async def follow(port: MapsPort, points: Sequence[Point], *, mode: str,
                 avoid: frozenset[str]) -> tuple[list[Point], bool]:
    """La ligne le long de laquelle chercher des lieux : le trajet quand les itinéraires le calculent (résumé à
    ``LINE_KEPT`` points), sinon les points reliés à vol d'oiseau — et si c'est le trajet."""
    if port.routing_ready() and len(points) >= 2:
        try:
            line = await line_of_async(await chain(port, points, mode=mode, avoid=avoid))
        except MapsUnavailable:
            line = []
        if len(line) >= 2:
            return thin(line, LINE_KEPT), True
    return list(points), False


def km_text(meters: float) -> str:
    """« 800 m », « 5,8 km », « 152 km »."""
    if meters < 1_000:
        return f"{round(meters / 10) * 10:.0f} m"
    km = meters / 1_000
    return f"{km:.1f} km".replace(".", ",") if km < 10 else f"{km:.0f} km"


def duration_text(seconds: float) -> str:
    """« 25 min », « 1 h 05 », « 7 h »."""
    minutes = max(1, round(seconds / 60))
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest:02d}" if rest else f"{hours} h"
