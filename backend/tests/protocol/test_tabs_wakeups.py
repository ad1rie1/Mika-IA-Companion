"""Connexions extérieures › Réveils par API dans sa forme (``app/domains/wakeup/console/tabs.py``, ADR 0177), à travers le
vrai serveur : « Déclarer un réveil » dans la barre de titre ; ses réveils en tuiles (un réveil sans clé le dit, en
avant) ; ses appels en fil, ce qu'ils apportaient et pourquoi ils attendent ; ce que la page dit, vide ; son
introduction dite une fois ; et pas de champ « nom exact » : ``?reveil=`` filtre encore, sous son titre."""

from __future__ import annotations

from mika.app.domains.wakeup.desk import WakeEndpoint, WakeupConfig
from mika.app.domains.wakeup.settings import WakeupSettings
from mika.contracts import wakeup as c
from tests.protocol.test_console_diagnostics import stop
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def test_wakeups_are_tiles_then_their_calls_with_what_they_brought(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    stop(client, live.kernel)
    empty = drawn(client, "/admin/reveils")
    assert 'data-tab="reveils/reveils"' in empty and "Aucun réveil déclaré." in empty
    assert "Aucun appel pour l'instant." in empty
    head = empty.split('class="page-head', 1)[1].split('data-tab=', 1)[0]
    assert ">Déclarer un réveil</a>" in head and "nouveau=1" in head and "gear-link" in head  # l'action, puis la roue
    # la roue est celle de la destination (ses réglages y vivent, ADR 0206), une seule fois
    assert head.count('href="/admin/reveils/parametres"') == 1
    client.portal.call(live.settings.of(WakeupSettings).save_wakeup, WakeupConfig(endpoints={
        "serre": WakeEndpoint(label="L'alerte de la serre", instructions="Résume-la.", notify=c.NOBODY),
        "cave": WakeEndpoint(label="La sonde de la cave", enabled=False)}))
    key = client.portal.call(live.parts["wakeup"].new_key, "serre", "test")
    assert client.post("/api/wake/serre", json={"text": "Il fait 41 °C dans la serre."},
                       headers={"Authorization": f"Bearer {key}"}).status_code == 202
    page = drawn(client, "/admin/reveils")
    tiles = page.split('class="wk-tiles"', 1)[1].split("</ul>", 1)[0]
    cave = tiles.split("La sonde de la cave", 1)[0].rsplit("<li", 1)[1]
    assert "off" in cave and "keyless" in cave  # désactivé, sans clé : le trait le dit
    serre = tiles.split("L'alerte de la serre", 1)[1].split("</li>", 1)[0]
    assert "1</b> en attente" in serre and "dernier appel" in serre
    call = page.split('class="sens-list sens-feed"', 1)[1]
    assert "Il fait 41 °C dans la serre." in call.split('class="wk-brought"', 1)[1].split("</p>", 1)[0]
    # pourquoi il attend en clair, le reste replié — la nuit son réveil, le jour d'être choisi : à toute heure
    assert ("Il attend :" in call or "Il peut partir" in call) and "Le détail" in call
    assert page.index('id="wk-endpoints-title"') < page.index('id="wk-calls-title"')
    # son détail replié compte ses essais accordés, sans « (s) »
    assert "0 panne, 0 départ" in call and "(s)" not in call
    # l'introduction dit l'adresse une fois (l'encart ne la redit pas) et ne renvoie pas à Paramètres : « Déclarer un
    # réveil » est dans la barre de titre, la roue la ferme
    assert page.count("POST /api/wake/") == 1 and "se règlent dans Paramètres" not in page
    # pas de champ « nom exact » suivi de « Filtrer » : la tuile d'un réveil mène à sa fiche, qui a tous ses appels
    assert '<form class="filters"' not in page and "nom exact" not in page
    one = drawn(client, "/admin/reveils?reveil=serre")  # l'adresse garde son titre et son filtre
    assert "Les appels de « serre »" in one and "Il fait 41 °C dans la serre." in one
    assert '<form class="filters"' not in one
    assert "Il fait 41 °C" not in drawn(client, "/admin/reveils?reveil=cave")
