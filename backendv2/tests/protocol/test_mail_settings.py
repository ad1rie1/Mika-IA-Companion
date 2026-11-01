"""Courrier › Paramètres (ADR 0173) : les réglages du courrier vivent dans le Courrier, derrière le bouton en haut à
droite — ses boîtes en cartes, une boîte sur sa page, et les paramètres généraux du courrier (relevé, ce qu'elle en
dit, ses brouillons). Ce qui s'y enregistre passe par les réglages et les paramètres, comme ailleurs ; un formulaire
refusé se remontre dans le Courrier, et l'ancienne adresse (Réglages › Plugins › Boîtes aux lettres) y mène."""

from __future__ import annotations

import html
import re
from types import SimpleNamespace

import pytest

from mika.inspector.catalog import Builtin, Destination, NavGroup, check
from mika.kernel.registry import CompositionError
from tests.fixtures.console_html import ConsoleHTML
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

PAGE = "/inspecteur/courrier/parametres"
#: où s'enregistrent ses boîtes et ses paramètres (les réglages, les paramètres internes)
SAVE = "/inspecteur/reglages/boites"
PARAMS = "/inspecteur/reglages/comportement-email"
ACCOUNT = {"_section": "courrier", "_enregistrement": "accounts", "_ancienne": "", "_cle": "perso",
           "_champs": ["label", "address", "imap_host", "user"], "label": "Personnel", "address": "moi@exemple.org",
           "imap_host": "imap.exemple.org", "user": "moi"}


def post(client, path: str, data: dict, **kw):
    return client.post(path, data={"csrf": client.cookies.get("csrftoken"), **data}, **kw)


def drawn(client, url: str) -> str:
    page = client.get(url)
    assert page.status_code == 200, url
    ConsoleHTML(page.text).check()
    assert "Cette vue a échoué" not in page.text, url
    return html.unescape(page.text)


def test_the_mail_settings_open_from_the_top_right_and_stay_in_the_mail(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    box = drawn(client, "/inspecteur/courrier")
    assert "<h1>Réception</h1>" in box  # le premier onglet de la barre, pas celui du bouton
    tabs = re.search(r'<nav class="tabs".*?</nav>', box, re.S).group()
    assert "Paramètres" not in tabs and "Gérer les comptes" not in box
    assert re.search(r'<a class="btn quiet gear-link" href="/inspecteur/courrier/parametres"', box)
    old = client.get(f"{SAVE}?enregistrement=accounts&cle=perso", follow_redirects=False)
    assert old.status_code == 301 and old.headers["location"] == f"{PAGE}?enregistrement=accounts&cle=perso"
    assert client.get("/inspecteur/courrier/comptes", follow_redirects=False).headers["location"].startswith(PAGE)
    page = drawn(client, PAGE)
    assert 'class="now-page mailset"' in page and "<h1>Paramètres</h1>" in page
    assert re.search(r'<a class="btn quiet gear-link on" href="/inspecteur/courrier/parametres" aria-current="page"',
                     page)
    assert "Aucune boîte encore" in page  # l'état vide, dessiné
    # ses paramètres généraux, sur la même page : ils s'enregistrent comme ailleurs, et reviennent ici
    assert f'action="{PARAMS}"' in page and f'name="_retour" value="{PAGE}"' in page
    for group in ("Relevé", "Le dire", "Brouillons"):
        assert f">{group}</h3>" in page, group
    assert "Réglages › Canaux" in page  # ce qui se règle ailleurs y mène


def test_a_mailbox_is_added_and_kept_on_the_mail_settings(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    form = drawn(client, f"{PAGE}?enregistrement=accounts&cle=&nouveau=1")
    assert "Ajouter une boîte" in form and f'action="{SAVE}"' in form and "<h1>Paramètres</h1>" in form
    for group in ("La boîte", "Connexion", "Lire", "Envoyer", "Sa voix"):
        assert f">{group}</h3>" in form, group
    added = post(client, SAVE, ACCOUNT)
    assert added.status_code == 200 and PAGE in str(added.url)
    page = html.unescape(added.text)
    assert "Personnel" in page and "moi@exemple.org" in page and "imap.exemple.org · moi" in page
    assert "/inspecteur/fiche/compte/perso" in page and f"{PAGE}?enregistrement=accounts&cle=perso" in page
    edit = drawn(client, f"{PAGE}?enregistrement=accounts&cle=perso")
    assert "La boîte" in edit and 'value="imap.exemple.org"' in edit
    refused = post(client, SAVE, {**ACCOUNT, "_ancienne": "perso", "_cle": "pro"})
    assert refused.status_code == 400
    ConsoleHTML(refused.text).check()
    again = html.unescape(refused.text)  # remontrée dans le Courrier, pas sous Réglages
    assert 'class="now-page mailset"' in again and "<h1>Paramètres</h1>" in again and "ne change pas" in again
    assert set(client.portal.call(live.settings.email).accounts) == {"perso"}


def test_a_mailbox_form_shows_what_serves_and_follows_the_changes(world):  # noqa: F811
    """La boîte d'abord, puis comment elle y entre ; ce qui ne sert pas au choix fait ne paraît pas, et le
    navigateur suit chaque changement (``data-only``, ``static/handmade/courrier_boite.js``)."""
    client, _, _ = world
    bootstrap(client)
    form = drawn(client, f"{PAGE}?enregistrement=accounts&cle=&nouveau=1")
    titles = re.findall(r'<h3 id="mailset-g\d+">([^<]+)</h3>', form)
    assert titles == ["La boîte", "Connexion", "Lire", "Envoyer", "Sa voix"]
    assert form.index('name="address"') < form.index('name="_cle"') < form.index('name="label"')
    # les champs d'un compte Microsoft, hors du pli « rarement utiles » ; masqués par mot de passe
    assert re.search(r'<div class="field" data-only="auth=microsoft" hidden>\s*<input type="hidden" '
                     r'name="_champs" value="oauth_client_id">', form)
    more = re.findall(r'<details class="hm-subfold mailset-more".*?</details>', form, re.S)
    assert not any("oauth_client_id" in fold or "sender_name" in fold or "signature" in fold for fold in more)
    # sans serveur d'envoi, ni réglages d'envoi ni voix : la page dit ce qu'elle attend
    assert re.search(r'data-only="smtp_host!=" hidden>\s*<input type="hidden" name="_champs" value="voice">', form)
    assert re.search(r'data-only="auth=password;smtp_host!=" hidden>\s*<input type="hidden" name="_champs" '
                     r'value="smtp_password">', form)
    assert re.search(r'<p class="now-muted mailset-waiting" data-only="smtp_host=">', form)
    assert "handmade/courrier_boite.js" in form and "data-new" in form
    assert '<option value="">—</option>' not in form  # un choix obligé n'offre pas de « — »
    # une boîte qui envoie : sa voix paraît, avec le nom qui va avec
    post(client, SAVE, {**ACCOUNT, "_champs": [*ACCOUNT["_champs"], "smtp_host"], "smtp_host": "smtp.exemple.org"})
    edit = drawn(client, f"{PAGE}?enregistrement=accounts&cle=perso")
    assert re.search(r'<div class="field" data-only="smtp_host!=">\s*<input type="hidden" name="_champs" '
                     r'value="voice">', edit)
    assert re.search(r'data-only="voice=elle;smtp_host!=">\s*<input type="hidden" name="_champs" '
                     r'value="sender_name">', edit)
    assert re.search(r'data-only="voice=assistante\|proprietaire;smtp_host!=" hidden>', edit)
    assert re.search(r'<p class="now-muted mailset-waiting" data-only="smtp_host=" hidden>', edit)
    assert "data-new" not in edit


def test_the_general_mail_settings_save_and_come_back_to_the_mail(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    drawn(client, PAGE)
    form = {"_faculte": "email", "_groupe": "", "_retour": PAGE, "_champs": ["per_poll"]}
    saved = post(client, PARAMS, {**form, "per_poll": "20"}, follow_redirects=False)
    assert saved.status_code == 303 and saved.headers["location"].startswith(f"{PAGE}?flash=")
    after = drawn(client, saved.headers["location"])
    assert "surcharges enregistrées" in after and "is-overridden" in after and "revenir au tempérament" in after
    refused = post(client, PARAMS, {**form, "per_poll": "1000"})  # au plus 100
    assert refused.status_code == 400
    ConsoleHTML(refused.text).check()
    shown = html.unescape(refused.text)  # remontré dans le Courrier, avec ce qui a été tapé
    assert 'class="now-page mailset"' in shown and "corrige les champs" in shown and 'value="1000"' in shown
    outside = post(client, PARAMS, {**form, "per_poll": "20", "_retour": "https://ailleurs.example/"},
                   follow_redirects=False)
    assert "ailleurs.example" not in outside.headers["location"]  # un retour hors de la console est ignoré


async def _tab(ui, request):
    return {"blocks": []}


@pytest.mark.parametrize(("gear", "refused"), [(("autre",), "bouton vers un onglet inconnu autre"),
                                               (("a", "b"), "tous ses onglets sont derrière le bouton"),
                                               (("b",), "")])
def test_a_gear_names_tabs_of_its_destination(gear, refused):
    builtins = {k: Builtin(k, k, _tab) for k in ("x.a", "x.b")}
    nav = [NavGroup("g", (Destination("x", "X", builtin=("x.a", "x.b"), gear=gear),))]
    registry = SimpleNamespace(inspectors=(), actions={})
    if not refused:
        check(nav, registry, builtins)
        return
    with pytest.raises(CompositionError, match=refused):
        check(nav, registry, builtins)
