"""La fiche d'un projet › Documentation, calquée sur l'écran Projets (ADR 0289, 0297) : ses pages rendues par le
moteur — ses images servies par la console, aucune image ni aucun lien du dehors, aucun script — ; l'éditeur, qui
enregistre par l'action déclarée en nommant la version lue, et dont un refus revient à l'éditeur — un conflit
seulement quand la page a bougé ; une version, et le retour à elle ; créer, renommer, supprimer ; l'aperçu rendu par
le moteur ; ses images (téléverser, la référence, retirer) ; ses décisions (consigner, modifier, remplacer, retirer,
remettre en vigueur)."""

from __future__ import annotations

import re
from urllib.parse import quote

from mika.faculties.projects import docs
from mika.faculties.projects import inspect_docs as words
from mika.kernel.forms import Upload
from mika.runtime.operations import perform
from tests.protocol.test_drawn_fiches import form_of
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_project_fiche_tabs import _chain, _do
from tests.protocol.test_web import world  # noqa: F401 — fixture partagée

FICHE = "/admin/fiche/project/{}?onglet=documentation"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
HOME = ("# Outils réseau\n\nVoir [l'installation](guide/installation.md), [dehors](https://piege.example/x) et "
        "[une page absente](absente.md).\n\n![Le schéma](images/schema.png)\n\n![loin](https://piege.example/i.png)"
        "\n\n<script>alert(1)</script>\n\n## Les commandes\n\n| Commande | Ce qu'elle fait |\n|:--|--:|\n| scan | liste |\n")


def _page(client, pid: int, more: str = "") -> str:
    return drawn(client, FICHE.format(pid) + more)


def _post(client, form: dict[str, list[str]], action: str, files=None, **values: str):
    data = {**form, "_champs": [*form.get("_champs", []), *values], **{k: [v] for k, v in values.items()}}
    return client.post(f"/admin/action/{action}", data=data, files=files, follow_redirects=False)


def _space(client, live) -> tuple[object, int]:
    kernel, pid, _ = _chain(client, live)
    _do(client, kernel, pid, "doc_ecrire", "w-inst", path="guide/installation.md", text="# Installation\n\nDeux "
        "commandes.", base="0")
    got = client.portal.call(lambda: perform(kernel, "projects.doc_image", {}, by="user_1", subject=str(pid),
                                             nonce="img-1", files=(Upload(name="schema.png", data=PNG),)))
    assert got.ok, got
    _do(client, kernel, pid, "doc_ecrire", "w-home", path="accueil.md", text=HOME, base="0")
    return kernel, pid


def _version(client, live, pid: int, path: str) -> int:
    return client.portal.call(lambda: docs.page(live.kernel.mind.store, pid, path)).version


def test_a_page_is_rendered_by_the_engine_with_its_own_images_and_nothing_from_outside(world):  # noqa: F811
    client, live, _ = world
    _, pid = _space(client, live)
    page = _page(client, pid)
    bar = page.split('aria-label="Sa documentation"', 1)[1].split("</nav>", 1)[0]
    assert re.findall(r'aria-current="page">([^<]+)', bar) == ["Pages"] and "Images" in bar and "Décisions" in bar
    body = page.split('class="pj-md pj-doc"', 1)[1].split("</article>", 1)[0]
    # la page d'accueil s'ouvre ; ses titres gardent leur ordre et une ancre, un cran plus bas, son tableau est une grille
    assert '<h2 id="doc-1">Outils réseau</h2>' in body and '<h3 id="doc-2">Les commandes</h3>' in body
    assert 'class="pj-doc-table c2"' in body and "<table" not in body and "style=" not in body
    # son image est servie par la console ; celle d'ailleurs n'est que son texte ; aucun script
    src = f"/admin/image/project/{pid}?fichier=" + quote("documentation:images/schema.png", safe="")
    kept = re.search(re.escape(f'<img class="pj-doc-img" src="{src}&v=') + r'(\d+)"', body)
    assert kept and "piege.example/i.png" not in body.split("title=")[0]
    raw = client.get(FICHE.format(pid)).text  # ``drawn`` rend le texte : le HTML brut se lit ici
    assert "<script>alert" not in raw and "&lt;script&gt;alert(1)&lt;/script&gt;" in raw
    # le seul lien qui s'ouvre mène à une autre page de l'espace, dans la console
    hrefs = re.findall(r'<a href="([^"]+)"', body)
    assert hrefs == [f"/admin/fiche/project/{pid}?onglet=documentation&page=guide%2Finstallation.md"]
    assert '<span class="pj-md-a" title="https://piege.example/x">dehors</span>' in body
    # son panneau : son sommaire, sa dernière modification, ses versions, ses images
    side = page.split('<aside class="pj-side"', 1)[1].split("</aside>", 1)[0]
    assert "Sur cette page" in side and "Les commandes" in side and "Version 1 · actuelle" in side
    assert "depuis la console" in side and "schema.png" in side
    # l'image se sert comme une image, et rien d'autre
    shown = client.get(src)
    assert shown.status_code == 200 and shown.headers["content-type"] == "image/png" and shown.content == PNG
    assert "sandbox" in shown.headers["content-security-policy"] and shown.headers["cache-control"] == "no-store"
    # son adresse nomme sa version (quand elle a été ajoutée) : le navigateur la garde, l'éditeur ne redemande pas
    # toutes ses vignettes à chaque page
    versioned = client.get(f"{src}&v={kept.group(1)}")
    assert versioned.content == PNG and versioned.headers["cache-control"] == "private, max-age=86400"
    assert client.get(f"/admin/image/project/{pid}?fichier=documentation:images/absente.png").status_code == 404
    # l'arborescence, la recherche
    tree = page.split('aria-label="L\'arborescence"', 1)[1].split("</nav>", 1)[0]
    assert re.findall(r"<span>([^<]+)</span>", tree) == ["guide", "installation.md", "accueil.md"]
    found = _page(client, pid, "&q=commandes")
    assert "2 pages pour « commandes »" in found or "1 page pour « commandes »" in found


def test_the_editor_saves_by_the_declared_action_and_a_conflict_is_only_a_moved_page(world):  # noqa: F811
    client, live, _ = world
    kernel, pid = _space(client, live)
    editor = _page(client, pid, "&page=accueil.md&modifier=1")
    assert 'data-doc-editor' in editor and 'name="text"' in editor and "# Outils réseau" in editor
    form = form_of(editor, "projects.doc_ecrire")
    assert form["base"] == ["1"] and form["path"] == ["accueil.md"]
    assert form["_retour"] == [f"/admin/fiche/project/{pid}?onglet=documentation&page=accueil.md&modifier=1&lu=1"]
    # enregistrée : la page se relit, et le brouillon du navigateur s'efface
    sent = _post(client, form, "projects.doc_ecrire", text=HOME + "\nUne ligne de plus.", word="Une ligne")
    assert sent.status_code == 303
    back = drawn(client, sent.headers["location"])
    assert words.SAVED.format(version=2, path="accueil.md") in back and f'data-doc-saved="mika-doc:{pid}:accueil.md"' in back
    assert "data-doc-editor" not in back and _version(client, live, pid, "accueil.md") == 2
    # quelqu'un l'enregistre pendant qu'on l'écrit : rien n'est écrasé, l'éditeur revient sur la version actuelle
    editor = _page(client, pid, "&page=accueil.md&modifier=1")
    form = form_of(editor, "projects.doc_ecrire")
    _do(client, kernel, pid, "doc_ecrire", "w-other", path="accueil.md", text="Autre chose.", base="2")
    sent = _post(client, form, "projects.doc_ecrire", text="Mon texte à moi.", word="")
    back = drawn(client, sent.headers["location"])
    assert words.MOVED_ON.split(" :")[0] in back and "écrite par " in back and "La page a bougé depuis ta lecture" in back
    assert "data-restore" in back and form_of(back, "projects.doc_ecrire")["base"] == ["3"]
    assert _version(client, live, pid, "accueil.md") == 3
    # un refus qui n'est pas un conflit (le même texte) revient aussi à l'éditeur, sans le dire « conflit »
    form = form_of(back, "projects.doc_ecrire")
    sent = _post(client, form, "projects.doc_ecrire", text="Autre chose.", word="")
    back = drawn(client, sent.headers["location"])
    assert words.SAME in back and "La page a bougé" not in back and "data-restore" in back
    # une page nouvelle : son chemin se tape ; le retour suit le chemin (le script l'ajoute) et l'ouvre
    new = _page(client, pid, "&nouvelle=1")
    assert "Nouvelle page" in new and 'name="path"' in new
    form = form_of(new, "projects.doc_ecrire")
    assert form["base"] == ["0"]
    form["_retour"] = [form["_retour"][0] + "&page=guide/depannage.md"]
    sent = _post(client, form, "projects.doc_ecrire", path="guide/depannage.md", text="# Dépannage", word="")
    back = drawn(client, sent.headers["location"])
    assert words.CREATED.format(path="guide/depannage.md") in back and "<h2 id=\"doc-1\">Dépannage</h2>" in back
    # revenir à une version : une version de plus, qui reprend son texte
    old = _page(client, pid, "&page=accueil.md&version=1")
    assert "Version 1" in old and "Revenir à cette version" in old
    form = form_of(old, "projects.doc_ecrire")
    assert form["restored"] == ["1"] and form["base"] == ["3"]
    sent = _post(client, form, "projects.doc_ecrire")
    assert words.RESTORED.format(version=4, path="accueil.md", restored=1) in drawn(client, sent.headers["location"])
    assert _version(client, live, pid, "accueil.md") == 4
    # renommer, puis supprimer
    page = _page(client, pid, "&page=guide/depannage.md")
    sent = _post(client, form_of(page, "projects.doc_deplacer"), "projects.doc_deplacer", to="guide/aide.md")
    assert words.MOVED.format(to="guide/aide.md") in drawn(client, sent.headers["location"])
    page = _page(client, pid, "&page=guide/aide.md")
    sent = _post(client, form_of(page, "projects.doc_supprimer"), "projects.doc_supprimer")
    assert words.REMOVED.format(path="guide/aide.md") in drawn(client, sent.headers["location"])
    # l'aperçu de l'éditeur : rendu par le moteur, comme la page le sera ; il veut le jeton de la page
    token = re.search(r'data-csrf="([^"]+)"', _page(client, pid, "&page=accueil.md&modifier=1")).group(1)
    seen = client.post(f"/admin/apercu/project/{pid}", data={"csrf": token, "text": "# Titre\n\n![s](images/schema.png)"
                                                            " <b>x</b>", "chemin": "accueil.md"})
    assert seen.status_code == 200 and '<h2 id="doc-1">Titre</h2>' in seen.text and 'class="pj-doc-img"' in seen.text
    assert "<b>x" not in seen.text and "&lt;b&gt;x" in seen.text
    assert client.post(f"/admin/apercu/project/{pid}", data={"csrf": "faux", "text": "x"}).status_code == 403


def test_images_are_uploaded_cited_and_removed(world):  # noqa: F811
    client, live, _ = world
    _, pid = _space(client, live)
    page = _page(client, pid, "&vue=images")
    assert 'enctype="multipart/form-data"' in page and 'name="_fichier"' in page
    assert "schema.png" in page and "1 page" in page and "![schema](images/schema.png)" in page
    form = form_of(page, "projects.doc_image")
    sent = _post(client, form, "projects.doc_image", files={"_fichier": ("capture scan.png", PNG, "image/png")})
    back = drawn(client, sent.headers["location"])
    assert words.IMAGE_ADDED.format(name="capture-scan.png") in back and "capture-scan.png" in back
    # rien d'autre qu'une image
    sent = _post(client, form_of(back, "projects.doc_image"), "projects.doc_image",
                 files={"_fichier": ("note.txt", b"bonjour", "text/plain")})
    assert words.NOT_AN_IMAGE in drawn(client, sent.headers["location"])
    chosen = _page(client, pid, "&vue=images&image=schema.png")
    drop = form_of(chosen, "projects.doc_image_retirer")
    assert drop["name"] == ["schema.png"] and "1 page la cite encore" in chosen
    sent = _post(client, drop, "projects.doc_image_retirer")
    assert words.IMAGE_REMOVED.format(name="schema.png") in drawn(client, sent.headers["location"])
    # la page qui la citait n'en montre plus que le texte
    assert "Le schéma</span>" in _page(client, pid)


def test_decisions_are_consigned_edited_replaced_and_withdrawn(world):  # noqa: F811
    client, live, _ = world
    _, pid, _ = _chain(client, live)
    page = _page(client, pid, "&vue=decisions&nouvelle=1")
    sent = _post(client, form_of(page, "projects.decision_ajouter"), "projects.decision_ajouter",
                 title="Le format du journal", choice="Du JSON Lines", reason="Un refus par ligne.",
                 context="Le collecteur le lit.", options="Du texte libre", replaces="0")
    back = drawn(client, sent.headers["location"])
    assert "Décision consignée" in back
    n = int(re.search(r"Décision n° (\d+)</p><h2>Le format du journal", back).group(1))
    detail = _page(client, pid, f"&vue=decisions&decision={n}")
    assert "Du JSON Lines" in detail and "Un refus par ligne." in detail and "Options écartées" in detail
    edit = _page(client, pid, f"&vue=decisions&decision={n}&geste=modifier")
    form = form_of(edit, "projects.decision_modifier")
    assert form["decision"] == [str(n)] and "Le collecteur le lit." in edit
    sent = _post(client, form, "projects.decision_modifier", title="Le format du journal", choice="Du JSON Lines, UTC",
                 reason="Un refus par ligne.", context="Le collecteur le lit.", options="Du texte libre")
    assert "Du JSON Lines, UTC" in drawn(client, sent.headers["location"])
    swap = _page(client, pid, f"&vue=decisions&decision={n}&geste=remplacer")
    form = form_of(swap, "projects.decision_ajouter")
    assert form["replaces"] == [str(n)]
    sent = _post(client, form, "projects.decision_ajouter", title="Le format du journal", choice="Du CSV",
                 reason="Le tableur.", context="", options="")
    assert sent.status_code == 303
    old = _page(client, pid, f"&vue=decisions&statut=toutes&decision={n}")
    assert "remplacée" in old and "Remplacée par" in old and "projects.decision_statut" not in old
    newest = _page(client, pid, "&vue=decisions")
    status = form_of(newest, "projects.decision_statut")
    assert status["status"] == ["withdrawn"]
    sent = _post(client, status, "projects.decision_statut")
    assert "retirée" in drawn(client, sent.headers["location"])
    gone = _page(client, pid, "&vue=decisions&statut=withdrawn")
    sent = _post(client, form_of(gone, "projects.decision_statut"), "projects.decision_statut")
    assert "remise en vigueur" in drawn(client, sent.headers["location"])
    # l'ancienne adresse des décisions mène ici
    moved = client.get(f"/admin/fiche/project/{pid}?onglet=decisions", follow_redirects=False)
    assert moved.status_code == 303 and "onglet=documentation" in moved.headers["location"] \
        and "vue=decisions" in moved.headers["location"]


def test_a_reload_after_saving_is_not_a_conflict_and_a_taken_path_says_so(world):  # noqa: F811
    """La relecture adverse de C0 à C3 (2026-11-22) : l'adresse de retour garde ``lu=`` ; le message de l'action est
    montré une fois. Recharger la page après un enregistrement réussi ne dit plus « la page a bougé » (sa propre
    version) ; créer une page sur un chemin pris dit qu'elle existe déjà ; renommer vers un chemin pris revient sur la
    page d'où l'on vient, pas sur celle qui porte ce chemin."""
    client, live, _ = world
    _, pid = _space(client, live)
    form = form_of(_page(client, pid, "&page=accueil.md&modifier=1"), "projects.doc_ecrire")
    sent = _post(client, form, "projects.doc_ecrire", text=HOME + "\nUne ligne.", word="")
    first = drawn(client, sent.headers["location"])
    assert words.SAVED.format(version=2, path="accueil.md") in first and "data-doc-editor" not in first
    again = drawn(client, sent.headers["location"])  # F5 : le message a été montré, ce n'est plus un retour
    assert "La page a bougé" not in again and "data-restore" not in again and "data-doc-editor" in again
    assert form_of(again, "projects.doc_ecrire")["base"] == ["2"]
    # une page nouvelle sur un chemin pris : elle existe déjà (pas « a bougé depuis la version 0 »)
    new = form_of(_page(client, pid, "&nouvelle=1"), "projects.doc_ecrire")
    new["_retour"] = [new["_retour"][0] + "&page=accueil.md"]  # ce que le script ajoute
    sent = _post(client, new, "projects.doc_ecrire", path="accueil.md", text="Une autre accueil.", word="")
    back = drawn(client, sent.headers["location"])
    assert words.EXISTS.format(path="accueil.md") in back and "Une page « accueil.md » existe déjà" in back
    assert "La page a bougé" not in back and "data-restore" in back
    assert form_of(back, "projects.doc_ecrire")["base"] == ["2"]  # enregistrer la remplacerait, en le sachant
    # renommer vers un chemin pris : refusé, on revient sur la page d'où l'on vient
    page = _page(client, pid, "&page=guide/installation.md")
    move = form_of(page, "projects.doc_deplacer")
    move["_retour"] = [move["_retour"][0] + "&page=accueil.md&de=guide%2Finstallation.md"]  # ce que le script pose
    sent = _post(client, move, "projects.doc_deplacer", to="accueil.md")
    back = drawn(client, sent.headers["location"])
    assert words.TAKEN.format(path="accueil.md") in back
    assert "<b>installation.md</b>" in back and "Deux commandes." in back and "Outils réseau" not in back.split(
        'class="pj-md pj-doc"', 1)[1].split("</article>", 1)[0]
    # passé, le retour suit le nouveau chemin
    move = form_of(_page(client, pid, "&page=guide/installation.md"), "projects.doc_deplacer")
    move["_retour"] = [move["_retour"][0] + "&page=guide%2Fmise-en-route.md&de=guide%2Finstallation.md"]
    sent = _post(client, move, "projects.doc_deplacer", to="guide/mise-en-route.md")
    back = drawn(client, sent.headers["location"])
    assert words.MOVED.format(to="guide/mise-en-route.md") in back and "<b>mise-en-route.md</b>" in back
