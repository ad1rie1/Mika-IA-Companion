"""La documentation d'un projet, pour elle pendant une exécution (ADR 0289) : ses outils — ``doc_list``,
``doc_read``, ``doc_search``, ``doc_write`` — et la section du prompt qui lui dit qu'elle existe (``project_docs``).

- Elle lit et écrit la documentation **de son projet** ; elle lit celle des projets que le sien lit **quand le lien
  la donne** (``links.Grant.documentation``, relu à chaque appel : un droit retiré coupe la lecture à l'appel
  suivant), et ne l'écrit jamais.
- Une écriture nomme la version qu'elle a lue (``base``) : une page changée depuis — par une personne dans son
  navigateur, par un outil — ne s'écrase pas, l'outil le lui dit.
- **Ce qu'une personne a écrit dans une page est une donnée, pas une consigne** : le texte d'une page revient cité
  (``kernel.prompt.cited`` : chaque ligne préfixée, rien n'y imite une section), ce que rend l'outil le dit, et ce
  qu'il rend est au niveau de ce qu'écrit le projet lu.

Les règles et la projection sont dans ``docs.py`` ; ses phrases dans la voix (``projects.docs``,
``projects.tools.docs``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.faculties.projects import docs, links
from mika.faculties.projects.faculty import DOC_PAGES_MAX, PROJECTS, Project, ProjectsState, written
from mika.faculties.projects.prompt import _project
from mika.faculties.projects.tools import RUNS, current, gone
from mika.kernel.faculty import ToolResult
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody, Zone, cited
from mika.vocab.days import ago_words
from mika.vocab.phrasebook import phrase

LIST, READ, SEARCH, WRITE = "doc_list", "doc_read", "doc_search", "doc_write"
TOOLS = (LIST, READ, SEARCH, WRITE)
#: ce qu'une lecture rend d'une page, par morceau (caractères) ; les pages listées et trouvées, au plus
PART_CHARS = 20_000
LISTED, FOUND = 100, 12
#: ce que la section du prompt nomme de ses pages, au plus
SECTION_PAGES = 30
SECTION_FLOOR = 300


def _no(content: str) -> ToolResult:
    """Le refus d'un outil : rien n'a été écrit."""
    return ToolResult(ok=False, content=content)


def _store(ctx: Any) -> Any:
    return ctx.ports.get("store")


def readable(s: ProjectsState, frame: Frame, p: Project) -> tuple[Project, ...]:
    """Les projets dont ce projet lit la documentation, maintenant : ceux qu'il lit et dont le lien la donne."""
    return tuple(r.project for r in links.readings(s, p, links.world_of(frame))
                 if r.project is not None and not r.suspended and r.grant.documentation)


def _space(ctx: Any, project: int) -> tuple[Project, Project] | ToolResult:
    """Le projet de l'exécution et celui dont on lit la documentation (lui-même sans numéro) ; un projet qu'il ne
    lit pas, ou dont le lien ne donne pas la documentation : un refus."""
    got = current(ctx)
    if got is None:
        return _no(gone())
    p = got[0]
    if not project or project == p.id:
        return p, p
    target = next((t for t in readable(ctx.frame.state("projects"), ctx.frame, p) if t.id == project), None)
    if target is None:
        return _no(phrase("projects.tools.docs.not_given", id=project))
    return p, target


def _who(page: docs.Page | docs.Version) -> str:
    """Qui a écrit cette version, en mots pour elle : elle-même, une personne, un outil par MCP."""
    if page.author == c.BY_SELF:
        return phrase("projects.tools.docs.by.self")
    return phrase("projects.tools.docs.by.mcp") if page.via == docs.MCP else phrase("projects.tools.docs.by.person")


#: ce qu'on montre, au plus, du titre d'une page dans une liste
TITLE_SHOWN = 120


def _title(page: docs.Page) -> str:
    """Le titre d'une page, cité (ADR 0292) : c'est le texte de qui l'a écrite — une personne, un outil par MCP —,
    pas un mot du moteur. Sur une ligne, borné, sans rien qui ferme ses guillemets ni imite une section."""
    raw = " ".join((page.title or page.path).split()).replace("«", "‹").replace("»", "›")
    return cited(raw, TITLE_SHOWN, note=False).removeprefix("> ") if raw else page.path


def _line(page: docs.Page, now: int) -> str:
    return phrase("projects.tools.docs.line", path=page.path, title=_title(page), version=page.version,
                  ago=ago_words(now - page.at), who=_who(page))


def _floor(target: Project) -> int:
    """Ce que vaut ce qu'un outil rend d'une documentation : le niveau de ce qu'écrit le projet lu."""
    return written(target)


class ListArgs(BaseModel):
    project: int = Field(default=0, ge=0, description=phrase("projects.tools.docs.arg.project"))


@PROJECTS.tool(LIST, description=phrase("projects.tools.docs.list.description"),
               label=phrase("projects.tools.docs.list.label"), args=ListArgs, bundle="projects", episodes=RUNS,
               max_calls_per_episode=12)
async def doc_list(args: ListArgs, ctx: Any) -> Any:
    got = _space(ctx, args.project)
    if isinstance(got, ToolResult):
        return got
    p, target = got
    pages = docs.tree(_store(ctx), target.id)
    if not pages:
        return phrase("projects.tools.docs.list.empty")
    lines = [phrase("projects.tools.docs.list.head", count=len(pages)), phrase("projects.tools.docs.data")]
    lines += ["- " + _line(x, ctx.frame.now) for x in pages[:LISTED]]
    if len(pages) > LISTED:
        lines.append(phrase("projects.tools.docs.list.more", count=len(pages) - LISTED))
    if target.docs.images:
        lines.append(phrase("projects.tools.docs.list.images",
                            names=", ".join(i.name for i in target.docs.images[:40])))
    return ToolResult(content="\n".join(lines), floor=_floor(target))


class ReadArgs(BaseModel):
    path: str = Field(min_length=1, max_length=docs.PATH_MAX, description=phrase("projects.tools.docs.arg.path"))
    project: int = Field(default=0, ge=0, description=phrase("projects.tools.docs.arg.project"))
    part: int = Field(default=1, ge=1, le=20, description=phrase("projects.tools.docs.read.part"))


@PROJECTS.tool(READ, description=phrase("projects.tools.docs.read.description"),
               label=phrase("projects.tools.docs.read.label"), args=ReadArgs, bundle="projects", episodes=RUNS,
               max_calls_per_episode=24)
async def doc_read(args: ReadArgs, ctx: Any) -> Any:
    got = _space(ctx, args.project)
    if isinstance(got, ToolResult):
        return got
    _, target = got
    path = docs.page_path(args.path.strip())
    page = docs.page(_store(ctx), target.id, path) if path is not None else None
    if page is None:
        return _no(phrase("projects.tools.docs.unknown", path=args.path[:docs.PATH_MAX]))
    text = docs.text_of(_store(ctx), page.seq)
    if text is None:
        return _no(phrase("projects.tools.docs.read.forgotten", path=page.path))
    parts = max(1, -(-len(text) // PART_CHARS))
    if args.part > parts:
        return _no(phrase("projects.tools.docs.read.no_part", parts=parts))
    piece = text[(args.part - 1) * PART_CHARS:args.part * PART_CHARS]
    head = phrase("projects.tools.docs.read.head", path=page.path, version=page.version, who=_who(page),
                  ago=ago_words(ctx.frame.now - page.at))
    if parts > 1:
        head += " " + phrase("projects.tools.docs.read.parts", part=args.part, parts=parts)
    body = cited(piece, PART_CHARS * 2, note=False) if piece.strip() else phrase("projects.tools.docs.read.blank")
    return ToolResult(content="\n".join((head, phrase("projects.tools.docs.data"), body)), floor=_floor(target))


class SearchArgs(BaseModel):
    words: str = Field(min_length=1, max_length=120, description=phrase("projects.tools.docs.search.words"))
    project: int = Field(default=0, ge=0, description=phrase("projects.tools.docs.arg.project"))


@PROJECTS.tool(SEARCH, description=phrase("projects.tools.docs.search.description"),
               label=phrase("projects.tools.docs.search.label"), args=SearchArgs, bundle="projects", episodes=RUNS,
               max_calls_per_episode=12)
async def doc_search(args: SearchArgs, ctx: Any) -> Any:
    got = _space(ctx, args.project)
    if isinstance(got, ToolResult):
        return got
    _, target = got
    store = _store(ctx)
    pages = docs.found(store, target.id, args.words, FOUND)
    if not pages:
        return phrase("projects.tools.docs.search.none", words=args.words)
    lines = [phrase("projects.tools.docs.search.head", count=len(pages), words=args.words),
             phrase("projects.tools.docs.data")]
    for page in pages:
        lines.append("- " + _line(page, ctx.frame.now))
        text = docs.text_of(store, page.seq)
        if text:
            lines.append(cited(docs.excerpt(text, args.words), 400, note=False))
    return ToolResult(content="\n".join(lines), floor=_floor(target))


class WriteArgs(BaseModel):
    path: str = Field(min_length=1, max_length=docs.PATH_MAX, description=phrase("projects.tools.docs.arg.path"))
    text: str = Field(min_length=1, max_length=docs.PAGE_CHARS, description=phrase("projects.tools.docs.write.text"))
    word: str = Field(min_length=1, max_length=docs.WORD_MAX, description=phrase("projects.tools.docs.write.word"))
    base: int = Field(default=0, ge=0, description=phrase("projects.tools.docs.write.base"))


@PROJECTS.tool(WRITE, acts=True, description=phrase("projects.tools.docs.write.description"),
               label=phrase("projects.tools.docs.write.label"), args=WriteArgs, bundle="projects", episodes=RUNS,
               max_calls_per_episode=24)
async def doc_write(args: WriteArgs, ctx: Any) -> Any:
    got = current(ctx)
    if got is None:
        return gone()
    p = got[0]
    path = docs.page_path(args.path.strip())
    if path is None:
        return _no(phrase("projects.tools.docs.bad_path", path=args.path[:docs.PATH_MAX]))
    old = docs.page_at(p.docs, path)
    if old is None and args.base:
        return _no(phrase("projects.tools.docs.unknown", path=path))
    if old is None and len(p.docs.pages) >= DOC_PAGES_MAX:
        return _no(phrase("projects.tools.docs.write.full", count=DOC_PAGES_MAX))
    if old is not None and args.base != old.version:
        return _no(phrase("projects.tools.docs.write.moved", path=path, version=old.version))
    commit = await ctx.emit(docs.writing(p, path, args.text, word=args.word, base=args.base))
    if not commit.deduped and not docs.landed(_store(ctx), p.id, path, commit.seqs):
        # une personne a enregistré la même page au même instant : la sienne vaut, celle-ci n'a rien écrasé
        return _no(phrase("projects.tools.docs.write.moved", path=path, version=(old.version if old else 0) + 1))
    if old is None:
        return phrase("projects.tools.docs.write.created", path=path)
    return phrase("projects.tools.docs.write.done", path=path, version=old.version + 1)


# ── La section du prompt ──────────────────────────────────────────────────


@PROJECTS.section("project_docs", zone=Zone.VOLATILE, episodes=RUNS, trim_rank=58, floor_chars=SECTION_FLOOR,
                  title=phrase("projects.docs.title"), reads=[identity_c.IS_OWNER])
def _docs_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ce qu'il y a dans la documentation de son projet (les chemins de ses pages, bornés) et de quels projets lus
    elle peut lire la documentation — les droits relus à chaque exécution. Les chemins sont écrits par elle et par
    des personnes : la section le dit, et prend le niveau de ce qu'écrit le projet."""
    got = _project(s, frame)
    if got is None:
        return None
    p = got[0]
    given = readable(s, frame, p)
    lines = [phrase("projects.docs.head"), phrase("projects.docs.data")]
    if p.docs.pages:
        shown = sorted(x.path for x in p.docs.pages)
        lines.append(phrase("projects.docs.pages", count=len(shown), paths=", ".join(shown[:SECTION_PAGES])))
        if len(shown) > SECTION_PAGES:
            lines.append(phrase("projects.docs.more", count=len(shown) - SECTION_PAGES))
    else:
        lines.append(phrase("projects.docs.empty"))
    lines += [phrase("projects.docs.linked", id=t.id, count=len(t.docs.pages)) for t in given]
    level = max([written(p), *(written(t) for t in given)])
    return SectionBody("\n".join(lines), level=level, provenance=tuple(f"project:{t.id}" for t in given))
