"""Les points du réchauffage des caches de la carte (ADR 0245) : la dernière position que le téléphone de chaque
personne a donnée, si elle l'a permis (le plugin ``location``, ADR 0119). L'adaptateur de la carte n'importe ni plugin
ni faculté : la composition lit la tranche de la localisation et lui passe les points. Seuls des points en sortent ;
le réchauffage n'envoie au service que leur case."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mika.plugins import location as location_p
from mika.plugins.trips import geo

#: une position plus vieille ne compte plus (la personne est sans doute ailleurs)
RECENT_DAYS = 30
US_PER_DAY = 86_400 * 1_000_000


def last_positions(kernel: Any, store: Any, now_us: Callable[[], int]) -> list[tuple[float, float]]:
    """Les dernières positions des personnes (une par adresse qui en a donné une, des trente derniers jours), lues
    au journal ; leurs coordonnées sont des contenus, lus à la demande."""
    try:
        state = kernel.mind.frame().state(location_p.LOCATION.name)
    except (KeyError, AttributeError):  # la localisation n'est pas composée
        return []
    since = now_us() - RECENT_DAYS * US_PER_DAY
    fixes = [f for f in getattr(state, "fixes", {}).values() if f.fixed_at >= since and f.coords_ref]
    if not fixes:
        return []
    texts = store.content([f.coords_ref for f in fixes])
    points = (geo.parse_coords(texts.get(f.coords_ref)) for f in fixes)
    return [p for p in points if p is not None]
