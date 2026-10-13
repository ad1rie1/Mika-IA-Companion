"""Ses outils pour retrouver et rouvrir ce qu'on lui a envoyé, et le relier à ce qu'elle sait (ADR 0106).

- ``attachments_search`` : les pièces reçues (photos, documents, vocaux), par ce qu'elles contiennent — leur nom, ce
  qu'elle y a lu, ce qu'elle sait qui va avec —, de la personne à qui elle parle ou de tout le monde, d'une sorte ;
  sans question, les plus récentes. Chacune dit ce qu'elle sait qui y est relié.
- ``attachment_open`` : rouvrir une pièce — ce qu'elle y a lu, page par page pour un long document ; une photo se
  regarde de nouveau pour une question (« qu'est-ce qui est écrit sur le ticket ? ») ; et ce qu'elle sait qui va
  avec.
- ``attachment_link`` : relier une pièce à ce qu'elle sait (ou l'en délier) — en mots : elle dit de quoi il s'agit,
  l'outil trouve l'élément.

Ce qu'elle peut rouvrir devant qui suit le verdict commun (``vocab.lineage.admits``, celui de sa mémoire) : une
pièce est confiée par qui l'a envoyée — personnelle en privé, anodine dans un salon public, une confidence quand sa
lecture l'a jugée intime. Elle la rouvre devant son expéditeur, dans le salon où elle a été postée, pour elle-même ;
devant quelqu'un d'autre seulement si la règle des liens le permet. Ce qu'elle sait qui va avec passe par le même
verdict, élément par élément. Elle ne renvoie jamais une pièce reçue (ADR 0062). Les repères (« 3f9a2c1d ») ne
servent qu'à ses outils.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from mika.contracts import attachments as c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.faculties.attachments.faculty import (
    ATTACHMENTS,
    PORT,
    VECTOR_KIND,
    FileRow,
    by_prefix,
    by_seqs,
    carriers,
    linked_knowledge,
    links,
    recent,
    rows,
)
from mika.kernel.faculty import ToolResult
from mika.kernel.frame import Audience, Frame
from mika.ports.preprocess import Upload, cite, inert
from mika.ports.shares import MAX_SHARE_BYTES
from mika.vocab.days import when_fr
from mika.vocab.episodes import CONVERSATIONAL, WORKING
from mika.vocab.knowledge import Known, lineage_of
from mika.vocab.lineage import admits
from mika.vocab.people import is_identifiable
from mika.vocab.phrasebook import family, phrase
from mika.vocab.words import fold, words

BUNDLE = "attachments"
SEARCH, OPEN, LINK = "attachments_search", "attachment_open", "attachment_link"
#: ce qu'une recherche lit de candidats : par le sens, par les mots, ou les plus récents
VECTOR_CANDIDATES, WORD_CANDIDATES, RECENT_CANDIDATES = 60, 40, 200
#: ce qu'une ligne de recherche montre de ce qu'elle y a lu
SEEN_SHOWN = 220
#: une page d'une pièce rouverte
PAGE_CHARS = 6000
#: ce qu'elle sait qui va avec : montré au plus, et sa longueur
LINKS_SHOWN, LINK_CHARS = 8, 300
#: une similarité en deçà, et rien ne se relie (« de quoi parles-tu ? »)
LINK_FLOOR = 0.3
#: un repère : le début de la clé d'une pièce
REF = re.compile(r"^[0-9a-f]{6,32}$")

ATTACHMENTS.bundle(BUNDLE, phrase("attachments.tools.bundle"))


# ── Ce qui est permis ─────────────────────────────────────────────────────


class Here:
    """Qui écoute, et comment juger une pièce ou un élément devant elle (calculé une fois par appel)."""

    def __init__(self, frame: Frame) -> None:
        self.frame = frame
        self.aud: Audience | None = frame.audience
        ep = frame.episode
        target = ep.target if ep is not None else None
        self.person = frame.get(identity_c.PERSON(target)) if target and is_identifiable(target) else None
        self.handles = tuple(sorted({self.person, *frame.get(identity_c.HANDLES(self.person))})) \
            if self.person else ()
        self.resolve, self.presumed = identity_c.resolvers(frame.get)

    def sender(self, r: FileRow) -> str:
        return self.frame.get(identity_c.PERSON(r.handle)) or r.handle

    def sees(self, r: FileRow, rooms: Sequence[str | None] = ()) -> bool:
        """Peut-elle la rouvrir ici ? Dans le salon où elle a été postée, oui ; sinon, le verdict commun : une pièce
        confiée par son expéditeur (``lineage_of``), entendue par lui seul en privé."""
        aud = self.aud
        if aud is None:
            return False
        if aud.room and aud.room in {r.room, *rooms}:
            return True
        sender = self.sender(r)
        lineage = lineage_of(r.seq, (sender,), r.sensitivity, told_by=(sender,),
                             heard_by=() if r.room else (sender,))
        return admits(lineage, self.person, aud, resolve=self.resolve, presumed=self.presumed).ok

    def knows(self, k: Known) -> bool:
        """Un élément de ce qu'elle sait peut-il se dire ici (le verdict de sa mémoire) ?"""
        return self.aud is not None and admits(k.lineage, self.person, self.aud, resolve=self.resolve,
                                               presumed=self.presumed).ok


def _visible(here: Here, found: Sequence[FileRow], store: Any) -> list[FileRow]:
    out = []
    for r in found:
        rooms = [] if here.aud is None or not here.aud.room or r.room == here.aud.room \
            else [room for _s, _a, room in carriers(store, r.id)]
        if here.sees(r, rooms):
            out.append(r)
    return out


def _who(here: Here, r: FileRow) -> str:
    sender = here.sender(r)
    name = here.frame.get(identity_c.IDENTITY(sender)).name or here.frame.get(identity_c.IDENTITY(r.handle)).name
    return phrase("attachments.tools.from", name=inert(name, 60)) if name else phrase("attachments.tools.from_someone")


def _kind(r: FileRow) -> str:
    return family("attachments.tools.kinds").get(r.kind, r.kind)


def _when(here: Here, at: int) -> str:
    return when_fr(at, here.frame.now, here.frame.env.tz_of(here.frame.root))


def _related(here: Here, store: Any, files: Sequence[str]) -> dict[str, list[Known]]:
    """Pièce → ce qu'elle sait qui y est relié et qui peut se dire ici."""
    linked = links(store, files)
    known = linked_knowledge(store, [i for ls in linked.values() for i, _by in ls])
    return {f: [known[i] for i, _by in ls if i in known and here.knows(known[i])] for f, ls in linked.items()}


def _item_kind(k: Known) -> str:
    return family("attachments.tools.items").get(k.kind, k.kind)


def _piece(here: Here, store: Any, wanted: str) -> FileRow | None:
    """La pièce que désigne un repère (le début de sa clé) ou un nom (avec ou sans extension) — la plus récente de
    celles qu'elle peut rouvrir ici."""
    key = wanted.strip().lower().lstrip("#")
    if REF.fullmatch(key):
        got = _visible(here, by_prefix(store, key), store)
        if got:
            return got[0]
    name = fold(wanted.strip().strip("«»\"' "))
    if not name:
        return None
    named = [r for r in recent(store, words=[name.rpartition(".")[0] or name], limit=RECENT_CANDIDATES)
             if name in (fold(r.name), fold(r.name).rpartition(".")[0])]
    got = _visible(here, named, store)
    return got[0] if got else None


# ── Chercher ──────────────────────────────────────────────────────────────


class SearchArgs(BaseModel):
    query: str = Field(default="", max_length=300, description=phrase("attachments.tools.search.query"))
    from_them: bool = Field(default=False, description=phrase("attachments.tools.search.from_them"))
    kind: Literal["", "image", "audio", "file"] = Field(default="", description=phrase("attachments.tools.search.kind"))
    limit: int = Field(default=5, ge=1, le=10)


#: par le sens seul, une pièce en deçà ne répond pas à la question
SIM_FLOOR = 0.25


def _overlap(r: FileRow, wanted: set[str]) -> float:
    """La part des mots de la question qu'on retrouve dans son nom ou ce qu'elle y a lu."""
    return len(wanted & set(words(f"{r.name} {r.seen or ''}"))) / len(wanted) if wanted else 0.0


def _score(r: FileRow, sim: float, wanted: set[str]) -> float:
    """Le sens d'abord, les mots ensuite."""
    return sim + 0.3 * _overlap(r, wanted)


@ATTACHMENTS.tool(SEARCH, description=phrase("attachments.tools.search.description"), args=SearchArgs, bundle=BUNDLE,
                  episodes=[*CONVERSATIONAL, *WORKING], max_calls_per_episode=4)
async def attachments_search(args: SearchArgs, ctx: Any) -> Any:
    store = ctx.ports.get("store")
    here = Here(ctx.frame)
    if store is None or here.aud is None:
        return ToolResult(ok=False, content=phrase("attachments.tools.unavailable"))
    handles = here.handles if args.from_them and here.handles else None
    if args.from_them and not here.handles:
        return ToolResult(content=phrase("attachments.tools.search.nothing"))
    query = args.query.strip()
    sims: dict[str, float] = {}
    candidates: dict[str, FileRow] = {}
    if query:
        vectors = ctx.ports.get(c.VECTORS)
        hits = await vectors.search(query, VECTOR_CANDIDATES, kinds={VECTOR_KIND}) if vectors is not None else []
        found = by_seqs(store, [k for k, _s in hits])
        for key, sim in hits:
            r = found.get(key)
            if r is not None:
                sims[r.id] = max(sim, sims.get(r.id, sim))
                candidates[r.id] = r
        for w in words(query)[:6]:
            for r in recent(store, handles=handles, kind=args.kind, words=[w], limit=WORD_CANDIDATES):
                candidates.setdefault(r.id, r)
    else:
        candidates = {r.id: r for r in recent(store, handles=handles, kind=args.kind, limit=RECENT_CANDIDATES)}
    pool = [r for r in candidates.values() if (handles is None or r.handle in handles)
            and (not args.kind or r.kind == args.kind)]
    wanted = set(words(query))
    if query:
        pool.sort(key=lambda r: (-_score(r, sims.get(r.id, 0.0), wanted), -r.at, r.id))
        pool = [r for r in pool if _overlap(r, wanted) > 0 or sims.get(r.id, 0.0) >= SIM_FLOOR]
    shown: list[FileRow] = []
    for r in pool:
        if _visible(here, [r], store):
            shown.append(r)
        if len(shown) >= args.limit:
            break
    if not shown:
        return ToolResult(content=phrase("attachments.tools.search.nothing"))
    related = _related(here, store, [r.id for r in shown])
    lines = []
    for r in shown:
        seen = inert(r.seen, SEEN_SHOWN) if r.seen else phrase("attachments.tools.unread")
        known = related.get(r.id, [])
        tied = ""
        if known:
            tied = phrase("attachments.tools.search.tied", text=inert(known[0].text, 120)) + \
                (phrase("attachments.tools.search.more", count=len(known) - 1) if len(known) > 1 else "")
        lines.append(phrase("attachments.tools.search.line", ref=r.ref, name=inert(r.name, 120), kind=_kind(r),
                            who=_who(here, r), when=_when(here, r.at),
                            gone=phrase("attachments.tools.gone") if r.gone else "", seen=seen, tied=tied))
    return ToolResult(content="\n".join([*lines, phrase("attachments.tools.search.note")]))


# ── Rouvrir ───────────────────────────────────────────────────────────────


class OpenArgs(BaseModel):
    piece: str = Field(min_length=1, max_length=200, description=phrase("attachments.tools.open.piece"))
    question: str = Field(default="", max_length=500, description=phrase("attachments.tools.open.question"))
    page: int = Field(default=1, ge=1, le=100, description=phrase("attachments.tools.open.page"))


def pages(text: str, size: int = PAGE_CHARS) -> list[str]:
    """Un long texte en pages, coupées sur une fin de ligne (sinon un blanc) quand c'est possible."""
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = max(text.rfind("\n", start + size // 2, end), text.rfind(" ", start + size // 2, end))
            end = cut if cut > start else end
        out.append(text[start:end].strip())
        start = end
    return [p for p in out if p] or [""]


@ATTACHMENTS.tool(OPEN, description=phrase("attachments.tools.open.description"), args=OpenArgs, bundle=BUNDLE,
                  episodes=[*CONVERSATIONAL, *WORKING], max_calls_per_episode=4)
async def attachment_open(args: OpenArgs, ctx: Any) -> Any:
    store = ctx.ports.get("store")
    here = Here(ctx.frame)
    if store is None or here.aud is None:
        return ToolResult(ok=False, content=phrase("attachments.tools.unavailable"))
    r = _piece(here, store, args.piece)
    if r is None:
        return ToolResult(ok=False, content=phrase("attachments.tools.not_found"))
    out = [phrase("attachments.tools.open.head", name=inert(r.name, 120), kind=_kind(r), who=_who(here, r),
                  when=_when(here, r.at))]
    question = args.question.strip()
    looked = await _look(ctx, r, question) if question and r.kind == c.IMAGE else None
    if looked:
        out += [phrase("attachments.tools.open.looked", question=inert(question, 200)), cite(looked)]
    elif question and r.kind == c.IMAGE:
        out.append(phrase("attachments.tools.open.cannot_look"))
    if not looked:
        if r.seen:
            parts = pages(r.seen)
            n = min(args.page, len(parts))
            out += [phrase("attachments.tools.open.seen"), cite(parts[n - 1], limit=PAGE_CHARS + 100)]
            if len(parts) > 1:
                out.append(phrase("attachments.tools.open.page_of", page=n, pages=len(parts)))
        else:
            out.append(phrase("attachments.tools.unread"))
    if r.gone:
        out.append(phrase("attachments.tools.open.gone"))
    known = _related(here, store, [r.id]).get(r.id, [])
    if known:
        out.append(phrase("attachments.tools.open.tied"))
        out += [phrase("attachments.tools.open.tied_line", kind=_item_kind(k), text=inert(k.text, LINK_CHARS))
                for k in known[:LINKS_SHOWN]]
    else:
        out.append(phrase("attachments.tools.open.untied"))
    return ToolResult(content="\n".join(out))


async def _look(ctx: Any, r: FileRow, question: str) -> str | None:
    """La regarder de nouveau, pour une question (ses octets doivent être là, et quelque chose pour voir)."""
    port, reader = ctx.ports.get(PORT), ctx.ports.get("preprocess")
    if r.gone or port is None or reader is None:
        return None
    data = await port.read(r.id, MAX_SHARE_BYTES)
    if data is None:
        return None
    return await reader.look(Upload(r.name, r.mime, data), question)


# ── Relier ────────────────────────────────────────────────────────────────


class LinkArgs(BaseModel):
    piece: str = Field(min_length=1, max_length=200, description=phrase("attachments.tools.link.piece"))
    element: str = Field(min_length=3, max_length=300, description=phrase("attachments.tools.link.element"))
    remove: bool = Field(default=False, description=phrase("attachments.tools.link.remove"))


#: ce qu'elle peut relier à une pièce : un souvenir, une croyance, un moment de la vie de quelqu'un
LINKABLE = frozenset({memory_c.SOUVENIR, memory_c.BELIEF, memory_c.EVENT})


async def _element(ctx: Any, here: Here, text: str, among: Sequence[int] | None = None) -> Known | None:
    """L'élément de ce qu'elle sait que ces mots désignent — le plus proche, s'il l'est assez, et qu'il peut se dire
    ici (parmi ``among`` quand c'est pour délier)."""
    vectors, store = ctx.ports.get("vectors"), ctx.ports.get("store")
    if vectors is None or store is None:
        return None
    if among is not None and not among:
        return None
    hits = await vectors.search(text, 12, kinds=set(LINKABLE), keys=list(among) if among is not None else None)
    known = linked_knowledge(store, [k for k, _s in hits])
    wanted = set(words(text))
    best: tuple[float, Known] | None = None
    for key, sim in hits:
        k = known.get(key)
        if k is None or k.kind not in LINKABLE or not here.knows(k):
            continue
        score = sim + (0.3 * len(wanted & set(words(k.text))) / len(wanted) if wanted else 0.0)
        if score >= LINK_FLOOR and (best is None or score > best[0]):
            best = (score, k)
    return best[1] if best is not None else None


@ATTACHMENTS.tool(LINK, description=phrase("attachments.tools.link.description"), args=LinkArgs, bundle=BUNDLE,
                  episodes=[*CONVERSATIONAL, *WORKING], max_calls_per_episode=3)
async def attachment_link(args: LinkArgs, ctx: Any) -> Any:
    store = ctx.ports.get("store")
    here = Here(ctx.frame)
    if store is None or here.aud is None:
        return ToolResult(ok=False, content=phrase("attachments.tools.unavailable"))
    r = _piece(here, store, args.piece)
    if r is None:
        return ToolResult(ok=False, content=phrase("attachments.tools.not_found"))
    current = [i for i, _by in links(store, [r.id]).get(r.id, [])]
    k = await _element(ctx, here, args.element, current if args.remove else None)
    if k is None:
        missing = phrase("attachments.tools.link.not_tied") if args.remove else \
            phrase("attachments.tools.link.nothing")
        return ToolResult(ok=False, content=missing)
    text = inert(k.text, 160)
    if not args.remove and k.id in current:
        return ToolResult(content=phrase("attachments.tools.link.already", text=text))
    await ctx.emit(c.LINKED.draft(file=r.id, item=k.id, by=c.BY_HER, removed=args.remove))
    if args.remove:
        return ToolResult(content=phrase("attachments.tools.link.undone", text=text))
    return ToolResult(content=phrase("attachments.tools.link.done", text=text))


def visible_rows(frame: Frame, store: Any, files: Sequence[str]) -> list[FileRow]:
    """Ces pièces, celles qu'elle peut rouvrir devant l'audience de ce cadre (ses sections, ses autres outils)."""
    return _visible(Here(frame), rows(store, files), store)
