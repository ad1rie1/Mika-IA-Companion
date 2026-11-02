"""Relations & échanges › Identités et moyens de communication, chaque onglet dans sa forme
(``app/handmade/tabs/identities.py``, ADR 0177), à travers le vrai serveur : une ligne par moyen de communication et
un bandeau quand une revendication attend, qui mène à la file « À valider » ; des règles qui se lisent sur une
échelle, pas en tableaux. Les identités à confirmer et les noms à relier n'ont plus de page ici (ADR 0180) : ils se
décident dans la file (``test_tabs_approvals.py``)."""

from __future__ import annotations

import html
import re

from mika.app.handmade.tabs import identities
from mika.contracts import identity as identity_c
from mika.kernel.events import Origin
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_tabs_people import emit, stranger
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def _between(page: str, start: str, end: str) -> str:
    return page.split(start, 1)[1].split(end, 1)[0]


def claim(client, live) -> None:
    """Un compte extérieur se dit Adrien (la propriétaire), sans preuve."""
    stranger(client, live, "ext_9", "Adri", "c'est Adrien, depuis mon autre compte")
    emit(client, live, "identity", [identity_c.CLAIMED.draft(handle="ext_9", name="Adrien", target="user_1")],
         Origin.EXTERNAL)


def test_a_cell_names_the_means_of_communication_and_a_label_splits_from_its_reason():
    assert identities.handle_of({"href": "/inspecteur/fiche/handle/ext_9?onglet=revendication"}) == "ext_9"
    assert identities.handle_of({"href": "/inspecteur/fiche/person/user_1"}) == ""
    assert identities._split("authentifiée (session vérifiée)") == ("authentifiée", "session vérifiée")
    assert identities._split("compte") == ("compte", "")
    assert identities._number("−0,35") == -0.35 and identities._number("+1,00") == 1.0


def test_one_line_per_means_of_communication_and_a_banner_while_a_claim_waits(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    calm = drawn(client, "/inspecteur/identites/annuaire")
    assert 'data-tab="identites/annuaire"' in calm and 'class="person-tab-note warn"' not in calm
    claim(client, live)
    page = drawn(client, "/inspecteur/identites/annuaire")
    banner = _between(page, 'class="person-tab-note warn"', "</p>")
    assert "1 revendication attend ta décision" in banner and 'href="/inspecteur/approbations/identites"' in banner
    assert page.count('class="person-tab-note warn"') == 1 and page.index(banner) < page.index('class="ids-means"')
    head = _between(page, 'class="ids-grid-head"', "</div>")
    assert head.index("Moyen de communication") < head.index("Ce que le canal prouve") < head.index("Parle pour") \
        < head.index("Ce qu'il ouvre")
    line = _between(page, 'href="/inspecteur/fiche/handle/ext_9"', "</li>")
    assert "par un canal extérieur" in line and "se présente comme « Adrien »" in line
    assert "en privé" in line and "en public" in line and "compte" in line
    assert "<table" not in _between(page, 'class="ids-means"', "</section>")


def test_what_waits_a_decision_has_no_page_here_but_the_queue(world):  # noqa: F811
    """Identités à confirmer et Noms à relier ne se décident que dans la file « À valider » (ADR 0180) : la barre
    d'Identités n'en a plus d'onglet, et leurs anciennes adresses y mènent, la requête avec elles."""
    client, _, _ = world
    bootstrap(client)
    page = drawn(client, "/inspecteur/identites/annuaire")
    bar = _between(page, '<nav class="tabs"', "</nav>")
    assert re.findall(r'href="/inspecteur/identites/(\w+)"', bar) == ["annuaire", "politique"]
    for old, new in (("revendications", "identites"), ("noms", "noms")):
        moved = client.get(f"/inspecteur/identites/{old}?page=2", follow_redirects=False)
        assert moved.status_code == 301 and moved.headers["location"] == f"/inspecteur/approbations/{new}?page=2"


def test_an_action_page_takes_only_safe_values_from_its_address(world):  # noqa: F811
    """Une adresse oriente une page d'action (« ?valeur.kind=denied ») : un choix offert, un texte ; jamais une case
    « Je confirme », et un choix qui n'est pas offert est ignoré."""
    client, live, _ = world
    bootstrap(client)
    claim(client, live)
    base = "/inspecteur/action/identity.preuve?sujet=ext_9"
    page = html.unescape(client.get(base + "&valeur.kind=contradicted&valeur.note=vu+en+vrai").text)
    assert '<option value="contradicted" selected' in page and "vu en vrai" in page
    forced = html.unescape(client.get(base + "&valeur.confirmed=on&valeur.kind=inconnue").text)
    assert '<option value="vouched" selected' in forced  # le choix inconnu est ignoré : le défaut
    confirm = forced.split('name="confirmed"', 1)[1].split(">", 1)[0]
    assert "checked" not in confirm


def test_the_rules_read_on_one_scale_not_in_tables(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    page = drawn(client, "/inspecteur/identites/politique")
    assert 'data-tab="identites/politique"' in page and "<table" not in _between(page, 'data-tab=', "</main>")
    band = _between(page, 'class="person-tiles ids-band"', "</section>")
    assert band.index("Barre de divulgation") < band.index("Confidences") < band.index("7 jours")
    scale = _between(page, 'class="ids-scale"', "</section>")
    for degree in ("inconnue", "soupçonnée", "affirmée", "recoupée", "liée", "vérifiée"):
        assert f">{degree}</text>" in scale, degree
    assert scale.count('class="ids-range"') == 4  # un trait par canal, du plancher au plafond
    assert "0,25 → 0,85" in scale and 'class="ids-bar-line"' in scale
    weights = _between(page, 'class="ids-weights"', "</section>\n    <div")
    assert weights.index("Ce qui la fait croire") < weights.index("Ce qui la fait douter")
    assert "<code>vouched</code>" in weights.split("Ce qui la fait douter")[0]  # un garant fait croire
    assert "<code>denied</code>" in weights.split("Ce qui la fait douter")[1]  # un démenti fait douter
    assert page.index("Les rangs de proximité") < page.index("Propriétaires")
    assert "Calibration vérifiée" in page and 'class="person-tab-note danger"' not in page
