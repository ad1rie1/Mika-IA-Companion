"""La géométrie de la carte : la distance entre deux points, la boîte autour d'un point ou d'un segment (ouest, sud,
est, nord). Des fonctions pures, sans SQL : l'index des lieux (``places.py``), les données touristiques
(``tourism.py``), les avis (``reviews_cells.py``) et le guichet (``desk.py``) les partagent."""

from __future__ import annotations

import math

#: mètres par degré de latitude (sphère de rayon moyen)
M_PER_DEG = 6_371_008.8 * math.pi / 180


def meters_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(min(1.0, math.sqrt(a)))


def widened_box(south: float, west: float, north: float, east: float, margin_m: float) -> tuple[float, float, float, float]:
    """Ouest, sud, est, nord d'une boîte élargie de ``margin_m`` de chaque côté — en longitude, à la latitude où un
    degré est le plus court (la marge n'y manque nulle part)."""
    dlat = margin_m / M_PER_DEG
    cos = max(0.01, min(math.cos(math.radians(south)), math.cos(math.radians(north))))
    dlon = margin_m / (M_PER_DEG * cos)
    return west - dlon, max(-90.0, south - dlat), east + dlon, min(90.0, north + dlat)


def box_around(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """Ouest, sud, est, nord autour d'un point."""
    return widened_box(lat, lon, lat, lon, radius_m)
