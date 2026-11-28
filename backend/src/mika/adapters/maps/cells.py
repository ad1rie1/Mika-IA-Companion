"""La grille des caches de la carte (ADR 0245) : la France découpée en cases d'à peu près ``size_km`` de côté. Un
service qu'on met en cache (DATAtourisme, Google Places) s'interroge sur une case entière — jamais sur la position
exacte de la personne — et garde ce qu'il a rendu avec la date de la case.

Une case est une bande de latitude (``size_km`` de haut) coupée en colonnes de la même largeur au centre de la
bande : la même position tombe toujours dans la même case, et une case a la même clé d'un redémarrage à l'autre
(``key`` : ``<taille>:<ligne>:<colonne>``)."""

from __future__ import annotations

import math
from dataclasses import dataclass

#: kilomètres par degré de latitude (sphère de rayon moyen)
KM_PER_DEG = 6_371.0088 * math.pi / 180


@dataclass(frozen=True, slots=True)
class Cell:
    key: str
    south: float
    west: float
    north: float
    east: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.south + self.north) / 2, (self.west + self.east) / 2

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """Ouest, sud, est, nord (l'ordre des zones du port)."""
        return self.west, self.south, self.east, self.north


def _steps(size_km: float, row: int) -> tuple[float, float]:
    dlat = size_km / KM_PER_DEG
    middle = (row + 0.5) * dlat
    return dlat, dlat / max(0.2, math.cos(math.radians(middle)))


def cell_of(lat: float, lon: float, size_km: float) -> Cell:
    """La case de ce point."""
    size = max(1.0, float(size_km))
    dlat = size / KM_PER_DEG
    row = math.floor(lat / dlat)
    _dlat, dlon = _steps(size, row)
    col = math.floor(lon / dlon)
    return Cell(f"{size:g}:{row}:{col}", round(row * dlat, 6), round(col * dlon, 6), round((row + 1) * dlat, 6),
                round((col + 1) * dlon, 6))


def neighbours(cell: Cell, size_km: float) -> list[Cell]:
    """Les cases tout autour (huit, ou moins près d'un pôle), sans elle."""
    lat, lon = cell.center
    dlat, dlon = cell.north - cell.south, cell.east - cell.west
    out: dict[str, Cell] = {}
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            if di or dj:
                other = cell_of(lat + di * dlat, lon + dj * dlon, size_km)
                if other.key != cell.key:
                    out.setdefault(other.key, other)
    return list(out.values())


def cells_in(bbox: tuple[float, float, float, float], size_km: float, most: int) -> list[Cell] | None:
    """Les cases qui couvrent une zone (ouest, sud, est, nord) ; plus de ``most`` : ``None`` (une zone trop grande)."""
    w, s, e, n = bbox
    size = max(1.0, float(size_km))
    dlat = size / KM_PER_DEG
    out: dict[str, Cell] = {}
    for row in range(math.floor(s / dlat), math.floor(n / dlat) + 1):
        _dlat, dlon = _steps(size, row)
        lat = (row + 0.5) * dlat
        for col in range(math.floor(w / dlon), math.floor(e / dlon) + 1):
            cell = cell_of(lat, (col + 0.5) * dlon, size)
            out.setdefault(cell.key, cell)
            if len(out) > most:
                return None
    return list(out.values())


def distance_km(cell: Cell, lat: float, lon: float) -> float:
    """De ce point au plus près de la case (0 : il est dedans), à plat — assez juste à l'échelle d'une case."""
    dlat = max(cell.south - lat, 0.0, lat - cell.north)
    dlon = max(cell.west - lon, 0.0, lon - cell.east)
    return math.hypot(dlat * KM_PER_DEG, dlon * KM_PER_DEG * math.cos(math.radians(lat)))


def cells_near(lat: float, lon: float, radius_km: float, size_km: float, most: int) -> list[Cell] | None:
    """Les cases que touche le cercle de ce point (ADR 0259), la sienne d'abord, puis les plus proches ; plus de
    ``most`` : ``None`` (un rayon trop grand pour les compter)."""
    radius = max(0.0, float(radius_km))
    dlat = radius / KM_PER_DEG
    dlon = dlat / max(0.01, math.cos(math.radians(lat)))
    found = cells_in((lon - dlon, lat - dlat, lon + dlon, lat + dlat), size_km, most * 2)
    if found is None:
        return None
    near = sorted(((distance_km(c, lat, lon), c.key, c) for c in found if distance_km(c, lat, lon) <= radius),
                  key=lambda item: item[:2])
    return [c for _d, _k, c in near] if len(near) <= most else None
