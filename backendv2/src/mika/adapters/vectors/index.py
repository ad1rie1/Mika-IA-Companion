"""L'index des vecteurs : une table de ``views.db`` (demi-précision), une
matrice en mémoire pour chercher (produit scalaire sur vecteurs normalisés).

Les écritures passent par l'écrivain du magasin ; la matrice suit. Un index
jeté se reconstruit en replongeant les textes : même modèle, mêmes octets.

**Tenir des années** (ADR 0059). La matrice est réservée d'avance et double
quand elle est pleine : un ajout coûte ce qu'il ajoute, pas toute la matrice.
Les filtres d'une recherche sont des masques numpy — la sorte (un code par
sorte), les clés (``np.isin``), les personnes (un index inverse personne →
positions) : rien ne parcourt tous les vecteurs en Python. Les ex æquo se
départagent par la clé, quel que soit l'ordre dans lequel les vecteurs sont
arrivés : la même mémoire répond la même chose, avant et après un redémarrage.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Sequence
from typing import Any

import numpy as np

from mika.ports.vectors import Embedder, VectorItem

#: la première réservation de la matrice (en lignes) ; elle double ensuite à la demande
_MIN_CAPACITY = 64


class SqliteVectorIndex:
    def __init__(self, store: Any, embedder: Embedder, *, table: str = "memory_vectors") -> None:
        self.store = store
        self.embedder = embedder
        self.table = table
        self._reset([])

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

    # ── la matrice et ses index ──
    def _reset(self, rows: list[tuple[int, str, tuple[str, ...], np.ndarray]]) -> None:
        """Repart de ces lignes (dans cet ordre) : la matrice, les clés, les sortes, les personnes."""
        n = len(rows)
        dims = int(rows[0][3].shape[0]) if rows else 0
        cap = max(_MIN_CAPACITY, n)
        self._n = n
        self._kind_code: dict[str, int] = {}
        self._kind_names: list[str] = []
        self._mat = np.zeros((cap if dims else 0, dims), dtype=np.float32)
        self._keys = np.zeros(cap, dtype=np.int64)
        self._kinds = np.zeros(cap, dtype=np.int32)
        if rows:
            self._mat[:n] = np.vstack([r[3] for r in rows])
            self._keys[:n] = [r[0] for r in rows]
            self._kinds[:n] = [self._code(r[1]) for r in rows]
        self._persons: list[tuple[str, ...]] = [r[2] for r in rows]
        self._by_person: dict[str, list[int]] = {}
        #: les positions d'une personne en tableau, gardées jusqu'au prochain changement de ses lignes
        self._person_rows: dict[str, np.ndarray] = {}
        for at, persons in enumerate(self._persons):
            for p in persons:
                self._by_person.setdefault(p, []).append(at)
        self._pos: dict[int, int] = {int(r[0]): at for at, r in enumerate(rows)}

    def _code(self, kind: str) -> int:
        code = self._kind_code.get(kind)
        if code is None:
            code = self._kind_code[kind] = len(self._kind_names)
            self._kind_names.append(kind)
        return code

    def _reserve(self, rows: int, dims: int) -> None:
        """De la place pour ``rows`` lignes de plus : la matrice grandit de moitié quand elle est pleine (jamais une
        copie par ajout ; une croissance par moitié plutôt que par doublement : au plus un tiers de lignes
        réservées pour rien, la machine a peu de mémoire)."""
        if self._mat.shape[1] != dims:
            if self._n:
                raise ValueError(f"dimension {dims} ≠ {self._mat.shape[1]} : un autre modèle")
            self._mat = np.zeros((self._keys.shape[0], dims), dtype=np.float32)
        need = self._n + rows
        cap = self._keys.shape[0]
        if need <= cap and self._mat.shape[0] >= need:
            return
        new = max(_MIN_CAPACITY, cap + cap // 2, need)
        mat = np.zeros((new, dims), dtype=np.float32)
        mat[: self._n] = self._mat[: self._n]
        keys = np.zeros(new, dtype=np.int64)
        keys[: self._n] = self._keys[: self._n]
        kinds = np.zeros(new, dtype=np.int32)
        kinds[: self._n] = self._kinds[: self._n]
        self._mat, self._keys, self._kinds = mat, keys, kinds

    def _append(self, key: int, kind: str, persons: tuple[str, ...], vec: np.ndarray) -> None:
        """Ajoute une ligne, ou remplace celle de cette clé (à sa place)."""
        at = self._pos.get(key)
        if at is None:
            self._reserve(1, int(vec.shape[0]))
            at = self._n
            self._n += 1
            self._pos[key] = at
            self._keys[at] = key
            self._persons.append(())
        old = self._persons[at]
        for p in old:
            self._by_person[p].remove(at)
            self._person_rows.pop(p, None)
            if not self._by_person[p]:
                del self._by_person[p]
        self._mat[at] = vec
        self._kinds[at] = self._code(kind)
        self._persons[at] = persons
        for p in persons:
            self._by_person.setdefault(p, []).append(at)
            self._person_rows.pop(p, None)

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
        for n, i in enumerate(items):
            self._append(int(i.key), i.kind, tuple(sorted(i.persons)), half[n].astype(np.float32))
        return len(items)

    async def search(self, query: str, k: int, *, kinds: Collection[str] | None = None,
                     keys: Collection[int] | None = None,
                     persons: Collection[str] | None = None) -> list[tuple[int, float]]:
        if not self._n or not query.strip() or k <= 0:
            return []
        q = np.asarray((await self.embedder.embed([query]))[0], dtype=np.float32)
        # après le plongement (une attente) : la matrice a pu grandir ou se recomposer entre-temps
        n = self._n
        mask = self._mask(kinds, keys, persons)
        idx = np.arange(n) if mask is None else np.flatnonzero(mask)
        if not len(idx):
            return []
        # un filtre étroit (une inconnue) : seulement ses lignes ; large : tout, sans copier la matrice
        sims = self._mat[idx] @ q if 8 * len(idx) < n else (self._mat[:n] @ q)[idx]
        if len(idx) > k:
            # les k meilleures, ex æquo du bord compris : le départage par clé reste exact
            edge = np.partition(sims, len(sims) - k)[len(sims) - k]
            near = np.flatnonzero(sims >= edge)
            idx, sims = idx[near], sims[near]
        order = np.lexsort((self._keys[idx], -sims))[:k]
        return [(int(self._keys[idx[i]]), float(sims[i])) for i in order]

    def _mask(self, kinds: Collection[str] | None, keys: Collection[int] | None,
              persons: Collection[str] | None) -> np.ndarray | None:
        """Les vecteurs qui passent les filtres (``None`` : tous)."""
        n = self._n
        mask: np.ndarray | None = None
        if kinds is not None:
            codes = [self._kind_code[kd] for kd in kinds if kd in self._kind_code]
            mask = np.isin(self._kinds[:n], np.asarray(codes, dtype=np.int32))
        if keys is not None:
            wanted = np.fromiter((int(x) for x in keys), dtype=np.int64)
            got = np.isin(self._keys[:n], wanted)
            mask = got if mask is None else mask & got
        if persons is not None:
            got = np.zeros(n, dtype=bool)
            for p in persons:
                rows = self._person_rows.get(p)
                if rows is None and p in self._by_person:
                    rows = self._person_rows[p] = np.asarray(self._by_person[p], dtype=np.int64)
                if rows is not None:
                    got[rows] = True
            mask = got if mask is None else mask & got
        return mask

    async def forget(self, subject: str) -> int:
        """Retire les vecteurs de tout ce qui concerne ``subject``, pour tous les
        modèles (la table peut en garder plusieurs) ; rend combien de clés."""
        table, like = self.table, f'%"{subject}"%'

        def delete(sql: Any) -> int:
            keys = {int(r[0]) for r in sql.query(f"SELECT key FROM {table} WHERE persons LIKE ?", (like,))}
            sql.execute(f"DELETE FROM {table} WHERE persons LIKE ?", (like,))
            return len(keys)

        removed = int(await self.store.run_views(delete) or 0)
        self._drop({int(self._keys[at]) for at in self._by_person.get(subject, ())})
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
        """Retire ces clés de la matrice (rare : l'oubli) — elle se recompose, dans l'ordre des clés."""
        if doomed & set(self._pos):
            names = self._kind_names
            keep = [(key, names[int(self._kinds[at])], self._persons[at], self._mat[at].copy())
                    for key, at in sorted(self._pos.items()) if key not in doomed]
            self._reset(keep)

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
