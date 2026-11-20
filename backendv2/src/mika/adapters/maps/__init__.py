"""La carte de sa position (ADR 0193) : d'où viennent ses tuiles (``MapConfig``, réglé dans la console) et ce qui les
lit ou les relaie (``MapTiles``). Le navigateur ne parle qu'à ce serveur.

Et l'écran Carte (ADR 0194) : les lieux d'un index local (``places``), les adresses de la Géoplateforme
(``geocode``), les itinéraires de Valhalla (``routing``) — le port ``maps`` du noyau (``MapsDesk``), réglé dans la
console (``PlacesConfig``, ``RoutingConfig``).

Et les données touristiques (ADR 0245) : une base des lieux et des événements de DATAtourisme, un cache par cases
(``tourism``, ``tourism_cells``, ``datatourisme`` ; en option, des départements entiers : ``tourism_sync``), réglée
dans la console (``TourismConfig``) ; ce que partagent les caches de la carte : la grille (``cells``), le limiteur
(``quota``), le réchauffage du soir (``warm``, ``WarmConfig``) et le relais des photos (``photos``).

Et les avis (ADR 0250, 0256) : un cache de Google Places par cases (``reviews``, ``reviews_cells``, le client de son
API officielle ``google_places``), réglé dans la console (``ReviewsConfig``)."""

from mika.adapters.maps.config import (
    FILE,
    IMAGE,
    MAPS_DIR,
    NONE,
    SERVER,
    VECTOR,
    MapConfig,
    PlacesConfig,
    ReviewsConfig,
    RoutingConfig,
    TourismConfig,
    WarmConfig,
)
from mika.adapters.maps.desk import MapsDesk
from mika.adapters.maps.routing import gpx
from mika.adapters.maps.tiles import MapInfo, MapTiles, MapUnavailable, Tile

__all__ = ["FILE", "IMAGE", "MAPS_DIR", "NONE", "SERVER", "VECTOR", "MapConfig", "MapInfo", "MapTiles",
           "MapUnavailable", "MapsDesk", "PlacesConfig", "ReviewsConfig", "RoutingConfig", "Tile", "TourismConfig",
           "WarmConfig", "gpx"]
