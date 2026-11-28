"""Demander à un fournisseur ce qu'il propose : le client HTTP et la lecture de sa réponse, partagés par la liste des
modèles de langage (``adapters/llm/models.py``) et celle des modèles d'images (``adapters/imaging/models.py``).

Un appel HTTP court, sur demande seulement (jamais au rendu d'une page), borné par ``TIMEOUT_S``, sans suivre de
redirection. Une panne — un fournisseur injoignable, une clé refusée, une réponse illisible — devient un
``ListingFailed`` au message en français, jamais une autre exception : c'est justement quand on vient réparer la
configuration qu'il ne répond pas. La clé n'apparaît dans aucun message.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

TIMEOUT_S = 8.0
#: au-delà, les modèles d'une liste ne sont pas lus
LIMIT = 500


class ListingFailed(Exception):
    """Le fournisseur n'a pas donné sa liste (message en français, sans secret)."""


@asynccontextmanager
async def http_client(client: httpx.AsyncClient | None) -> AsyncIterator[httpx.AsyncClient]:
    """Le client donné, tel quel ; sinon un client à soi (``TIMEOUT_S``, aucune redirection), fermé après usage."""
    if client is not None:
        yield client
        return
    async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False) as own:
        yield own


async def fetch_json(http: httpx.AsyncClient, url: str, headers: dict[str, str], body: Any = None) -> Any:
    """La réponse JSON du fournisseur (``body`` : en POST) ; lève ``ListingFailed``."""
    try:
        response = await (http.post(url, headers=headers, json=body) if body is not None
                          else http.get(url, headers=headers))
    except httpx.HTTPError as exc:
        raise ListingFailed(f"Fournisseur injoignable ({type(exc).__name__}).") from None
    if response.status_code in (401, 403):
        raise ListingFailed("Clé refusée par le fournisseur.")
    if response.status_code >= 400:
        raise ListingFailed(f"Le fournisseur a répondu {response.status_code}.")
    try:
        return response.json()
    except ValueError:
        raise ListingFailed("Réponse illisible du fournisseur.") from None
