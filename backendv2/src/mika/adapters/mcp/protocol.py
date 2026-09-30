"""Le cœur MCP : JSON-RPC sur HTTP (transport « streamable HTTP »), sans état.

Juste ce qu'il faut pour servir des outils à un client MCP (Claude Code) :
``initialize``, ``ping``, ``tools/list``, ``tools/call`` ; les notifications
reçoivent un 202 vide. Chaque requête POST porte un message (ou un lot) et
reçoit sa réponse en JSON — jamais de flux SSE : un appel d'outil peut rester
ouvert longtemps (le relais le tient en attente), une réponse JSON suffit.

Pourquoi pas le SDK ``mcp`` : son gestionnaire de sessions ne s'ouvre qu'une
fois par instance (gênant pour une passerelle rechargée à chaud) et un appel
tenu dont le client disparaît finit sur un flux fermé ; ici, une requête dont
le client est parti se perd sans bruit, et rien ne vit hors de la requête.

Un hôte d'outils (``ToolHost``) dit ses outils et les exécute ; ``asgi``
choisit l'hôte d'une requête (ou la refuse par un statut HTTP) — c'est là que
vivent l'authentification et la portée.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

log = logging.getLogger("mika.mcp")

#: du plus récent au plus ancien ; on répond la version du client si on la connaît
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
#: au-delà, une requête est refusée (413) : un appel d'outil n'a pas à peser plus
MAX_BODY = 4 * 1024 * 1024

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    #: n'écrit rien : le client peut l'appeler en parallèle d'autres
    read_only: bool = False


@dataclass(frozen=True, slots=True)
class Outcome:
    text: str
    is_error: bool = False


class ToolHost(Protocol):
    name: str

    def tools(self) -> Sequence[Tool]: ...

    async def call(self, name: str, arguments: Mapping[str, Any]) -> Outcome: ...


def describe(tool: Tool) -> dict[str, Any]:
    out: dict[str, Any] = {"name": tool.name, "description": tool.description,
                           "inputSchema": dict(tool.input_schema) or {"type": "object"}}
    if tool.read_only:
        out["annotations"] = {"readOnlyHint": True}
    return out


async def answer(host: ToolHost, message: Any) -> dict[str, Any] | None:
    """La réponse JSON-RPC à un message ; ``None`` pour une notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return _error(message.get("id") if isinstance(message, dict) else None, INVALID_REQUEST, "requête invalide")
    if "id" not in message:
        return None  # une notification (initialized, cancelled…) : rien à répondre
    mid, method = message["id"], message["method"]
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return _error(mid, INVALID_PARAMS, "paramètres invalides")
    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return _result(mid, {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                             "serverInfo": {"name": host.name, "version": "1"}})
    if method == "ping":
        return _result(mid, {})
    if method == "tools/list":
        return _result(mid, {"tools": [describe(t) for t in host.tools()]})
    if method == "tools/call":
        name, arguments = params.get("name"), params.get("arguments") or {}
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return _error(mid, INVALID_PARAMS, "tools/call attend un nom et des arguments")
        out = await host.call(name, arguments)
        return _result(mid, {"content": [{"type": "text", "text": out.text}], "isError": out.is_error})
    return _error(mid, METHOD_NOT_FOUND, f"méthode inconnue : {method}")


def _result(mid: Any, result: Mapping[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "result": dict(result)}


def _error(mid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


#: une requête HTTP → l'hôte qui la sert, ou le statut qui la refuse
Resolve = Callable[[Mapping[str, Any]], "ToolHost | int | Awaitable[ToolHost | int]"]


def asgi(resolve: Resolve) -> Callable[..., Awaitable[None]]:
    """L'application ASGI d'un point MCP. ``resolve`` reçoit le ``scope`` HTTP."""

    async def app(scope: Mapping[str, Any], receive: Callable[..., Any], send: Callable[..., Any]) -> None:
        if scope.get("type") != "http":
            return
        if scope.get("method") != "POST":
            # pas de flux serveur → client (GET) ni de session à fermer (DELETE)
            await _send(send, 405, b"", extra=((b"allow", b"POST"),))
            return
        host = resolve(scope)
        if not isinstance(host, int) and hasattr(host, "__await__"):
            host = await host
        if isinstance(host, int):
            await _send(send, host, b"")
            return
        body = await _read(receive)
        if body is None:
            await _send(send, 413, b"")
            return
        try:
            message = json.loads(body or b"null")
        except ValueError:
            await _json(send, _error(None, PARSE_ERROR, "JSON illisible"))
            return
        if isinstance(message, list):
            replies = [r for r in [await answer(host, m) for m in message] if r is not None]
            if replies:
                await _json(send, replies)
            else:
                await _send(send, 202, b"")
            return
        reply = await answer(host, message)
        if reply is None:
            await _send(send, 202, b"")
        else:
            await _json(send, reply)

    return app


async def _read(receive: Callable[..., Any]) -> bytes | None:
    chunks, size = [], 0
    while True:
        msg = await receive()
        if msg.get("type") == "http.disconnect":
            return b""
        chunk = msg.get("body", b"")
        size += len(chunk)
        if size > MAX_BODY:
            return None
        chunks.append(chunk)
        if not msg.get("more_body"):
            return b"".join(chunks)


async def _json(send: Callable[..., Any], payload: Any) -> None:
    await _send(send, 200, json.dumps(payload, ensure_ascii=False).encode(),
                extra=((b"content-type", b"application/json"),))


async def _send(send: Callable[..., Any], status: int, body: bytes,
                extra: tuple[tuple[bytes, bytes], ...] = ()) -> None:
    try:
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-length", str(len(body)).encode()), *extra]})
        await send({"type": "http.response.body", "body": body})
    except OSError:
        log.debug("client MCP parti avant la réponse")


def bearer(scope: Mapping[str, Any]) -> str:
    """Le jeton ``Authorization: Bearer …`` d'une requête, ou ""."""
    for key, value in scope.get("headers") or ():
        if key.lower() == b"authorization":
            text = value.decode("latin-1")
            return text[7:].strip() if text[:7].lower() == "bearer " else ""
    return ""


def loopback(scope: Mapping[str, Any]) -> bool:
    client = scope.get("client")
    return bool(client) and client[0] in ("127.0.0.1", "::1")
