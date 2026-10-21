"""« Lui dire où je suis » (ADR 0119), sur l'application réelle : la trame ``where`` d'un téléphone.

- une position valide s'écrit au journal, à l'adresse du compte, coordonnées et lieu en contenus ;
- une position invalide est ignorée ; une position qui n'a pas bougé (même lieu, quelques mètres) redite à chaque
  ouverture ne s'écrit pas deux fois ; une qui a bougé, si ;
- ``off`` efface la dernière position ;
- la console la montre, personne par personne, et sur sa fiche (« Sa position ») — seulement sur la fiche de qui en a
  une.
"""

from __future__ import annotations

import html

from mika.contracts import location as c
from mika.runtime.effects import with_content
from tests.protocol.test_mobile_presence import CHAT, PASSWORD, ctx, headers, pong  # noqa: F401 — la fixture
from tests.protocol.test_web import bootstrap

HOME = {"type": "where", "lat": 45.764043, "lon": 4.835659, "accuracy": 12, "label": "Rue de la République, Lyon",
        "age_ms": 1500}


def located(ctx) -> list:  # noqa: F811
    mind = ctx.live.kernel.mind
    return ctx.call(lambda: [with_content(mind, mind.decode(e)) for e in mind.store.read()
                             if e.type == c.LOCATED.name])


def test_the_phone_says_where_once_per_place_and_off_clears_it(ctx) -> None:  # noqa: F811
    token = ctx.phone()
    with ctx.client.websocket_connect(CHAT, headers=headers(token)) as ws:
        for bad in ({"type": "where", "lat": 120, "lon": 4}, {"type": "where", "lat": "45", "lon": 4},
                    {"type": "where"}):
            ws.send_json(bad)
        ws.send_json(HOME)
        ws.send_json({**HOME, "lat": HOME["lat"] + 0.0001})  # ~11 m : le téléphone redit la même place
        pong(ws, 1)
        [home] = located(ctx)
        assert home.data.handle == "user_1" and home.data.coords.text == "45.764043,4.835659"
        assert home.data.label.text == HOME["label"] and home.data.accuracy_m == 12
        ws.send_json({**HOME, "lat": 45.75, "label": "Place Bellecour, Lyon"})  # ~1,6 km plus loin
        pong(ws, 2)
        assert [e.data.label.text for e in located(ctx)] == [HOME["label"], "Place Bellecour, Lyon"]
        ws.send_json({"type": "where", "off": True})
        pong(ws, 3)
        assert len(ctx.journal(c.CLEARED)) == 1
        state = ctx.call(lambda: ctx.live.kernel.mind.frame().state(c.OWNER))
        assert not state.fixes



def test_the_console_shows_where_each_person_is(ctx) -> None:  # noqa: F811
    """Localisation : une ligne par personne, puis ce que les téléphones lui ont dit ; sur sa fiche, « Sa position »,
    qui n'apparaît pas sur la fiche de qui n'en a pas."""
    bootstrap(ctx.client, "adrien", PASSWORD)
    token = ctx.phone()
    with ctx.client.websocket_connect(CHAT, headers=headers(token)) as ws:
        ws.send_json(HOME)
        pong(ws, 1)
    [home] = located(ctx)
    page = html.unescape(ctx.client.get("/inspecteur/sens/positions").text)
    assert "Dernière position connue" in page and HOME["label"] in page and "à 12 m près" in page
    assert "Ce que les téléphones lui ont dit" in page
    fiche = ctx.client.get(f"/inspecteur/fiche/person/{home.data.person}")
    assert fiche.status_code == 200 and "onglet=position" in fiche.text
    tab = html.unescape(ctx.client.get(f"{fiche.url.path}?onglet=position").text)
    assert "Sa dernière position" in tab and HOME["label"] in tab and "45.764043,4.835659" in tab
    owner = ctx.client.get("/inspecteur/fiche/person/user_1")
    assert owner.status_code == 200 and "onglet=position" not in owner.text
