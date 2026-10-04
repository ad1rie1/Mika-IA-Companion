"""Le transport HTTP « streamable » d'un client MCP (ADR 0064).

Chaque message part en POST ; la réponse arrive en JSON ou dans un flux SSE (le serveur choisit). La session est
celle que le serveur donne à ``initialize`` (``Mcp-Session-Id``), la version du protocole est redite à chaque
requête (``MCP-Protocol-Version``). Une requête que le serveur adresse au client dans un flux (« écris pour moi »,
« demande à la personne ») reçoit un refus : ce client ne déclare aucune capacité.

Bornes : pas de redirection, pas de mandataire hérité de l'environnement, une réponse plafonnée. L'adresse est
choisie par l'opérateur (la machine, le réseau local sont permis) ; en http, elle doit **résoudre** vers une
adresse de ce côté-ci — le jeton ne voyage pas en clair sur Internet.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx

from mika.adapters.mcp.client import McpError, SessionExpired
from mika.adapters.mcp.config import private_host, private_ip

log = logging.getLogger("mika.mcp.client")

#: une réponse au-delà : refusée
MAX_RESPONSE = 4 * 1024 * 1024
CONNECT_TIMEOUT_S = 10.0
#: ce qu'on répond à une requête du serveur (sampling, elicitation, roots…)
UNSUPPORTED = -32601


class HttpTransport:
    def __init__(self, url: str, *, headers: Mapping[str, str] | None = None, verify: bool | str = True,
                 client: httpx.AsyncClient | None = None, max_bytes: int = MAX_RESPONSE) -> None:
        self.url = url
        self.headers = dict(headers or {})
        self.max_bytes = max_bytes
        self.session_id: str | None = None
        self.protocol_version: str | None = None
        #: le serveur a signalé que sa liste d'outils a changé (``notifications/tools/list_changed``)
        self.tools_changed = False
        self._owned = client is None
        self._client = client or httpx.AsyncClient(follow_redirects=False, trust_env=False, verify=verify,
                                                   timeout=httpx.Timeout(None, connect=CONNECT_TIMEOUT_S))
        self._checked = False
        self._tasks: set[asyncio.Task[Any]] = set()

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **self.headers}
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        if self.protocol_version:
            h["MCP-Protocol-Version"] = self.protocol_version
        return h

    async def _check_address(self) -> None:
        """En http, l'adresse doit résoudre vers cette machine ou le réseau local (vérifié une fois)."""
        if self._checked:
            return
        parts = urlsplit(self.url)
        host = parts.hostname or ""
        if parts.scheme == "http":
            try:
                literal = ipaddress.ip_address(host.strip("[]"))
            except ValueError:
                literal = None
            if literal is not None:
                ok = private_ip(literal)
            elif host in ("localhost",) or private_host(host):
                infos = await _resolve(host, parts.port or 80)
                ok = bool(infos) and all(private_ip(ip) for ip in infos)
            else:
                ok = False
            if not ok:
                raise McpError("http vers une adresse publique : le jeton passerait en clair (https ailleurs)")
        self._checked = True

    async def request(self, message: Mapping[str, Any]) -> dict[str, Any]:
        await self._check_address()
        mid = message.get("id")
        try:
            async with self._client.stream("POST", self.url, content=json.dumps(message, ensure_ascii=False),
                                           headers=self._headers()) as r:
                self._status(r, initialize=message.get("method") == "initialize")
                kind = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if kind == "text/event-stream":
                    return await self._from_stream(r, mid)
                body = await _read(r, self.max_bytes)
        except httpx.TimeoutException as exc:
            raise McpError(f"délai de connexion dépassé ({type(exc).__name__})") from None
        except httpx.HTTPError as exc:
            raise McpError(f"injoignable : {_describe(exc)}") from None
        try:
            data = json.loads(body or b"null")
        except ValueError:
            raise McpError("réponse illisible (ce n'est pas du JSON)") from None
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("id") == mid and ("result" in item or "error" in item):
                return item
        raise McpError("le serveur n'a pas répondu à la requête")

    async def notify(self, message: Mapping[str, Any]) -> None:
        await self._check_address()
        try:
            r = await self._client.post(self.url, content=json.dumps(message, ensure_ascii=False),
                                        headers=self._headers(), timeout=CONNECT_TIMEOUT_S)
        except httpx.HTTPError as exc:
            raise McpError(f"injoignable : {_describe(exc)}") from None
        self._status(r)

    async def aclose(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self.session_id:
            try:  # fermer la session chez le serveur : une politesse
                await self._client.delete(self.url, headers=self._headers(), timeout=2.0)
            except (httpx.HTTPError, OSError):
                pass
            self.session_id = None
        if self._owned:
            await self._client.aclose()

    # ── détails ──
    def _status(self, r: httpx.Response, *, initialize: bool = False) -> None:
        sid = r.headers.get("mcp-session-id")
        if initialize and sid:
            self.session_id = sid[:200]
        if r.status_code == 404 and self.session_id and not initialize:
            raise SessionExpired("le serveur ne connaît plus la session")
        if r.status_code in (401, 403):
            raise McpError(f"refusé par le serveur (HTTP {r.status_code}) : vérifie le jeton")
        if r.status_code >= 400:
            raise McpError(f"le serveur a répondu HTTP {r.status_code}")
        if r.status_code in (301, 302, 303, 307, 308):
            raise McpError(f"le serveur redirige (HTTP {r.status_code}) : donne l'adresse finale")

    async def _from_stream(self, r: httpx.Response, mid: Any) -> dict[str, Any]:
        size, data_lines = 0, []
        async for line in r.aiter_lines():
            size += len(line) + 1
            if size > self.max_bytes:
                raise McpError("réponse trop grosse")
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
                continue
            if line.strip() or not data_lines:
                continue
            raw, data_lines = "\n".join(data_lines), []
            found = self._event(raw, mid)
            if found is not None:
                return found
        if data_lines:
            found = self._event("\n".join(data_lines), mid)
            if found is not None:
                return found
        raise McpError("le flux s'est fermé sans réponse")

    def _event(self, raw: str, mid: Any) -> dict[str, Any] | None:
        try:
            msg = json.loads(raw)
        except ValueError:
            return None
        for item in msg if isinstance(msg, list) else [msg]:
            if not isinstance(item, dict):
                continue
            if item.get("id") == mid and ("result" in item or "error" in item):
                return item
            method = item.get("method")
            if method == "notifications/tools/list_changed":
                self.tools_changed = True
            elif isinstance(method, str) and "id" in item:
                self._refuse(item["id"], method)
        return None

    def _refuse(self, rid: Any, method: str) -> None:
        """Une requête du serveur (« écris pour moi », « demande à la personne ») : refusée, sans attendre."""
        log.info("mcp : requête du serveur refusée (%s)", method[:60])
        reply = {"jsonrpc": "2.0", "id": rid, "error": {"code": UNSUPPORTED, "message": "non pris en charge"}}

        async def send() -> None:
            try:
                await self._client.post(self.url, content=json.dumps(reply), headers=self._headers(), timeout=5.0)
            except httpx.HTTPError:
                pass

        task = asyncio.get_running_loop().create_task(send())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


async def _read(r: httpx.Response, limit: int) -> bytes:
    chunks, size = [], 0
    async for chunk in r.aiter_bytes():
        size += len(chunk)
        if size > limit:
            raise McpError("réponse trop grosse")
        chunks.append(chunk)
    return b"".join(chunks)


async def _resolve(host: str, port: int) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise McpError(f"nom inconnu : {host} ({exc.strerror or exc})") from None
    out = []
    for *_rest, addr in infos:
        try:
            out.append(ipaddress.ip_address(addr[0].split("%")[0]))
        except ValueError:
            continue
    return out


def _describe(exc: BaseException) -> str:
    text = str(exc) or type(exc).__name__
    return text[:200]
