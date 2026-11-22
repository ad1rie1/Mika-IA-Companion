"""À valider › Historique des autorisations dans sa forme (``app/handmade/tabs/approvals.py``, ADR 0177), à travers le
vrai serveur : une entrée par demande — ce qu'elle voulait faire (relu au journal), puis ta décision et son exécution,
dans l'ordre où elles sont arrivées ; une demande refusée et une exécution ratée se voient ; et ce que la page dit,
vide."""

from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, urlsplit

from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.kernel.events import Content
from mika.runtime.inspection import Inspection
from mika.runtime.operations import FIXED_FIELD, perform
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
    empty = drawn(client, "/admin/approbations/historique")
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
    page = drawn(client, "/admin/approbations/historique")
    sent = _entry(page, "Répondre à Léa au sujet des maquettes")
    assert "m-danger" in sent and f"/admin/evenement/{asked[0]}" in sent
    assert sent.index(">approuvé<") < sent.index("Vas-y.") < sent.index(">en échec<") < sent.index("serveur injoignable")
    refused = _entry(page, "Installer les dépendances du projet")
    assert "m-refused" in refused and ">refusé<" in refused and "exécut" not in refused
    assert page.index("Répondre à Léa") < page.index("Installer les dépendances")  # la plus récente d'abord


def test_everything_to_decide_is_one_queue_with_one_tab_bar(world):  # noqa: F811
    """« À valider » est une seule file (ADR 0177) : une barre d'onglets (tout, les courriers, Teams, les identités,
    les rapprochements — les noms à relier en sont, ADR 0298 —, l'historique) ; une identité à confirmer y entre comme une demande, avec ses faits, sa source et ses
    actions, qui ramènent à la file ; un courrier à envoyer a son onglet."""
    client, live, _ = world
    bootstrap(client)
    claim(client, live)
    append(client, live.kernel, [rt.EFFECT_PROPOSED.draft(capability="email.send", owner="email",
        args_json='{"draft": "d-1", "account": "perso"}', summary=Content.of("Répondre au libraire"),
        context="user_1")])
    everything = drawn(client, "/admin/approbations")
    bar = everything.split('<nav class="tabs"', 1)[1].split("</nav>", 1)[0]
    titles = re.findall(r'class="tab[^"]*" href="/admin/approbations/(\w+)"', bar)
    assert titles == ["en_attente", "courriers", "teams", "identites", "rapprochements", "historique"]
    rows = everything.split('class="apv-list"', 1)[1].split("</ol>", 1)[0]
    assert "Identité à confirmer" in rows and "Répondre au libraire" in rows
    mails = drawn(client, "/admin/approbations/courriers")
    assert "Répondre au libraire" in mails and "Identité à confirmer" not in mails
    page = drawn(client, "/admin/approbations/identites")
    reader = page.split('class="now-card hm-approval apv-reader', 1)[1].split("</article>", 1)[0]
    assert "se présente comme « Adrien »" in reader and "Ta décision est attendue" in reader
    assert "<dt>vise</dt>" in reader and "Le moyen de communication" in reader
    links = re.findall(r'class="btn[^"]*" href="([^"]+)">([^<]+)<', reader)
    assert [t for _, t in links] == ["S'en porter garant", "La démentir", "Relier à une personne"]
    for href, _ in links:  # chacune ramène à la file, pas à l'onglet d'Identités
        assert "retour=%2Fadmin%2Fapprobations%2Fidentites" in href
    # l'accueil compte chaque chose une fois : la file par son total, pas ses onglets ni les vues qui la répètent
    home = drawn(client, "/admin/")
    assert "À valider › Tout ce qui attend" in home
    assert "À valider › Courriers à envoyer" not in home and "Identités › Identités à confirmer" not in home


def test_each_sort_reads_by_its_short_name_its_sentence_stays_at_hand(world):  # noqa: F811
    """Dans la file, ses puces et l'historique, une sorte se lit en nom court, sans rien de coupé ; sa phrase entière
    reste au survol de la file, et dans l'en-tête de la demande ouverte ; l'historique garde sa clé au survol."""
    client, live, _ = world
    bootstrap(client)
    stop(client, live.kernel)
    kernel = live.kernel
    sentence = "Lancer une commande avec le réseau dans l'atelier d'un projet."
    asked = append(client, kernel, [
        rt.EFFECT_PROPOSED.draft(capability="projects.networked", owner="projects", args_json="{}",
                                 summary=Content.of("Installer les dépendances")),
        rt.EFFECT_PROPOSED.draft(capability="projects.push", owner="projects", args_json="{}",
                                 summary=Content.of("Pousser la branche"))]).seqs
    page = drawn(client, "/admin/approbations")
    queue = page.split('class="apv-list"', 1)[1].split("</ol>", 1)[0]
    assert f'<span class="apv-kind" title="{sentence}">Commande réseau</span>' in queue
    assert ">Push git</span>" in queue
    chips = page.split('class="hm-chips apv-kinds"', 1)[1].split("</nav>", 1)[0]
    assert f'title="{sentence}"' in chips and "Commande réseau" in chips
    assert f'title="{sentence}">{sentence.rstrip(".")}</span>' in _reader(page)  # l'en-tête de la demande ouverte

    append(client, kernel, [rt.EFFECT_RESOLVED.draft(proposal=asked[0], approved=False, by="user_1",
                                                     capability="projects.networked", owner="projects")])
    entry = _entry(drawn(client, "/admin/approbations/historique"), "Installer les dépendances")
    assert 'title="projects.networked">Commande réseau</span>' in entry


def test_a_claim_is_decided_in_the_queue_its_actions_already_oriented(world):  # noqa: F811
    """Une identité à confirmer ne se décide que dans la file (ADR 0180) : où elle en est vers la barre, puis les
    actions de la fiche du moyen de communication, sur leur page et déjà orientées — la preuve choisie par l'adresse,
    le nom démenti et la personne visée posés par la faculté ; la règle de la faculté au pied."""
    client, live, _ = world
    bootstrap(client)
    claim(client, live)
    reader = _reader(drawn(client, "/admin/approbations/identites"))
    assert "0,45 / 0,70" in reader  # vers la barre
    links = {t: h for h, t in re.findall(r'class="btn[^"]*" href="([^"]+)">([^<]+)<', reader)}
    for label, key in (("S'en porter garant", "identity.preuve"), ("La démentir", "identity.preuve"),
                       ("Relier à une personne", "identity.relier")):
        assert urlsplit(links[label]).path == f"/admin/action/{key}"
        assert parse_qs(urlsplit(links[label]).query)["sujet"] == ["ext_9"]
    assert '<option value="vouched" selected' in drawn(client, links["S'en porter garant"])
    deny = drawn(client, links["La démentir"])
    assert '<option value="denied" selected' in deny and 'value="Adrien"' in deny
    assert '<option value="user_1" selected' in drawn(client, links["Relier à une personne"])
    assert "Une affirmation seule ne franchit jamais la barre" in reader


def test_a_name_is_decided_in_the_queue_with_both_answers(world):  # noqa: F811
    """Un nom à relier ne se décide que dans la file (ADR 0180), parmi les rapprochements (ADR 0298) : les deux fiches
    côte à côte — la personne dont on lui a parlé, celle qui lui parle —, qui lui en a parlé, et ses deux réponses :
    « La même personne : relier… » (la fiche, le formulaire pré-rempli de l'identité) et « Deux personnes
    différentes » (le bouton de la faculté)."""
    client, live, _ = world
    bootstrap(client)
    assert "Aucune fiche n'en rappelle une autre par son nom." in drawn(client, "/admin/approbations/rapprochements")
    emit(client, live, "memory", [memory_c.BELIEVED.draft(
        text=Content.of("Léa, la sœur d'Adrien, prépare un concours."), about=("name:lea",), sensitivity=1,
        source="user_1", told_by=("user_1",))])
    stranger(client, live, "ext_7", "Léa Martin")
    reader = _reader(drawn(client, "/admin/approbations/rapprochements"))
    assert "« Lea », dont on lui a parlé, et Léa Martin : la même personne ?" in html.unescape(reader)
    assert 'class="pair"' in reader and "porté par Léa Martin" in reader
    assert "<dt>qui lui en a parlé</dt>" in reader
    actions = reader.split('class="apv-do"', 1)[1]
    assert "La même personne : relier" in actions and "onglet=synthese" in actions
    assert "/admin/action/identity.ecarter_nom" in actions and "Deux personnes différentes" in actions
    # son badge accorde son nom à son nombre, jamais « nom(s) » (ADR 0219)
    names = Inspection(live.kernel).find("identity", "noms")
    assert client.portal.call(lambda: Inspection(live.kernel).badge(names)) == (
        1, "nom dont on lui a parlé que porte quelqu'un qu'elle connaît")
    emit(client, live, "memory", [memory_c.BELIEVED.draft(
        text=Content.of("Max, le voisin d'Adrien, joue du piano."), about=("name:max",), sensitivity=1,
        source="user_1", told_by=("user_1",))])
    stranger(client, live, "ext_8", "Max Dupont")
    assert client.portal.call(lambda: Inspection(live.kernel).badge(names)) == (
        2, "noms dont on lui a parlé que porte quelqu'un qu'elle connaît")


def _head(page: str) -> str:
    """La barre de titre d'une fiche : ses actions en vue et celles sous « ⋯ »."""
    return page.split('class="fiche-head-side"', 1)[1].split('class="tabs', 1)[0]


def test_naming_shows_in_the_title_bar_only_while_a_name_waits(world):  # noqa: F811
    """« C'est la personne dont on lui a parlé » n'est dans la barre de titre d'une fiche que si un nom dont on lui a
    parlé attend d'être relié (audit du 2026-11-05, C3-08) : sans lui, la barre garde « Fixer la proximité » ; avec
    lui, l'action revient, et la fiche ouverte depuis la file garde son formulaire pré-rempli."""
    client, live, _ = world
    bootstrap(client)
    alone = _head(drawn(client, "/admin/fiche/person/user_1"))
    assert "Fixer la proximité" in alone and "C'est la personne dont on lui a parlé" not in alone
    emit(client, live, "memory", [memory_c.BELIEVED.draft(
        text=Content.of("Léa, la sœur d'Adrien, prépare un concours."), about=("name:lea",), sensitivity=1,
        source="user_1", told_by=("user_1",))])
    stranger(client, live, "ext_7", "Léa Martin")
    assert "C'est la personne dont on lui a parlé" in _head(drawn(client, "/admin/fiche/person/user_1"))
    reader = _reader(drawn(client, "/admin/approbations/rapprochements"))
    href = re.search(r'href="([^"]+)">La même personne : relier', reader).group(1)
    assert parse_qs(urlsplit(href).query) == {"onglet": ["synthese"], "nom": ["name:lea"]}
    synthesis = drawn(client, href)
    body = synthesis.split('class="tabs', 1)[1]
    assert "« Lea », dont on lui a parlé" in body and 'action="/admin/action/identity.nommer' in body
    # relié, plus rien n'attend : l'action quitte les barres, et ce nom-ci, ouvert sur une autre fiche, dit comment
    # le libérer au lieu d'un formulaire qui ne serait plus offert
    done = client.portal.call(lambda: perform(live.kernel, "identity.nommer", {
        "_champs": ["name", "confirmed"], "name": ["Lea"], "confirmed": ["on"], FIXED_FIELD: ["key"],
        "key": ["name:lea"]}, by="user_1", subject=urlsplit(href).path.rsplit("/", 1)[1], nonce="lea"))
    assert done.ok, done
    elsewhere = drawn(client, "/admin/fiche/person/user_1?onglet=synthese&nom=name%3Alea")
    assert "C'est la personne dont on lui a parlé" not in _head(elsewhere)
    body = elsewhere.split('class="tabs', 1)[1]
    assert "« Détacher un nom », sur sa fiche, le libère" in body and "identity.nommer" not in body


def test_a_name_her_memory_keeps_nothing_active_of_no_longer_waits(world):  # noqa: F811
    """Un nom dont sa mémoire ne garde plus rien d'actif (ici, un moment de sa vie fini) n'attend plus d'être relié,
    comme la file le compte (``free_names``) : la fiche du nom ne mène plus au formulaire « à décider », et la
    Synthèse ouverte avec ce nom le dit, au lieu d'un titre de section sans formulaire — qu'un autre nom attende
    (l'action est alors offerte) ou non."""
    client, live, _ = world
    bootstrap(client)
    now = client.portal.call(live.kernel.mind.clock.now)
    move = append(client, live.kernel, [memory_c.EVENT_NOTED.draft(
        text=Content.of("Max, le voisin d'Adrien, déménage."), when=now, about=("name:max",), ongoing=True)],
        "memory").seqs[0]
    append(client, live.kernel, [memory_c.SITUATION_ENDED.draft(event=move)], "memory")
    stranger(client, live, "ext_8", "Max Dupont")
    sheet = drawn(client, "/admin/fiche/person/name%3Amax").split('class="tabs', 1)[1]
    assert "Qui porte ce nom" in sheet and "Max Dupont" in sheet and "rien à relier" in sheet
    assert "à décider" not in sheet and "nom=name" not in sheet
    opened = "/admin/fiche/person/ext_8?onglet=synthese&nom=name%3Amax"

    def says_nothing_waits(page: str) -> None:
        body = page.split('class="tabs', 1)[1]
        assert "« Max », dont on lui a parlé" not in body and "Rien n'est relié tant que" not in body
        assert "« Max » n'attend plus d'être relié : sa mémoire n'en garde plus rien d'actif." in body

    alone = drawn(client, opened)
    assert "C'est la personne dont on lui a parlé" not in _head(alone)
    says_nothing_waits(alone)
    # un autre nom attend : l'action revient dans la barre, ce nom-ci n'a toujours rien à relier
    emit(client, live, "memory", [memory_c.BELIEVED.draft(
        text=Content.of("Léa, la sœur d'Adrien, prépare un concours."), about=("name:lea",), sensitivity=1,
        source="user_1", told_by=("user_1",))])
    other = drawn(client, opened)
    assert "C'est la personne dont on lui a parlé" in _head(other)
    says_nothing_waits(other)
