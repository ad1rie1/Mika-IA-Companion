"""Le code d'un projet, pour qui est connecté (ADR 0288) : ses fichiers, ses commits et leur diff, ses branches, ses
pull requests, ses issues, sa CI — et **fusionner** une pull request, le geste d'une personne.

**Aucune règle n'est d'ici**, comme pour le reste de ses projets (``projects.py``, dont viennent ``_opened`` et ce
qu'elle a d'un projet) :

- le **détail** d'un projet donne ses commits, ses branches, ses pull requests et ses issues en titres et en états ;
- le **contenu** d'un fichier, l'arbre du dépôt et un diff demandent en plus le droit sur ses fichiers
  (``projects.reads_files``) : sans lui, 403 pour un fichier, et un commit ou une pull request sans ``files`` ;
- une issue d'un inconnu ne dit son titre, son texte et ses échanges qu'à qui peut la trancher (``tracker.veiled``) ;
- fusionner est au propriétaire du projet et à qui s'occupe d'elle (``tracker.settles``), par l'action
  ``projects.fusionner`` : le commit de tête qu'elle a lu est nommé, et l'action refuse s'il a bougé.

**D'où vient chaque chose.** Les pull requests, leur CI et leur relecture : du journal (ce que le moteur sait). Les
fichiers, les commits, les branches et les diffs : de l'atelier, par le port, à une référence — jamais l'arbre de
travail, jamais un chemin composé ici. Ce que l'hôte est seul à savoir (le texte d'une pull request, ses échanges,
ses vérifications une à une, les issues et leurs étiquettes) : lu chez lui à la demande, borné par compte
(``HOST_READS``), jamais journalisé. Tout texte de l'hôte porte ``outside``. Le contrat, route par route :
``docs/protocole-moi.md``, § 11.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from typing import Any
from urllib.parse import quote
from weakref import WeakKeyDictionary

from starlette.routing import Route

from mika.adapters.web.gate import SlidingWindow
from mika.app.domains.projects.api.projects import (
    HAND_WORDS,
    NO_FILES,
    NOT_MERGER,
    PAGE_MAX,
    PATH,
    REVIEW_WORDS,
    TEXT_SHOWN,
    VEIL_WORDS,
    YOU_WORDS,
    Reach,
    Scene,
    _milestone_json,
    _name,
    _objective_refs,
    _opened,
    _outside,
    _steers,
    _texts,
    merge_refusal,
    reads_files,
)
from mika.app.me.api import Call, Denied, MeApiBase, done, form, missing, spend
from mika.app.me.common import millis
from mika.contracts import projects as c
from mika.contracts import self_ as self_c
from mika.faculties.projects import merge, pulls, tickets, tracker
from mika.faculties.projects.faculty import (
    Item,
    Objective,
    Project,
    by_pulls,
    handed_over,
    objective_on,
    repo_page,
    ticket_held,
)
from mika.faculties.projects.inspect import OBJ_FR
from mika.faculties.projects.inspect_code import (  # ses mots et ses règles : ceux de la console (ADR 0297)
    BINARY,
    CHECK_WORDS,
    DIFF_CUT,
    ENTRY_WORDS,
    FILE_WORDS,
    HIDDEN,
    HIDDEN_FILE,
    ISSUE_DROPPED,
    ISSUE_WORDS,
    LINK,
    MODULE,
    PULL_ORDER,
    PULL_WORDS,
    READY,
    TOO_BIG,
)
from mika.faculties.projects.inspect_code import issue_ticket as _issue_ticket
from mika.faculties.projects.inspect_code import objective_for as _objective_for
from mika.faculties.projects.inspect_code import pull_stage as _pull_state
from mika.faculties.projects.inspect_code import pulled as _pulled
from mika.faculties.projects.inspect_merge import ACTION as MERGE_ACTION
from mika.faculties.projects.inspect_merge import REFUSED_WORDS
from mika.ports.workshop import (
    BASE_BRANCH,
    CHECKS_FAILED,
    ENTRY_FILE,
    ENTRY_LINK,
    ENTRY_MODULE,
    ISSUE_CLOSED,
    ISSUE_OPEN,
    PULL_OPEN,
    Commit,
    FileDiff,
    OutsideWorkshop,
    hidden_path,
)

#: où vivent ses routes : sous la fiche du projet
CODE = PATH + "/{project:int}/code"
#: une page de commits, de pull requests, d'issues ; l'histoire courte d'un fichier
PAGE = 30
FILE_HISTORY = 10
#: un fichier rendu, au plus (octets) ; les lignes d'un diff rendues, au plus, en une réponse
FILE_BYTES, DIFF_LINES = 400_000, 3000
#: ce qu'une personne peut faire lire à l'hôte, au plus, dans la fenêtre : chaque lecture le joint
HOST_READS = (60, 60.0)
#: les vérifications suivies qu'on montre, au plus ; et l'histoire où l'on cherche leurs commits
CHECKS_SHOWN, CHECKS_HISTORY = 40, 300

# ── Ses mots ──────────────────────────────────────────────────────────────

#: une relecture indépendante : aucune encore, demandée, puis son verdict
REVIEW_NONE, REVIEW_ASKED = "pas encore relue", "relecture demandée"
#: qui a signé un commit : elle (l'atelier), ou quelqu'un d'autre (un commit venu du dépôt distant)
BY_HER, BY_OTHER = "self", "other"

# ── Les refus, en mots ────────────────────────────────────────────────────

OUTSIDE = "Ce chemin sort du dépôt : écris un chemin relatif à sa racine."
NO_REMOTE = "Ce projet n'a pas de dépôt distant que l'on sache lire."
HOST_BUSY = "Trop de lectures de l'hôte d'affilée : attends une minute."
HEAD_NEEDED = "Nomme le commit que tu as lu : « head », l'identifiant complet du commit au bout de sa branche."

_SHA = re.compile(r"^[0-9a-f]{4,40}$")
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_host_reads: WeakKeyDictionary[MeApiBase, SlidingWindow] = WeakKeyDictionary()


# ── Ce qu'il faut pour lire ───────────────────────────────────────────────


def _shop(call: Call, r: Reach) -> Any:
    """L'atelier du projet, s'il a un dépôt à lire ; sinon ``None`` (aucune exécution n'a encore rien écrit)."""
    port = call.port("workshop")
    return port if port is not None and port.exists(r.p.id) else None


def _files(sc: Scene, r: Reach) -> None:
    """La garde du contenu : un fichier, l'arbre, un diff demandent le droit sur ses fichiers (403 sinon)."""
    if not reads_files(sc, r):
        raise Denied(403, NO_FILES)


def _host(call: Call, p: Project) -> Any:
    """L'hôte du dépôt distant, s'il sait le lire ; sinon ``None``."""
    host = call.port("repo_host")
    return host if p.remote and host is not None and host.handles(p.remote) else None


def _host_read(call: Call) -> None:
    """Une lecture qui joint l'hôte : bornée par compte (429 au-delà)."""
    window = _host_reads.setdefault(call.api, SlidingWindow(*HOST_READS))
    if not spend(window, call.me.account):
        raise Denied(429, HOST_BUSY)


def _path(call: Call) -> str:
    """Le chemin que la requête nomme. Un segment caché — qui commence par un point — ne se lit pas d'ici (403) : la
    règle du partage d'un fichier de projet (ADR 0292)."""
    path = call.arg("path", limit=1000)
    if hidden_path(path):
        raise Denied(403, HIDDEN, {"path": "un fichier caché ne se lit pas d'ici"})
    return path


def _lines(call: Call) -> int:
    return call.number("lines", DIFF_LINES, 0, DIFF_LINES)


def _paged(call: Call) -> tuple[int, int]:
    return call.number("page", 1, 1, 10_000), call.number("size", PAGE, 1, PAGE_MAX)


def _outside_path() -> Denied:
    return Denied(400, OUTSIDE, {"path": "un chemin relatif au dépôt"})


# ── Ce qui est lié : l'objectif, le ticket, la pull request ───────────────


def _ticket_refs(items: Iterable[Item | None]) -> list[str]:
    return [x.title_ref for x in items if x is not None]


def _objective_brief(o: Objective | None, texts: Mapping[str, str]) -> dict[str, Any] | None:
    if o is None:
        return None
    return {"id": o.id, "text": texts.get(o.text_ref, "")[:TEXT_SHOWN], "kind": o.kind, "status": o.status,
            "status_label": OBJ_FR.get(o.status, o.status)}


def _ticket_brief(r: Reach, item: Item | None, texts: Mapping[str, str]) -> dict[str, Any] | None:
    """Le ticket lié, tel qu'elle peut le lire : son étape toujours, son titre seulement s'il se lit."""
    if item is None:
        return None
    veil = tracker.veiled(r.reader, item)
    hand = tickets.hand(item) if not item.closed else ""
    return {"number": item.number, "handle": f"#{item.number}", "title": "" if veil else texts.get(item.title_ref, ""),
            "veiled": veil, "veiled_label": VEIL_WORDS.get(veil, ""), "status": item.status,
            "status_label": tracker.status_words(c.TICKETS, item.status), "open": not item.closed, "hand": hand,
            "hand_label": HAND_WORDS.get(hand, ""), "yours": hand == c.ACTOR_OWNER and r.settles}


def _checks_brief(o: Objective) -> dict[str, Any] | None:
    if not o.checks_sha:
        return None
    return {"state": o.checks, "state_label": CHECK_WORDS.get(o.checks, ""), "sha": o.checks_sha,
            "at": millis(o.checks_at)}


def _review_brief(o: Objective) -> dict[str, Any] | None:
    if not o.review_at and not o.review_due:
        return None
    asked = bool(o.review_due) and o.review_due != o.reviewed
    return {"ok": o.review_ok if o.review_at else None, "asked": asked,
            "label": REVIEW_ASKED if asked else REVIEW_WORDS[o.review_ok] if o.review_at else REVIEW_NONE,
            "at": millis(o.review_at), "commit": o.reviewed, "refused": len(o.review_refused),
            "handed_over": handed_over(o)}


def _merge_json(sc: Scene, r: Reach, o: Objective) -> dict[str, Any]:
    """Peut-elle fusionner cette pull request, et sinon pourquoi — la garde de la route, dite d'avance ; et où en est
    une fusion déjà demandée."""
    why = merge_refusal(r, o, sc.frame.now)
    by = YOU_WORDS if o.merge_by and o.merge_by == sc.person else _name(sc, o.merge_by)
    refused = REFUSED_WORDS.get(o.merge_refused, "") if o.merge_refused else ""
    asked = o.pull_state == PULL_OPEN and merge.merging(o)
    return {"can": not why, "why": why, "asked": asked, "asked_at": millis(o.merge_asked_at),
            "asked_by": by if o.merge_asked_at or o.merge_answered_at else "", "refused": refused,
            "refused_at": millis(o.merge_answered_at) if refused else 0}


def _pull_brief(sc: Scene, r: Reach, o: Objective | None) -> dict[str, Any] | None:
    """La pull request d'un objectif en une ligne : son numéro, où elle en est, sa page chez l'hôte."""
    if o is None or not (o.pull_state or o.pull or o.pull_proposal):
        return None
    state = _pull_state(r.p, o)
    return {"number": o.pull, "title": pulls.title_of(o), "state": state, "state_label": PULL_WORDS[state],
            "url": pulls.pull_url(r.p, o), "branch": o.branch, "checks": _checks_brief(o),
            "review": _review_brief(o)}


def _pull_json(sc: Scene, r: Reach, o: Objective, texts: Mapping[str, str]) -> dict[str, Any]:
    p = r.p
    return {**(_pull_brief(sc, r, o) or {}), "base": p.branch, "at": millis(o.pull_at),
            "conflicts": o.pull_conflicts, "changes_asked": o.pull_changes, "awaits_accord": o.pull_proposal,
            "unsent": o.unsent, "objective": _objective_brief(o, texts),
            "ticket": _ticket_brief(r, ticket_held(p, o), texts), "merge": _merge_json(sc, r, o)}


# ── Un commit, un diff ────────────────────────────────────────────────────


def _commit_json(sc: Scene, r: Reach, k: Commit, texts: Mapping[str, str]) -> dict[str, Any]:
    """Un commit : son message, son empreinte, qui l'a signé — elle, ou quelqu'un d'autre (un commit venu du dépôt
    distant : son message et son auteur sont alors des textes d'ailleurs, ``outside``) —, son instant, sa branche,
    ses comptes, et l'objectif ou le ticket qui lui est lié."""
    p = r.p
    o = _objective_for(p, k)
    page = repo_page(p) if _host(sc.call, p) is not None else ""
    her = self_c.name_of(sc.frame.get(self_c.PERSONA))
    return {"sha": k.sha, "short": k.sha[:7], "title": k.title[:400], "at": millis(k.at),
            "author_kind": BY_HER if k.local else BY_OTHER, "author": her if k.local else k.author[:80],
            "outside": not k.local, "branch": k.branch, "base": k.branch == BASE_BRANCH,
            "merge": len(k.parents) > 1, "files": k.files, "insertions": k.insertions, "deletions": k.deletions,
            "objective": o.id if o is not None else 0, "ticket": o.ticket if o is not None else 0,
            "url": f"{page}/commit/{k.sha}" if page else ""}


def _commit_refs(p: Project, commits: Iterable[Commit]) -> list[str]:
    found = [_objective_for(p, k) for k in commits]
    return [o.text_ref for o in found if o is not None] + _ticket_refs(ticket_held(p, o) for o in found)


def _diff_json(files: Sequence[FileDiff]) -> dict[str, Any]:
    """Un diff, fichier par fichier : ses comptes toujours ; ses passages et leurs lignes numérotées (avant, après)
    tant que la borne n'est pas atteinte — ``cut`` dit qu'un fichier n'a pas tous les siens."""
    # un fichier caché (``.env``, ``.github/…``) se dit — son chemin, ses comptes —, sans ses passages (ADR 0292)
    out = [{"path": f.path, "status": f.status, "status_label": FILE_WORDS.get(f.status, f.status),
            "insertions": f.insertions, "deletions": f.deletions, "binary": f.binary, "cut": f.cut,
            "hidden": hidden_path(f.path), "why": HIDDEN_FILE if hidden_path(f.path) else "",
            "hunks": [] if hidden_path(f.path) else
            [{"header": h.header, "lines": [{"kind": x.kind, "old": x.old, "new": x.new, "text": x.text}
                                            for x in h.lines]} for h in f.hunks]} for f in files]
    cut = any(f.cut for f in files)
    return {"files": out, "cut": cut, "cut_label": DIFF_CUT if cut else "",
            "insertions": sum(f.insertions for f in files), "deletions": sum(f.deletions for f in files)}


async def _diff(sc: Scene, r: Reach, port: Any, since: str, head: str, *, counts_only: bool = False) -> dict[str, Any]:
    """Ce qui change entre deux commits, si elle lit ses fichiers ; sinon rien, et pourquoi (``files_why``).
    ``path`` : un seul fichier ; ``lines`` : la borne (0 : les comptes seuls)."""
    call = sc.call
    if not reads_files(sc, r):
        return {"files": [], "cut": False, "cut_label": "", "insertions": 0, "deletions": 0, "files_readable": False,
                "files_why": NO_FILES}
    try:
        files = await port.diff_of(r.p.id, since, head, path=_path(call), lines=0 if counts_only else _lines(call))
    except OutsideWorkshop:
        raise _outside_path() from None
    return {**_diff_json(files or ()), "files_readable": True, "files_why": ""}


# ── Le résumé ─────────────────────────────────────────────────────────────


async def summary(call: Call) -> dict[str, Any]:
    """``GET …/code`` : le dépôt en bref — sa branche de base, son dépôt distant, ce qu'elle peut y lire et y faire,
    et les comptes des sous-onglets."""
    sc, r = _opened(call)
    p = r.p
    port = _shop(call, r)
    history = await port.history(p.id, n=1) if port is not None else None
    branches = await port.branches(p.id) if port is not None else []
    found = _pulled(p)
    last = history.commits[:1] if history is not None else ()
    texts = _texts(call, _commit_refs(p, last))
    page = repo_page(p) if _host(call, p) is not None else ""
    return {"has_repo": history is not None, "base": BASE_BRANCH,
            "current": next((b.name for b in branches if b.current), ""),
            "remote": {"has": bool(p.remote), "web": page, "branch": p.branch, "flow": p.flow,
                       "by_pulls": by_pulls(p), "synced_at": millis(p.remote_at)},
            "rights": {"files": reads_files(sc, r), "merge": r.steer in c.CHANGES and r.reader.settles},
            "counts": {"commits": history.total if history is not None else 0, "branches": len(branches),
                       "pulls_open": sum(1 for o in found if o.pull_state == PULL_OPEN),
                       "pulls_ready": sum(1 for o in found if _pull_state(p, o) == READY),
                       "issues_open": sum(1 for x in p.board.items if x.list_name == c.TICKETS and x.issue
                                          and not x.closed),
                       "checks_failed": sum(1 for o in found if o.pull_state == PULL_OPEN
                                            and o.checks == CHECKS_FAILED)},
            "last_commit": _commit_json(sc, r, last[0], texts) if last else None}


# ── Fichiers ──────────────────────────────────────────────────────────────


async def tree(call: Call) -> dict[str, Any]:
    """``GET …/code/fichiers`` : un dossier du dépôt à une branche ou à un commit (``ref`` ; par défaut la base) —
    ses entrées directes, les dossiers d'abord —, son dernier commit, et son README s'il en a un."""
    sc, r = _opened(call)
    _files(sc, r)
    port = _shop(call, r)
    ref, path = call.arg("ref", BASE_BRANCH, limit=100) or BASE_BRANCH, _path(call)
    try:
        entries = await port.ref_tree(r.p.id, ref, path) if port is not None else None
        history = await port.history(r.p.id, ref, path=path, n=1) if entries is not None else None
    except OutsideWorkshop:
        raise _outside_path() from None
    except FileNotFoundError:
        raise missing() from None
    if entries is None:
        raise missing()
    here = "/".join(x for x in path.strip().split("/") if x and x != ".")
    last = history.commits[:1] if history is not None else ()
    texts = _texts(call, _commit_refs(r.p, last))
    readme = next((e.path for e in entries if e.kind == ENTRY_FILE
                   and e.path.rsplit("/", 1)[-1].lower() in ("readme.md", "readme", "readme.txt")), "")
    shown = [e for e in entries if not hidden_path(e.path)]  # un fichier caché ne sort pas d'ici (ADR 0292)
    return {"ref": ref, "path": here, "parent": here.rpartition("/")[0] if here else None, "readme": readme,
            "hidden": len(entries) - len(shown),
            "items": [{"path": e.path, "name": e.path.rsplit("/", 1)[-1], "kind": e.kind,
                       "kind_label": ENTRY_WORDS.get(e.kind, e.kind), "size": e.size} for e in shown],
            "last_commit": _commit_json(sc, r, last[0], texts) if last else None}


async def blob(call: Call) -> dict[str, Any]:
    """``GET …/code/fichier`` : un fichier à une branche ou à un commit — son texte s'il en est un et qu'il tient
    sous la borne ; sinon ce qu'il est, sans contenu —, le dernier commit qui l'a touché et son histoire courte."""
    sc, r = _opened(call)
    _files(sc, r)
    port = _shop(call, r)
    ref, path = call.arg("ref", BASE_BRANCH, limit=100) or BASE_BRANCH, _path(call)
    try:
        found = await port.ref_file(r.p.id, ref, path, FILE_BYTES) if port is not None else None
        history = await port.history(r.p.id, ref, path=path, n=FILE_HISTORY) if found is not None else None
    except OutsideWorkshop:
        raise _outside_path() from None
    except FileNotFoundError:
        raise missing() from None
    if found is None:
        raise missing()
    why = BINARY if found.binary else TOO_BIG if found.too_big else LINK if found.kind == ENTRY_LINK else \
        MODULE if found.kind == ENTRY_MODULE else ""
    commits = history.commits if history is not None else ()
    texts = _texts(call, _commit_refs(r.p, commits))
    said = [_commit_json(sc, r, k, texts) for k in commits]
    page = repo_page(r.p) if _host(call, r.p) is not None else ""
    return {"ref": ref, "sha": found.sha, "path": found.path, "name": found.path.rsplit("/", 1)[-1],
            "kind": found.kind, "kind_label": ENTRY_WORDS.get(found.kind, found.kind), "size": found.size,
            "binary": found.binary, "too_big": found.too_big, "readable": not why, "why": why, "text": found.text,
            "lines": found.text.count("\n") + (1 if found.text and not found.text.endswith("\n") else 0),
            "last_commit": said[0] if said else None, "history": said,
            "history_total": history.total if history is not None else 0,
            "url": f"{page}/blob/{found.sha}/{quote(found.path)}" if page else ""}


# ── Commits ───────────────────────────────────────────────────────────────


async def commits(call: Call) -> dict[str, Any]:
    """``GET …/code/commits`` : l'histoire d'une branche (``ref``), ou de toutes (sans ``ref``), du plus récent, page
    par page. ``path`` : seulement ceux qui ont touché ce chemin — pour qui lit ses fichiers."""
    sc, r = _opened(call)
    port = _shop(call, r)
    ref, path = call.arg("ref", limit=100), _path(call)
    if path:
        _files(sc, r)
    page, size = _paged(call)
    try:
        history = await port.history(r.p.id, ref, path=path, n=size, offset=(page - 1) * size) \
            if port is not None else None
    except OutsideWorkshop:
        raise _outside_path() from None
    if history is None:
        if ref and port is not None:
            raise missing()  # une branche ou un commit que ce dépôt n'a pas
        return {"ref": ref, "total": 0, "page": page, "size": size, "items": []}
    texts = _texts(call, _commit_refs(r.p, history.commits))
    return {"ref": ref, "total": history.total, "page": page, "size": size,
            "items": [_commit_json(sc, r, k, texts) for k in history.commits]}


def _linked(sc: Scene, r: Reach, o: Objective | None, texts: Mapping[str, str]) -> dict[str, Any]:
    """Ce qui est lié à un commit ou à une branche : l'objectif, son ticket, sa pull request, ses vérifications."""
    p = r.p
    return {"objective": _objective_brief(o, texts), "ticket": _ticket_brief(r, ticket_held(p, o), texts),
            "pull": _pull_brief(sc, r, o), "checks": _checks_brief(o) if o is not None else None}


def _linked_refs(p: Project, found: Iterable[Objective | None]) -> list[str]:
    kept = [o for o in found if o is not None]
    return [o.text_ref for o in kept] + _ticket_refs(ticket_held(p, o) for o in kept)


async def commit(call: Call) -> dict[str, Any]:
    """``GET …/code/commit`` : un commit — son message entier, ses fichiers changés avec leurs comptes et leur diff
    (pour qui lit ses fichiers), et ce qui lui est lié."""
    sc, r = _opened(call)
    port = _shop(call, r)
    sha = call.arg("sha", limit=40)
    found = await port.change(r.p.id, sha) if port is not None and _SHA.match(sha) else None
    if found is None:
        raise missing()
    k = found.commit
    o = _objective_for(r.p, k)
    texts = _texts(call, [*_commit_refs(r.p, [k]), *_linked_refs(r.p, [o])])
    # face à son premier parent : pour une fusion, ce qu'elle apporte à la branche où elle entre
    diff = await _diff(sc, r, port, k.parents[0] if k.parents else "", k.sha)
    return {"commit": {**_commit_json(sc, r, k, texts), "body": found.body, "parents": list(k.parents)}, **diff,
            "linked": _linked(sc, r, o, texts)}


# ── Branches ──────────────────────────────────────────────────────────────


def _branch_json(sc: Scene, r: Reach, b: Any, texts: Mapping[str, str]) -> dict[str, Any]:
    o = None if b.base else objective_on(r.p, b.name)
    return {"name": b.name, "base": b.base, "current": b.current, "ahead": b.ahead, "behind": b.behind,
            "head": _commit_json(sc, r, b.head, texts), **_linked(sc, r, o, texts)}


def _branch_refs(p: Project, found: Iterable[Any]) -> list[str]:
    return [*_commit_refs(p, (b.head for b in found)),
            *_linked_refs(p, (objective_on(p, b.name) for b in found if not b.base))]


async def branches(call: Call) -> dict[str, Any]:
    """``GET …/code/branches`` : ses branches, la base d'abord — pour chacune son objectif, son avance et son retard
    sur la base, son dernier commit, sa pull request."""
    sc, r = _opened(call)
    port = _shop(call, r)
    found = await port.branches(r.p.id) if port is not None else []
    texts = _texts(call, _branch_refs(r.p, found))
    return {"base": BASE_BRANCH, "items": [_branch_json(sc, r, b, texts) for b in found]}


async def branch(call: Call) -> dict[str, Any]:
    """``GET …/code/branche`` : une branche — ce qu'elle a d'avance sur la base (ses commits, ses fichiers et leurs
    comptes pour qui lit ses fichiers), son objectif, sa pull request."""
    sc, r = _opened(call)
    port = _shop(call, r)
    name = call.arg("name", limit=100)
    found = next((b for b in await port.branches(r.p.id) if b.name == name), None) if port is not None else None
    if found is None:
        raise missing()
    span = None if found.base else await port.span(r.p.id, name)
    ahead = span.commits if span is not None else ()
    labelled = [replace(k, branch=name) for k in ahead]
    texts = _texts(call, [*_branch_refs(r.p, [found]), *_commit_refs(r.p, labelled)])
    diff = await _diff(sc, r, port, span.base, span.head, counts_only=True) if span is not None and ahead else \
        {"files": [], "cut": False, "cut_label": "", "insertions": 0, "deletions": 0,
         "files_readable": reads_files(sc, r), "files_why": "" if reads_files(sc, r) else NO_FILES}
    return {"branch": _branch_json(sc, r, found, texts),
            "commits": [_commit_json(sc, r, k, texts) for k in labelled], **diff}


# ── Pull requests ─────────────────────────────────────────────────────────


async def pull_list(call: Call) -> dict[str, Any]:
    """``GET …/code/pulls`` : ses pull requests, telles que le journal les sait — les prêtes d'abord, puis les
    ouvertes, les proposées, les fusionnées et les fermées —, chacune avec sa CI, sa relecture et si elle peut la
    fusionner."""
    sc, r = _opened(call)
    p = r.p
    found = sorted(_pulled(p), key=lambda o: (PULL_ORDER[_pull_state(p, o)], -o.pull_at, -o.id))
    page, size = _paged(call)
    shown = found[(page - 1) * size: page * size]
    texts = _texts(call, _linked_refs(p, shown))
    return {"total": len(found), "page": page, "size": size,
            "items": [_pull_json(sc, r, o, texts) for o in shown]}


def _pull_named(call: Call, p: Project) -> Objective:
    """L'objectif dont la pull request porte ce numéro (``number``) ; une pull request encore proposée, sans numéro,
    se nomme par son objectif (``objective``)."""
    number, oid = call.number("number", 0, 0), call.number("objective", 0, 0)
    found = next((o for o in _pulled(p) if (number and o.pull == number) or (oid and not number and o.id == oid)),
                 None)
    if found is None:
        raise missing()
    return found


async def pull(call: Call) -> dict[str, Any]:
    """``GET …/code/pull`` : une pull request, de ce que le journal et l'atelier en savent — sa branche et sa base,
    le commit à son bout (``head`` : celui à nommer pour la fusionner), les jalons de son objectif et leurs preuves,
    sa relecture indépendante, ses vérifications, ses conflits, ses commits, ses fichiers changés et leur diff, ce
    qui lui est lié, et si elle peut la fusionner."""
    sc, r = _opened(call)
    p = r.p
    o = _pull_named(call, p)
    port = _shop(call, r)
    span = await port.span(p.id, o.branch) if port is not None and o.branch else None
    ahead = [replace(k, branch=o.branch) for k in (span.commits if span is not None else ())]
    texts = _texts(call, [*_linked_refs(p, [o]), *_objective_refs(o), *_commit_refs(p, ahead)])
    diff = await _diff(sc, r, port, span.base, span.head) if span is not None and ahead else \
        {"files": [], "cut": False, "cut_label": "", "insertions": 0, "deletions": 0,
         "files_readable": reads_files(sc, r), "files_why": "" if reads_files(sc, r) else NO_FILES}
    review = _review_brief(o)
    if review is not None:
        review = {**review, "by": o.review_by, "text": texts.get(o.review_ref, "")[:TEXT_SHOWN],
                  "last_refusal": texts.get(o.review_refused[-1], "")[:TEXT_SHOWN] if o.review_refused else ""}
    checks = _checks_brief(o)
    if checks is not None:
        checks = {**checks, "said": _outside(texts.get(o.checks_said_ref, ""))}
    return {"pull": {**_pull_json(sc, r, o, texts), "head": span.head if span is not None else "",
                     "fork": span.base if span is not None else "", "review": review, "checks": checks,
                     "done_when": texts.get(o.done_when_ref, "")[:TEXT_SHOWN],
                     "result": texts.get(o.result_ref, "")[:TEXT_SHOWN],
                     "milestones": _milestone_json(o, texts), "said": _outside(texts.get(o.pull_said_ref, ""))},
            "commits": [_commit_json(sc, r, k, texts) for k in ahead], **diff}


def _remark_json(x: Any) -> dict[str, Any]:
    """Un échange venu de l'hôte : ses mots et le compte qui les a écrits là-bas, des données d'un inconnu
    (``outside``) ; ``from_here`` : il a été publié d'ici, sous le compte du jeton."""
    return {"id": x.id, "at": millis(x.at), "from_here": bool(x.mark), "outside": True,
            "account": _outside(x.author, 80), "text": x.body[:TEXT_SHOWN]}


async def pull_host(call: Call) -> dict[str, Any]:
    """``GET …/code/pull/hote`` : ce que l'hôte est seul à savoir d'une pull request, relu maintenant — son titre
    et son texte tels qu'ils y sont, ses échanges (commentaires et relectures), ses vérifications une à une, la fin
    du journal d'un échec. Tout y est une donnée d'un inconnu. Rien n'en va au journal."""
    sc, r = _opened(call)
    p = r.p
    o = _pull_named(call, p)
    host = _host(call, p)
    if host is None or not o.pull:
        raise Denied(409, NO_REMOTE)
    _host_read(call)
    seen = await host.pull(p.remote, o.branch)
    if seen.error or seen.number != o.pull:
        return {"number": o.pull, "error": (seen.error or NO_REMOTE)[:300], "title": None, "body": None,
                "head": "", "mergeable": None, "talk": [], "checks": None}
    talk = await host.talk(p.remote, o.pull, pull=True)
    checks = await _checks_read(host, p, seen.sha) if seen.sha else None
    return {"number": o.pull, "error": talk.error[:300], "title": _outside(seen.title, 400),
            "body": _outside(seen.body), "head": seen.sha, "mergeable": seen.mergeable,
            "state": seen.state, "at": millis(seen.at), "read_at": millis(seen.read_at),
            "talk": [_remark_json(x) for x in talk.remarks], "checks": checks}


# ── Fusionner : le geste d'une personne ───────────────────────────────────


async def fuse(call: Call) -> dict[str, Any]:
    """``POST …/code/pull/fusionner`` : fusionner une pull request chez l'hôte — le propriétaire du projet, ou qui
    s'occupe d'elle, et personne d'autre. ``head`` nomme le commit lu : si sa branche a bougé, rien ne part (409).
    La fusion est demandée ; le moteur l'apprend en relisant l'hôte, comme toute fusion."""
    sc, r = _opened(call)
    _steers(r)
    if not r.reader.settles:
        raise Denied(403, NOT_MERGER)
    o = _pull_named(call, r.p)
    head = call.arg("head", limit=40)
    if not _FULL_SHA.match(head):
        raise Denied(400, HEAD_NEEDED, {"head": "valeur requise"})
    if why := merge_refusal(r, o, sc.frame.now):
        raise Denied(409, why)
    got = done(await call.act(MERGE_ACTION, form(fixed={"objective": str(o.id), "head": head}),
                              subject=str(r.p.id)))
    return {**got, "asked": True, "number": o.pull}


# ── Issues ────────────────────────────────────────────────────────────────


def _issue_veil(r: Reach, item: Item | None) -> str:
    """Pourquoi les textes d'une issue ne se lisent pas (vide : ils se lisent). Celle d'un ticket suit son ticket ;
    celle qu'aucun ticket ne reflète encore est le texte d'un inconnu : pour qui peut la trancher seulement."""
    if item is not None:
        return tracker.veiled(r.reader, item)
    return "" if r.reader.settles else tracker.PROPOSED_VEIL


def _issue_json(r: Reach, page: str, number: int, seen: Any, item: Item | None,
                texts: Mapping[str, str]) -> dict[str, Any]:
    veil = _issue_veil(r, item)
    state = seen.state if seen is not None else ""
    label = ISSUE_DROPPED if seen is not None and seen.dropped else ISSUE_WORDS.get(state, state)
    return {"number": number, "url": f"{page}/issues/{number}" if page else "",
            "title": _outside(seen.title, 400) if seen is not None and not veil else None, "veiled": veil,
            "veiled_label": VEIL_WORDS.get(veil, ""), "state": state, "state_label": label,
            "dropped": bool(seen is not None and seen.dropped),
            "labels": [x for x in (_outside(t, 40) for t in (seen.labels if seen is not None and not veil else ()))
                       if x is not None],
            "comments": seen.comments if seen is not None else 0, "at": millis(seen.at) if seen is not None else 0,
            "from_here": bool(seen is not None and seen.mark),
            "account": _outside(seen.author, 80) if seen is not None and not veil else None,
            "ticket": _ticket_brief(r, item, texts)}


async def _issues_read(call: Call, p: Project) -> tuple[dict[int, Any], str]:
    """Les issues que l'hôte dit, par numéro, et pourquoi il ne les dit pas (vide : il les a dites)."""
    host = _host(call, p)
    if host is None:
        return {}, NO_REMOTE
    _host_read(call)
    got = await host.issues(p.remote)
    return ({x.number: x for x in got.items}, "") if not got.error else ({}, got.error[:300])


async def issues(call: Call) -> dict[str, Any]:
    """``GET …/code/issues`` : les issues du dépôt, relues chez l'hôte, chacune avec le ticket qui la reflète et son
    étape. Si l'hôte ne répond pas, celles que ses tickets connaissent, sans leur état (``error`` le dit)."""
    sc, r = _opened(call)
    p = r.p
    seen, error = await _issues_read(call, p)
    known = {x.issue: x for x in p.board.items if x.list_name == c.TICKETS and x.issue}
    numbers = sorted({*seen, *known}, key=lambda n: (-(seen[n].at if n in seen else 0), -n))
    state = call.arg("state", limit=10)
    if state not in ("", ISSUE_OPEN, ISSUE_CLOSED):
        raise Denied(400, "« state » : open, closed, ou rien.", {"state": "open, closed, ou rien"})
    if state:
        numbers = [n for n in numbers if n in seen and seen[n].state == state]
    page, size = _paged(call)
    shown = numbers[(page - 1) * size: page * size]
    items = {n: known.get(n) or _issue_ticket(p, n) for n in shown}
    texts = _texts(call, _ticket_refs(items.values()))
    where = repo_page(p) if _host(call, p) is not None else ""
    return {"total": len(numbers), "page": page, "size": size, "error": error,
            "items": [_issue_json(r, where, n, seen.get(n), items[n], texts) for n in shown]}


async def issue(call: Call) -> dict[str, Any]:
    """``GET …/code/issue`` : une issue — son état chez l'hôte, ses étiquettes, son texte et ses échanges (pour qui
    peut la lire), le ticket qui la reflète et son étape."""
    sc, r = _opened(call)
    p = r.p
    number = call.number("number", 0, 0)
    seen, error = await _issues_read(call, p)
    item = _issue_ticket(p, number)
    if number <= 0 or (number not in seen and item is None):
        raise missing()
    texts = _texts(call, _ticket_refs([item]))
    found = seen.get(number)
    out = _issue_json(r, repo_page(p) if _host(call, p) is not None else "", number, found, item, texts)
    readable = not out["veiled"]
    talk = await _host(call, p).talk(p.remote, number) if found is not None and readable else None
    return {**out, "error": error or (talk.error[:300] if talk is not None else ""),
            "body": _outside(found.body) if found is not None and readable else None,
            "talk": [_remark_json(x) for x in (talk.remarks if talk is not None else ())]}


# ── CI ────────────────────────────────────────────────────────────────────


def _run_json(x: Any) -> dict[str, Any]:
    seconds = (x.at - x.started) // 1_000_000 if x.at and x.started and x.at >= x.started else 0
    return {"name": _outside(x.name, 80), "state": x.state, "state_label": CHECK_WORDS.get(x.state, x.state),
            "started": millis(x.started), "at": millis(x.at), "seconds": seconds}


async def _checks_read(host: Any, p: Project, sha: str) -> dict[str, Any]:
    """Les vérifications d'un commit, relues chez l'hôte : son état, chacune d'elles, et la fin du journal d'un
    échec — des données d'un inconnu."""
    got = await host.checks(p.remote, sha)
    if got.error:
        return {"sha": sha, "state": "", "state_label": "", "error": got.error[:300], "at": 0, "read_at": 0,
                "runs": [], "failed": [], "log": None}
    log = await host.check_log(p.remote, sha) if got.state == CHECKS_FAILED else None
    return {"sha": sha, "state": got.state, "state_label": CHECK_WORDS.get(got.state, got.state), "error": "",
            "at": millis(got.at), "read_at": millis(got.read_at), "runs": [_run_json(x) for x in got.runs],
            "failed": [x for x in (_outside(n, 80) for n in got.failed) if x is not None],
            "log": {"name": _outside(log.name, 80), "tail": _outside(log.tail)}
            if log is not None and not log.error and log.tail.strip() else None}


async def ci(call: Call) -> dict[str, Any]:
    """``GET …/code/ci`` : les vérifications que le moteur suit, par commit — celles du commit de chaque pull
    request —, les plus récentes d'abord, avec le commit, sa branche et son objectif."""
    sc, r = _opened(call)
    p = r.p
    found = sorted((o for o in _pulled(p) if o.checks_sha), key=lambda o: -o.checks_at)[:CHECKS_SHOWN]
    port = _shop(call, r)
    # leurs commits, lus d'un coup dans l'histoire récente de toutes les branches ; un plus ancien se dit sans lui
    recent = await port.history(p.id, n=CHECKS_HISTORY) if port is not None and found else None
    wanted = {o.checks_sha for o in found}
    known = {k.sha: k for k in (recent.commits if recent is not None else ()) if k.sha in wanted}
    texts = _texts(call, [*_linked_refs(p, found), *_commit_refs(p, known.values()),
                          *(o.checks_said_ref for o in found)])
    return {"items": [{**(_checks_brief(o) or {}), "said": _outside(texts.get(o.checks_said_ref, "")),
                       "commit": _commit_json(sc, r, known[o.checks_sha], texts) if o.checks_sha in known else None,
                       "branch": o.branch, "objective": _objective_brief(o, texts), "pull": _pull_brief(sc, r, o)}
                      for o in found]}


async def ci_commit(call: Call) -> dict[str, Any]:
    """``GET …/code/ci/commit`` : les vérifications d'un commit de ce dépôt, relues chez l'hôte, une à une, et la
    fin du journal d'un échec."""
    sc, r = _opened(call)
    p = r.p
    port = _shop(call, r)
    sha = call.arg("sha", limit=40)
    found = await port.change(p.id, sha) if port is not None and _SHA.match(sha) else None
    if found is None:
        raise missing()  # seulement un commit que ce dépôt connaît
    host = _host(call, p)
    if host is None:
        raise Denied(409, NO_REMOTE)
    _host_read(call)
    o = _objective_for(p, found.commit)
    texts = _texts(call, [*_commit_refs(p, [found.commit]), *_linked_refs(p, [o])])
    return {**await _checks_read(host, p, found.commit.sha), "commit": _commit_json(sc, r, found.commit, texts),
            "linked": _linked(sc, r, o, texts)}


def routes(api: MeApiBase) -> list[Route]:
    r = api.route
    return [r(CODE, summary), r(CODE + "/fichiers", tree), r(CODE + "/fichier", blob),
            r(CODE + "/commits", commits), r(CODE + "/commit", commit), r(CODE + "/branches", branches),
            r(CODE + "/branche", branch), r(CODE + "/pulls", pull_list), r(CODE + "/pull", pull),
            r(CODE + "/pull/hote", pull_host), r(CODE + "/pull/fusionner", fuse, write=True),
            r(CODE + "/issues", issues), r(CODE + "/issue", issue), r(CODE + "/ci", ci),
            r(CODE + "/ci/commit", ci_commit)]
