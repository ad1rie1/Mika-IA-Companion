"""Les réglages de la carte (ADR 0193, 0194, 0245, 0256, 0310) : d'où viennent les tuiles de la carte de sa position,
l'index des lieux et les adresses, les itinéraires, les données touristiques (DATAtourisme), le réchauffage du soir de
ses caches et les avis (Google Places).

Rangés dans les réglages du serveur (``mind.db``), par leur porte (``app/settings.py::SettingsPart``) : chaque
écriture s'y dit. Les clés des API de DATAtourisme et de Google y sont scellées.
"""

from __future__ import annotations

from mika.adapters.maps import (
    MapConfig,
    PlacesConfig,
    ReviewsConfig,
    RoutingConfig,
    TourismConfig,
    WarmConfig,
)
from mika.app.settings import SettingsPart

#: d'où vient la carte de sa position (ADR 0193)
MAP_KEY = "carte"
#: l'index des lieux et les adresses, les itinéraires de l'écran Carte (ADR 0194)
PLACES_KEY = "lieux"
ROUTING_KEY = "itineraires"
#: les données touristiques de DATAtourisme (ADR 0245) : la clé de son API scellée, les zones, l'horizon, la nuit
TOURISM_KEY = "tourisme"
#: le réchauffage du soir des caches de la carte (ADR 0245) : son heure, autour de qui, des points fixes
WARM_KEY = "rechauffage"
#: les avis de Google Places (ADR 0256) : la clé de son API scellée, les bornes, la durée du cache, la case
REVIEWS_KEY = "avis"


class MapsSettings(SettingsPart):
    # ── La carte de sa position (ADR 0193) ──
    def map_config(self) -> MapConfig:
        """D'où viennent ses tuiles ; un réglage illisible (gardé avant une règle plus stricte) : aucune carte, le
        plan dessiné."""
        try:
            return MapConfig.model_validate(self._get(MAP_KEY) or {})
        except ValueError:
            return MapConfig()

    async def save_map_config(self, cfg: MapConfig) -> None:
        await self._put(MAP_KEY, cfg.model_dump(mode="json"))

    # ── Les lieux, les adresses et les itinéraires de l'écran Carte (ADR 0194) ──
    def places_config(self) -> PlacesConfig:
        """L'index des lieux et les adresses ; un réglage illisible : les défauts (l'index sous cartes/, aucune
        adresse : rien ne sort)."""
        try:
            return PlacesConfig.model_validate(self._get(PLACES_KEY) or {})
        except ValueError:
            return PlacesConfig()

    async def save_places_config(self, cfg: PlacesConfig) -> None:
        await self._put(PLACES_KEY, cfg.model_dump(mode="json"))

    def routing_config(self) -> RoutingConfig:
        """Qui calcule les itinéraires ; un réglage illisible : aucun (rien ne sort)."""
        try:
            return RoutingConfig.model_validate(self._get(ROUTING_KEY) or {})
        except ValueError:
            return RoutingConfig()

    async def save_routing_config(self, cfg: RoutingConfig) -> None:
        await self._put(ROUTING_KEY, cfg.model_dump(mode="json"))

    # ── Les données touristiques de l'écran Carte (DATAtourisme, ADR 0245) ──
    def tourism_config(self) -> TourismConfig:
        """La clé (déchiffrée), les zones, l'horizon, l'heure de nuit et les bornes ; un réglage illisible : les
        défauts (aucune clé : rien ne se synchronise)."""
        data = dict(self._get(TOURISM_KEY) or {})
        key = self.box.open(str(data.pop("api_key_sealed", "") or ""))
        try:
            return TourismConfig.model_validate({**data, "api_key": key})
        except ValueError:
            return TourismConfig(api_key=key)

    async def save_tourism_config(self, cfg: TourismConfig) -> None:
        data = cfg.model_dump(mode="json")
        data["api_key_sealed"] = self.box.seal(data.pop("api_key"))
        await self._put(TOURISM_KEY, data)

    def warm_config(self) -> WarmConfig:
        """Le réchauffage du soir des caches de la carte ; un réglage illisible : les défauts (22:00, autour des
        personnes)."""
        try:
            return WarmConfig.model_validate(self._get(WARM_KEY) or {})
        except ValueError:
            return WarmConfig()

    async def save_warm_config(self, cfg: WarmConfig) -> None:
        await self._put(WARM_KEY, cfg.model_dump(mode="json"))

    # ── Les avis de l'écran Carte (Google Places, ADR 0256) ──
    def reviews_config(self) -> ReviewsConfig:
        """La clé (déchiffrée), les bornes des demandes, la durée du cache, la case ; un réglage illisible : les
        défauts, la clé gardée (rien ne part sans elle)."""
        data = dict(self._get(REVIEWS_KEY) or {})
        key = self.box.open(str(data.pop("api_key_sealed", "") or ""))
        try:
            return ReviewsConfig.model_validate({**data, "api_key": key})
        except ValueError:
            return ReviewsConfig(api_key=key)

    async def save_reviews_config(self, cfg: ReviewsConfig) -> None:
        data = cfg.model_dump(mode="json")
        data["api_key_sealed"] = self.box.seal(data.pop("api_key"))
        await self._put(REVIEWS_KEY, data)


#: la classe que le cadre prend par le nom du domaine (``Settings.named``)
SETTINGS = MapsSettings
