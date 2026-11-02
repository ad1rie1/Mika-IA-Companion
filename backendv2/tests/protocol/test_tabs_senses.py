"""Connexions extérieures, chaque onglet dans sa forme (``app/handmade/tabs/senses.py``, ADR 0177), à travers le vrai
serveur : la phrase d'état de la vue en tête, ses liens vers ses réglages dans la barre de titre ; un flux en panne en
bandeau ; ce que voit la caméra à côté de ses appareils ; un dessin dit pour qui (son nom, pas sa clé) et ce qu'elle y
voit ; les appareils à gauche, leurs signaux à droite ; et ce que chaque page dit, vide."""

from __future__ import annotations

from mika.contracts import camera as cam
from mika.contracts import imaging as img
from mika.contracts import rss
from mika.contracts import sensors as sen
from mika.kernel.clock import HOUR
from mika.kernel.events import Content
from mika.ports.feeds import Entry
from mika.sim.outside import FakeFeeds
from tests.fixtures.mika import connect
from tests.protocol.test_console_diagnostics import stop
from tests.protocol.test_console_workflows import append
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


class Feeds(FakeFeeds):
    """Deux flux : l'un répond, l'autre est en panne depuis quatre relevés."""

    def health(self):
        return [{"title": "Sciences", "url": "https://example.net/sciences.xml", "attempted_at": 1, "ok_at": 1,
                 "error": "", "failures": 0, "items": 2, "added": 2, "kept": 2},
                {"title": "Blog du studio", "url": "https://example.net/studio.xml", "attempted_at": 1,
                 "ok_at": 0, "error": "HTTP 503", "failures": 4, "items": 0, "added": 0, "kept": 0}]


def _life(client, live):
    bootstrap(client)
    stop(client, live.kernel)
    return live.kernel, live.kernel.mind.clock.now()


def _head(page: str) -> str:
    """La barre de titre de la page (avant ses onglets)."""
    return page.split('class="page-head', 1)[1].split('<nav class="tabs"', 1)[0]


def _pane(page: str, pane: str) -> str:
    """Un sous-onglet : jusqu'au suivant (ses détails repliés ont leurs propres sections)."""
    return page.split(f'<section id="{pane}" data-pane', 1)[1].split(" data-pane", 1)[0]


def test_feeds_say_how_she_reads_then_a_broken_feed_then_articles_with_their_pertinence(world):  # noqa: F811
    client, live, _ = world
    kernel, now = _life(client, live)
    empty = drawn(client, "/inspecteur/sens/flux")
    assert 'data-tab="sens/flux"' in empty and "Aucun flux n'est suivi" in empty
    assert "Configurer le plugin" in _head(empty) and "gear-link" in _head(empty)  # ses réglages, en roue
    feeds = Feeds()
    feeds.publish(Entry(id="e1", feed="Sciences", title="Une exoplanète habitable", link="https://example.net/1",
                        summary="Une planète rocheuse, à 40 années-lumière.", published=now - HOUR))
    feeds.publish(Entry(id="e2", feed="Sciences", title="La carte du ciel profond", link="https://example.net/2",
                        summary="Des millions de galaxies.", published=now - 2 * HOUR))
    kernel.ports["feeds"] = feeds
    append(client, kernel, [rss.NOTICED.draft(source="rss", kind="entry", entry="e1", feed="Sciences",
                                              summary=Content.of("Une exoplanète habitable"), pertinence=0.72)],
           "rss")
    page = drawn(client, "/inspecteur/sens/flux")
    # la phrase d'état ouvre la page ; le flux en panne, en un seul bandeau, mène à ses flux
    assert page.index("Relevés toutes les") < page.index('role="alert"') < page.index('class="person-tiles"')
    alert = page.split('role="alert"', 1)[1].split("</p>", 1)[0]
    assert "1 flux ne répond plus" in alert and "Blog du studio (HTTP 503)" in alert and 'href="#flux-feeds"' in alert
    # les articles : celui qu'elle a remarqué, sa pertinence en chiffre et en jauge, son résumé à lire
    articles = _pane(page, "flux-articles")
    noticed = articles.split("Une exoplanète habitable", 1)[1].split("</li>", 1)[0]
    assert ">remarqué<" in noticed and "0.72" in noticed and "sens-score-bar" in noticed
    assert "Une planète rocheuse" in noticed
    passed = articles.split("La carte du ciel profond", 1)[1].split("</li>", 1)[0]
    assert ">laissé passer<" in passed and "(estimée)" in passed
    # ses flux : celui en panne, son erreur ; son dernier relevé, replié
    mine = _pane(page, "flux-feeds")
    broken = mine.split("Blog du studio", 1)[0].rsplit("<li", 1)[1]
    assert "flux-feed broken" in broken and "HTTP 503" in mine and "Son dernier relevé" in mine
    assert "Une exoplanète habitable" in _pane(page, "flux-noticed")


def test_camera_shows_what_she_sees_beside_her_devices_and_never_an_image(world):  # noqa: F811
    client, live, _ = world
    kernel, _ = _life(client, live)
    empty = drawn(client, "/inspecteur/sens/camera")
    assert 'data-tab="sens/camera"' in empty and "Aucun appareil ne s'est encore connecté" in empty
    assert "elle n'a encore rien vu" in empty and "Connecter une caméra" in _head(empty)
    kernel.ports["camera"].put("salon", "image/jpeg", b"\xff" * 4096)
    append(client, kernel, [cam.SEEN.draft(source="camera", kind="view", device="salon", digest="d1", notable=True,
                                           summary=Content.of("Adrien est rentré et pose son sac."), pertinence=0.8)],
           "camera")
    page = drawn(client, "/inspecteur/sens/camera")
    views, devices = page.split('id="cam-views-title"', 1)[1], page.split('id="cam-devices-title"', 1)[1]
    seen = views.split("Adrien est rentré", 1)[0].rsplit("<li", 1)[1]
    assert "cam-view notable" in seen and "quelque chose se passe" in seen and ">salon<" in seen
    assert page.index('id="cam-views-title"') < page.index('id="cam-devices-title"') < page.index('id="cam-looks-title"')
    assert "cam-dev live" in devices and "en direct" in devices and "image/jpeg" in devices
    assert "<img" not in page.split('data-tab="sens/camera"', 1)[1]


def test_a_drawing_says_for_whom_by_name_and_what_she_sees_in_it(world):  # noqa: F811
    client, live, _ = world
    kernel, _ = _life(client, live)
    empty = drawn(client, "/inspecteur/sens/dessins")
    assert 'data-tab="sens/dessins"' in empty and "aucun dessin pour l'instant" in empty
    client.portal.call(connect, kernel, "alice", "Alice")
    append(client, kernel, [img.REQUESTED.draft(job="j1", target="alice", person="alice", quality="normal",
                                                prompt=Content.of("Un chat roux endormi sur des livres."))],
           "imaging")
    append(client, kernel, [img.DRAWN.draft(job="j1", person="alice", file="f1", target="alice",
                                            name=Content.of("chat.png"), mime="image/png", size=1000, digest="x",
                                            caption=Content.of("Un chat roulé en boule."), backend="local")],
           "imaging")
    page = drawn(client, "/inspecteur/sens/dessins")
    item = page.split("Un chat roux endormi", 1)[0].rsplit("<li", 1)[1] + page.split("Un chat roux endormi", 1)[1]
    item = item.split("</li>", 1)[0]
    assert "prêt, pas encore montré" in item and ">Alice</a>" in item and "/inspecteur/fiche/person/alice" in item
    assert "Ce qu'elle y voit" in item and "Un chat roulé en boule." in item and ">alice<" not in item
    assert "Brancher un fournisseur" in _head(page) and "Régler ses dessins" in _head(page)


def test_devices_on_the_left_filter_the_page_and_their_signals_read_on_the_right(world):  # noqa: F811
    client, live, _ = world
    kernel, _ = _life(client, live)
    empty = drawn(client, "/inspecteur/sens/appareils")
    assert 'data-tab="sens/appareils"' in empty and "Aucun appareil n’a encore rien signalé" in empty
    append(client, kernel, [
        sen.SENSED.draft(source="sensors", kind="signal", device="sonnette", summary=Content.of("On a sonné."),
                         pertinence=0.7, emotion="surprised", intensity=0.4),
        sen.SENSED.draft(source="sensors", kind="signal", device="thermostat", summary=Content.of("Il fait 17 °C."),
                         pertinence=0.3)], "sensors")
    page = drawn(client, "/inspecteur/sens/appareils")
    left, right = page.split('id="dev-devices-title"', 1)[1], page.split('id="dev-signals-title"', 1)[1]
    assert page.index('id="dev-devices-title"') < page.index('id="dev-signals-title"')
    assert "sonnette" in left.split('id="dev-signals-title"', 1)[0] and "appareil=sonnette" in left
    rang = right.split("On a sonné.", 1)[0].rsplit("<li", 1)[1]
    assert "sw-surprised" in rang  # ce que ça pourrait lui faire, en couleur
    one = drawn(client, "/inspecteur/sens/appareils?appareil=sonnette")
    assert "dev-one on" in one and "Tous les appareils" in one and "Il fait 17 °C." not in one
