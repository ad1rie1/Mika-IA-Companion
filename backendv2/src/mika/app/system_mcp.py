"""Les serveurs MCP que ses plugins système apportent (ADR 0066) : ce que leurs paramètres demandent, fait serveur
du client MCP (ADR 0064). Un plugin ne connaît pas le client ; le client ne connaît aucun plugin : c'est ici qu'ils
se rejoignent.

Aujourd'hui un seul : ``web`` (chercher sur le web, lire des pages). Lancé dans sa cage, **réseau isolé**
(Internet, jamais cette machine ni le réseau local), jamais en initiative, à la demande (pas en main).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mika.adapters.mcp.config import McpServer
from mika.adapters.mcp.system import Provided
from mika.plugins import web

#: les plugins qui apportent un serveur : quand leurs paramètres changent, le client MCP se reconfigure
OWNERS = frozenset({web.WEB.name})


def provided(params_of: Callable[[str], Any]) -> dict[str, Provided]:
    """Les serveurs système demandés maintenant (``params_of(faculté)`` : ses paramètres courants)."""
    out: dict[str, Provided] = {}
    s = web.system_server(params_of(web.WEB.name))
    if s is not None:
        out[s.name] = Provided(spec(s), s.tools)
    return out


def spec(s: web.SystemServer) -> McpServer:
    return McpServer(purpose=s.purpose, when_to_use=s.when_to_use, enabled=True, transport="local", command=s.command,
                     args=s.args, env=s.env, network="isole", shared=s.shared, audience=s.audience,  # type: ignore[arg-type]
                     in_conversation=True, in_initiative=False, in_work=s.in_work, in_hand=False,
                     timeout_s=s.timeout_s, max_calls=s.max_calls, max_result_chars=s.max_result_chars)
