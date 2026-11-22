"""Projet › Code (ADR 0288, 0297), calqué sur l'écran Projets du client web : ses sous-onglets — Fichiers, Commits,
Pull requests, Branches, Issues, CI — sont des adresses (``?vue=``), chacun dans les trois zones quand il a une liste et
un détail (``code.html``, ``_code.html``, ``projets_code.css``).

- **Fichiers** : le choix de la branche (un menu de liens), l'arborescence ouverte jusqu'au chemin demandé, le fichier en
  chasse fixe avec ses numéros de ligne — un Markdown rendu, ou sa source (``md=source``) —, son dernier commit et son
  historique ; un fichier binaire, trop gros ou caché le dit. « Déposer un fichier » s'ouvre dans le contenu.
- **Commits** : la ligne de temps par jour, le filtre par branche, la pagination ; le commit choisi, son message, ses
  fichiers changés et le diff en couleurs, unifié ou côte à côte (``diff=cote``).
- **Pull requests** : la liste et ses états (du journal) ; la choisie en volets — Résumé (ses jalons et leurs preuves),
  Commits, Fichiers, Échanges (de quoi y répondre), « Modifier » — et son panneau : sa fusion, sa relecture, ses
  vérifications une à une, ses conflits, sa branche, ce qui lui est lié. **Fusionner** ouvre une confirmation qui dit
  ce qui va être fusionné et nomme le commit de tête que la page vient de lire ; le formulaire est l'action
  ``projects.fusionner`` (la même règle et le même chemin que l'API : ADR 0288, 0292).
- **Branches** : le tableau sur toute la largeur, et le panneau de la branche choisie.
- **Issues** : la liste, l'issue en volets (Description, Échanges), son panneau — son état chez l'hôte, le ticket lié et
  son étape, l'accepter ou l'écarter quand il est proposé (``projects.ticket_trancher``).
- **CI** : les vérifications suivies par commit, le détail une à une, la fin du journal d'un échec.

**Ce qu'il lit.** Les blocs de la vue ``git`` de la faculté (``inspect_code.py``), tels qu'elle les déclare (``Got.raw``) :
ce que lit l'atelier, et ce que l'hôte est seul à savoir, par sa lecture gardée et bornée. Ce que le journal sait d'une
pull request — son étape, ce qui retient sa fusion, sa relecture, ses jalons — par les fonctions de la faculté que lit
aussi l'API par personne (``pull_stage``, ``merge.blocked``…), déclarées dans ``tests/protocol/test_drawn_fiches.py``.
**Tout texte de l'hôte, tout contenu de fichier et tout diff** est rendu en texte brut, échappé ; ce qui vient
d'ailleurs se présente comme tel. Un Markdown rendu ne charge aucune image et n'ouvre aucun lien.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

from markupsafe import Markup

from mika.app.handmade.subjects.project_goals import milestone
from mika.app.handmade.subjects.project_goals import refs as goal_refs
from mika.app.handmade.subjects.project_tickets import ticket_tone
from mika.app.handmade.subjects.project_zones import (
    DONE,
    FAIL,
    OBJECTIVE_TONES,
    WAIT,
    WORK,
    YOU,
    Scene,
    markdown,
    pull_card,
    pull_href,
    shown,
)
from mika.app.handmade.tabs import Got, raw_rows
from mika.app.handmade.tabs.decisions import by_day
from mika.contracts import projects as c
from mika.faculties.projects import inspect_code as code
from mika.faculties.projects import merge
from mika.faculties.projects.faculty import objective_at
from mika.faculties.projects.inspect import FORGOTTEN, OBJ_FR
from mika.faculties.projects.inspect_code import (
    diff_rows,
    issue_ticket,
    objective_on,
    pull_named,
    pull_order,
    pull_stage,
    ticket_of,
)
from mika.faculties.projects.inspect_merge import BLOCK_WORDS, MOVED_THERE, REFUSED_WORDS
from mika.faculties.projects.inspect_reviews import REVIEW_WORDS
from mika.faculties.projects.managing import writable
from mika.faculties.projects.tracker import status_words
from mika.inspector import render
from mika.inspector.ui import env
from mika.kernel.inspect import Code, Fields, Note, Pager, Ref, Section, Table, Text, When, plural
from mika.ports.workshop import (
    CHECKS_FAILED,
    CHECKS_PASSED,
    CHECKS_PENDING,
    LINE_ADDED,
    LINE_REMOVED,
    PULL_OPEN,
)

#: ses sous-onglets : (la clé de l'adresse, son libellé, le fait de l'en-tête qui le compte)
BAR = ((code.FILES, "Fichiers", ""), (code.COMMITS, "Commits", "commits"),
       (code.PULLS, "Pull requests", "pull requests ouvertes"), (code.BRANCHES, "Branches", "branches"),
       (code.ISSUES, "Issues", "issues ouvertes"), (code.CI, "CI", "vérifications en échec"))
#: l'étape d'une pull request → sa couleur
STAGE_TONES = {code.PROPOSED: YOU, code.OPEN: WORK, code.READY: YOU, code.MERGED: DONE, code.CLOSED: WAIT}
#: l'état de vérifications (``CHECKS_*`` ou ses mots) → sa couleur, son icône
CHECK_TONES = {CHECKS_PASSED: DONE, CHECKS_FAILED: FAIL, CHECKS_PENDING: WORK}
CHECK_ICONS = {DONE: "check", FAIL: "x", WORK: "refresh", WAIT: "clock"}
WORD_TONES = {"passée": DONE, "en échec": FAIL, "en cours": WORK, "aucune vérification": WAIT}
#: un fichier Markdown se rend ; sinon, il se lit en chasse fixe
MARKDOWN = (".md", ".markdown", ".mdown")
LANGUAGES = {"py": "Python", "md": "Markdown", "markdown": "Markdown", "toml": "TOML", "json": "JSON",
             "js": "JavaScript", "mjs": "JavaScript", "cjs": "JavaScript", "ts": "TypeScript", "tsx": "TypeScript",
             "html": "HTML", "css": "CSS", "sh": "Shell", "bash": "Shell", "yml": "YAML", "yaml": "YAML",
             "txt": "Texte", "csv": "CSV", "rs": "Rust", "go": "Go", "java": "Java", "kt": "Kotlin", "c": "C",
             "h": "C", "cpp": "C++", "sql": "SQL", "xml": "XML", "ini": "INI", "cfg": "INI", "lock": "Verrou"}
#: la profondeur d'une entrée de l'arborescence, au plus (au-delà, son retrait ne grandit plus)
DEPTH_MAX = 8
#: une ligne sans lien d'un Markdown rendu : ``readable_markdown`` ne garde que des liens http(s) et mailto ; un
#: fichier du dépôt n'ouvre aucune adresse qu'il contient
_LINK_OPEN = re.compile(r'<a href="[^"]*"(?: target="_blank")? rel="noopener noreferrer nofollow">')
_PLUS = re.compile(r"^\d+$")
#: son dépôt distant en mots, sans son protocole ni « .git » (la vue le dit ainsi)
_REMOTE = re.compile(r"^https?://|(?:\.git)?/?$")


# ── Les blocs de la vue, tels qu'elle les déclare ─────────────────────────


def _walk(items: Iterable[Any]) -> Iterator[Any]:
    for b in items:
        yield b
        inner = getattr(b, "items", None)
        if isinstance(inner, tuple | list):
            yield from _walk(inner)


class Raw:
    """Les blocs déclarés de la section « Code » (l'onglet réunit aussi « Fichiers ») : par sorte et par titre."""

    def __init__(self, got: Got) -> None:
        section = next((b for b in got.raw if isinstance(b, Section) and b.title == "Code"), None)
        self.items = list(section.items) if section is not None else list(got.raw)
        self.env = got.env

    def first(self, kind: type, title: str, *, prefix: bool = False) -> Any:
        return next((b for b in _walk(self.items) if isinstance(b, kind) and (
            b.title.startswith(title) if prefix else b.title == title)), None)

    def fields(self, title: str) -> dict[str, Any]:
        found = self.first(Fields, title)
        return dict(found.pairs) if found is not None else {}

    def table(self, title: str) -> Table | None:
        return self.first(Table, title)

    def rows(self, title: str) -> list[tuple[Any, dict[str, Any]]]:
        t = self.table(title)
        return list(raw_rows(t)) if t is not None else []

    def code(self, title: str, *, prefix: bool = False) -> Code | None:
        return self.first(Code, title, prefix=prefix)

    def codes(self, prefix: str) -> list[Code]:
        return [b for b in _walk(self.items) if isinstance(b, Code) and b.title.startswith(prefix)]

    def notes(self) -> list[dict[str, str]]:
        return [{"text": b.text, "tone": b.tone} for b in self.items if isinstance(b, Note)]

    def href(self, ref: Any) -> str:
        return render.href(ref, self.env) if isinstance(ref, Ref) else ""


def said(cell: Any) -> str:
    """Les mots d'une cellule déclarée."""
    if cell is None:
        return ""
    if isinstance(cell, Ref | Text):
        return cell.text
    if isinstance(cell, When):
        return ""
    return str(cell)


def number(cell: Any) -> int:
    return cell if isinstance(cell, int) and not isinstance(cell, bool) else int(cell) if \
        isinstance(cell, str) and _PLUS.match(cell) else 0


def instant(cell: Any) -> int:
    return cell.at if isinstance(cell, When) else 0


def param(ref: Any, name: str) -> str:
    return dict(ref.params).get(name, "") if isinstance(ref, Ref) else ""


# ── Le dessin commun : un fichier, un diff, un commit ─────────────────────


def language(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return LANGUAGES.get(name.rsplit(".", 1)[-1].lower(), "Texte") if "." in name else "Texte"


def rendered(text: str) -> Markup:
    """Un Markdown du dépôt, rendu (``readable_markdown`` : le HTML brut reste du texte, une image se réduit à son
    texte) et sans un lien qui s'ouvre : un fichier du dépôt est une donnée."""
    html = str(markdown(text))
    return Markup(_LINK_OPEN.sub('<span class="pj-md-a">', html).replace("</a>", "</span>"))


def source(text: str) -> list[dict[str, Any]]:
    """Un texte en lignes numérotées (une dernière ligne vide ne se compte pas)."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [{"n": i, "text": line} for i, line in enumerate(lines, start=1)]


def _pairs(rows: list[code.DiffRow]) -> list[dict[str, Any]]:
    """Un passage côte à côte : les retraits face aux ajouts qui les suivent, le contexte des deux côtés."""
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(rows):
        r = rows[i]
        if r.kind == "@":
            out.append({"hunk": r.text})
            i += 1
            continue
        if r.kind not in (LINE_ADDED, LINE_REMOVED):
            out.append({"l": r, "r": r})
            i += 1
            continue
        dels, adds = [], []
        while i < len(rows) and rows[i].kind == LINE_REMOVED:
            dels.append(rows[i])
            i += 1
        while i < len(rows) and rows[i].kind == LINE_ADDED:
            adds.append(rows[i])
            i += 1
        out += [{"l": dels[k] if k < len(dels) else None, "r": adds[k] if k < len(adds) else None}
                for k in range(max(len(dels), len(adds)))]
    return out


def diffs(raw: Raw, side_by_side: bool) -> dict[str, Any]:
    """Les fichiers changés (leurs comptes, ce qu'ils sont devenus) et le diff de chacun, unifié ou côte à côte."""
    texts = {b.title[len(code.DIFF_TITLE):]: b.text for b in raw.codes(code.DIFF_TITLE)}
    files = []
    for i, (_row, cells) in enumerate(raw.rows(code.CHANGED_TITLE)):
        path = said(cells.get("chemin"))
        rows = diff_rows(texts.get(path, ""))
        why = said(cells.get("sans passages"))
        files.append({"i": i, "path": path, "dir": posixpath.dirname(path), "name": posixpath.basename(path),
                      "status": said(cells.get("devenu")), "plus": number(cells.get("ajoutées")),
                      "minus": number(cells.get("retirées")), "why": "" if why in ("", "—") else why,
                      "rows": rows if not side_by_side else [], "pairs": _pairs(rows) if side_by_side else []})
    return {"files": files, "plus": sum(f["plus"] for f in files), "minus": sum(f["minus"] for f in files),
            "cut": any(n["text"] == code.DIFF_CUT for n in raw.notes()), "side": side_by_side,
            "groups": _groups(files)}


def _groups(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Les fichiers changés rangés par dossier, pour le sommaire du panneau."""
    out: dict[str, list[dict[str, Any]]] = {}
    for f in files:
        out.setdefault(f["dir"], []).append(f)
    return [{"dir": d, "files": fs} for d, fs in sorted(out.items())]


def commits(sc: Scene, raw: Raw, title: str, *, ref: str = "", chosen: str = "",
            keep: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Les commits d'une liste déclarée, groupés par jour : message, empreinte, branche, objectif, comptes. ``keep`` :
    ce que le lien d'un commit garde de l'adresse (sa page dans la liste)."""
    items = []
    for _row, cells in raw.rows(title):
        link = cells.get("commit")
        sha = param(link, "sha")
        obj = said(cells.get("objectif"))
        items.append({
            "sha": sha, "short": sha[:7], "title": said(cells.get("message")), "at": instant(cells.get("quand")),
            "ago": sc.ago(instant(cells.get("quand"))), "when": sc.when(instant(cells.get("quand"))),
            "author": said(cells.get("auteur")), "branch": said(cells.get("branche")).strip("—"),
            "files": number(cells.get("fichiers")), "plus": number(cells.get("ajoutées")),
            "minus": number(cells.get("retirées")), "outside": said(cells.get("signé")) == "ailleurs",
            "merge": said(cells.get("fusion")) == "oui", "objective": obj.split(" · ", 1)[0].removeprefix("n° ") if obj != "—" else "",
            "on": bool(chosen) and sha.startswith(chosen),
            "href": sc.url("git", vue=code.COMMITS, ref=ref, sha=sha, **(keep or {}))})
    return items


def linked_objective(sc: Scene, o: Any, said_: Mapping[str, str]) -> dict[str, Any] | None:
    if o is None:
        return None
    return {"n": o.id, "title": said_.get(o.text_ref, FORGOTTEN), "tone": OBJECTIVE_TONES.get(o.status, WAIT),
            "state": OBJ_FR.get(o.status, ""), "href": sc.url("objectifs", objectif=o.id)}


def linked_ticket(sc: Scene, item: Any, said_: Mapping[str, str]) -> dict[str, Any] | None:
    if item is None:
        return None
    return {"n": item.number, "title": said_.get(item.title_ref, FORGOTTEN), "tone": ticket_tone(item),
            "state": status_words(c.TICKETS, item.status), "href": sc.url("tickets", element=f"#{item.number}")}


def _pull_href(sc: Scene, o: Any, anchor: str = "") -> str:
    return pull_href(sc.key, o, anchor)


def card(sc: Scene, o: Any) -> dict[str, Any] | None:
    """La pull request d'un objectif avec son statut (``pull_card``), au titre de son objectif, comme sa liste."""
    found = pull_card(sc.p, o, sc.now, _pull_href(sc, o)) if o is not None else None
    if found is None:
        return None
    return {**found, "title": sc.texts([o.text_ref]).get(o.text_ref) or found["title"]}


def linked(sc: Scene, o: Any) -> dict[str, Any]:
    """Ce qui est lié à un commit, une branche, des vérifications : l'objectif, son ticket, sa pull request."""
    item = ticket_of(sc.p, o)
    words = sc.texts([o.text_ref] + ([item.title_ref] if item is not None else [])) if o is not None else {}
    return {"objective": linked_objective(sc, o, words), "ticket": linked_ticket(sc, item, words),
            "pull": card(sc, o)}


# ── La page ───────────────────────────────────────────────────────────────


def code_page(sc: Scene, got: Got, legacy: Markup | None = None) -> Markup | None:
    """L'onglet Code : sa barre de sous-onglets, puis la sous-vue demandée — ou, pour « l'atelier face au distant »
    (``vue=distant``), le dessin de l'onglet Dépôt d'avant (``legacy``, ``project_git.py``) sous la même barre."""
    if sc.p is None:
        return None
    raw = Raw(got)
    head = raw.fields(code.REPO_TITLE)
    if not head and legacy is None:
        return None
    view = said(head.get("vue")) or code.FILES if head else code.REMOTE
    remote = head.get("dépôt distant")
    bar = [{"key": k, "label": label, "count": number(head.get(fact)) if fact and head else None, "on": k == view,
            "href": sc.url("git", vue=k if k != code.FILES else "")} for k, label, fact in BAR]
    seen = instant(head.get("lu chez l'hôte"))
    context: dict[str, Any] = {
        "view": view, "bar": bar, "notes": raw.notes(), "her": sc.ui.her_name(),
        "remote": {"text": said(remote) if isinstance(remote, Ref) else _REMOTE.sub("", sc.p.remote),
                   "href": sc.url("git", vue=code.REMOTE),
                   # « relire » : le lien de la vue — ce qu'elle ouvre, et l'instant de cette page (une fois)
                   "seen": sc.ago(seen), "fresh": raw.href(head.get("relire"))}}
    builders = {code.FILES: files_view, code.COMMITS: commits_view, code.PULLS: pulls_view,
                code.BRANCHES: branches_view, code.ISSUES: issues_view, code.CI: checks_view}
    if legacy is not None:
        context["legacy"] = legacy
    else:
        context.update(builders.get(view, files_view)(sc, raw, head))
    return Markup(env.get_template("handmade/projets/code.html").render(**context))


# ── Fichiers ──────────────────────────────────────────────────────────────


def files_view(sc: Scene, raw: Raw, head: Mapping[str, Any]) -> dict[str, Any]:
    tree = raw.table(code.TREE_TITLE)
    info = raw.fields(code.FILE_TITLE)
    ref = said(info.get("branche")) or sc.query.get("ref") or "main"
    names = said(head.get("ses branches")).split()
    adding = bool(sc.query.get("deposer"))
    back = sc.url("git", ref=sc.query.get("ref", ""), chemin=sc.query.get("chemin", ""))
    deposit = shown(sc.form("deposer", sc.url("git")), "file", "folder", "note", "replace")
    out: dict[str, Any] = {
        "norepo": tree is None, "ref": ref, "lire": bool(sc.query.get("chemin")) or adding,
        "branches": [{"name": n, "on": n == ref, "href": sc.url("git", ref=n)} for n in names],
        "tree": [], "file": None, "adding": deposit if adding else None, "can_add": deposit is not None,
        "add_href": sc.url("git", ref=sc.query.get("ref", ""), deposer=1), "home": back}
    if tree is None:  # pas encore de dépôt : la page le dit en grand, sans le redire en bandeau
        out["notes"] = [n for n in raw.notes() if not n["text"].startswith("Pas encore de dépôt")]
    for _row, cells in raw.rows(code.TREE_TITLE):
        name = cells.get("nom")
        kind = said(cells.get("sorte"))
        out["tree"].append({"name": said(name), "href": raw.href(name), "kind": kind, "dir": kind == "dossier",
                            "hidden": kind == "caché", "open": said(cells.get("ouvert")) == "ouvert",
                            "depth": min(DEPTH_MAX, number(cells.get("niveau"))),
                            "on": param(name, "chemin") == said(info.get("chemin")) and bool(info) and not adding})
    if info:
        path = said(info.get("chemin"))
        text = raw.code(code.SOURCE_TITLE)
        md = path.lower().endswith(MARKDOWN) and text is not None
        as_source = sc.query.get("md") == "source"
        history = commits(sc, raw, code.HISTORY_TITLE, ref=ref)
        why = said(info.get("pourquoi rien"))
        out["file"] = {
            "path": path, "parts": path.split("/"), "home": said(info.get("page d'accueil")) == "oui",
            "lines": number(info.get("lignes")), "size": said(info.get("poids")), "md": md, "source": as_source,
            "html": rendered(text.text) if md and not as_source and text is not None else None,
            "src": source(text.text) if text is not None and (not md or as_source) else [],
            "why": "" if why in ("", "—") else why, "kind": said(info.get("sorte")),
            "language": language(path) if text is not None else said(info.get("sorte")),
            "url": raw.href(info.get("chez l'hôte")), "download": raw.href(info.get("télécharger")),
            "last": history[0] if history else None,
            "history": history[1:], "total": len(history),
            "md_links": {"rendu": sc.url("git", ref=sc.query.get("ref", ""), chemin=sc.query.get("chemin", "")),
                         "source": sc.url("git", ref=sc.query.get("ref", ""), chemin=sc.query.get("chemin", ""),
                                          md="source")}}
    return out


# ── Commits ───────────────────────────────────────────────────────────────


def _pages(sc: Scene, table: Table | None, **keep: Any) -> dict[str, str] | None:
    """Les liens « plus récents » et « plus anciens » d'une liste paginée par numéro."""
    pager = table.pager if table is not None else None
    if pager is None or pager.pages <= 1:
        return None
    url = lambda n: sc.url("git", **keep, **({pager.param: n} if n > 1 else {}))  # noqa: E731
    return {"newer": url(pager.number - 1) if pager.number > 1 else "",
            "older": url(pager.number + 1) if pager.number < pager.pages else "",
            "said": f"page {pager.number} sur {pager.pages}"}


def commits_view(sc: Scene, raw: Raw, head: Mapping[str, Any]) -> dict[str, Any]:
    ref = sc.query.get("ref", "")
    names = said(head.get("ses branches")).split()
    ref = ref if ref in names else ""
    info = raw.fields(code.COMMIT_TITLE)
    sha = said(info.get("commit"))
    table = raw.table(code.COMMITS_TITLE)
    # choisir un commit garde sa page dans la liste, et la liste se lit par jour, du plus récent : l'ordre de l'histoire
    # (une branche après l'autre) peut redire un jour plus bas, ses en-têtes suivent donc les dates
    pager = table.pager if table is not None else None
    page = {pager.param: pager.number} if pager is not None and pager.number > 1 else {}
    items = sorted(commits(sc, raw, code.COMMITS_TITLE, ref=ref, chosen=sha, keep=page), key=lambda x: -x["at"])
    side = sc.query.get("diff") == "cote"
    keep = {"vue": code.COMMITS, "ref": ref, "sha": sha, **page}
    out: dict[str, Any] = {
        "ref": ref, "lire": bool(sc.query.get("sha") or sc.query.get("commit")),
        "branches": [{"name": "", "label": "Toutes les branches", "on": not ref,
                      "href": sc.url("git", vue=code.COMMITS)}] +
                    [{"name": n, "label": n, "on": n == ref, "href": sc.url("git", vue=code.COMMITS, ref=n)}
                     for n in names],
        "total": number(head.get("commits")) if not ref else (table.pager.total if table and table.pager else 0),
        "days": by_day_items(sc, items), "pages": _pages(sc, table, vue=code.COMMITS, ref=ref), "commit": None}
    if not info:
        return out
    o = objective_at(sc.p, number(info.get("objectif"))) if number(info.get("objectif")) else None
    message = raw.code(code.MESSAGE_TITLE)
    out["commit"] = {
        "sha": sha, "short": sha[:7], "title": said(info.get("titre")), "author": said(info.get("auteur")),
        "outside": said(info.get("signé")) == "ailleurs", "merge": said(info.get("fusion")) == "oui",
        "at": sc.when(instant(info.get("quand"))), "ago": sc.ago(instant(info.get("quand"))),
        "branch": said(info.get("branche")).strip("—"), "url": raw.href(info.get("chez l'hôte")),
        "message": message.text if message is not None else "", "linked": linked(sc, o),
        "diff": diffs(raw, side), "toggle": {"unifie": sc.url("git", **keep), "cote": sc.url("git", **keep,
                                                                                               diff="cote")}}
    return out


def by_day_items(sc: Scene, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Des commits par jour (« Aujourd'hui », « Hier », « Lundi 2 novembre »)."""
    return by_day(_DayGot(sc), items)


class _DayGot:
    """Ce que ``by_day`` lit d'un onglet : la console et l'instant de la page."""

    def __init__(self, sc: Scene) -> None:
        self.ui = sc.ui
        self.env = sc.ui.env()


# ── Pull requests ─────────────────────────────────────────────────────────


def _runs(raw: Raw) -> list[dict[str, Any]]:
    out = []
    for _row, cells in raw.rows(code.RUNS_TITLE):
        state = said(cells.get("état"))
        tone = WORD_TONES.get(state, WAIT)
        seconds = number(cells.get("secondes"))
        out.append({"name": said(cells.get("vérification")), "state": state, "tone": tone,
                    "icon": CHECK_ICONS[tone], "took": f"{seconds} s" if seconds else state})
    return out


def _talk(sc: Scene, raw: Raw) -> list[dict[str, Any]]:
    return [{"account": said(cells.get("compte")), "text": said(cells.get("ce qu'il a écrit")),
             "ago": sc.ago(instant(cells.get("quand"))), "here": said(cells.get("publié d'ici")) == "oui"}
            for _row, cells in raw.rows(code.TALK_TITLE)]


def _review(o: Any, said_: Mapping[str, str]) -> dict[str, Any] | None:
    if not o.review_at and not o.review_due:
        return None
    asked = bool(o.review_due) and o.review_due != o.reviewed
    label = "relecture demandée" if asked else REVIEW_WORDS[o.review_ok].removeprefix("relu : ") \
        if o.review_at else "pas encore relue"
    return {"label": label, "tone": WAIT if asked or not o.review_at else DONE if o.review_ok else FAIL,
            "text": said_.get(o.review_ref, "") if o.review_ref else "",
            "refused": said_.get(o.review_refused[-1], "") if o.review_refused and not o.review_ok else ""}


def _hosted_block(sc: Scene, o: Any, raw: Raw, head: str) -> str:
    """Ce que l'hôte, tel que la page l'a lu (``inspect_code.hosted``), dirait à l'action ``projects.fusionner`` :
    sa branche à un autre commit, des conflits, des vérifications pas finies sur ce commit (``merge.checks_block``,
    la règle même de l'action). Vide : rien — ou l'hôte n'a pas été lu sur ce commit, et l'action le relira."""
    pr = raw.fields(code.HOST_PULL_TITLE)
    there = said(pr.get("commit")).strip("—")
    if there and head and there != head:
        return MOVED_THERE.format(sha=there[:12])
    if said(pr.get("fusionnable")) == "non":
        return BLOCK_WORDS[merge.CONFLICTS]
    checks = raw.fields(f"{code.RUNS_TITLE} en bref")
    if said(checks.get("commit")) != head:
        return ""
    held = merge.checks_block(o, said(checks.get("étape")), 0, sc.now)
    return BLOCK_WORDS[held] if held else ""


def _merge(sc: Scene, o: Any, info: Mapping[str, Any], d: dict[str, Any], title: str, raw: Raw) -> dict[str, Any]:
    """La fusion : où elle en est, ce qui la retient (``merge.blocked``, la règle même de l'action, puis ce que
    l'hôte lu par la page dirait : ``_hosted_block``), et le formulaire de ``projects.fusionner`` qui nomme le commit
    de tête lu par la page."""
    stage = pull_stage(sc.p, o)
    block = merge.blocked(sc.p, o, sc.now)
    head = said(info.get("tête"))
    out: dict[str, Any] = {"stage": stage, "base": sc.p.branch, "head": head, "short": head[:12], "n": o.pull,
                           "branch": o.branch,
                           "refused": REFUSED_WORDS.get(o.merge_refused, "") if o.merge_refused else "",
                           "asked": stage == code.OPEN and merge.merging(o), "why": "", "form": None}
    if stage == code.MERGED:
        return out
    # le geste ne s'offre que si l'action l'acceptera : la règle à l'instant de la page (``merge.blocked`` avec
    # ``now`` — une pull request fraîche dont l'hôte ne dit encore aucune vérification attend, ADR 0292), comme
    # l'API (``merge_refusal``), puis ce que l'hôte lu en dirait (``_hosted_block``)
    if block and block != merge.ASKED:
        out["why"] = BLOCK_WORDS.get(block, block)
    hosted = _hosted_block(sc, o, raw, head) if stage == code.READY and head and not out["why"] else ""
    if hosted:  # l'action le refuserait : la page le dit, sans offrir le geste
        out["why"] = hosted
    elif stage == code.READY and head and not out["why"]:
        form = shown(sc.form("fusionner", _pull_href(sc, o), objective=str(o.id), head=head))
        out["form"] = form
        out["facts"] = [("commit", plural(len(d["commits"]), "commit", "commits")),
                        ("file", f"{plural(len(d['diff']['files']), 'fichier', 'fichiers')}, +{d['diff']['plus']} "
                                 f"−{d['diff']['minus']}"),
                        ("check", " · ".join(x for x in (
                            f"relecture : {d['review']['label']}" if d["review"] else "",
                            f"vérifications : {code.CHECK_WORDS.get(o.checks, '')}" if o.checks_sha else "",
                            "aucun conflit" if not o.pull_conflicts else "") if x))]
        out["title"] = title
    return out


def pulls_view(sc: Scene, raw: Raw, head: Mapping[str, Any]) -> dict[str, Any]:
    p = sc.p
    order = pull_order(p)
    words = sc.texts(o.text_ref for o in order)
    wanted = sc.query.get("pr", "")
    chosen = pull_named(p, wanted) if wanted else (order[0] if order else None)
    rows = [{"key": code.pull_key(o), "n": o.pull, "title": words.get(o.text_ref, FORGOTTEN),
             "stage": pull_stage(p, o), "state": code.PULL_WORDS[pull_stage(p, o)].split(",")[0],
             "tone": STAGE_TONES[pull_stage(p, o)], "ago": sc.age(o.pull_at), "yours": pull_stage(p, o) == code.READY,
             "on": chosen is not None and o.id == chosen.id, "merged": o.pull_state == "merged",
             "href": _pull_href(sc, o)} for o in order]
    out: dict[str, Any] = {"rows": rows, "open": sum(1 for o in order if o.pull_state == PULL_OPEN),
                           "lire": bool(wanted), "pr": None, "missing": wanted if wanted and chosen is None else ""}
    if chosen is None:
        return out
    o = chosen
    info = raw.fields(code.PULL_TITLE)
    host = raw.fields(code.HOST_PULL_TITLE)
    body = raw.code(code.HOST_BODY_TITLE)
    log = raw.code(code.LOG_TITLE, prefix=True)
    said_ = sc.texts(goal_refs(sc, o))
    back = _pull_href(sc, o)
    item = ticket_of(p, o)
    ticket_words = sc.texts([item.title_ref]) if item is not None else {}
    title = said_.get(o.text_ref, FORGOTTEN)
    side_by_side = sc.query.get("diff") == "cote"
    d: dict[str, Any] = {
        "o": o.id, "n": o.pull, "title": title, "stage": pull_stage(p, o), "tone": STAGE_TONES[pull_stage(p, o)],
        "state": code.PULL_WORDS[pull_stage(p, o)].split(",")[0], "branch": o.branch, "base": p.branch,
        "ago": sc.ago(o.pull_at), "url": raw.href(info.get("chez l'hôte")),
        "done_when": said_.get(o.done_when_ref, "") if o.done_when_ref else "",
        "result": said_.get(o.result_ref, "") if o.result_ref else "",
        "milestones": [milestone(sc, o, m, said_, back, gestures=False) for m in o.milestones
                       if m.status != c.DROPPED],
        "host_said": said_.get(o.pull_said_ref, "") if o.pull_said_ref else "",
        "commits": commits(sc, raw, code.COMMITS_TITLE), "diff": diffs(raw, side_by_side),
        "commit_days": by_day_items(sc, commits(sc, raw, code.COMMITS_TITLE)),
        "talk": _talk(sc, raw), "body": body.text if body is not None else "",
        "host": {"title": said(host.get("titre")).strip("—"), "seen": sc.ago(instant(host.get("lue")))} if host
        else None, "host_read": bool(host), "runs": _runs(raw), "log": log.text if log is not None else "",
        "log_name": log.title.split(" — ", 1)[1] if log is not None and " — " in log.title else "",
        "checks": {"state": code.CHECK_WORDS.get(o.checks, ""), "tone": CHECK_TONES.get(o.checks, WAIT),
                   "sha": o.checks_sha, "href": sc.url("git", vue=code.CI, sha=o.checks_sha)}
        if o.checks_sha else None,
        "review": _review(o, said_), "conflicts": bool(o.pull_conflicts and o.pull_state == PULL_OPEN),
        "changes": o.pull_changes, "unsent": o.unsent, "head": said(info.get("tête")),
        "branch_href": sc.url("git", vue=code.BRANCHES, branche=o.branch) if o.branch else "",
        "objective": linked_objective(sc, o, said_), "ticket": linked_ticket(sc, item, ticket_words),
        "toggle": {"unifie": sc.url("git", "pr-fichiers", vue=code.PULLS, pr=code.pull_key(o)),
                   "cote": sc.url("git", "pr-fichiers", vue=code.PULLS, pr=code.pull_key(o), diff="cote")}}
    d["merge"] = _merge(sc, o, info, d, title, raw)
    live = writable(p, o)
    d["edit"] = shown(sc.form("pull_modifier", back + "#pr-resume", objective=str(o.id),
                              title=d["host"]["title"] if d["host"] and d["host"]["title"] else "",
                              body=d["body"]), "title", "body") if live else None
    d["reply"] = shown(sc.form("pull_commenter", back + "#pr-echanges", objective=str(o.id)), "text") \
        if live else None
    out["pr"] = d
    return out


# ── Branches ──────────────────────────────────────────────────────────────


def branches_view(sc: Scene, raw: Raw, head: Mapping[str, Any]) -> dict[str, Any]:
    p = sc.p
    items = []
    wanted = sc.query.get("branche", "")
    info = raw.fields(code.BRANCH_TITLE)
    chosen = said(info.get("branche"))
    biggest = max([1] + [max(number(cells.get("avance")), number(cells.get("retard")))
                         for _r, cells in raw.rows(code.BRANCHES_TITLE)])
    for _row, cells in raw.rows(code.BRANCHES_TITLE):
        name = said(cells.get("branche"))
        base = said(cells.get("base")) == "oui"
        o = None if base else objective_on(p, name)
        item = ticket_of(p, o)
        ahead, behind = number(cells.get("avance")), number(cells.get("retard"))
        sha = said(cells.get("dernier commit"))
        items.append({
            "name": name, "base": base, "ahead": ahead, "behind": behind,
            "ahead_w": round(56 * ahead / biggest), "behind_w": round(56 * behind / biggest),
            "sha": sha[:7], "message": said(cells.get("message")), "ago": sc.ago(instant(cells.get("quand"))),
            "objective": o.id if o is not None else 0, "ticket": item.number if item is not None else 0,
            "pull": card(sc, o),
            "checks": code.CHECK_WORDS.get(o.checks, "") if o is not None and o.checks_sha else "",
            "checks_tone": CHECK_TONES.get(o.checks, WAIT) if o is not None else WAIT,
            "on": name == chosen, "href": sc.url("git", vue=code.BRANCHES, branche=name),
            "commit_href": sc.url("git", vue=code.COMMITS, sha=sha) if sha else ""})
    out: dict[str, Any] = {"items": items, "base": head.get("branche de base") or "main", "panel": None,
                           "pager": render._pager(Pager(size=max(1, len(items)), total=max(1, len(items))), {}),
                           "by_pulls": bool(code.pulled(p)) or p.flow == c.FLOW_PR, "lire": bool(wanted)}
    picked = next((b for b in items if b["on"]), None)
    if picked is None:
        return out
    o = objective_on(p, chosen)
    changed = diffs(raw, False)
    out["panel"] = {**picked, "linked": linked(sc, o), "commits": commits(sc, raw, code.AHEAD_TITLE),
                    "files": changed, "files_href": sc.url("git", ref=chosen),
                    "commits_href": sc.url("git", vue=code.COMMITS, ref=chosen),
                    "diff_href": _pull_href(sc, o, "pr-fichiers") if o is not None and (o.pull or o.pull_proposal)
                    else ""}
    return out


# ── Issues ────────────────────────────────────────────────────────────────


def _settle(sc: Scene, item: Any, back: str) -> list[dict[str, Any]]:
    """Accepter ou écarter le ticket qu'une issue propose : les gestes du ticket lui-même (``ticket_trancher``)."""
    if item is None:
        return []
    name = f"#{item.number}"

    def form(verdict: str, *paths: str) -> dict[str, Any] | None:
        return shown(sc.form("ticket_trancher", back, item=name, plan=str(item.plan_seq)), *paths, verdict=verdict)

    out = []
    if item.status == c.STAGE_PROPOSED:
        out.append({"form": form("accept"), "label": "Accepter le ticket", "icon": "check", "main": True})
    if item.status in c.STAGES_OPEN:
        out.append({"form": form("dismiss", "reason"), "label": "Écarter", "icon": "x", "ask": True,
                    "title": f"Écarter le ticket {name}", "submit": "Écarter le ticket"})
    return [g for g in out if g["form"] is not None]


def issues_view(sc: Scene, raw: Raw, head: Mapping[str, Any]) -> dict[str, Any]:
    p = sc.p
    info = raw.fields(code.ISSUE_TITLE)
    chosen = number(info.get("n°"))
    rows = []
    for _row, cells in raw.rows(code.ISSUES_TITLE):
        n = number(param(cells.get("n°"), "issue"))
        state = said(cells.get("état"))
        rows.append({"n": n, "title": said(cells.get("titre")).strip("—") or f"Issue n° {n}", "state": state,
                     "tone": DONE if state.startswith("fermée") else WAIT,
                     "here": said(cells.get("publiée d'ici")) == "oui", "ago": sc.age(instant(cells.get("touchée"))),
                     "on": n == chosen, "href": sc.url("git", vue=code.ISSUES, issue=n)})
    out: dict[str, Any] = {"rows": rows, "open": sum(1 for r in rows if r["state"] == code.ISSUE_WORDS["open"]),
                           "lire": bool(sc.query.get("issue")), "issue": None}
    if not info:
        return out
    item = issue_ticket(p, chosen)
    words = sc.texts([item.title_ref]) if item is not None else {}
    back = sc.url("git", vue=code.ISSUES, issue=chosen)
    body = raw.code(code.ISSUE_BODY_TITLE)
    state = said(info.get("état"))
    held = objective_at(p, item.objective) if item is not None and item.objective else None
    labels = said(info.get("étiquettes"))
    out["issue"] = {
        "n": chosen, "title": said(info.get("titre")).strip("—") or f"Issue n° {chosen}", "state": state,
        "tone": DONE if state.startswith("fermée") else WAIT, "author": said(info.get("auteur")).strip("—"),
        "here": said(info.get("publiée d'ici")) == "oui", "ago": sc.ago(instant(info.get("touchée"))),
        "when": sc.when(instant(info.get("touchée"))), "comments": said(info.get("commentaires")),
        "labels": [x for x in labels.split(" · ") if x and x != "—"], "url": raw.href(info.get("chez l'hôte")),
        "body": body.text if body is not None else "", "talk": _talk(sc, raw),
        "ticket": linked_ticket(sc, item, words), "proposed": item is not None and item.status == c.STAGE_PROPOSED,
        "hand": "au propriétaire" if item is not None and item.status in (c.STAGE_PROPOSED, c.STAGE_VALIDATION)
        else "", "gestures": _settle(sc, item, back),
        "pull": card(sc, held)}
    return out


# ── CI ────────────────────────────────────────────────────────────────────


def checks_view(sc: Scene, raw: Raw, head: Mapping[str, Any]) -> dict[str, Any]:
    p = sc.p
    info = raw.fields(f"{code.RUNS_TITLE} en bref")
    chosen = said(info.get("commit"))
    rows = []
    for _row, cells in raw.rows(code.TRACKED_TITLE):
        sha = param(cells.get("commit"), "sha")
        state = said(cells.get("étape"))
        rows.append({"sha": sha, "short": sha[:7], "title": said(cells.get("message")).strip("—") or
                     said(cells.get("objectif")), "state": code.CHECK_WORDS.get(state, state),
                     "tone": CHECK_TONES.get(state, WAIT), "ago": sc.age(instant(cells.get("quand"))),
                     "on": bool(chosen) and sha == chosen, "href": sc.url("git", vue=code.CI, sha=sha)})
    out: dict[str, Any] = {"rows": rows, "lire": bool(sc.query.get("sha")), "checks": None}
    wanted = chosen or sc.query.get("sha", "")
    if not wanted:
        return out
    o = next((x for x in code.pulled(p) if x.checks_sha and x.checks_sha.startswith(wanted)), None)
    row = next((r for r in rows if r["sha"] == wanted), None)
    log = raw.code(code.LOG_TITLE, prefix=True)
    state = said(info.get("étape"))
    runs = _runs(raw)
    out["checks"] = {
        "sha": wanted, "short": wanted[:12], "title": row["title"] if row else f"Commit {wanted[:7]}",
        "state": code.CHECK_WORDS.get(state, "") if state else (row["state"] if row else ""),
        "tone": CHECK_TONES.get(state, row["tone"] if row else WAIT), "ago": sc.ago(instant(info.get("finies"))),
        "seen": sc.ago(instant(info.get("relues"))), "runs": runs,
        "passed": sum(1 for r in runs if r["tone"] == DONE), "log": log.text if log is not None else "",
        "log_name": log.title.split(" — ", 1)[1] if log is not None and " — " in log.title else "",
        "url": raw.href(info.get("chez l'hôte")), "read": bool(info), "linked": linked(sc, o),
        "branch": o.branch if o is not None else ""}
    return out
