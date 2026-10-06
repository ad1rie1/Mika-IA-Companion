"""Le client MCP (ADR 0064) : une session avec un serveur, quel que soit son transport.

Écrit à la main, comme le serveur (``protocol.py``, ADR 0026 §4) : ``initialize`` puis
``notifications/initialized``, ``tools/list`` (avec son curseur), ``tools/call``, ``ping``, et
``notifications/cancelled`` quand un appel est abandonné. Le client ne déclare **aucune** capacité : ni
``sampling`` (un serveur qui ferait écrire son modèle), ni ``elicitation``, ni ``roots``. Ce que le serveur rend
est une donnée venue d'ailleurs : bornée ici, désamorcée et citée plus loin.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from mika.adapters.mcp.config import MAX_DESCRIPTION, MAX_SCHEMA, fingerprint
from mika.adapters.mcp.protocol import PROTOCOL_VERSIONS
from mika.kernel.codec import canonical_json
from mika.ports.mcp import LiveTool
from mika.ports.preprocess import inert
from mika.vocab.phrasebook import phrase

CLIENT_INFO = {"name": "mika", "version": "1"}
#: une liste d'outils au-delà : coupée (un serveur ne lui offre pas mille outils)
MAX_TOOLS = 200
MAX_PAGES = 20
#: le texte d'une réponse au-delà : coupé ici (la faculté le borne encore à ce que l'opérateur a choisi)
MAX_RESULT = 200_000
#: ce que dit un appel abandonné au serveur
CANCELLED = "abandonné par le client"


class McpError(Exception):
    """Une panne de transport ou de protocole (injoignable, refusé, réponse illisible), dite en français."""


class McpTimeout(McpError):
    pass


class SessionExpired(McpError):
    """Le serveur ne connaît plus la session (HTTP 404) : la requête n'a pas été traitée, on peut en rouvrir une."""


class McpRemoteError(Exception):
    """Le serveur a répondu par une erreur JSON-RPC : il a été joint."""

    def __init__(self, code: Any, message: str) -> None:
        super().__init__(f"{message} (code {code})")
        self.code = code


class Transport(Protocol):
    protocol_version: str | None

    async def request(self, message: Mapping[str, Any]) -> dict[str, Any]: ...

    async def notify(self, message: Mapping[str, Any]) -> None: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ServerInfo:
    name: str
    version: str
    protocol: str
    instructions: str
    has_tools: bool


@dataclass(frozen=True, slots=True)
class CallOutcome:
    text: str
    is_error: bool


class McpSession:
    def __init__(self, transport: Transport) -> None:
        self.transport = transport
        self._ids = itertools.count(1)
        self.info: ServerInfo | None = None

    async def initialize(self, timeout_s: float) -> ServerInfo:
        result = await self._request("initialize", {"protocolVersion": PROTOCOL_VERSIONS[0], "capabilities": {},
                                                    "clientInfo": CLIENT_INFO}, timeout_s)
        version = str(result.get("protocolVersion") or "")
        if version not in PROTOCOL_VERSIONS:
            raise McpError(f"le serveur parle une version du protocole que ce client ne connaît pas : « {version[:30]} »")
        self.transport.protocol_version = version
        await self.transport.notify({"jsonrpc": "2.0", "method": "notifications/initialized"})
        info = result.get("serverInfo") if isinstance(result.get("serverInfo"), Mapping) else {}
        caps = result.get("capabilities") if isinstance(result.get("capabilities"), Mapping) else {}
        self.info = ServerInfo(name=_text(info.get("name"), 120), version=_text(info.get("version"), 60),
                               protocol=version, instructions=_text(result.get("instructions"), 4000),
                               has_tools="tools" in caps)
        return self.info

    async def list_tools(self, timeout_s: float) -> list[LiveTool]:
        tools: list[LiveTool] = []
        seen: set[str] = set()
        cursor: Any = None
        for _ in range(MAX_PAGES):
            result = await self._request("tools/list", {"cursor": cursor} if cursor else {}, timeout_s)
            for raw in result.get("tools") or ():
                tool = live_tool(raw)
                if tool is not None and tool.remote not in seen and len(tools) < MAX_TOOLS:
                    seen.add(tool.remote)
                    tools.append(tool)
            cursor = result.get("nextCursor")
            if not cursor or len(tools) >= MAX_TOOLS:
                break
        return tools

    async def call_tool(self, name: str, arguments: Mapping[str, Any], timeout_s: float) -> CallOutcome:
        result = await self._request("tools/call", {"name": name, "arguments": dict(arguments)}, timeout_s)
        return outcome(result)

    async def ping(self, timeout_s: float) -> None:
        await self._request("ping", {}, timeout_s)

    async def aclose(self) -> None:
        await self.transport.aclose()

    async def _request(self, method: str, params: Mapping[str, Any], timeout_s: float) -> dict[str, Any]:
        mid = next(self._ids)
        message = {"jsonrpc": "2.0", "id": mid, "method": method, "params": dict(params)}
        try:
            reply = await asyncio.wait_for(self.transport.request(message), timeout_s)
        except TimeoutError:
            await self._cancel(mid, "délai dépassé")
            raise McpTimeout(f"pas de réponse en {timeout_s:g} s") from None
        except asyncio.CancelledError:
            await asyncio.shield(self._cancel(mid, CANCELLED))
            raise
        if not isinstance(reply, Mapping):
            raise McpError("réponse illisible")
        if "error" in reply:
            err = reply["error"] if isinstance(reply["error"], Mapping) else {}
            raise McpRemoteError(err.get("code"), _text(err.get("message"), 500) or "erreur sans message")
        result = reply.get("result")
        if not isinstance(result, Mapping):
            raise McpError("réponse sans résultat")
        return dict(result)

    async def _cancel(self, mid: int, reason: str) -> None:
        """Dire au serveur qu'on n'attend plus (sans jamais attendre ni lever)."""
        try:
            await asyncio.wait_for(self.transport.notify({
                "jsonrpc": "2.0", "method": "notifications/cancelled",
                "params": {"requestId": mid, "reason": reason}}), 2.0)
        except Exception:  # noqa: BLE001 — une politesse, rien ne dépend d'elle
            pass


def _text(value: Any, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


def live_tool(raw: Any) -> LiveTool | None:
    """Un outil tel que le serveur le décrit, borné et désamorcé ; ``None`` s'il est illisible (sans nom, schéma
    qui n'est pas un objet ou trop gros)."""
    if not isinstance(raw, Mapping) or not isinstance(raw.get("name"), str) or not raw["name"].strip():
        return None
    name = raw["name"].strip()[:128]
    schema = raw.get("inputSchema") if isinstance(raw.get("inputSchema"), Mapping) else {"type": "object"}
    if schema.get("type", "object") != "object" or len(canonical_json(schema)) > MAX_SCHEMA:
        return None
    annotations = raw.get("annotations") if isinstance(raw.get("annotations"), Mapping) else {}
    description = _text(raw.get("description"), 20_000)
    title = _text(raw.get("title") or annotations.get("title"), 200)
    return LiveTool(remote=name, title=inert(title, 200), description=inert(description, MAX_DESCRIPTION),
                    schema=dict(schema), annotations=dict(annotations),
                    fingerprint=fingerprint(name, description, schema, annotations))


def outcome(result: Mapping[str, Any]) -> CallOutcome:
    """Le texte d'un résultat ``tools/call`` : ses textes, ce qui n'en est pas dit en une ligne, le contenu
    structuré quand il n'y a rien d'autre."""
    parts: list[str] = []
    for item in result.get("content") or ():
        if not isinstance(item, Mapping):
            continue
        kind = item.get("type")
        if kind == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
        elif kind in ("image", "audio"):
            what = phrase("mcp.content.image") if kind == "image" else phrase("mcp.content.sound")
            parts.append(phrase("mcp.content.media", what=what, mime=_text(item.get("mimeType"), 40) or "?"))
        elif kind == "resource_link":
            parts.append(phrase("mcp.content.link", name=_text(item.get("name"), 120),
                                uri=_text(item.get("uri"), 300)).strip())
        elif kind == "resource" and isinstance(item.get("resource"), Mapping):
            res = item["resource"]
            parts.append(res["text"] if isinstance(res.get("text"), str)
                         else phrase("mcp.content.resource", uri=_text(res.get("uri"), 300)))
    structured = result.get("structuredContent")
    if not parts and structured is not None:
        try:
            parts.append(json.dumps(structured, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            parts.append(str(structured))
    text = "\n".join(parts)
    if len(text) > MAX_RESULT:
        text = text[:MAX_RESULT] + "…[coupé]"
    return CallOutcome(text=text, is_error=bool(result.get("isError")))
