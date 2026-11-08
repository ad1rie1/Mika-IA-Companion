"""La navigation de la console : le menu fait foi (ADR 0178, 0202) — un nom par page, un fil d'Ariane qui part de sa
rubrique, Système en trois colonnes —, et la recherche globale retrouve les pages et les réglages, pas seulement les
objets."""
import html
import re

import pytest

from mika.app.console import NAVIGATION
from mika.app.console_menu import MENU, SHORTCUT_GROUPS
from mika.inspector.catalog import menu_place
from tests.fixtures.console_html import ConsoleHTML
from tests.fixtures.courrier import NOW, mailbox
from tests.protocol.test_console_operator import converse
from tests.protocol.test_wakeup_web import configure as declare_wakeup
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

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
    un à un (« À valider ») les nomme tous, dans leur ordre. Sauf l'annuaire des réglages, et les liens vers une page qui
    vit dans une autre rubrique (Système › Journaux mène aux historiques, ADR 0202)."""
    client, _, _ = world
    bootstrap(client)
    columns = menu_columns(client.get('/inspecteur/').text)
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
    # les groupes de pages de sa rubrique, des échanges, de l'activité, des outils et des connexions, et les trois
    # colonnes de Système
    assert grouped >= 12 and len(columns) == grouped + 3


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
            # une page rangée dans une autre rubrique (Système › Journaux › l'historique des réglages) y allume son
            # lien à elle, pas cet onglet
            crossing = head.startswith('/inspecteur/systeme/') and not href.startswith('/inspecteur/systeme/')
            assert lit == ([] if crossing else [href]), (href, lit)
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
    # Système en colonnes (ADR 0202) : la colonne s'allume, et la page dedans ; un événement allume son journal
    ('systeme/operations', 'Système', 'Journaux', 'Gestes audités'),
    ('evenement/1', 'Système', 'Journaux', None),
    # l'historique des réglages vit dans Réglages : Système › Journaux y mène sans le lui prendre
    ('reglages/journal', 'Réglages', 'Historique des réglages', None),
    ('approbations/historique', 'À valider', 'Historique des autorisations', None),
    # Carte et téléphone a son lien (ADR 0197), ses quatre pages derrière lui
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
    page = client.get('/inspecteur/' + path)
    assert page.status_code == 200
    assert page.url.path == '/inspecteur/' + path.split('?', 1)[0]  # la page même, pas une redirection ailleurs
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
            page = html.unescape(client.get(f'/inspecteur/{link.target}').text)
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
    columns = system_columns(client.get('/inspecteur/').text)
    assert [name for name, _tabs in columns] == ["Surveiller", "Journaux", "Anatomie"]
    shown = dict(columns)
    assert [title for _href, title in shown["Journaux"]] == [
        "Journal d’événements", "Gestes audités", "Historique des réglages", "Historique des autorisations"]
    assert ('/inspecteur/reglages/journal', 'Historique des réglages') in shown["Journaux"]
    assert ('/inspecteur/approbations/historique', 'Historique des autorisations') in shown["Journaux"]
    assert len(shown["Surveiller"]) == 8 and [t for _h, t in shown["Anatomie"]][-1] == "Simulations"
    for name, tabs in columns:
        for href, _title in tabs:
            if href.startswith('/inspecteur/systeme/'):
                assert texts(trail_of(client.get(href).text)) == ["Système", name], href
    assert texts(trail_of(client.get('/inspecteur/reglages/journal').text)) == ["Réglages", "Historique des réglages"]
    assert texts(trail_of(client.get('/inspecteur/approbations/historique').text)) == ["À valider"]


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
    thread = client.get('/inspecteur/fiche/person/user_1?onglet=echanges').text
    seq = re.search(r'href="/inspecteur/parole/(\d+)"', thread).group(1)
    utterance = client.portal.call(lambda: live.kernel.mind.store.get_events([int(seq)]))[0]
    episode = f'/inspecteur/episode/{utterance.correlation}'
    urls = {u for u in re.findall(r'href="(/inspecteur/[^"#]+)"', primary_nav(client.get('/inspecteur/').text))
            if u != '/inspecteur/constellation'}  # la constellation : une page à elle, sans le cadre de la console
    directory = html.unescape(client.get('/inspecteur/reglages/apercu').text)
    urls |= set(re.findall(r'href="(/inspecteur/[^"#?]+)"', directory.split('<div class="settings-directory stack">')[1]))
    urls |= {episode, f'/inspecteur/parole/{seq}', '/inspecteur/evenement/1', '/inspecteur/fiche/person/user_1',
             '/inspecteur/fiche/handle/user_1', '/inspecteur/outils/tous?outil=email_read&lot=email',
             '/inspecteur/fiche/serveur/web', '/inspecteur/fiche/reveil/serre',
             '/inspecteur/action/projects.creer?retour=/inspecteur/projets'}
    trails = {}
    for url in sorted(urls):
        response = client.get(url)
        assert response.status_code == 200, (url, response.status_code)
        trails[url] = trail_of(response.text)
        assert trails[url] and trails[url][0][0] in RUBRICS, (url, trails[url])
        assert not any(text.startswith("Retour") for text in texts(trails[url])), (url, trails[url])
    expected = {
        '/inspecteur/maintenant': ["Mika"],
        '/inspecteur/personnes': ["Échanges", "Personnes"],
        '/inspecteur/vie/needs': ["Mika", "Humeur et corps"],
        '/inspecteur/sens': ["Connexions", "Ses sens"],
        '/inspecteur/systeme/operations': ["Système", "Journaux"],
        '/inspecteur/evenement/1': ["Système", "Journaux", "Journal d’événements", "n° 1"],
        '/inspecteur/reglages/temperament': ["Réglages", "Personnage"],
        '/inspecteur/reglages/comportement-memory': ["Réglages", "Paramètres avancés", "Esprit"],
        '/inspecteur/reglages/depots': ["Connexions", "Dépôts Git"],
        # les réglages d'un plugin vivent dans sa destination (ADR 0206) : le fil dit la destination
        '/inspecteur/teams/parametres': ["Échanges", "Teams"],
        '/inspecteur/outils/parametres': ["Outils", "Ses outils"],
        '/inspecteur/sens/parametres-flux': ["Connexions", "Ses sens"],
        '/inspecteur/reveils/parametres': ["Connexions", "Réveils par API"],
        # une personne, un moyen de communication : leur titre les nomme, leur clé interne (user_1) ne se dit pas
        '/inspecteur/fiche/person/user_1': ["Échanges", "Personnes"],
        '/inspecteur/fiche/handle/user_1': ["Échanges", "Identités"],
        '/inspecteur/outils/tous?outil=email_read&lot=email': ["Outils", "Ses outils", "email_read"],
        # un serveur extérieur (la recherche web, un service du système) : son nom est sa clé, il le dit comme un outil
        '/inspecteur/fiche/serveur/web': ["Outils", "Ses outils", "web"],
        '/inspecteur/fiche/reveil/serre': ["Connexions", "Réveils par API", "serre"],
        '/inspecteur/action/projects.creer?retour=/inspecteur/projets': ["Activité", "Projets"],
        episode: ["Activité", "Décisions", "Épisodes"],
        f'/inspecteur/parole/{seq}': ["Échanges", "Conversations", f"n° {seq}"],
    }
    for url, levels in expected.items():
        assert texts(trails[url]) == levels, (url, trails[url])
    # chaque niveau mène à sa page (C7-14 : la rubrique d'une page de réglages, la famille d'une faculté)
    assert dict(trails['/inspecteur/reglages/temperament'])["Personnage"] == '/inspecteur/reglages/identite'
    assert dict(trails['/inspecteur/reglages/comportement-memory'])["Paramètres avancés"] == \
        '/inspecteur/reglages/comportement'
    # sa famille mène à la vue d'ensemble, ouverte sur elle
    assert dict(trails['/inspecteur/reglages/comportement-memory'])["Esprit"] == \
        '/inspecteur/reglages/comportement#famille-esprit'
    assert 'id="famille-esprit"' in client.get('/inspecteur/reglages/comportement').text
    assert dict(trails['/inspecteur/evenement/1'])["Journal d’événements"] == '/inspecteur/systeme/chronologie'
    assert dict(trails[episode])["Épisodes"] == '/inspecteur/decisions/episodes'
    # l'outil ouvert depuis une liste filtrée : la destination ramène à cette liste
    assert dict(trails['/inspecteur/outils/tous?outil=email_read&lot=email'])["Ses outils"] == \
        '/inspecteur/outils/tous?lot=email'
    # le serveur : sa destination mène à la liste d'où il vient (son retour déclaré, Venus d'ailleurs), son nom à rien
    assert trails['/inspecteur/fiche/serveur/web'][1:] == [("Ses outils", '/inspecteur/outils/serveurs'), ("web", "")]
    assert back_of(client.get('/inspecteur/action/projects.creer?retour=/inspecteur/projets').text) is None
    # une fiche ouverte depuis une liste : son chemin à elle, et le retour à part
    listed = client.get('/inspecteur/fiche/person/user_1?retour=/inspecteur/approbations/noms').text
    assert texts(trail_of(listed)) == ["Échanges", "Personnes"]
    assert back_of(listed) == ("Retour à la liste", '/inspecteur/approbations/noms')


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
    page = client.get('/inspecteur/recherche?q=Maquettes').text
    mails = pane(page, "Mails")
    assert "Maquettes du projet" in mails and str(NOW + 60_000_000) not in page
    assert re.search(r'Léa Martin <lea@example\.test> · \d\d/\d\d \d\d:\d\d', mails), mails
    fiche = re.search(r'href="(/inspecteur/fiche/mail/[^"]+)"', mails).group(1)
    shown = client.get(html.unescape(fiche)).text
    assert texts(trail_of(shown)) == ["Échanges", "Courrier"] and back_of(shown) is None
    assert dict(trail_of(shown))["Courrier"].startswith('/inspecteur/courrier/reception')
    handles = pane(client.get('/inspecteur/recherche?q=adrien').text, "Moyens de communication")
    assert "adrien" in handles and "user_1 ·" not in handles
    settings = pane(client.get('/inspecteur/recherche?q=fuseau').text, "Réglages")
    assert 'href="/inspecteur/reglages/identite"' in settings and "Trouvé dans : Fuseau horaire" in settings
    memories = client.get('/inspecteur/recherche?q=souvenirs').text
    assert not pane(memories, "Vues") and 'aria-label="Vues' not in memories
    assert re.search(r'<a href="/inspecteur/systeme/vues">Chercher dans les vues techniques</a>', memories)


def test_each_settings_page_belongs_to_one_menu_link_and_its_bar_follows_it(world):  # noqa: F811
    """C7-03, Q01 : chaque page de réglages appartient à un seul lien du menu (hors les liens d'une colonne, qui
    mènent à une page rangée ailleurs) ; sa barre d'onglets suit ce lien, dans son ordre — Portrait dans celle du
    Personnage, Import / export en dernier ; Carte et téléphone a son lien, et ses quatre pages une barre commune."""
    client, _, _ = world
    bootstrap(client)
    directory = html.unescape(client.get('/inspecteur/reglages/apercu').text)
    pages = {u.removeprefix('/inspecteur/') for u in re.findall(r'href="(/inspecteur/reglages/[^"#?]+)"', directory)}
    assert len(pages) > 40
    for page in sorted(pages):
        owners = [link.label for group in MENU for link in group.items if not link.column
                  and (page in (link.target, *link.also) or page.startswith(link.target + "-"))]
        assert len(owners) == 1, (page, owners)
    personnage = bar_of(client.get('/inspecteur/reglages/portrait').text)
    assert [title for _href, title in personnage] == [
        "Identité", "Portrait", "Sa parole", "Tempérament", "Autrices", "Import / export"]
    map_and_phone = client.get('/inspecteur/reglages/lieux').text
    assert [href.rsplit('/', 1)[1] for href, _title in bar_of(map_and_phone)] == [
        "carte", "lieux", "itineraires", "notifications"]
    assert texts(trail_of(map_and_phone)) == ["Réglages", "Carte et téléphone"]


#: les réglages d'un plugin, derrière la roue de sa destination (ADR 0173, 0206) : leur ancienne adresse sous Réglages
#: (où leurs formulaires s'envoient toujours), leur adresse, leur titre, et le fil d'Ariane de leur page
GEARED = (
    ("boites", "courrier/parametres", "Paramètres", ["Échanges", "Courrier"]),
    ("teams", "teams/parametres", "Paramètres", ["Échanges", "Teams"]),
    ("serveurs-mcp", "outils/parametres", "Paramètres des services", ["Outils", "Ses outils"]),
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
        tabs = bar_of(client.get(f'/inspecteur/{destination}').text) or [(f'/inspecteur/{destination}', '')]
        for href, _title in tabs:
            assert (f'/inspecteur/{new}', title, False) in gear_of(client.get(href).text), (href, new)
        page = client.get(f'/inspecteur/{new}')
        assert page.status_code == 200, new
        text = html.unescape(page.text)
        assert re.search(rf'<h1>{re.escape(title)}</h1>', text), (new, title)
        assert texts(trail_of(text)) == trail, (new, trail_of(text))
        assert (f'/inspecteur/{new}', title, True) in gear_of(text), new
        assert bar_of(text) == [t for t in tabs if t[1]], new  # la barre de la destination, sans la page de la roue
        moved = client.get(f'/inspecteur/reglages/{old}?enregistrement=x', follow_redirects=False)
        assert moved.status_code == 301 and moved.headers['location'] == f'/inspecteur/{new}?enregistrement=x', old
    # un formulaire s'envoie toujours sous Réglages, et revient là où vit la page
    saved = client.post('/inspecteur/reglages/flux', data={'csrf': client.cookies.get('csrftoken'), '_section': 'flux',
                                                           '_champs': ['urls'], 'urls': 'https://a.fr/rss'},
                        follow_redirects=False)
    assert saved.status_code == 303 and saved.headers['location'].startswith('/inspecteur/sens/parametres-flux?flash=')
    refused = client.post('/inspecteur/reglages/flux', data={'csrf': client.cookies.get('csrftoken'), '_section': 'flux',
                                                             '_champs': ['urls'], 'urls': 'ftp://b'})
    assert refused.status_code == 400 and texts(trail_of(refused.text)) == ["Connexions", "Ses sens"]
    # le menu ne les prend plus ailleurs (``also``), et Réglages n'a plus de lien vers l'une d'elles
    olds = {f'reglages/{old}' for old, *_ in GEARED}
    assert not [link.label for group in MENU for link in group.items if olds & {link.target, *link.also}]
    # l'annuaire et la vue d'ensemble des plugins les nomment par leur destination, à leur adresse
    directory = html.unescape(client.get('/inspecteur/reglages/apercu').text)
    plugins = html.unescape(client.get('/inspecteur/reglages/plugins').text)
    labels = {d.key: d.label for group in NAVIGATION for d in group.items}
    for _old, new, title, _trail in GEARED:
        named = f'{labels[new.split("/", 1)[0]]} › {title}'
        assert f'<a href="/inspecteur/{new}"><span class="hm-dir-title">{named}</span>' in directory, named
        assert f'<a href="/inspecteur/{new}">{named}</a>' in plugins, named


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
