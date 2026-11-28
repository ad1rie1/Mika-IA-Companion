"""Le câblage de la carte (ADR 0193, 0194, 0245, 0256, 0310) : le port ``maps`` du noyau (``MapsDesk`` : les lieux,
les adresses, les itinéraires, les données touristiques, les avis, et le réchauffage du soir de leurs caches autour
de la dernière position de chacun) et les tuiles de la carte de sa position (``MapTiles``), que l'API par personne
sert. Dans le cycle de vie, le réchauffage démarre (``start``) et s'arrête (``stop``) ; les tuiles puis le port se
ferment en dernier (``release``)."""

from __future__ import annotations

from mika.adapters.maps import MapsDesk, MapTiles
from mika.app.domains.maps.settings import MapsSettings
from mika.app.domains.maps.warm_points import last_positions
from mika.app.wiring import Wiring

NAME = "maps"
#: les tuiles de la carte de sa position (ADR 0193) : sous ce nom dans ``w.parts``, et pour l'API par personne
#: (``MeApiBase.tiles``)
TILES = "tiles"


def wire(w: Wiring) -> None:
    """Avant le noyau : le port ``maps`` et les tuiles. Les points du réchauffage se lisent au noyau, qui n'existe pas
    encore : il est pris à l'usage (``w.port``, posé avant ``bind``)."""
    settings = w.settings.of(MapsSettings)
    # les lieux, les adresses et les itinéraires de l'écran Carte et de ses outils (ADR 0194) : l'index des lieux de
    # ``cartes/``, la Géoplateforme, Valhalla ; les données touristiques et les événements de DATAtourisme, dans
    # ``cartes/tourisme.db`` (ADR 0245) ; les avis de Google Places, dans ``cartes/avis.db`` (ADR 0256) — réglés dans la
    # console, relus à chaque usage ; chaque soir, leurs caches se réchauffent autour de la dernière position de chacun
    # (``warm_points``)
    w.ports[NAME] = w.parts[NAME] = MapsDesk(w.data, settings.places_config, settings.routing_config,
                                             tourism=settings.tourism_config, reviews=settings.reviews_config,
                                             warm=settings.warm_config,
                                             warm_points=lambda: last_positions(w.port.kernel, w.store, w.clock.now))
    # la carte de sa position (ADR 0193) : ses tuiles, lues ou relayées par ce serveur
    w.parts[TILES] = w.me[TILES] = MapTiles(w.data, settings.map_config)


async def start(w: Wiring) -> None:
    w.parts[NAME].start()  # le réchauffage des caches de la carte, les départements tenus en entier (ADR 0245)


async def stop(w: Wiring) -> None:
    await w.parts[NAME].stop()


async def release(w: Wiring) -> None:
    await w.parts[TILES].close()
    await w.parts[NAME].close()
