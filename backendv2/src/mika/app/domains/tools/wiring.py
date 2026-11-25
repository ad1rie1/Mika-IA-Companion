"""Le câblage de ses outils venus d'ailleurs (ADR 0064, 0066, 0122, 0310) : le client MCP, qui est le port ``mcp`` du
noyau — les serveurs réglés, plus ceux que ses plugins système apportent (la recherche web) ; une fois le noyau là,
ce qui le reconfigure et ce qu'il prévient, et ses outils prêtés à un agent (``/mcp/pret/<nom>``) ; dans le cycle de
vie, le client joint ses serveurs (``start``) et les ferme en dernier (``release``)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from starlette.routing import Mount

from mika.adapters.mcp.hub import McpHub
from mika.adapters.mcp.system import SystemServers
from mika.app.domains.tools import system as system_mcp
from mika.app.domains.tools.lending import PREFIX as LENT_PREFIX
from mika.app.domains.tools.lending import Lending
from mika.app.domains.tools.settings import ToolsSettings
from mika.app.domains.tools.store import McpSettingsStore
from mika.app.wiring import Wiring
from mika.kernel.builtin import PARAMS_CHANGED

NAME = "tools"


def wire(w: Wiring) -> None:
    """Avant le noyau : ses réglages, le client MCP (le port ``mcp``). Ce que demandent les paramètres d'un plugin
    système se lit au noyau, qui n'existe pas encore : il est pris à l'usage (``w.port``, posé avant ``bind``)."""
    settings = w.settings.of(ToolsSettings)
    # les outils venus d'ailleurs (ADR 0064) : la configuration relue à chaque usage, les décisions aussi — plus les
    # serveurs de ses plugins système, d'après leurs paramètres, approuvés d'office (ADR 0066)
    system = SystemServers(lambda: system_mcp.provided(
        lambda owner: w.port.kernel.mind.registry.params_of(owner, w.port.kernel.mind.root)),
        access=settings.mcp_system_access)
    mcp_settings = McpSettingsStore(settings, system)
    mcp = w.ports["mcp"] = McpHub(lambda: system.config(settings.mcp()), lambda: system.reviews(settings.mcp_tools()),
                                system.saving(settings.save_mcp_tools), local_root=w.data / "mcp",
                                settle=mcp_settings.settle, remove=mcp_settings.remove, system=system.plugins)
    w.parts[NAME] = mcp


def bind(w: Wiring) -> None:
    """Une fois le noyau là : ce qui reconfigure le client MCP, ce qu'il prévient quand son offre change, et ses
    outils prêtés à un agent — leur porte (un montage) et ce que la console en lit."""
    kernel, mcp = w.port.kernel, w.parts[NAME]
    reconfiguring: set[asyncio.Task[None]] = set()

    def reconfigure_mcp(events: Sequence[Any], root: Any) -> None:
        """Les paramètres d'un plugin qui apporte un serveur ont changé (activé, désactivé, réglé) : le client MCP
        ferme ce qui a changé et rejoint ce qui doit l'être ; ses outils suivent."""
        if not any(e.type is PARAMS_CHANGED and e.data.owner in system_mcp.OWNERS for e in events):
            return
        try:
            task = asyncio.get_running_loop().create_task(mcp.reconfigure())
        except RuntimeError:  # pas de boucle (une commande hors ligne) : il se reconfigurera au démarrage
            return
        reconfiguring.add(task)
        task.add_done_callback(reconfiguring.discard)

    kernel.mind.subscribe(reconfigure_mcp)
    mcp.on_change(kernel.refresh_tools)  # son offre change : ses outils aussi (ADR 0064)
    lending = Lending(kernel, w.settings.lent)  # ses outils prêtés à un agent (ADR 0122)
    w.routes.append(Mount(LENT_PREFIX, app=lending.app()))
    w.inspector["lending"] = lending


async def start(w: Wiring) -> None:
    w.parts[NAME].start()  # chaque serveur actif est joint en tâche de fond


async def release(w: Wiring) -> None:
    await w.parts[NAME].aclose()
