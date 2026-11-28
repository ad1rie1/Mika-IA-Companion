"""Relations & échanges › Conversations dans sa forme (``app/handmade/tabs/threads.py``, ADR 0177 et 0181), à travers
le vrai serveur : par personne, une ligne par personne avec son dernier message et ce qui attend, qui mène à leur
conversation (l'onglet Échanges de sa fiche, les plus récents en premier) ; chaque question sans réponse dans sa bulle,
depuis combien de temps elle attend, le message source et la conversation sur sa ligne."""

from __future__ import annotations

from mika.app.handmade.tabs import Line, threads
from mika.contracts import runtime as rt
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.events import Content, Origin
from mika.kernel.inspect import Ref, Table
from mika.runtime.inspection import Inspection
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
    assert "aucune conversation pour l'instant" in drawn(client, "/admin/fil/conversations")
    chat(client, "salut ! je reviens d'un concert")
    stranger(client, live, "ext_7", "Léa", "tu es là ?")
    page = drawn(client, "/admin/fil")  # l'onglet par défaut de Conversations
    assert 'data-tab="fil/conversations"' in page and "1 avec une question sans réponse" in page
    items = page.split('<li class="fil-conv')[1:]
    assert len(items) == 2
    lea, adrien = items  # la plus récente d'abord
    assert "Léa" in lea and "tu es là ?" in lea and "1 sans réponse" in lea and "par compte extérieur" in lea
    assert 'href="/admin/fiche/person/ext_7?onglet=echanges"' in lea and "elle :" not in lea
    assert lea.startswith(" asks") and not adrien.startswith(" asks")
    assert "elle :" in adrien and "2 messages · par web" in adrien  # sa réponse est le dernier message
    assert 'href="/admin/fiche/person/user_1?onglet=echanges"' in adrien
    only = drawn(client, "/admin/fil/conversations?handle=lea")  # casse et accents ignorés
    assert only.count('<li class="fil-conv') == 1 and "tu es là ?" in only
    assert "personne ne s'appelle « zoé »" in drawn(client, "/admin/fil/conversations?handle=zoé")
    table = drawn(client, "/admin/fil/conversations?vue_pg1=table")
    assert '<table class="hm-table">' in table and "fil-inbox" not in table
    # un mot cherché : les conversations où il a été dit, chacune avec ce message-là ; la recherche y mène
    concert = drawn(client, "/admin/fil/conversations?q=CONCERT")
    assert concert.count('<li class="fil-conv') == 1 and "je reviens d'un concert" in concert
    assert "« CONCERT » a été dit" in concert
    assert "« crêpes » n'a été dit dans aucune conversation" in drawn(client, "/admin/fil/conversations?q=crêpes")
    search = drawn(client, "/admin/recherche?q=concert")
    assert "fil/conversations?q=concert" in search and "transcript/messages" not in search


def test_their_conversation_reads_the_latest_first(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    chat(client, "salut ! je reviens d'un concert")
    said(client, live, "et toi, ta soirée ?")
    page = drawn(client, "/admin/fiche/person/user_1?onglet=echanges")
    assert page.index("et toi, ta soirée ?") < page.index("je reviens d'un concert")
    # une conversation d'une seule page ne dit pas « Page 1 sur 1 », ni sur la fiche de son moyen de communication
    chat_card = page.split('class="now-card person-chat"', 1)[1].split("</section>", 1)[0]
    assert 'class="pager"' not in chat_card and "Page 1 sur 1" not in page
    assert "Page 1 sur 1" not in drawn(client, "/admin/fiche/handle/user_1?onglet=fil")


def test_a_waiting_question_in_its_bubble_with_how_long_it_waits(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    assert "Aucune question en attente" in drawn(client, "/admin/fil/questions")
    emit(client, live, "runtime", [rt.PERCEPTION_RECEIVED.draft(
        handle="user_1", channel="web", authenticated=True,
        text=Content.of("Tu peux me résumer ce qui reste pour le stream ?"))], Origin.EXTERNAL)
    page = drawn(client, "/admin/fil/questions")
    item = page.split('class="fil-q ', 1)[1].split("</li>", 1)[0]
    assert item.index("attend depuis") < item.index("Tu peux me résumer ce qui reste pour le stream ?")
    assert "< 1 min" in item and 'class="person-bubble' in item
    assert 'href="/admin/evenement/' in item and "Voir le message source" in item
    assert 'href="/admin/fiche/person/user_1?onglet=echanges">Leur conversation' in item
    assert ">adrien</a>" in item and "(user_1)" not in item  # son nom ; sa clé reste dans le lien de sa fiche
    assert "la plus ancienne attend depuis" in page and 'href="?vue_pg1=table"' in page
    assert "Une question reste ici tant qu'aucune réponse ne l'a réglée" in page  # l'aide de la faculté


def test_the_whole_thread_served_in_mcp_still_finds_a_person_by_name_or_by_key(world):  # noqa: F811
    """La vue cachée de tout le fil (servie à la console en MCP) cherche dans le nom et dans la clé : les autres
    vues disent le nom seul, celle-ci garde par quel moyen de communication chaque message est venu."""
    client, live, _ = world
    bootstrap(client)
    chat(client, "salut ! je reviens d'un concert")
    stranger(client, live, "ext_7", "Léa", "tu es là ?")
    ins = Inspection(live.kernel)
    spec = ins.find("transcript", "messages")

    def senders(handle: str) -> set[str]:
        blocks = client.portal.call(lambda: ins.run(spec, {"handle": handle}))
        table = next(b for b in blocks if isinstance(b, Table))
        return {cell.text for row in table.rows for cell in row.cells if isinstance(cell, Ref) and cell.kind == "subject"}

    assert senders("ext_") == {"Léa (ext_7)"}  # un bout de clé
    assert senders("user_1") and all(s.endswith("(user_1)") for s in senders("user_1"))
    assert senders("léa") == {"Léa (ext_7)"}  # son nom


def test_a_long_wait_is_said_then_alerted():
    line = Line({"de": {"t": "link", "text": "Béa", "href": "/admin/fiche/person/user_2"},
                 "texte": {"t": "text", "text": "Tu viens samedi ?"}}, {}, "/admin/evenement/7", "", [], False,
                {})
    now = 10 * DAY
    assert threads._question(line, now - 30 * MINUTE, now)["tone"] == ""
    hour = threads._question(line, now - 2 * HOUR, now)
    assert hour["tone"] == "warn" and hour["wait"] == "2 h"
    assert threads._question(line, now - 2 * DAY, now)["tone"] == "danger"
    assert hour["exchanges"] == "/admin/fiche/person/user_2?onglet=echanges"
