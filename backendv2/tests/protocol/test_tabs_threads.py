"""Relations & échanges › Conversations dans sa forme (``app/handmade/tabs/threads.py``, ADR 0177 et 0181), à travers
le vrai serveur : par personne, une ligne par personne avec son dernier message et ce qui attend, qui mène à leur
conversation (l'onglet Échanges de sa fiche, les plus récents en premier) ; chaque question sans réponse dans sa bulle,
depuis combien de temps elle attend, le message source et la conversation sur sa ligne."""

from __future__ import annotations

from mika.app.handmade.tabs import Line, threads
from mika.contracts import runtime as rt
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.events import Content, Origin
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_now_page import chat
from tests.protocol.test_tabs_people import emit, stranger
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def said(client, live, text: str) -> None:
    """Adrien écrit encore, depuis le web (le message seul, au journal)."""
    emit(client, live, "runtime", [rt.PERCEPTION_RECEIVED.draft(
        handle="user_1", channel="web", authenticated=True, text=Content.of(text))], Origin.EXTERNAL)


def test_one_line_per_person_the_latest_first_with_what_waits(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    assert "aucune conversation pour l'instant" in drawn(client, "/inspecteur/fil/conversations")
    chat(client, "salut ! je reviens d'un concert")
    stranger(client, live, "ext_7", "Léa", "tu es là ?")
    page = drawn(client, "/inspecteur/fil")  # l'onglet par défaut de Conversations
    assert 'data-tab="fil/conversations"' in page and "1 avec une question sans réponse" in page
    items = page.split('<li class="fil-conv')[1:]
    assert len(items) == 2
    lea, adrien = items  # la plus récente d'abord
    assert "Léa" in lea and "tu es là ?" in lea and "1 sans réponse" in lea and "par compte extérieur" in lea
    assert 'href="/inspecteur/fiche/person/ext_7?onglet=echanges"' in lea and "elle :" not in lea
    assert lea.startswith(" asks") and not adrien.startswith(" asks")
    assert "elle :" in adrien and "2 messages · par web" in adrien  # sa réponse est le dernier message
    assert 'href="/inspecteur/fiche/person/user_1?onglet=echanges"' in adrien
    only = drawn(client, "/inspecteur/fil/conversations?handle=lea")  # casse et accents ignorés
    assert only.count('<li class="fil-conv') == 1 and "tu es là ?" in only
    assert "personne ne s'appelle « zoé »" in drawn(client, "/inspecteur/fil/conversations?handle=zoé")
    table = drawn(client, "/inspecteur/fil/conversations?vue_pg1=table")
    assert '<table class="hm-table">' in table and "fil-inbox" not in table
    # un mot cherché : les conversations où il a été dit, chacune avec ce message-là ; la recherche y mène
    concert = drawn(client, "/inspecteur/fil/conversations?q=CONCERT")
    assert concert.count('<li class="fil-conv') == 1 and "je reviens d'un concert" in concert
    assert "« CONCERT » a été dit" in concert
    assert "« crêpes » n'a été dit dans aucune conversation" in drawn(client, "/inspecteur/fil/conversations?q=crêpes")
    search = drawn(client, "/inspecteur/recherche?q=concert")
    assert "fil/conversations?q=concert" in search and "transcript/messages" not in search


def test_their_conversation_reads_the_latest_first(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    chat(client, "salut ! je reviens d'un concert")
    said(client, live, "et toi, ta soirée ?")
    page = drawn(client, "/inspecteur/fiche/person/user_1?onglet=echanges")
    assert page.index("et toi, ta soirée ?") < page.index("je reviens d'un concert")


def test_a_waiting_question_in_its_bubble_with_how_long_it_waits(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    assert "Aucune question en attente" in drawn(client, "/inspecteur/fil/questions")
    emit(client, live, "runtime", [rt.PERCEPTION_RECEIVED.draft(
        handle="user_1", channel="web", authenticated=True,
        text=Content.of("Tu peux me résumer ce qui reste pour le stream ?"))], Origin.EXTERNAL)
    page = drawn(client, "/inspecteur/fil/questions")
    item = page.split('class="fil-q ', 1)[1].split("</li>", 1)[0]
    assert item.index("attend depuis") < item.index("Tu peux me résumer ce qui reste pour le stream ?")
    assert "< 1 min" in item and 'class="person-bubble' in item
    assert 'href="/inspecteur/evenement/' in item and "Voir le message source" in item
    assert 'href="/inspecteur/fiche/person/user_1?onglet=echanges">Leur conversation' in item
    assert "la plus ancienne attend depuis" in page and 'href="?vue_pg1=table"' in page
    assert "Une question reste ici tant qu'aucune réponse ne l'a réglée" in page  # l'aide de la faculté


def test_a_long_wait_is_said_then_alerted():
    line = Line({"de": {"t": "link", "text": "Béa", "href": "/inspecteur/fiche/person/user_2"},
                 "texte": {"t": "text", "text": "Tu viens samedi ?"}}, {}, "/inspecteur/evenement/7", "", [], False,
                {})
    now = 10 * DAY
    assert threads._question(line, now - 30 * MINUTE, now)["tone"] == ""
    hour = threads._question(line, now - 2 * HOUR, now)
    assert hour["tone"] == "warn" and hour["wait"] == "2 h"
    assert threads._question(line, now - 2 * DAY, now)["tone"] == "danger"
    assert hour["exchanges"] == "/inspecteur/fiche/person/user_2?onglet=echanges"
