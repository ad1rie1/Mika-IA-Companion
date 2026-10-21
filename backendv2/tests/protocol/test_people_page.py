"""Personnes (``app/handmade/people.py``), à travers le vrai serveur : la page d'entrée de la destination, dessinée —
une carte par personne (ce qu'elle est pour elle, ce qu'elle ressent, ce qui se passe entre elles), qui est là ; on
cherche, on filtre ; les onglets des facultés restent, sous « Le détail »."""

from __future__ import annotations

import html
import re

from mika.app.handmade import people
from tests.fixtures.console_html import ConsoleHTML
from tests.protocol.test_now_page import chat
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def test_only_an_operator_sees_the_people(world):  # noqa: F811
    client, _, _ = world
    page = client.get(people.BASE, follow_redirects=False)
    assert page.status_code == 303 and page.headers["location"].endswith("/inspecteur/connexion")
    assert client.get(people.FRAGMENT).status_code == 401


def test_a_card_per_person(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    chat(client)
    page = client.get(people.BASE)
    assert page.status_code == 200
    ConsoleHTML(page.text).check()
    text = html.unescape(page.text)
    assert "<h1>Personnes</h1>" in text and re.search(r'<a class="nav-item on" href="/inspecteur/personnes"', text)
    assert " style=" not in text and not re.search(r"<script(?![^>]*\bsrc=)", text)
    card = re.search(r'<li class="people-card.*?</li>\s*</ul>', text, re.S).group()
    assert '<a href="/inspecteur/fiche/person/user_1">adrien</a>' in card
    assert '<span class="now-tag owner">propriétaire</span>' in card and "lui a écrit à l'instant" in card
    # les onglets des facultés restent, sous « Le détail »
    assert all(f'href="/inspecteur/personnes/{tab}"' in text for tab in ("personnes", "liens", "presents"))
    for tab in ("personnes", "liens", "presents"):
        assert client.get(f"/inspecteur/personnes/{tab}").status_code == 200, tab


def test_search_and_filters(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    chat(client)
    found = html.unescape(client.get(f"{people.BASE}?q=adri").text)
    assert 'href="/inspecteur/fiche/person/user_1"' in found and 'value="adri"' in found
    nobody = html.unescape(client.get(f"{people.BASE}?q=personne-inconnue").text)
    assert "Personne ne correspond à « personne-inconnue »" in nobody and "people-card" not in nobody
    # une proximité choisie : la pastille s'allume, la recherche est gardée
    level = html.unescape(client.get(f"{people.BASE}?q=adri&proximite=friend").text)
    assert re.search(r'<a class="people-chip on" href="/inspecteur/personnes\?q=adri&proximite=friend"', level)
    fragment = client.get(f"{people.FRAGMENT}?q=adri")
    assert fragment.status_code == 200 and "<h1" not in fragment.text and "data-now-stamp" in fragment.text
