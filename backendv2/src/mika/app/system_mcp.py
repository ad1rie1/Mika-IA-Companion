"""Les serveurs MCP que ses plugins système apportent (ADR 0066) : ce que leurs paramètres demandent, fait serveur
du client MCP (ADR 0064). Un plugin ne connaît pas le client ; le client ne connaît aucun plugin : c'est ici qu'ils
se rejoignent.

Aujourd'hui un seul : ``web`` (chercher sur le web, lire des pages). Lancé dans sa cage, **réseau isolé**
(Internet, jamais cette machine ni le réseau local), à la demande (pas en main). Ses lignes d'accès par défaut sont
ici ; celles réglées sur sa fiche les remplacent (ADR 0131).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from mika.adapters.mcp.config import AccessRule, McpServer
from mika.adapters.mcp.system import Provided
from mika.plugins import web
from mika.ports.mcp import OWNER, WHO_ACCOUNTS, WORK

#: les plugins qui apportent un serveur : quand leurs paramètres changent, le client MCP se reconfigure
OWNERS = frozenset({web.WEB.name})


def provided(params_of: Callable[[str], Any]) -> dict[str, Provided]:
    """Les serveurs système demandés maintenant (``params_of(faculté)`` : ses paramètres courants)."""
    out: dict[str, Provided] = {}
    s = web.system_server(params_of(web.WEB.name))
    if s is not None:
        out[s.name] = Provided(spec(s), s.tools)
    return out


#: ses lignes d'accès tant qu'on ne les a pas réglées sur sa fiche (ADR 0131) : avec toi quand elle répond et quand
#: elle travaille ; elle lit seule, te demande avant d'agir, et ce qu'elle y lit est public (une recherche, des pages)
WEB_ACCESS = (AccessRule(who=(OWNER, WORK), when=("conversation",), read="seule", act="toi", keep="public"),)


#: ce que la recherche web réglait avant l'ADR 0131, comme surcharges de son plugin : devenu ses lignes d'accès
BEFORE_0131 = {web.WEB.name: ("audience", "in_work")}


def access_before(overrides: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Les lignes d'accès qui font ce que faisaient « Pour qui » et « Quand elle travaille » de la recherche web
    (des surcharges de son plugin, retirées par l'ADR 0131) ; rien quand ils valaient ce que ``WEB_ACCESS`` fait
    déjà (sa propriétaire seulement, et quand elle travaille)."""
    old = dict(overrides.get(web.WEB.name) or {})
    accounts, work = old.get("audience") == "comptes", bool(old.get("in_work", True))
    if not accounts and work:
        return {}
    rows = [AccessRule(who=(OWNER, WORK) if work else (OWNER,), when=("conversation",), read="seule", act="toi",
                       keep="public")]
    if accounts:  # « aussi une personne authentifiée » : les comptes d'avant, lisibles tant qu'on ne les change pas
        rows.append(AccessRule(who=(WHO_ACCOUNTS,), when=("conversation",), read="seule", act="toi", keep="public"))
    return {web.SERVER: {"access": [r.model_dump(mode="json") for r in rows]}}


def spec(s: web.SystemServer) -> McpServer:
    """Son serveur et ses lignes d'accès par défaut ; personne d'autre : la ligne par défaut est fermée."""
    rows = WEB_ACCESS
    return McpServer(purpose=s.purpose, when_to_use=s.when_to_use, enabled=True, transport="local", command=s.command,
                     args=s.args, env=s.env, network="isole", shared=s.shared, access=tuple(rows), in_hand=False,
                     timeout_s=s.timeout_s, max_calls=s.max_calls, max_result_chars=s.max_result_chars)
