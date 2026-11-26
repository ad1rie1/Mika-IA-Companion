"""La documentation d'un projet (ADR 0289) : un espace à part de son dépôt — des pages en Markdown rangées en
dossiers, et des images.

Ce n'est pas le dépôt de l'atelier : enregistrer une page n'est pas un commit. C'est ce qu'elle et des personnes
écrivent sur le projet, et cela suit les règles du moteur :

- **Les événements** : ``projects.doc_written`` (une version de plus d'une page : son texte, un mot sur ce qui a
  changé, qui l'a écrite et par où), ``doc_moved`` (renommée ou déplacée), ``doc_removed``, ``doc_image_added`` et
  ``doc_image_removed``. Chacun porte les sujets du projet et ceux qu'il a hérités de ses lectures (``read_about``,
  ADR 0262) : l'oubli d'une personne atteint les pages et leurs versions.
- **Qui écrit, et par où** (``author``, ``by``, ``via``) : elle, pendant une exécution (``run``) ; une personne dans
  son espace — le navigateur ou l'application (``web``) ; un outil, par MCP, au nom d'une personne (``mcp`` ;
  ``tool`` : le nom du jeton qu'il présente) ; un opérateur, par une action de la console (``console``).
- **Pas d'écrasement** : une écriture dit la version que voyait qui écrit (``base`` ; 0 : la page n'existait pas).
  Elle ne vaut que si la page y est encore (``stepped``) — la même règle pour le réducteur et pour la projection.
- **L'état reste borné** (``faculty.Docs``) : le chemin de chaque page, le numéro de sa dernière version et sa date
  (``DOC_PAGES_MAX`` pages) ; le nom, la taille et l'identifiant des octets de chaque image (``DOC_IMAGES_MAX``).
- **La projection T0** (``Pages`` : ``project_doc_pages``, ``project_doc_versions``), écrite dans la transaction de
  l'ajout : l'arbre (le titre de chaque page, sa dernière modification), la recherche (son texte replié), les images
  que chaque page cite, et l'historique — ``DOC_VERSIONS_KEPT`` versions par page, les plus anciennes sortent de la
  projection. Le texte d'une version n'y est pas recopié : il se relit dans les contenus du journal, par l'événement
  qui l'a écrite.
- **Les images** sont des octets : hors du journal, sous le dossier de données (``documentation/``, le port
  ``project_docs`` — le magasin des fichiers envoyés, ``ports.shares``), bornées une à une (``IMAGE_BYTES``) et par
  projet (``SPACE_BYTES``), avec leurs sujets : l'oubli d'une personne les efface.

Un chemin ne sort jamais de l'espace : chaque segment est un nom simple (``SEGMENT``), une page finit par ``.md``.
Qui peut lire et écrire : ``links.Grant.documentation`` pour un projet qui en lit un autre ; ``app/domains/projects/api/docs``
pour une personne. Les actions sont dans ``inspect_docs.py``, ses outils et la section du prompt dans
``docs_tools.py``.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import BigInteger, Column, Index, Table, delete, func, select, update

from mika.contracts import projects as c
from mika.faculties.projects.faculty import (
    DOC_IMAGES_MAX,
    DOC_PAGES_MAX,
    DOC_VERSIONS_KEPT,
    INHERITED,
    PROJECTS,
    DocImage,
    DocPage,
    Docs,
    Project,
    ProjectsState,
    with_project,
    written,
)
from mika.kernel.codec import digest
from mika.kernel.events import Content, Draft, Payload
from mika.kernel.faculty import Tier
from mika.kernel.text import clipped, fold
from mika.ports.shares import valid_id
from mika.ports.sql import HANDLE_MAX, Key, LongText, insert_ignore, projection_table
from mika.ports.store import Sql

# ── Les bornes ────────────────────────────────────────────────────────────

#: une page : son texte, au plus (caractères) ; le mot sur ce qui a changé ; son chemin et sa profondeur
PAGE_CHARS = 100_000
WORD_MAX = 200
PATH_MAX, DEPTH_MAX = 160, 6
#: un segment de chemin : un nom simple, en minuscules — jamais ``..``, jamais un point devant
SEGMENT = re.compile(r"[a-z0-9][a-z0-9._-]{0,59}")
#: une image : ses octets, au plus ; toutes les images d'un projet, au plus
IMAGE_BYTES = 5 * 1024 * 1024
SPACE_BYTES = 100 * 1024 * 1024
#: les sortes d'images gardées, par leur extension, et ce qu'on répond en les servant (pas de SVG : un SVG porte
#: du script, et il serait servi depuis l'origine de l'API)
MIMES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}
IMAGE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}\.(?:png|jpg|jpeg|gif|webp)")
#: où une page cite une image de l'espace
IMAGES_DIR = "images/"
_CITED = re.compile(r"!\[[^\]]*\]\(images/([a-z0-9][a-z0-9._-]{0,90})")
#: le port qui garde les octets des images (``ports.shares.ShareStore``)
PORT = "project_docs"
#: par où une écriture arrive : elle, pendant une exécution ; une personne dans son espace (le navigateur,
#: l'application) ; un outil par MCP, au nom d'une personne ; un opérateur, par une action de la console
RUN, WEB, MCP, CONSOLE = "run", "web", "mcp", "console"
VIAS = (RUN, WEB, MCP, CONSOLE)
TOOL_MAX, TITLE_SHOWN = 60, 200
PAGES_TABLE, VERSIONS_TABLE = "project_doc_pages", "project_doc_versions"


# ── Les chemins ───────────────────────────────────────────────────────────


def page_path(raw: str) -> str | None:
    """Le chemin d'une page, s'il s'écrit comme tel : relatif, des segments simples, ``.md`` au bout — sinon ``None``.
    Rien n'est corrigé : un chemin absolu, qui remonte (``..``) ou qui porte autre chose que des minuscules, des
    chiffres, des points et des tirets est refusé."""
    path = raw if isinstance(raw, str) else ""
    parts = path.split("/")
    if not path or len(path) > PATH_MAX or len(parts) > DEPTH_MAX or not path.endswith(".md"):
        return None
    return path if all(SEGMENT.fullmatch(part) for part in parts) else None


def image_name(raw: str) -> str | None:
    """Le nom d'une image, s'il s'écrit comme tel (un seul segment, une extension gardée) — sinon ``None``."""
    return raw if isinstance(raw, str) and IMAGE_NAME.fullmatch(raw) else None


def mime_of(name: str) -> str:
    return MIMES.get(name.rsplit(".", 1)[-1], "application/octet-stream")


def sniffed(data: bytes) -> str:
    """L'extension que disent les premiers octets d'une image (vide : ce n'en est pas une qu'on garde)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return "webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else ""


def file_id(project: int, name: str, sha256: str, at: int = 0) -> str:
    """L'identifiant des octets d'une image : le projet, son nom, son contenu, et l'instant de l'ajout (ADR 0292) —
    chaque ajout a les siens. Sans l'instant, la même image remise sous le même nom après un retrait retombait sur
    les octets que l'effet du retrait efface."""
    return digest(("doc", project, name, sha256, at) if at else ("doc", project, name, sha256))


def title_of(path: str, text: str) -> str:
    """Le titre d'une page : son premier titre de niveau 1, sinon le nom de son fichier."""
    for line in text.splitlines():
        if line.startswith("# ") and line[2:].strip():
            return clipped(line[2:].strip(), TITLE_SHOWN)
    return path.rsplit("/", 1)[-1].removesuffix(".md")


def cited_images(text: str) -> tuple[str, ...]:
    """Les images de l'espace qu'une page cite (``![…](images/nom.png)``), sans doublon."""
    return tuple(dict.fromkeys(name for name in _CITED.findall(text) if image_name(name)))


# ── Ses événements ────────────────────────────────────────────────────────


class DocWritten(Payload):
    """Une version de plus d'une page (la première la crée). Son numéro n'est pas ici : le réducteur et la
    projection le comptent."""

    project: int
    path: str
    text: Content
    #: un mot sur ce qui a changé
    word: Content | None = None
    #: la version que voyait qui écrit (0 : la page n'existait pas) — l'écriture ne vaut que si elle y est encore
    base: int = 0
    #: un retour à une version : son numéro (0 : une écriture ordinaire)
    restored: int = 0
    #: qui l'a écrite (``self``, ``person``, ``operator``), sa personne, par où (``VIAS``) et, par MCP, le nom du
    #: jeton que l'outil présente
    author: str = c.BY_SELF
    by: str = ""
    via: str = RUN
    tool: Content | None = None
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


class DocMoved(Payload):
    """Une page renommée ou déplacée : ses versions la suivent."""

    project: int
    path: str
    to: str
    author: str = c.BY_SELF
    by: str = ""
    via: str = RUN
    owner: str | None = None
    about: tuple[str, ...] = ()


class DocRemoved(Payload):
    """Une page supprimée, avec ses versions."""

    project: int
    path: str
    author: str = c.BY_SELF
    by: str = ""
    via: str = RUN
    owner: str | None = None
    about: tuple[str, ...] = ()


class DocImageAdded(Payload):
    """Une image de plus : ses octets sont déjà au port (``file``), le journal en garde les faits."""

    project: int
    name: str
    file: str
    size: int
    mime: str = ""
    sha256: str = ""
    author: str = c.BY_SELF
    by: str = ""
    via: str = RUN
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


class DocImageRemoved(Payload):
    """Une image retirée : ses octets s'effacent après le commit (``_erase``)."""

    project: int
    name: str
    file: str = ""
    author: str = c.BY_SELF
    by: str = ""
    via: str = RUN
    owner: str | None = None
    about: tuple[str, ...] = ()


_SUBJECTS = ("owner", "about", "by", INHERITED)
_FACTS = ("owner", "about", "by")
DOC_WRITTEN = PROJECTS.event("doc_written", DocWritten, content=("text", "word", "tool"), subjects=_SUBJECTS)
DOC_MOVED = PROJECTS.event("doc_moved", DocMoved, subjects=_FACTS)
DOC_REMOVED = PROJECTS.event("doc_removed", DocRemoved, subjects=_FACTS)
DOC_IMAGE_ADDED = PROJECTS.event("doc_image_added", DocImageAdded, subjects=_SUBJECTS)
DOC_IMAGE_REMOVED = PROJECTS.event("doc_image_removed", DocImageRemoved, subjects=_FACTS)
EVENTS = (DOC_WRITTEN, DOC_MOVED, DOC_REMOVED, DOC_IMAGE_ADDED, DOC_IMAGE_REMOVED)


# ── Les règles, pures : les mêmes pour le réducteur et la projection ──────


def stepped(current: int | None, pages: int, d: DocWritten) -> int | None:
    """Le numéro que prend cette écriture, ou ``None`` si elle ne vaut pas. ``current`` : la dernière version de la
    page (``None`` : elle n'existe pas) ; ``pages`` : combien le projet en a. Une page naît d'une écriture partie de
    rien (``base`` 0), sous la borne ; une page qui existe ne prend que l'écriture partie de sa dernière version."""
    if page_path(d.path) is None or d.via not in VIAS:
        return None
    if current is None:
        return 1 if d.base == 0 and pages < DOC_PAGES_MAX else None
    return current + 1 if d.base == current else None


def movable(exists: bool, taken: bool, d: DocMoved) -> bool:
    """Un déplacement vaut pour une page qui existe, vers un chemin bien écrit et libre."""
    return exists and not taken and d.to != d.path and page_path(d.to) is not None


def space_used(docs: Docs) -> int:
    """La place que prennent ses images (octets)."""
    return sum(i.size for i in docs.images)


def page_at(docs: Docs, path: str) -> DocPage | None:
    return next((x for x in docs.pages if x.path == path), None)


def image_at(docs: Docs, name: str) -> DocImage | None:
    return next((x for x in docs.images if x.name == name), None)


def image_fits(docs: Docs, name: str, size: int) -> bool:
    """Une image de plus tient-elle ? Un nom bien écrit et libre, sous la borne d'une image, du nombre et de la
    place du projet."""
    return (image_name(name) is not None and image_at(docs, name) is None and 0 < size <= IMAGE_BYTES
            and len(docs.images) < DOC_IMAGES_MAX and space_used(docs) + size <= SPACE_BYTES)


def free_name(docs: Docs, wanted: str) -> str:
    """Un nom libre pour une image : celui qu'on demande, sinon suivi d'un numéro (``schema-2.png``)."""
    stem, _, ext = wanted.rpartition(".")
    name, n = wanted, 2
    while image_at(docs, name) is not None:
        name, n = f"{stem[:70]}-{n}.{ext}", n + 1
    return name


# ── Écrire : les seuls endroits qui font un brouillon ─────────────────────


def _about(p: Project) -> dict[str, Any]:
    return {"owner": p.owner, "about": p.about, INHERITED: p.read_about}


def writing(p: Project, path: str, text: str, *, word: str = "", base: int = 0, restored: int = 0,
            author: str = c.BY_SELF, by: str = "", via: str = RUN, tool: str = "") -> Draft[Any]:
    """Le brouillon d'une écriture, partie de la version qu'on voit (``base``). Ce qu'on écrit dans la documentation
    est au niveau de ce que le projet écrit (``written``), quel que soit qui l'écrit."""
    level = written(p)
    return DOC_WRITTEN.draft(
        project=p.id, path=path, text=Content.of(text, level=level),
        word=Content.of(clipped(word, WORD_MAX), level=level) if word.strip() else None, base=base,
        restored=restored, author=author, by=by, via=via,
        tool=Content.of(clipped(tool, TOOL_MAX), level=level) if tool.strip() else None, **_about(p))


def moving(p: Project, path: str, to: str, *, author: str = c.BY_SELF, by: str = "", via: str = RUN) -> Draft[Any]:
    return DOC_MOVED.draft(project=p.id, path=path, to=to, author=author, by=by, via=via, owner=p.owner,
                           about=p.about)


def removing(p: Project, path: str, *, author: str = c.BY_SELF, by: str = "", via: str = RUN) -> Draft[Any]:
    return DOC_REMOVED.draft(project=p.id, path=path, author=author, by=by, via=via, owner=p.owner, about=p.about)


def adding_image(p: Project, name: str, file: str, size: int, sha256: str, *, author: str = c.BY_SELF,
                 by: str = "", via: str = RUN) -> Draft[Any]:
    # aucune clé de dédoublonnage (ADR 0292) : une clé est permanente, et une image retirée puis remise à
    # l'identique ne s'écrivait plus jamais. Un envoi redit est tenu par la clé d'envoi de l'action ; un nom pris,
    # par ``free_name`` et par la garde du réducteur (``image_fits``)
    return DOC_IMAGE_ADDED.draft(project=p.id, name=name, file=file, size=size, mime=mime_of(name), sha256=sha256,
                                 author=author, by=by, via=via, **_about(p))


def removing_image(p: Project, image: DocImage, *, author: str = c.BY_SELF, by: str = "",
                   via: str = RUN) -> Draft[Any]:
    return DOC_IMAGE_REMOVED.draft(project=p.id, name=image.name, file=image.file, author=author, by=by, via=via,
                                   owner=p.owner, about=p.about)


def image_subjects(p: Project, by: str = "") -> tuple[str, ...]:
    """Les personnes que l'oubli doit atteindre dans une image : celles du projet, de ses lectures, et qui l'a mise."""
    return tuple(dict.fromkeys(x for x in (p.owner, *p.about, *p.read_about, by) if x))


# ── Réducteurs ────────────────────────────────────────────────────────────


def _docs(s: ProjectsState, p: Project, docs: Docs) -> ProjectsState:
    return with_project(s, replace(p, docs=docs))


@PROJECTS.reducer(DOC_WRITTEN)
def _doc_written(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    if p is None:
        return s
    old = page_at(p.docs, d.path)
    number = stepped(old.version if old is not None else None, len(p.docs.pages), d)
    if number is None:
        return s  # partie d'une version qui n'est plus la dernière : elle n'écrase rien
    new = DocPage(d.path, number, e.at)
    pages = tuple(new if x is old else x for x in p.docs.pages) if old is not None else (*p.docs.pages, new)
    return _docs(s, p, replace(p.docs, pages=pages))


@PROJECTS.reducer(DOC_MOVED)
def _doc_moved(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    if p is None:
        return s
    old = page_at(p.docs, d.path)
    if not movable(old is not None, page_at(p.docs, d.to) is not None, d):
        return s
    return _docs(s, p, replace(p.docs, pages=tuple(replace(x, path=d.to) if x is old else x for x in p.docs.pages)))


@PROJECTS.reducer(DOC_REMOVED)
def _doc_removed(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    if p is None or page_at(p.docs, d.path) is None:
        return s
    return _docs(s, p, replace(p.docs, pages=tuple(x for x in p.docs.pages if x.path != d.path)))


@PROJECTS.reducer(DOC_IMAGE_ADDED)
def _doc_image_added(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    if p is None or not valid_id(d.file) or not image_fits(p.docs, d.name, d.size):
        return s
    image = DocImage(d.name, d.file, d.size, mime_of(d.name), e.at, d.author, d.by, d.via if d.via in VIAS else "")
    return _docs(s, p, replace(p.docs, images=(*p.docs.images, image)))


@PROJECTS.reducer(DOC_IMAGE_REMOVED)
def _doc_image_removed(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    if p is None or image_at(p.docs, d.name) is None:
        return s
    return _docs(s, p, replace(p.docs, images=tuple(x for x in p.docs.images if x.name != d.name)))


def image_kept(docs: Docs, name: str, file: str) -> bool:
    """L'état garde-t-il cette image, avec ces octets-là ?"""
    image = image_at(docs, name)
    return image is not None and image.file == file


@PROJECTS.effect(DOC_IMAGE_ADDED, deadline_s=60.0)
async def _unkept(ev: Any, ports: Mapping[str, Any]) -> None:
    """Après le commit : un ajout que le réducteur n'a pas gardé (un nom pris au même instant, une borne atteinte)
    n'a laissé que des octets — ils s'effacent, au lieu de rester orphelins (ADR 0292). Idempotent, rejouable."""
    store, frame_of = ports.get(PORT), ports.get("frame")
    if store is None or frame_of is None or not valid_id(ev.data.file):
        return
    p = frame_of().state("projects").projects.get(ev.data.project)
    if p is None or not image_kept(p.docs, ev.data.name, ev.data.file):
        await store.delete((ev.data.file,))


@PROJECTS.effect(DOC_IMAGE_REMOVED, deadline_s=60.0)
async def _erase(ev: Any, ports: Mapping[str, Any]) -> None:
    """Après le commit : les octets d'une image retirée s'effacent (idempotent, rejouable)."""
    store = ports.get(PORT)
    if store is not None and valid_id(ev.data.file):
        await store.delete((ev.data.file,))


# ── La projection T0 ──────────────────────────────────────────────────────

_PAGE_COLUMNS = ("project", "path", "version", "seq", "at", "created_at", "author", "by", "via", "tool", "chars",
                 "title", "images", "search", "subjects")
_VERSION_COLUMNS = ("seq", "project", "path", "n", "at", "author", "by", "via", "tool", "word", "restored", "chars",
                    "subjects")


@functools.cache
def pages_table(sfx: str = "") -> Table:
    """``project_doc_pages`` : une ligne par page — sa dernière version (son numéro, l'événement qui l'a écrite, qui,
    par où), son titre, les images qu'elle cite, son texte replié pour la recherche."""
    name = f"{PAGES_TABLE}{sfx}"
    return projection_table(
        name,
        Column("project", BigInteger, primary_key=True),
        Column("path", Key(PATH_MAX), primary_key=True),
        Column("version", BigInteger, nullable=False),
        Column("seq", BigInteger, nullable=False),
        Column("at", BigInteger, nullable=False),
        Column("created_at", BigInteger, nullable=False),
        Column("author", Key(64), nullable=False),
        Column("by", Key(HANDLE_MAX), nullable=False),
        Column("via", Key(16), nullable=False),
        Column("tool", LongText, nullable=False),
        Column("chars", BigInteger, nullable=False),
        Column("title", LongText, nullable=False),
        Column("images", LongText, nullable=False),
        Column("search", LongText, nullable=False),
        Column("subjects", LongText, nullable=False),
    )


@functools.cache
def versions_table(sfx: str = "") -> Table:
    """``project_doc_versions`` : une ligne par version gardée d'une page (l'événement qui l'a écrite) — son texte se
    relit dans les contenus du journal (``<seq>.text``)."""
    name = f"{VERSIONS_TABLE}{sfx}"
    return projection_table(
        name,
        Column("seq", BigInteger, primary_key=True),
        Column("project", BigInteger, nullable=False),
        Column("path", Key(PATH_MAX), nullable=False),
        Column("n", BigInteger, nullable=False),
        Column("at", BigInteger, nullable=False),
        Column("author", Key(64), nullable=False),
        Column("by", Key(HANDLE_MAX), nullable=False),
        Column("via", Key(16), nullable=False),
        Column("tool", LongText, nullable=False),
        Column("word", LongText, nullable=False),
        Column("restored", BigInteger, nullable=False),
        Column("chars", BigInteger, nullable=False),
        Column("subjects", LongText, nullable=False),
        Index(f"{name}_page", "project", "path", "n"),
    )


def _text(content: Content | None) -> str:
    return (content.text or "") if content is not None else ""


def _subjects(d: Any) -> str:
    """Les sujets d'une ligne, entre barres (``|user_7|name:alice|``) : l'oubli d'un seul d'entre eux la vide."""
    keys = sorted({k for k in (d.owner, *d.about, *getattr(d, INHERITED, ()), d.by) if k})
    return "|" + "|".join(keys) + "|"


def _merged(old: str, new: str) -> str:
    keys = sorted({k for k in (*old.split("|"), *new.split("|")) if k})
    return "|" + "|".join(keys) + "|"


def _at(t: Table, project: int, path: str) -> Any:
    return (t.c.project == project) & (t.c.path == path)


class Pages:
    """T0 : une ligne par page, une ligne par version gardée — dans la transaction de l'ajout : qui vient d'écrire
    relit aussitôt. Les règles sont celles du réducteur (``stepped``, ``movable``)."""

    def create(self, sql: Sql, sfx: str) -> None:
        sql.create(pages_table(sfx))
        sql.create(versions_table(sfx))

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.drop(pages_table(sfx))
        sql.drop(versions_table(sfx))

    def apply(self, sql: Sql, items: Sequence[Any], sfx: str) -> None:
        t, v = pages_table(sfx), versions_table(sfx)
        for e in items:
            name = e.type.name
            if name == DOC_WRITTEN.name:
                self._write(sql, t, v, e)
            elif name == DOC_MOVED.name:
                self._move(sql, t, v, e)
            elif name == DOC_REMOVED.name:
                d = e.data
                sql.execute(delete(t).where(_at(t, d.project, d.path)))
                sql.execute(delete(v).where(_at(v, d.project, d.path)))

    def _write(self, sql: Sql, t: Table, v: Table, e: Any) -> None:
        d = e.data
        where = _at(t, d.project, d.path)
        rows = sql.query(select(t.c.version, t.c.subjects).where(where))
        count = sql.query(select(func.count()).select_from(t).where(t.c.project == d.project))
        number = stepped(int(rows[0][0]) if rows else None, int(count[0][0]) if count else 0, d)
        if number is None:
            return
        text, tool = _text(d.text), _text(d.tool)
        subjects = _merged(str(rows[0][1] or ""), _subjects(d)) if rows else _subjects(d)
        facts = {"version": number, "seq": e.seq, "at": e.at, "author": d.author, "by": d.by, "via": d.via,
                 "tool": tool, "chars": len(text), "title": title_of(d.path, text),
                 "images": "|" + "|".join(cited_images(text)) + "|", "search": fold(f"{d.path}\n{text}"),
                 "subjects": subjects}
        if rows:
            sql.execute(update(t).where(where).values(**facts))
        else:
            insert_ignore(sql, t, {"project": d.project, "path": d.path, "created_at": e.at, **facts})
        insert_ignore(sql, v, dict(zip(_VERSION_COLUMNS, (
            e.seq, d.project, d.path, number, e.at, d.author, d.by, d.via, tool, _text(d.word),
            max(0, d.restored), len(text), subjects), strict=True)))
        # les plus anciennes sortent de la projection : l'historique d'une page reste borné
        sql.execute(delete(v).where(_at(v, d.project, d.path), v.c.n <= number - DOC_VERSIONS_KEPT))

    def _move(self, sql: Sql, t: Table, v: Table, e: Any) -> None:
        d = e.data
        exists = bool(sql.query(select(t.c.version).where(_at(t, d.project, d.path))))
        taken = bool(sql.query(select(t.c.version).where(_at(t, d.project, d.to))))
        if not movable(exists, taken, d):
            return
        # un chemin libre peut garder les versions d'une page supprimée puis jamais recréée : elles ne se mêlent pas
        sql.execute(delete(v).where(_at(v, d.project, d.to)))
        sql.execute(update(t).where(_at(t, d.project, d.path)).values(path=d.to))
        sql.execute(update(v).where(_at(v, d.project, d.path)).values(path=d.to))

    def forget(self, sql: Sql, subject: str, sfx: str) -> None:
        """L'oubli d'une personne vide les textes de ce qui la concerne : la page et ses versions restent (leur
        chemin, leur numéro), plus son titre, sa recherche, le mot ni le nom de l'outil. Le texte de chaque version
        s'efface avec les contenus du journal."""
        t, v = pages_table(sfx), versions_table(sfx)
        mark = f"|{subject}|"
        sql.execute(update(t).where(func.instr(t.c.subjects, mark) > 0)
                    .values(title="", search="", images="||", tool=""))
        sql.execute(update(v).where(func.instr(v.c.subjects, mark) > 0).values(word="", tool=""))


PROJECTS.projector(PAGES_TABLE, version=1, tier=Tier.T0, types=[DOC_WRITTEN, DOC_MOVED, DOC_REMOVED])(Pages)


# ── Lire la projection ────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Page:
    """Une page lue de la projection : sa dernière version, et ce qui se dit d'elle sans son texte."""

    path: str
    version: int
    seq: int
    at: int
    created_at: int
    author: str
    by: str
    via: str
    tool: str
    chars: int
    title: str
    images: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Version:
    """Une version gardée d'une page : l'événement qui l'a écrite, son numéro, qui, par où, son mot."""

    seq: int
    n: int
    at: int
    author: str
    by: str
    via: str
    tool: str
    word: str
    restored: int
    chars: int


def _page(row: Sequence[Any]) -> Page:
    got = dict(zip(_PAGE_COLUMNS[1:13], row, strict=True))
    return Page(**{**got, "images": tuple(x for x in str(got["images"] or "").split("|") if x)})


def _page_columns(t: Table) -> list[Any]:
    return [t.c[n] for n in _PAGE_COLUMNS[1:13]]


def tree(store: Any, project: int) -> list[Page]:
    """Toutes ses pages, par chemin."""
    if store is None:
        return []
    t = pages_table()
    return [_page(r) for r in store.query_mind(
        select(*_page_columns(t)).where(t.c.project == project).order_by(t.c.path))]


def page(store: Any, project: int, path: str) -> Page | None:
    if store is None or not path:
        return None
    t = pages_table()
    rows = store.query_mind(select(*_page_columns(t)).where(_at(t, project, path)))
    return _page(rows[0]) if rows else None


def landed(store: Any, project: int, path: str, seqs: Sequence[int]) -> bool:
    """Cette écriture est-elle devenue la dernière version de la page ? Deux écritures parties de la même version
    au même instant s'ajoutent toutes deux au journal : seule la première vaut (``stepped``), et qui a écrit la
    seconde doit l'apprendre — on relit ce que la projection en a fait."""
    row = page(store, project, path)
    return row is not None and row.seq in set(seqs)


def found(store: Any, project: int, said: str, limit: int = 20) -> list[Page]:
    """Les pages dont le chemin ou le texte contient ces mots (repliés), les dernières écrites d'abord."""
    words = fold(said.strip())
    if store is None or not words:
        return []
    t = pages_table()
    return [_page(r) for r in store.query_mind(
        select(*_page_columns(t)).where(t.c.project == project, func.instr(t.c.search, words) > 0)
        .order_by(t.c.at.desc(), t.c.path).limit(limit))]


def versions(store: Any, project: int, path: str) -> list[Version]:
    """Les versions gardées d'une page, de la plus récente à la plus ancienne."""
    if store is None:
        return []
    v = versions_table()
    rows = store.query_mind(select(*[v.c[n] for n in _VERSION_COLUMNS if n not in ("project", "path", "subjects")])
                            .where(_at(v, project, path)).order_by(v.c.n.desc()))
    return [Version(*r) for r in rows]


def version(store: Any, project: int, path: str, number: int) -> Version | None:
    return next((x for x in versions(store, project, path) if x.n == number), None)


def text_of(store: Any, seq: int) -> str | None:
    """Le texte de la version qu'a écrite cet événement ; ``None`` : il n'est plus là (oublié)."""
    if store is None or not seq:
        return None
    ref = f"{seq}.text"
    return store.content([ref]).get(ref)


def excerpt(text: str, said: str, before: int = 40, after: int = 120) -> str:
    """Ce qu'une recherche montre d'une page : le passage autour du premier endroit où les mots apparaissent."""
    folded, words = fold(text), fold(said.strip())
    at = folded.find(words) if words and len(folded) == len(text) else -1
    if at < 0:
        return clipped(text, before + after)
    start = max(0, at - before)
    return ("…" if start else "") + clipped(text[start:at + len(words) + after], before + after + len(words))
