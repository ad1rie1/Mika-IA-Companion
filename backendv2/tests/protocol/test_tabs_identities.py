"""Relations & échanges › Identités et moyens de communication, chaque onglet dans sa forme
(``app/handmade/tabs/identities.py``, ADR 0177), à travers le vrai serveur : une ligne par moyen de communication et
un bandeau quand une revendication attend ; deux files à valider dont les actions sont sur chaque ligne ; des règles
qui se lisent sur une échelle, pas en tableaux."""

from __future__ import annotations

import html
from urllib.parse import parse_qs, urlsplit

from mika.app.handmade.tabs import identities
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.kernel.events import Content, Origin
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
    assert "1 revendication attend ta décision" in banner and 'href="/inspecteur/facultes/identity/revendications"' in banner
    assert page.count('class="person-tab-note warn"') == 1 and page.index(banner) < page.index('class="ids-means"')
    head = _between(page, 'class="ids-grid-head"', "</div>")
    assert head.index("Moyen de communication") < head.index("Ce que le canal prouve") < head.index("Parle pour") \
        < head.index("Ce qu'il ouvre")
    line = _between(page, 'href="/inspecteur/fiche/handle/ext_9"', "</li>")
    assert "par un canal extérieur" in line and "se présente comme « Adrien »" in line
    assert "en privé" in line and "en public" in line and "compte" in line
    assert "<table" not in _between(page, 'class="ids-means"', "</section>")


def test_a_claim_waits_with_its_actions_on_its_line(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    assert "Aucune revendication en attente" in drawn(client, "/inspecteur/identites/revendications")
    claim(client, live)
    page = drawn(client, "/inspecteur/identites/revendications")
    entry = _between(page, 'class="ids-claim"', "</li>")
    assert "se présente comme" in entry and "« Adrien »" in entry and "vise" in entry
    assert 'class="ids-toward' in entry and "0,45 / 0,70" in entry  # vers la barre
    actions = _between(entry, 'class="ids-do"', "</div>")
    assert 'href="/inspecteur/fiche/handle/ext_9?onglet=revendication">Examiner et décider' in actions
    links = {html.unescape(a.split(">", 1)[1].split("<", 1)[0]): html.unescape(a.split('"', 1)[0])
             for a in actions.split('href="')[1:]}
    for label, key in (("S'en porter garant", "identity.preuve"), ("La démentir", "identity.preuve"),
                       ("Relier à une personne", "identity.relier")):
        # les actions de la fiche, sur leur page, ramènent à la file
        got = parse_qs(urlsplit(links[label]).query)
        assert urlsplit(links[label]).path == f"/inspecteur/action/{key}"
        assert got["sujet"] == ["ext_9"] and got["retour"] == ["/inspecteur/identites/revendications"]
    # chacune arrive orientée : la preuve choisie par l'adresse, le nom démenti et la personne visée par la faculté
    vouch = html.unescape(client.get(links["S'en porter garant"]).text)
    assert '<option value="vouched" selected' in vouch
    deny = html.unescape(client.get(links["La démentir"]).text)
    assert '<option value="denied" selected' in deny and 'value="Adrien"' in deny
    link = html.unescape(client.get(links["Relier à une personne"]).text)
    assert '<option value="user_1" selected' in link
    assert "Une affirmation seule ne franchit jamais la barre" in page  # la règle de la faculté, au pied


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


def test_a_name_waits_for_someone_with_both_answers_on_its_line(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    assert "Aucun nom n'attend" in drawn(client, "/inspecteur/identites/noms")
    emit(client, live, "memory", [memory_c.BELIEVED.draft(
        text=Content.of("Léa, la sœur d'Adrien, prépare un concours."), about=("name:lea",), sensitivity=1,
        source="user_1", told_by=("user_1",))])
    stranger(client, live, "ext_7", "Léa Martin")
    page = drawn(client, "/inspecteur/identites/noms")
    entry = _between(page, 'class="ids-claim ids-name', "</li>")
    assert "« Lea »" in entry and "Léa Martin" in entry and "on lui en a parlé" in entry
    actions = _between(entry, 'class="ids-do"', "</li>")
    assert "C'est elle : relier" in actions and "onglet=synthese" in actions  # la fiche, le formulaire pré-rempli
    assert "/inspecteur/action/identity.ecarter_nom" in actions and "Ce n'est pas elle" in actions  # son bouton
    assert "1 nom dont on lui a parlé" in page


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
