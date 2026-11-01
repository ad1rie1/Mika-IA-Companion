"""Parcours courrier avec plusieurs comptes et de vrais formulaires HTTP."""

from __future__ import annotations

import base64
import html
import re
from dataclasses import replace
from urllib.parse import quote, urlencode

from mika.inspector.framed import FRAME_CSP, FRAME_CSP_REMOTE
from mika.ports.mail import Attachment, File
from tests.fixtures.console_html import ConsoleHTML
from tests.fixtures.courrier import framed, mailbox
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
    assert '<span class="person-count now-num">530</span>' in page  # pas seulement les 500 premiers du cache
    for tab in ("brouillons", "envoyes", "contacts"):
        assert f'href="/inspecteur/courrier/{tab}?compte=perso"' in page
        get(client, f"/inspecteur/courrier/{tab}?compte=perso")
    assert 'value="perso" selected' in page  # composer depuis le compte choisi
    assert 'name="compte" value="perso"' in page  # filtres conservent le compte
    assert "Personnel · message 529" in get(client, "/inspecteur/courrier/reception?compte=perso&page=45")  # 12 par page
    searched = get(client, "/inspecteur/courrier/reception?compte=perso&q=529")
    assert '<span class="person-count now-num">1</span>' in searched and "Personnel · message 529" in searched
    assert not box.sent and not box.actions  # consulter ne marque pas lu et n'envoie rien
    tabs = re.search(r'<nav class="tabs".*?</nav>', page, re.S).group()
    assert "Comptes" not in tabs and "Réglages" not in tabs and "Paramètres" not in tabs
    # ses paramètres : le bouton en haut à droite, plus un lien dans la barre de côté (ADR 0172)
    assert re.search(r'<a class="btn quiet gear-link" href="/inspecteur/courrier/parametres[^"]*"', page)
    assert "Gérer les comptes" not in page
    assert client.get("/inspecteur/courrier/comptes", follow_redirects=False).status_code == 301


def test_reader_displays_html_safely_and_replies_from_the_original_account(world):  # noqa: F811
    client, box = setup(world)
    key = quote("pro:<projet@example.test>", safe="")
    page = get(client, f"/inspecteur/fiche/mail/{key}")
    mail = framed(client, page)  # le mail tel qu'il a été écrit, dans son cadre (ADR 0169)
    assert "<strong>Ton retour jeudi</strong>" in mail and "<h1>Les maquettes sont prêtes</h1>" in mail
    assert "FIN DU MESSAGE LONG" in page  # sa version texte, dans la page
    assert '<a href="https://example.test/projet" target="_blank"' in mail
    assert "Logo Atelier" in mail  # l'image distante : son texte de remplacement
    for text in (page, mail):
        assert "tracker.example.test" not in text and "window.mailExecuted" not in text
    assert "frame-src 'self'" in client.get(f"/inspecteur/fiche/mail/{key}").headers["content-security-policy"]
    assert 'class="hm-reading' in page  # un document à lire (ADR 0121)
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


def test_a_mail_frame_needs_the_console_session_and_says_when_it_is_gone(world):  # noqa: F811
    client, _ = setup(world)
    page = get(client, "/inspecteur/fiche/mail/" + quote("pro:<projet@example.test>", safe=""))
    src = re.search(r'<iframe class="document-frame" src="([^"]+)"', page).group(1)
    gone = client.get("/inspecteur/document/" + "0" * 40)  # oublié (un redémarrage) : la page rechargée le redonne
    assert gone.status_code == 404 and "recharge la page" in gone.text
    assert gone.headers["content-security-policy"] == FRAME_CSP
    client.cookies.clear()
    assert client.get(src, follow_redirects=False).status_code == 303  # vers la connexion


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


def test_inline_images_show_in_the_frame_and_a_mail_kept_before_rereads_its_parts(world):  # noqa: F811
    """ADR 0172 : le logo intégré (``cid:``) s'affiche dans le cadre ; un mail relevé avant que ses pièces soient
    gardées le dit, et se relit pour les garder."""
    client, box = setup(world)
    m = box.cached_one('pro:<projet@example.test>')
    logo = b'\x89PNG\r\n\x1a\n-logo-atelier'
    box.inbox[box.inbox.index(m)] = replace(m, html=m.html + '<img src="cid:logo@atelier" alt="Logo intégré">',
                                            parts_kept=False)
    box.inline[m.ref] = (('logo@atelier', 'image/png', logo),)
    url = '/inspecteur/fiche/mail/' + quote(m.ref, safe='')
    page = get(client, url)
    mail = framed(client, page)
    assert f'src="data:image/png;base64,{base64.b64encode(logo).decode()}"' in mail
    assert 'tracker.example.test' not in mail  # l'image distante, elle, reste masquée
    assert 'relevé avant que ses pièces soient gardées' in page and 'Récupérer ses pièces' in page
    done = client.post('/inspecteur/action/email.completer', data=posted_form(page, 'email.completer'))
    assert done.status_code == 200, done.text
    assert ('reread', m.ref) in box.actions
    assert 'Récupérer ses pièces' not in get(client, url)


def test_inbox_reading_list_and_table_keep_account_filters_and_return_path(world):  # noqa: F811
    client, box = setup(world)
    url = '/inspecteur/courrier/reception?compte=perso&q=message&etat=non_lus'
    listing = get(client, url)
    assert 'class="mail-lines"' in listing and "lire=" in listing  # une ligne ouvre le message sous la liste
    table = get(client, url + '&vue_pg1=table')
    assert 'class="mail-lines"' not in table and 'class="hm-table"' in table
    assert 'name="vue_pg1" value="table"' in table
    assert 'name="compte" value="perso"' in table
    assert 'Personnel · message 001' in listing and 'Personnel · message 001' in table
    assert 'Personnel · message 000' not in listing and 'Maquettes du projet' not in table
    link = re.search(r'href="([^\"]+/fiche/mail/[^\"]+)"', table).group(1)
    reader = get(client, link)
    assert 'retour=' in link and 'vue_pg1%3Dtable' in link
    assert 'vue_pg1=table' in reader
    next_page = re.search(r'<a href="([^\"]+)" rel="next">', table).group(1)
    assert 'vue_pg1=table' in next_page and 'compte=perso' in next_page
    assert not box.sent and not box.actions


def test_a_line_opens_the_message_under_the_list_with_its_actions(world):  # noqa: F811
    """La boîte se lit comme une messagerie : une ligne par message, douze par page ; une ligne ouvre le message
    sous la liste (``?lire=``) avec ses actions, préparées à son nom (leur jeton), et un lien vers sa fiche."""
    client, box = setup(world)
    listing = get(client, "/inspecteur/courrier/reception?compte=perso")
    # une case par ligne, qui appartient à la barre de la liste (ADR 0175), puis le lien qui ouvre le message
    lines = re.findall(r'<li class="[^"]*"><label class="mail-check"><input type="checkbox" name="mails" value="[^"]+" '
                       r'form="mail-bulk"[^>]*></label><a href="\?', listing)
    assert listing.count('<li class="') >= 12 and len(lines) == 12
    assert 'rel="next"' in listing and "Choisis un message pour le lire ici." in listing
    key = quote("pro:<projet@example.test>", safe="")
    page = get(client, f"/inspecteur/courrier/reception?compte=pro&lire={key}")
    assert '<li class="unread on">' in page  # la ligne du message ouvert
    reader = page.split('class="now-card mail-reader"')[1]
    assert "Maquettes du projet" in reader and "<strong>Ton retour jeudi</strong>" in framed(client, reader)
    assert "maquettes.pdf" in reader and f'href="/inspecteur/fiche/mail/{key}"' in reader
    form = re.search(r'<form[^>]+action="/inspecteur/action/email.repondre".*?</form>', reader, re.S).group()
    assert 'name="csrf"' in form  # le retour ramène au message ouvert
    assert 'name="_retour" value="/inspecteur/courrier/reception?compte=pro&lire=' in form
    assert not box.sent and not box.actions  # lire ne marque pas lu et n'envoie rien


# ── Le courrier au quotidien (ADR 0175) ───────────────────────────────────

BULK = r'name="mails" value="([^"]+)" form="mail-bulk"'


def test_the_side_names_what_you_read_on_every_mail_page(world):  # noqa: F811
    """À côté : ce qu'on lit (à la place des onglets, que la feuille tait), les comptes, les dossiers — sur chaque page
    du courrier."""
    client, _ = setup(world)
    page = get(client, "/inspecteur/courrier/reception?compte=perso")
    side = page.split('aria-label="Le courrier, ses comptes et ses dossiers"')[1].split("</aside>")[0]
    for label in ("Réception", "À traiter", "Suivis", "Ses brouillons", "Envoyés", "Contacts", "Comptes", "Dossiers"):
        assert label in side, label
    assert "/inspecteur/courrier/reception?compte=perso&etat=a_traiter&dossier=%2A" in side
    assert 'class="hm-workspace mail-views"' in page
    assert "<h2>Suivis</h2>" in get(client, "/inspecteur/courrier/reception?compte=perso&etat=suivis&dossier=*")
    assert "<h2>À traiter</h2>" in get(client, "/inspecteur/courrier/reception?compte=perso&etat=a_traiter&dossier=*")
    for tab in ("brouillons", "envoyes", "contacts"):
        assert "Dossiers" in get(client, f"/inspecteur/courrier/{tab}?compte=perso")
    # remonter plus loin : au bout de la liste, plus dans la barre du haut
    assert page.index("Charger des messages plus anciens") > page.index('class="mail-lines"')


def test_checked_lines_are_tidied_at_once_on_the_server(world):  # noqa: F811
    client, box = setup(world)
    url = "/inspecteur/courrier/reception?compte=perso&etat=non_lus"
    page = get(client, url)
    keys = re.findall(BULK, page)[:2]
    assert len(keys) == 2 and 'action="/inspecteur/action/email.ranger"' in page
    nothing = client.post("/inspecteur/action/email.ranger", data=posted_form(page, "email.ranger", geste="lu"))
    assert nothing.status_code == 400 and not box.actions  # rien de coché : rien ne part
    done = client.post("/inspecteur/action/email.ranger", data=posted_form(page, "email.ranger", mails=keys, geste="lu"))
    assert done.status_code == 200, done.text
    assert ("seen_many", tuple(keys)) in box.actions  # par lot, sur le serveur
    after = get(client, url)
    assert all(f'value="{k}" form="mail-bulk"' not in after for k in keys)  # sortis de tes non-lus
    other = re.findall(BULK, after)[0]
    moved = client.post("/inspecteur/action/email.ranger",
                        data=posted_form(after, "email.ranger", mails=[other], geste="archiver"))
    assert moved.status_code == 200 and any(a[:2] == ("move", other) for a in box.actions)
    assert not box.sent


def test_remote_images_show_once_or_always_for_a_sender(world):  # noqa: F811
    client, box = setup(world)
    key = quote("pro:<projet@example.test>", safe="")
    url = f"/inspecteur/fiche/mail/{key}"
    page = get(client, url)
    assert "Images masquées" in page and "Les afficher cette fois" in page and "Toujours pour cet expéditeur" in page
    assert "tracker.example.test" not in framed(client, page)

    def frame_of(text):
        src = re.search(r'<iframe class="document-frame" src="([^"]+)"', text).group(1)
        return client.get(src)

    once = frame_of(get(client, url + "?images=1"))
    assert once.headers["content-security-policy"] == FRAME_CSP_REMOTE
    assert once.headers["referrer-policy"] == "no-referrer"
    assert 'src="https://tracker.example.test/pixel"' in once.text and "window.mailExecuted" not in once.text
    assert not box.images_from  # cette fois seulement
    reader = get(client, f"/inspecteur/courrier/reception?compte=pro&lire={key}")
    assert "reception?compte=pro&lire=" in reader and "&images=1" in reader  # la liseuse reste sur la boîte
    done = client.post("/inspecteur/action/email.images", data=posted_form(page, "email.images"))
    assert done.status_code == 200 and box.images_from == {"lea@example.test"}
    always = get(client, url)
    assert "Ne plus les afficher" in always and "Images masquées" not in always
    assert frame_of(always).headers["content-security-policy"] == FRAME_CSP_REMOTE
    off = client.post("/inspecteur/action/email.images_masquer", data=posted_form(always, "email.images_masquer"))
    assert off.status_code == 200 and not box.images_from
    assert frame_of(get(client, url)).headers["content-security-policy"] == FRAME_CSP


def test_the_reader_steps_through_the_list_and_reads_after_a_delay_only_when_asked(world):  # noqa: F811
    client, box = setup(world)
    listing = get(client, "/inspecteur/courrier/reception?compte=perso")
    keys = re.findall(BULK, listing)

    def reader(n):
        page = get(client, "/inspecteur/courrier/reception?compte=perso&" + urlencode({"lire": keys[n]}))
        return page.split('class="now-card mail-reader"')[1]

    middle = reader(1)
    assert 'rel="prev"' in middle and urlencode({"lire": keys[0]}) in middle
    assert 'rel="next"' in middle and urlencode({"lire": keys[2]}) in middle
    assert 'rel="prev"' not in reader(0)
    assert "Lui demander une réponse" in middle and "Marquer comme lu" in middle  # à portée
    assert "data-read-after" not in middle  # ouvrir ne marque rien comme lu, par défaut
    saved = client.post("/inspecteur/reglages/comportement-email", follow_redirects=False, data={
        "csrf": client.cookies.get("csrftoken"), "_faculte": "email", "_groupe": "",
        "_retour": "/inspecteur/courrier/parametres", "_champs": ["read_on_open"], "read_on_open": "3s"})
    assert saved.status_code == 303
    assert 'data-read-after="3"' in reader(1)
    assert 'data-read-after="3"' in get(client, "/inspecteur/fiche/mail/" + quote(keys[1], safe=""))
    assert "Ouvrir un mail le marque lu" in get(client, "/inspecteur/courrier/parametres")
    assert not box.actions and not box.sent  # le script s'en charge : la page, elle, ne marque rien

