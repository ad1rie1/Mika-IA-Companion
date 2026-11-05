"""Le port ``maps`` du noyau (ADR 0194, ``mika.ports.maps.MapsPort``) : les lieux de l'index local, les adresses de la
Géoplateforme, les itinéraires de Valhalla — ce que l'écran Carte montre (l'API par personne) et ce dont elle se sert
en parlant (le plugin des voyages). Les réglages sont relus à chaque usage : la console les change sans redémarrer.

Les erreurs : ``MapsUnavailable`` dit en mots ce qui manque (rien de réglé, un serveur qui ne répond pas, aucun
chemin) ; ``ValueError``, des arguments hors des bornes du port (un mode inconnu, un point hors du monde) — les
appelants les vérifient avant."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from mika.adapters.maps.config import FOSSGIS, NO_ROUTING, PlacesConfig, RoutingConfig
from mika.adapters.maps.geocode import Geocoder
from mika.adapters.maps.pace import Pace
from mika.adapters.maps.places import LABELS, Places
from mika.adapters.maps.routing import Router
from mika.ports.maps import PlaceHit, RouteResult


class MapsDesk:
    """Les lieux, les adresses et les itinéraires, réglés dans la console (Réglages › Canaux : « Lieux et
    adresses », « Itinéraires »)."""

    def __init__(self, data: Path, places: Callable[[], PlacesConfig], routing: Callable[[], RoutingConfig], *,
                 transport: httpx.AsyncBaseTransport | None = None, routing_pace: Pace | None = None,
                 address_pace: Pace | None = None, now: Callable[[], float] = time.monotonic) -> None:
        self.places = Places(data, places)
        self.geocoder = Geocoder(places, transport=transport, pace=address_pace)
        self.router = Router(routing, transport=transport, pace=routing_pace, now=now)

    async def close(self) -> None:
        await self.geocoder.close()
        await self.router.close()

    # ── le port ──
    def categories(self) -> tuple[tuple[str, str], ...]:
        return LABELS

    def places_ready(self) -> bool:
        return self.places.ready()

    def addresses_ready(self) -> bool:
        return self.geocoder.ready()

    def routing_ready(self) -> bool:
        return self.router.ready()

    def routing_provider(self) -> str:
        return self.router.provider()

    async def search(self, text: str, *, near: tuple[float, float] | None = None,
                     bbox: tuple[float, float, float, float] | None = None, category: str = "",
                     limit: int = 20) -> list[PlaceHit]:
        return await self.places.search(text, near=near, bbox=bbox, category=category, limit=limit)

    async def along(self, line: Sequence[tuple[float, float]], *, corridor_m: int = 10_000, category: str = "",
                    limit: int = 20) -> list[PlaceHit]:
        return await self.places.along(line, corridor_m=corridor_m, category=category, limit=limit)

    async def addresses(self, text: str, *, limit: int = 5) -> list[PlaceHit]:
        return await self.geocoder.search(text, limit=limit)

    async def route(self, points: Sequence[tuple[float, float]], *, mode: str = "voiture",
                    avoid: frozenset[str] = frozenset()) -> RouteResult:
        return await self.router.route(points, mode=mode, avoid=avoid)

    async def optimize(self, points: Sequence[tuple[float, float]], *, mode: str = "voiture") -> list[int]:
        return await self.router.optimize(points, mode=mode)

    # ── en plus du port ──
    async def around(self, lat: float, lon: float, radius_m: float, category: str = "",
                     limit: int = 20) -> list[PlaceHit]:
        """Dans l'index local : à moins de ``radius_m`` de ce point, les plus proches d'abord."""
        return await self.places.around(lat, lon, radius_m, category, limit)

    def places_summary(self) -> dict[str, object]:
        """L'index pour l'écran : ``{"ready", "count", "built"}`` (``built`` : ISO 8601, vide sans index)."""
        return self.places.summary()

    # ── ce que la console en dit ──
    def describe_places(self) -> list[tuple[str, str]]:
        facts = self.places.describe()
        cfg = self.places.config()
        if not self.geocoder.ready():
            facts.append(("Adresses", "aucune : rien ne sort"))
            return facts
        host = urlsplit(cfg.addresses_url).hostname or cfg.addresses_url
        facts.append(("Adresses", f"la Géoplateforme de l'IGN ({host}) : seul le texte cherché part, jamais la "
                                  "position de la personne"))
        if self.geocoder.asked:
            facts.append(("Depuis le démarrage", f"{self.geocoder.asked} recherche(s) d'adresse, "
                                                 f"{self.geocoder.failed} en échec"))
        if self.geocoder.last_error:
            facts.append(("Dernière erreur", self.geocoder.last_error))
        return facts

    def describe_routing(self) -> list[tuple[str, str]]:
        cfg = self.router.config()
        if cfg.source == NO_ROUTING:
            return [("Itinéraires", "aucun : l'écran Carte le dit, rien ne sort")]
        if cfg.source == FOSSGIS:
            facts = [("Itinéraires", "le Valhalla public de FOSSGIS : au plus une demande par seconde pour tout ce "
                                     "serveur, sans garantie qu'il réponde ; seuls les points du trajet partent")]
        else:
            host = urlsplit(cfg.url).netloc or cfg.url
            rate = f"{cfg.per_second:g}".replace(".", ",")
            facts = [("Itinéraires", f"ton Valhalla ({host}) : au plus {rate} demande(s) par seconde ; seuls les "
                                     "points du trajet partent")]
        router = self.router
        if router.asked or router.cached:
            facts.append(("Depuis le démarrage", f"{router.asked} trajet(s) demandé(s), {router.cached} repris du "
                                                 f"cache, {router.failed} en échec"))
        if router.last_error:
            facts.append(("Dernière erreur", router.last_error))
        return facts
