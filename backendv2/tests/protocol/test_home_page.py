"""L'accueil (``app/handmade/home.py``), à travers le vrai serveur : ce qui attend l'opératrice (une ligne par page
où décider), comment elle va, qui est là, la journée en chiffres et ses derniers épisodes ; il se relit seul."""

from __future__ import annotations

import html
import re

from mika.app.handmade import home
from mika.kernel.inspect import Note, Ref, Stat, Stats
from tests.fixtures.console_html import ConsoleHTML
from tests.protocol.test_now_page import chat
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def test_only_an_operator_opens_the_home(world):  # noqa: F811
    client, _, _ = world
    for url in home.BASES:
        page = client.get(url, follow_redirects=False)
        assert page.status_code == 303 and page.headers["location"].endswith("/inspecteur/connexion"), url
    assert client.get(home.FRAGMENT).status_code == 401


def test_the_home_says_what_waits_how_she_is_and_what_she_did(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    chat(client, "salut, tu vas bien ?")
    page = client.get("/inspecteur/")
    assert page.status_code == 200
    ConsoleHTML(page.text).check()
    text = html.unescape(page.text)
    assert "<h1>Vue d'ensemble</h1>" in text and re.search(r'<a class="nav-item on" href="/inspecteur/"', text)
    assert " style=" not in text and not re.search(r"<script(?![^>]*\bsrc=)", text)
    assert "À regarder maintenant" in text and ", en ce moment</h2>" in text and "Qui est là" in text
    assert '<a href="/inspecteur/fiche/person/user_1">adrien</a>' in text  # en ligne, sur sa carte
    assert "réponses" in text and "Derniers épisodes" in text and "Comprendre le résultat" in text
    assert client.get("/inspecteur/accueil").status_code == 200
    fragment = client.get(home.FRAGMENT)
    assert fragment.status_code == 200 and "<h1" not in fragment.text and "data-now-stamp" in fragment.text


def test_one_line_per_page_where_to_decide():
    """Un badge, son cadre et un contrôle de santé qui mènent à la même page font une seule ligne : la plus grave, et
    à gravité égale la plus précise ; « tout va bien » ne se dit que s'il n'y a rien."""
    processes = Ref("local", "/inspecteur/systeme/processus", "Processus")
    got = home.priorities([
        Stats((Stat("Système › Processus", 1, "à regarder", "warn", processes),
               Stat("Processus en échec", 1, "Retenir (souvenirs, croyances)", "danger", processes),
               Stat("Système › Santé générale", 1, "à regarder", "warn",
                    Ref("local", "/inspecteur/systeme/sante", "Santé")))),
        Note("1 processus en échec", "warn", title="Santé · Processus de fond"),
    ])
    assert [(r["label"], r["sub"]) for r in got["rows"]] == [
        ("Processus en échec", "Retenir (souvenirs, croyances)"), ("Santé · Processus de fond", "1 processus en échec")]
    assert got["calm"] is None
    calm = home.priorities([Note("Rien ne demande ton attention.", "ok", title="Tout va bien")])
    assert calm == {"rows": [], "calm": {"title": "Tout va bien", "text": "Rien ne demande ton attention."}}
