"""Ses services venus d'ailleurs (ADR 0192, 0219, 0310) : leur part de ce qui vient d'ailleurs (``app/me/outside.py``).

Un service a sa famille d'outils (``mcp.<service>``) ; l'écran Outils redit, case par case, la ligne de ses accès que
sa faculté déclare, lue comme elle la lit (``tool_allowance``), et le nomme pour la personne : un service du système
par son titre (« Le web »), un autre par son nom, à quoi il lui sert quand une personne l'a branché. Réglages › Droits
le range sur sa ligne, « Service « … » », le détail de ses accès sous ``mcp:<service>``, dans le sous-onglet des
services (``tab``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

from mika.app.domains.domain import OutsidePart
from mika.app.domains.tools import system as system_mcp
from mika.kernel.frame import Audience
from mika.vocab.rights import Allowance, tool_allowance


class Seen(NamedTuple):
    """Ce qu'une lecture de la matrice lit une fois de ses services : les outils qu'offre le port ``mcp``, par (son
    service, son outil là-bas) ; l'état de chaque service, par son nom ; les services du système offerts maintenant
    (``system.shown`` : leur titre et leur but, pour la personne)."""

    offered: Mapping[tuple[str, str], Any]
    statuses: Mapping[str, Any]
    system: Mapping[str, tuple[str, str]]


def seen(kernel: Any, frame: Any) -> Seen:
    """Ce que la matrice lit une fois de ses services."""
    port = kernel.ports.get("mcp")
    offered = {(t.server, t.remote): t for t in (port.offered() if port else ())}
    statuses = {st.name: st for st in (port.statuses() if port else ())}
    return Seen(offered, statuses, system_mcp.shown(frame))


def tool(s: Seen, g: Any) -> tuple[str, str]:
    """(l'outil chez elle, sa ressource) d'une ligne d'un service (« « meteo » · echo »)."""
    found = s.offered.get(_served(g))
    return (found.name if found is not None else ""), g.resource


def _served(g: Any) -> tuple[str, str]:
    """(son service, son outil là-bas) d'une ligne d'un service : sa ressource (``mcp:<service>``), son titre."""
    return g.resource.partition(":")[2], g.title.rsplit(" · ", 1)[-1]


def _service_allowance(g: Any, offered: Mapping[tuple[str, str], Any], statuses: Mapping[str, Any],
                       aud: Audience, kind: str, rights: Any, close: Callable[[str], bool] | None) -> Allowance | None:
    """La lecture même des lignes de son service (``tool_allowance``, comme sa faculté la fait), pour en redire la
    ligne : ``None`` sans le service ou l'outil."""
    server, remote = _served(g)
    status, found = statuses.get(server), offered.get((server, remote))
    if status is None or found is None:
        return None
    return tool_allowance(status.access, status.default, aud, kind, found.nature != "lecture", rights,
                          lambda a: a.concerns(remote), close=close, outside=True)


def allowance(s: Seen, frame: Any, g: Any, resource: str, tool: str, acts: bool, aud: Audience, kind: str,
              rights: Any, close: Callable[[str], bool] | None) -> Allowance | None:
    """La lecture même de la ligne de son service (``_service_allowance``)."""
    return _service_allowance(g, s.offered, s.statuses, aud, kind, rights, close)


def name(s: Seen, resource: str) -> str:
    """Le nom d'un service : un service du système par son titre (« Le web », ADR 0219), un autre par son nom."""
    kind, _, key = resource.partition(":")
    if kind == "mcp" and key in s.system:
        return s.system[key][0]
    return {"mcp": f"Service « {key} »"}.get(kind, resource)


def about(s: Seen, resource: str) -> str:
    """À quoi sert un service, dit à la personne : celui qu'une personne a branché (``owner``, ADR 0192), tel qu'elle
    l'a dit (``purpose``) — Paramètres le montre déjà à elle et à qui elle le partage ; un service du système, la
    phrase que la composition écrit pour la personne (``system_mcp.SHOWN``, ADR 0219). Rien pour un service de
    l'opérateur : son ``purpose`` est la ligne de son catalogue, écrite pour elle et au « tu » qui la désigne, pas pour
    la personne (ADR 0209) ; rien pour une app."""
    kind, _, key = resource.partition(":")
    status = s.statuses.get(key) if kind == "mcp" else None
    if status is not None and status.owner:
        return status.purpose
    return s.system[key][1] if kind == "mcp" and key in s.system else ""


def row(frame: Any, server: str) -> tuple[str, str]:
    """Sa ligne dans Réglages › Droits : « Service « … » », et le détail de ses accès."""
    return f"Service « {server} »", f"mcp:{server}"


OUTSIDE = OutsidePart("services", bundle="mcp.", title="Services", why="les accès de ce service", seen=seen, tool=tool,
                      allowance=allowance, name=name, about=about, row=row, tab="services",
                      tab_title="Services MCP", tab_hint="les outils venus d'ailleurs, service par service")
