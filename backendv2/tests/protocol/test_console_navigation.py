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
    assert menu.count('data-nav-group=') == 8  # et l'accueil, directement accessible
    for group in MENU:
        for link in group.items:
            url = '/inspecteur/' + link.target
            assert f'href="{url}"' in menu
            response = client.get(url, follow_redirects=False)
            assert response.status_code == 200, (link.label, url, response.status_code)
            ConsoleHTML(response.text).check()


def tabs_of(page, destination):
    """Les onglets d'une destination dans l'ordre où sa page les montre (sa barre d'onglets, ou le sous-menu d'une
    console sans menu d'opérateur) :
    ``(slug, titre)``."""
    tabs = []
    for nav in re.findall(r'<nav class="tabs"[^>]*>.*?</nav>', html.unescape(page), re.S):
        for slug, title in re.findall(rf'href="/inspecteur/{destination}/([^"?#]+)"[^>]*>(.*?)</a>', nav, re.S):
            tab = (slug, re.sub(r"<[^>]+>", "", title).strip())
            if tab[0] not in [t[0] for t in tabs]:
                tabs.append(tab)
    return tabs


def bar_of(page):
    """La barre d'onglets d'une page, ``(adresse, titre)`` : son titre sans son compteur."""
    nav = re.search(r'<nav class="tabs"[^>]*>(.*?)</nav>', html.unescape(page), re.S)
    if nav is None:
        return []
    bar = []
    for href, title in re.findall(r'<a class="tab[^"]*" href="([^"]+)"[^>]*>(.*?)</a>', nav.group(1), re.S):
        title = re.sub(r'<span class="(?:count|tab-n)[^"]*">.*?</span>', '', title, flags=re.S)
        bar.append((href.split('?', 1)[0], re.sub(r"<[^>]+>", "", title).strip()))
    return bar


def menu_columns(page):
    """Les groupes de pages du menu : l'adresse de chaque page à onglets, et ses onglets ``(adresse, titre)``."""
    out = {}
    for href, tabs in re.findall(r'<a class="nav-item(?: on)? nav-head" href="([^"]+)".*?<ul class="nav-tabs"[^>]*>(.*?)</ul>',
                                 primary_nav(page), re.S):
        out[href] = [(h, t.strip()) for h, t in re.findall(r'<a class="nav-tab[^"]*" href="([^"]+)"[^>]*><span>(.*?)</span>', tabs)]
    return out


def test_the_menu_and_the_tabs_say_the_same_thing(world):  # noqa: F811
    """Le menu et la barre d'onglets ne se contredisent pas (ADR 0178) : un lien vers une destination à onglets montre
    ses onglets, ceux de sa barre, dans leur ordre et sous leur nom ; une rubrique qui nomme les onglets d'une destination
    un à un (« À valider ») les nomme tous, dans leur ordre. Sauf l'annuaire des réglages."""
    client, _, _ = world
    bootstrap(client)
    columns = menu_columns(client.get('/inspecteur/').text)
    grouped = 0
    for group in MENU:
        if group.label in SHORTCUT_GROUPS:
            continue
        by_destination = {}
        for link in group.items:
            destination, _, slug = link.target.partition('/')
            by_destination.setdefault(destination, []).append((slug, link.label))
        for destination, links in by_destination.items():
            bar = bar_of(client.get(f'/inspecteur/{destination}').text)
            if links == [('', links[0][1])]:  # un lien vers la destination : sa colonne, si elle a des onglets
                assert columns.get(f'/inspecteur/{destination}', []) == bar, (group.label, destination)
                grouped += bool(bar)
                continue
            if not bar:
                # une destination sans barre d'onglets (Système) : le menu est sa seule liste de pages,
                # rien ne peut le contredire
                continue
            shown = [(f'/inspecteur/{destination}/{slug or bar[0][0].rsplit("/", 1)[1]}', label) for slug, label in links]
            assert shown == bar, (group.label, destination, shown, bar)
    # les groupes de pages de sa rubrique, des échanges, de l'activité, des outils et des connexions
    assert grouped >= 12 and len(columns) == grouped


def test_a_menu_tab_leads_to_its_page_and_lights_up(world):  # noqa: F811
    """Chaque onglet d'un groupe de pages mène à une page qui répond, et s'allume dans le menu quand on y est ; la
    destination ouverte à sa propre adresse allume son premier onglet."""
    client, _, _ = world
    bootstrap(client)
    columns = menu_columns(client.get('/inspecteur/').text)
    for head, tabs in columns.items():
        for href, title in tabs:
            page = client.get(href)
            assert page.status_code == 200, (href, page.status_code)
            lit = re.findall(r'<a class="nav-tab on" href="([^"]+)"', primary_nav(page.text))
            assert lit == [href], (href, lit)
        lit = re.findall(r'<a class="nav-tab on" href="([^"]+)"', primary_nav(client.get(head).text))
        assert lit == [tabs[0][0]], (head, lit)


@pytest.mark.parametrize(('path', 'group', 'label', 'tab'), [
    ('sens/dessins', 'Connexions extérieures', 'Ses sens', 'Dessins'),
    ('sens/camera', 'Connexions extérieures', 'Ses sens', 'Caméra'),
    ('outils/expose', 'Outils', 'Ses outils', 'Prêter à un agent'),
    ('outils/tous?outil=email_read', 'Outils', 'Ses outils', 'Ce qu'),
    ('courrier/brouillons', 'Relations & échanges', 'Courrier', 'Brouillons'),
    # « À valider » est une seule file (ADR 0177) : chacun de ses onglets allume son lien
    ('approbations/courriers', 'À valider', 'Courriers à envoyer', None),
    ('approbations/noms', 'À valider', 'Noms à relier', None),
    ('courrier/reception', 'Relations & échanges', 'Courrier', 'Réception'),
    ('vie/rythme', 'Mika', 'Humeur et corps', 'Sommeil et rythme'),
    ('reglages/comportement-memory', 'Réglages', 'Paramètres avancés', None),
    ('fiche/person/user_1', 'Relations & échanges', 'Personnes', None),
    # une fiche ouverte depuis une liste allume cette liste, pas seulement la rubrique de la fiche
    ('fiche/person/user_1?retour=/inspecteur/approbations/noms', 'À valider', 'Noms à relier', None),
])
def test_page_and_subject_keep_the_correct_menu_open(world, path, group, label, tab):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    page = client.get('/inspecteur/' + path)
    assert page.status_code == 200
    menu = primary_nav(page.text)
    # la rubrique de la page est marquée dans la barre du haut (ADR 0176) : son menu reste fermé jusqu'au clic
    assert f'<details class="nav-group active" data-nav-group="{group}">' in menu
    assert menu.count('class="nav-group active"') == 1
    current = re.findall(r'<a class="nav-item on[^"]*"[^>]*>(.*?)</a>', menu, re.S)
    assert len(current) == 1 and label in current[0]
    # dans un groupe de pages, l'onglet de la page s'allume aussi, et lui seul porte « page courante » (ADR 0178)
    lit = re.findall(r'<a class="nav-tab on"[^>]*><span>(.*?)</span>', menu)
    if tab is None:
        assert not lit
    else:
        assert len(lit) == 1 and tab in lit[0]
    assert menu.count('aria-current="page"') == 1


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
    assert 'data-tab="personnes/personnes"' in cards.text  # l'onglet est dessiné dans sa forme (ADR 0177)
    assert 'data-tab="personnes/personnes"' not in table.text
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
    # la recherche est dessinée (ADR 0121) : « Tout », puis une section par sorte de résultat (ADR 0176)
    def section(text: str) -> str:
        return re.search(r'data-pane aria-label="Pages de la console">.*?</section>', text, re.S).group()

    assert '<a href="#r-tout">Tout' in page.text
    results = section(page.text)
    assert 'href="/inspecteur/reglages/identite"' in results
    assert 'href="/inspecteur/identites"' in results
    assert 'href="/inspecteur/reglages/fournisseurs"' in section(client.get('/inspecteur/recherche?q=fournisseurs').text)
    assert 'href="/inspecteur/vie/rythme"' in section(client.get('/inspecteur/recherche?q=sommeil').text)
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
