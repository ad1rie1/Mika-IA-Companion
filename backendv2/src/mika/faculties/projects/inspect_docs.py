"""La documentation d'un projet, vue de la console et écrite par une personne (ADR 0289) : l'onglet
« Documentation » de sa fiche — ses pages et leur dernière modification, ses images, rien à y éditer — et les actions
par lesquelles une personne l'écrit depuis son espace ou par MCP (``app/domains/projects/api/docs.py``, ``app/domains/projects/docs_mcp.py``).
Des textes de console et d'écran, lus par qui décide — pas des phrases qu'elle lit. Les règles, les événements et la
projection sont dans ``docs.py``.

Qui a le droit se juge avant l'action, là où l'on sait qui demande (les routes de l'espace d'une personne, le point
MCP) ; ici, comme toute action de la console, c'est le geste d'un opérateur ou d'une personne déjà admise. L'action
garde ce qui ne dépend pas de qui : un chemin qui ne sort pas de l'espace, les bornes, et **l'écriture qui n'écrase
pas** — elle nomme la version lue (``base``), et se refuse si la page a changé depuis.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Any

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.faculties.projects import docs
from mika.faculties.projects.actions import can_edit
from mika.faculties.projects.faculty import (
    DOC_IMAGES_MAX,
    DOC_PAGES_MAX,
    DOC_VERSIONS_KEPT,
    PROJECTS,
    Project,
    ProjectsState,
)
from mika.faculties.projects.inspect_common import (
    LIVE,
    operator_person,
    subject_project,
    target_project,
    unchanged,
)
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.inspect import Badge, Block, Column, InspectContext, Note, Row, Table, When, plural, size_fr
from mika.kernel.operate import ActionContext, Done, Refused
from mika.kernel.text import fold

#: les actions, telles que la console, l'API et le point MCP les nomment
WRITE, MOVE, REMOVE, IMAGE, IMAGE_REMOVE = (
    "projects.doc_ecrire", "projects.doc_deplacer", "projects.doc_supprimer", "projects.doc_image",
    "projects.doc_image_retirer")
#: par où une écriture est arrivée, en mots
VIA_WORDS = {docs.RUN: "pendant une exécution", docs.WEB: "dans son espace", docs.MCP: "par MCP",
             docs.CONSOLE: "depuis la console"}
HER_WORDS = "elle"

# ── Les refus, en mots ────────────────────────────────────────────────────

BAD_PATH = ("Un chemin de page est relatif à l'espace et finit par « .md » : des minuscules, des chiffres, des points "
            "et des tirets, des dossiers séparés par « / » (six niveaux au plus) — jamais « .. » ni un chemin absolu.")
BAD_IMAGE = ("Un nom d'image tient en un seul segment : des minuscules, des chiffres, des points et des tirets, puis "
             "« .png », « .jpg », « .gif » ou « .webp ».")
NO_PAGE = "Aucune page « {path} » dans la documentation de ce projet."
NO_IMAGE = "Aucune image « {name} » dans la documentation de ce projet."
EXISTS = "Une page « {path} » existe déjà : nomme la version que tu as lue pour l'écrire."
MOVED_ON = ("Cette page a changé depuis ta lecture : elle en est à la version {version}, écrite {who}. Relis-la, "
            "puis reprends tes modifications.")
OVERTAKEN = ("Quelqu'un a enregistré cette page au même instant : ta version n'a pas été gardée. Relis la page, puis "
             "reprends tes modifications.")
TAKEN = "Une page porte déjà ce chemin : « {path} »."
SAME = "Ce texte est déjà celui de la page : rien n'a été enregistré."
PAGES_FULL = f"Cette documentation a déjà ses {DOC_PAGES_MAX} pages : supprime-en avant d'en créer d'autres."
TOO_LONG = f"Une page tient en {docs.PAGE_CHARS} caractères au plus."
NO_STORE = "Les images ne peuvent pas être gardées ici (aucun magasin d'images)."
ONE_FILE = "Envoie une image, une seule."
NOT_AN_IMAGE = "Ce fichier n'est pas une image qu'on garde ici : PNG, JPEG, GIF ou WebP."
IMAGE_TOO_BIG = f"Une image pèse au plus {docs.IMAGE_BYTES // (1024 * 1024)} Mio."
IMAGES_FULL = f"Cette documentation a déjà ses {DOC_IMAGES_MAX} images : retires-en avant d'en ajouter."
SPACE_FULL = (f"Les images de cette documentation prennent déjà presque leurs {docs.SPACE_BYTES // (1024 * 1024)} "
              "Mio : retires-en avant d'en ajouter.")
SAVED = "Version {version} de « {path} » enregistrée dans la documentation du projet."
CREATED = "Page « {path} » créée dans la documentation du projet."
RESTORED = "Version {version} de « {path} » : retour à la version {restored}."
MOVED = "La page est maintenant « {to} »."
REMOVED = "Page « {path} » supprimée, avec ses versions."
IMAGE_ADDED = "Image ajoutée : images/{name}"
IMAGE_LOST = ("L'image n'a pas été gardée : une autre a pris ce nom ou la place au même instant. Rien n'a été "
              "ajouté : renvoie-la.")
#: qui a écrit la dernière version, quand le refus part hors de la console : personne n'y est nommé (ADR 0292) —
#: l'espace d'une personne et le point MCP composent ce refus eux-mêmes, par la règle de qui peut être nommé
SOMEONE = "entre-temps"
IMAGE_REMOVED = "Image « {name} » retirée."


def who_wrote(frame: Frame, author: str, by: str, via: str, tool: str = "") -> str:
    """Qui a écrit une version, en mots de console : elle, une personne par son nom, et par où."""
    if author == c.BY_SELF:
        return f"{HER_WORDS}, {VIA_WORDS[docs.RUN]}"
    name = (identity_c.person_name(frame, by) if by else "") or "une personne"
    where = VIA_WORDS.get(via, "")
    if via == docs.MCP and tool:
        where = f"par MCP (« {tool} »)"
    return f"{name}, {where}" if where else name


# ── L'onglet « Documentation » ────────────────────────────────────────────


@PROJECTS.inspect("documentation", title="Documentation", subject="project", order=34,
                  description="Sa documentation, un espace à part de son dépôt : ses pages et leur dernière "
                              "modification, ses images. Elle s'écrit dans l'espace de chaque personne, par elle "
                              "pendant ses exécutions, et par MCP.")
def _docs_tab(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = subject_project(s, ctx)
    if isinstance(p, Note):
        return [p]
    store = ctx.ports.get("store")
    pages = docs.tree(store, p.id)
    rows = tuple(Row((x.path, x.title or "(oublié)", x.version, When(x.at) if x.at else "—",
                      who_wrote(frame, x.author, x.by, x.via, x.tool), size_fr(x.chars))) for x in pages)
    images = tuple(Row((i.name, size_fr(i.size), When(i.at) if i.at else "—",
                        who_wrote(frame, i.author, i.by, i.via))) for i in p.docs.images)
    used = docs.space_used(p.docs)
    return [
        Note("Un espace à part du dépôt du code : enregistrer une page n'est pas un commit. Qui a droit à la "
             "documentation du projet (son onglet « Accès ») la lit dans son espace et par MCP ; l'écrire demande "
             "en plus de le piloter en modification.", tone="muted"),
        Table((Column("page"), Column("titre"), Column("version", "num"), Column("modifiée", "fit"),
               Column("par"), Column("taille", "num")), rows, title="Ses pages",
              empty="aucune page pour l'instant",
              caption=f"{plural(len(pages), 'page', 'pages')} sur {DOC_PAGES_MAX} au plus ; chaque page garde ses "
                      f"{DOC_VERSIONS_KEPT} dernières versions."),
        Table((Column("image"), Column("taille", "num"), Column("ajoutée", "fit"), Column("par")), images,
              title="Ses images", empty="aucune image pour l'instant",
              caption=f"{plural(len(p.docs.images), 'image', 'images')}, {size_fr(used)} sur "
                      f"{size_fr(docs.SPACE_BYTES)} au plus."),
        *([Badge("la projection ne se lit pas ici", "warn")] if store is None else []),
    ]


# ── Écrire, déplacer, supprimer une page ──────────────────────────────────


def _writer(frame: Frame, ctx: ActionContext) -> tuple[str, str]:
    """Qui agit : la personne de son compte (``person``), sinon un opérateur sans personne reliée."""
    person = operator_person(frame, ctx)
    return (c.BY_PERSON, person) if person else (c.BY_OPERATOR, ctx.by)


def _via(raw: str) -> str:
    return raw if raw in (docs.WEB, docs.MCP) else docs.CONSOLE


def _path(raw: str, field: str = "path") -> str:
    path = docs.page_path(raw.strip())
    if path is None:
        raise Refused(BAD_PATH, {field: "un chemin de page, relatif, en « .md »"})
    return path


def _last_writer(frame: Frame, ctx: ActionContext, p: Project, path: str, via: str) -> str:
    """Qui a écrit la dernière version, pour le refus d'une écriture périmée. Dans la console : son nom et, par MCP,
    celui de son jeton. Ailleurs (l'espace d'une personne, le point MCP) : personne — l'action ne sait pas si qui
    agit a le droit de connaître ce nom."""
    row = docs.page(ctx.store, p.id, path)
    if row is None or _via(via) != docs.CONSOLE:
        return SOMEONE
    return f"par {who_wrote(frame, row.author, row.by, row.via, row.tool)}"


class WriteArgs(BaseModel):
    path: Annotated[str, Knob(label="Chemin de la page")] = Field(min_length=1, max_length=docs.PATH_MAX)
    text: Annotated[str, Knob(label="Son texte, en Markdown", widget="textarea")] = \
        Field(default="", max_length=docs.PAGE_CHARS)
    word: Annotated[str, Knob(label="Un mot sur ce qui a changé")] = Field(default="", max_length=docs.WORD_MAX)
    base: Annotated[int, Knob(label="La version lue (0 : une page nouvelle)")] = Field(default=0, ge=0)
    restored: Annotated[int, Knob(label="Version reprise", widget="hidden")] = Field(default=0, ge=0)
    via: Annotated[str, Knob(label="Par où", widget="hidden")] = Field(default="", max_length=16)
    tool: Annotated[str, Knob(label="Outil", widget="hidden")] = Field(default="", max_length=docs.TOOL_MAX)


@PROJECTS.action("doc_ecrire", title="Écrire une page de sa documentation", args=WriteArgs,
                 emits=[docs.DOC_WRITTEN], subject="project", order=70, available=can_edit, inline=True,
                 description="Enregistrer une version d'une page de la documentation du projet, en nommant la "
                             "version lue : si la page a changé depuis, rien n'est écrasé.")
def _write(s: ProjectsState, frame: Frame, args: WriteArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    path = _path(args.path)
    old = docs.page_at(p.docs, path)
    if old is None and args.base:
        raise Refused(NO_PAGE.format(path=path))
    if old is None and len(p.docs.pages) >= DOC_PAGES_MAX:
        raise Refused(PAGES_FULL)
    if old is not None and args.base == 0:
        raise Refused(EXISTS.format(path=path))
    if old is not None and args.base != old.version:
        raise Refused(MOVED_ON.format(version=old.version, who=_last_writer(frame, ctx, p, path, args.via)))
    if old is not None and not args.restored:
        row = docs.page(ctx.store, p.id, path)
        if row is not None and docs.text_of(ctx.store, row.seq) == args.text:
            raise Refused(SAME)
    author, by = _writer(frame, ctx)
    draft = docs.writing(p, path, args.text, word=args.word, base=args.base, restored=args.restored, author=author,
                         by=by, via=_via(args.via), tool=args.tool if args.via == docs.MCP else "")
    number = (old.version if old is not None else 0) + 1
    said = (RESTORED.format(version=number, path=path, restored=args.restored) if args.restored else
            SAVED.format(version=number, path=path) if old is not None else CREATED.format(path=path))
    return Done(drafts=(draft,), message=said, guard=unchanged(p.id, LIVE))


class MoveArgs(BaseModel):
    path: Annotated[str, Knob(label="Chemin de la page")] = Field(min_length=1, max_length=docs.PATH_MAX)
    to: Annotated[str, Knob(label="Son nouveau chemin")] = Field(min_length=1, max_length=docs.PATH_MAX)
    via: Annotated[str, Knob(label="Par où", widget="hidden")] = Field(default="", max_length=16)


@PROJECTS.action("doc_deplacer", title="Renommer ou déplacer une page de sa documentation", args=MoveArgs,
                 emits=[docs.DOC_MOVED], subject="project", order=71, available=can_edit, inline=True,
                 description="Donner un autre chemin à une page : ses versions la suivent ; les liens des autres "
                             "pages ne sont pas réécrits.")
def _move(s: ProjectsState, frame: Frame, args: MoveArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    path, to = _path(args.path), _path(args.to, "to")
    if docs.page_at(p.docs, path) is None:
        raise Refused(NO_PAGE.format(path=path))
    if docs.page_at(p.docs, to) is not None:
        raise Refused(TAKEN.format(path=to))
    author, by = _writer(frame, ctx)
    return Done(drafts=(docs.moving(p, path, to, author=author, by=by, via=_via(args.via)),),
                message=MOVED.format(to=to), guard=unchanged(p.id, LIVE))


class RemoveArgs(BaseModel):
    path: Annotated[str, Knob(label="Chemin de la page")] = Field(min_length=1, max_length=docs.PATH_MAX)
    via: Annotated[str, Knob(label="Par où", widget="hidden")] = Field(default="", max_length=16)


@PROJECTS.action("doc_supprimer", title="Supprimer une page de sa documentation", args=RemoveArgs,
                 emits=[docs.DOC_REMOVED], subject="project", order=72, available=can_edit, inline=True, danger=True,
                 description="Supprimer une page et ses versions de la documentation du projet.")
def _remove(s: ProjectsState, frame: Frame, args: RemoveArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    path = _path(args.path)
    if docs.page_at(p.docs, path) is None:
        raise Refused(NO_PAGE.format(path=path))
    author, by = _writer(frame, ctx)
    return Done(drafts=(docs.removing(p, path, author=author, by=by, via=_via(args.via)),),
                message=REMOVED.format(path=path), guard=unchanged(p.id, LIVE))


# ── Ses images ────────────────────────────────────────────────────────────


def image_refusal(p: Project, name: str, size: int) -> str:
    """Pourquoi cette image ne tient pas (vide : elle tient) — la borne du nombre, puis celle de la place."""
    if not 0 < size <= docs.IMAGE_BYTES:
        return IMAGE_TOO_BIG
    if len(p.docs.images) >= DOC_IMAGES_MAX:
        return IMAGES_FULL
    if docs.space_used(p.docs) + size > docs.SPACE_BYTES:
        return SPACE_FULL
    return "" if docs.image_fits(p.docs, name, size) else BAD_IMAGE


def image_named(p: Project, said: str, data: bytes) -> str:
    """Le nom que prend une image : celui qu'on dit (replié en un nom simple), à l'extension que disent ses octets,
    suivi d'un numéro s'il est pris. Refuse ce qui n'est pas une image qu'on garde."""
    kind = docs.sniffed(data)
    if not kind:
        raise Refused(NOT_AN_IMAGE)
    stem = fold(said.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0])
    stem = "-".join(part for part in "".join(ch if ch.isascii() and ch.isalnum() else "-" for ch in stem).split("-")
                    if part)[:70] or "image"
    return docs.free_name(p.docs, f"{stem}.{kind}")


class ImageArgs(BaseModel):
    name: Annotated[str, Knob(label="Son nom (vide : celui du fichier)")] = Field(default="", max_length=120)
    via: Annotated[str, Knob(label="Par où", widget="hidden")] = Field(default="", max_length=16)


async def add_image(s: ProjectsState, frame: Frame, ctx: ActionContext, name: str, data: bytes, via: str) -> Done:
    """Une image de plus : ses octets d'abord (hors du journal), puis le fait."""
    p = target_project(s, ctx)
    store = (ctx.ports or {}).get(docs.PORT)
    if store is None:
        raise Refused(NO_STORE)
    if not data or len(data) > docs.IMAGE_BYTES:
        raise Refused(IMAGE_TOO_BIG)
    named = image_named(p, name, data)
    if why := image_refusal(p, named, len(data)):
        raise Refused(why)
    author, by = _writer(frame, ctx)
    sha = hashlib.sha256(data).hexdigest()
    file = docs.file_id(p.id, named, sha, ctx.now)
    await store.put(file, data, subjects=docs.image_subjects(p, by if author == c.BY_PERSON else ""))
    return Done(drafts=(docs.adding_image(p, named, file, len(data), sha, author=author, by=by, via=_via(via)),),
                message=IMAGE_ADDED.format(name=named), guard=unchanged(p.id, LIVE))


@PROJECTS.action("doc_image", title="Ajouter une image à sa documentation", args=ImageArgs,
                 emits=[docs.DOC_IMAGE_ADDED], subject="project", order=73, available=can_edit, inline=True,
                 description="Téléverser une image (PNG, JPEG, GIF, WebP) dans la documentation du projet : une "
                             "page la cite par « images/<nom> ».")
async def _image(s: ProjectsState, frame: Frame, args: ImageArgs, ctx: ActionContext) -> Done:
    files: tuple[Any, ...] = tuple(ctx.files or ())
    if len(files) != 1:
        raise Refused(ONE_FILE)
    sent = files[0]
    return await add_image(s, frame, ctx, args.name.strip() or str(getattr(sent, "name", "") or ""),
                           bytes(sent.data), args.via)


class ImageRemoveArgs(BaseModel):
    name: Annotated[str, Knob(label="Nom de l'image")] = Field(min_length=1, max_length=120)
    via: Annotated[str, Knob(label="Par où", widget="hidden")] = Field(default="", max_length=16)


@PROJECTS.action("doc_image_retirer", title="Retirer une image de sa documentation", args=ImageRemoveArgs,
                 emits=[docs.DOC_IMAGE_REMOVED], subject="project", order=74, available=can_edit, inline=True,
                 danger=True, description="Retirer une image de la documentation du projet : ses octets s'effacent.")
def _image_remove(s: ProjectsState, frame: Frame, args: ImageRemoveArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    image = docs.image_at(p.docs, args.name.strip())
    if image is None:
        raise Refused(NO_IMAGE.format(name=args.name.strip()[:90]))
    author, by = _writer(frame, ctx)
    return Done(drafts=(docs.removing_image(p, image, author=author, by=by, via=_via(args.via)),),
                message=IMAGE_REMOVED.format(name=image.name), guard=unchanged(p.id, LIVE))
