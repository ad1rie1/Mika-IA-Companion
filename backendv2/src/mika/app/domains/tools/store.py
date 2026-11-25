"""Ce qu'un serveur MCP fait d'elle, écrit dans les réglages (ADR 0128, 0131) : sa fiche réglée depuis la console ou
l'API par personne, un serveur branché, un serveur retiré — chaque fois relue puis réécrite d'un seul tenant, sous
``Settings.writing`` : la console et l'API par personne qui règlent deux serveurs en même temps ne s'effacent pas.

Un serveur du système (ADR 0066) suit les paramètres de son plugin : seuls ses accès (``SYSTEM_ACCESS_FIELDS``) se
règlent ici, rangés à part ; il ne se branche ni ne se retire ici. Le client MCP (``adapters/mcp/hub.py``) reçoit
``settle`` et ``remove`` : il enregistre par eux, puis applique (``reconfigure``)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from mika.adapters.mcp.config import McpConfig, McpServer
from mika.adapters.mcp.system import SystemServers
from mika.app.domains.tools.settings import SYSTEM_ACCESS_FIELDS, ToolsSettings


class McpSettingsStore:
    """Les fiches des serveurs MCP de l'opérateur et des personnes, rangées par ``ToolsSettings`` ; ``system`` : les
    serveurs qu'apportent ses plugins système, qu'on ne réécrit pas ici."""

    def __init__(self, settings: ToolsSettings, system: SystemServers) -> None:
        self.settings = settings
        self.system = system

    async def settle(self, name: str, changes: Mapping[str, Any] | Callable[[McpServer], Mapping[str, Any]],
                     create: bool = False) -> None:
        """Ce qu'un serveur de l'opérateur fait d'elle, réglé depuis sa fiche (ADR 0128) : sa fiche de réglages
        réécrite ; un serveur du système suit les paramètres de son plugin. ``create`` : un serveur qu'on branche.
        Relue puis réécrite d'un seul tenant (``Settings.writing``) : la console et l'API par personne qui règlent
        deux serveurs en même temps ne s'effacent pas. ``changes`` peut se calculer depuis la fiche relue sous le
        verrou (une fonction de la fiche) : un partage retiré ailleurs entre-temps ne revient pas."""
        async with self.settings.writing:
            await self._settle(name, changes, create)

    async def _settle(self, name: str, changes: Mapping[str, Any] | Callable[[McpServer], Mapping[str, Any]],
                      create: bool) -> None:
        settings, system = self.settings, self.system
        if callable(changes):
            servers_now = {**system.config(McpConfig()).servers, **settings.mcp().servers}
            if create or name not in servers_now:
                raise ValueError("ce serveur ne se règle pas ici : il n'existe plus")
            changes = dict(changes(servers_now[name]))
        if not create and name in system.names():
            # un serveur du système : ses accès seulement, rangés à part (ADR 0131) ; le reste suit son plugin
            if set(changes) - set(SYSTEM_ACCESS_FIELDS):
                raise ValueError("un serveur du système suit les paramètres de son plugin : seuls ses accès se "
                                 "règlent ici")
            McpServer.model_validate({**system.config(McpConfig()).servers[name].model_dump(), **changes})
            await settings.save_mcp_system_access(name, changes)
            return
        cfg = settings.mcp()
        servers = dict(cfg.servers)
        if create:
            if name in servers or name in system.names():
                raise ValueError(f"un serveur s'appelle déjà « {name} »")
            servers[name] = McpServer.model_validate(dict(changes))
        elif name not in servers:
            raise ValueError("ce serveur ne se règle pas ici : un serveur du système suit les paramètres de son plugin")
        else:
            servers[name] = McpServer.model_validate({**servers[name].model_dump(), **changes})
        await settings.save_mcp(McpConfig(servers=servers))

    async def remove(self, name: str) -> None:
        """Retirer un serveur (ADR 0192) : sa fiche ôtée des réglages, relus puis réécrits d'un seul tenant
        (``Settings.writing``). La fiche se cherche d'abord : celle qu'un serveur du système du même nom masque
        (branchée quand son plugin était inactif) se retire aussi, sans toucher à ce serveur, qui suit les paramètres
        de son plugin. Sans fiche, un serveur du système ne se retire pas ici, et un nom qu'on ne trouve plus n'a rien
        à retirer : refusés tous deux."""
        async with self.settings.writing:
            cfg = self.settings.mcp()
            if name not in cfg.servers:
                if name in self.system.names():
                    raise ValueError("un serveur du système suit les paramètres de son plugin : il ne se retire pas "
                                     "ici")
                raise ValueError("ce serveur n'existe plus")
            await self.settings.save_mcp(McpConfig(servers={n: s for n, s in cfg.servers.items() if n != name}))
