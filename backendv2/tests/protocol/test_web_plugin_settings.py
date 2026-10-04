"""Le plugin ``web`` dans le vrai serveur (ADR 0066) : ses paramètres ont leur page dans la console, et les changer
reconfigure le client MCP — désactivé, ses outils quittent son registre ; réactivé, ils reviennent.

Le serveur de recherche est lancé pour de vrai dans sa cage (sans requête vers DuckDuckGo : se joindre et lister ses
outils ne sort pas de la machine)."""

from __future__ import annotations

import asyncio
import shutil

import pytest

from mika.plugins.web import WebParams
from tests.protocol.test_inspector_pages import html_of
from tests.protocol.test_web import bootstrap

pytestmark = pytest.mark.skipif(shutil.which("bwrap") is None or shutil.which("pasta") is None,
                                reason="bubblewrap ou pasta absent")

TOOLS = {"mcp_web_search", "mcp_web_read", "mcp_web_read_pages"}


def _wait(client, live, present: bool) -> set[str]:
    for _ in range(200):
        names = set(live.kernel.mind.registry.tools) & TOOLS
        if bool(names) == present:
            return names
        client.portal.call(asyncio.sleep, 0.05)
    raise AssertionError(f"ses outils web ne sont pas {'apparus' if present else 'partis'} : {names}")


def test_its_settings_have_a_page_and_changing_them_reconfigures_the_mcp_client(tmp_path):
    from starlette.testclient import TestClient

    from mika.adapters.llm.config import LiveGateway
    from mika.adapters.vectors import HashEmbedder
    from mika.adapters.web.app import WebConfig
    from mika.app.server import build
    from tests.protocol.test_web import ORIGIN

    app, live = build(tmp_path / "data", web=WebConfig(), gateway=LiveGateway(), embedder=HashEmbedder())
    with TestClient(app, base_url="http://localhost:8001", headers={"Origin": ORIGIN}) as client:
        bootstrap(client)
        page = "/inspecteur/reglages/comportement-web"
        assert "Recherche web" in html_of(client.get(page)) and "Actif" in html_of(client.get(page))
        assert "Pages chargées en même temps" in html_of(client.get(f"{page}?groupe=lire-des-pages"))
        assert "Entre deux recherches" in html_of(client.get(f"{page}?groupe=menager-duckduckgo"))

        assert _wait(client, live, present=True) == TOOLS  # actif d'office : joint au démarrage, sans accord
        client.portal.call(live.kernel.set_params, "web", WebParams(enabled=False))
        _wait(client, live, present=False)
        assert live.mcp.status("web") is None
        client.portal.call(live.kernel.set_params, "web", WebParams(parallel_pages=1))
        assert _wait(client, live, present=True) == {"mcp_web_search", "mcp_web_read"}
