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
from mika.app.handmade import blocks as drawn_blocks
from mika.app.handmade import pages, plain
from mika.app.handmade.lists import text as cell_text
from mika.app.handmade.tabs import Tab
from mika.app.handmade.tabs import text as tabs_text
from mika.contracts import self_
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
    """Les modules repris dans ``tabs/`` (K0-10) : ni un gabarit, ni une feuille, ni le code ne renvoient à eux. Ce sont
    justement les commentaires qu'on lit ici, pour savoir où aller : le texte, pas l'arbre du code."""
    gone = re.compile(r"app/handmade/(?:nights|conversations|mail|running|tools|senses|system)\.py")
    root = Path(mika.__file__).parent
    cited = [f"{path.relative_to(root)}:{at}" for path in sorted(root.rglob("*"))
             if path.suffix in (".py", ".html", ".css", ".js") and "__pycache__" not in path.parts
             for at, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if gone.search(line)]
    assert cited == []


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
    assert "Lundi 18 oct." in journal and "Une soirée au bureau, sous la lampe." in journal
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


def test_what_comes_from_elsewhere_is_drawn_as_cards(world):  # noqa: F811
    """Outils › Venus d'ailleurs : brancher un service en bouton de la barre de titre (ADR 0176), leurs réglages
    derrière la roue de Ses outils (ADR 0206) ; une carte par service branché, une par app — pas les listes
    génériques de la console."""
    client, _, _ = world
    bootstrap(client)
    page = drawn(client, "/inspecteur/outils/serveurs")
    head, body = page.split('<div class="page-head-side">')[1].split('<div class="stack">', 1)
    actions = head.split('<div class="action-bar" role="group" aria-label="Actions">')[1].split("</div>")[0]
    assert "Brancher un service" in actions and "Leurs réglages" not in actions
    gear = head.split('class="action-bar"', 1)[1]
    assert 'href="/inspecteur/outils/parametres"' in gear and "Paramètres des services" in gear
    assert "Brancher un service</a>" not in body
    assert "Les services branchés" in page and "Les outils de ses apps" in page
    assert "Comprendre cette liste" not in page and "un nouveau service" not in page


def test_a_means_of_communication_is_drawn(world):  # noqa: F811
    """La fiche d'un moyen de communication : son en-tête et « En bref » (le canal et ce qu'il prouve, qui écrit
    d'ici, ce que ça ouvre en privé et en public) ; son fil en bulles ; son verdict sous « Le détail ». Un compte
    authentifié prouve déjà qui écrit : pas d'onglet « Revendication »."""
    client, _, _ = world
    bootstrap(client)
    chat(client, "salut ! je reviens d'un concert")
    page = drawn(client, "/inspecteur/fiche/handle/user_1")
    assert 'class="handle-head"' in page and "Par le chat, dans un navigateur" in page
    for part in ("En bref", "Le canal", "Ce qu'il prouve", "Qui écrit d'ici", "Ce que ça ouvre", "En privé",
                 "En public", "Le verdict, pas à pas"):
        assert part in page, part
    more = page.split('<details class="tabs-more')[1].split("</details>")[0]
    assert "onglet=verdict" in more and "onglet=autres" in more
    assert "onglet=revendication" not in page
    thread = drawn(client, "/inspecteur/fiche/handle/user_1?onglet=fil")
    assert 'class="person-thread"' in thread and "salut ! je reviens d'un concert" in thread
