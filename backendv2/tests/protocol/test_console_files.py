"""Les fichiers dans la console (ADR 0205 ; audit du 2026-11-05, C9-11, décision Q08) : à travers le vrai serveur.

- Mémoire › Fichiers envoyés montre ce qu'elle a envoyé, à tout le monde, à côté de Pièces reçues ;
- « Retirer », confirmé, sur la ligne d'un fichier envoyé ou d'une pièce reçue (l'onglet Fichiers de la personne,
  Mémoire) et sur sa fiche : ses octets s'effacent, sa ligne reste et le dit (« retiré par un opérateur »), ce qu'elle
  en a lu reste ; c'est audité ; un fichier retiré n'a plus ni « Retirer » ni « télécharger ».
"""

from __future__ import annotations

import hashlib
import html
import time

from mika.contracts import attachments as attachments_c
from mika.contracts import runtime as rt
from mika.contracts import shares as shares_c
from mika.faculties.attachments import row as piece_row
from mika.faculties.shares import row as file_row
from mika.kernel.events import Content
from tests.fixtures.console_html import ConsoleHTML
from tests.protocol.test_drawn_fiches import append, drawn, form_of
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

ADRIEN = "user_1"
FICHE = f"/inspecteur/fiche/person/{ADRIEN}"
SECRET, LIST, PHOTO = "a" * 32, "b" * 32, "c" * 32
BYTES = {SECRET: b"un code a ne pas garder", LIST: b"- pain\n- lait\n", PHOTO: b"\x89PNG\r\n\x1a\n" + b"x" * 64}
SEEN = "Une ordonnance au nom d'Adrien."
#: l'étiquette d'un fichier retiré par un opérateur (la question qui confirme « Retirer » le dit aussi)
SENT_GONE = '<span class="now-tag muted">retiré par un opérateur</span>'
PIECE_GONE = '<span class="now-tag muted">retirée par un opérateur</span>'


def _files(client, live) -> None:
    """Deux fichiers qu'elle lui a envoyés, une pièce qu'il lui a envoyée : leurs octets dans leur port, leur fiche au
    journal (comme ses outils et sa lecture de près les y mettent)."""
    shares, pieces = live.kernel.ports["shares"], live.kernel.ports[attachments_c.PORT]
    for file in (SECRET, LIST):
        client.portal.call(lambda f=file: shares.put(f, BYTES[f], subjects=[ADRIEN]))
    client.portal.call(lambda: pieces.put(PHOTO, BYTES[PHOTO], subjects=[ADRIEN]))
    append(client, live, [shares_c.SHARED.draft(file=f, target=ADRIEN, name=Content.of(name), mime="text/plain",
                                                size=len(BYTES[f]), digest=hashlib.sha256(BYTES[f]).hexdigest(),
                                                about=(ADRIEN,))
                          for f, name in ((SECRET, "secret.txt"), (LIST, "courses.md"))], shares_c.OWNER)
    append(client, live, [attachments_c.KEPT.draft(
        file=PHOTO, message=1, handle=ADRIEN, name=Content.of("ordonnance.png"), mime="image/png",
        size=len(BYTES[PHOTO]), digest=hashlib.sha256(BYTES[PHOTO]).hexdigest(), kind=attachments_c.IMAGE,
        seen=Content.of(SEEN), read=True)], attachments_c.OWNER)


def _erased(client, port, file: str) -> bool:
    """Les octets s'effacent après le commit (l'effet de ``*.expired``) : on les attend un peu."""
    for _ in range(100):
        if client.portal.call(lambda: port.read(file)) is None:
            return True
        time.sleep(0.05)
    return False


def _events(client, live, *types) -> list:
    """Les événements de ces types, décodés (lus dans le fil du serveur : SQLite y tient)."""
    mind = live.kernel.mind
    names = {t.name for t in types}
    return client.portal.call(lambda: [mind.decode(e) for e in mind.store.read() if e.type in names])


def _entry(page: str, name: str) -> str:
    """L'entrée d'un fichier dans une liste : de son nom (le lien vers sa fiche) à la fin de son élément de liste."""
    return page.split(f">{name}</a>", 1)[1].split("</li>", 1)[0]


def test_an_operator_removes_a_sent_file_from_the_person_s_files_tab(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    _files(client, live)
    page = drawn(client, f"{FICHE}?onglet=fichiers")
    # « Retirer » sur chaque fichier encore là, le fichier pour objet, confirmé par son nom
    sent = form_of(page, "shares.retirer", having=SECRET)
    assert sent["_sujet"] == [SECRET]
    assert form_of(page, "shares.retirer", having=LIST)["_sujet"] == [LIST]
    assert form_of(page, "attachments.retirer", having=PHOTO)["_sujet"] == [PHOTO]
    assert "Retirer « secret.txt » ? Ses octets sont effacés" in page  # data-confirm

    done = client.post("/inspecteur/action/shares.retirer", data=sent, follow_redirects=False)
    assert done.status_code == 303 and done.headers["location"].startswith(f"{FICHE}?onglet=fichiers")
    after = drawn(client, done.headers["location"])
    assert "« secret.txt » retiré : ses octets sont effacés." in after
    # la ligne reste, et le dit ; plus de « Retirer » ni de téléchargement pour elle
    gone = _entry(after, "secret.txt")
    assert SENT_GONE in gone and "/inspecteur/telecharger/partage/" not in gone
    assert f'value="{SECRET}"' not in after
    assert SENT_GONE not in _entry(after, "courses.md")
    # les octets partent, la ligne reste avec sa raison ; l'autre fichier ne bouge pas
    assert _erased(client, live.kernel.ports["shares"], SECRET)
    assert client.portal.call(lambda: live.kernel.ports["shares"].read(LIST)) == BYTES[LIST]
    line = client.portal.call(lambda: file_row(live.kernel.mind.store, SECRET))
    assert line is not None and line.gone and line.reason == shares_c.OPERATOR
    [expired] = _events(client, live, shares_c.EXPIRED)
    assert (expired.data.files, expired.data.target, expired.data.reason) == ((SECRET,), ADRIEN, shares_c.OPERATOR)
    audit = [e.data for e in _events(client, live, rt.OPERATED)]
    assert [(a.action, a.by, a.subject, a.outcome, a.seqs) for a in audit] == \
        [("shares.retirer", ADRIEN, SECRET, "done", (expired.seq,))]
    assert "n'est plus disponible" in html.unescape(client.get(f"/inspecteur/telecharger/partage/{SECRET}").text)
    # le renvoi du même formulaire ne refait rien
    again = client.post("/inspecteur/action/shares.retirer", data=sent, follow_redirects=False)
    assert again.status_code == 303
    assert len(_events(client, live, shares_c.EXPIRED)) == 1


def test_sent_files_have_their_memory_tab_and_a_piece_is_removed_from_received(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    _files(client, live)
    # Mémoire › Fichiers envoyés : à côté de Pièces reçues, ce qu'elle a envoyé à tout le monde
    sent = drawn(client, "/inspecteur/memoire/envoyes")
    assert 'data-tab="memoire/envoyes"' in sent
    bar = sent.split('class="tabs', 1)[1]
    assert bar.index("/inspecteur/memoire/recues") < bar.index("/inspecteur/memoire/envoyes") \
        < bar.index("/inspecteur/memoire/promesses")
    entry = _entry(sent, "secret.txt")
    assert ">adrien (user_1)</a>" in entry and "/inspecteur/telecharger/partage/" in entry and "pas parti" in entry
    assert form_of(sent, "shares.retirer", having=SECRET)["_sujet"] == [SECRET]

    # une pièce reçue, retirée depuis Mémoire › Pièces reçues : ses octets partent, ce qu'elle y a lu reste
    received = drawn(client, "/inspecteur/memoire/recues")
    form = form_of(received, "attachments.retirer", having=PHOTO)
    assert "Retirer « ordonnance.png » ?" in received
    done = client.post("/inspecteur/action/attachments.retirer", data=form, follow_redirects=False)
    assert done.status_code == 303 and done.headers["location"].startswith("/inspecteur/memoire/recues")
    after = drawn(client, done.headers["location"])
    piece = _entry(after, "ordonnance.png")
    assert PIECE_GONE in piece and SEEN in piece and "Télécharger" not in piece
    assert 'class="memories-item piece k-image faded"' in after
    assert _erased(client, live.kernel.ports[attachments_c.PORT], PHOTO)
    line = client.portal.call(lambda: piece_row(live.kernel.mind.store, PHOTO))
    assert line is not None and line.gone and line.reason == attachments_c.OPERATOR and line.seen == SEEN
    # l'onglet Fichiers de la personne le dit aussi
    files = drawn(client, f"{FICHE}?onglet=fichiers")
    assert PIECE_GONE in _entry(files, "ordonnance.png")
    assert 'action="/inspecteur/action/attachments.retirer"' not in files


def test_the_fiche_of_a_file_removes_it_and_then_says_so(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    _files(client, live)
    url = f"/inspecteur/fiche/partage/{LIST}"
    page = client.get(url)
    assert page.status_code == 200
    ConsoleHTML(page.text).check()
    text = html.unescape(page.text)
    form = form_of(text, "shares.retirer", having=LIST)  # sous « ⋯ », comme toute action dangereuse
    assert "Retirer ce fichier ? Ses octets sont effacés" in text
    done = client.post("/inspecteur/action/shares.retirer", data=form, follow_redirects=False)
    assert done.status_code == 303 and done.headers["location"].startswith(url)
    after = client.get(done.headers["location"])
    ConsoleHTML(after.text).check()
    said = html.unescape(after.text)
    assert "retiré par un opérateur" in said and 'action="/inspecteur/action/shares.retirer"' not in said
    assert "/inspecteur/telecharger/partage/" not in said
    assert _erased(client, live.kernel.ports["shares"], LIST)
    # la fiche d'une pièce porte le même geste
    piece = html.unescape(client.get(f"/inspecteur/fiche/piece/{PHOTO}").text)
    assert form_of(piece, "attachments.retirer", having=PHOTO)["_sujet"] == [PHOTO]
