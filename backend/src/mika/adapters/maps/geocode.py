"""Les adresses (ADR 0194) : un numéro et une rue, une commune, cherchés à la Géoplateforme de l'IGN (la Base Adresse
Nationale, ``data.geopf.fr/geocodage``), relayée par ce serveur. **Seul le texte cherché part** : jamais la position
de la personne (ni ``lat`` ni ``lon`` dans la demande), ni rien d'elle. Au plus dix demandes par seconde pour tout ce
serveur (la Géoplateforme en permet cinquante)."""

from __future__ import annotations

import json
import math
from collections.abc import Callable

import httpx

from mika.adapters.maps.config import GEOPLATEFORME, PlacesConfig
from mika.adapters.maps.pace import Pace, client
from mika.adapters.maps.tiles import read_capped
from mika.ports.maps import MapsUnavailable, PlaceHit

TIMEOUT_S = 10.0
PER_SECOND = 10.0
TEXT_MIN, TEXT_MAX = 3, 200
LIMIT_MAX = 10
RESPONSE_MAX_BYTES = 2 * 1024 * 1024
#: ce qu'est une réponse, en français
TYPES_FR = {"housenumber": "Adresse", "street": "Rue", "locality": "Lieu-dit", "municipality": "Commune"}
ADDRESS, CATEGORY = "address", "adresse"
NOT_SET = "Les adresses ne sont pas réglées."
#: pour tout ce serveur : une seule Géoplateforme, quelle que soit l'adresse réglée
_PACE = Pace(PER_SECOND, wait_max=3.0, busy="La recherche d'adresses est très demandée : réessaie dans un instant.")


def _said(value: object, limit: int = 200) -> str:
    return " ".join(str(value).split())[:limit] if isinstance(value, str) else ""


class Geocoder:
    """Les adresses de la source réglée (``config`` relu à chaque fois : la console la change sans redémarrer)."""

    def __init__(self, config: Callable[[], PlacesConfig], *, transport: httpx.AsyncBaseTransport | None = None,
                 pace: Pace | None = None) -> None:
        self.config = config
        self._transport = transport
        self._pace = pace or _PACE
        self._client: httpx.AsyncClient | None = None
        #: depuis le démarrage, pour la console
        self.asked = 0
        self.failed = 0
        self.last_error = ""

    def ready(self) -> bool:
        return self.config().addresses == GEOPLATEFORME

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = client(TIMEOUT_S, self._transport)
        return self._client

    async def search(self, text: str, *, limit: int = 5) -> list[PlaceHit]:
        """Les adresses qui répondent à ce texte, les plus sûres d'abord. Moins de trois lettres : rien (la
        Géoplateforme les refuse)."""
        cfg = self.config()
        if cfg.addresses != GEOPLATEFORME:
            raise MapsUnavailable(NOT_SET)
        query = " ".join(str(text or "").split())[:TEXT_MAX]
        if len(query) < TEXT_MIN:
            return []
        limit = max(1, min(LIMIT_MAX, int(limit)))
        await self._pace.turn()
        self.asked += 1
        try:
            body = await self._get(cfg.addresses_url + "/search", {"q": query, "limit": str(limit),
                                                                   "index": "address"})
            return _hits(body)[:limit]
        except MapsUnavailable as exc:
            self.failed += 1
            self.last_error = str(exc)
            raise

    async def _get(self, url: str, params: dict[str, str]) -> object:
        try:
            async with self._http().stream("GET", url, params=params) as r:
                if r.status_code == 429:
                    raise MapsUnavailable("La Géoplateforme demande d'attendre : réessaie dans un instant.")
                if r.status_code != 200:
                    raise MapsUnavailable(f"La Géoplateforme a répondu HTTP {r.status_code}.")
                raw = await read_capped(r, RESPONSE_MAX_BYTES)
        except httpx.HTTPError as exc:
            raise MapsUnavailable(f"La Géoplateforme ne répond pas ({type(exc).__name__}).") from None
        except ValueError:
            raise MapsUnavailable("La Géoplateforme a rendu une réponse démesurée.") from None
        try:
            return json.loads(raw)
        except ValueError:
            raise MapsUnavailable("La Géoplateforme a rendu une réponse illisible.") from None


def _hits(body: object) -> list[PlaceHit]:
    """Les adresses d'une réponse GeoJSON (``features[].properties``, ``geometry.coordinates`` en lon, lat) ; ce qui
    ne se lit pas est laissé de côté."""
    features = body.get("features") if isinstance(body, dict) else None
    if not isinstance(features, list):
        raise MapsUnavailable("La Géoplateforme a rendu une réponse illisible.")
    out: list[PlaceHit] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties")
        geometry = feature.get("geometry")
        coords = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if not isinstance(props, dict) or not isinstance(coords, list) or len(coords) < 2:
            continue
        lon, lat = coords[0], coords[1]
        if not all(isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) for v in (lat, lon)):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        label = _said(props.get("label")) or _said(props.get("name"))
        if not label:
            continue
        kind = _said(props.get("type"), 40)
        out.append(PlaceHit(id=f"a:{len(out)}", name=label, kind=ADDRESS, kind_fr=TYPES_FR.get(kind, "Adresse"),
                            category=CATEGORY, lat=round(float(lat), 6), lon=round(float(lon), 6),
                            town=_said(props.get("city"), 120)))
    return out
