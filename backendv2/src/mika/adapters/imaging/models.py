"""Les modèles d'images qu'un fournisseur propose (le bouton « charger » de la
console), comme ``adapters/llm/models.py`` : un appel HTTP court, sur demande ;
une panne devient un message en français, sans la clé. Chez OpenAI, seuls les
modèles d'images restent (``gpt-image-*``, ``dall-e-*``) ; un serveur compatible
rend sa liste telle quelle (stable-diffusion.cpp : le modèle qu'il a chargé)."""

from __future__ import annotations

from typing import Any

import httpx

from mika.adapters.imaging.openai_images import OPENAI_BASE_URL

TIMEOUT_S = 8.0
LIMIT = 500


class ListingFailed(Exception):
    """Le fournisseur n'a pas donné sa liste (message en français, sans secret)."""


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
    own = client is None
    http = client or httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False)
    try:
        response = await http.get(f"{base}/models", headers=headers)
    except httpx.HTTPError as exc:
        raise ListingFailed(f"Fournisseur injoignable ({type(exc).__name__}).") from None
    finally:
        if own:
            await http.aclose()
    if response.status_code in (401, 403):
        raise ListingFailed("Clé refusée par le fournisseur.")
    if response.status_code >= 400:
        raise ListingFailed(f"Le fournisseur a répondu {response.status_code}.")
    try:
        names = _names(response.json())
    except ValueError:
        raise ListingFailed("Réponse illisible du fournisseur.") from None
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
