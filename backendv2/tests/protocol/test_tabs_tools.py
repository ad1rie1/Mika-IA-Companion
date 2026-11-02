"""Outils › Prêter à un agent dans sa forme (``app/handmade/tabs/tools.py``, ADR 0177) : la page est son panneau, gardé
tel quel avec sa feuille ; l'onglet ne pose que sa marque."""

from __future__ import annotations

from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def test_lending_keeps_its_panel_and_its_stylesheet(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    page = drawn(client, "/inspecteur/outils/expose")
    assert 'data-tab="outils/expose"' in page and "/static/handmade/tools.css" in page
    assert "La console, en lecture" in page and "Ses outils prêtés" in page and "Créer un jeton" in page
    assert page.index("La console, en lecture") < page.index('data-tab="outils/expose"')  # le panneau d'abord
