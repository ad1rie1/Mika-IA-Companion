"""Parcours courrier avec plusieurs comptes et de vrais formulaires HTTP."""

from __future__ import annotations

import html
import re
from dataclasses import replace
from urllib.parse import quote

from mika.ports.mail import Attachment, File
from tests.fixtures.console_html import ConsoleHTML
from tests.fixtures.courrier import mailbox
from tests.protocol.test_console_workflows import page as export_page
from tests.protocol.test_web import bootstrap, world  # noqa: F401


def setup(environment):
    client, live, _ = environment
    bootstrap(client)
    box = mailbox(530)
    live.kernel.ports["mail"] = box
    return client, box


def get(client, url):
    response = client.get(url)
    assert response.status_code == 200
    assert "Cette vue a échoué" not in response.text
    ConsoleHTML(response.text).check()
    return html.unescape(response.text)


def test_account_scope_survives_tabs_search_pagination_and_composing(world, tmp_path):  # noqa: F811
    client, box = setup(world)
    page = export_page(client, "/inspecteur/courrier/reception?compte=perso", tmp_path / 'review')
    export_page(client, "/inspecteur/courrier/reception?compte=pro", tmp_path / 'review')
    assert "Personnel · message 000" in page and "Maquettes du projet" not in page
    assert "530 au total" in page  # pas seulement les 500 premiers du cache
    for tab in ("brouillons", "envoyes", "contacts"):
        assert f'href="/inspecteur/courrier/{tab}?compte=perso"' in page
        get(client, f"/inspecteur/courrier/{tab}?compte=perso")
    assert 'value="perso" selected' in page  # composer depuis le compte choisi
    assert 'name="compte" value="perso"' in page  # filtres conservent le compte
    assert "Personnel · message 529" in get(client, "/inspecteur/courrier/reception?compte=perso&page=22")
    searched = get(client, "/inspecteur/courrier/reception?compte=perso&q=529")
    assert "1 au total" in searched and "Personnel · message 529" in searched
    assert not box.sent and not box.actions  # consulter ne marque pas lu et n'envoie rien
    tabs = re.search(r'<nav class="tabs".*?</nav>', page, re.S).group()
    assert "Comptes" not in tabs and "Réglages" not in tabs
    assert 'href="/inspecteur/reglages/boites"' in page
    assert client.get("/inspecteur/courrier/comptes", follow_redirects=False).status_code == 301


def test_reader_displays_html_safely_and_replies_from_the_original_account(world):  # noqa: F811
    client, box = setup(world)
    key = quote("pro:<projet@example.test>", safe="")
    page = get(client, f"/inspecteur/fiche/mail/{key}")
    assert "<strong>Ton retour jeudi</strong>" in page
    assert "FIN DU MESSAGE LONG" in page
    assert '<a href="https://example.test/projet"' in page
    assert 'src="https://tracker.example.test' not in page and "window.mailExecuted" not in page
    assert 'class="reading-document"' in page or 'card reading-document' in page
    assert "maquettes.pdf" in page and "150 Ko" in page
    assert "/inspecteur/courrier/reception?compte=pro&dossier=INBOX" in page
    # Submit the actual displayed reply form into the fake mail port.
    form = re.search(r'<form[^>]+action="/inspecteur/action/email.repondre".*?</form>', page, re.S).group()
    data = {}
    for name, value in re.findall(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', form):
        data.setdefault(name, []).append(value)
    data.update(to="lea@example.test", cc="", subject="Re: Maquettes", body="Merci, retour jeudi.", quote="1")
    response = client.post("/inspecteur/action/email.repondre", data=data)
    assert response.status_code == 200 and len(box.outgoing) == 3
    sent = box.outgoing[-1]
    assert sent.account == "pro" and sent.in_reply_to == "pro:<projet@example.test>"
    sent_page = get(client, "/inspecteur/courrier/envoyes?compte=pro")
    assert "Envoyé depuis Personnel" not in sent_page and "Re: Maquettes" in sent_page


def test_folders_unread_and_unknown_accounts_do_not_mix_mail(world):  # noqa: F811
    client, box = setup(world)
    archive = get(client, "/inspecteur/courrier/reception?compte=pro&dossier=Archives")
    assert "Ancien devis" in archive and "Maquettes du projet" not in archive and "Personnel · message" not in archive
    unread = get(client, "/inspecteur/courrier/reception?compte=perso&etat=non_lus")
    assert "Personnel · message 000" not in unread and "Personnel · message 001" in unread
    unknown = get(client, "/inspecteur/courrier/reception?compte=absent")
    assert "Ce compte n'existe plus" in unknown and "Personnel · message" not in unknown
    message = box.cached_one("pro:<projet@example.test>")
    box.deliver(replace(message, account="perso", subject="Copie personnelle distincte"))
    thread = get(client, "/inspecteur/fiche/mail/" + quote(message.ref, safe="") + "?onglet=fil")
    assert "Maquettes du projet" in thread and "Copie personnelle distincte" not in thread
    folder = next(f.name for f in box.folders("pro") if f.role == "sent")
    box.deliver(replace(message, message_id="<sent-cache@example.test>", folder=folder, subject="Envoyé depuis un autre client"))
    sent = get(client, "/inspecteur/courrier/envoyes?compte=pro")
    assert "Envoyé depuis un autre client" in sent and "Envoyé depuis Atelier" in sent
    assert "Envoyé depuis Personnel" not in sent


def posted_form(page, action, **values):
    form = re.search(r'<form[^>]+action="/inspecteur/action/' + action + r'".*?</form>', page, re.S).group()
    data = {}
    for name, value in re.findall(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', form):
        data.setdefault(name, []).append(value)
    return {**data, **values}


def test_complete_document_downloads_and_forwarding_are_real_workflows(world, tmp_path):  # noqa: F811
    client, box = setup(world)
    m = box.cached_one('pro:<projet@example.test>')
    body = 'Texte du document complet.\n' * 4500 + 'DERNIÈRE LIGNE DU DOCUMENT'
    # Trois parties lisibles et téléchargeables, même au-delà de la limite d'un bloc.
    box.inbox[box.inbox.index(m)] = replace(m, body=body, html='', attachments=(Attachment('devis été.pdf', 'application/pdf', 15),))
    box.files[(m.ref, '0')] = File('devis été.pdf', 'application/pdf', b'%PDF-test\x00\xffFIN')
    url = '/inspecteur/fiche/mail/' + quote(m.ref, safe='')
    page = export_page(client, url, tmp_path / 'review')
    assert 'partie 1 sur 3' in page and 'Partie suivante' in page and 'DERNIÈRE LIGNE' not in page
    last = export_page(client, url + '?onglet=message&page_texte=3', tmp_path / 'review')
    assert 'DERNIÈRE LIGNE DU DOCUMENT' in last and 'Partie précédente' in last and 'Partie suivante' not in last
    file_url = '/inspecteur/telecharger/mail/' + quote(m.ref, safe='')
    downloaded = client.get(file_url + '?fichier=0')
    assert downloaded.content == b'%PDF-test\x00\xffFIN' and downloaded.status_code == 200
    assert "attachment; filename*=UTF-8''devis%20%C3%A9t%C3%A9.pdf" == downloaded.headers['content-disposition']
    assert downloaded.headers['x-content-type-options'] == 'nosniff'
    assert downloaded.headers['cache-control'] == 'no-store'
    assert client.get(file_url + '?fichier=texte').content.decode() == body
    assert client.get(file_url + '?fichier=../source').status_code == 404
    assert client.get(file_url + '?fichier=90').status_code == 404
    assert not box.actions and not box.sent
    data = posted_form(page, 'email.transferer', to='dest@example.test', cc='', subject='Tr : Document', body='Pour toi.', attachments='1')
    sent = client.post('/inspecteur/action/email.transferer', data=data)
    assert sent.status_code == 200, sent.text
    assert len(box.outgoing) == 3 and box.outgoing[-1].account == 'pro'
    assert body in box.outgoing[-1].body
    assert box.outgoing_files[box.outgoing[-1].message_id][0].data == downloaded.content
    outgoing_url = '/inspecteur/fiche/mail/' + quote(box.outgoing[-1].ref, safe='')
    outgoing = export_page(client, outgoing_url, tmp_path / 'review')
    assert 'devis été.pdf' in outgoing
    assert client.get('/inspecteur/telecharger/mail/' + quote(box.outgoing[-1].ref, safe='') + '?fichier=0').content == downloaded.content
    # La protection de session s'applique aussi aux fichiers, pas seulement aux pages.
    client.cookies.clear()
    assert client.get(file_url + '?fichier=0', follow_redirects=False).status_code in (303, 307)


def test_global_mail_search_reaches_every_result_and_old_threads(world):  # noqa: F811
    client, box = setup(world)
    url = '/inspecteur/recherche?q=Personnel&sorte=mail'
    seen = set()
    for n in range(22):
        page = get(client, url)
        seen.update(re.findall(r'Personnel · message (\d{3})', page))
        next_link = re.search(r'<a href="([^"]+)" rel="next">', page)
        if n < 21:
            assert next_link is not None
            url = '/inspecteur/recherche' + next_link.group(1)
        else:
            assert next_link is None and 'Plus récents' in page
    assert seen == {f'{n:03}' for n in range(530)}
    old = get(client, '/inspecteur/fiche/mail/' + quote('perso:<perso-529@example.test>', safe='') + '?onglet=fil')
    assert 'Personnel · message 529' in old and "Ce mail n'est plus" not in old


def test_legacy_cache_is_labelled_and_all_attachment_links_are_paginated(world):  # noqa: F811
    client, box = setup(world)
    m = box.cached_one('pro:<projet@example.test>')
    box.inbox[box.inbox.index(m)] = replace(m, complete=False, attachments=tuple(
        Attachment(f'fichier-{i}.txt', 'text/plain', 20) for i in range(31)))
    url = '/inspecteur/fiche/mail/' + quote(m.ref, safe='')
    page = get(client, url)
    assert 'ancien cache' in page and 'Charger le message intégral' in page
    assert 'fichier-24.txt' in page and 'fichier-25.txt' not in page
    assert 'fichier-30.txt' in get(client, url + '?pg1=2')
