"""La navigation de la console : le menu fait foi (ADR 0178, 0202) — un nom par page, un fil d'Ariane qui part de sa
rubrique, Système en trois colonnes —, et la recherche globale retrouve les pages et les réglages, pas seulement les
objets."""
import html
import re

import pytest
from starlette.testclient import TestClient

from mika.adapters.llm.config import LiveGateway
from mika.adapters.vectors import HashEmbedder
from mika.adapters.web.app import WebConfig
from mika.app.console import NAVIGATION
from mika.app.console_menu import MENU, SHORTCUT_GROUPS, menu_for
from mika.app.server import build
from mika.contracts import email as email_c
from mika.inspector.catalog import menu_place
from mika.kernel.events import Content, Origin
from mika.plugins.forge import written_draft
from mika.plugins.forge.guide import EXAMPLE_CODE, EXAMPLE_MANIFEST
from tests.fixtures.console_html import ConsoleHTML
from tests.fixtures.courrier import NOW, mailbox
from tests.protocol.test_console_operator import converse
from tests.protocol.test_wakeup_web import configure as declare_wakeup
from tests.protocol.test_web import ORIGIN, bootstrap, world  # noqa: F401 — fixture partagée

#: le nom de chaque rubrique dans la barre du haut ; la sienne porte le nom de sa persona (Mika dans ces essais)
RUBRICS = {"Mika"} | {g.short or g.label for g in MENU if g.label and not g.her}


def primary_nav(page):
    return re.search(r'<nav class="primary-nav.*?</nav>', html.unescape(page), re.S).group()


def home_link(target):
    """Le lien du menu où vit une page : celui qu'elle allume, et d'où part son fil (``catalog.menu_place``)."""
    place = menu_place(MENU, NAVIGATION, target)
    return MENU[place[0]].items[place[1]] if place else None


def trail_of(page):
    """Le fil d'Ariane d'une page, ``(texte, adresse)`` par niveau, sans le retour dit à part."""
    nav = re.search(r'<nav class="crumbs"[^>]*>(.*?)</nav>', html.unescape(page), re.S)
    if nav is None:
        return []
    levels = []
    for part in nav.group(1).split('<span aria-hidden="true">·</span>', 1)[0].split('<span aria-hidden="true">/</span>'):
        link = re.match(r'\s*<a href="([^"]*)"[^>]*>(.*?)</a>\s*$', part, re.S)
        text = re.sub(r"<[^>]+>", "", link.group(2) if link else part).strip()
        if text:
            levels.append((text, link.group(1) if link else ""))
    return levels


def back_of(page):
    """Le retour dit à part au bout du fil (« ← Retour à la liste ») : ``(texte, adresse)``."""
    found = re.search(r'<a href="([^"]+)" class="crumbs-back"><span aria-hidden="true">←</span> (.*?)</a>',
                      html.unescape(page))
    return (found.group(2), found.group(1)) if found else None


def texts(trail):
    return [text for text, _href in trail]


def test_operator_menu_links_open_real_pages(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    page = client.get('/admin/')
    ConsoleHTML(page.text).check()
    menu = primary_nav(page.text)
    assert menu.count('data-nav-group=') == 8  # et l'accueil, directement accessible
    served = {link.target for group in menu_for(None) for link in group.items}
    for group in MENU:
        for link in group.items:
            url = '/admin/' + link.target
            # sans dossier de rapports, Simulations n'est pas au menu, mais son adresse répond (C8-12)
            assert (f'href="{url}"' in menu) == (link.target in served), link.label
            response = client.get(url, follow_redirects=False)
            assert response.status_code == 200, (link.label, url, response.status_code)
            ConsoleHTML(response.text).check()


def tabs_of(page, destination):
    """Les onglets d'une destination dans l'ordre où sa page les montre (sa barre d'onglets, ou le sous-menu d'une
    console sans menu d'opérateur) :
    ``(slug, titre)``."""
    tabs = []
    for nav in re.findall(r'<nav class="tabs"[^>]*>.*?</nav>', html.unescape(page), re.S):
        for slug, title in re.findall(rf'href="/admin/{destination}/([^"?#]+)"[^>]*>(.*?)</a>', nav, re.S):
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
    un à un (« À valider ») les nomme tous, dans leur ordre. Sauf l'annuaire des réglages, et les liens vers une page qui
    vit dans une autre rubrique (Système › Journaux mène aux historiques, ADR 0202)."""
    client, _, _ = world
    bootstrap(client)
    columns = menu_columns(client.get('/admin/').text)
    grouped = 0
    for group in MENU:
        if group.label in SHORTCUT_GROUPS:
            continue
        by_destination = {}
        for link in group.items:
            if home_link(link.target) is not link:
                continue
            destination, _, slug = link.target.partition('/')
            by_destination.setdefault(destination, []).append((slug, link.label))
        for destination, links in by_destination.items():
            bar = bar_of(client.get(f'/admin/{destination}').text)
            if links == [('', links[0][1])]:  # un lien vers la destination : sa colonne, si elle a des onglets
                assert columns.get(f'/admin/{destination}', []) == bar, (group.label, destination)
                grouped += bool(bar)
                continue
            if not bar:
                # une destination sans barre d'onglets (Système) : le menu est sa seule liste de pages,
                # rien ne peut le contredire
                continue
            shown = [(f'/admin/{destination}/{slug or bar[0][0].rsplit("/", 1)[1]}', label) for slug, label in links]
            assert shown == bar, (group.label, destination, shown, bar)
    # les groupes de pages de sa rubrique, des échanges, de l'activité, des outils et des connexions, et les trois
    # colonnes de Système
    assert grouped >= 12 and len(columns) == grouped + 3


def test_a_menu_tab_leads_to_its_page_and_lights_up(world):  # noqa: F811
    """Chaque onglet d'un groupe de pages mène à une page qui répond, et s'allume dans le menu quand on y est ; la
    destination ouverte à sa propre adresse allume son premier onglet."""
    client, _, _ = world
    bootstrap(client)
    columns = menu_columns(client.get('/admin/').text)
    for head, tabs in columns.items():
        for href, title in tabs:
            page = client.get(href)
            assert page.status_code == 200, (href, page.status_code)
            lit = re.findall(r'<a class="nav-tab on" href="([^"]+)"', primary_nav(page.text))
            # une page rangée dans une autre rubrique (Système › Journaux › l'historique des réglages) y allume son
            # lien à elle, pas cet onglet
            crossing = head.startswith('/admin/systeme/') and not href.startswith('/admin/systeme/')
            assert lit == ([] if crossing else [href]), (href, lit)
        lit = re.findall(r'<a class="nav-tab on" href="([^"]+)"', primary_nav(client.get(head).text))
        assert lit == [tabs[0][0]], (head, lit)


@pytest.mark.parametrize(('path', 'group', 'label', 'tab'), [
    ('sens/dessins', 'Connexions extérieures', 'Ses sens', 'Dessins'),
    ('sens/camera', 'Connexions extérieures', 'Ses sens', 'Caméra'),
    ('outils/expose', 'Outils', 'Ses outils', 'Prêter à un agent'),
    ('outils/tous?outil=email_read', 'Outils', 'Ses outils', 'Ce qu'),
    ('courrier/brouillons', 'Relations & échanges', 'Courrier', 'Ses brouillons'),
    # « À valider » est une seule file (ADR 0177) : chacun de ses onglets allume son lien
    ('approbations/courriers', 'À valider', 'Courriers à envoyer', None),
    ('approbations/rapprochements', 'À valider', 'Rapprochements', None),
    ('courrier/reception', 'Relations & échanges', 'Courrier', 'Réception'),
    ('vie/rythme', 'Mika', 'Humeur et corps', 'Sommeil et rythme'),
    ('reglages/comportement-memory', 'Réglages', 'Paramètres avancés', None),
    ('fiche/person/user_1', 'Relations & échanges', 'Personnes', None),
    # une fiche ouverte depuis une liste allume cette liste, pas seulement la rubrique de la fiche
    ('fiche/person/user_1?retour=/admin/approbations/rapprochements', 'À valider', 'Rapprochements', None),
    # Système en colonnes (ADR 0202) : la colonne s'allume, et la page dedans ; un événement allume son journal
    ('systeme/operations', 'Système', 'Journaux', 'Gestes audités'),
    ('evenement/1', 'Système', 'Journaux', None),
    # l'historique des réglages vit dans Réglages : Système › Journaux y mène sans le lui prendre
    ('reglages/journal', 'Réglages', 'Historique des réglages', None),
    ('approbations/historique', 'À valider', 'Historique des autorisations', None),
    # Carte et téléphone a son lien (ADR 0197), ses six pages derrière lui (ADR 0245)
    ('reglages/itineraires', 'Réglages', 'Carte et téléphone', None),
    # les réglages d'un plugin, derrière la roue de sa destination (ADR 0206) : elle s'allume, aucun de ses onglets
    ('teams/parametres', 'Relations & échanges', 'Teams', None),
    ('outils/parametres', 'Outils', 'Ses outils', None),
    ('sens/parametres-transcription', 'Connexions extérieures', 'Ses sens', None),
    ('reveils/parametres', 'Connexions extérieures', 'Réveils par API', None),
])
def test_page_and_subject_keep_the_correct_menu_open(world, path, group, label, tab):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    page = client.get('/admin/' + path)
    assert page.status_code == 200
    assert page.url.path == '/admin/' + path.split('?', 1)[0]  # la page même, pas une redirection ailleurs
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


def test_the_menu_is_the_reference_one_name_per_page(world):  # noqa: F811
    """C1-05, C9-07, C9-08 (ADR 0202) : chaque lien du menu nomme sa page comme elle se nomme — son fil d'Ariane ou son
    titre reprend le libellé du lien ; une destination porte le nom de son lien ; « Comptes » et « Gestes audités »
    disent ce qu'il y a derrière (tous les comptes, les gestes de chacun)."""
    client, _, _ = world
    bootstrap(client)
    for group in MENU:
        for link in group.items:
            if not link.target:
                continue  # l'accueil
            page = html.unescape(client.get(f'/admin/{link.target}').text)
            title = re.sub(r"<[^>]+>", "", re.search(r'<h1[^>]*>(.*?)</h1>', page, re.S).group(1))
            shown = texts(trail_of(page))
            assert link.label in shown or link.label.casefold() in title.casefold(), (link.label, shown, title)
    hints = {link.label: link.hint for group in MENU for link in group.items}
    assert hints["Comptes"] == "Qui se connecte, qui pilote la console" and "Comptes opérateurs" not in hints
    assert "Gestes audités" in hints and "Actions des opérateurs" not in hints
    labels = {d.key: d.label for group in NAVIGATION for d in group.items}
    assert (labels["sens"], labels["buts"], labels["outils"]) == ("Ses sens", "Buts et rappels", "Ses outils")


def system_columns(page):
    """Les colonnes du menu Système, dans l'ordre : ``(nom, [(adresse, titre)])``."""
    group = re.search(r'data-nav-group="Système">.*?</details>', primary_nav(page), re.S).group()
    heads = re.findall(r'<a class="nav-item[^"]*nav-head" href="[^"]+"[^>]*><span class="nav-item-label">(.*?)</span>'
                       r'.*?<ul class="nav-tabs"[^>]*>(.*?)</ul>', group, re.S)
    return [(name.strip(), re.findall(r'<a class="nav-tab[^"]*" href="([^"]+)"[^>]*><span>(.*?)</span>', tabs))
            for name, tabs in heads]


def test_system_reads_in_three_columns_and_its_journals_lead_to_the_histories(world):  # noqa: F811
    """Q10 (ADR 0202) : le menu Système en trois colonnes — Surveiller, Journaux, Anatomie —, chacune son nom puis ses
    pages ; Journaux mène aussi aux historiques des réglages et des autorisations, qui restent dans leur rubrique (leur
    fil en part). Chaque page de Système dit sa colonne dans son fil."""
    client, _, _ = world
    bootstrap(client)
    columns = system_columns(client.get('/admin/').text)
    assert [name for name, _tabs in columns] == ["Surveiller", "Journaux", "Anatomie"]
    shown = dict(columns)
    assert [title for _href, title in shown["Journaux"]] == [
        "Journal d’événements", "Gestes audités", "Historique des réglages", "Historique des autorisations"]
    assert ('/admin/reglages/journal', 'Historique des réglages') in shown["Journaux"]
    assert ('/admin/approbations/historique', 'Historique des autorisations') in shown["Journaux"]
    # sans dossier de rapports (le monde de ces essais, l'unité de service), Simulations n'est pas au menu (C8-12)
    assert len(shown["Surveiller"]) == 7  # plus d'écrans du monde (ADR 0319)
    assert [t for _h, t in shown["Anatomie"]] == ["Diagnostic avancé", "Contributions", "Toutes les vues"]
    for name, tabs in columns:
        for href, _title in tabs:
            if href.startswith('/admin/systeme/'):
                assert texts(trail_of(client.get(href).text)) == ["Système", name], href
    assert texts(trail_of(client.get('/admin/reglages/journal').text)) == ["Réglages", "Historique des réglages"]
    assert texts(trail_of(client.get('/admin/approbations/historique').text)) == ["À valider"]


def test_the_old_console_address_leads_to_the_same_page_under_admin(world):  # noqa: F811
    """ADR 0237 : la console vit sous /admin ; /inspecteur et tout ce qui est dessous mènent à la même page (308 : la
    méthode et la requête suivent), même sans session, et /admin/souvenirs est l'adresse courte des souvenirs."""
    client, _, _ = world
    for old, new in (('/inspecteur', '/admin/'), ('/inspecteur/', '/admin/'),
                     ('/inspecteur/memoire/souvenirs?q=chat&vue_pg1=table', '/admin/memoire/souvenirs?q=chat&vue_pg1=table'),
                     ('/inspecteur/parole/12', '/admin/parole/12')):
        moved = client.get(old, follow_redirects=False)
        assert moved.status_code == 308 and moved.headers['location'] == new, old
    posted = client.post('/inspecteur/reglages/canaux/regler', data={'csrf': 'x'}, follow_redirects=False)
    assert posted.status_code == 308 and posted.headers['location'] == '/admin/reglages/canaux/regler'
    bootstrap(client)
    short = client.get('/admin/souvenirs', follow_redirects=False)
    assert short.status_code == 301 and short.headers['location'] == '/admin/memoire/souvenirs'
    assert client.get('/inspecteur/memoire/souvenirs').status_code == 200  # suivie jusqu'au bout, la page répond


def test_without_a_reports_folder_simulations_leave_the_menu_but_keep_their_address(world):  # noqa: F811
    """C8-12 (décision C8-Q2) : sans dossier de rapports (``serve --reports``, que l'unité de service ne passe pas),
    Simulations n'est pas au menu — la page serait toujours vide —, mais son adresse et l'ancienne répondent, son fil
    dit sa colonne, sa rubrique s'allume sans qu'une autre page prenne sa place, et la recherche la trouve."""
    client, _, _ = world
    bootstrap(client)
    page = client.get('/admin/systeme/simulations')
    assert page.status_code == 200
    menu = primary_nav(page.text)
    assert '/admin/systeme/simulations' not in menu
    assert '<details class="nav-group active" data-nav-group="Système">' in menu
    assert 'aria-current="page"' not in menu and 'class="nav-item on' not in menu and 'nav-tab on' not in menu
    assert texts(trail_of(page.text)) == ["Système", "Anatomie"]
    moved = client.get('/admin/rapports', follow_redirects=False)
    assert moved.status_code == 301 and moved.headers['location'] == '/admin/systeme/simulations'
    found = html.unescape(client.get('/admin/recherche?q=simulations').text)
    assert 'href="/admin/systeme/simulations"' in found


def test_with_a_reports_folder_simulations_close_the_anatomy(tmp_path):
    """Le contre-exemple (C8-12) : un serveur lancé avec un dossier de rapports montre Simulations au menu, en
    dernier de l'Anatomie, et l'allume quand on y est."""
    reports = tmp_path / "rapports"
    reports.mkdir()
    app, _ = build(tmp_path / "data", web=WebConfig(), gateway=LiveGateway(), embedder=HashEmbedder(), reports=reports)
    with TestClient(app, base_url="http://localhost:8001", headers={"Origin": ORIGIN}) as client:
        bootstrap(client)
        shown = dict(system_columns(client.get('/admin/').text))
        assert shown["Anatomie"][-1] == ('/admin/systeme/simulations', "Simulations")
        lit = primary_nav(client.get('/admin/systeme/simulations').text)
        assert re.findall(r'<a class="nav-tab on"[^>]*><span>(.*?)</span>', lit) == ["Simulations"]


def test_every_trail_starts_from_its_menu_rubric(world):  # noqa: F811
    """C1-04, C7-14 (ADR 0177, 0202) : le fil d'Ariane de toute page part de la rubrique du menu, puis de sa
    destination (pour Réglages et Système, du lien qui couvre la page, ou de sa colonne), et chaque niveau mène à sa
    page ; une fiche, un événement, une parole disent leur numéro ; un objet qui n'a pour nom que sa clé (un serveur
    extérieur, un réveil) la dit, comme un outil, quand une personne ou un moyen de communication ne disent pas la
    leur ; un retour ne remplace plus le chemin : il se dit à part, au bout, et jamais comme un niveau."""
    client, live, _ = world
    bootstrap(client)
    converse(client)  # un épisode, une parole
    declare_wakeup(client, live)  # un réveil, « serre »
    thread = client.get('/admin/fiche/person/user_1?onglet=echanges').text
    seq = re.search(r'href="/admin/parole/(\d+)"', thread).group(1)
    utterance = client.portal.call(lambda: live.kernel.mind.store.get_events([int(seq)]))[0]
    episode = f'/admin/episode/{utterance.correlation}'
    urls = {u for u in re.findall(r'href="(/admin/[^"#]+)"', primary_nav(client.get('/admin/').text))
            if u != '/admin/constellation'}  # la constellation : une page à elle, sans le cadre de la console
    directory = html.unescape(client.get('/admin/reglages/apercu').text)
    urls |= set(re.findall(r'href="(/admin/[^"#?]+)"', directory.split('<div class="settings-directory stack">')[1]))
    urls |= {episode, f'/admin/parole/{seq}', '/admin/evenement/1', '/admin/fiche/person/user_1',
             '/admin/fiche/handle/user_1', '/admin/outils/tous?outil=email_read&lot=email',
             '/admin/fiche/serveur/web', '/admin/fiche/reveil/serre',
             '/admin/action/projects.creer?retour=/admin/projets'}
    trails = {}
    for url in sorted(urls):
        response = client.get(url)
        assert response.status_code == 200, (url, response.status_code)
        trails[url] = trail_of(response.text)
        assert trails[url] and trails[url][0][0] in RUBRICS, (url, trails[url])
        assert not any(text.startswith("Retour") for text in texts(trails[url])), (url, trails[url])
    expected = {
        '/admin/maintenant': ["Mika"],
        '/admin/personnes': ["Échanges", "Personnes"],
        '/admin/vie/needs': ["Mika", "Humeur et corps"],
        '/admin/sens': ["Connexions", "Ses sens"],
        '/admin/systeme/operations': ["Système", "Journaux"],
        '/admin/evenement/1': ["Système", "Journaux", "Journal d’événements", "n° 1"],
        '/admin/reglages/temperament': ["Réglages", "Personnage"],
        '/admin/reglages/comportement-memory': ["Réglages", "Paramètres avancés", "Esprit"],
        '/admin/reglages/depots': ["Connexions", "Dépôts Git"],
        # les réglages d'un plugin vivent dans sa destination (ADR 0206) : le fil dit la destination
        '/admin/teams/parametres': ["Échanges", "Teams"],
        '/admin/outils/parametres': ["Outils", "Ses outils"],
        '/admin/sens/parametres-flux': ["Connexions", "Ses sens"],
        '/admin/reveils/parametres': ["Connexions", "Réveils par API"],
        # une personne, un moyen de communication : leur titre les nomme, leur clé interne (user_1) ne se dit pas
        '/admin/fiche/person/user_1': ["Échanges", "Personnes"],
        '/admin/fiche/handle/user_1': ["Échanges", "Identités"],
        '/admin/outils/tous?outil=email_read&lot=email': ["Outils", "Ses outils", "email_read"],
        # un serveur extérieur (la recherche web, un service du système) : son nom est sa clé, il le dit comme un outil
        '/admin/fiche/serveur/web': ["Outils", "Ses outils", "web"],
        '/admin/fiche/reveil/serre': ["Connexions", "Réveils par API", "serre"],
        '/admin/action/projects.creer?retour=/admin/projets': ["Activité", "Projets"],
        episode: ["Activité", "Décisions", "Épisodes"],
        f'/admin/parole/{seq}': ["Échanges", "Conversations", f"n° {seq}"],
    }
    for url, levels in expected.items():
        assert texts(trails[url]) == levels, (url, trails[url])
    # chaque niveau mène à sa page (C7-14 : la rubrique d'une page de réglages, la famille d'une faculté)
    assert dict(trails['/admin/reglages/temperament'])["Personnage"] == '/admin/reglages/identite'
    assert dict(trails['/admin/reglages/comportement-memory'])["Paramètres avancés"] == \
        '/admin/reglages/comportement'
    # sa famille mène à la vue d'ensemble, ouverte sur elle
    assert dict(trails['/admin/reglages/comportement-memory'])["Esprit"] == \
        '/admin/reglages/comportement#famille-esprit'
    assert 'id="famille-esprit"' in client.get('/admin/reglages/comportement').text
    assert dict(trails['/admin/evenement/1'])["Journal d’événements"] == '/admin/systeme/chronologie'
    assert dict(trails[episode])["Épisodes"] == '/admin/decisions/episodes'
    # l'outil ouvert depuis une liste filtrée : la destination ramène à cette liste
    assert dict(trails['/admin/outils/tous?outil=email_read&lot=email'])["Ses outils"] == \
        '/admin/outils/tous?lot=email'
    # le serveur : sa destination mène à la liste d'où il vient (son retour déclaré, Venus d'ailleurs), son nom à rien
    assert trails['/admin/fiche/serveur/web'][1:] == [("Ses outils", '/admin/outils/serveurs'), ("web", "")]
    assert back_of(client.get('/admin/action/projects.creer?retour=/admin/projets').text) is None
    # une fiche ouverte depuis une liste : son chemin à elle, et le retour à part
    listed = client.get('/admin/fiche/person/user_1?retour=/admin/approbations/rapprochements').text
    assert texts(trail_of(listed)) == ["Échanges", "Personnes"]
    assert back_of(listed) == ("Retour à la liste", '/admin/approbations/rapprochements')


def pane(page, title):
    """Une section de la recherche dessinée (son sous-onglet), par son titre."""
    found = re.search(rf'data-pane aria-label="{re.escape(title)}">.*?</section>', html.unescape(page), re.S)
    return found.group() if found else ""


def test_search_writes_dates_finds_settings_by_name_and_leaves_raw_views_aside(world):  # noqa: F811
    """C1-03, C1-09, Q09 (ADR 0202) : la recherche écrit la date d'un mail comme la console, jamais son horodatage
    brut ; un compte s'y lit sans sa clé interne ; un réglage se trouve par le nom de son champ (section « Réglages ») ;
    les vues brutes des facultés ne sont plus une sorte de résultat, un lien mène à Système › Toutes les vues. La fiche
    d'un mail dit son chemin, sa destination ramenant à la liste d'où il vient."""
    client, live, _ = world
    bootstrap(client)
    live.kernel.ports["mail"] = mailbox(3)
    page = client.get('/admin/recherche?q=Maquettes').text
    mails = pane(page, "Mails")
    assert "Maquettes du projet" in mails and str(NOW + 60_000_000) not in page
    assert re.search(r'Léa Martin <lea@example\.test> · \d\d/\d\d \d\d:\d\d', mails), mails
    fiche = re.search(r'href="(/admin/fiche/mail/[^"]+)"', mails).group(1)
    shown = client.get(html.unescape(fiche)).text
    assert texts(trail_of(shown)) == ["Échanges", "Courrier"] and back_of(shown) is None
    assert dict(trail_of(shown))["Courrier"].startswith('/admin/courrier/reception')
    handles = pane(client.get('/admin/recherche?q=adrien').text, "Moyens de communication")
    assert "adrien" in handles and "user_1 ·" not in handles
    settings = pane(client.get('/admin/recherche?q=fuseau').text, "Réglages")
    assert 'href="/admin/reglages/identite"' in settings and "Trouvé dans : Fuseau horaire" in settings
    memories = client.get('/admin/recherche?q=souvenirs').text
    assert not pane(memories, "Vues") and 'aria-label="Vues' not in memories
    assert re.search(r'<a href="/admin/systeme/vues">Chercher dans les vues techniques</a>', memories)


def test_each_settings_page_belongs_to_one_menu_link_and_its_bar_follows_it(world):  # noqa: F811
    """C7-03, Q01 : chaque page de réglages appartient à un seul lien du menu (hors les liens d'une colonne, qui
    mènent à une page rangée ailleurs) ; sa barre d'onglets suit ce lien, dans son ordre — Portrait dans celle du
    Personnage, Import / export en dernier ; Carte et téléphone a son lien, et ses six pages une barre commune."""
    client, _, _ = world
    bootstrap(client)
    directory = html.unescape(client.get('/admin/reglages/apercu').text)
    pages = {u.removeprefix('/admin/') for u in re.findall(r'href="(/admin/reglages/[^"#?]+)"', directory)}
    assert len(pages) > 40
    for page in sorted(pages):
        owners = [link.label for group in MENU for link in group.items if not link.column
                  and (page in (link.target, *link.also) or page.startswith(link.target + "-"))]
        assert len(owners) == 1, (page, owners)
    personnage = bar_of(client.get('/admin/reglages/portrait').text)
    assert [title for _href, title in personnage] == [
        "Identité", "Portrait", "Sa parole", "Tempérament", "Autrices", "Import / export"]
    map_and_phone = client.get('/admin/reglages/lieux').text
    assert [href.rsplit('/', 1)[1] for href, _title in bar_of(map_and_phone)] == [
        "carte", "lieux", "itineraires", "tourisme", "avis", "rechauffage", "notifications"]
    assert texts(trail_of(map_and_phone)) == ["Réglages", "Carte et téléphone"]


#: les réglages d'un plugin, derrière la roue de sa destination (ADR 0173, 0206) : leur ancienne adresse sous Réglages
#: (où leurs formulaires s'envoient toujours), leur adresse, leur titre, et le fil d'Ariane de leur page
GEARED = (
    ("boites", "courrier/parametres", "Paramètres", ["Échanges", "Courrier"]),
    ("teams", "teams/parametres", "Paramètres", ["Échanges", "Teams"]),
    ("serveurs-mcp", "outils/parametres", "Paramètres", ["Outils", "Ses outils"]),
    ("flux", "sens/parametres-flux", "Flux suivis", ["Connexions", "Ses sens"]),
    ("appareils", "sens/parametres-appareils", "Accès des appareils", ["Connexions", "Ses sens"]),
    ("transcription", "sens/parametres-transcription", "Transcription vocale", ["Connexions", "Ses sens"]),
    ("reveils", "reveils/parametres", "Paramètres", ["Connexions", "Réveils par API"]),
)


def gear_of(page):
    """La roue de la barre de titre (``page.html``) : ``(adresse, titre, allumée)`` de chaque page qu'elle porte — un
    bouton quand elle n'en porte qu'une, un menu « Réglages » sinon."""
    head = html.unescape(page).split('<div class="page-head">', 1)[1]
    head = re.split(r'<nav class="tabs"|<div class="stack">', head, maxsplit=1)[0]
    found = re.findall(r'<a class="btn quiet gear-link( on)?" href="([^"]+)"[^>]*>(.*?)</a>', head, re.S)
    panel = re.search(r'<nav class="gear-panel"[^>]*>(.*?)</nav>', head, re.S)
    found += re.findall(r'<a class="(on)?" href="([^"]+)"[^>]*>(.*?)</a>', panel.group(1), re.S) if panel else []
    return [(href, re.sub(r"<[^>]+>", "", title).strip(), bool(on)) for on, href, title in found]


def test_the_gear_of_each_destination_leads_to_its_settings(world):  # noqa: F811
    """C7-05, Q11 (ADR 0173, 0206) : les réglages d'un plugin vivent dans sa destination. La roue de chacun de ses
    onglets y mène ; ouverte, la page dit sa destination — son fil d'Ariane, la barre d'onglets de la destination (sans
    elle), la roue allumée — ; son ancienne adresse sous Réglages y mène, sa requête gardée, et un formulaire s'y envoie
    toujours, puis revient dans la destination. Aucun lien du menu ne la prend ailleurs ; Réglages ne mène plus à
    Transcription. L'annuaire et la vue d'ensemble des plugins la nomment par sa destination."""
    client, _, _ = world
    bootstrap(client)
    for old, new, title, trail in GEARED:
        destination = new.split('/', 1)[0]
        tabs = bar_of(client.get(f'/admin/{destination}').text) or [(f'/admin/{destination}', '')]
        for href, _title in tabs:
            assert (f'/admin/{new}', title, False) in gear_of(client.get(href).text), (href, new)
        page = client.get(f'/admin/{new}')
        assert page.status_code == 200, new
        text = html.unescape(page.text)
        assert re.search(rf'<h1>{re.escape(title)}</h1>', text), (new, title)
        assert texts(trail_of(text)) == trail, (new, trail_of(text))
        assert (f'/admin/{new}', title, True) in gear_of(text), new
        assert bar_of(text) == [t for t in tabs if t[1]], new  # la barre de la destination, sans la page de la roue
        moved = client.get(f'/admin/reglages/{old}?enregistrement=x', follow_redirects=False)
        assert moved.status_code == 301 and moved.headers['location'] == f'/admin/{new}?enregistrement=x', old
    # un formulaire s'envoie toujours sous Réglages, et revient là où vit la page
    saved = client.post('/admin/reglages/flux', data={'csrf': client.cookies.get('csrftoken'), '_section': 'flux',
                                                           '_champs': ['urls'], 'urls': 'https://a.fr/rss'},
                        follow_redirects=False)
    assert saved.status_code == 303 and saved.headers['location'].startswith('/admin/sens/parametres-flux?flash=')
    refused = client.post('/admin/reglages/flux', data={'csrf': client.cookies.get('csrftoken'), '_section': 'flux',
                                                             '_champs': ['urls'], 'urls': 'ftp://b'})
    assert refused.status_code == 400 and texts(trail_of(refused.text)) == ["Connexions", "Ses sens"]
    # le menu ne les prend plus ailleurs (``also``), et Réglages n'a plus de lien vers l'une d'elles
    olds = {f'reglages/{old}' for old, *_ in GEARED}
    assert not [link.label for group in MENU for link in group.items if olds & {link.target, *link.also}]
    # l'annuaire et la vue d'ensemble des plugins les nomment par leur destination, à leur adresse
    directory = html.unescape(client.get('/admin/reglages/apercu').text)
    plugins = html.unescape(client.get('/admin/reglages/plugins').text)
    labels = {d.key: d.label for group in NAVIGATION for d in group.items}
    for _old, new, title, _trail in GEARED:
        named = f'{labels[new.split("/", 1)[0]]} › {title}'
        assert f'<a href="/admin/{new}"><span class="hm-dir-title">{named}</span>' in directory, named
        assert f'<a href="/admin/{new}">{named}</a>' in plugins, named


def test_a_gear_of_one_page_is_named_parametres_everywhere(world):  # noqa: F811
    """Le même geste porte le même nom : la roue d'une destination qui ne porte qu'une page s'appelle « Paramètres »
    sur tous ses onglets — Courrier, Teams, Réveils par API, et Ses outils, dont la fiche d'un outil du code et
    « Prêter à un agent » ne parlent d'aucun service. Ses sens, qui en porte plusieurs, garde son menu (ADR 0206 ;
    audit du 2026-11-05, C6-12, C6-Q3)."""
    client, _, _ = world
    bootstrap(client)
    single = [d.key for group in NAVIGATION for d in group.items if len(d.gear) == 1]
    assert {"courrier", "teams", "reveils", "outils"} <= set(single)
    tool_fiche = '/admin/outils/tous?outil=email_read'  # la fiche d'un outil du code, sous Ses outils
    for key in single:
        tabs = bar_of(client.get(f'/admin/{key}').text) or [(f'/admin/{key}', '')]
        for href in [h for h, _title in tabs] + ([tool_fiche] if key == "outils" else []):
            assert [title for _h, title, _on in gear_of(client.get(href).text)] == ["Paramètres"], href


def test_a_tab_badge_says_what_it_counts_on_hover(world):  # noqa: F811
    """Un badge d'onglet n'a qu'un style : ce qu'il compte (son indice, ADR 0219) se lit au survol du nombre — sur
    Courrier › Paramètres, « Réception » compte les mails importants pas encore lus, pas les non-lus de la colonne
    (audit du 2026-11-05, C4-11)."""
    client, live, _ = world
    bootstrap(client)
    live.kernel.ports["mail"] = mailbox(3)
    important = email_c.NOTICED.draft(source="email", kind=email_c.MAIL, summary=Content.of("Léa attend ton avis."),
                                      pertinence=0.8, bundle="email", mail="pro:<projet@example.test>",
                                      sender="Léa Martin", address="lea@example.test", importance=0.95,
                                      dedupe_key="test-important")
    client.portal.call(lambda: live.kernel.mind.append([important], emitter="email", origin=Origin.EXTERNAL,
                                                        correlation="test-badge"))
    page = client.get('/admin/courrier/parametres')
    assert page.status_code == 200
    ConsoleHTML(page.text).check()
    tabs = re.search(r'<nav class="tabs".*?</nav>', html.unescape(page.text), re.S).group()
    reception = re.search(r'>Réception<span class="count"([^>]*)>(\d+)</span>', tabs)
    assert reception is not None and reception.group(2) == "1", tabs
    assert reception.group(1) == ' title="mail important pas encore lu"', tabs
    # un badge sans indice ne porte pas de « title » vide
    assert 'title=""' not in tabs


def test_her_menu_section_bears_the_name_of_her_persona(world):  # noqa: F811
    """La rubrique qui la décrit porte son nom, lu dans sa persona : jamais « Mika » écrit en dur (ADR 0070)."""
    client, live, _ = world
    bootstrap(client)
    assert 'data-nav-group="Mika"' in primary_nav(client.get('/admin/').text)
    renamed = client.post('/admin/reglages/identite', data={
        'csrf': client.cookies.get('csrftoken'), '_section': 'personnage', '_champs': ['name'], 'name': 'Lina'})
    assert renamed.status_code in (200, 303)
    assert client.portal.call(live.persona).name == 'Lina'
    menu = primary_nav(client.get('/admin/').text)
    assert 'data-nav-group="Lina"' in menu and 'data-nav-group="Mika"' not in menu


def test_login_has_a_main_heading(world):  # noqa: F811
    client, _, _ = world
    page = client.get('/admin/connexion')
    assert page.status_code == 200
    ConsoleHTML(page.text).check()


def test_people_view_switch_keeps_subject_links(world):  # noqa: F811
    # l'annuaire des identités, onglet de la destination Personnes (dont la page d'entrée est dessinée, ADR 0121) ; il
    # se parcourt, sans filtre : on cherche quelqu'un depuis la vue d'ensemble (tests/protocol/test_people_page.py)
    client, _, _ = world
    bootstrap(client)
    cards = client.get('/admin/personnes/personnes')
    table = client.get('/admin/personnes/personnes?vue_pg1=table')
    for response in (cards, table):
        assert response.status_code == 200
        ConsoleHTML(response.text).check()
        assert 'href="/admin/fiche/person/user_1"' in response.text
        assert '<form class="filters"' not in response.text
    assert 'data-tab="personnes/personnes"' in cards.text  # l'onglet est dessiné dans sa forme (ADR 0177)
    assert 'data-tab="personnes/personnes"' not in table.text
    assert '<a href="?vue_pg1=table" aria-current=page>Tableau</a>' in table.text  # la bascule dit où l'on est


def test_search_finds_settings_without_accents_and_preserves_subject_filter(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    page = client.get('/admin/recherche?q=identite')
    assert page.status_code == 200
    ConsoleHTML(page.text).check()
    # la recherche est dessinée (ADR 0121) : « Tout », puis une section par sorte de résultat (ADR 0176)
    def section(text: str) -> str:
        return re.search(r'data-pane aria-label="Pages de la console">.*?</section>', text, re.S).group()

    assert '<a href="#r-tout">Tout' in page.text
    results = section(page.text)
    assert 'href="/admin/reglages/identite"' in results
    assert 'href="/admin/identites"' in results
    assert 'href="/admin/reglages/fournisseurs"' in section(client.get('/admin/recherche?q=fournisseurs').text)
    assert 'href="/admin/vie/rythme"' in section(client.get('/admin/recherche?q=sommeil').text)
    assert 'Pages de la console' not in client.get('/admin/recherche?q=identite&sorte=person').text
    assert 'Pages de la console' not in client.get('/admin/recherche?q=aucune-page-de-ce-nom').text


def test_settings_directory_finds_pages_and_separates_advanced_settings(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    response = client.get('/admin/reglages')
    assert response.status_code == 200 and '<h1>Tous les réglages</h1>' in response.text
    ConsoleHTML(response.text).check()
    directory = response.text.split('<div class="settings-directory stack">', 1)[1]
    assert 'id="reglages-avances">' in directory
    assert '/admin/reglages/fournisseurs' in directory
    assert '/admin/reglages/comportement-memory' in directory
    # Consulter le répertoire ne charge aucun fournisseur et ne montre aucune valeur de réglage.
    for query in ('memoire', 'mémoire'):
        page = client.get('/admin/reglages/apercu', params={'q': query})
        ConsoleHTML(page.text).check()
        results = page.text.split('<div class="settings-directory stack">', 1)[1]
        assert 'id="reglages-avances" open' in results
        assert '/admin/reglages/comportement-memory' in results
        assert '/admin/reglages/comptes' not in results
    empty = client.get('/admin/reglages/apercu?q=aucun-resultat')
    assert 'Aucun réglage ne correspond' in empty.text
    malicious = client.get('/admin/reglages/apercu', params={'q': '<script>alert(1)</script>'})
    assert '<script>alert(1)</script>' not in malicious.text


def test_a_fiche_tab_description_comes_under_the_tab_bar_which_stays_put(world):  # noqa: F811
    """La description d'un onglet que la fiche ne dessine pas est la première ligne de son contenu, sous la barre
    d'onglets : la barre ne descend plus d'un onglet à l'autre (ADR 0176 ; audit du 2026-11-05, C5-05). Une app de la
    Forge n'a pas de vue d'ensemble dessinée : chacun de ses onglets reçoit sa description."""
    client, live, _ = world
    bootstrap(client)
    forge, kernel = live.kernel.ports["forge"], live.kernel

    async def write():
        await forge.write("meteo", EXAMPLE_MANIFEST, EXAMPLE_CODE)
        await kernel.mind.append([written_draft(forge.info("meteo"))], emitter="forge", correlation="t",
                                 origin=Origin.GENESIS)

    client.portal.call(write)
    above = {}
    # « Accès » est dans la barre, « Vécu » rangé sous la roue des réglages : tous deux ont leur description
    for tab, said in (("acces", "Pour une app sans projet : qui peut"), ("vecu", "Les exécutions, changements d'état")):
        page = client.get(f"/admin/fiche/app/meteo?onglet={tab}")
        assert page.status_code == 200, tab
        ConsoleHTML(page.text).check()
        body = html.unescape(page.text)
        view = body.split('<div class="page-view">', 1)[1]
        bar = view.index('<nav class="tabs"')
        bar_end = view.index("</nav>", bar)
        description = view.index('<p class="view-description">')
        assert description > bar_end, tab
        assert view[description:].startswith(f'<p class="view-description">{said}'), tab
        above[tab] = unlit(view[:bar])
    # ce qui précède la barre (le fil, l'en-tête de l'app et sa roue) est le même d'un onglet à l'autre, à l'entrée
    # allumée près : la roue des réglages s'allume sur l'onglet qu'elle range
    assert above["acces"] == above["vecu"]


def unlit(fragment):
    """Un fragment de page sans ce qui dit l'entrée allumée (la classe ``on``, ``aria-current``)."""
    fragment = re.sub(r' aria-current="[^"]*"', "", fragment)
    return re.sub(r'class="([^"]*)"', lambda m: 'class="{}"'.format(" ".join(c for c in m.group(1).split() if c != "on")),
                  fragment)
