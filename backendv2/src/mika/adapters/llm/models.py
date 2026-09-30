"""Les modèles qu'un fournisseur propose (le bouton « charger » de la console).

Un appel HTTP court, sur demande seulement (jamais au rendu d'une page). Un
fournisseur injoignable ou une clé refusée donnent un message en français,
jamais une exception : c'est justement quand on vient réparer la
configuration qu'il ne répond pas. La clé n'apparaît dans aucun message.
"""

from __future__ import annotations

from typing import Any

import httpx

from mika.adapters.llm.config import BackendSpec

TIMEOUT_S = 8.0
LIMIT = 500
#: ce que ``claude --model`` comprend sans rien demander ; vide : le modèle par défaut de la CLI
CLAUDE_CODE_MODELS = ("fable", "haiku", "opus", "sonnet")


class ListingFailed(Exception):
    """Le fournisseur n'a pas donné sa liste (message en français, sans secret)."""


def _endpoint(spec: BackendSpec) -> tuple[str, dict[str, str], str]:
    """(adresse, en-têtes, format de la réponse)."""
    if spec.kind == "claude":
        return ("https://api.anthropic.com/v1/models?limit=1000",
                {"x-api-key": spec.api_key, "anthropic-version": "2023-06-01"}, "data")
    if spec.kind == "openai":
        base = (spec.base_url or "https://api.openai.com/v1").rstrip("/")
        return f"{base}/models", ({"Authorization": f"Bearer {spec.api_key}"} if spec.api_key else {}), "data"
    host = (spec.host or ("https://ollama.com" if spec.kind == "ollama_cloud" else "http://localhost:11434"))
    headers = {"Authorization": f"Bearer {spec.api_key}"} if spec.kind == "ollama_cloud" and spec.api_key else {}
    return f"{host.rstrip('/')}/api/tags", headers, "models"


def _names(payload: Any, shape: str) -> list[str]:
    items = payload.get(shape) if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ListingFailed("Réponse inattendue du fournisseur.")
    out = []
    for item in items[:LIMIT]:
        if isinstance(item, dict):
            name = item.get("id") or item.get("name") or item.get("model")
            if isinstance(name, str) and name.strip():
                out.append(name.strip()[:200])
    return sorted(set(out))


async def list_models(spec: BackendSpec, *, client: httpx.AsyncClient | None = None) -> list[str]:
    """Les identifiants de modèles du fournisseur ; lève ``ListingFailed``."""
    if spec.kind == "claude_code":
        return list(CLAUDE_CODE_MODELS)  # la CLI choisit : ses alias suffisent, sans réseau
    if spec.kind in ("claude",) and not spec.api_key:
        raise ListingFailed("Il faut une clé d'API pour lister les modèles.")
    url, headers, shape = _endpoint(spec)
    own = client is None
    http = client or httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False)
    try:
        response = await http.get(url, headers=headers)
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
        return _names(response.json(), shape)
    except ValueError:
        raise ListingFailed("Réponse illisible du fournisseur.") from None
