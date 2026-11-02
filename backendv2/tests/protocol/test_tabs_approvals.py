"""À valider › Historique des autorisations dans sa forme (``app/handmade/tabs/approvals.py``, ADR 0177), à travers le
vrai serveur : une entrée par demande — ce qu'elle voulait faire (relu au journal), puis ta décision et son exécution,
dans l'ordre où elles sont arrivées ; une demande refusée et une exécution ratée se voient ; et ce que la page dit,
vide."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.kernel.events import Content
from tests.protocol.test_console_diagnostics import stop
from tests.protocol.test_console_workflows import append
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_tabs_identities import claim
from tests.protocol.test_tabs_people import emit, stranger
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def _reader(page: str) -> str:
    return page.split('class="now-card hm-approval apv-reader', 1)[1].split("</article>", 1)[0]


def _entry(page: str, text: str) -> str:
    return page.split(text, 1)[0].rsplit('<li class="hist-item', 1)[1] + page.split(text, 1)[1].split("</ol>", 1)[0]


def test_each_request_reads_with_its_decision_then_its_execution(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    stop(client, live.kernel)
    kernel = live.kernel
    empty = drawn(client, "/inspecteur/approbations/historique")
    assert 'data-tab="approbations/historique"' in empty and "Rien n'a encore été décidé." in empty
    asked = append(client, kernel, [
        rt.EFFECT_PROPOSED.draft(capability="demo.envoyer", owner="email", args_json="{}",
                                 summary=Content.of("Répondre à Léa au sujet des maquettes")),
        rt.EFFECT_PROPOSED.draft(capability="demo.installer", owner="projects", args_json="{}",
                                 summary=Content.of("Installer les dépendances du projet"))]).seqs
    append(client, kernel, [
        rt.EFFECT_RESOLVED.draft(proposal=asked[0], approved=True, by="user_1", capability="demo.envoyer",
                                 owner="email", note=Content.of("Vas-y.")),
        rt.EFFECT_RESOLVED.draft(proposal=asked[1], approved=False, by="user_1", capability="demo.installer",
                                 owner="projects")])
    append(client, kernel, [rt.EFFECT_EXECUTED.draft(proposal=asked[0], ok=False, result="serveur injoignable")])
    page = drawn(client, "/inspecteur/approbations/historique")
    sent = _entry(page, "Répondre à Léa au sujet des maquettes")
    assert "m-danger" in sent and f"/inspecteur/evenement/{asked[0]}" in sent
    assert sent.index(">approuvé<") < sent.index("Vas-y.") < sent.index(">en échec<") < sent.index("serveur injoignable")
    refused = _entry(page, "Installer les dépendances du projet")
    assert "m-refused" in refused and ">refusé<" in refused and "exécut" not in refused
    assert page.index("Répondre à Léa") < page.index("Installer les dépendances")  # la plus récente d'abord


def test_everything_to_decide_is_one_queue_with_one_tab_bar(world):  # noqa: F811
    """« À valider » est une seule file (ADR 0177) : une barre d'onglets (tout, les courriers, Teams, les identités,
    les noms, l'historique) ; une identité à confirmer y entre comme une demande, avec ses faits, sa source et ses
    actions, qui ramènent à la file ; un courrier à envoyer a son onglet."""
    client, live, _ = world
    bootstrap(client)
    claim(client, live)
    append(client, live.kernel, [rt.EFFECT_PROPOSED.draft(capability="email.send", owner="email",
        args_json='{"draft": "d-1", "account": "perso"}', summary=Content.of("Répondre au libraire"),
        context="user_1")])
    everything = drawn(client, "/inspecteur/approbations")
    bar = everything.split('<nav class="tabs"', 1)[1].split("</nav>", 1)[0]
    titles = re.findall(r'class="tab[^"]*" href="/inspecteur/approbations/(\w+)"', bar)
    assert titles == ["en_attente", "courriers", "teams", "identites", "noms", "historique"]
    rows = everything.split('class="apv-list"', 1)[1].split("</ol>", 1)[0]
    assert "Identité à confirmer" in rows and "Répondre au libraire" in rows
    mails = drawn(client, "/inspecteur/approbations/courriers")
    assert "Répondre au libraire" in mails and "Identité à confirmer" not in mails
    page = drawn(client, "/inspecteur/approbations/identites")
    reader = page.split('class="now-card hm-approval apv-reader', 1)[1].split("</article>", 1)[0]
    assert "se présente comme « Adrien »" in reader and "Ta décision est attendue" in reader
    assert "<dt>vise</dt>" in reader and "Le moyen de communication" in reader
    links = re.findall(r'class="btn[^"]*" href="([^"]+)">([^<]+)<', reader)
    assert [t for _, t in links] == ["S'en porter garant", "La démentir", "Relier à une personne"]
    for href, _ in links:  # chacune ramène à la file, pas à l'onglet d'Identités
        assert "retour=%2Finspecteur%2Fapprobations%2Fidentites" in href
    # l'accueil compte chaque chose une fois : la file par son total, pas ses onglets ni les vues qui la répètent
    home = drawn(client, "/inspecteur/")
    assert "À valider › Tout ce qui attend" in home
    assert "À valider › Courriers à envoyer" not in home and "Identités › Identités à confirmer" not in home


def test_a_claim_is_decided_in_the_queue_its_actions_already_oriented(world):  # noqa: F811
    """Une identité à confirmer ne se décide que dans la file (ADR 0180) : où elle en est vers la barre, puis les
    actions de la fiche du moyen de communication, sur leur page et déjà orientées — la preuve choisie par l'adresse,
    le nom démenti et la personne visée posés par la faculté ; la règle de la faculté au pied."""
    client, live, _ = world
    bootstrap(client)
    claim(client, live)
    reader = _reader(drawn(client, "/inspecteur/approbations/identites"))
    assert "0,45 / 0,70" in reader  # vers la barre
    links = {t: h for h, t in re.findall(r'class="btn[^"]*" href="([^"]+)">([^<]+)<', reader)}
    for label, key in (("S'en porter garant", "identity.preuve"), ("La démentir", "identity.preuve"),
                       ("Relier à une personne", "identity.relier")):
        assert urlsplit(links[label]).path == f"/inspecteur/action/{key}"
        assert parse_qs(urlsplit(links[label]).query)["sujet"] == ["ext_9"]
    assert '<option value="vouched" selected' in drawn(client, links["S'en porter garant"])
    deny = drawn(client, links["La démentir"])
    assert '<option value="denied" selected' in deny and 'value="Adrien"' in deny
    assert '<option value="user_1" selected' in drawn(client, links["Relier à une personne"])
    assert "Une affirmation seule ne franchit jamais la barre" in reader


def test_a_name_is_decided_in_the_queue_with_both_answers(world):  # noqa: F811
    """Un nom à relier ne se décide que dans la file (ADR 0180) : qui lui en a parlé, la personne qui le porte, et
    ses deux réponses — « C'est elle » (la fiche, le formulaire pré-rempli) et « Ce n'est pas elle » (le bouton de la
    faculté)."""
    client, live, _ = world
    bootstrap(client)
    assert "Aucun nom dont on lui a parlé n'attend quelqu'un." in drawn(client, "/inspecteur/approbations/noms")
    emit(client, live, "memory", [memory_c.BELIEVED.draft(
        text=Content.of("Léa, la sœur d'Adrien, prépare un concours."), about=("name:lea",), sensitivity=1,
        source="user_1", told_by=("user_1",))])
    stranger(client, live, "ext_7", "Léa Martin")
    reader = _reader(drawn(client, "/inspecteur/approbations/noms"))
    assert "On lui a parlé de « Lea »" in reader and "porté par Léa Martin" in reader
    assert "<dt>qui lui en a parlé</dt>" in reader
    actions = reader.split('class="apv-do"', 1)[1]
    assert "C'est elle : relier" in actions and "onglet=synthese" in actions
    assert "/inspecteur/action/identity.ecarter_nom" in actions and "Ce n'est pas elle" in actions
