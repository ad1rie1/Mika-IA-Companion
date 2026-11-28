"""L'index des vecteurs (``memory.index``).

**Indexer.** L'index des vecteurs est un cache : ce processus y ajoute ce
qui manque (éléments retenus, extraits d'échanges) et retire ce qui a
disparu (l'oubli efface des lignes).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Table, func, select

from mika.contracts import memory as c
from mika.contracts import runtime as rt
from mika.faculties.memory import tables as tb
from mika.faculties.memory.faculty import MEMORY, MemoryState
from mika.faculties.memory.tables import ITEM_COLUMNS, batches, keys_of
from mika.kernel.clock import MINUTE
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.ports.vectors import VectorItem

BATCH = 64
#: après un échec de l'indexation (un plongement absent), pas de nouvel essai avant
INDEX_RETRY_US = 5 * MINUTE


def _rows(store: Any, query: Any, columns: tuple[str, ...]) -> list[dict[str, Any]]:
    return [dict(zip(columns, r, strict=True)) for r in store.query_mind(query)]


_CHUNK_COLUMNS = ("id", "person", "user_text", "reply_text", "room")


def _item_vector(r: dict[str, Any]) -> VectorItem:
    # qui l'a dit, tous témoins compris (ADR 0080) : ce qu'une personne lui a appris se retrouve avec elle
    people = {*keys_of(r["about"]), *keys_of(r["told_by"]), *keys_of(r.get("informants"))}
    if r.get("holder"):
        people.add(r["holder"])
    return VectorItem(int(r["id"]), r["kind"], r["text"], tuple(sorted(people)))


def _chunk_vector(r: dict[str, Any]) -> VectorItem:
    """Un échange : en privé (``chunk``), retrouvé avec la personne ; dans un salon (``room_chunk``), dans ce salon
    seulement."""
    kind = c.CHUNK if r["room"] is None else c.ROOM_CHUNK
    return VectorItem(int(r["id"]), kind, f"{r['user_text']}\n{r['reply_text']}", (r["person"],))


def _by_ids(store: Any, table: Table, columns: tuple[str, ...], ids: Sequence[int]) -> list[dict[str, Any]]:
    """Ces lignes, par paquets (jamais une liste ``IN`` sans borne)."""
    out: list[dict[str, Any]] = []
    for part in batches(ids):
        out += _rows(store, select(*(table.c[n] for n in columns)).where(table.c.id.in_(part)).order_by(table.c.id),
                     columns)
    return out


def forgets_of(store: Any) -> int:
    """Combien de fois la mémoire a oublié quelqu'un (``memory_forgets``)."""
    ft = tb.forgets()
    rows = store.query_mind(select(ft.c.n).order_by(ft.c.id).limit(1))
    return int(rows[0][0]) if rows else 0


@MEMORY.process("memory.index", wake_on=[*c.ALL, rt.UTTERANCE],
                catch_up=CatchUp.ONCE, max_quantum_s=600)
class Index:
    """L'index des vecteurs (un cache) suit la mémoire : à chaque passage, ce qui est né depuis le précédent
    (``id > ?``, textes compris) ; au premier passage, et après un oubli (``memory_forgets`` a bougé), un
    rapprochement par les seuls identifiants — ce qui a disparu part, ce qui manque s'ajoute. Relire toute la
    mémoire, textes compris, à chaque énoncé coûtait 80 ms à cinquante mille éléments, sur la boucle (ADR 0059)."""

    def __init__(self) -> None:
        self.done: tuple[int, int, int] | None = None
        self.retry_at = 0
        #: les plus grands identifiants déjà confiés à l'index (éléments, échanges)
        self.upto = (0, 0)
        #: le compte d'oublis vu au dernier rapprochement
        self.forgets = 0
        self.revision = 0

    def next_due(self, state: MemoryState, frame: Frame, last_run: int | None) -> int | None:
        if (state.items, state.chunks, state.index_revision) == self.done:
            return None
        return max(frame.now, self.retry_at)

    async def run(self, ctx: Any) -> None:
        state: MemoryState = ctx.state
        key = (state.items, state.chunks, state.index_revision)
        vectors, store = ctx.ports.get("vectors"), ctx.ports.get("store")
        if vectors is None or store is None:
            self.done = key
            return
        # si le plongement lève (modèle absent), pas de nouvel essai avant un moment : aucune rafale
        self.retry_at = ctx.frame.now + INDEX_RETRY_US
        forgets = forgets_of(store)
        first = self.done is None
        if first or forgets != self.forgets:
            todo, upto = await self._reconcile(vectors, store)
        else:
            todo, upto = self._fresh(store)
        ch = tb.changes()
        if first:
            self.revision = int(store.query_mind(select(func.coalesce(func.max(ch.c.seq), 0)))[0][0])
        changed = store.query_mind(select(ch.c.item, ch.c.seq).where(ch.c.seq > self.revision)
                                   .order_by(ch.c.seq, ch.c.item))
        if changed:
            rows = _by_ids(store, tb.items(), ITEM_COLUMNS, [int(i) for i, _ in changed])
            active = [r for r in rows if r["status"] in (c.ACTIVE_STATUS, c.PENDING_STATUS)]
            valid = {int(r["id"]) for r in active}
            await vectors.remove([int(i) for i, _ in changed if int(i) not in valid])
            todo = list({v.key: v for v in [*todo, *map(_item_vector, active)]}.values())
        for i in range(0, len(todo), BATCH):
            await vectors.upsert(todo[i:i + BATCH])
        self.upto, self.forgets, self.done = upto, forgets, key
        self.revision = max((int(seq) for _, seq in changed), default=self.revision)
        self.retry_at = 0

    def _fresh(self, store: Any) -> tuple[list[VectorItem], tuple[int, int]]:
        """Ce qui est né depuis le dernier passage."""
        t, ch = tb.items(), c.chunks_table()
        items = _rows(store, select(*(t.c[n] for n in ITEM_COLUMNS)).where(t.c.id > self.upto[0]).order_by(t.c.id),
                      ITEM_COLUMNS)
        chunks = _rows(store, select(*(ch.c[n] for n in _CHUNK_COLUMNS)).where(ch.c.id > self.upto[1])
                       .order_by(ch.c.id), _CHUNK_COLUMNS)
        upto = (max([self.upto[0], *(int(r["id"]) for r in items)]),
                max([self.upto[1], *(int(r["id"]) for r in chunks)]))
        return [*map(_item_vector, (r for r in items if r["status"] in (c.ACTIVE_STATUS, c.PENDING_STATUS))),
                *map(_chunk_vector, chunks)], upto

    @staticmethod
    async def _reconcile(vectors: Any, store: Any) -> tuple[list[VectorItem], tuple[int, int]]:
        """Toute la mémoire, par ses identifiants : l'oubli efface des lignes, leurs vecteurs partent aussi (l'index
        n'est qu'un cache) ; ce qui manque (un index neuf, jeté) s'ajoute."""
        indexed = vectors.indexed()
        t, ch = tb.items(), c.chunks_table()
        items = {int(r[0]) for r in store.query_mind(select(t.c.id).where(t.c.status.in_((c.ACTIVE_STATUS, c.PENDING_STATUS))))}
        chunks = {int(r[0]) for r in store.query_mind(select(ch.c.id))}
        gone = indexed - items - chunks
        if gone:
            await vectors.remove(sorted(gone))
        todo = [*map(_item_vector, _by_ids(store, t, ITEM_COLUMNS, sorted(items - indexed))),
                *map(_chunk_vector, _by_ids(store, ch, _CHUNK_COLUMNS, sorted(chunks - indexed)))]
        return todo, (max(items, default=0), max(chunks, default=0))
