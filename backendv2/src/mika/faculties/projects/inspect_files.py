"""L'onglet « Fichiers » de la fiche d'un projet (``fichiers``) et le téléchargement d'un fichier de son atelier
(``@PROJECTS.download("project")``) : le dossier du projet à parcourir, un fichier lu ici ou rapatrié tel quel, le
dépôt d'un fichier pour elle. Lu du port de l'atelier ; les aides communes de la fiche viennent de ``inspect.py``."""

from __future__ import annotations

import re
from typing import Any

from mika.faculties.projects import docs
from mika.faculties.projects.actions import can_deposit
from mika.faculties.projects.faculty import PROJECTS, Project, ProjectsState, project_at
from mika.faculties.projects.inspect_common import cut_noted, subject_project
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Block,
    Code,
    Column,
    Disclosure,
    Download,
    Fields,
    InspectContext,
    Nav,
    NavItem,
    Note,
    Ref,
    Row,
    Table,
    Text,
    plural,
    size_fr,
)
from mika.ports.workshop import OutsideWorkshop

# ── La fiche : fichiers ───────────────────────────────────────────────────

#: ce qu'on montre d'un fichier ouvert (au-delà : coupé, et dit ; le téléchargement donne tout)
FILE_SHOWN = 60_000
DOWNLOAD_MAX = 20 * 1024 * 1024
#: une image de sa documentation (ADR 0289), par son nom : la fiche de la console la montre (ADR 0297)
DOC_IMAGE = "documentation:images/"

_TREE_LINE = re.compile(r"^(?P<path>.+) \((?P<size>\d+) o\)$")


def _download_link(project: int, path: str) -> Ref:
    return Ref.download("project", str(project), "télécharger", path)


def _folder_ref(p: Project, folder: str, text: str) -> Ref:
    params: tuple[tuple[str, str], ...] = (("onglet", "fichiers"),) + ((("dossier", folder),) if folder else ())
    return Ref("subject", f"project/{p.id}", text, params)


def _file_ref(p: Project, path: str, text: str) -> Ref:
    folder = path.rsplit("/", 1)[0] if "/" in path else ""
    params = (("onglet", "fichiers"), *((("dossier", folder),) if folder else ()), ("fichier", path))
    return Ref("subject", f"project/{p.id}", text, params)


def _listing(tree: list[str], folder: str) -> tuple[list[tuple[str, int, int]], list[tuple[str, int]]]:
    """Les sous-dossiers (nom, fichiers, octets) et les fichiers (chemin, octets) directement dans ``folder``."""
    prefix = f"{folder}/" if folder else ""
    dirs: dict[str, list[int]] = {}
    files: list[tuple[str, int]] = []
    for line in tree:
        m = _TREE_LINE.match(line)
        if m is None or not m.group("path").startswith(prefix):
            continue
        rest = m.group("path")[len(prefix):]
        size = int(m.group("size"))
        if "/" in rest:
            name = rest.split("/", 1)[0]
            entry = dirs.setdefault(name, [0, 0])
            entry[0] += 1
            entry[1] += size
        else:
            files.append((m.group("path"), size))
    return [(n, v[0], v[1]) for n, v in sorted(dirs.items())], sorted(files)


@PROJECTS.inspect("fichiers", title="Fichiers", subject="project", order=29,
                  description="Le dossier du projet, à parcourir : un dossier s'ouvre, un fichier se lit ici ou se "
                              "télécharge ; tu peux y déposer un fichier pour elle.")
async def _files_tab(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = subject_project(s, ctx)
    if isinstance(p, Note):
        return [p]
    port = ctx.ports.get("workshop")
    if port is None:
        return [Note("L'atelier n'est pas disponible ici (aucun port d'atelier).", tone="warn")]
    deposit = [Disclosure("Déposer un fichier dans l'atelier", (
        ActionSlot("projects.deposer", title="Déposer un fichier", compact=True),))] \
        if can_deposit(s, frame, str(p.id), ctx.ports) else []
    if not port.exists(p.id):
        return [Note("L'atelier n'est pas encore ouvert : aucune exécution n'y a encore écrit.", tone="muted"), *deposit]
    folder = ctx.param("dossier").strip("/")
    if ".." in folder.split("/"):
        folder = ""
    tree = await port.tree(p.id, folder or ".")
    cut = [line for line in tree if line.startswith("[")]
    tree = [line for line in tree if not line.startswith("[")]
    dirs, files = _listing(tree, folder)
    crumbs = [NavItem("racine", _folder_ref(p, "", "racine"), active=not folder)]
    acc = ""
    for part in [x for x in folder.split("/") if x]:
        acc = f"{acc}/{part}" if acc else part
        crumbs.append(NavItem(part, _folder_ref(p, acc, part), active=acc == folder))
    rows: list[Any] = [Row((_folder_ref(p, f"{folder}/{name}" if folder else name, f"{name}/"),
                            Badge("dossier", "info"), plural(count, "fichier", "fichiers"), size_fr(size), ""),
                           href=_folder_ref(p, f"{folder}/{name}" if folder else name, ""))
                       for name, count, size in dirs]
    rows += [Row((_file_ref(p, path, path.rsplit("/", 1)[-1]), Badge("fichier"), "", size_fr(size),
                  _download_link(p.id, path))) for path, size in files]
    total = sum(int(m.group("size")) for m in (_TREE_LINE.match(x) for x in tree) if m is not None)
    opened = await _opened_file(p, port, ctx.param("fichier"))
    where = f"dans /{folder}" if folder else "dans l'atelier"
    notes = [Note(f"Plus de {len(tree)} fichiers {where} : la liste est coupée — ouvre un sous-dossier pour voir "
                  "la suite.", "warn")] if cut else []
    return [
        *opened,
        Nav(tuple(crumbs), title="Dossier"),
        *notes,
        Table((Column("nom"), Column("sorte", "fit"), Column("contenu", "fit"), Column("taille", "num"),
               Column("télécharger", "fit")), tuple(rows), title=f"/{folder}" if folder else "Le dossier du projet",
              empty="ce dossier est vide",
              caption=f"{plural(len(tree), 'fichier', 'fichiers')} {where}, {size_fr(total)} en tout. Un nom ouvre "
                      "le fichier ici ; « télécharger » le rapatrie tel quel."),
        *deposit,
    ]


async def _opened_file(p: Project, port: Any, path: str) -> list[Block]:
    if not path:
        return []
    try:
        text = await port.read(p.id, path)
    except (OutsideWorkshop, FileNotFoundError, OSError, ValueError) as exc:
        return [Note(f"« {path} » ne s'ouvre pas : {exc}", "warn")]
    if "\x00" in text or text.count("�") > max(8, len(text) // 50):
        return [Note(f"« {path} » n'est pas un texte : télécharge-le.", "muted"),
                Fields((("télécharger", _download_link(p.id, path)),))]
    folder = path.rsplit("/", 1)[0] if "/" in path else ""
    lang = "diff" if path.endswith((".diff", ".patch")) else ""
    return [Code(cut_noted(text, FILE_SHOWN), title=path, lang=lang),
            Fields((("fichier", Text(path, "mono")), ("télécharger", _download_link(p.id, path)),
                    ("fermer", _folder_ref(p, folder, "revenir au dossier"))), columns=3)]


@PROJECTS.download("project")
async def _download(s: ProjectsState, frame: Frame, ctx: InspectContext, key: str, name: str) -> Download | Note:
    """Un fichier de l'atelier, tel quel ; ou une image de sa documentation (``DOC_IMAGE`` puis son nom)."""
    p = project_at(s, key)
    if p is not None and name.startswith(DOC_IMAGE):
        found = docs.image_at(p.docs, name.removeprefix(DOC_IMAGE))
        store = ctx.ports.get(docs.PORT)
        data = await store.read(found.file, docs.IMAGE_BYTES) if found is not None and store is not None else None
        return Download(found.name, data) if found is not None and data is not None else \
            Note("Cette image n'est pas (ou plus) dans sa documentation.", tone="warn")
    port = ctx.ports.get("workshop")
    if p is None or port is None or not port.exists(p.id):
        return Note("Ce fichier n'est pas disponible.", tone="warn")
    try:
        data = await port.read_bytes(p.id, name, DOWNLOAD_MAX + 1)
    except (OutsideWorkshop, FileNotFoundError, OSError, ValueError):
        return Note("Ce fichier n'est pas (ou plus) dans l'atelier.", tone="warn")
    if len(data) > DOWNLOAD_MAX:
        return Note(f"Trop gros pour la console ({DOWNLOAD_MAX // (1024 * 1024)} Mo au plus).", tone="warn")
    return Download(name.rsplit("/", 1)[-1], data)
