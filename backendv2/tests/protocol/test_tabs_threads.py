"""Relations & échanges › Conversations › Questions sans réponse dans sa forme (``app/handmade/tabs/threads.py``,
ADR 0177), à travers le vrai serveur : chaque question dans sa bulle, depuis combien de temps elle attend, le message
source et la conversation sur sa ligne."""

from __future__ import annotations

from mika.app.handmade.tabs import Line, threads
from mika.contracts import runtime as rt
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.events import Content, Origin
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_tabs_people import emit
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


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
