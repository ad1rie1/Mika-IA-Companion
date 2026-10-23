"""Les serveurs MCP que ses plugins système apportent (ADR 0066) : ce que leurs paramètres demandent, fait serveur
du client MCP (ADR 0064). Un plugin ne connaît pas le client ; le client ne connaît aucun plugin : c'est ici qu'ils
se rejoignent.

Aujourd'hui un seul : ``web`` (chercher sur le web, lire des pages). Lancé dans sa cage, **réseau isolé**
(Internet, jamais cette machine ni le réseau local), jamais en initiative, à la demande (pas en main).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mika.adapters.mcp.config import AccessRule, McpServer
from mika.adapters.mcp.system import Provided
from mika.plugins import web
from mika.ports.mcp import WHO_ACCOUNTS, WHO_OWNER

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
    """Son serveur, ses lignes d'accès d'après les paramètres du plugin (ADR 0131) : avec toi quand elle répond (et
    quand elle travaille, s'il le dit), avec les comptes s'il le dit ; elle lit seule, te demande avant d'agir, et ce
    qu'elle y lit est public. Personne d'autre : la ligne par défaut est fermée."""
    mine = ("conversation", "travail") if s.in_work else ("conversation",)
    rows = [AccessRule(who=WHO_OWNER, when=mine, read="seule", act="toi", keep="public")]
    if s.audience == "comptes":
        rows.append(AccessRule(who=WHO_ACCOUNTS, when=("conversation",), read="seule", act="toi", keep="public"))
    return McpServer(purpose=s.purpose, when_to_use=s.when_to_use, enabled=True, transport="local", command=s.command,
                     args=s.args, env=s.env, network="isole", shared=s.shared, access=tuple(rows), in_hand=False,
                     timeout_s=s.timeout_s, max_calls=s.max_calls, max_result_chars=s.max_result_chars)
