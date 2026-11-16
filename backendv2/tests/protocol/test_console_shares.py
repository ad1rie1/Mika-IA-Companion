"""Réglages › Droits › Partages (ADR 0210, C9-04 de l'audit du 2026-11-05), par le vrai serveur : l'opératrice voit qui a
reçu quoi, de qui, en mots ; elle retire le partage d'une boîte ou d'un compte Teams, confirmé et audité, par l'écriture
de son propriétaire, et la personne ne le voit plus dans son espace ; un service renvoie à ses lignes d'accès ; rien ne
s'y crée. Le même geste est sur la fiche d'une personne (Comptes › Partages, C3-06), qui y revient — jamais hors de la
console."""

from __future__ import annotations

import re

from mika.adapters.mail.config import MailAccount, MailConfig
from mika.adapters.teams import TeamsAccount, TeamsConfig
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from tests.fixtures.courrier import mailbox
from tests.protocol.test_console_mcp import html_of
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_moi_mail import API, PROJET, journal, login, post, second_person
from tests.protocol.test_moi_mcp import SERVICE, servers
from tests.protocol.test_moi_shares import share
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

PAGE = "/inspecteur/reglages/droits"
FICHE = "/inspecteur/fiche/person"
RETIRE = PAGE + "/partages"
GESTURE = "console.droits.partage_retire"
GESTURES = "/inspecteur/systeme/operations"
#: la sorte d'un partage audité
AUDITED = "ressource_partagee"


def forms_on(page: str) -> list[tuple[str, dict[str, str]]]:
    """Les « Retirer » que la page dessine : leur confirmation, et ce que le navigateur enverrait."""
    found = re.findall(rf'<form[^>]+action="{RETIRE}"[^>]*data-confirm="([^"]*)"[^>]*>(.*?)</form>', page, re.S)
    return [(ask, dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', body))) for ask, body in found]


def shared_world(client, live) -> str:
    """Une boîte, un compte Teams et un service d'Adrien, chacun partagé à Léa : rend la clé de sa personne."""
    bootstrap(client)
    live.kernel.ports["mail"] = mailbox(3)
    client.portal.call(live.settings.save_email, MailConfig(accounts={
        "pro": MailAccount(label="Atelier", address="atelier@example.test")}))
    client.portal.call(live.settings.save_teams, TeamsConfig(accounts={"travail": TeamsAccount(label="Travail")}))
    lea = second_person(client, live)
    assert post(client, "/mcp/plug", SERVICE).status_code == 200
    assert share(client, "mail", "pro", lea, "lire").status_code == 200
    assert share(client, "teams", "travail", lea, "preparer").status_code == 200
    assert share(client, "mcp", "factures", lea, "servir").status_code == 200
    return lea


def partages(client, person: str) -> str:
    """Comptes › Partages, sur la fiche de cette personne (le sous-onglet ``#partages`` de l'onglet ``boites``)."""
    page = drawn(client, f"{FICHE}/{person}?onglet=boites")
    return page.partition('id="partages"')[2]


def audited(live) -> list[tuple[str, str, str]]:
    return [(e.data.by, e.data.subject_kind, e.data.subject) for e in journal(live, rt.OPERATED)
            if e.data.action == GESTURE]


def test_without_a_share_the_tab_says_so(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    page = html_of(client.get(PAGE))
    assert 'href="#d-partages"' in page and "Aucun partage pour l'instant." in page and not forms_on(page)


def test_an_operator_reads_every_share_and_takes_one_off(world):  # noqa: F811
    client, live, _ = world
    lea = shared_world(client, live)
    page = html_of(client.get(PAGE))
    pane = page.partition('id="d-partages"')[2].partition('id="d-code"')[0]
    rows = re.findall(r"<tr>\s*<th scope=\"row\">(.*?)</tr>", pane, re.S)
    assert len(rows) == 3
    said = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.partition("<form")[0])).strip() for r in rows]
    assert said == ["Atelier boîte toi Léa Martin Lire", "Travail compte Teams toi Léa Martin Lire et préparer",
                    "factures service adrien Léa Martin S'en servir ses lignes d'accès"]
    assert "personne:" not in pane  # jamais la clé brute
    assert f'href="/inspecteur/fiche/person/{lea}"' in pane  # qui le reçoit mène à sa fiche
    assert 'href="/inspecteur/fiche/serveur/factures?onglet=fait"' in rows[2]  # un service : ses lignes d'accès
    forms = forms_on(page)
    assert [(f["kind"], f["key"], f["person"]) for _, f in forms] == [("mail", "pro", lea), ("teams", "travail", lea)]
    assert "Léa Martin" in forms[0][0] and "la boîte « Atelier »" in forms[0][0]
    assert "le compte Teams « Travail »" in forms[1][0]
    assert not re.search(r'name="level"|<select', pane)  # on n'y donne rien
    # Paramètres › Partages les lit à la même source, dans le même ordre : par sorte, ressource et personne
    mine = client.get(API + "/shares").json()
    assert [(g["kind"], g["key"], g["person"]) for g in mine["given"]] == \
        [("mail", "pro", lea), ("teams", "travail", lea), ("mcp", "factures", lea)] and mine["received"] == []

    login(client, "lea")
    received = client.get(API + "/shares").json()["received"]
    assert [(r["kind"], r["key"]) for r in received] == [("mail", "pro"), ("teams", "travail"), ("mcp", "factures")]
    assert client.get(API + "/shares").json()["given"] == []
    assert [b["key"] for b in client.get(API + "/mail/boxes").json()["boxes"]] == ["pro"]
    assert client.get(API + f"/mail/message?ref={PROJET}").status_code == 200
    login(client, "adrien")

    done = client.post(RETIRE, data=forms[0][1], follow_redirects=False)
    assert done.status_code == 303 and done.headers["location"].endswith("#d-partages")
    after = html_of(client.get(done.headers["location"]))
    assert "Partage retiré : Léa Martin n'a plus accès à la boîte « Atelier »." in after
    assert [f["kind"] for _, f in forms_on(after)] == ["teams"]
    assert client.portal.call(live.settings.email).accounts["pro"].shares == {}
    assert audited(live) == [("user_1", AUDITED, f"mail:pro:{lea}")]

    login(client, "lea")
    assert client.get(API + "/mail/boxes").json()["boxes"] == []  # elle ne la voit plus
    assert client.get(API + f"/mail/message?ref={PROJET}").status_code != 200
    assert [r["kind"] for r in client.get(API + "/shares").json()["received"]] == ["teams", "mcp"]

    login(client, "adrien")  # le compte Teams, de même
    assert client.post(RETIRE, data=forms[1][1], follow_redirects=False).status_code == 303
    assert client.portal.call(live.settings.teams).accounts["travail"].shares == {}
    login(client, "lea")
    assert client.get(API + "/teams/accounts").json()["accounts"] == []
    assert [r["kind"] for r in client.get(API + "/shares").json()["received"]] == ["mcp"]


def test_the_console_only_takes_off_what_is_there_and_gives_nothing(world):  # noqa: F811
    client, live, _ = world
    lea = shared_world(client, live)
    forms = forms_on(html_of(client.get(PAGE)))
    box = forms[0][1]

    def said(**data: str) -> str:
        done = client.post(RETIRE, data={**box, **data}, follow_redirects=False)
        assert done.status_code == 303
        return html_of(client.get(done.headers["location"]))

    # un service se retire sur ses lignes d'accès, où il reste
    assert "Un service se retire sur ses lignes d'accès" in said(kind="mcp", key="factures")
    assert [tuple(a.who) for a in servers(client, live)["factures"].access][1] == (f"personne:{lea}",)
    # ni une ressource inconnue, ni une personne qui n'a rien reçu : rien n'est écrit, rien n'est donné
    assert "n'est plus là" in said(key="inconnue")
    assert "n'est plus là" in said(person="user_1", level="servir")
    assert client.portal.call(live.settings.email).accounts["pro"].shares == {f"personne:{lea}": "lire"}
    # sans le jeton du formulaire : rien
    assert "Jeton de formulaire invalide" in said(csrf="faux")
    assert client.portal.call(live.settings.email).accounts["pro"].shares == {f"personne:{lea}": "lire"}
    assert audited(live) == []
    # deux onglets : le second ne retire rien et n'audite rien de plus
    assert "Partage retiré" in said()
    assert "n'est plus là" in said()
    assert audited(live) == [("user_1", AUDITED, f"mail:pro:{lea}")]


def test_a_share_is_audited_as_a_share_never_as_a_mail(world):  # noqa: F811
    """« mail » est un sujet de la console : ses fiches sont des messages. Audités sous ce nom, le retrait d'une boîte et
    son partage par son propriétaire menaient, dans Gestes audités, à un « Mail pro:… » qui répond 404 (relecture du lot
    L03b). L'audit porte sur le partage même, sa ressource et sa personne, sous une sorte qui n'est pas un sujet (ni
    « partage » : c'est celui d'un fichier envoyé) : sa ligne reste du texte."""
    client, live, _ = world
    lea = shared_world(client, live)
    box = forms_on(html_of(client.get(PAGE)))[0][1]
    assert client.post(RETIRE, data=box, follow_redirects=False).status_code == 303

    given = [(e.data.subject_kind, e.data.subject) for e in journal(live, rt.OPERATED) if e.data.action == "moi.partage"]
    assert given == [(AUDITED, f"mail:pro:{lea}"), (AUDITED, f"teams:travail:{lea}"), (AUDITED, f"mcp:factures:{lea}")]
    assert audited(live) == [("user_1", AUDITED, f"mail:pro:{lea}")]
    assert AUDITED not in live.kernel.registry.subjects
    page = drawn(client, GESTURES)
    feed = page[page.index('class="sys-ops-feed"'):]
    assert "Partage retiré" in feed and "Partage modifié" in feed and f'title="{AUDITED}">mail:pro:{lea}</span>' in feed
    assert "/inspecteur/fiche/mail/" not in feed and "Mail pro" not in feed


def test_only_an_operator_takes_a_share_off(world):  # noqa: F811
    client, live, _ = world
    lea = shared_world(client, live)
    box = forms_on(html_of(client.get(PAGE)))[0][1]
    login(client, "lea")  # elle a reçu le partage, pas la console
    done = client.post(RETIRE, data=box, follow_redirects=False)
    assert done.status_code == 303 and done.headers["location"].endswith("/inspecteur/connexion")
    assert client.portal.call(live.settings.email).accounts["pro"].shares == {f"personne:{lea}": "lire"}
    assert audited(live) == []


def test_the_fiche_of_a_person_takes_a_share_off_and_comes_back(world):  # noqa: F811
    """C3-06 : depuis la fiche, « Retirer » est le geste de Droits — la même question, le même audit, la même écriture —
    et revient sur Comptes › Partages, le message en tête ; un service mène à ses lignes d'accès."""
    client, live, _ = world
    lea = shared_world(client, live)
    pane = partages(client, lea)
    # ce qu'on partage avec Léa : la boîte et le compte Teams se retirent ici, le service sur ses lignes d'accès
    forms = forms_on(pane)
    assert [(f["kind"], f["key"], f["person"]) for _, f in forms] == [("mail", "pro", lea), ("teams", "travail", lea)]
    assert [ask for ask, _ in forms] == [ask for ask, _ in forms_on(html_of(client.get(PAGE)))]  # la même question
    assert {f["retour"] for _, f in forms} == {f"{FICHE}/{lea}?onglet=boites#partages"}
    assert forms[0][1]["csrf"] == client.cookies.get("csrftoken")  # le jeton de la page
    assert 'href="/inspecteur/fiche/serveur/factures?onglet=fait">ses lignes d\'accès</a>' in pane
    assert not re.search(r'name="level"|<select', pane)  # on n'y donne rien
    # ce qu'Adrien partage : les mêmes, sur sa fiche à lui, qui y revient
    adrien = str(live.kernel.mind.frame().get(identity_c.PERSON("user_1")) or "user_1")
    given = forms_on(partages(client, adrien))
    assert [(f["kind"], f["person"], f["retour"]) for _, f in given] == \
        [("mail", lea, f"{FICHE}/{adrien}?onglet=boites#partages"), ("teams", lea, f"{FICHE}/{adrien}?onglet=boites#partages")]

    done = client.post(RETIRE, data=forms[0][1], follow_redirects=False)
    assert done.status_code == 303
    back = done.headers["location"]
    assert back.startswith(f"{FICHE}/{lea}?onglet=boites&flash=") and back.endswith("#partages")
    after = html_of(client.get(back))
    assert "Partage retiré : Léa Martin n'a plus accès à la boîte « Atelier »." in after
    assert [f["kind"] for _, f in forms_on(after)] == ["teams"]
    assert client.portal.call(live.settings.email).accounts["pro"].shares == {}
    assert audited(live) == [("user_1", AUDITED, f"mail:pro:{lea}")]


def test_the_way_back_stays_in_the_console(world):  # noqa: F811
    """Un ``retour`` qui sort de la console ramène à Droits ; un jeton refusé ne retire rien et revient sur la fiche,
    qui le dit."""
    client, live, _ = world
    lea = shared_world(client, live)
    box = forms_on(partages(client, lea))[0][1]
    for away in ("https://exemple.test/inspecteur/", "//exemple.test/inspecteur/", "/inspecteur//exemple.test",
                 "/ailleurs", "javascript:alert(1)"):
        done = client.post(RETIRE, data={**box, "retour": away, "person": "user_1"}, follow_redirects=False)
        assert done.status_code == 303
        assert done.headers["location"].startswith(PAGE + "?flash=") and done.headers["location"].endswith("#d-partages")
    refused = client.post(RETIRE, data={**box, "csrf": "faux"}, follow_redirects=False)
    assert refused.headers["location"].startswith(f"{FICHE}/{lea}?onglet=boites&flash=")
    assert "Jeton de formulaire invalide" in html_of(client.get(refused.headers["location"]))
    assert client.portal.call(live.settings.email).accounts["pro"].shares == {f"personne:{lea}": "lire"}
    assert audited(live) == []
