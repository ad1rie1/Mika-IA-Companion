"""Le plugin ``web`` branché sur le vrai client MCP (ADR 0066), son serveur dans la vraie cage — ici **sans
réseau** : les tests ne sortent pas.

Actif, son serveur est joint et ses outils sont offerts **sans que l'opérateur ait rien approuvé** ; ils répondent
en français (DuckDuckGo injoignable se dit, une adresse de cette machine ne se lit pas, plusieurs pages à la fois
aussi) ; désactivé, après ``reconfigure`` (ce que fait le serveur quand ses paramètres changent), il n'y a plus
rien — et réactivé avec une page à la fois, ``read_pages`` n'est plus proposé."""

from __future__ import annotations

import shutil

import pytest

from mika.adapters.mcp.config import McpConfig
from mika.adapters.mcp.hub import McpHub
from mika.adapters.mcp.system import Provided, SystemServers
from mika.app import system_mcp
from mika.kernel.schema import problems
from mika.plugins import web

pytestmark = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap absent")


class Plugin:
    """Les paramètres du plugin, que le test change comme la console les change."""

    def __init__(self) -> None:
        self.params = web.WebParams()
        self.reviews: dict = {}

    def provided(self) -> dict[str, Provided]:
        out = system_mcp.provided(lambda owner: self.params)
        return {k: Provided(v.spec.model_copy(update={"network": "aucun"}), v.tools) for k, v in out.items()}

    async def save(self, reviews) -> None:
        self.reviews = reviews


async def test_the_web_plugin_serves_her_through_the_mcp_client_when_active(tmp_path):
    plugin = Plugin()
    system = SystemServers(plugin.provided)
    hub = McpHub(lambda: system.config(McpConfig()), lambda: system.reviews(plugin.reviews),
                 system.saving(plugin.save), local_root=tmp_path / "mcp")
    try:
        ok, message = await hub.test("web")
        assert ok and "mika-web" in message and "3 outil(s)" in message and "à regarder" not in message, message
        offered = {t.name: t for t in hub.offered()}  # aucun accord de l'opérateur : ce sont des outils système
        assert set(offered) == {"mcp_web_search", "mcp_web_read", "mcp_web_read_pages"}
        assert all(t.nature == "lecture" and t.approval == "aucun" for t in offered.values())
        assert problems(offered["mcp_web_read_pages"].schema, {"urls": ["https://a.fr/", "https://b.fr/"]}) == []
        assert problems(offered["mcp_web_read_pages"].schema, {"urls": "https://a.fr/"})

        got = await hub.call("web", "search", {"query": "actualités"})
        assert not got.ok and got.reached and "joindre DuckDuckGo" in got.text
        local = await hub.call("web", "read", {"url": "http://127.0.0.1:8001/"})
        assert not local.ok and local.reached and "réseau local" in local.text
        several = await hub.call("web", "read_pages", {"urls": ["http://10.0.0.1/", "https://absente.exemple/"]})
        assert not several.ok and several.reached and "aucune de ces pages" in several.text
        assert plugin.reviews == {}  # rien n'a été rangé pour lui

        plugin.params = web.WebParams(enabled=False)
        await hub.reconfigure()
        assert hub.offered() == [] and hub.status("web") is None

        plugin.params = web.WebParams(parallel_pages=1)
        await hub.reconfigure()
        ok, message = await hub.test("web")
        assert ok and "2 outil(s)" in message, message
        assert {t.name for t in hub.offered()} == {"mcp_web_search", "mcp_web_read"}
    finally:
        await hub.aclose()
