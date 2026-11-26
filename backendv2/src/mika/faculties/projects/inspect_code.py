"""L'onglet Code de la fiche d'un projet (``git``, ADR 0288, 0297), en sous-vues comme l'écran Projets du client web :
Fichiers, Commits, Pull requests, Branches, Issues, CI (``?vue=``) ; « le dépôt distant » (``vue=distant``) garde ce
que montrait l'onglet Dépôt (``inspect_git.py`` : l'atelier face au distant, pousser, récupérer, ses réglages).

**D'où vient chaque chose** — comme pour l'API par personne (``app/domains/projects/api/code.py``), qui lit d'ici ses mots :
les pull requests, leur CI et leur relecture viennent du journal ; les fichiers, les commits, les branches et
les diffs, de l'atelier, par le port, à une référence (jamais l'arbre de travail) ; ce que l'hôte est seul à savoir
(le texte d'une pull request et ses échanges, ses vérifications une à une, la fin du journal d'un échec, les issues et
leurs échanges) se lit chez lui **par une lecture gardée et bornée** (``hosted``) : gardée ``HOST_KEPT_S`` secondes
(une erreur, ``HOST_ERROR_KEPT_S``), « relire » (``frais``, un jeton) la refait une fois, et la console n'en fait pas plus de
``HOST_READS`` par minute. Tout texte de l'hôte, le
contenu d'un fichier et un diff sont des données : la console les montre en texte brut.

**Ce qui est pur** et que l'API lit aussi : le diff mis en texte puis relu (``diff_text``, ``diff_rows``). Les règles
que la vue lit vivent chez leur sujet : l'objectif d'un commit ou d'une branche (``faculty.objective_for``,
``faculty.objective_on``), le ticket d'une issue (``issues.issue_ticket`` ; celui d'un objectif est
``faculty.ticket_held``), où en est une pull request et celles d'un projet (``pulls.pull_stage``, ``pulls.pulled``).
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from typing import Any, NamedTuple, TypeVar
from urllib.parse import quote
from weakref import WeakKeyDictionary

from mika.contracts import projects as c
from mika.contracts import self_ as self_c
from mika.faculties.projects import merge, pulls
from mika.faculties.projects.actions import can_deposit
from mika.faculties.projects.faculty import (
    Objective,
    Project,
    ProjectsState,
    by_pulls,
    objective_for,
    objective_on,
    repo_page,
)
from mika.faculties.projects.inspect_common import stored_text, stored_texts
from mika.faculties.projects.inspect_merge import BLOCK_WORDS, REFUSED_WORDS
from mika.faculties.projects.issues import issue_ticket
from mika.faculties.projects.pulls import (
    CLOSED,
    MERGED,
    OPEN,
    PROPOSED,
    READY,
    pull_key,
    pull_named,
    pull_order,
    pull_stage,
    pulled,
)
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Block,
    Code,
    Column,
    Disclosure,
    Fields,
    InspectContext,
    Note,
    Ref,
    Row,
    Table,
    Text,
    When,
    plural,
    size_fr,
)
from mika.ports.workshop import (
    BASE_BRANCH,
    CHECKS_FAILED,
    CHECKS_NONE,
    CHECKS_PASSED,
    CHECKS_PENDING,
    ENTRY_DIR,
    ENTRY_FILE,
    ENTRY_LINK,
    ENTRY_MODULE,
    FILE_ADDED,
    FILE_DELETED,
    FILE_MODIFIED,
    ISSUE_CLOSED,
    ISSUE_OPEN,
    LINE_ADDED,
    LINE_REMOVED,
    LINE_SAME,
    PULL_OPEN,
    Commit,
    FileDiff,
    OutsideWorkshop,
    hidden_path,
)

T = TypeVar("T")

# ── Ses mots (l'API par personne les sert aussi) ──────────────────────────

ENTRY_WORDS = {ENTRY_DIR: "dossier", ENTRY_FILE: "fichier", ENTRY_LINK: "lien symbolique", ENTRY_MODULE: "sous-module"}
FILE_WORDS = {FILE_ADDED: "ajouté", FILE_MODIFIED: "modifié", FILE_DELETED: "supprimé"}
#: où en est une pull request (``pulls.pull_stage``), en mots
PULL_WORDS = {PROPOSED: "proposée, elle attend un accord", OPEN: "ouverte", READY: "prête à fusionner",
              MERGED: "fusionnée", CLOSED: "fermée sans fusion"}
CHECK_WORDS = {CHECKS_NONE: "aucune vérification", CHECKS_PENDING: "en cours", CHECKS_PASSED: "passée",
               CHECKS_FAILED: "en échec"}
ISSUE_WORDS = {ISSUE_OPEN: "ouverte", ISSUE_CLOSED: "fermée", "": "état inconnu"}
ISSUE_DROPPED = "fermée, non prévue"
#: pourquoi un fichier ne dit pas son contenu
BINARY, TOO_BIG = "Un fichier binaire : son contenu ne s'affiche pas.", "Un fichier trop gros pour s'afficher ici."
LINK, MODULE = "Un lien symbolique : il ne se suit pas.", "Un sous-module : il ne s'ouvre pas d'ici."
HIDDEN_FILE = "Un fichier caché : son diff ne s'affiche pas."
HIDDEN = ("Un fichier ou un dossier caché (son nom commence par un point) ne se lit pas d'ici : ni son contenu, ni "
          "son diff.")
DIFF_CUT = "Ce diff est trop long pour tenir ici : les fichiers coupés se relisent un à un (« path »)."

# ── Ses sous-vues, et les titres de leurs blocs (la fiche dessinée les retrouve par eux) ──

VIEW = "vue"
FILES, COMMITS, PULLS, BRANCHES, ISSUES, CI, REMOTE = "fichiers", "commits", "pulls", "branches", "issues", "ci", "distant"
VIEWS = (FILES, COMMITS, PULLS, BRANCHES, ISSUES, CI)
REPO_TITLE, TREE_TITLE, FILE_TITLE, SOURCE_TITLE = "Le dépôt", "Ses fichiers", "Le fichier", "Son contenu"
HISTORY_TITLE, COMMITS_TITLE, COMMIT_TITLE, MESSAGE_TITLE = "Son historique", "Ses commits", "Le commit", "Son message"
CHANGED_TITLE, DIFF_TITLE = "Fichiers changés", "Diff de "
BRANCHES_TITLE, BRANCH_TITLE, AHEAD_TITLE = "Ses branches", "La branche", "Ce qu'elle a d'avance"
PULLS_TITLE, PULL_TITLE, HOST_PULL_TITLE, HOST_BODY_TITLE = ("Ses pull requests", "La pull request",
                                                             "Chez l'hôte", "Son texte chez l'hôte")
TALK_TITLE, RUNS_TITLE, LOG_TITLE = "Ses échanges chez l'hôte", "Ses vérifications", "La fin du journal"
ISSUES_TITLE, ISSUE_TITLE, ISSUE_BODY_TITLE = "Ses issues", "L'issue", "Son texte"
TRACKED_TITLE = "Les vérifications suivies"
DEPOSIT_TITLE = "Déposer un fichier dans l'atelier"

#: un fichier rendu, au plus (octets) ; les lignes d'un diff, au plus ; une page de commits ; l'histoire courte d'un
#: fichier ; les vérifications suivies montrées, et l'histoire où l'on cherche leurs commits
FILE_BYTES, DIFF_LINES, PAGE, FILE_HISTORY = 400_000, 3000, 30, 10
CHECKS_SHOWN, CHECKS_HISTORY = 40, 300
#: une lecture de l'hôte faite pour la console se garde tant (secondes), une erreur moins longtemps (comme l'adaptateur
#: les garde) ; « relire » la refait ; et la console n'en fait pas plus de tant par minute (au-delà, elle dit d'attendre)
HOST_KEPT_S, HOST_ERROR_KEPT_S, HOST_READS, HOST_WINDOW_S = 120, 30, 30, 60
#: ce qu'une sous-vue ouvre dans son adresse, que « relire » garde
AIMS = ("ref", "chemin", "sha", "pr", "branche", "issue")
HOST_BUSY = "Trop de lectures de l'hôte d'affilée : relis dans une minute."
NO_HOST = "Ce projet n'a pas de dépôt distant que l'on sache lire."

_SECOND = 1_000_000
_SHA = re.compile(r"^[0-9a-f]{4,40}$")
_REF = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")
_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


# ── Un diff, mis en texte puis relu ───────────────────────────────────────


class DiffRow(NamedTuple):
    """Une ligne d'un diff relu : sa sorte (``LINE_*``, ou ``"@"`` pour l'en-tête d'un passage), son numéro avant et
    après (0 : elle n'y est pas), son texte."""

    kind: str
    old: int
    new: int
    text: str


def diff_text(f: FileDiff) -> str:
    """Les passages d'un fichier en diff unifié — leur en-tête, puis chaque ligne précédée de sa sorte —, la forme que
    lit la console en MCP et que ``diff_rows`` relit."""
    out: list[str] = []
    for h in f.hunks:
        out.append(h.header)
        out += [f"{x.kind}{x.text}" for x in h.lines]
    return "\n".join(out)


def diff_rows(text: str) -> list[DiffRow]:
    """Un diff unifié relu ligne à ligne, ses numéros avant et après repris de l'en-tête de chaque passage."""
    rows: list[DiffRow] = []
    old = new = 0
    for line in text.split("\n") if text else ():
        m = _HUNK.match(line)
        if m is not None:
            old, new = int(m.group(1)), int(m.group(2))
            rows.append(DiffRow("@", 0, 0, line))
        elif line.startswith(LINE_ADDED):
            rows.append(DiffRow(LINE_ADDED, 0, new, line[1:]))
            new += 1
        elif line.startswith(LINE_REMOVED):
            rows.append(DiffRow(LINE_REMOVED, old, 0, line[1:]))
            old += 1
        elif line.startswith("\\"):
            continue  # « \ No newline at end of file »
        else:
            rows.append(DiffRow(LINE_SAME, old, new, line[1:] if line.startswith(LINE_SAME) else line))
            old, new = old + 1, new + 1
    return rows


# ── La lecture de l'hôte, gardée et bornée ────────────────────────────────


class _Kept:
    """Ce que la console a lu chez un hôte : par clé, (quand, quoi) ; quand elle l'a joint, dans la dernière minute ;
    et les « relire » déjà faits, (jeton, clé)."""

    def __init__(self) -> None:
        self.reads: dict[tuple[Any, ...], tuple[int, Any]] = {}
        self.spent: deque[int] = deque()
        self.redone: dict[tuple[str, tuple[Any, ...]], None] = {}


_KEPT: WeakKeyDictionary[Any, _Kept] = WeakKeyDictionary()
#: les lectures gardées, au plus, par hôte (et autant de « relire » faits)
_KEPT_MAX = 200


def _kept(host: Any) -> _Kept | None:
    try:
        return _KEPT.setdefault(host, _Kept())
    except TypeError:  # un hôte qu'on ne peut pas suivre (aucun dans le moteur)
        return None


def _again(kept: _Kept, fresh: str, key: tuple[Any, ...]) -> bool:
    """Ce « relire » (``fresh``, son jeton) vaut-il encore pour cette lecture ? Une fois : il est alors compté fait."""
    if not fresh or (fresh, key) in kept.redone:
        return False
    kept.redone[(fresh, key)] = None
    while len(kept.redone) > _KEPT_MAX:
        kept.redone.pop(next(iter(kept.redone)))
    return True


async def hosted(host: Any, key: tuple[Any, ...], now: int, fetch: Callable[[], Awaitable[T]],
                 *, fresh: str = "") -> tuple[T | None, int]:
    """Une lecture de l'hôte pour la console : celle qu'elle a déjà faite il y a moins de ``HOST_KEPT_S`` secondes
    (une erreur : ``HOST_ERROR_KEPT_S``), sinon une nouvelle — pas plus de ``HOST_READS`` par minute. « Relire »
    (``fresh`` : son jeton, ``fresh_from``) la refait une fois ; recharger la page qui le garde dans son adresse ne la
    refait plus. Rend (ce qui est lu, quand) ; ``(None, 0)`` : la borne est atteinte."""
    kept = _kept(host)
    if kept is None:
        return await fetch(), now
    got = kept.reads.get(key)
    lasts = HOST_ERROR_KEPT_S if got is not None and getattr(got[1], "error", "") else HOST_KEPT_S
    if got is not None and (fresh, key) in kept.redone:
        fresh = ""  # déjà relue pour ce jeton
    if got is not None and not fresh and now - got[0] < lasts * _SECOND:
        return got[1], got[0]
    while kept.spent and now - kept.spent[0] >= HOST_WINDOW_S * _SECOND:
        kept.spent.popleft()
    if len(kept.spent) >= HOST_READS:
        return (got[1], got[0]) if got is not None else (None, 0)
    kept.spent.append(now)
    _again(kept, fresh, key)
    value = await fetch()
    kept.reads[key] = (now, value)
    if len(kept.reads) > _KEPT_MAX:
        for old in sorted(kept.reads, key=lambda k: kept.reads[k][0])[:len(kept.reads) - _KEPT_MAX]:
            del kept.reads[old]
    return value, now


def fresh_from(ctx: InspectContext) -> str:
    """« Relire » (``frais``) : son jeton, l'instant de la page qui l'a offert ; vide : rien à relire."""
    raw = ctx.param("frais")
    return raw if raw.isdecimal() and len(raw) <= 20 else ""


def read_again(host: Any, fresh: str, key: tuple[Any, ...]) -> bool:
    """La lecture générale de l'hôte (``host.read``, gardée par l'adaptateur) se refait-elle pour ce « relire » ? Une
    fois par jeton : recharger la page ne la refait plus."""
    kept = _kept(host)
    return bool(fresh) if kept is None else _again(kept, fresh, key)


def _host(p: Project, ctx: InspectContext) -> Any:
    host = ctx.ports.get("repo_host")
    return host if p.remote and host is not None and host.handles(p.remote) else None


# ── Les liens d'une sous-vue à l'autre ────────────────────────────────────


def here(p: Project, text: str, **params: Any) -> Ref:
    """Un lien vers une sous-vue de Code, avec ce qu'elle ouvre (un paramètre vide ne s'écrit pas)."""
    kept = tuple((k, str(v)) for k, v in params.items() if v not in (None, "", 0))
    return Ref("subject", f"project/{p.id}", text, (("onglet", "git"), *kept))


def _ref(ctx: InspectContext) -> str:
    """La branche (ou le commit) que l'adresse nomme ; illisible : rien."""
    ref = ctx.param("ref")
    return ref if _REF.match(ref) and ".." not in ref else ""


def _path(ctx: InspectContext) -> str:
    """Le chemin que l'adresse nomme, réduit (ni « . », ni « / » de trop)."""
    return "/".join(x for x in ctx.param("chemin").replace("\\", "/").split("/") if x and x != ".")


def _who(k: Commit, her: str) -> str:
    return her if k.local else (k.author or "—")


def _commit_row(p: Project, k: Commit, texts: Mapping[str, str], her: str, *, ref: str = "") -> Row:
    """Un commit en une ligne : son empreinte (qui l'ouvre), son message, quand, qui, sa branche, ses comptes, s'il
    vient d'ailleurs (un commit du dépôt distant), s'il est une fusion, l'objectif qui lui est lié."""
    o = objective_for(p, k)
    return Row((
        here(p, k.sha[:7], vue=COMMITS, ref=ref, sha=k.sha), Text(k.title, clamp=200),
        When(k.at) if k.at else "—", _who(k, her), Text(k.branch or "—", "mono"), k.files, k.insertions,
        k.deletions, "elle" if k.local else "ailleurs",
        "oui" if len(k.parents) > 1 else "non",
        f"n° {o.id} · {stored_text(texts, o.text_ref)}"[:120] if o is not None else "—"),
        href=here(p, "", vue=COMMITS, ref=ref, sha=k.sha))


COMMIT_COLUMNS = (Column("commit", "fit"), Column("message"), Column("quand", "fit"), Column("auteur", "fit"),
                  Column("branche", "fit"), Column("fichiers", "num"), Column("ajoutées", "num"),
                  Column("retirées", "num"),
                  Column("signé", "fit"), Column("fusion", "fit"), Column("objectif"))


def _commit_texts(ctx: InspectContext, p: Project, commits: Iterable[Commit]) -> Mapping[str, str]:
    found = [objective_for(p, k) for k in commits]
    return stored_texts(ctx, (o.text_ref for o in found if o is not None))


def _changed(p: Project, files: Sequence[FileDiff]) -> list[Block]:
    """Les fichiers d'un diff (leur chemin, ce qu'ils sont devenus, leurs comptes), puis le diff de chacun ; un
    fichier caché, binaire ou coupé se dit sans ses passages."""
    rows = []
    for f in files:
        why = HIDDEN_FILE if hidden_path(f.path) else "binaire" if f.binary else "coupé" if f.cut else ""
        rows.append((Text(f.path, "mono"), FILE_WORDS.get(f.status, f.status), f.insertions, f.deletions,
                     Text(why, "muted") if why else "—"))
    blocks: list[Block] = [Table((Column("chemin"), Column("devenu", "fit"), Column("ajoutées", "num"),
                                  Column("retirées", "num"), Column("sans passages", "fit")), tuple(rows),
                                 title=CHANGED_TITLE, empty="aucun fichier n'y change")]
    if any(f.cut for f in files):
        blocks.append(Note(DIFF_CUT, "muted"))
    blocks += [Code(diff_text(f), title=f"{DIFF_TITLE}{f.path}", lang="diff") for f in files
               if f.hunks and not hidden_path(f.path)]
    return blocks


# ── La vue : son en-tête commun, puis la sous-vue demandée ────────────────


async def code_view(p: Project, s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    """Code, en sous-vues (``?vue=``) : Fichiers (par défaut), Commits, Pull requests, Branches, Issues, CI. Un
    ancien lien vers un commit (``?commit=``) ouvre Commits."""
    view = ctx.param(VIEW)
    if ctx.param("commit") and view not in VIEWS:
        view = COMMITS
    view = view if view in VIEWS else FILES
    port = ctx.ports.get("workshop")
    there = port is not None and port.exists(p.id)
    host = _host(p, ctx)
    fresh = fresh_from(ctx)
    seen = await host.read(p.remote, p.branch, fresh=read_again(host, fresh, ("read", p.remote, p.branch)),
                           since=p.remote_at) if host is not None else None
    branches = await port.branches(p.id) if there else []
    last = await port.history(p.id, n=1) if there else None
    found = pulled(p)
    head: list[Block] = [Fields((
        ("vue", view), ("branche de base", BASE_BRANCH),
        ("dépôt distant", Ref.url(repo_page(p), re.sub(r"^https?://", "", repo_page(p))) if p.remote else "aucun"),
        ("lu chez l'hôte", When(seen.read_at) if seen is not None and seen.read_at else "—"),
        ("relire", here(p, "relire chez l'hôte", vue=view, **{k: ctx.param(k) for k in AIMS}, frais=ctx.now)
         if host is not None else "—"),
        ("commits", last.total if last is not None else 0), ("branches", len(branches)),
        ("pull requests ouvertes", sum(1 for o in found if o.pull_state == PULL_OPEN)),
        ("pull requests prêtes", sum(1 for o in found if pull_stage(p, o) == READY)),
        ("issues ouvertes", seen.open_issues if seen is not None and not seen.error else "—"),
        ("vérifications en échec", sum(1 for o in found if o.pull_state == PULL_OPEN and o.checks == CHECKS_FAILED)),
        ("le dépôt distant", here(p, "l'atelier face au distant", vue=REMOTE)),
        ("ses branches", Text(" ".join(b.name for b in branches) or "—", "mono"))), title=REPO_TITLE, columns=3)]
    if not there and view in (FILES, COMMITS, BRANCHES):
        return [*head, Note("Pas encore de dépôt : il s'ouvre à la première exécution qui écrit (ou au premier dépôt "
                            "de fichier, ou en récupérant le dépôt distant).", "muted"), *_deposit(s, frame, p, ctx)]
    if view == FILES:
        return [*head, *await _files(p, s, frame, ctx, port, branches)]
    if view == COMMITS:
        return [*head, *await _commits(p, frame, ctx, port, branches)]
    if view == PULLS:
        return [*head, *await _pulls(p, frame, ctx, port if there else None, host, fresh)]
    if view == BRANCHES:
        return [*head, *await _branches(p, frame, ctx, port, branches)]
    if view == ISSUES:
        return [*head, *await _issues(p, ctx, host, fresh)]
    return [*head, *await _checks(p, frame, ctx, port if there else None, host, fresh)]


def _deposit(s: ProjectsState, frame: Frame, p: Project, ctx: InspectContext) -> list[Block]:
    if not can_deposit(s, frame, str(p.id), ctx.ports):
        return []
    return [Disclosure(DEPOSIT_TITLE, (ActionSlot("projects.deposer", title="Déposer un fichier", compact=True),))]


def _her(frame: Frame) -> str:
    """Son nom, tel que sa persona le dit : celui qui signe les commits de l'atelier."""
    return self_c.name_of(frame.get(self_c.PERSONA))


# ── Fichiers ──────────────────────────────────────────────────────────────


async def _files(p: Project, s: ProjectsState, frame: Frame, ctx: InspectContext, port: Any,
                 branches: Sequence[Any]) -> list[Block]:
    """L'arborescence à une branche (ses dossiers ouverts jusqu'au chemin demandé), le fichier choisi — ou le README
    du dossier —, son dernier commit et son historique, et « Déposer un fichier »."""
    names = [b.name for b in branches]
    ref = _ref(ctx) or BASE_BRANCH
    notes: list[Block] = []
    if ref not in names and not _SHA.match(ref):
        notes.append(Note(f"Aucune branche « {ref[:60]} » dans ce dépôt : voici « {BASE_BRANCH} ».", "warn"))
        ref = BASE_BRANCH
    path = _path(ctx)
    if path and hidden_path(path):
        notes.append(Note(HIDDEN, "warn"))
        path = ""
    rows: list[Row] = []
    chosen = ""  # le fichier ouvert
    readme = ""
    readme_home = False

    async def level(folder: str, depth: int) -> bool:
        nonlocal chosen, readme, readme_home
        try:
            entries = await port.ref_tree(p.id, ref, folder or ".")
        except (OutsideWorkshop, FileNotFoundError):
            return False
        if entries is None:
            return False
        shown = [e for e in entries if not hidden_path(e.path)]
        for e in shown:
            on_path = path == e.path or path.startswith(e.path + "/")
            rows.append(Row((here(p, e.path.rsplit("/", 1)[-1], vue=FILES, ref=ref, chemin=e.path),
                             ENTRY_WORDS.get(e.kind, e.kind), size_fr(e.size) if e.kind == ENTRY_FILE else "",
                             depth, "ouvert" if on_path else ""),
                            href=here(p, "", vue=FILES, ref=ref, chemin=e.path)))
            if on_path and e.kind == ENTRY_DIR:
                await level(e.path, depth + 1)
            elif on_path:
                chosen = e.path
        if len(entries) > len(shown):
            hidden = len(entries) - len(shown)
            rows.append(Row((Text(plural(hidden, "entrée cachée", "entrées cachées"), "muted"), "caché", "", depth,
                             "")))
        # le README du dossier demandé (la racine si rien ne l'est) : il s'ouvre quand aucun fichier ne l'est
        if folder == path or (not path and not folder):
            readme = next((e.path for e in shown if e.kind == ENTRY_FILE and e.path.rsplit("/", 1)[-1].lower()
                           in ("readme.md", "readme", "readme.txt")), "")
            readme_home = not folder
        return True

    if not await level("", 0):
        return [*notes, Note(f"La branche « {ref[:60]} » ne se lit pas.", "warn"), *_deposit(s, frame, p, ctx)]
    blocks: list[Block] = [*notes, Table((Column("nom"), Column("sorte", "fit"), Column("taille", "num"),
                                          Column("niveau", "num"), Column("ouvert", "fit")), tuple(rows),
                                         title=TREE_TITLE, empty="ce dossier est vide",
                                         caption=f"Le dépôt à la branche « {ref} » : un dossier s'ouvre, un fichier "
                                                 "se lit à côté.")]
    shown_path = chosen or readme
    current = next((b.name for b in branches if b.current), "")
    if shown_path:
        blocks += await _blob(p, frame, ctx, port, ref, shown_path, home=not chosen and readme_home,
                              readme=not chosen, here=ref == current)
    return [*blocks, *_deposit(s, frame, p, ctx)]


async def _blob(p: Project, frame: Frame, ctx: InspectContext, port: Any, ref: str, path: str, *, home: bool,
                readme: bool, here: bool) -> list[Block]:
    """Un fichier à une référence : ce qu'il est, son texte s'il en a un qui s'affiche, son historique ; et, à la
    branche où se trouve l'atelier (``here``), de quoi rapatrier sa copie telle quelle."""
    try:
        found = await port.ref_file(p.id, ref, path, FILE_BYTES)
        history = await port.history(p.id, ref, path=path, n=FILE_HISTORY) if found is not None else None
    except (OutsideWorkshop, FileNotFoundError):
        found, history = None, None
    if found is None:
        return [Note(f"« {path[:200]} » ne se lit pas à la branche « {ref} ».", "warn")]
    why = BINARY if found.binary else TOO_BIG if found.too_big else LINK if found.kind == ENTRY_LINK else \
        MODULE if found.kind == ENTRY_MODULE else ""
    lines = found.text.count("\n") + (1 if found.text and not found.text.endswith("\n") else 0)
    page = repo_page(p) if _host(p, ctx) is not None else ""
    commits = history.commits if history is not None else ()
    texts = _commit_texts(ctx, p, commits)
    her = _her(frame)
    blocks: list[Block] = [Fields((
        ("chemin", Text(found.path, "mono")), ("branche", Text(ref, "mono")),
        ("sorte", ENTRY_WORDS.get(found.kind, found.kind)), ("lignes", lines if not why else "—"),
        ("poids", size_fr(found.size)), ("page d'accueil", "oui" if home else "non"),
        ("le readme du dossier", "oui" if readme else "non"), ("pourquoi rien", why or "—"),
        ("chez l'hôte", Ref.url(f"{page}/blob/{found.sha}/{quote(found.path)}", "voir chez l'hôte")
         if page else "—"),
        ("télécharger", Ref.download("project", str(p.id), "télécharger", found.path) if here else "—")),
        title=FILE_TITLE, columns=2)]
    if not why:
        blocks.append(Code(found.text, title=SOURCE_TITLE, lang=found.path.rsplit(".", 1)[-1].lower()
                           if "." in found.path.rsplit("/", 1)[-1] else ""))
    blocks.append(Table(COMMIT_COLUMNS, tuple(_commit_row(p, k, texts, her) for k in commits),
                        title=HISTORY_TITLE, empty="aucun commit ne le touche sur cette branche",
                        caption=f"{plural(history.total if history is not None else 0, 'commit', 'commits')} "
                                "l'ont touché."))
    return blocks


# ── Commits ───────────────────────────────────────────────────────────────


async def _commits(p: Project, frame: Frame, ctx: InspectContext, port: Any, branches: Sequence[Any]) -> list[Block]:
    """L'histoire d'une branche (``ref``), ou de toutes, page par page ; le commit choisi (``sha`` ; le premier
    sinon) : son message entier, ses fichiers changés et leur diff, face à son premier parent."""
    ref = _ref(ctx)
    if ref and ref not in [b.name for b in branches]:
        ref = ""
    first = await port.history(p.id, ref, n=1)
    pager = ctx.pager("page_commits", size=PAGE, total=first.total if first is not None else 0)
    history = await port.history(p.id, ref, n=pager.size, offset=pager.offset)
    commits = history.commits if history is not None else ()
    texts = _commit_texts(ctx, p, commits)
    her = _her(frame)
    blocks: list[Block] = [Table(COMMIT_COLUMNS, tuple(_commit_row(p, k, texts, her, ref=ref) for k in commits),
                                 title=COMMITS_TITLE, pager=pager, empty="aucun commit encore",
                                 caption=f"L'histoire de « {ref} »." if ref else "L'histoire de toutes ses branches, "
                                                                                 "du plus récent.")]
    sha = ctx.param("sha") or ctx.param("commit") or (commits[0].sha if commits else "")
    if not sha:
        return blocks
    found = await port.change(p.id, sha) if _SHA.match(sha) else None
    if found is None:
        return [*blocks, Note(f"Aucun commit « {sha[:12]} » dans ce dépôt.", "warn")]
    k = found.commit
    o = objective_for(p, k)
    page = repo_page(p) if _host(p, ctx) is not None else ""
    files = await port.diff_of(p.id, k.parents[0] if k.parents else "", k.sha, lines=DIFF_LINES) or ()
    rest = found.body[len(k.title):].strip() if found.body.startswith(k.title) else found.body.strip()
    blocks.append(Fields((
        ("commit", Text(k.sha, "mono")), ("titre", k.title), ("auteur", _who(k, her)),
        ("signé", "elle" if k.local else "ailleurs"), ("quand", When(k.at) if k.at else "—"),
        ("branche", Text(k.branch or "—", "mono")), ("fusion", "oui" if len(k.parents) > 1 else "non"),
        ("parents", Text(" ".join(x[:12] for x in k.parents) or "—", "mono")),
        ("objectif", o.id if o is not None else "—"), ("ticket", o.ticket if o is not None and o.ticket else "—"),
        ("ajoutées", sum(f.insertions for f in files)), ("retirées", sum(f.deletions for f in files)),
        ("chez l'hôte", Ref.url(f"{page}/commit/{k.sha}", "voir chez l'hôte") if page else "—")),
        title=COMMIT_TITLE, columns=2))
    if rest:
        blocks.append(Code(rest, title=MESSAGE_TITLE))
    return [*blocks, *_changed(p, files)]


# ── Branches ──────────────────────────────────────────────────────────────


async def _branches(p: Project, frame: Frame, ctx: InspectContext, port: Any, branches: Sequence[Any]) -> list[Block]:
    """Ses branches, la base d'abord — son objectif, son avance et son retard sur la base, son dernier commit — ; la
    branche choisie (``branche`` ; la première de travail sinon) : ses commits d'avance et ses fichiers changés."""
    found = [objective_on(p, b.name) for b in branches if not b.base]
    texts = stored_texts(ctx, (o.text_ref for o in found if o is not None))
    rows = []
    for b in branches:
        o = None if b.base else objective_on(p, b.name)
        rows.append(Row((
            here(p, b.name, vue=BRANCHES, branche=b.name), "oui" if b.base else "non", b.ahead, b.behind,
            Text(b.head.sha, "mono"), Text(b.head.title, clamp=200), When(b.head.at) if b.head.at else "—",
            o.id if o is not None else "—", f"{stored_text(texts, o.text_ref)}"[:120] if o is not None else "—",
            "oui" if b.current else "non"), href=here(p, "", vue=BRANCHES, branche=b.name)))
    blocks: list[Block] = [Table((Column("branche"), Column("base", "fit"), Column("avance", "num"),
                                  Column("retard", "num"), Column("dernier commit", "fit"), Column("message"),
                                  Column("quand", "fit"), Column("objectif", "fit"), Column("pour"),
                                  Column("courante", "fit")), tuple(rows), title=BRANCHES_TITLE,
                                 empty="ce dépôt n'a pas encore de branche",
                                 caption="Elle ouvre une branche par objectif (ou par ticket) et ne pousse jamais sur "
                                         f"« {BASE_BRANCH} » quand le projet passe par des pull requests.")]
    wanted = ctx.param("branche")
    chosen = next((b for b in branches if b.name == wanted), None) if wanted else \
        next((b for b in branches if not b.base), None)
    if wanted and chosen is None:
        return [*blocks, Note(f"Aucune branche « {wanted[:60]} » dans ce dépôt.", "warn")]
    if chosen is None or chosen.base:
        return blocks
    span = await port.span(p.id, chosen.name)
    ahead = span.commits if span is not None else ()
    her = _her(frame)
    labelled = [replace(k, branch=chosen.name) for k in ahead]
    ctexts = _commit_texts(ctx, p, labelled)
    blocks.append(Fields((("branche", Text(chosen.name, "mono")), ("avance", chosen.ahead),
                          ("retard", chosen.behind), ("tête", Text(span.head if span is not None else "", "mono"))),
                         title=BRANCH_TITLE, columns=2))
    blocks.append(Table(COMMIT_COLUMNS, tuple(_commit_row(p, k, ctexts, her) for k in labelled), title=AHEAD_TITLE,
                        empty="aucun commit d'avance sur la base"))
    if span is not None and ahead:
        files = await port.diff_of(p.id, span.base, span.head, lines=0) or ()
        blocks += _changed(p, files)[:1]
    return blocks


# ── Pull requests ─────────────────────────────────────────────────────────


async def _pulls(p: Project, frame: Frame, ctx: InspectContext, port: Any, host: Any, fresh: str) -> list[Block]:
    """Ses pull requests, telles que le journal les sait ; la choisie (``pr`` : son numéro, ou ``o<objectif>`` ; la
    première sinon) : sa branche et le commit à son bout (celui que nomme sa fusion), ses commits et son diff ; et, lu
    chez l'hôte, son titre et son texte, ses échanges, ses vérifications une à une, la fin du journal d'un échec."""
    order = pull_order(p)
    texts = stored_texts(ctx, (o.text_ref for o in order))
    rows = tuple(Row((
        here(p, f"n° {o.pull}" if o.pull else "proposée", vue=PULLS, pr=pull_key(o)), stored_text(texts, o.text_ref),
        PULL_WORDS[pull_stage(p, o)], Text(o.branch or "—", "mono"), CHECK_WORDS.get(o.checks, "—")
        if o.checks_sha else "—", When(o.pull_at) if o.pull_at else "—"), href=here(p, "", vue=PULLS, pr=pull_key(o)))
        for o in order)
    blocks: list[Block] = [Table((Column("n°", "fit"), Column("objectif"), Column("état", "fit"),
                                  Column("branche", "fit"), Column("vérifications", "fit"), Column("depuis", "fit")),
                                 rows, title=PULLS_TITLE,
                                 empty="aucune pull request : elle en ouvre une quand un objectif a du code à faire "
                                       "entrer" if by_pulls(p) else "ce projet ne passe pas par des pull requests")]
    wanted = ctx.param("pr")
    o = pull_named(p, wanted) if wanted else (order[0] if order else None)
    if o is None:
        return blocks + ([Note(f"Aucune pull request « {wanted[:20]} » dans ce projet.", "warn")] if wanted else [])
    span = await port.span(p.id, o.branch) if port is not None and o.branch else None
    ahead = [replace(k, branch=o.branch) for k in (span.commits if span is not None else ())]
    stage = pull_stage(p, o)
    block = merge.blocked(p, o, ctx.now)
    blocks.append(Fields((
        ("n°", o.pull or "—"), ("objectif", o.id), ("état", PULL_WORDS[stage]), ("étape", stage),
        ("branche", Text(o.branch or "—", "mono")), ("base", Text(p.branch, "mono")),
        ("tête", Text(span.head if span is not None else "", "mono")),
        ("fusion", BLOCK_WORDS.get(block, block) if block else "possible : elle attend ta fusion"),
        ("fusion refusée", REFUSED_WORDS.get(o.merge_refused, "") if o.merge_refused else "—"),
        ("chez l'hôte", Ref.url(pulls.pull_url(p, o), "voir chez l'hôte") if pulls.pull_url(p, o) else "—")),
        title=PULL_TITLE, columns=2))
    her = _her(frame)
    ctexts = _commit_texts(ctx, p, ahead)
    blocks.append(Table(COMMIT_COLUMNS, tuple(_commit_row(p, k, ctexts, her) for k in ahead), title=COMMITS_TITLE,
                        empty="sa branche n'a pas de commit d'avance"))
    if span is not None and ahead:
        blocks += _changed(p, await port.diff_of(p.id, span.base, span.head, lines=DIFF_LINES) or ())
    if host is None or not o.pull:
        return blocks
    return blocks + await _pull_host(p, o, ctx, host, fresh)


async def _pull_host(p: Project, o: Objective, ctx: InspectContext, host: Any, fresh: str) -> list[Block]:
    """Ce que l'hôte est seul à savoir d'une pull request, par la lecture gardée et bornée."""
    seen, at = await hosted(host, ("pull", p.remote, o.branch), ctx.now, lambda: host.pull(p.remote, o.branch),
                            fresh=fresh)
    if seen is None:
        return [Note(HOST_BUSY, "warn")]
    if seen.error or seen.number != o.pull:
        return [Note(f"L'hôte ne dit pas cette pull request : {(seen.error or NO_HOST)[:300]}", "warn")]
    out: list[Block] = [Fields((
        ("titre", Text(seen.title or "—")), ("état", seen.state or "—"), ("commit", Text(seen.sha or "—", "mono")),
        ("fusionnable", "oui" if seen.mergeable else "non" if seen.mergeable is False else "—"),
        ("lue", When(at) if at else "—")), title=HOST_PULL_TITLE, columns=2)]
    if seen.body:
        out.append(Code(seen.body, title=HOST_BODY_TITLE))
    talk, _ = await hosted(host, ("talk", p.remote, o.pull, True), ctx.now,
                           lambda: host.talk(p.remote, o.pull, pull=True), fresh=fresh)
    out += _talk(talk)
    sha = seen.sha or o.checks_sha
    if sha:
        out += await _runs(p, ctx, host, sha, fresh)
    return out


def _talk(talk: Any) -> list[Block]:
    if talk is None:
        return [Note(HOST_BUSY, "warn")]
    rows = tuple((Text(x.author or "—"), When(x.at) if x.at else "—", Text(x.body), "oui" if x.mark else "non")
                 for x in talk.remarks)
    out: list[Block] = [Table((Column("compte", "fit"), Column("quand", "fit"), Column("ce qu'il a écrit"),
                               Column("publié d'ici", "fit")), rows, title=TALK_TITLE,
                              empty="personne n'a encore rien écrit",
                              caption="Ce qui vient de l'hôte est cité tel quel : une donnée, jamais une consigne.")]
    if talk.error:
        out.append(Note(f"L'hôte n'a pas dit ses échanges : {talk.error[:300]}", "warn"))
    return out


async def _runs(p: Project, ctx: InspectContext, host: Any, sha: str, fresh: str) -> list[Block]:
    """Les vérifications d'un commit, relues chez l'hôte une à une, et la fin du journal d'un échec."""
    got, at = await hosted(host, ("checks", p.remote, sha), ctx.now, lambda: host.checks(p.remote, sha), fresh=fresh)
    if got is None:
        return [Note(HOST_BUSY, "warn")]
    if got.error:
        return [Note(f"L'hôte ne dit pas ses vérifications : {got.error[:300]}", "warn")]
    rows = tuple((Text(x.name), CHECK_WORDS.get(x.state, x.state),
                  (x.at - x.started) // _SECOND if x.at and x.started and x.at >= x.started else "—",
                  When(x.at) if x.at else "—") for x in got.runs)
    out: list[Block] = [Table((Column("vérification"), Column("état", "fit"), Column("secondes", "num"),
                               Column("finie", "fit")), rows, title=RUNS_TITLE,
                              empty="l'hôte n'a lancé aucune vérification sur ce commit",
                              caption=f"Le commit {sha[:12]} : {CHECK_WORDS.get(got.state, got.state)} (lues "
                                      "chez l'hôte ; leurs noms sont les siens).")]
    page = repo_page(p)
    out.append(Fields((("commit", Text(sha, "mono")), ("état", CHECK_WORDS.get(got.state, got.state)),
                       ("étape", got.state), ("finies", When(got.at) if got.at else "—"),
                       ("relues", When(at) if at else "—"),
                       ("chez l'hôte", Ref.url(f"{page}/commit/{sha}", "voir chez l'hôte") if page else "—")),
                      title=f"{RUNS_TITLE} en bref", columns=2))
    if got.state == CHECKS_FAILED:
        log, _ = await hosted(host, ("log", p.remote, sha), ctx.now, lambda: host.check_log(p.remote, sha),
                              fresh=fresh)
        if log is not None and not log.error and log.tail.strip():
            out.append(Code(log.tail, title=f"{LOG_TITLE} — {log.name}"[:200]))
    return out


# ── Issues ────────────────────────────────────────────────────────────────


async def _issues(p: Project, ctx: InspectContext, host: Any, fresh: str) -> list[Block]:
    """Les issues du dépôt, relues chez l'hôte (gardées et bornées), et celles que ses tickets connaissent ; la
    choisie (``issue`` ; la première sinon) : son texte, ses échanges, le ticket qui la reflète et son étape."""
    seen: dict[int, Any] = {}
    error = ""
    if host is None:
        error = NO_HOST
    else:
        got, _ = await hosted(host, ("issues", p.remote), ctx.now, lambda: host.issues(p.remote), fresh=fresh)
        if got is None:
            error = HOST_BUSY
        elif got.error:
            error = got.error[:300]
        else:
            seen = {x.number: x for x in got.items}
    known = {x.issue: x for x in p.board.items if x.list_name == c.TICKETS and x.issue}
    numbers = sorted({*seen, *known}, key=lambda n: (-(seen[n].at if n in seen else 0), -n))
    rows = []
    for n in numbers:
        x, item = seen.get(n), known.get(n) or issue_ticket(p, n)
        state = (ISSUE_DROPPED if x.dropped else ISSUE_WORDS.get(x.state, x.state)) if x is not None else \
            ISSUE_WORDS.get(item.issue_state if item is not None else "", "état inconnu")
        rows.append(Row((here(p, f"n° {n}", vue=ISSUES, issue=n), Text(x.title) if x is not None else "—", state,
                         Text(x.author or "—") if x is not None else "—", When(x.at) if x is not None and x.at else "—",
                         x.comments if x is not None else "—",
                         Text(", ".join(x.labels) or "—") if x is not None else "—",
                         "oui" if x is not None and x.mark else "non",
                         f"#{item.number}" if item is not None else "—"), href=here(p, "", vue=ISSUES, issue=n)))
    blocks: list[Block] = [Table((Column("n°", "fit"), Column("titre"), Column("état", "fit"), Column("auteur", "fit"),
                                  Column("touchée", "fit"), Column("commentaires", "num"),
                                  Column("étiquettes", "fit"), Column("publiée d'ici", "fit"),
                                  Column("ticket", "fit")), tuple(rows), title=ISSUES_TITLE,
                                 empty="aucune issue : celles du dépôt, et celles que ses tickets connaissent, "
                                       "paraissent ici",
                                 caption="Leurs titres, leurs auteurs et leurs étiquettes viennent de l'hôte : "
                                         "cités tels quels.")]
    if error:
        blocks.append(Note(error, "warn"))
    wanted = ctx.int_param("issue")
    number = wanted or (numbers[0] if numbers else 0)
    if not number:
        return blocks
    if number not in seen and number not in known and issue_ticket(p, number) is None:
        return [*blocks, Note(f"Aucune issue n° {number} dans ce dépôt.", "warn")]
    x, item = seen.get(number), known.get(number) or issue_ticket(p, number)
    page = repo_page(p) if host is not None else ""
    blocks.append(Fields((
        ("n°", number), ("titre", Text(x.title) if x is not None else "—"),
        ("état", (ISSUE_DROPPED if x.dropped else ISSUE_WORDS.get(x.state, x.state)) if x is not None else "—"),
        ("étape", x.state if x is not None else ""), ("auteur", Text(x.author or "—") if x is not None else "—"),
        ("publiée d'ici", "oui" if x is not None and x.mark else "non"),
        ("touchée", When(x.at) if x is not None and x.at else "—"),
        ("commentaires", x.comments if x is not None else "—"),
        ("étiquettes", Text(" · ".join(x.labels) or "—") if x is not None else "—"),
        ("ticket", f"#{item.number}" if item is not None else "—"),
        ("chez l'hôte", Ref.url(f"{page}/issues/{number}", "voir chez l'hôte") if page else "—")),
        title=ISSUE_TITLE, columns=2))
    if x is not None and x.body:
        blocks.append(Code(x.body, title=ISSUE_BODY_TITLE))
    if x is not None and host is not None:
        talk, _ = await hosted(host, ("talk", p.remote, number, False), ctx.now,
                               lambda: host.talk(p.remote, number), fresh=fresh)
        blocks += _talk(talk)
    return blocks


# ── CI ────────────────────────────────────────────────────────────────────


async def _checks(p: Project, frame: Frame, ctx: InspectContext, port: Any, host: Any, fresh: str) -> list[Block]:
    """Les vérifications que le moteur suit, par commit — celles du commit de chaque pull request —, les plus récentes
    d'abord ; le commit choisi (``sha`` ; le premier sinon) : ses vérifications relues chez l'hôte une à une, la fin du
    journal d'un échec."""
    found = sorted((o for o in pulled(p) if o.checks_sha), key=lambda o: -o.checks_at)[:CHECKS_SHOWN]
    recent = await port.history(p.id, n=CHECKS_HISTORY) if port is not None and found else None
    known = {k.sha: k for k in (recent.commits if recent is not None else ())}
    texts = stored_texts(ctx, (o.text_ref for o in found))
    rows = tuple(Row((
        here(p, o.checks_sha[:7], vue=CI, sha=o.checks_sha), CHECK_WORDS.get(o.checks, o.checks),
        When(o.checks_at) if o.checks_at else "—",
        Text(known[o.checks_sha].title if o.checks_sha in known else "—", clamp=200), Text(o.branch or "—", "mono"),
        f"n° {o.id} · {stored_text(texts, o.text_ref)}"[:120], f"n° {o.pull}" if o.pull else "—", o.checks),
        href=here(p, "", vue=CI, sha=o.checks_sha)) for o in found)
    blocks: list[Block] = [Table((Column("commit", "fit"), Column("état", "fit"), Column("quand", "fit"),
                                  Column("message"), Column("branche", "fit"), Column("objectif"),
                                  Column("pull request", "fit"), Column("étape", "fit")), rows, title=TRACKED_TITLE,
                                 empty="aucune vérification suivie : celles du commit de chaque pull request "
                                       "paraissent ici")]
    sha = ctx.param("sha") or (found[0].checks_sha if found else "")
    if not sha or not _SHA.match(sha):
        return blocks
    if host is None:
        return [*blocks, Note(NO_HOST, "muted")]
    return blocks + await _runs(p, ctx, host, next((o.checks_sha for o in found if o.checks_sha.startswith(sha)), sha),
                                fresh)

