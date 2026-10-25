"""Les onglets des destinations dessinés (``app/handmade/pages.py``, ADR 0121), à travers le vrai serveur : chacun
garde les données et les filtres de sa faculté, sous une autre forme ; demandée en tableau, la liste revient à la
console ; un dessin qui échoue rend la main aux blocs."""

from __future__ import annotations

import html

import pytest

from mika.app.handmade import pages
from mika.contracts import self_
from mika.kernel.events import Content, VoiceProvenance
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
    messages = drawn(client, "/inspecteur/fil/messages")
    assert 'class="now-card person-chat"' in messages and "salut ! je reviens d'un concert" in messages
    assert "/static/handmade/base.css" in messages and '<table class="tbl">' not in messages
    assert "/inspecteur/fil" in messages  # l'onglet par défaut de la destination, dessiné aussi
    assert 'class="now-card person-chat"' in drawn(client, "/inspecteur/fil")
    table = drawn(client, "/inspecteur/fil/messages?vue_pg1=table")
    assert '<table class="hm-table">' in table and "person-chat" not in table
    judged = drawn(client, "/inspecteur/fil/jugees")
    assert 'class="now-page person-tab"' in judged and "aucune réponse jugée" in judged
    questions = drawn(client, "/inspecteur/fil/questions")
    assert 'class="now-page person-tab"' in questions


@pytest.mark.parametrize("where", sorted(pages.DRAWN))
def test_every_drawn_tab_opens(world, where):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    url = where.replace("*", "affect")  # « destination/préfixe-* » : un de ses onglets
    page = client.get(f"/inspecteur/{url}", follow_redirects=False)
    assert page.status_code == 200, where
    ConsoleHTML(page.text).check()
    assert 'class="now-page' in page.text, where  # le dessin, pas le repli sur les blocs


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

    def broken(ui, items, query):
        raise RuntimeError("dessin cassé")

    monkeypatch.setattr(pages.DRAWN["fil/messages"], "draw", broken)
    page = drawn(client, "/inspecteur/fil/messages")
    assert "person-chat" not in page and 'class="now-card person-list' in page  # la liste de la faculté


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
    minimum vital ; une recherche ne garde que les familles qui répondent ; un tableau s'enregistre d'un envoi, et
    « remettre » revient au minimum vital."""
    client, live, _ = world
    bootstrap(client)
    page = drawn(client, "/inspecteur/outils/tous")
    for part in ("Ses propres outils", 'id="f-memory-title">Mémoire', "minimum vital", "Comportement par défaut",
                 "Régler les droits", "Ce que son prompt dit de ses outils"):
        assert part in page, part
    assert 'name="qui.1|proprietaire" checked' in page and 'name="canal.2|interne" checked' in page
    assert 'type="checkbox" name="o"' not in page  # plus de grille à cocher
    only = drawn(client, "/inspecteur/outils/tous?q=memory_search")
    assert 'id="f-memory-title"' in only and 'id="f-email-title"' not in only and "tout voir" in only
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
    """Outils › Venus d'ailleurs : brancher un service et leurs réglages en boutons ; une carte par service branché,
    une par app — pas les listes génériques de la console."""
    client, _, _ = world
    bootstrap(client)
    page = drawn(client, "/inspecteur/outils/serveurs")
    actions = page.split('class="toolbar hm-toolbar elsewhere-actions"')[1].split("</div>")[0]
    assert "Brancher un service" in actions and "Leurs réglages" in actions
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
