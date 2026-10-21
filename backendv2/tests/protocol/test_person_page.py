"""La vue d'ensemble d'une personne (``app/person.py``), à travers le vrai serveur : le premier onglet de sa fiche,
ouvert par défaut, qui croise ce qu'elle vit avec elle — son ressenti, leur histoire, ce qu'elle sait, leurs derniers
mots — ; l'en-tête, les actions et les onglets de la fiche restent ; une lecture qui échoue tait sa carte, jamais la
fiche."""

from __future__ import annotations

import html
import re

from mika.app.handmade import person
from mika.contracts import memory as memory_c
from mika.kernel.clock import DAY
from mika.kernel.events import Content, Origin
from tests.fixtures.console_html import ConsoleHTML
from tests.protocol.test_now_page import THOUGHT, chat, think
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

PAGE = "/inspecteur/fiche/person/user_1"
MOMENT = "Son concert de guitare, jeudi soir"
SOUVENIR = "Il a calé l'intro du concert après trois répétitions"


def note(client, live) -> None:
    async def go():
        now = live.kernel.mind.clock.now()
        await live.kernel.mind.append([
            memory_c.EVENT_NOTED.draft(text=Content.of(MOMENT), when=now + 2 * DAY, about=("user_1",),
                                       told_by=("user_1",), importance=0.8),
            # un souvenir n'a pas d'origine (seuls ceux nés d'un mensonge en ont une) : il se montre quand même
            memory_c.REMEMBERED.draft(text=Content.of(SOUVENIR), about=("user_1",), told_by=("user_1",), secret=True)],
            emitter="memory", origin=Origin.GENESIS, correlation="test-une-personne")
    client.portal.call(go)


def test_only_an_operator_sees_a_person(world):  # noqa: F811
    client, live, _ = world
    page = client.get(PAGE, follow_redirects=False)
    assert page.status_code == 303 and page.headers["location"].endswith("/inspecteur/connexion")
    assert client.get(f"{person.FRAGMENT}/user_1").status_code == 401
    assert client.get(f"{person.BASE}/user_1", follow_redirects=False).headers["location"].endswith("/connexion")
    async def guest():
        account = await live.accounts.create("bea", "un-autre-mot-de-passe", operator=False)
        return await live.accounts.open_session(account)
    client.cookies.set("sessionid", client.portal.call(guest))
    assert client.get(PAGE, follow_redirects=False).status_code == 303


def test_the_page_crosses_what_she_lives_with_a_person(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    chat(client, "salut ! je reviens d'un concert")
    think(client, live)
    note(client, live)
    page = client.get(PAGE)
    assert page.status_code == 200
    assert "script-src 'self'" in page.headers["content-security-policy"]
    ConsoleHTML(page.text).check()
    text = html.unescape(page.text)
    assert "<h1>adrien</h1>" in text
    # la vue d'ensemble est le premier onglet, ouvert ; les onglets des facultés suivent, l'en-tête et ses actions
    # restent (la proximité, l'oubli)
    tabs = re.findall(r'<a class="tab( on)?" href="([^"]+)"[^>]*>([^<]+)<', text)
    assert tabs[0] == (" on", PAGE, "Vue d'ensemble") and ("", f"{PAGE}?onglet=echanges", "Échanges") in tabs
    # ce qu'elle résume est rangé au bout de la barre, « Le détail »
    assert not any("onglet=lien" in href for _, href, _ in tabs)
    more = re.search(r'<details class="tabs-more">.*?</details>', text, re.S).group()
    assert all(f"onglet={tab}" in more for tab in ("synthese", "lien", "devine", "affect", "pensees_personne"))
    assert "Fixer la proximité" in text and "Retape « adrien » pour confirmer" in text
    # l'en-tête est dessiné : son nom, ce qu'elle est pour elle, par où elles se parlent, ce qu'elle ferait envers
    # elle — plus les clés et les certitudes en vrac
    assert 'class="person-head' in text and 'class="person-avatar"' in text
    assert "1 adresse · web, vérifiée" in text and "Que ferait-elle envers adrien maintenant ?" in text
    assert "canal principal" not in text and "vue pour la première fois" not in text
    assert re.search(r'<a class="nav-item on" href="/inspecteur/personnes"', text)
    assert " style=" not in text and not re.search(r"<script(?![^>]*\bsrc=)", text)
    assert "/static/handmade/person.css" in text
    assert f'data-now-live="{person.FRAGMENT}/user_1"' in text
    # qui elle est pour elle : sa propriétaire, ce qu'elle ressent envers elle
    assert '<span class="now-tag owner">propriétaire</span>' in text and "Ce qu'elle ressent envers adrien" in text
    # leur histoire : aujourd'hui, ils ont échangé (la case du jour est pleine)
    assert re.search(r'<rect class="cal l1[^"]* today"', text)
    # ce qu'elle sait : le moment de sa vie qui vient ; ce qui reste en suspens : la pensée qu'elle a pour lui
    assert MOMENT in text and THOUGHT in text
    assert SOUVENIR in text and '<span class="danger">secret</span>' in text
    # « de », « que » s'élident devant son nom
    assert "Ce qu'elle sait d'adrien" in text
    # leurs derniers mots, dans l'ordre, et le pourquoi de sa réponse
    assert text.index("salut ! je reviens d'un concert") < text.index('href="/inspecteur/parole/')
    assert "Impossible de lire" not in text


def test_the_other_tabs_stay_as_they_were(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    tab = client.get(f"{PAGE}?onglet=synthese")
    assert tab.status_code == 200
    ConsoleHTML(tab.text).check()
    # un onglet replié s'ouvre toujours ; le menu « Le détail » dit lequel
    assert '<summary class="tab on">Le détail · Synthèse' in html.unescape(tab.text)
    # l'en-tête dessiné reste sur chaque onglet ; la vue d'ensemble, non
    assert 'class="person-head' in tab.text and "now-hero" not in tab.text
    # l'adresse courte d'une personne mène à sa fiche
    short = client.get(f"{person.BASE}/user_1", follow_redirects=False)
    assert short.status_code == 303 and short.headers["location"] == PAGE


def test_an_unknown_address_has_no_overview(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    assert client.get(f"{person.FRAGMENT}/personne-inconnue").status_code == 404


def test_the_fragment_is_the_body_alone(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    think(client, live)
    fragment = client.get(f"{person.FRAGMENT}/user_1")
    assert fragment.status_code == 200
    assert "<html" not in fragment.text and "<h1" not in fragment.text
    assert "data-now-stamp" in fragment.text and THOUGHT in html.unescape(fragment.text)


def test_a_failing_reading_silences_its_card_not_the_page(world, monkeypatch):  # noqa: F811
    client, _, _ = world
    bootstrap(client)

    def broken(look, who):
        raise RuntimeError("lecture cassée")

    monkeypatch.setattr(person, "PARTS", tuple((k, broken if k == "knows" else fn) for k, fn in person.PARTS))
    page = client.get(PAGE)
    assert page.status_code == 200
    ConsoleHTML(page.text).check()
    assert "Impossible de lire sa mémoire" in html.unescape(page.text)
    assert page.text.count("Impossible de lire") == 1


def test_a_failing_overview_falls_back_on_the_tabs(world, monkeypatch):  # noqa: F811
    client, _, _ = world
    bootstrap(client)

    def broken(self, ui, key):
        raise RuntimeError("vue cassée")

    monkeypatch.setattr(person.PersonOverview, "render", broken)
    page = client.get(PAGE)
    assert page.status_code == 200
    ConsoleHTML(page.text).check()
    assert '<summary class="tab on">Le détail · Synthèse' in html.unescape(page.text)


def test_de_and_que_elide_before_a_vowel():
    assert person.elided("de", "Adrien") == "d'Adrien" and person.elided("de", "Béa") == "de Béa"
    assert person.elided("que", "Élise") == "qu'Élise" and person.elided("que", "Sam") == "que Sam"


def test_exchanges_are_a_conversation(world):  # noqa: F811
    """Échanges, dessiné : la conversation dans l'ordre, sa réponse à droite avec son pourquoi, le message reçu à
    gauche avec ce qu'il est devenu — les données de la faculté du fil, une autre forme."""
    client, _, _ = world
    bootstrap(client)
    chat(client, "salut ! je reviens d'un concert")
    tab = client.get(f"{PAGE}?onglet=echanges")
    assert tab.status_code == 200
    ConsoleHTML(tab.text).check()
    text = html.unescape(tab.text)
    assert 'class="tab on" href="/inspecteur/fiche/person/user_1?onglet=echanges"' in text
    assert 'class="now-card person-chat"' in text and 'class="person-day"' in text
    theirs = text.index('<li class="theirs')
    mine = text.index('<li class="mine')
    assert theirs < mine  # dans l'ordre : son message, puis sa réponse
    assert "salut ! je reviens d'un concert" in text[theirs:mine] and "répondue → n°" in text[theirs:mine]
    assert re.search(r'href="/inspecteur/parole/\d+">pourquoi \?</a>', text[mine:])
    # rien de la table d'origine : la même donnée, une autre forme
    assert '<table class="tbl">' not in text


def test_memory_is_four_cards(world):  # noqa: F811
    """Mémoire, dessinée : les moments de sa vie, ses promesses, ce qu'elle croit, ses souvenirs — chaque élément avec
    ce qu'il est (un secret) et son détail ; la recherche de la faculté reste."""
    client, live, _ = world
    bootstrap(client)
    note(client, live)
    tab = client.get(f"{PAGE}?onglet=memoire")
    assert tab.status_code == 200
    ConsoleHTML(tab.text).check()
    text = html.unescape(tab.text)
    for kind in ("moments", "promesses", "croyances", "souvenirs"):
        assert f"person-list kind-{kind}" in text, kind
    moments, souvenirs = text.index("kind-moments"), text.index("kind-souvenirs")
    assert MOMENT in text[moments:souvenirs] and SOUVENIR in text[souvenirs:]
    assert '<span class="now-tag danger">secret</span>' in text[souvenirs:] and "Le détail" in text[souvenirs:]
    assert 'name="q"' in text and '<table class="tbl">' not in text
    nothing = html.unescape(client.get(f"{PAGE}?onglet=memoire&q=rien-de-tel").text)
    assert "aucun résultat pour cette recherche" in nothing and SOUVENIR not in nothing


def test_every_list_tab_is_drawn(world):  # noqa: F811
    """Adresses, Fichiers, Pièces reçues, Buts, Projets : des cartes, plus de tableau — les données de leur faculté,
    vides comprises (leur phrase d'absence)."""
    client, live, _ = world
    bootstrap(client)
    chat(client)
    for tab, expected in (("adresses", "Ses adresses"), ("fichiers", "elle ne lui a encore envoyé aucun fichier"),
                          ("pieces", "elle ne lui a encore rien envoyé"),
                          ("buts", "rien d'entrepris pour cette personne ni à son sujet"),
                          ("projets", "aucun projet pour cette personne ni à son sujet")):
        page = client.get(f"{PAGE}?onglet={tab}")
        assert page.status_code == 200, tab
        ConsoleHTML(page.text).check()
        text = html.unescape(page.text)
        assert 'class="now-page person-tab"' in text and '<table class="tbl">' not in text, tab
        assert expected in text, tab
    # une adresse : son nom mène à sa fiche, sa confiance est une étiquette
    addresses = html.unescape(client.get(f"{PAGE}?onglet=adresses").text)
    assert re.search(r'<p class="person-entry-title"><a href="/inspecteur/fiche/handle/user_1">', addresses)


def test_folded_tabs_are_drawn_and_keep_their_forms(world):  # noqa: F811
    """Le détail (Synthèse, Lien, Ce qu'elle devine, Affect, Pensées) : bloc par bloc dans le vocabulaire des pages
    dessinées ; un formulaire de la faculté (fixer la proximité) reste à la console, avec son jeton."""
    client, live, _ = world
    bootstrap(client)
    chat(client)
    think(client, live)
    for tab in ("synthese", "lien", "devine", "affect", "pensees_personne"):
        page = client.get(f"{PAGE}?onglet={tab}")
        assert page.status_code == 200, tab
        ConsoleHTML(page.text).check()
        assert 'class="now-page person-tab"' in page.text, tab
    link = client.get(f"{PAGE}?onglet=lien").text
    assert 'name="csrf"' in link and link.index('class="now-page person-tab"') < link.rindex("social.proximite")
    assert THOUGHT in html.unescape(client.get(f"{PAGE}?onglet=pensees_personne").text)
