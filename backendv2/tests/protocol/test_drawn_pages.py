"""Les onglets des destinations dessinés (``app/handmade/pages.py``, ADR 0121), à travers le vrai serveur : chacun
garde les données et les filtres de sa faculté, sous une autre forme ; demandée en tableau, la liste revient à la
console ; un dessin qui échoue rend la main aux blocs."""

from __future__ import annotations

import ast
import html
import re
from pathlib import Path

import pytest

import mika
import mika.app.handmade as handmade
from mika.app.console import NAVIGATION
from mika.app.handmade import blocks as drawn_blocks
from mika.app.handmade import pages, plain
from mika.app.handmade.lists import text as cell_text
from mika.app.handmade.tabs import Tab
from mika.app.handmade.tabs import text as tabs_text
from mika.contracts import self_
from mika.inspector.catalog import destinations
from mika.inspector.ui import env
from mika.kernel.events import Content, VoiceProvenance
from mika.kernel.inspect import Badge, Ref, Text
from tests.fixtures.console_html import ConsoleHTML
from tests.protocol.test_console_workflows import append
from tests.protocol.test_now_page import chat
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def drawn(client, url: str) -> str:
    page = client.get(url)
    assert page.status_code == 200, url
    ConsoleHTML(page.text).check()
    return html.unescape(page.text)


def test_conversations_are_drawn(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    chat(client, "salut ! je reviens d'un concert")
    # l'onglet par défaut de la destination : avec qui elle parle, une ligne par personne (ADR 0181)
    people = drawn(client, "/inspecteur/fil")
    assert 'data-tab="fil/conversations"' in people and "/static/handmade/base.css" in people
    assert '<table class="tbl">' not in people
    messages = drawn(client, "/inspecteur/fiche/person/user_1?onglet=echanges")  # leur conversation
    assert 'class="now-card person-chat"' in messages and "salut ! je reviens d'un concert" in messages
    table = drawn(client, "/inspecteur/fil/conversations?vue_pg1=table")
    assert '<table class="hm-table">' in table and "fil-inbox" not in table
    judged = drawn(client, "/inspecteur/fil/jugees")
    assert 'class="now-page person-tab"' in judged and "aucune réponse jugée" in judged
    questions = drawn(client, "/inspecteur/fil/questions")
    assert 'class="now-page fil-questions" data-tab="fil/questions"' in questions  # sa forme (tabs/threads.py)


@pytest.mark.parametrize("where", sorted(pages.DRAWN))
def test_every_drawn_tab_opens(world, where):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    url = where.replace("*", "affect")  # « destination/préfixe-* » : un de ses onglets
    page = client.get(f"/inspecteur/{url}", follow_redirects=False)
    assert page.status_code == 200, where
    ConsoleHTML(page.text).check()
    assert 'class="now-page' in page.text, where  # le dessin, pas le repli sur les blocs
    assert f'data-tab="{where}"' in page.text, where  # sa forme à lui, même vide


def test_a_block_is_shaped_under_one_name():
    """K11-05 : ``shape_block``, sans l'ancien nom ``shape`` qui se confondait avec ``card`` et ``fiche_parts.shaped``."""
    assert not hasattr(drawn_blocks, "shape")


def test_nothing_cites_a_tab_module_that_moved():
    """Les modules repris dans ``tabs/`` ou renommés (K0-10, K0-11), les dossiers de gabarits et les feuilles renommés
    sous leur destination (K11-10), les deux anciens noms des réglages, retirés avec leurs réexports (``app/reglages.py``,
    ``inspector/pages/reglages.py`` ; LR2) : ni un gabarit, ni une feuille, ni le code ne renvoient à eux. Ce sont
    justement les commentaires qu'on lit ici, pour savoir où aller : le texte, pas l'arbre du code."""
    gone = re.compile(r"app/handmade/(?:nights|conversations|mail|running|tools|senses|system|people)\.py"
                      r"|\b(?:app|pages)/reglages\.py"
                      r"|app/handmade/person/memoire\.py|handmade/(?:conversations|mail|system|people)/"
                      r"|\b(?:tools|senses|rights|system|mail|nights|people)\.css\b")
    root = Path(mika.__file__).parent
    cited = [f"{path.relative_to(root)}:{at}" for path in sorted(root.rglob("*"))
             if path.suffix in (".py", ".html", ".css", ".js") and "__pycache__" not in path.parts
             for at, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if gone.search(line)]
    assert cited == []


#: les dossiers de gabarits et les feuilles d'une page à part, pas d'une destination : la console et ses macros
#: (``shared``, ``base``), l'accueil, « En ce moment », la fiche d'une personne et celles des objets (``fiches``,
#: ``projet-git``), les droits (Réglages › Droits et Canaux, Outils › Ce qu'elle peut faire), la recherche, un
#: événement, un épisode, une parole
NOT_A_DESTINATION = {"shared", "base", "home", "now", "person", "fiches", "projet-git", "droits", "recherche",
                     "evenement", "episode", "parole"}


def test_templates_and_sheets_are_named_after_their_destination():
    """K11-10 : un onglet dessine son gabarit ``handmade/<destination>/<onglet>.html`` et lit la feuille
    ``handmade/<destination>.css`` (ou ``<destination>_<partie>.css``), sous la clé de sa destination — pas sous un
    nom anglais à côté (``conversations/`` pour fil, ``mail.css`` pour courrier), ni dans un second dossier ou une
    seconde feuille de même sens (``people/`` à côté de ``personnes/``, ``nights.css`` à côté de ``pensees.css``)."""
    named = set(destinations(NAVIGATION)) | NOT_A_DESTINATION
    inspector = Path(mika.__file__).parent / "inspector"
    folders = {p.name for p in (inspector / "templates" / "handmade").iterdir() if p.is_dir()}
    sheets = {p.stem.split("_")[0] for p in (inspector / "static" / "handmade").glob("*.css")}
    assert sorted(folders - named) == []
    assert sorted(sheets - named) == []


def test_a_destination_is_drawn_by_one_module():
    """K0-10 : la page d'entrée d'une destination vit avec ses onglets, dans son module de ``tabs/`` ; aucun module de
    ``app/handmade/`` ne porte le nom d'un module de ``tabs/`` (``people.py`` à côté de ``tabs/people.py``)."""
    root = Path(handmade.__file__).parent
    beside = {p.stem for p in root.glob("*.py")} & {p.stem for p in (root / "tabs").glob("*.py")}
    assert sorted(beside - {"__init__"}) == []


def test_every_drawn_tab_is_a_tab():
    """ADR 0177 : chaque onglet d'une destination a sa forme, déclarée dans le module de sa destination (``tabs/``)."""
    assert sorted(k for k, v in pages.DRAWN.items() if not isinstance(v, Tab)) == []


def test_there_is_one_way_to_draw_a_tab():
    """Un seul adaptateur d'onglet (``tabs.Tab``) : personne d'autre, dans ``app/handmade/``, ne dérive de ``Drawn``."""
    root = Path(handmade.__file__).parent
    others = []
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef) and any(getattr(b, "id", "") == "Drawn" for b in node.bases):
                others.append(f"{path.relative_to(root)}::{node.name}")
    assert others == ["tabs/__init__.py::Tab"]


def test_the_text_of_a_cell_is_read_one_way():
    """Le texte d'une cellule rendue a une seule implémentation (``tabs.text`` est celle de ``lists``) ; « — » se tait
    sur demande."""
    assert tabs_text is cell_text
    assert tabs_text({"text": "—"}) == "—"
    assert tabs_text({"text": "—"}, dash=False) == ""
    assert tabs_text({"text": "ok"}, dash=False) == "ok"
    assert tabs_text(None) == "" and tabs_text({}) == ""


@pytest.mark.parametrize(("value", "said"), [
    (Text("un mot"), "un mot"), (Badge("actif", "ok"), "actif"), (Ref("event", "12", "n° 12"), "n° 12"),
    (None, ""), ("—", ""), ("écrit", "écrit"), (3, "3"),
])
def test_a_declared_value_is_read_one_way(value, said):
    """Une valeur telle que la faculté l'a déclarée : son texte ; ``None`` et « — » : rien (K11-06)."""
    assert plain(value) == said


def test_processes_put_what_fails_first_with_its_error(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    sched = live.kernel.scheduler
    calm = drawn(client, "/inspecteur/systeme/processus")
    assert "Tous ses processus passent" in calm and "Ce qui ne va pas" not in calm
    name = sched.specs[0].name
    sched.consecutive[name], sched.failures[name] = 4, 4
    sched.last_error[name] = (live.kernel.mind.clock.now(), "RuntimeError('le relevé a cassé')")
    page = drawn(client, "/inspecteur/systeme/processus")
    trouble = page.index("Ce qui ne va pas")
    assert "4 échecs d'affilée" in page and page.index("le relevé a cassé") > trouble
    assert page.index("Par faculté") > page.index("le relevé a cassé")
    assert page.count('class="now-card sys-faculty"') == len({s.owner for s in sched.specs})
    assert "Historique des échecs" in page  # l'historique au journal reste celui de la console
    table = drawn(client, "/inspecteur/systeme/processus?vue_pg1=table")
    assert "sys-faculty" not in table and '<table class="hm-table">' in table


def test_a_failing_drawing_gives_back_the_blocks(world, monkeypatch):  # noqa: F811
    client, _, _ = world
    bootstrap(client)

    def broken(got):
        raise RuntimeError("dessin cassé")

    monkeypatch.setattr(pages.DRAWN["fil/jugees"], "draw", broken)
    page = drawn(client, "/inspecteur/fil/jugees")
    assert "judged-list" not in page and 'class="now-card person-list' in page  # la liste de la faculté


def test_nights_read_the_journal_then_one_card_per_night(world):  # noqa: F811
    """Pensées › Nuits : le journal en page de carnet, ce qu'elle en raconte, sa journée en cours ; puis une carte
    par nuit — son journal et ses rêves ensemble, même écrits à part —, la plus récente d'abord. Des journées à venir :
    le journal qu'elle écrit pendant le test, sur l'horloge réelle (celui d'hier), ne passe pas devant."""
    client, live, _ = world
    bootstrap(client)
    voice = VoiceProvenance(call_id="nuit", persona_hash="fictive", role="journal", model="fake")
    append(client, live.kernel, [
        self_.JOURNALED.draft(day="2027-10-17", voice=voice, text=Content.of("Une journée tranquille, à lire.")),
        self_.DREAMT.draft(night="2027-10-18", voice=voice, kind=self_.PLEASANT, vividness=0.8,
                           text=Content.of("Un toit où chaque note allumait une fenêtre.")),
        self_.JOURNALED.draft(day="2027-10-18", voice=voice, text=Content.of("Une soirée au bureau, sous la lampe."),
                              shareable=Content.of("Une soirée calme.")),
    ], "self")
    page = drawn(client, "/inspecteur/pensees/nuits")
    journal = page.split('class="now-card nights-journal"')[1].split("</article>")[0]
    assert "Journal du lun. 18 oct., en entier" in journal and "Une soirée au bureau, sous la lampe." in journal
    assert "Une soirée calme." in journal  # ce qu'elle en raconte à n'importe qui
    assert "Sa journée en cours" in page
    nights = page.split('class="nights-list"')[1]
    assert nights.index("Nuit du lundi 18 oct.") < nights.index("Nuit du dimanche 17 oct.")
    assert nights.count("<h3>Nuit du lundi 18 oct.</h3>") == 1  # le journal et le rêve de cette nuit, ensemble
    night = nights.partition("<h3>Nuit du lundi 18 oct.</h3>")[2].partition("Nuit du dimanche")[0]
    assert night.index("Une soirée au bureau") < night.index("Un toit où chaque note")  # son journal, puis ses rêves


def test_what_she_can_do_is_her_families_and_their_tables(world):  # noqa: F811
    """Outils › Ce qu'elle peut faire (ADR 0134) : ses familles d'outils, chacune avec son tableau de droits né du
    minimum vital, une famille par sous-onglet (ADR 0176) ; une recherche ne garde que les familles qui répondent,
    l'une sous l'autre ; un tableau s'enregistre d'un envoi, et « remettre » revient au minimum vital."""
    client, live, _ = world
    bootstrap(client)
    page = drawn(client, "/inspecteur/outils/tous")
    for part in ("Ses propres outils", 'id="f-memory-title">Mémoire', "minimum vital", "Comportement par défaut",
                 "Régler les droits", "Ce que son prompt dit de ses outils"):
        assert part in page, part
    assert 'name="qui.1|proprietaire" checked' in page and 'name="canal.2|interne" checked' in page
    assert 'type="checkbox" name="o"' not in page  # plus de grille à cocher
    assert 'href="#f-memory">Mémoire <span class="hm-count">2</span>' in page and 'id="f-memory" data-pane' in page
    # chaque outil se dit par son libellé, à qui lit ; sa description, la consigne au modèle où « tu » la désigne, est
    # citée sur sa fiche (audit du 2026-11-05, C6-10)
    listed = page.split('id="f-memory" data-pane', 1)[1].split("</ul>", 1)[0]
    for spec in (s for s in live.kernel.registry.tools.values() if s.bundle == "memory"):
        assert f'<span class="access-tool-desc">{spec.label}</span>' in listed, spec.name
        assert spec.description not in listed, spec.name
    # la famille demandée a sa section en premier : sans ancre, c'est elle que les sous-onglets montrent
    panes = drawn(client, "/inspecteur/outils/tous?famille=memory").split('class="hm-subpanes"', 1)[1]
    assert panes.index('id="f-memory"') < panes.index("data-pane")
    only = drawn(client, "/inspecteur/outils/tous?q=memory_search")
    assert 'id="f-memory-title"' in only and 'id="f-email-title"' not in only and "tout voir" in only
    assert "data-subtabs" not in only  # filtrée : tout ce qui répond se lit d'un coup
    # régler la mémoire : toi seule ; puis revenir au minimum vital
    csrf = client.cookies.get("csrftoken")
    done = client.post("/inspecteur/outils/familles/regler", data={
        "csrf": csrf, "cle": "memory", "faire": "", "ligne.1": "1", "qui.1|proprietaire": "on", "toujours.1": "on",
        "lecture.1": "seule", "action.1": "seule", "garde.1": "public", "tous.1": "on",
        "defaut_lecture": "non", "defaut_action": "non", "defaut_garde": "rien"})
    assert done.status_code == 200 and "enregistrés" in html.unescape(done.text)
    table = client.portal.call(live.settings.families)["memory"]
    assert [(a.who, a.read) for a in table.lines] == [(("proprietaire",), "seule")] and table.default.read == "non"
    back = client.post("/inspecteur/outils/familles/regler", data={"csrf": csrf, "cle": "memory", "faire": "remettre"})
    assert "minimum vital" in html.unescape(back.text) and "memory" not in client.portal.call(live.settings.families)


def test_what_comes_from_elsewhere_is_drawn_as_lines(world):  # noqa: F811
    """Outils › Venus d'ailleurs : brancher un service en bouton de la barre de titre (ADR 0176), leurs réglages
    derrière la roue de Ses outils (ADR 0206) ; une ligne par service branché, une par app, séparées par un filet
    (``person-entries``) — ni les listes génériques de la console, ni une carte dans la carte de leur section. Le nom
    du service mène à sa fiche, une fois : plus de « Ouvrir sa fiche → » qui la redise."""
    client, _, _ = world
    bootstrap(client)
    page = drawn(client, "/inspecteur/outils/serveurs")
    head, body = page.split('<div class="page-head-side">')[1].split('<div class="stack">', 1)
    actions = head.split('<div class="action-bar" role="group" aria-label="Actions">')[1].split("</div>")[0]
    assert "Brancher un service" in actions and "Leurs réglages" not in actions
    gear = head.split('class="action-bar"', 1)[1]
    assert 'href="/inspecteur/outils/parametres"' in gear and "Paramètres</a>" in gear
    assert "Paramètres des services" not in gear  # le nom de la roue à une page, partout (audit du 2026-11-05, C6-Q3)
    assert "Brancher un service</a>" not in body
    assert "Les services branchés" in page and "Les outils de ses apps" in page
    assert "Comprendre cette liste" not in page and "un nouveau service" not in page
    assert "elsewhere-item" not in page and "Ouvrir sa fiche" not in page
    services = page.split('aria-labelledby="elsewhere-services"')[1].split("</section>", 1)[0]
    assert '<ul class="person-entries" role="list">' in services
    web = next(li for li in services.split("<li>")[1:] if '>web</a>' in li)
    assert web.count('href="/inspecteur/fiche/serveur/web"') == 1, web
    assert services.count('href="/inspecteur/fiche/serveur/web"') == 1


def test_an_app_and_a_service_to_review_from_elsewhere_are_lines_too():
    """Venus d'ailleurs, ce que le monde de test n'a pas : un service à revoir, avec sa note, et une app et ses
    outils. Chacun est une ligne de ``person-entries``, dont le nom est le lien (seule « Les regarder », dans l'alerte,
    mène aussi à la fiche) ; chaque ligne dit encore tout ce qu'elle disait."""
    page = html.unescape(env.get_template("handmade/outils/ailleurs.html").render(
        owners=[], services_empty="", apps_empty="",
        services=[{"name": "meteo", "href": "/inspecteur/fiche/serveur/meteo", "owner": "Adrien",
                   "owner_href": "/inspecteur/fiche/person/user_1", "state": "connecté", "tone": "ok",
                   "purpose": "la météo du jour", "where": "sur cette machine", "served": "1", "offered": "2",
                   "review": 2, "joined": "hier", "notes": ["Il a mis du temps à répondre."], "who": "toi",
                   "access": "1 ligne · par défaut : fermé"}],
        apps=[{"title": "Factures", "href": "/inspecteur/apps?app=factures", "state": "sert avec toi", "tone": "ok",
               "tools": [{"name": "app_factures_lire", "what": "lire une facture", "args": "numero"}]}]))
    assert not ConsoleHTML(page).errors
    assert "elsewhere-item" not in page and "Ouvrir" not in page
    assert page.count('<ul class="person-entries" role="list">') == 2
    service, app = page.split('aria-labelledby="elsewhere-apps"')
    for said in ('<a href="/inspecteur/fiche/serveur/meteo">meteo</a>', "connecté", "La météo du jour",
                 "Avec toi", "1 ligne · par défaut : fermé", '<a href="/inspecteur/fiche/person/user_1">Adrien</a>',
                 "<b>1</b> outil servi sur 2 proposés", "sur cette machine", "joint hier",
                 "2 outils à revoir : nouveaux ou changés depuis ton accord.", "Il a mis du temps à répondre."):
        assert said in service, said
    assert service.count('href="/inspecteur/fiche/serveur/meteo"') == 2  # son nom, et « Les regarder »
    for said in ('<a href="/inspecteur/apps?app=factures">Factures</a>', "sert avec toi", "Lire une facture",
                 "<code>app_factures_lire</code>", "arguments <code>numero</code>"):
        assert said in app, said
    assert app.count('href="/inspecteur/apps?app=factures"') == 1


def test_a_means_of_communication_is_drawn(world):  # noqa: F811
    """La fiche d'un moyen de communication : son en-tête et « En bref » (quatre tuiles — dont ce que le canal
    prouve, et pourquoi —, qui écrit d'ici, ce que ça ouvre en privé et en public) ; son fil en bulles ; son verdict
    sous « Le détail », et seulement là. En bref ne redit pas l'en-tête : ni « Le canal », ni la certitude. Un compte
    authentifié prouve déjà qui écrit : pas d'onglet « Revendication »."""
    client, _, _ = world
    bootstrap(client)
    chat(client, "salut ! je reviens d'un concert")
    page = drawn(client, "/inspecteur/fiche/handle/user_1")
    assert 'class="handle-head"' in page and "Par le chat, dans un navigateur" in page
    for part in ("En bref", "Ce que le canal prouve", "session vérifiée", "Qui écrit d'ici", "Vue pour la première fois",
                 "Sa clé", "Ce que ça ouvre", "En privé", "En public"):
        assert part in page, part
    brief = page.split('class="now-page handle"')[1].split('aria-labelledby="handle-opens"')[0]
    for gone in ("Le canal", "Ce qu'il prouve", "Certitude", "certitude", "Le verdict, pas à pas"):
        assert gone not in brief, gone
    assert page.count("Dernier message reçu") == 1 and page.count("Elle peut lui écrire d'elle-même") == 1
    assert "Le verdict, pas à pas" not in page  # replié en bas d'En bref, il redisait l'onglet Verdict
    more = page.split('<details class="tabs-more')[1].split("</details>")[0]
    assert "onglet=verdict" in more and "onglet=autres" in more
    assert "onglet=revendication" not in page
    thread = drawn(client, "/inspecteur/fiche/handle/user_1?onglet=fil")
    assert 'class="person-thread"' in thread and "salut ! je reviens d'un concert" in thread


def test_the_other_tabs_of_a_means_of_communication_are_drawn_block_by_block(world):  # noqa: F811
    """Preuves, Ses autres moyens de communication et Verdict, dessinés bloc par bloc comme le détail d'une personne :
    l'état vide se dit une fois, sans « aucun » ni « Page 1 sur 1 » d'une pagination d'une seule page ; Verdict dit le
    verdict pas à pas sans redire les faits du moyen de communication (l'en-tête et En bref les disent)."""
    client, _, _ = world
    bootstrap(client)
    chat(client, "salut ! je reviens d'un concert")
    proofs = drawn(client, "/inspecteur/fiche/handle/user_1?onglet=preuves")
    body = proofs.split('class="now-page person-tab"')[1]
    assert body.lower().count("aucune revendication, preuve ni liaison") == 1  # la majuscule : la feuille de style
    assert "Page 1 sur 1" not in body and ">aucun<" not in body and 'class="pager"' not in body
    others = drawn(client, "/inspecteur/fiche/handle/user_1?onglet=autres")
    body = others.split('class="now-page person-tab"')[1]
    assert body.lower().count("aucun autre moyen de communication ne parle pour cette personne") == 1
    assert "Page 1 sur 1" not in body and ">aucun<" not in body
    verdict = drawn(client, "/inspecteur/fiche/handle/user_1?onglet=verdict")
    body = verdict.split('class="now-page person-tab"')[1]
    assert "Le verdict, pas à pas" in body and "Ce que ça ouvre" in body
    assert "Le moyen de communication" not in body and "Page 1 sur 1" not in body
