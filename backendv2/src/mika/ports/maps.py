"""Le port de la carte (ADR 0194) : chercher un lieu dans l'index local, une adresse à la Géoplateforme, calculer un
itinéraire au serveur réglé (Valhalla). Ce que la personne voit dans l'écran Carte, et ce dont Mika se sert en lui
parlant, passe par ici.

Les lieux se cherchent dans l'index du dossier de données : rien ne sort. Une adresse ne fait partir que le texte
cherché, jamais la position de la personne ; un itinéraire, que ses points. ``MapsUnavailable`` dit en mots ce qui
manque (rien de réglé, un serveur qui ne répond pas, aucun chemin).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

#: comment on va d'un point à l'autre ; ce qu'un trajet peut éviter
MODES = ("voiture", "velo", "pied")
AVOIDS = ("peages", "autoroutes", "ferries")
#: les points d'un trajet, départ et arrivée compris
ROUTE_POINTS_MAX = 20


class MapsUnavailable(Exception):
    """Ce qui manque, en une phrase qu'on peut montrer à la personne comme à elle."""


@dataclass(frozen=True, slots=True)
class PlaceHit:
    """Un lieu trouvé. ``id`` : ``l<n>`` (l'index local, qui change à chaque reconstruction : un arrêt garde son nom et
    ses coordonnées) ou ``a:<n>`` (une adresse de cette réponse). ``distance_m`` : depuis le point donné, ou jusqu'au
    trajet pour ``along`` ; ``along_m`` : où on le croise, depuis le départ."""

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

    def addresses_ready(self) -> bool: ...

    def routing_ready(self) -> bool: ...

    def routing_provider(self) -> str: ...

    async def search(self, text: str, *, near: tuple[float, float] | None = None,
                     bbox: tuple[float, float, float, float] | None = None, category: str = "",
                     limit: int = 20) -> list[PlaceHit]:
        """Dans l'index local : par le nom (et la ville), d'une catégorie, près d'un point (lat, lon) ou dans une
        zone (ouest, sud, est, nord). Sans texte : les plus proches."""
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
