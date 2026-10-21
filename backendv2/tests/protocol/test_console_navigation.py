"""La recherche globale retrouve les pages et réglages, pas seulement les objets."""
import html
import re

import pytest

from mika.app.console_menu import MENU, SHORTCUT_GROUPS
from tests.fixtures.console_html import ConsoleHTML
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def primary_nav(page):
    return re.search(r'<nav class="primary-nav.*?</nav>', html.unescape(page), re.S).group()


def test_operator_menu_links_open_real_pages(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    page = client.get('/inspecteur/')
    ConsoleHTML(page.text).check()
    menu = primary_nav(page.text)
    assert menu.count('data-nav-group=') == 7  # et l'accueil, directement accessible
    for group in MENU:
        for link in group.items:
            url = '/inspecteur/' + link.target
            assert f'href="{url}"' in menu
            response = client.get(url, follow_redirects=False)
            assert response.status_code == 200, (link.label, url, response.status_code)
            ConsoleHTML(response.text).check()


def tabs_of(page, destination):
    """Les onglets d'une destination dans l'ordre où sa page les montre (sa barre d'onglets, ou son sous-menu) :
    ``(slug, titre)``."""
    tabs = []
    for nav in re.findall(r'<nav class="(?:tabs|submenu)"[^>]*>.*?</nav>', html.unescape(page), re.S):
        for slug, title in re.findall(rf'href="/inspecteur/{destination}/([^"?#]+)"[^>]*>(.*?)</a>', nav, re.S):
            tab = (slug, re.sub(r"<[^>]+>", "", title).strip())
            if tab[0] not in [t[0] for t in tabs]:
                tabs.append(tab)
    return tabs


def test_the_menu_and_the_tabs_say_the_same_thing(world):  # noqa: F811
    """Le menu et la barre d'onglets ne se contredisent pas : dans une rubrique, une destination a un seul lien (la
    page entière), ou un lien par onglet — tous ses onglets, dans leur ordre, sous leur nom (le lien vers la
    destination elle-même : son premier onglet). Sauf les raccourcis d'« À valider » et l'annuaire des réglages."""
    client, _, _ = world
    bootstrap(client)
    for group in MENU:
        if group.label in SHORTCUT_GROUPS:
            continue
        by_destination = {}
        for link in group.items:
            destination, _, slug = link.target.partition('/')
            by_destination.setdefault(destination, []).append((slug, link.label))
        for destination, links in by_destination.items():
            if len(links) < 2:
                continue
            tabs = tabs_of(client.get(f'/inspecteur/{destination}').text, destination)
            shown = [(slug or tabs[0][0], label) for slug, label in links]
            assert shown == tabs, (group.label, destination, shown, tabs)


@pytest.mark.parametrize(('path', 'group', 'label'), [
    ('sens/dessins', 'Outils & connexions', 'Dessins'),
    ('sens/camera', 'Outils & connexions', 'Caméra'),
    ('courrier/brouillons', 'À valider', 'Brouillons de courrier'),
    ('courrier/reception', 'Relations & échanges', 'Courrier'),
    ('vie/rythme', 'Mika', 'Sommeil et rythme'),
    ('reglages/comportement-memory', 'Réglages', 'Paramètres avancés'),
    ('fiche/person/user_1', 'Relations & échanges', 'Personnes'),
    # une fiche ouverte depuis une liste allume cette liste, pas seulement la rubrique de la fiche
    ('fiche/person/user_1?retour=/inspecteur/identites/noms', 'À valider', 'Noms à relier'),
])
def test_page_and_subject_keep_the_correct_menu_open(world, path, group, label):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    page = client.get('/inspecteur/' + path)
    assert page.status_code == 200
    menu = primary_nav(page.text)
    assert f'data-nav-group="{group}" open' in menu
    current = re.findall(r'<a class="nav-item on"[^>]*>(.*?)</a>', menu, re.S)
    assert len(current) == 1 and label in current[0]


def test_her_menu_section_bears_the_name_of_her_persona(world):  # noqa: F811
    """La rubrique qui la décrit porte son nom, lu dans sa persona : jamais « Mika » écrit en dur (ADR 0070)."""
    client, live, _ = world
    bootstrap(client)
    assert 'data-nav-group="Mika"' in primary_nav(client.get('/inspecteur/').text)
    renamed = client.post('/inspecteur/reglages/identite', data={
        'csrf': client.cookies.get('csrftoken'), '_section': 'personnage', '_champs': ['name'], 'name': 'Lina'})
    assert renamed.status_code in (200, 303)
    assert client.portal.call(live.persona).name == 'Lina'
    menu = primary_nav(client.get('/inspecteur/').text)
    assert 'data-nav-group="Lina"' in menu and 'data-nav-group="Mika"' not in menu


def test_login_has_a_main_heading(world):  # noqa: F811
    client, _, _ = world
    page = client.get('/inspecteur/connexion')
    assert page.status_code == 200
    ConsoleHTML(page.text).check()


def test_people_view_switch_keeps_filter_and_subject_links(world):  # noqa: F811
    # l'annuaire des identités, onglet de la destination Personnes (dont la page d'entrée est dessinée, ADR 0121)
    client, _, _ = world
    bootstrap(client)
    cards = client.get('/inspecteur/personnes/personnes?q=adrien')
    table = client.get('/inspecteur/personnes/personnes?q=adrien&vue_pg1=table')
    for response in (cards, table):
        assert response.status_code == 200
        ConsoleHTML(response.text).check()
        assert 'href="/inspecteur/fiche/person/user_1"' in response.text
    assert 'class="now-card person-list' in cards.text  # l'onglet est dessiné (ADR 0121)
    assert 'class="now-card person-list' not in table.text
    assert 'name="vue_pg1" value="table"' in table.text
    assert '?q=adrien' in table.text
    empty = client.get('/inspecteur/personnes/personnes?q=personne-inconnue')
    assert 'personne ne correspond à « personne-inconnue »' in empty.text  # le mot de la faculté


def test_search_finds_settings_without_accents_and_preserves_subject_filter(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    page = client.get('/inspecteur/recherche?q=identite')
    assert page.status_code == 200
    ConsoleHTML(page.text).check()
    results = re.search(r'Pages de la console.*?</table>', page.text, re.S).group()
    assert 'href="/inspecteur/reglages/identite"' in results
    assert 'href="/inspecteur/identites"' in results
    providers = client.get('/inspecteur/recherche?q=fournisseurs').text
    results = re.search(r'Pages de la console.*?</table>', providers, re.S).group()
    assert 'href="/inspecteur/reglages/fournisseurs"' in results
    rhythm = client.get('/inspecteur/recherche?q=sommeil').text
    results = re.search(r'Pages de la console.*?</table>', rhythm, re.S).group()
    assert 'href="/inspecteur/vie/rythme"' in results
    assert 'Pages de la console' not in client.get('/inspecteur/recherche?q=identite&sorte=person').text
    assert 'Pages de la console' not in client.get('/inspecteur/recherche?q=aucune-page-de-ce-nom').text


def test_settings_directory_finds_pages_and_separates_advanced_settings(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    response = client.get('/inspecteur/reglages')
    assert response.status_code == 200 and '<h1>Tous les réglages</h1>' in response.text
    ConsoleHTML(response.text).check()
    directory = response.text.split('<div class="settings-directory stack">', 1)[1]
    assert 'id="reglages-avances">' in directory
    assert '/inspecteur/reglages/fournisseurs' in directory
    assert '/inspecteur/reglages/comportement-memory' in directory
    # Consulter le répertoire ne charge aucun fournisseur et ne montre aucune valeur de réglage.
    for query in ('memoire', 'mémoire'):
        page = client.get('/inspecteur/reglages/apercu', params={'q': query})
        ConsoleHTML(page.text).check()
        results = page.text.split('<div class="settings-directory stack">', 1)[1]
        assert 'id="reglages-avances" open' in results
        assert '/inspecteur/reglages/comportement-memory' in results
        assert '/inspecteur/reglages/comptes' not in results
    empty = client.get('/inspecteur/reglages/apercu?q=aucun-resultat')
    assert 'Aucun réglage ne correspond' in empty.text
    malicious = client.get('/inspecteur/reglages/apercu', params={'q': '<script>alert(1)</script>'})
    assert '<script>alert(1)</script>' not in malicious.text
