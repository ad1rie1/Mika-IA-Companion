"""Outils › Apps forgées dans sa forme (``app/handmade/tabs/apps.py``, ADR 0177), à travers le vrai serveur : ses apps
en tuiles vers leur fiche, une app cassée en rouge avec sa raison, une promue le dit ; la bascule « Tableau » rend la
liste de la console ; et ce que la page dit, vide."""

from __future__ import annotations

from mika.kernel.events import Origin
from mika.plugins.forge import SWITCHED, TICKED, written_draft
from mika.plugins.forge.guide import EXAMPLE_CODE, EXAMPLE_MANIFEST
from tests.protocol.test_console_diagnostics import stop
from tests.protocol.test_console_workflows import append
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def test_apps_are_tiles_and_a_broken_one_says_why(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    stop(client, live.kernel)
    empty = drawn(client, "/inspecteur/apps")
    assert 'data-tab="apps/apps"' in empty and "Elle n’a encore écrit aucune app." in empty
    kernel, forge = live.kernel, live.kernel.ports["forge"]

    async def write():
        for name, title in (("meteo", "Carnet météo"), ("prix", "Veille des prix")):
            await forge.write(name, EXAMPLE_MANIFEST.replace("Carnet météo", title), EXAMPLE_CODE)
            await kernel.mind.append([written_draft(forge.info(name))], emitter="forge", correlation="t",
                                     origin=Origin.GENESIS)

    client.portal.call(write)
    append(client, kernel, [SWITCHED.draft(app="meteo", state="promoted"),
                            TICKED.draft(app="prix", ok=False, error="KeyError: 'prix'"),
                            SWITCHED.draft(app="prix", state="broken", reason="trois tours ratés")], "forge")
    page = drawn(client, "/inspecteur/apps")
    tiles = page.split('class="apx-tiles"', 1)[1].split("</ul>", 1)[0]
    meteo = tiles.split("Carnet météo", 1)[0].rsplit("<li", 1)[1] + tiles.split("Carnet météo", 1)[1].split("</li>")[0]
    assert "/inspecteur/fiche/app/meteo" in meteo and ">promue<" in meteo and ">active<" in meteo
    prix = tiles.split("Veille des prix", 1)[0].rsplit("<li", 1)[1] + tiles.split("Veille des prix", 1)[1].split("</li>")[0]
    assert "apx-app danger" in prix and ">cassée<" in prix and "trois tours ratés" in prix
    assert "apx-last failed" in prix and "KeyError" in prix
    assert "1 cassée" in page
    table = drawn(client, "/inspecteur/apps?vue_pg1=table")
    assert "<table" in table and "apx-tiles" not in table  # la liste de la console (son rendu à elle)
