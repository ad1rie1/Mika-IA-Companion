"""La lecture d'un corps de requête : bornée pendant qu'il arrive, puis lue en JSON.

Ni Starlette ni uvicorn ne bornent un corps : chaque route le lit par ``read_bounded`` (ou ``bounded_stream``, pour un
envoi en ``multipart/form-data`` qu'un analyseur lit morceau par morceau), sous sa borne. Le JSON se lit de deux
façons :

- ``json_fields`` pour les routes ordinaires du serveur (connexion, premier compte, jeton, notifications, décision,
  appareil) : un corps vide, illisible ou qui n'est pas un objet vaut ``{}`` ; trop grand, ``PayloadTooLarge`` remonte
  au gestionnaire ``too_large`` que ``create_app`` pose ;
- ``json_object`` pour les portes à clé (Teams, le téléphone) et ``/api/moi``, qui refusent elles-mêmes, avec leurs
  en-têtes : trop grand, 413 ; illisible ou pas un objet, 400 ; un corps vide vaut ``{}``.

Un réveil (``/api/wake/…``) lit son corps brut (il en vérifie la signature), puis ``parsed`` : un texte qui n'est pas
du JSON ne s'y refuse pas.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Mapping
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

#: le corps JSON d'une route ordinaire (connexion, premier compte, jeton, notifications, décision, appareil) : au
#: plus tant d'octets, 413 au-delà — ni Starlette ni uvicorn ne bornent un corps
BODY_MAX_BYTES = 64 * 1024


class PayloadTooLarge(Exception):
    """Un corps au-delà de sa borne : la route répond 413. Pour les routes ordinaires, c'est le gestionnaire
    ``too_large`` (posé par ``create_app``) ; pour les portes à clé et la branche JSON de ``/api/moi``, c'est
    ``json_object``, avec leurs en-têtes ; un réveil et un envoi en ``multipart/form-data`` de ``/api/moi`` l'attrapent
    eux-mêmes."""


async def bounded_stream(request: Request, limit: int) -> AsyncGenerator[bytes, None]:
    """Le corps d'une requête, morceau par morceau, borné à ``limit`` octets : un ``Content-Length`` au-delà, ou un flux
    (un envoi par morceaux, sans longueur annoncée) qui le dépasse, lèvent ``PayloadTooLarge``."""
    try:
        size = int(request.headers.get("content-length") or 0)
    except ValueError:
        size = 0
    if size > limit:
        raise PayloadTooLarge
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise PayloadTooLarge
        yield chunk


async def read_bounded(request: Request, limit: int) -> bytes:
    """Le corps d'une requête, tout entier, borné à ``limit`` octets (``bounded_stream`` : rien de trop n'est gardé)."""
    return b"".join([chunk async for chunk in bounded_stream(request, limit)])


async def too_large(request: Request, exc: Exception) -> Response:
    return JSONResponse({"error": "Requête trop grande."}, status_code=413, headers={"Cache-Control": "no-store"})


def parsed(raw: bytes) -> Any | None:
    """Le JSON d'un corps ; ``None`` s'il est illisible (et, selon la version de Python, trop imbriqué)."""
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        return None


async def json_object(request: Request, limit: int, headers: Mapping[str, str]) -> dict[str, Any] | JSONResponse:
    """L'objet JSON d'une porte à clé ou de ``/api/moi``, lu borné à ``limit`` octets (aussi sans ``Content-Length``),
    ou le refus à rendre : au-delà, 413 ; illisible ou pas un objet, 400. Un corps vide vaut ``{}``. Chaque refus porte
    les ``headers`` donnés."""
    try:
        raw = await read_bounded(request, limit)
    except PayloadTooLarge:
        return JSONResponse({"error": "Requête trop grande."}, status_code=413, headers=headers)
    data = parsed(raw or b"{}")
    if not isinstance(data, dict):
        return JSONResponse({"error": "Un objet JSON."}, status_code=400, headers=headers)
    return data


async def json_fields(request: Request) -> dict[str, Any]:
    """Le JSON d'une route ordinaire, borné (``BODY_MAX_BYTES`` ; au-delà, ``PayloadTooLarge`` → 413) ;
    illisible, ou pas un objet : ``{}``."""
    data = parsed(await read_bounded(request, BODY_MAX_BYTES) or b"{}")
    return data if isinstance(data, dict) else {}
