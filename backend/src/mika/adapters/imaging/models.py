"""Les modèles d'images qu'un fournisseur propose (le bouton « charger » de la
console). Le client HTTP et la lecture de la réponse sont ceux de la liste des
modèles de langage, partagés par ``adapters/listing.py`` : un appel HTTP court,
sur demande ; une panne devient un ``ListingFailed`` au message en français, sans
la clé. Chez OpenAI, seuls les modèles d'images restent (``gpt-image-*``,
``dall-e-*``) ; un serveur compatible rend sa liste telle quelle
(stable-diffusion.cpp : le modèle qu'il a chargé)."""

from __future__ import annotations

from typing import Any

import httpx

from mika.adapters.imaging.openai_images import OPENAI_BASE_URL
from mika.adapters.listing import LIMIT, ListingFailed, fetch_json, http_client


def is_image_model(name: str) -> bool:
    n = name.lower()
    return "image" in n or n.startswith("dall-e")


async def list_image_models(kind: str, *, api_key: str = "", base_url: str = "",
                            client: httpx.AsyncClient | None = None) -> list[str]:
    """Les identifiants de modèles ; lève ``ListingFailed``."""
    if kind == "openai" and not api_key:
        raise ListingFailed("Il faut une clé d'API pour lister les modèles.")
    if kind in ("openai_compatible", "sdcpp") and not base_url:
        raise ListingFailed("Il faut l'adresse du serveur pour lister ses modèles.")
    base = OPENAI_BASE_URL if kind == "openai" else base_url.rstrip("/")
    if kind == "sdcpp":  # sd-server donne son modèle par sa route compatible
        base = base.removesuffix("/v1") + "/v1"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with http_client(client) as http:
        payload = await fetch_json(http, f"{base}/models", headers)
    names = _names(payload)
    return [n for n in names if is_image_model(n)] if kind == "openai" else names


def _names(payload: Any) -> list[str]:
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ListingFailed("Réponse inattendue du fournisseur.")
    out = set()
    for item in items[:LIMIT]:
        name = item.get("id") if isinstance(item, dict) else None
        if isinstance(name, str) and name.strip():
            out.add(name.strip()[:200])
    return sorted(out)
