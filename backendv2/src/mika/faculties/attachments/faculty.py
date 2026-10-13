"""``attachments`` : ce qu'on lui envoie dans une conversation, gardé, lu de près et relié à ce qu'elle sait
(ADR 0106).

Au bord, le message qui porte une pièce jointe la désigne (``AttachmentMeta.file``) : ses octets sont déjà dans le
port ``attachments`` (hors du journal, sous la clé de la pièce, avec l'adresse qui l'a envoyée pour sujet). La
tranche note la pièce **à lire** ; le processus ``attachments.study`` la lit de près en fond (une photo décrite en
détail, son texte visible et ce qu'elle a d'intime ; tout le texte d'un document ; la transcription d'un vocal), puis
journalise ``attachments.kept`` — son nom et ce qu'elle y a lu sont des contenus, effaçables. Une lecture qui échoue
pour un temps (un modèle injoignable) est redemandée, au plus ``STUDY_ATTEMPTS`` fois ; au-delà, la pièce est gardée
sans lecture (son nom seul).

Trois projections T0 :

- ``received_files`` : une ligne par pièce lue — ce que lisent ses outils, la console et le téléchargement ;
- ``received_messages`` : quels messages portent quelles pièces (la même photo renvoyée : deux messages) ;
- ``received_links`` : ses liens avec ce qu'elle sait. **Un lien n'est pas une source** : les sources d'un souvenir,
  d'une croyance, d'un moment restent des messages ; ses pièces (``pieces``, que la relecture désigne) sont en plus,
  et il peut y en avoir plusieurs, dans les deux sens. Elle en fait aussi elle-même (``attachments.linked``).

Les pièces ont leur propre index de vecteurs (``attachment_vectors``) : un texte par pièce — son nom, ce qu'elle y a
lu, ce qu'elle sait qui va avec. Une pièce gardée le reste (``keep_days`` à 0 : toujours), dans une place bornée par
personne (``per_person_mb``) : au-delà, les plus anciennes sont retirées — leurs octets s'effacent, ce qu'elle en
avait lu reste. Oublier une personne efface ses lignes, ses contenus, ses octets et ses vecteurs.
"""

from __future__ import annotations

import functools
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, Index, Table, delete, func, select, update

from mika.contracts import attachments as c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.kernel.clock import DAY, MINUTE
from mika.kernel.codec import digest
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp, Faculty, Tier
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.ports.preprocess import Upload
from mika.ports.shares import MAX_SHARE_BYTES, valid_id
from mika.ports.sql import HANDLE_MAX, Key, LongText, insert_ignore, projection_table
from mika.ports.store import Sql
from mika.ports.vectors import VectorItem
from mika.vocab.knowledge import knowns
from mika.vocab.privacy import Sensitivity
from mika.vocab.words import fold

MIB = 1024 * 1024
PORT = c.PORT
#: une lecture qui échoue pour un temps est redemandée au plus tant de fois, de plus en plus tard
STUDY_ATTEMPTS = 3
STUDY_RETRY_US = 5 * MINUTE
#: la sorte des vecteurs des pièces (leur index est à part)
VECTOR_KIND = "piece"
#: ce que le texte d'une pièce apporte à son vecteur, au plus ; et ce qu'elle sait qui va avec
VECTOR_SEEN_CHARS = 1500
VECTOR_LINKED, VECTOR_LINKED_CHARS = 5, 300
#: une pièce dont les octets manquaient quand il a fallu la lire (oubliée, jamais écrite) : retirée d'emblée
MISSING = "missing"
#: les événements de la mémoire qui désignent leurs pièces (``pieces``) : l'élément est l'événement lui-même, ou
#: celui qu'il renforce
_CREATES = (memory_c.REMEMBERED, memory_c.BELIEVED, memory_c.EVENT_NOTED)
_TOUCHES = (memory_c.REINFORCED, memory_c.ATTESTED)
MEMORY_LINKS = (*_CREATES, *_TOUCHES)


class AttachmentsParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    look_closely: Annotated[bool, Knob(
        label="Regarder de près les images reçues", group="Lire",
        help="Juste après un message, chaque photo qu'on lui envoie est décrite en détail par le modèle qui voit "
             "(« décrire une image »), son texte visible recopié, et ce qu'elle a d'intime jugé : un appel de plus "
             "par image, en fond. Décoché : l'image est gardée sans être relue (la courte description du moment "
             "reste dans le message).")] = True
    text_max_chars: Annotated[int, Knob(
        label="Texte gardé d'une pièce (caractères)", group="Lire", lo=1_000, hi=500_000,
        help="Ce qu'elle garde, au plus, du texte d'un document (ou d'une description, d'une transcription) : "
             "c'est ce qu'elle relit quand elle rouvre la pièce, page par page.")] = 60_000
    keep_days: Annotated[int, Knob(
        label="Garder une pièce reçue (jours)", group="Garder", lo=0, hi=3650,
        help="Au-delà, les octets d'une pièce sont effacés ; ce qu'elle en avait lu reste, et ses liens. 0 : "
             "toujours (seule la place par personne la limite).")] = 0
    per_person_mb: Annotated[int, Knob(
        label="Place par personne (Mio)", group="Garder", lo=10, hi=100_000,
        help="Quand les pièces gardées de quelqu'un (toutes ses adresses) dépassent cette place, les plus anciennes "
             "sont retirées. La console montre ce que chacun occupe.")] = 2048


def params(p: AttachmentsParams | None) -> AttachmentsParams:
    return p if p is not None else AttachmentsParams()


def params_of(frame: Frame) -> AttachmentsParams:
    return params(frame.env.params_of(c.OWNER, frame.root))


@dataclass(frozen=True, slots=True)
class Pending:
    """Une pièce reçue, pas encore lue de près."""

    file: str
    message: int
    index: int
    at: int
    handle: str
    room: str | None
    public: bool
    name: str
    mime: str
    kind: str


@dataclass(frozen=True, slots=True)
class AttachmentsState:
    #: clé de la pièce → ce qu'il faut pour la lire
    pending: FrozenDict[str, Pending] = field(default_factory=FrozenDict)
    #: adresse → ses pièces gardées, de la plus ancienne à la plus récente
    kept: FrozenDict[str, tuple[c.KeptView, ...]] = field(default_factory=FrozenDict)
    #: change à chaque pièce lue ou lien posé : ce que l'index des vecteurs suit
    revision: int = 0


ATTACHMENTS = Faculty("attachments", state=AttachmentsState, init=lambda p: AttachmentsState(),
                      params=AttachmentsParams)
ATTACHMENTS.declare(*c.ALL)


def kind_of(mime: str) -> str:
    major = (mime or "").split("/", 1)[0].lower()
    return {"image": c.IMAGE, "audio": c.AUDIO}.get(major, c.FILE)


def _held(s: AttachmentsState, handle: str, file: str) -> bool:
    return file in s.pending or any(v.file == file for v in s.kept.get(handle, ()))


@ATTACHMENTS.reducer(rt.PERCEPTION_RECEIVED)
def _received(s: AttachmentsState, e: Any, cx: Any) -> AttachmentsState:
    """Un message qui porte des pièces gardées au bord : chacune, nouvelle, est à lire."""
    d = e.data
    pending = s.pending
    for i, a in enumerate(d.attachments, 1):
        if not a.file or not valid_id(a.file) or _held(s, d.handle, a.file) or a.file in pending:
            continue
        pending = pending.set(a.file, Pending(file=a.file, message=e.seq, index=i, at=e.at, handle=d.handle,
                                              room=d.room, public=d.public, name=a.name, mime=a.mime,
                                              kind=kind_of(a.mime) if a.mime else a.kind))
    return s if pending is s.pending else replace(s, pending=pending)


@ATTACHMENTS.reducer(c.KEPT)
def _kept(s: AttachmentsState, e: Any, cx: Any) -> AttachmentsState:
    d = e.data
    files = s.kept.get(d.handle, ())
    if any(v.file == d.file for v in files):
        return replace(s, pending=s.pending.delete(d.file))
    view = c.KeptView(file=d.file, at=e.at, size=d.size if d.stored else 0, stored=d.stored)
    return replace(s, pending=s.pending.delete(d.file), kept=s.kept.set(d.handle, (*files, view)),
                   revision=s.revision + 1)


@ATTACHMENTS.reducer(c.EXPIRED)
def _expired(s: AttachmentsState, e: Any, cx: Any) -> AttachmentsState:
    gone = set(e.data.files)
    pending = s.pending
    for f in gone:
        pending = pending.delete(f)
    files = s.kept.get(e.data.handle, ())
    left = tuple(v for v in files if v.file not in gone)
    kept = s.kept if len(left) == len(files) else (s.kept.set(e.data.handle, left) if left
                                                   else s.kept.delete(e.data.handle))
    return replace(s, pending=pending, kept=kept)


@ATTACHMENTS.reducer(c.LINKED, *MEMORY_LINKS)
def _linked(s: AttachmentsState, e: Any, cx: Any) -> AttachmentsState:
    """Un lien posé (par elle, ou par la relecture) : l'index des vecteurs de la pièce suit."""
    if e.type is not c.LINKED and not getattr(e.data, "pieces", ()):
        return s
    return replace(s, revision=s.revision + 1)


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
ATTACHMENTS.projector(c.TABLE, version=1, tier=Tier.T0,
                      types=[rt.PERCEPTION_RECEIVED, *c.ALL, *MEMORY_LINKS])(ReceivedFiles)


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


def files_of_messages(store: Any, seqs: Sequence[int]) -> dict[int, list[str]]:
    """Message → les pièces qu'il porte, dans l'ordre."""
    if store is None or not seqs:
        return {}
    m = carried_table()
    out: dict[int, list[str]] = {}
    for s, f in store.query_mind(select(m.c.message, m.c.file).where(m.c.message.in_(list(seqs)))
                                 .order_by(m.c.message, m.c.idx)):
        out.setdefault(int(s), []).append(str(f))
    return out


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
                                                                  v.c.status == "active")),
                   memory_c.KNOWN_COLUMNS)
    return {k.id: k for k in found}


# ── Lire de près ──────────────────────────────────────────────────────────


def oldest(s: AttachmentsState, ready: Mapping[str, int], now: int) -> Pending | None:
    """La plus ancienne pièce à lire dont l'heure est venue (``ready`` : quand redemander une lecture ratée)."""
    due = [p for p in s.pending.values() if ready.get(p.file, 0) <= now]
    return min(due, key=lambda p: (p.at, p.message, p.index)) if due else None


def level_of(p: Pending, sensitive: bool) -> int:
    """Personnelle en privé, anodine dans un salon public ; une confidence quand la lecture l'a jugée intime."""
    if sensitive:
        return int(Sensitivity.CONFIDENCE)
    return int(Sensitivity.ANODYNE) if p.public else int(Sensitivity.PERSONAL)


@ATTACHMENTS.process("attachments.study", wake_on=[rt.PERCEPTION_RECEIVED, c.KEPT, c.EXPIRED], lane="background",
                     catch_up=CatchUp.ONCE, max_quantum_s=600, deadline_s=600)
class Study:
    """Lire de près, une pièce à la fois, la plus ancienne d'abord ; un échec passager se redemande plus tard."""

    def __init__(self) -> None:
        self.failures: dict[str, int] = {}
        self.retry_at: dict[str, int] = {}

    def next_due(self, state: AttachmentsState, frame: Frame, last_run: int | None) -> int | None:
        if not state.pending:
            return None
        return max(frame.now, min(self.retry_at.get(f, 0) for f in state.pending))

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        p = oldest(ctx.state, self.retry_at, frame.now)
        if p is None:
            return
        port = ctx.ports.get(PORT)
        data = await port.read(p.file, MAX_SHARE_BYTES) if port is not None else None
        if data is None:  # rien à lire (oubliée, jamais écrite) : elle sort de la file, sans texte
            await ctx.emit(c.EXPIRED.draft(files=(p.file,), handle=p.handle, reason=MISSING,
                                           dedupe_key=f"piece-absente:{p.file}"))
            return
        prm = params_of(frame)
        reader = ctx.ports.get("preprocess")
        studied = None
        if reader is not None and (p.kind != c.IMAGE or prm.look_closely):
            studied = await reader.study(Upload(p.name, p.mime, data), max_chars=prm.text_max_chars)
            if not studied.read and studied.transient:
                tries = self.failures.get(p.file, 0) + 1
                if tries < STUDY_ATTEMPTS:
                    self.failures[p.file] = tries
                    self.retry_at[p.file] = frame.now + STUDY_RETRY_US * tries
                    return
        self.failures.pop(p.file, None)
        self.retry_at.pop(p.file, None)
        level = level_of(p, bool(studied and studied.read and studied.sensitive))
        text = studied.text if studied is not None and studied.read else ""
        person = frame.get(identity_c.PERSON(p.handle))
        await ctx.emit(c.KEPT.draft(
            file=p.file, message=p.message, index=p.index, handle=p.handle, room=p.room, public=p.public,
            name=Content.of(p.name, level=level), mime=p.mime, size=len(data),
            digest=hashlib.sha256(data).hexdigest(), kind=p.kind,
            seen=Content.of(text, level=level) if text else None, read=bool(text), stored=True, sensitivity=level,
            about=tuple(k for k in (person,) if k and k != p.handle), dedupe_key=f"piece:{p.file}"))


# ── L'index des vecteurs des pièces ───────────────────────────────────────


def vector_text(r: FileRow, linked: Sequence[str]) -> str:
    """Ce qu'on plonge d'une pièce : son nom, ce qu'elle y a lu (le début), ce qu'elle sait qui va avec."""
    parts = [r.name, (r.seen or "")[:VECTOR_SEEN_CHARS], *(t[:VECTOR_LINKED_CHARS] for t in linked[:VECTOR_LINKED])]
    return "\n".join(x for x in parts if x)


INDEX_RETRY_US = 10 * MINUTE


@ATTACHMENTS.process("attachments.index", wake_on=[c.KEPT, c.LINKED, c.EXPIRED, *MEMORY_LINKS], lane="background",
                     catch_up=CatchUp.ONCE, max_quantum_s=600)
class VectorIndex:
    """L'index des vecteurs des pièces (un cache) : à chaque passage, ce qui a bougé depuis le précédent (une pièce
    lue, un lien posé) ; au premier, un rapprochement par les clés — ce qui a disparu part, ce qui manque s'ajoute."""

    def __init__(self) -> None:
        self.done: int | None = None
        self.upto = 0
        self.retry_at = 0

    def next_due(self, state: AttachmentsState, frame: Frame, last_run: int | None) -> int | None:
        if state.revision == self.done:
            return None
        return max(frame.now, self.retry_at)

    async def run(self, ctx: Any) -> None:
        state: AttachmentsState = ctx.state
        vectors, store = ctx.ports.get(c.VECTORS), ctx.ports.get("store")
        if vectors is None or store is None:
            self.done = state.revision
            return
        self.retry_at = ctx.frame.now + INDEX_RETRY_US  # un plongement qui lève : pas de rafale
        t = files_table()
        top = int(store.query_mind(select(func.coalesce(func.max(t.c.touched), 0)))[0][0])
        if self.done is None:  # au premier passage : ce qui manque s'ajoute, ce qui a disparu part
            keys = {int(s) for (s,) in store.query_mind(select(t.c.seq))}
            indexed = vectors.indexed()
            gone = indexed - keys
            if gone:
                await vectors.remove(sorted(gone))
            wanted = sorted(keys - indexed)
        else:
            wanted = [int(s) for (s,) in store.query_mind(select(t.c.seq).where(t.c.touched > self.upto)
                                                          .order_by(t.c.seq))]
        found = by_seqs(store, wanted)
        linked = links(store, [r.id for r in found.values()])
        known = linked_knowledge(store, [i for ls in linked.values() for i, _by in ls])
        subjects = subjects_of(store, [r.id for r in found.values()])
        items = []
        for seq, r in sorted(found.items()):
            texts = [known[i].text for i, _by in linked.get(r.id, ()) if i in known and not known[i].secret]
            items.append(VectorItem(key=seq, kind=VECTOR_KIND, text=vector_text(r, texts),
                                    persons=subjects.get(r.id, (r.handle,))))
        for i in range(0, len(items), 64):
            await vectors.upsert(items[i:i + 64])
        self.upto, self.done, self.retry_at = int(top), state.revision, 0


def subjects_of(store: Any, files: Sequence[str]) -> dict[str, tuple[str, ...]]:
    """Les sujets de ces pièces (leur adresse, la personne derrière) : l'oubli de l'un efface leur vecteur."""
    if store is None or not files:
        return {}
    t = files_table()
    return {str(f): tuple(k for k in str(raw).split("|") if k)
            for f, raw in store.query_mind(select(t.c.id, t.c.subjects).where(t.c.id.in_(list(files))))}


# ── La place et la rétention ──────────────────────────────────────────────


def due_expiries(state: AttachmentsState, frame: Frame, p: AttachmentsParams) -> list[tuple[str, str, tuple[str, ...]]]:
    """(adresse, raison, pièces) à retirer maintenant : trop vieilles (si ``keep_days``), puis, par personne (toutes
    ses adresses ensemble), les plus anciennes au-delà de sa place."""
    out: list[tuple[str, str, tuple[str, ...]]] = []
    now = frame.now
    old: set[str] = set()
    if p.keep_days:
        for handle, files in state.kept.items():
            due = tuple(v.file for v in files if v.stored and v.at + p.keep_days * DAY <= now)
            if due:
                out.append((handle, c.RETENTION, due))
                old.update(due)
    budget = p.per_person_mb * MIB
    groups: dict[str, list[tuple[str, c.KeptView]]] = {}
    for handle, files in state.kept.items():
        person = frame.get(identity_c.PERSON(handle)) or handle
        groups.setdefault(person, []).extend((handle, v) for v in files if v.stored and v.file not in old)
    for _person, items in sorted(groups.items()):
        total = sum(v.size for _h, v in items)
        over: dict[str, list[str]] = {}
        for handle, v in sorted(items, key=lambda hv: (hv[1].at, hv[1].file)):
            if total <= budget:
                break
            over.setdefault(handle, []).append(v.file)
            total -= v.size
        out += [(h, c.BUDGET, tuple(fs)) for h, fs in sorted(over.items())]
    return out


@ATTACHMENTS.process("attachments.retention", wake_on=[c.KEPT, c.EXPIRED], lane="background",
                     catch_up=CatchUp.ONCE, max_quantum_s=600)
class Retention:
    """Retirer ce qui a fait son temps (``keep_days``) ou ce qui dépasse la place d'une personne : les octets
    s'effacent après le commit (l'effet de ``attachments.expired``)."""

    def next_due(self, state: AttachmentsState, frame: Frame, last_run: int | None) -> int | None:
        p = params_of(frame)
        if not state.kept:
            return None
        if due_expiries(state, frame, p):
            return frame.now
        if not p.keep_days:
            return None
        ats = [v.at for files in state.kept.values() for v in files if v.stored]
        return max(frame.now, min(ats) + p.keep_days * DAY) if ats else None

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        drafts = [c.EXPIRED.draft(files=files, handle=handle, reason=reason,
                                  dedupe_key=f"pieces-retirees:{handle}:{reason}:{digest(files)}")
                  for handle, reason, files in due_expiries(ctx.state, frame, params_of(frame))]
        if drafts:
            await ctx.emit(*drafts)


@ATTACHMENTS.effect(c.EXPIRED, deadline_s=60.0)
async def _erase(ev: Any, ports: Mapping[str, Any]) -> None:
    """Après le commit : les octets des pièces retirées s'effacent (idempotent, rejouable)."""
    store = ports.get(PORT)
    if store is not None and ev.data.files and ev.data.reason != MISSING:
        await store.delete(tuple(ev.data.files))


def file_id(handle: str, data: bytes) -> str:
    """La clé d'une pièce : la même photo renvoyée par la même adresse est la même pièce (une autre adresse en a
    une autre — oublier l'une n'efface pas la pièce de l'autre)."""
    return hashlib.blake2b(f"piece:{handle}:".encode() + hashlib.sha256(data).digest(), digest_size=16).hexdigest()


def decode_list(raw: Any) -> list[Any]:
    try:
        got = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return []
    return got if isinstance(got, list) else []
