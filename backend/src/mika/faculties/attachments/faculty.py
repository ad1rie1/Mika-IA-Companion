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

Leurs tables, leur projecteur et leurs lecteurs sont dans ``tables.py`` ; ce fichier-ci tient les réglages, l'état,
les réducteurs, l'enregistrement du projecteur, la lecture de près, l'index des vecteurs et la rétention.

Les pièces ont leur propre index de vecteurs (``attachment_vectors``) : un texte par pièce — son nom, ce qu'elle y a
lu, ce qu'elle sait qui va avec. Une pièce gardée le reste (``keep_days`` à 0 : toujours), dans une place bornée par
personne (``per_person_mb``) : au-delà, les plus anciennes sont retirées — leurs octets s'effacent, ce qu'elle en
avait lu reste. Un opérateur peut en retirer une à l'unité depuis la console (``attachments.retirer``,
``inspect.py``, ADR 0205) : le même ``attachments.expired``, sa raison ``operator``. Oublier une personne efface ses
lignes, ses contenus, ses octets et ses vecteurs.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from mika.contracts import attachments as c
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.faculties.attachments.tables import (
    MEMORY_LINKS,
    FileRow,
    ReceivedFiles,
    by_seqs,
    files_table,
    linked_knowledge,
    links,
    subjects_of,
)
from mika.kernel.clock import DAY, MINUTE
from mika.kernel.codec import digest
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp, Faculty, Tier
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.ports.preprocess import Upload
from mika.ports.shares import MAX_SHARE_BYTES, valid_id
from mika.ports.vectors import VectorItem
from mika.vocab.privacy import Sensitivity

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
        help="Quand les pièces gardées de quelqu'un (tous ses moyens de communication) dépassent cette place, les plus anciennes "
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
# leurs tables, leur projecteur (``ReceivedFiles``) et leurs lecteurs sont dans ``tables.py`` ; la faculté
# l'enregistre ici

ATTACHMENTS.projector(c.TABLE, version=1, tier=Tier.T0,
                      types=[rt.PERCEPTION_RECEIVED, *c.ALL, *MEMORY_LINKS])(ReceivedFiles)


def waiting(state: AttachmentsState | None, file: str, handle: str | None = None) -> Pending | None:
    """Une pièce gardée au bord mais pas encore lue de près (ADR 0312) : ses octets sont déjà là, et la personne qui
    l'a envoyée la reprend sans attendre sa lecture. ``handle`` : seulement si c'est cette adresse qui l'a envoyée."""
    p = state.pending.get(file) if state is not None else None
    return p if p is not None and (handle is None or p.handle == handle) else None


def holder(state: AttachmentsState, file: str) -> str | None:
    """L'adresse qui garde cette pièce, ses octets là (``None`` : retirée, pas encore lue, ou inconnue) — ce qu'un
    opérateur peut retirer (ADR 0205)."""
    return next((handle for handle, files in state.kept.items()
                 if any(v.file == file and v.stored for v in files)), None)


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


@ATTACHMENTS.process("attachments.study", wake_on=[rt.PERCEPTION_RECEIVED, c.KEPT, c.EXPIRED],
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


@ATTACHMENTS.process("attachments.index", wake_on=[c.KEPT, c.LINKED, c.EXPIRED, *MEMORY_LINKS],
                     catch_up=CatchUp.ONCE, max_quantum_s=600)
class PieceIndexer:
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


@ATTACHMENTS.process("attachments.retention", wake_on=[c.KEPT, c.EXPIRED],
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
