"""L'index des vecteurs : une table de ``views.db`` (demi-précision), une
matrice en mémoire pour chercher (produit scalaire sur vecteurs normalisés).

Les écritures passent par l'écrivain du magasin ; la matrice suit. Un index
jeté se reconstruit en replongeant les textes : même modèle, mêmes octets.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Sequence
from typing import Any

import numpy as np

from mika.ports.vectors import Embedder, VectorItem


class SqliteVectorIndex:
    def __init__(self, store: Any, embedder: Embedder, *, table: str = "memory_vectors") -> None:
        self.store = store
        self.embedder = embedder
        self.table = table
        self._keys = np.zeros(0, dtype=np.int64)
        self._kinds: list[str] = []
        self._persons: list[tuple[str, ...]] = []
        self._mat = np.zeros((0, 0), dtype=np.float32)
        self._pos: dict[int, int] = {}

    @property
    def model(self) -> str:
        return self.embedder.name

    async def open(self) -> None:
        table = self.table

        def create(sql: Any) -> None:
            sql.execute(f"CREATE TABLE IF NOT EXISTS {table}(key INTEGER NOT NULL, model TEXT NOT NULL, "
                        "kind TEXT NOT NULL, persons TEXT NOT NULL, vec BLOB NOT NULL, PRIMARY KEY(key, model))")

        await self.store.run_views(create)
        rows = self.store.query_views(f"SELECT key, kind, persons, vec FROM {table} WHERE model=? ORDER BY key",
                                      (self.model,))
        self._reset([(int(k), kind, tuple(json.loads(p)), np.frombuffer(v, dtype=np.float16).astype(np.float32))
                     for k, kind, p, v in rows])

    def _reset(self, rows: list[tuple[int, str, tuple[str, ...], np.ndarray]]) -> None:
        self._keys = np.array([r[0] for r in rows], dtype=np.int64)
        self._kinds = [r[1] for r in rows]
        self._persons = [r[2] for r in rows]
        self._mat = np.vstack([r[3] for r in rows]) if rows else np.zeros((0, 0), dtype=np.float32)
        self._pos = {int(k): i for i, k in enumerate(self._keys)}

    def indexed(self) -> set[int]:
        return set(self._pos)

    async def upsert(self, items: Sequence[VectorItem]) -> int:
        items = [i for i in items if i.text.strip()]
        if not items:
            return 0
        vecs = np.asarray(await self.embedder.embed([i.text for i in items]), dtype=np.float32)
        half = vecs.astype(np.float16)
        table, model = self.table, self.model
        rows = [(i.key, model, i.kind, json.dumps(sorted(i.persons), ensure_ascii=False), half[n].tobytes())
                for n, i in enumerate(items)]

        def write(sql: Any) -> None:
            sql.executemany(f"INSERT OR REPLACE INTO {table}(key, model, kind, persons, vec) VALUES(?,?,?,?,?)", rows)

        await self.store.run_views(write)
        current = [(int(k), self._kinds[p], self._persons[p], self._mat[p]) for k, p in self._pos.items()]
        fresh = {i.key: (i.key, i.kind, tuple(sorted(i.persons)), half[n].astype(np.float32))
                 for n, i in enumerate(items)}
        merged = [r for r in current if r[0] not in fresh] + list(fresh.values())
        self._reset(sorted(merged, key=lambda r: r[0]))
        return len(items)

    async def search(self, query: str, k: int, *, kinds: Collection[str] | None = None,
                     keys: Collection[int] | None = None) -> list[tuple[int, float]]:
        if not len(self._keys) or not query.strip() or k <= 0:
            return []
        q = np.asarray((await self.embedder.embed([query]))[0], dtype=np.float32)
        sims = self._mat @ q
        mask = np.ones(len(self._keys), dtype=bool)
        if kinds is not None:
            mask &= np.array([kind in kinds for kind in self._kinds])
        if keys is not None:
            allowed = set(keys)
            mask &= np.array([int(key) in allowed for key in self._keys])
        idx = np.flatnonzero(mask)
        if not len(idx):
            return []
        best = idx[np.argsort(-sims[idx], kind="stable")[:k]]
        return [(int(self._keys[i]), float(sims[i])) for i in best]

    async def forget(self, subject: str) -> int:
        """Retire les vecteurs de tout ce qui concerne ``subject``, pour tous les
        modèles (la table peut en garder plusieurs) ; rend combien de clés."""
        table, like = self.table, f'%"{subject}"%'

        def delete(sql: Any) -> int:
            keys = {int(r[0]) for r in sql.query(f"SELECT key FROM {table} WHERE persons LIKE ?", (like,))}
            sql.execute(f"DELETE FROM {table} WHERE persons LIKE ?", (like,))
            return len(keys)

        removed = int(await self.store.run_views(delete) or 0)
        doomed = {int(k) for k, persons in zip(self._keys, self._persons, strict=True) if subject in persons}
        self._drop(doomed)
        return removed

    async def remove(self, keys: Collection[int]) -> int:
        """Retire ces clés (l'élément a disparu de la mémoire : oublié, effacé)."""
        doomed = {int(k) for k in keys}
        if not doomed:
            return 0
        table, rows = self.table, [(k,) for k in sorted(doomed)]

        def delete(sql: Any) -> None:
            sql.executemany(f"DELETE FROM {table} WHERE key=?", rows)

        await self.store.run_views(delete)
        before = len(self._pos)
        self._drop(doomed)
        return before - len(self._pos)

    def _drop(self, doomed: set[int]) -> None:
        if doomed & set(self._pos):
            keep = [(int(k), self._kinds[p], self._persons[p], self._mat[p]) for k, p in self._pos.items()
                    if int(k) not in doomed]
            self._reset(sorted(keep, key=lambda r: r[0]))

    async def clear(self) -> None:
        table, model = self.table, self.model
        await self.store.run_views(lambda sql: sql.execute(f"DELETE FROM {table} WHERE model=?", (model,)))
        self._reset([])

    def digest(self) -> str:
        h = hashlib.blake2b(digest_size=16)
        for key in sorted(self._pos):
            h.update(str(key).encode())
            h.update(self._mat[self._pos[key]].astype(np.float16).tobytes())
        return h.hexdigest()
