"""Réglages › Comptes et la fiche d'une personne, à travers le vrai serveur (audit du 2026-11-05, lot L06).

- la page s'appelle « Comptes », pas « Comptes opérateurs » ; la page d'un compte est la vue d'un objet : le fil
  « Réglages / Comptes / son nom », son nom affiché avec ses étiquettes, jamais l'identifiant interne (C9-07, C7-12,
  C1-04) ;
- la console crée un jeton d'application pour un compte : donné par la console, montré une seule fois à qui l'a créé,
  audité ; il ne tombe pas avec le mot de passe (C9-05) ;
- elle compte les sessions web d'un compte, dit sa dernière connexion, et les ferme d'un geste sans toucher à ses
  applications (C9-06) ;
- le compte mène à sa fiche, à ses comptes et à ses droits exacts ; la fiche mène au compte, et son onglet Comptes
  dit ses services et ses partages (C7-08, C9-02).
"""

from __future__ import annotations

import html
import json
import re
from urllib.parse import parse_qs, urlsplit

from mika.contracts import runtime as rt
from mika.plugins.email import EmailParams
from tests.fixtures.console_html import ConsoleHTML
from tests.fixtures.courrier import mailbox
from tests.protocol.test_moi_mail import login, second_person
from tests.protocol.test_moi_mail import post as moi_post
from tests.protocol.test_moi_mcp import SERVICE
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

ACCOUNTS = "/inspecteur/reglages/comptes"
#: un jeton de client natif, tel qu'il se montre (``TOKEN_PREFIX``)
RAW_TOKEN = re.compile(r"mw_[A-Za-z0-9_-]{20,}")


def page(client, url: str) -> str:
    got = client.get(url)
    assert got.status_code == 200, url
    ConsoleHTML(got.text).check()
    return html.unescape(got.text)


def text(markup: str) -> str:
    """Ce qu'on lit : sans balises (leurs attributs, ses liens et ses champs cachés, ne se lisent pas)."""
    return " ".join(re.sub(r"<[^>]+>", " ", markup).split())


def main(markup: str) -> str:
    """Le contenu de la page, sans le menu du haut (son libellé est à part, ``app/console_menu.py``)."""
    return markup.split('<main class="content"', 1)[1].split("</main>", 1)[0]


def crumbs(markup: str) -> list[str]:
    nav = re.search(r'<nav class="crumbs"[^>]*>(.*?)</nav>', markup, re.S)
    assert nav is not None
    return [c for c in (text(x) for x in re.split(r'<span aria-hidden="true">/</span>', nav.group(1))) if c]


def act(browser, follow: bool = False, **data: str):
    return browser.post(ACCOUNTS, data={"csrf": browser.cookies.get("csrftoken"), **data}, follow_redirects=follow)


def audited(live) -> list[str]:
    ops = live.kernel.mind.store.latest([rt.OPERATED.name], 50)
    return [json.loads(o.data)["action"] for o in ops]


def bea_account(client, live):
    return client.portal.call(lambda: live.accounts.create("bea", "un-mot-de-passe-long", operator=False,
                                                           full_name="Béa Martin"))


def test_the_accounts_page_says_comptes_and_an_account_is_an_object_view(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    bea = bea_account(client, live)
    listing = page(client, ACCOUNTS)
    assert crumbs(listing) == ["Réglages", "Comptes"] and "Comptes opérateurs" not in main(listing)
    shown = page(client, f"{ACCOUNTS}?compte={bea.id}")
    # le fil : la rubrique, la destination, le compte par son nom (avant : « Réglages / Comptes opérateurs /
    # Comptes / bea ») ; le titre : son nom et ses étiquettes, jamais « Modifier · » ni l'identifiant interne
    assert crumbs(shown) == ["Réglages", "Comptes", "Béa Martin"]
    title = shown.split('<div class="page-title-row">', 1)[1].split("</div>", 1)[0]
    assert "<h1>Béa Martin</h1>" in title and ">utilisateur<" in title and ">actif<" in title
    assert "Modifier ·" not in shown and bea.handle not in text(shown)
    assert "sans ouvrir la console" in text(shown.split('<div class="page-title">', 1)[1].split("</p>", 1)[0])
    adding = page(client, f"{ACCOUNTS}?nouveau=utilisateur")
    assert crumbs(adding) == ["Réglages", "Comptes", "Ajouter un utilisateur"]


def test_a_console_token_is_shown_once_audited_and_survives_a_new_password(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    bea = bea_account(client, live)
    forged = client.post(ACCOUNTS, data={"action": "create_token", "account": str(bea.id), "label": "Unity",
                                         "client": "screen"})
    assert "Jeton de formulaire invalide" in html.unescape(forged.text)
    unnamed = act(client, action="create_token", account=str(bea.id), label="  ", client="screen")
    assert unnamed.status_code == 400 and "Donne un nom au jeton" in html.unescape(unnamed.text)
    odd = act(client, action="create_token", account=str(bea.id), label="Unity", client="frigo")
    assert odd.status_code == 400 and "Choisis ce qu'il ouvre" in html.unescape(odd.text)
    assert client.portal.call(live.accounts.tokens, bea.id) == []
    made = act(client, action="create_token", account=str(bea.id), label="Unity du salon", client="screen")
    assert made.status_code == 303
    where = made.headers["location"]
    assert parse_qs(urlsplit(where).query)["montrer"] and "mw_" not in where  # jamais le secret dans l'adresse
    first = page(client, where)
    raw = RAW_TOKEN.findall(first)
    assert len(raw) == 1 and "Montré une seule fois" in first and "Jeton créé" in first
    assert RAW_TOKEN.search(page(client, where)) is None  # une seule fois
    [token] = client.portal.call(live.accounts.tokens, bea.id)
    assert (token.label, token.client, token.source) == ("Unity du salon", "screen", "console")
    assert "obtenu par console" in text(first)
    found = client.portal.call(live.accounts.token, raw[0])
    assert found is not None and found[0].id == bea.id and found[1] == token.id
    assert "console.comptes.jeton" in client.portal.call(audited, live)
    # donné par un opérateur, il ne suit pas le mot de passe
    client.portal.call(lambda: live.accounts.update(bea.id, password="un-autre-mot-de-passe"))
    assert client.portal.call(live.accounts.token, raw[0]) is not None
    # un compte désactivé n'en reçoit pas
    client.portal.call(lambda: live.accounts.update(bea.id, active=False))
    off = act(client, action="create_token", account=str(bea.id), label="Encore", client="mobile")
    assert off.status_code == 400 and "désactivé" in html.unescape(off.text)
    assert len(client.portal.call(live.accounts.tokens, bea.id)) == 1


def test_web_sessions_are_counted_and_closed_without_touching_its_apps(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    bea = bea_account(client, live)
    keys = [client.portal.call(live.accounts.open_session, bea) for _ in range(2)]
    _info, raw = client.portal.call(lambda: live.accounts.create_token(bea.id, "Pixel", client="mobile",
                                                                       source="login"))
    assert len(client.portal.call(live.accounts.sessions, bea.id)) == 2
    shown = text(page(client, f"{ACCOUNTS}?compte={bea.id}"))
    assert "Connexions web" in shown and "2 sessions ouvertes" in shown and "Fermer ses sessions" in shown
    # la liste dit la dernière connexion de chaque compte
    seen = client.portal.call(live.accounts.last_seen)
    assert set(seen) == {1, bea.id}
    table = page(client, f"{ACCOUNTS}?vue_pg1=table")
    assert "dernière connexion" in table
    assert "dernière connexion" in text(page(client, ACCOUNTS))
    closed = act(client, action="close_sessions", account=str(bea.id), follow=True)
    assert "2 sessions web fermées" in html.unescape(closed.text)
    assert client.portal.call(live.accounts.sessions, bea.id) == []
    assert all(client.portal.call(live.accounts.session, k) is None for k in keys)
    assert client.portal.call(live.accounts.token, raw) is not None  # ses applications restent
    assert client.portal.call(audited, live).count("console.comptes.sessions") == 1
    again = act(client, action="close_sessions", account=str(bea.id), follow=True)
    assert "Aucune session web n'était ouverte" in html.unescape(again.text)
    assert client.portal.call(audited, live).count("console.comptes.sessions") == 1  # rien fermé : rien à auditer
    assert client.get(ACCOUNTS).status_code == 200  # la session de l'opératrice, elle, vaut toujours
    unknown = act(client, action="close_sessions", account="99")
    assert unknown.status_code == 400 and "n'existe pas" in html.unescape(unknown.text)


def test_an_account_leads_to_her_fiche_her_accounts_and_her_exact_rights(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    bea = bea_account(client, live)
    shown = page(client, f"{ACCOUNTS}?compte={bea.id}")
    facts = shown.split('<div class="head-facts">', 1)[1].split("</div>", 1)[0]
    assert f'href="/inspecteur/fiche/person/{bea.handle}"' in facts
    rights = f"/inspecteur/reglages/droits?qui=p%3A{bea.handle}&amp;canal=web%3Aprive"
    assert html.unescape(rights) in facts and "ses droits exacts" in facts
    assert "onglet=boites" not in facts  # pas de boîte à elle : pas d'onglet Comptes sur sa fiche
    exact = page(client, html.unescape(rights))
    chosen = exact.split('class="rights-chosen">', 1)[1].split("</p>", 1)[0]
    assert "Béa" in chosen and "par <b>le chat web, en privé</b>" in chosen
    # une de ses propriétaires se lit « toi » dans Droits
    assert "/inspecteur/reglages/droits?qui=toi&canal=web%3Aprive" in page(client, f"{ACCOUNTS}?compte=1")
    # chaque ligne de la liste mène aussi à ses droits exacts
    assert "Ses droits exacts" in page(client, ACCOUNTS)
    # une boîte à elle : sa fiche a l'onglet Comptes, le compte y mène
    live.kernel.ports["mail"] = mailbox(1)
    client.portal.call(live.kernel.set_params, "email", EmailParams(owners={"perso": "", "pro": f"personne:{bea.handle}"}))
    facts = page(client, f"{ACCOUNTS}?compte={bea.id}").split('<div class="head-facts">', 1)[1].split("</div>", 1)[0]
    assert f"/inspecteur/fiche/person/{bea.handle}?onglet=boites" in facts


def test_a_persons_fiche_leads_to_her_account_and_lists_her_services_and_shares(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    lea = second_person(client, live)
    live.kernel.ports["mail"] = mailbox(1)
    # « Personnel » est à toi, partagée avec Léa (lire) ; « Atelier » est à Léa, partagée avec toi (lire et préparer)
    client.portal.call(live.kernel.set_params, "email", EmailParams(
        owners={"perso": "", "pro": f"personne:{lea}"},
        shares={"perso": {f"personne:{lea}": "lire"}, "pro": {"personne:user_1": "preparer"}}))
    login(client, "lea")
    assert moi_post(client, "/mcp/plug", SERVICE).status_code == 200
    login(client, "adrien")
    # l'en-tête de sa fiche dit son compte et mène à sa page
    head = page(client, f"/inspecteur/fiche/person/{lea}")
    head = head.split('class="person-head-links"', 1)[1].split("</p>", 1)[0]
    assert "compte utilisateur" in head and 'href="/inspecteur/reglages/comptes?compte=2">Modifier le compte<' in head
    assert "compte opérateur" in page(client, "/inspecteur/fiche/person/user_1")
    tab = page(client, f"/inspecteur/fiche/person/{lea}?onglet=boites")
    panes = re.findall(r'<section id="([a-z]+)" class="stack" data-pane', tab)
    assert panes == ["boites", "services", "partages"]
    services = text(tab.split('id="services"', 1)[1].split('id="partages"', 1)[0])
    assert "factures" in services and "Ses factures et ses devis" in services and "actif" in services
    assert 'href="/inspecteur/fiche/serveur/factures"' in tab
    shares = text(tab.split('id="partages"', 1)[1])
    given, received = shares.split("Ce qu'on partage avec", 1)
    assert "Atelier" in given and "lire et préparer" in given and "adrien" in given
    assert "Personnel" in received and "lire" in received and "partagé par adrien" in received
    # de l'autre côté, ta fiche : ton compte Teams (« principal », à toi) réuni sous Comptes, ce que tu partages avec
    # Léa, ce qu'elle partage avec toi
    yours = page(client, "/inspecteur/fiche/person/user_1?onglet=boites")
    assert re.findall(r'<section id="([a-z]+)" class="stack" data-pane', yours) == \
        ["boites", "teams", "services", "partages"]
    given, received = text(yours.split('id="partages"', 1)[1]).split("Ce qu'on partage avec", 1)
    assert "Personnel" in given and "Léa Martin" in given and "Atelier" in received and "Léa Martin" in received
    # l'ancienne adresse de Teams rouvre son sous-onglet
    moved = client.get("/inspecteur/fiche/person/user_1?onglet=teams", follow_redirects=False)
    assert moved.status_code == 303 and moved.headers["location"].endswith("#teams")
