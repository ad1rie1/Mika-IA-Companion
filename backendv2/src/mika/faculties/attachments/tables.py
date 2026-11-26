"""Les tables des pièces reçues (ADR 0106), leur projecteur et leurs lecteurs — sans la faculté.

- ``received_files`` (``files_table``), ``received_messages`` (``carried_table``), ``received_links``
  (``links_table``) : déclarées pour les deux moteurs (ADR 0101), suffixées de leur version ;
- ``ReceivedFiles`` : le projecteur T0 qui les tient, dans la même transaction que l'ajout ; il lit aussi les types
  de la mémoire qui désignent leurs pièces (``MEMORY_LINKS``). La faculté l'enregistre (``faculty.py``) ;
- leurs lecteurs : ``FileRow``, ``rows``, ``row``, ``by_prefix``, ``by_seqs``, ``recent``, ``count``, ``carriers``,
  ``links``, ``usage``, ``subjects_of``, et ``linked_knowledge`` (ce qu'elle sait, par la porte de la mémoire).

Ce module n'importe pas ``faculty.py`` : c'est elle qui lit ses tables et ses lecteurs (l'enregistrement du
projecteur, l'index des vecteurs des pièces) ; l'inverse ferait un cycle.
"""

from __future__ import annotations

import functools
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import BigInteger, Column, Index, Table, delete, func, select, update

from mika.contracts import attachments as c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.ports.shares import valid_id
from mika.ports.sql import HANDLE_MAX, Key, LongText, insert_ignore, projection_table
from mika.ports.store import Sql
from mika.vocab.knowledge import knowns
from mika.vocab.words import fold

#: les événements de la mémoire qui désignent leurs pièces (``pieces``) : l'élément est l'événement lui-même, ou
#: celui qu'il renforce
_CREATES = (memory_c.REMEMBERED, memory_c.BELIEVED, memory_c.EVENT_NOTED)
_TOUCHES = (memory_c.REINFORCED, memory_c.ATTESTED)
MEMORY_LINKS = (*_CREATES, *_TOUCHES)


# ── Les projections T0 ────────────────────────────────────────────────────

_FILE_COLUMNS = ("id", "seq", "at", "message", "idx", "handle", "room", "public", "subjects", "name", "mime", "size",
                 "digest", "kind", "seen", "readable", "stored", "sensitivity", "folded", "touched", "expired_at",
                 "reason")


@functools.cache
def files_table(sfx: str = "") -> Table:
    """``received_files`` (suffixée de sa version) : une ligne par pièce lue."""
    name = f"{c.TABLE}{sfx}"
    return projection_table(
        name,
        Column("id", Key(64), primary_key=True),
        Column("seq", BigInteger, nullable=False),
        Column("at", BigInteger, nullable=False),
        Column("message", BigInteger, nullable=False),
        Column("idx", BigInteger, nullable=False),
        Column("handle", Key(HANDLE_MAX), nullable=False),
        Column("room", Key(HANDLE_MAX)),
        Column("public", BigInteger, nullable=False),
        Column("subjects", LongText, nullable=False),
        Column("name", LongText, nullable=False),
        Column("mime", LongText, nullable=False),
        Column("size", BigInteger, nullable=False),
        Column("digest", LongText, nullable=False),
        Column("kind", Key(16), nullable=False),
        Column("seen", LongText),
        Column("readable", BigInteger, nullable=False),
        Column("stored", BigInteger, nullable=False),
        Column("sensitivity", BigInteger, nullable=False),
        Column("folded", LongText, nullable=False),
        Column("touched", BigInteger, nullable=False),
        Column("expired_at", BigInteger),
        Column("reason", LongText),
        Index(f"{name}_handle", "handle", "at"),
        Index(f"{name}_seq", "seq"),
        Index(f"{name}_touched", "touched"),
    )


@functools.cache
def carried_table(sfx: str = "") -> Table:
    """``received_messages`` : un message, une pièce qu'il porte (sa place dans le message)."""
    name = f"{c.CARRIED}{sfx}"
    return projection_table(
        name,
        Column("message", BigInteger, primary_key=True, autoincrement=False),
        Column("file", Key(64), primary_key=True),
        Column("idx", BigInteger, nullable=False),
        Column("at", BigInteger, nullable=False),
        Column("handle", Key(HANDLE_MAX), nullable=False),
        Column("room", Key(HANDLE_MAX)),
        Index(f"{name}_file", "file"),
        Index(f"{name}_handle", "handle"),
    )


@functools.cache
def links_table(sfx: str = "") -> Table:
    """``received_links`` : une pièce, un élément de ce qu'elle sait (``item`` : le ``seq`` d'un souvenir, d'une
    croyance, d'un moment), qui l'a relié, quand."""
    name = f"{c.LINKS}{sfx}"
    return projection_table(
        name,
        Column("file", Key(64), primary_key=True),
        Column("item", BigInteger, primary_key=True, autoincrement=False),
        Column("by", Key(16), nullable=False),
        Column("at", BigInteger, nullable=False),
        Index(f"{name}_item", "item"),
    )


def _subjects(keys: Iterable[str]) -> str:
    """Les sujets d'une ligne, entre barres (``|user_7|name:alice|``) : l'oubli d'un seul d'entre eux la retire."""
    got = sorted({k for k in keys if k})
    return "|" + "|".join(got) + "|"


def _forgotten(text: Any) -> bool:
    """Un texte relu après l'oubli de qui il concerne : sa référence reste, plus son texte."""
    return text is not None and getattr(text, "ref", None) is not None and getattr(text, "text", None) is None


def search_text(name: str, seen: str) -> str:
    """Ce qu'une recherche par mots compare : le nom et ce qu'elle y a lu, repliés (casse et accents)."""
    return fold(f"{name}\n{seen}")[:200_000]


class ReceivedFiles:
    """T0 : les pièces lues, les messages qui les portent, leurs liens (même transaction que l'ajout : l'outil qui
    cherche juste après trouve déjà la pièce)."""

    def create(self, sql: Sql, sfx: str) -> None:
        sql.create(files_table(sfx))
        sql.create(carried_table(sfx))
        sql.create(links_table(sfx))

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.drop(files_table(sfx))
        sql.drop(carried_table(sfx))
        sql.drop(links_table(sfx))

    def apply(self, sql: Sql, items: Sequence[Any], sfx: str) -> None:
        t, m, ln = files_table(sfx), carried_table(sfx), links_table(sfx)
        for e in items:
            d, name = e.data, e.type.name
            if name == rt.PERCEPTION_RECEIVED.name:
                rows = [{"message": e.seq, "file": a.file, "idx": i, "at": e.at, "handle": d.handle, "room": d.room}
                        for i, a in enumerate(d.attachments, 1) if a.file and valid_id(a.file)]
                if rows:
                    insert_ignore(sql, m, rows)
            elif name == c.KEPT.name:
                if _forgotten(d.name) or _forgotten(d.seen):
                    continue  # une reconstruction relit tout le journal : une pièce oubliée ne revient pas
                seen = d.seen.text if d.seen is not None else None
                insert_ignore(sql, t, dict(zip(_FILE_COLUMNS, (
                    d.file, e.seq, e.at, d.message, d.index, d.handle, d.room, int(d.public),
                    _subjects((d.handle, *d.about)), d.name.text or "", d.mime, d.size, d.digest, d.kind, seen,
                    int(d.read), int(d.stored), d.sensitivity, search_text(d.name.text or "", seen or ""), e.seq,
                    None, None), strict=True)))
            elif name == c.EXPIRED.name and d.files:
                sql.execute(update(t).where(t.c.id.in_(list(d.files)), t.c.expired_at.is_(None))
                            .values(expired_at=e.at, reason=d.reason, stored=0, touched=e.seq))
            elif name == c.LINKED.name:
                if d.removed:
                    sql.execute(delete(ln).where(ln.c.file == d.file, ln.c.item == d.item))
                else:
                    insert_ignore(sql, ln, {"file": d.file, "item": d.item, "by": d.by, "at": e.at})
                sql.execute(update(t).where(t.c.id == d.file).values(touched=e.seq))
            elif getattr(d, "pieces", ()):
                self._from_memory(sql, e, t, m, ln)

    @staticmethod
    def _from_memory(sql: Sql, e: Any, t: Table, m: Table, ln: Table) -> None:
        """Les pièces que la relecture désigne pour un élément : seulement des pièces que des messages ont portées
        (une clé inventée ne relie rien)."""
        d = e.data
        item = int(d.item) if e.type.name in _TOUCH_NAMES else e.seq
        wanted = sorted({f for f in d.pieces if valid_id(f)})
        if not wanted:
            return
        real = {str(f) for (f,) in sql.execute(select(m.c.file).where(m.c.file.in_(wanted)).distinct())}
        rows = [{"file": f, "item": item, "by": c.BY_REREAD, "at": e.at} for f in wanted if f in real]
        if rows:
            insert_ignore(sql, ln, rows)
            sql.execute(update(t).where(t.c.id.in_([r["file"] for r in rows])).values(touched=e.seq))

    def forget(self, sql: Sql, subject: str, sfx: str) -> None:
        t, m, ln = files_table(sfx), carried_table(sfx), links_table(sfx)
        sql.execute(delete(t).where((t.c.handle == subject) | (func.instr(t.c.subjects, f"|{subject}|") > 0)))
        sql.execute(delete(m).where(m.c.handle == subject))
        sql.execute(delete(ln).where(ln.c.file.not_in(select(t.c.id))))


_TOUCH_NAMES = frozenset(t.name for t in _TOUCHES)


# ── Lire les lignes ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FileRow:
    """Une pièce lue : ce qu'on en sait."""

    id: str
    seq: int
    at: int
    message: int
    idx: int
    handle: str
    room: str | None
    public: bool
    name: str
    mime: str
    size: int
    digest: str
    kind: str
    seen: str | None
    readable: bool
    stored: bool
    sensitivity: int
    expired_at: int | None
    reason: str | None

    @property
    def gone(self) -> bool:
        """Ses octets ne sont plus là (retirée)."""
        return self.expired_at is not None or not self.stored

    @property
    def ref(self) -> str:
        """Son repère court, pour ses outils (jamais dit en conversation)."""
        return self.id[:8]


_ROW_COLUMNS = tuple(n for n in _FILE_COLUMNS if n not in ("subjects", "folded", "touched"))


def _row(r: Sequence[Any]) -> FileRow:
    got = dict(zip(_ROW_COLUMNS, r, strict=True))
    got["public"], got["readable"], got["stored"] = bool(got["public"]), bool(got["readable"]), bool(got["stored"])
    return FileRow(**got)


def _select(t: Table) -> Any:
    return select(*(t.c[n] for n in _ROW_COLUMNS))


def rows(store: Any, files: Sequence[str]) -> list[FileRow]:
    """Ces pièces, dans l'ordre demandé (celles qu'on ne connaît pas, ou plus, n'y sont pas)."""
    wanted = list(dict.fromkeys(f for f in files if isinstance(f, str) and valid_id(f)))
    if store is None or not wanted:
        return []
    t = files_table()
    found = {r[0]: _row(r) for r in store.query_mind(_select(t).where(t.c.id.in_(wanted)))}
    return [found[f] for f in wanted if f in found]


def row(store: Any, file: str) -> FileRow | None:
    got = rows(store, [file])
    return got[0] if got else None


def by_prefix(store: Any, prefix: str, limit: int = 20) -> list[FileRow]:
    """Les pièces dont la clé commence ainsi (un repère), de la plus récente à la plus ancienne."""
    if store is None or not prefix or not all(ch in "0123456789abcdef" for ch in prefix):
        return []
    t = files_table()
    return [_row(r) for r in store.query_mind(_select(t).where(t.c.id.like(f"{prefix}%"))
                                              .order_by(t.c.at.desc(), t.c.id).limit(limit))]


def by_seqs(store: Any, seqs: Sequence[int]) -> dict[int, FileRow]:
    """Les pièces par le ``seq`` de leur lecture (la clé de leurs vecteurs)."""
    if store is None or not seqs:
        return {}
    t = files_table()
    return {int(r[1]): _row(r) for r in store.query_mind(_select(t).where(t.c.seq.in_(list(seqs))))}


def recent(store: Any, *, handles: Sequence[str] | None = None, kind: str = "", words: Sequence[str] = (),
           limit: int = 200, before_at: int | None = None) -> list[FileRow]:
    """Les pièces, de la plus récente à la plus ancienne : de ces adresses, de cette sorte, dont le nom ou ce qu'elle
    y a lu contient chacun de ces mots (repliés)."""
    if store is None:
        return []
    t = files_table()
    query = _select(t)
    if handles is not None:
        query = query.where(t.c.handle.in_(list(handles)))
    if kind:
        query = query.where(t.c.kind == kind)
    for w in words:
        query = query.where(func.instr(t.c.folded, fold(w)) > 0)
    if before_at is not None:
        query = query.where(t.c.at < before_at)
    return [_row(r) for r in store.query_mind(query.order_by(t.c.at.desc(), t.c.id).limit(limit))]


def count(store: Any, *, handles: Sequence[str] | None = None, kind: str = "", words: Sequence[str] = ()) -> int:
    if store is None:
        return 0
    t = files_table()
    query = select(func.count()).select_from(t)
    if handles is not None:
        query = query.where(t.c.handle.in_(list(handles)))
    if kind:
        query = query.where(t.c.kind == kind)
    for w in words:
        query = query.where(func.instr(t.c.folded, fold(w)) > 0)
    return int(store.query_mind(query)[0][0])


def carriers(store: Any, file: str) -> list[tuple[int, int, str | None]]:
    """Les messages qui portent cette pièce : (``seq``, instant, salon), du plus ancien au plus récent."""
    if store is None:
        return []
    m = carried_table()
    return [(int(s), int(a), r) for s, a, r in store.query_mind(
        select(m.c.message, m.c.at, m.c.room).where(m.c.file == file).order_by(m.c.message))]


def links(store: Any, files: Sequence[str]) -> dict[str, list[tuple[int, str]]]:
    """Pièce → ses liens (élément, qui l'a relié), du plus ancien au plus récent."""
    if store is None or not files:
        return {}
    ln = links_table()
    out: dict[str, list[tuple[int, str]]] = {}
    for f, item, by in store.query_mind(select(ln.c.file, ln.c.item, ln.c.by).where(ln.c.file.in_(list(files)))
                                        .order_by(ln.c.at, ln.c.item)):
        out.setdefault(str(f), []).append((int(item), str(by)))
    return out


def usage(store: Any) -> dict[str, tuple[int, int]]:
    """Adresse → (pièces dont les octets sont gardés, leur taille) : la place que chacun occupe."""
    if store is None:
        return {}
    t = files_table()
    return {str(h): (int(n), int(size or 0)) for h, n, size in store.query_mind(
        select(t.c.handle, func.count(), func.sum(t.c.size)).where(t.c.stored == 1)
        .group_by(t.c.handle).order_by(t.c.handle))}


def linked_knowledge(store: Any, items: Sequence[int]) -> dict[int, Any]:
    """Ces éléments de ce qu'elle sait, par la porte de la mémoire (``contracts.memory``), encore actifs."""
    if store is None or not items:
        return {}
    v = memory_c.KNOWLEDGE
    found = knowns(store.query_mind(memory_c.select_known().where(v.c.id.in_(sorted(set(items))),
                                                                  v.c.status == memory_c.ACTIVE_STATUS)),
                   memory_c.KNOWN_COLUMNS)
    return {k.id: k for k in found}


def subjects_of(store: Any, files: Sequence[str]) -> dict[str, tuple[str, ...]]:
    """Les sujets de ces pièces (leur adresse, la personne derrière) : l'oubli de l'un efface leur vecteur."""
    if store is None or not files:
        return {}
    t = files_table()
    return {str(f): tuple(k for k in str(raw).split("|") if k)
            for f, raw in store.query_mind(select(t.c.id, t.c.subjects).where(t.c.id.in_(list(files))))}
