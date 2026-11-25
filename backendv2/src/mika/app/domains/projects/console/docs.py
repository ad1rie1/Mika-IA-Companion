"""La fiche d'un projet › Documentation, calquée sur l'écran Projets (ADR 0289, 0297) : ses sous-onglets en adresses
(``?vue=``) — Pages, Images, Décisions —, chacun dans ses zones.

- **Pages** : l'arborescence et la recherche à gauche ; la page au centre, rendue par le moteur (``doc_html``) — ses
  images servies par la console (``/admin/image/project/<n>``, le document que déclare la faculté), aucune image
  d'une autre adresse, aucun script, et seul un lien vers une autre page de l'espace s'ouvre (dans la console) ; son
  panneau : sa version, qui l'a écrite et par où, son sommaire, ses versions, ses images. Écrire une page
  (``modifier=1``, ``nouvelle=1``) ouvre l'éditeur de la console (``static/handmade/doc_editor.js`` sur un champ
  ordinaire : sans script, le champ suffit) ; l'historique (``version=<n>``) montre une version et en revient.
- **Images** : la grille, téléverser (``projects.doc_image``, le fichier par ``_fichier``), copier la référence,
  retirer.
- **Décisions** : les décisions techniques d'avant (``projects.decision_*``), une liste et le détail de l'une, comme une
  décision d'architecture.

**L'écriture** passe par l'action déclarée ``projects.doc_ecrire``, comme l'API (``app/domains/projects/api/docs.py::_write``) :
elle nomme la version lue (``base``) et se refuse si la page a bougé. Le retour de l'éditeur dit la version lue
(``lu``) : la page sait, par le message que la console garde pour elle (``UI.peek_flash``), si l'enregistrement est
passé ; refusé, l'éditeur revient avec le texte tapé (gardé par le navigateur le temps de l'envoi) et **ce n'est un
conflit que si la page a bougé** — elle en est alors à une autre version que celle lue (``frontendv2/…/docparts.ts::
movedOn``) : l'éditeur repart de la version actuelle, qu'il montre à côté. Une page créée sur un chemin pris le dit
(« existe déjà »). Ce n'est un retour que tant que le message n'a pas été montré : recharger la page ensuite n'est ni
un refus ni un conflit. Renommer vers un chemin pris revient, refusé, sur la page d'où l'on vient (``de``).
"""

from __future__ import annotations

import html
import posixpath
import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import quote

from markdown_it import MarkdownIt
from markupsafe import Markup, escape

from mika.app.domains.projects.console.zones import DONE, FAIL, WAIT, WORK, Scene, shown
from mika.contracts import projects as c
from mika.faculties.projects import docs
from mika.faculties.projects.faculty import DOC_IMAGES_MAX, DOC_PAGES_MAX, DOC_VERSIONS_KEPT, objective_at
from mika.faculties.projects.inspect import AUTHOR_FR, DECISION_FR, DECISION_PARAM, FORGOTTEN, OBJ_FR
from mika.faculties.projects.inspect_docs import who_wrote
from mika.inspector.ui import PREFIX, env
from mika.kernel.inspect import plural, size_fr

TAB = "documentation"
PAGES, IMAGES, DECISIONS = "", "images", "decisions"
BAR = ((PAGES, "Pages"), (IMAGES, "Images"), (DECISIONS, "Décisions"))
#: la page qui s'ouvre quand rien n'est choisi, si l'espace en a une
HOME_PAGES = ("accueil.md", "index.md", "readme.md")
#: une décision → sa couleur ; qui l'a posée, en mots (elle : son nom)
DECISION_TONES = {c.IN_FORCE: DONE, c.SUPERSEDED: WAIT, c.WITHDRAWN: WAIT}
#: les mots d'un objectif lié → sa couleur
OBJECTIVE_TONES = {c.OPEN: WORK, c.DONE: DONE, c.BLOCKED: FAIL, c.DROPPED: WAIT}
#: un extrait de recherche, au plus ; les résultats rendus
FOUND = 20
#: ce que l'aide « Écrire » de l'éditeur dit de la syntaxe, en lignes
MARKDOWN_HELP = (("# Titre, ## Sous-titre", "des titres"), ("**gras**, *italique*, `code`", "le texte"),
                 ("- un point, 1. une étape, - [ ] une tâche", "des listes"),
                 ("[texte](autre-page.md)", "un lien vers une autre page"),
                 ("![texte](images/nom.png)", "une image de la documentation"))

# ── Le rendu d'une page ───────────────────────────────────────────────────

#: le Markdown d'une page : CommonMark, ses tableaux et le barré ; **le HTML brut du texte reste du texte**
_MD = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])
_A = re.compile(r'<a href="([^"]*)"(?: title="[^"]*")?>(.*?)</a>', re.S)
_IMG = re.compile(r'<img src="([^"]*)" alt="([^"]*)"(?: title="[^"]*")? ?/?>')
_H = re.compile(r"<h([1-6])>(.*?)</h\1>", re.S)
_TAG = re.compile(r"<[^>]+>")
_STYLE = re.compile(r' style="[^"]*"')
_TASK = re.compile(r"<li>\[([ xX])\]\s")
_TABLE = re.compile(r"<table>(.*?)</table>", re.S)
_CELL = re.compile(r"<(th|td)>(.*?)</\1>", re.S)
_ROW = re.compile(r"<tr>(.*?)</tr>", re.S)


def image_url(project: int, name: str, at: int = 0) -> str:
    """Où la console sert une image de sa documentation (``inspect_files.DOC_IMAGE``). ``at`` : quand elle a été
    ajoutée — l'adresse change avec l'image, que le navigateur garde donc sans la redemander (``pages/subjects.py::
    image``)."""
    return f"{PREFIX}/image/project/{project}?fichier=" + quote(f"documentation:{docs.IMAGES_DIR}{name}", safe="") \
        + (f"&v={at}" if at else "")


def page_url(sc: Any, path: str, **more: Any) -> str:
    return sc.url(TAB, page=path, **more)


def _table(m: re.Match[str]) -> str:
    """Un tableau Markdown en grille de cases (la console veut une pagination sous toute ``<table>``) : ses colonnes
    comptées, son en-tête marqué ; ses alignements (des styles en ligne) tombent."""
    rows = _ROW.findall(m.group(1))
    width = max((len(_CELL.findall(r)) for r in rows), default=1)
    cells = []
    for r in rows:
        for tag, inner in _CELL.findall(r):
            role = "columnheader" if tag == "th" else "cell"
            cells.append(f'<div class="{"h" if tag == "th" else "d"}" role="{role}">{inner}</div>')
    return f'<div class="pj-doc-table c{min(width, 8)}" role="table">{"".join(cells)}</div>'


def doc_html(project: Any, text: str, folder: str, page_href: Any, pages: Iterable[str]
             ) -> tuple[Markup, list[dict[str, Any]]]:
    """Une page de documentation rendue par le moteur, et son sommaire. Le HTML du texte reste du texte ; une image
    ne se montre que si elle est dans sa documentation (``images/<nom>``), servie par la console ; un lien ne s'ouvre
    que vers une autre page de l'espace — dans la console (``page_href``) —, aucun autre : son adresse se lit au
    survol. Les titres gardent leur ordre et une ancre, un cran plus bas (la console a son titre principal)."""
    known = set(pages)
    kept = {i.name: i.at for i in project.docs.images}
    out = _MD.render(text or "")
    out = _STYLE.sub("", out)
    out = _TABLE.sub(_table, out)

    def image(m: re.Match[str]) -> str:
        src, alt = html.unescape(m.group(1)), m.group(2)
        name = src.removeprefix(docs.IMAGES_DIR) if src.startswith(docs.IMAGES_DIR) else ""
        if name in kept:
            return f'<img class="pj-doc-img" src="{escape(image_url(project.id, name, kept[name]))}" alt="{alt}" loading="lazy">'
        said = alt or str(escape(src))
        return f'<span class="pj-doc-noimg" title="Une image qui n\'est pas dans sa documentation">{said}</span>'

    def link(m: re.Match[str]) -> str:
        href, inner = html.unescape(m.group(1)), m.group(2)
        target = href.split("#", 1)[0]
        path = posixpath.normpath(posixpath.join(folder, target)) if target and "://" not in target \
            and not target.startswith(("/", "mailto:")) else ""
        if path in known:
            return f'<a href="{escape(page_href(path))}">{inner}</a>'
        return f'<span class="pj-md-a" title="{escape(href)}">{inner}</span>'

    out = _IMG.sub(image, out)
    out = _A.sub(link, out)
    out = _TASK.sub(lambda m: '<li class="tache">' + ("☑ " if m.group(1) != " " else "☐ "), out)
    toc: list[dict[str, Any]] = []

    def heading(m: re.Match[str]) -> str:
        level = int(m.group(1))
        anchor = f"doc-{len(toc) + 1}"
        toc.append({"level": level, "text": html.unescape(_TAG.sub("", m.group(2))), "anchor": anchor})
        shown = min(6, level + 1)  # la page de la console a son titre principal : « # » y est un titre de section
        return f'<h{shown} id="{anchor}">{m.group(2)}</h{shown}>'

    out = _H.sub(heading, out)
    return Markup(out), toc


# ── Ce qu'on en dit ───────────────────────────────────────────────────────


def _who(sc: Scene, x: Any) -> dict[str, Any]:
    """Qui a écrit une version ou ajouté une image, et par où, en mots de console ; ``her`` : elle."""
    said = who_wrote(sc.frame, x.author, x.by, x.via, getattr(x, "tool", ""))
    name, _, where = said.partition(", ")
    her = x.author == c.BY_SELF
    return {"name": sc.ui.her_name() if her else name, "where": where, "her": her,
            "initial": (sc.ui.her_name() if her else name)[:1].upper()}


def _bar(sc: Scene, view: str, counts: Mapping[str, int]) -> list[dict[str, Any]]:
    return [{"label": label, "on": k == view, "count": counts.get(k), "href": sc.url(TAB, vue=k)} for k, label in BAR]


def docs_page(sc: Scene) -> Markup | None:
    """L'onglet Documentation : sa barre (Pages, Images, Décisions, et l'espace en chiffres), puis la sous-vue."""
    p = sc.p
    if p is None:
        return None
    store = sc.ui.kernel.mind.store
    pages = docs.tree(store, p.id)
    view = sc.query.get("vue", "")
    view = view if view in (IMAGES, DECISIONS) else PAGES
    living = sum(1 for d in p.decisions if d.status == c.IN_FORCE)
    context: dict[str, Any] = {
        "view": view, "bar": _bar(sc, view, {PAGES: len(pages), IMAGES: len(p.docs.images), DECISIONS: living}),
        "space": f"{plural(len(pages), 'page', 'pages')} · {size_fr(sum(x.chars for x in pages))}",
        "her": sc.ui.her_name()}
    builders = {PAGES: pages_view, IMAGES: images_view, DECISIONS: decisions_view}
    context.update(builders[view](sc, pages))
    return Markup(env.get_template("handmade/projets/documentation.html").render(**context))


# ── Pages ─────────────────────────────────────────────────────────────────


def _tree(sc: Scene, pages: list[docs.Page], chosen: str) -> list[dict[str, Any]]:
    """L'arborescence : chaque dossier puis ses pages, dépliés, les dossiers d'abord."""
    by_folder: dict[str, list[docs.Page]] = {}
    for x in pages:
        by_folder.setdefault(x.path.rpartition("/")[0], []).append(x)
    folders = sorted({"/".join(x.path.split("/")[:i]) for x in pages for i in range(1, x.path.count("/") + 1)})
    out: list[dict[str, Any]] = []

    def walk(folder: str, depth: int) -> None:
        for sub in [f for f in folders if f.rpartition("/")[0] == folder]:
            out.append({"name": sub.rsplit("/", 1)[-1], "dir": True, "depth": depth, "path": sub})
            walk(sub, depth + 1)
        for x in sorted(by_folder.get(folder, []), key=lambda x: x.path):
            out.append({"name": x.path.rsplit("/", 1)[-1], "dir": False, "depth": depth, "path": x.path,
                        "title": x.title, "on": x.path == chosen, "href": page_url(sc, x.path)})

    walk("", 0)
    return out


def _versions(sc: Scene, path: str, current: int, chosen: int = 0) -> list[dict[str, Any]]:
    out = []
    for v in docs.versions(sc.ui.kernel.mind.store, sc.p.id, path):
        out.append({"n": v.n, "word": v.word, "restored": v.restored, "current": v.n == current,
                    "on": v.n == chosen, "who": _who(sc, v), "ago": sc.ago(v.at), "when": sc.when(v.at),
                    "href": page_url(sc, path, version=v.n)})
    return out


def _flash_tone(sc: Scene) -> str:
    """Le ton du retour de l'action qui vient d'être faite (« ok » : passée) ; vide : aucun."""
    got = sc.ui.peek_flash(sc.query.get("flash", ""))
    return got[0] if got else ""


def _editor(sc: Scene, x: docs.Page | None, text: str, base: int, *, path: str = "", folder: str = "",
            restore: bool = False, conflict: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """L'éditeur d'une page (``projects.doc_ecrire``) : le texte, un mot sur ce qui a changé, la version lue posée
    sans se montrer ; pour une page nouvelle, son chemin. Son retour revient à l'éditeur et dit la version lue."""
    p = sc.p
    new = x is None
    target = x.path if x is not None else path
    back = sc.url(TAB, page=target, modifier=1, lu=str(base)) if not new else sc.url(TAB, nouvelle=1, lu="0")
    form = sc.form("doc_ecrire", back, path=target or folder, base=str(base))
    if form is None:
        return None
    form = shown(form, *(("path",) if new else ()), "word", **({} if new else {"path": target}), base=str(base))
    upload = shown(sc.form("doc_image", sc.url(TAB, page=target, modifier=1, lu=str(base), brouillon=1)
                           if not new else sc.url(TAB, nouvelle=1, lu="0", brouillon=1)), "name")
    return {"form": form, "text": text, "new": new, "path": target, "base": base,
            "draft": f"mika-doc:{p.id}:{target if not new else ''}", "restore": restore, "conflict": conflict,
            "preview": f"{PREFIX}/apercu/project/{p.id}", "upload": {**upload, "multipart": True} if upload else None,
            "images": [{"name": i.name, "url": image_url(p.id, i.name, i.at), "ref": f"![{i.name.rsplit('.', 1)[0]}]"
                        f"({docs.IMAGES_DIR}{i.name})"} for i in sorted(p.docs.images, key=lambda i: -i.at)],
            "help": MARKDOWN_HELP, "limit": docs.PAGE_CHARS}


def pages_view(sc: Scene, pages: list[docs.Page]) -> dict[str, Any]:
    p, store, q = sc.p, sc.ui.kernel.mind.store, sc.query.get("q", "").strip()[:120]
    paths = [x.path for x in pages]
    wanted = sc.query.get("page", "")
    adding = bool(sc.query.get("nouvelle"))
    # le retour d'un geste de l'éditeur : seulement tant que la console garde son message — un rechargement de la
    # page (le message déjà montré) n'est plus un retour, et ne se lit ni comme un refus ni comme un conflit
    tone = _flash_tone(sc)
    returned = "lu" in sc.query and bool(tone)
    came = sc.query.get("de", "")
    if came in paths and tone and tone != "ok":  # renommer ou déplacer, refusé : on revient sur la page d'où l'on vient
        wanted = came
    chosen = wanted if wanted in paths else "" if adding or wanted else \
        next((x for x in paths if x.rsplit("/", 1)[-1] in HOME_PAGES), paths[0] if paths else "")
    can = sc.form("doc_ecrire") is not None
    out: dict[str, Any] = {
        "q": q, "base": sc.url(TAB).split("?", 1)[0], "tree": _tree(sc, pages, chosen), "found": None,
        "can_write": can, "new_href": sc.url(TAB, nouvelle=1), "home": sc.url(TAB), "adding": None,
        "lire": bool(wanted) or adding, "page": None, "missing": wanted if wanted and wanted not in paths else "",
        "limits": f"{DOC_PAGES_MAX} pages au plus, chacune gardant ses {DOC_VERSIONS_KEPT} dernières versions"}
    if q:
        out["found"] = [{"path": x.path, "title": x.title, "href": page_url(sc, x.path),
                         "excerpt": docs.excerpt(docs.text_of(store, x.seq) or "", q)}
                        for x in docs.found(store, p.id, q, FOUND)]
    folder = sc.query.get("dossier", "")
    if adding:
        x = docs.page(store, p.id, wanted) if wanted else None
        if x is None:  # une page nouvelle — ou son enregistrement refusé : l'éditeur revient, son texte gardé
            out["adding"] = _editor(sc, None, "", 0, folder=f"{folder}/" if folder else "",
                                    restore=returned and (tone != "ok" or bool(sc.query.get("brouillon"))))
            return out
        chosen = x.path
        if not returned or tone == "ok":  # créée : on la lit
            out.update(page=_page(sc, x, paths, clear=f"mika-doc:{p.id}:"), lire=True)
            return out
    if not chosen:
        return out
    x = docs.page(store, p.id, chosen)
    if x is None:
        return out
    if sc.query.get("modifier") or adding:
        read = int(sc.query.get("lu", "0") or 0) if sc.query.get("lu", "").isdecimal() else x.version
        draft = bool(sc.query.get("brouillon"))
        if returned and tone == "ok" and not draft:  # enregistrée : on la lit, le brouillon s'efface
            out["page"] = _page(sc, x, paths, clear=f"mika-doc:{p.id}:{x.path}")
            return out
        text = docs.text_of(store, x.seq) or ""
        conflict = None
        if returned and read != x.version:  # la page a bougé depuis la lecture : c'est un conflit
            html_now, _ = doc_html(p, text, x.path.rpartition("/")[0], lambda path: page_url(sc, path), paths)
            # une page « nouvelle » sur un chemin déjà pris (lue à la version 0) : elle existait déjà, elle n'a pas bougé
            conflict = {"version": x.version, "read": read, "who": _who(sc, x), "ago": sc.ago(x.at), "html": html_now,
                        "exists": adding and read == 0, "path": x.path}
        out["page"] = {**_page(sc, x, paths), "mode": "modifier", "editor": _editor(
            sc, x, text, x.version if conflict or not returned else read, restore=returned, conflict=conflict)}
        return out
    number = sc.query.get("version", "")
    if number.isdecimal():
        out["page"] = _version(sc, x, paths, int(number))
        return out
    out["page"] = _page(sc, x, paths)
    return out


def _page(sc: Scene, x: docs.Page, paths: list[str], *, clear: str = "") -> dict[str, Any]:
    """Une page à lire : son texte rendu et son sommaire, sa dernière modification, ses versions, ses images ; ses
    gestes (la modifier, la renommer ou la déplacer, la supprimer)."""
    p, store = sc.p, sc.ui.kernel.mind.store
    text = docs.text_of(store, x.seq)
    body, toc = doc_html(p, text or "", x.path.rpartition("/")[0], lambda path: page_url(sc, path), paths)
    versions = _versions(sc, x.path, x.version)
    last = next((v for v in versions if v["current"]), None)
    home = sc.url(TAB)
    move = shown(sc.form("doc_deplacer", home, path=x.path, to=x.path), "to", path=x.path)
    drop = shown(sc.form("doc_supprimer", home, path=x.path), path=x.path)
    return {
        "path": x.path, "parts": x.path.split("/"), "title": x.title, "version": x.version, "html": body,
        "toc": toc, "forgotten": text is None, "last": last, "versions": versions, "chars": size_fr(x.chars),
        "who": _who(sc, x), "ago": sc.ago(x.at), "when": sc.when(x.at), "created": sc.when(x.created_at),
        "images": [{"name": n, "url": image_url(p.id, n, i.at), "href": sc.url(TAB, vue=IMAGES, image=n)}
                   for n in x.images if (i := docs.image_at(p.docs, n)) is not None],
        "edit_href": page_url(sc, x.path, modifier=1), "read_href": page_url(sc, x.path),
        "history_href": page_url(sc, x.path, version=x.version), "mode": "lire", "saved": clear,
        "move": move, "drop": {**drop, "confirm": f"Supprimer « {x.path} » et ses versions ?"} if drop else None,
        "editor": None, "shown_version": None}


def _version(sc: Scene, x: docs.Page, paths: list[str], n: int) -> dict[str, Any]:
    """Une version de la page, et le retour à elle quand ce n'est pas l'actuelle : une version de plus, qui reprend
    son texte (``projects.doc_ecrire``, ``restored``)."""
    p, store = sc.p, sc.ui.kernel.mind.store
    out = _page(sc, x, paths)
    v = docs.version(store, p.id, x.path, n)
    out["versions"] = _versions(sc, x.path, x.version, n)
    out["mode"] = "historique"
    if v is None:
        out["shown_version"] = {"n": n, "gone": True}
        return out
    text = docs.text_of(store, v.seq)
    body, _ = doc_html(p, text or "", x.path.rpartition("/")[0], lambda path: page_url(sc, path), paths)
    back = page_url(sc, x.path)
    form = sc.form("doc_ecrire", back, path=x.path) if text is not None and n != x.version else None
    restore = shown(form, path=x.path, text=text or "", word=f"Retour à la version {n}", base=str(x.version))
    if restore is not None:  # la version reprise : un champ caché de l'action, posé comme l'API le pose (fixé)
        restore["fixed"] = [*(restore.get("fixed") or ()), ("restored", str(n))]
    out["html"] = body
    out["shown_version"] = {"n": n, "word": v.word, "who": _who(sc, v), "when": sc.when(v.at), "ago": sc.ago(v.at),
                            "current": n == x.version, "forgotten": text is None, "restore": restore}
    return out


# ── Images ────────────────────────────────────────────────────────────────


def images_view(sc: Scene, pages: list[docs.Page]) -> dict[str, Any]:
    p = sc.p
    used: dict[str, list[docs.Page]] = {}
    for x in pages:
        for name in x.images:
            used.setdefault(name, []).append(x)
    wanted = sc.query.get("image", "")
    images = sorted(p.docs.images, key=lambda i: -i.at)
    chosen = next((i for i in images if i.name == wanted), images[0] if images else None)
    back = sc.url(TAB, vue=IMAGES)
    upload = shown(sc.form("doc_image", back), "name")
    cards = [{"name": i.name, "url": image_url(p.id, i.name, i.at), "size": size_fr(i.size), "on": i is chosen,
              "used": len(used.get(i.name, [])), "href": sc.url(TAB, vue=IMAGES, image=i.name)} for i in images]
    out: dict[str, Any] = {"cards": cards, "upload": {**upload, "multipart": True} if upload else None,
                           "lire": bool(wanted), "image": None, "home": back,
                           "room": f"{plural(len(images), 'image', 'images')} sur {DOC_IMAGES_MAX}, "
                                   f"{size_fr(docs.space_used(p.docs))} sur {size_fr(docs.SPACE_BYTES)}"}
    if chosen is None:
        return out
    drop = sc.form("doc_image_retirer", back, name=chosen.name)
    cited = used.get(chosen.name, [])
    out["image"] = {
        "name": chosen.name, "url": image_url(p.id, chosen.name, chosen.at), "size": size_fr(chosen.size),
        "mime": chosen.mime or docs.mime_of(chosen.name), "who": _who(sc, chosen), "when": sc.when(chosen.at),
        "ago": sc.ago(chosen.at), "ref": f"![{chosen.name.rsplit('.', 1)[0]}]({docs.IMAGES_DIR}{chosen.name})",
        "cited": [{"path": x.path, "title": x.title, "href": page_url(sc, x.path)} for x in cited],
        "drop": {**shown(drop, name=chosen.name),
                 "confirm": f"Retirer « {chosen.name} » ? Ses octets s'effacent"
                            + (f" ; {plural(len(cited), 'page la cite', 'pages la citent')} encore." if cited
                               else ".")} if drop else None}
    return out


# ── Décisions ─────────────────────────────────────────────────────────────


def decisions_view(sc: Scene, pages: list[docs.Page]) -> dict[str, Any]:
    """Les décisions techniques : la liste (son filtre : en vigueur, remplacées, retirées, toutes) et le détail de
    l'une — ce qui est choisi, le contexte, pourquoi ; les options écartées ; ce qu'elle remplace et ce qui l'a
    remplacée, l'objectif pendant lequel elle a été prise ; la consigner, la modifier, la remplacer, la retirer, la
    remettre en vigueur. Les gestes sont ceux de la faculté (``projects.decision_*``)."""
    p = sc.p
    wanted = sc.query.get(DECISION_PARAM.name) or DECISION_PARAM.default
    shown_ = [d for d in reversed(p.decisions) if wanted == "toutes" or d.status == wanted]
    words = sc.texts(r for d in p.decisions for r in (d.title_ref, d.choice_ref, d.context_ref, d.options_ref,
                                                      d.reason_ref))
    number = sc.query.get("decision", "")
    chosen = next((d for d in p.decisions if number.isdecimal() and d.id == int(number)), None) \
        if number else (shown_[0] if shown_ else None)
    filters = [{"text": label[:1].upper() + label[1:], "on": value == wanted,
                "count": sum(1 for d in p.decisions if value == "toutes" or d.status == value),
                "href": sc.url(TAB, vue=DECISIONS, statut=value if value != DECISION_PARAM.default else "")}
               for value, label in DECISION_PARAM.choices]
    keep = {"vue": DECISIONS, "statut": wanted if wanted != DECISION_PARAM.default else ""}
    rows = [{"n": d.id, "title": words.get(d.title_ref, FORGOTTEN), "state": DECISION_FR.get(d.status, d.status),
             "tone": DECISION_TONES.get(d.status, WAIT), "ago": sc.age(d.at), "on": chosen is not None and d is chosen,
             "href": sc.url(TAB, **keep, decision=d.id)} for d in shown_]
    adding = bool(sc.query.get("nouvelle"))
    add = shown(sc.form("decision_ajouter", sc.url(TAB, vue=DECISIONS)), "title", "choice", "reason", "context",
                "options")
    out: dict[str, Any] = {"rows": rows, "filters": filters, "adding": add if adding else None,
                           "can_add": add is not None, "add_href": sc.url(TAB, vue=DECISIONS, nouvelle=1),
                           "home": sc.url(TAB, **keep), "lire": bool(number) or adding, "decision": None}
    if chosen is None or adding:
        return out
    d = chosen
    back = sc.url(TAB, **keep, decision=d.id)
    texts = {k: words.get(ref, "") for k, ref in (("title", d.title_ref), ("choice", d.choice_ref),
                                                  ("context", d.context_ref), ("options", d.options_ref),
                                                  ("reason", d.reason_ref)) if ref}
    o = objective_at(p, d.objective) if d.objective else None
    o_words = sc.texts([o.text_ref]) if o is not None else {}
    replaced = next((x for x in p.decisions if x.id == d.replaces), None) if d.replaces else None
    by = next((x for x in p.decisions if x.id == d.replaced_by), None) if d.replaced_by else None
    live = d.status != c.SUPERSEDED
    edit = shown(sc.form("decision_modifier", back, decision=str(d.id), **texts), "title", "choice", "reason",
                 "context", "options", decision=str(d.id)) if live else None
    replace = shown(sc.form("decision_ajouter", sc.url(TAB, vue=DECISIONS), title=texts.get("title", ""),
                            replaces=str(d.id)), "title", "choice", "reason", "context", "options",
                    replaces=str(d.id)) if d.status == c.IN_FORCE else None
    target = c.WITHDRAWN if d.status == c.IN_FORCE else c.IN_FORCE
    status = shown(sc.form("decision_statut", back, decision=str(d.id), status=target), decision=str(d.id),
                   status=target) if live else None
    mode = sc.query.get("geste", "")

    def linked(x: Any) -> dict[str, Any] | None:
        return None if x is None else {"n": x.id, "title": words.get(x.title_ref, FORGOTTEN),
                                       "state": DECISION_FR.get(x.status, x.status),
                                       "tone": DECISION_TONES.get(x.status, WAIT), "href": sc.url(TAB, vue=DECISIONS,
                                                                                                 statut="toutes",
                                                                                                 decision=x.id)}

    out["decision"] = {
        "n": d.id, "title": texts.get("title", FORGOTTEN), "choice": texts.get("choice", ""),
        "context": texts.get("context", ""), "reason": texts.get("reason", ""), "options": texts.get("options", ""),
        "state": DECISION_FR.get(d.status, d.status), "tone": DECISION_TONES.get(d.status, WAIT),
        "by": sc.ui.her_name() if d.author in ("self", c.BY_SELF) else AUTHOR_FR.get(d.author, d.author),
        "her": d.author in ("self", c.BY_SELF), "when": sc.when(d.at), "ago": sc.ago(d.at),
        "replaces": linked(replaced), "replaced_by": linked(by),
        "objective": {"n": o.id, "text": o_words.get(o.text_ref, FORGOTTEN), "state": OBJ_FR.get(o.status, o.status),
                      "tone": OBJECTIVE_TONES.get(o.status, WAIT), "href": sc.url("objectifs", objectif=o.id)}
        if o is not None else None,
        "edit": edit if mode == "modifier" else None, "edit_href": sc.url(TAB, **keep, decision=d.id,
                                                                           geste="modifier") if edit else "",
        "replace": replace if mode == "remplacer" else None,
        "replace_href": sc.url(TAB, **keep, decision=d.id, geste="remplacer") if replace else "",
        "status": status, "status_label": "Retirer la décision" if target == c.WITHDRAWN else "Remettre en vigueur",
        "withdraw": target == c.WITHDRAWN, "back": back}
    return out
