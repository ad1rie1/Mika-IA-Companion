"""Le cœur MCP du jumeau : JSON-RPC 2.0 sur l'entrée et la sortie standard (transport « stdio »).

Juste ce qu'il faut pour servir des outils et des prompts à Claude Code :
``initialize``, ``ping``, ``tools/list``, ``tools/call``, ``prompts/list``, ``prompts/get``.
Écrit à la main, comme celui du moteur (``backendv2/src/mika/adapters/mcp/protocol.py``) :
un message par ligne, une réponse par requête, rien pour une notification.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    run: Callable[[Mapping[str, Any]], str]
    read_only: bool = True


@dataclass(frozen=True, slots=True)
class Prompt:
    name: str
    description: str
    render: Callable[[Mapping[str, Any]], str]
    arguments: tuple[tuple[str, str, bool], ...] = ()  # (nom, description, requis)


class ToolFailure(Exception):
    """Une erreur à rendre au modèle (« isError ») plutôt qu'au protocole."""


@dataclass
class Server:
    name: str
    version: str
    tools: dict[str, Tool] = field(default_factory=dict)
    prompts: dict[str, Prompt] = field(default_factory=dict)
    instructions: str = ""

    def handle_line(self, line: str) -> str | None:
        try:
            msg = json.loads(line)
        except ValueError:
            return json.dumps(_error(None, PARSE_ERROR, "JSON illisible"))
        if isinstance(msg, list):
            out = [r for m in msg if (r := self.handle(m)) is not None]
            return json.dumps(out, ensure_ascii=False) if out else None
        reply = self.handle(msg)
        return None if reply is None else json.dumps(reply, ensure_ascii=False)

    def handle(self, msg: Any) -> dict[str, Any] | None:
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
            return _error(msg.get("id") if isinstance(msg, dict) else None, INVALID_REQUEST, "requête invalide")
        mid = msg.get("id")
        method = msg["method"]
        params = msg.get("params") or {}
        if mid is None:  # une notification (initialized, cancelled…) : pas de réponse
            return None
        if method == "initialize":
            asked = params.get("protocolVersion")
            version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            result: dict[str, Any] = {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}, "prompts": {"listChanged": False}},
                "serverInfo": {"name": self.name, "version": self.version}}
            if self.instructions:
                result["instructions"] = self.instructions
            return _result(mid, result)
        if method == "ping":
            return _result(mid, {})
        if method == "tools/list":
            return _result(mid, {"tools": [_describe(t) for t in self.tools.values()]})
        if method == "tools/call":
            tool = self.tools.get(str(params.get("name")))
            if tool is None:
                return _error(mid, INVALID_PARAMS, f"outil inconnu : {params.get('name')}")
            args = params.get("arguments") or {}
            try:
                text, is_error = tool.run(args), False
            except ToolFailure as exc:
                text, is_error = str(exc), True
            except (KeyError, ValueError, TypeError) as exc:
                text, is_error = f"arguments invalides : {exc}", True
            except sqlite3.Error as exc:  # une recherche mal formée, une base occupée : l'outil le dit, le serveur reste
                text, is_error = f"la base n'a pas pu répondre ({exc}) : reformuler ou réessayer", True
            return _result(mid, {"content": [{"type": "text", "text": text}], "isError": is_error})
        if method == "prompts/list":
            return _result(mid, {"prompts": [{
                "name": p.name, "description": p.description,
                "arguments": [{"name": n, "description": d, "required": r} for n, d, r in p.arguments]}
                for p in self.prompts.values()]})
        if method == "prompts/get":
            prompt = self.prompts.get(str(params.get("name")))
            if prompt is None:
                return _error(mid, INVALID_PARAMS, f"prompt inconnu : {params.get('name')}")
            text = prompt.render(params.get("arguments") or {})
            return _result(mid, {"description": prompt.description,
                                 "messages": [{"role": "user", "content": {"type": "text", "text": text}}]})
        return _error(mid, METHOD_NOT_FOUND, f"méthode inconnue : {method}")


def _describe(t: Tool) -> dict[str, Any]:
    return {"name": t.name, "description": t.description, "inputSchema": dict(t.input_schema),
            "annotations": {"readOnlyHint": t.read_only}}


def _result(mid: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}
