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

import asyncio
import hashlib
import json
from collections.abc import Collection, Sequence
from typing import Any

import numpy as np
from sqlalchemy import BigInteger, Column, Table, delete, func, or_, select

from mika.ports.sql import Key, LongBlob, LongText, json_has, projection_table, upsert
from mika.ports.vectors import Embedder, VectorItem

#: la première réservation de la matrice (en lignes) ; elle double ensuite à la demande
_MIN_CAPACITY = 64
#: au plus tant de valeurs dans un filtre posé en SQL (la limite de paramètres de SQLite reste loin)
_SQL_FILTER_MAX = 900


def vectors_table(name: str) -> Table:
    """La table d'un index (hors des migrations : un index jeté se reconstruit en replongeant les textes)."""
    return projection_table(
        name,
        Column("key", BigInteger, primary_key=True, autoincrement=False),
        Column("model", Key(200), primary_key=True),
        Column("kind", LongText, nullable=False),
        Column("persons", LongText, nullable=False),
        Column("vec", LongBlob, nullable=False),
    )


async def _compute(fn, *args):
    """Même annulée, une lecture termine avant de rendre le verrou aux mutations."""
    task = asyncio.create_task(asyncio.to_thread(fn, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


class SqliteVectorIndex:
    def __init__(self, store: Any, embedder: Embedder, *, table: str = "memory_vectors",
                 max_resident_vectors: int = 50_000) -> None:
        self.store = store
        self.embedder = embedder
        self.table = table
        self._t = vectors_table(table)
        self.max_resident_vectors = max(1, max_resident_vectors)
        self._spilled = False
        self._lock = asyncio.Lock()
        self._reset([])

    @property
    def model(self) -> str:
        return self.embedder.name

    async def open(self) -> None:
        t = self._t
        await self.store.run_views(lambda sql: sql.create(t))
        count = self.store.query_views(select(func.count()).select_from(t).where(t.c.model == self.model))[0][0]
        if count > self.max_resident_vectors:
            self._reset([])
            self._spilled = True
            return
        rows = self.store.query_views(select(t.c.key, t.c.kind, t.c.persons, t.c.vec)
                                      .where(t.c.model == self.model).order_by(t.c.key))
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

    async def dump(self, limit: int | None = None) -> tuple[list[int], list[str], list[tuple[str, ...]], np.ndarray]:
        """Tout l'index de ce modèle, rangé par clé — (clés, sortes, personnes, matrice (n, d)) : de quoi en tirer une
        carte (``layout``). ``limit`` : seulement les ``limit`` clés les plus récentes (les plus grandes)."""
        t, model = self._t, self.model
        query = select(t.c.key, t.c.kind, t.c.persons, t.c.vec).where(t.c.model == model)
        if limit is not None:
            query = query.order_by(t.c.key.desc()).limit(max(0, limit))
        rows = sorted(await self.store.run_views(lambda sql: sql.query(query)), key=lambda r: int(r[0]))
        if not rows:
            return [], [], [], np.zeros((0, 0), dtype=np.float32)
        mat = np.vstack([np.frombuffer(blob, dtype=np.float16) for _, _, _, blob in rows]).astype(np.float32)
        return ([int(k) for k, _, _, _ in rows], [str(kind) for _, kind, _, _ in rows],
                [tuple(json.loads(p)) for _, _, p, _ in rows], mat)

    def indexed(self) -> set[int]:
        if self._spilled:
            t = self._t
            return {int(k) for (k,) in self.store.query_views(select(t.c.key).where(t.c.model == self.model))}
        return set(self._pos)

    async def upsert(self, items: Sequence[VectorItem]) -> int:
        items = [i for i in items if i.text.strip()]
        if not items:
            return 0
        vecs = np.asarray(await self.embedder.embed([i.text for i in items]), dtype=np.float32)
        half = vecs.astype(np.float16)
        t, model = self._t, self.model
        rows = [{"key": i.key, "model": model, "kind": i.kind, "persons": json.dumps(sorted(i.persons),
                 ensure_ascii=False), "vec": half[n].tobytes()} for n, i in enumerate(items)]

        def write(sql: Any) -> None:
            upsert(sql, t, rows, keys=["key", "model"])

        async with self._lock:
            await self.store.run_views(write)
            if self._spilled or self._n + len({i.key for i in items} - self._pos.keys()) > self.max_resident_vectors:
                self._reset([])
                self._spilled = True
            else:
                for n, i in enumerate(items):
                    self._append(int(i.key), i.kind, tuple(sorted(i.persons)), half[n].astype(np.float32))
        return len(items)

    async def search(self, query: str, k: int, *, kinds: Collection[str] | None = None,
                     keys: Collection[int] | None = None,
                     persons: Collection[str] | None = None) -> list[tuple[int, float]]:
        if (not self._n and not self._spilled) or not query.strip() or k <= 0:
            return []
        q = np.asarray((await self.embedder.embed_query([query]))[0], dtype=np.float32)
        async with self._lock:
            if self._spilled:
                return await self._search_disk(q, k, kinds, keys, persons)
            return await _compute(self._search, q, k, kinds, keys, persons)

    def _search(self, q: np.ndarray, k: int, kinds, keys, persons) -> list[tuple[int, float]]:
        # après le plongement (une attente) : la matrice a pu grandir ou se recomposer entre-temps
        n = self._n
        mask = self._mask(kinds, keys, persons)
        idx = np.arange(n) if mask is None else np.flatnonzero(mask)
        if not len(idx):
            return []
        # un filtre étroit (une inconnue) : seulement ses lignes ; large : tout, sans copier la matrice
        # Réduction identique quelle que soit la position de la ligne : BLAS peut changer
        # l'arrondi selon l'alignement après suppression et inverser des ex æquo.
        sims = (np.einsum("ij,j->i", self._mat[idx], q, dtype=np.float64).astype(np.float32)
                if 8 * len(idx) < n else
                np.einsum("ij,j->i", self._mat[:n], q, dtype=np.float64).astype(np.float32)[idx])
        if len(idx) > k:
            # les k meilleures, ex æquo du bord compris : le départage par clé reste exact
            edge = np.partition(sims, len(sims) - k)[len(sims) - k]
            near = np.flatnonzero(sims >= edge)
            idx, sims = idx[near], sims[near]
        order = np.lexsort((self._keys[idx], -sims))[:k]
        return [(int(self._keys[idx[i]]), float(sims[i])) for i in order]

    async def _search_disk(self, q: np.ndarray, k: int, kinds, keys, persons) -> list[tuple[int, float]]:
        """Au-delà du cache RAM : recherche exacte par blocs, sans charger toute la matrice.

        Le verrou protège la cohérence entre les blocs ; le calcul quitte la boucle d'événements.
        Le coût CPU reste linéaire, la mémoire de travail est bornée à 1024 vecteurs.
        """
        t = self._t
        where = [t.c.model == self.model]
        if kinds is not None:
            if not kinds:
                return []
            where.append(t.c.kind.in_(sorted(kinds)))
        wanted = set(keys) if keys is not None else None
        people = set(persons) if persons is not None else None
        if (wanted is not None and not wanted) or (people is not None and not people):
            return []
        # Les filtres structurés se posent en SQL avant de lire les vecteurs : chercher parmi trois clés ne lit
        # pas toute la mémoire (audit du 2026-10-08). Au-delà de ``_SQL_FILTER_MAX`` valeurs, le filtre reste en
        # Python (la limite de paramètres de SQLite) ; il est de toute façon réappliqué ci-dessous.
        if wanted is not None and len(wanted) <= _SQL_FILTER_MAX:
            where.append(t.c.key.in_(sorted(wanted)))
        if people is not None and len(people) <= _SQL_FILTER_MAX:
            where.append(or_(*(json_has(t.c.persons, p) for p in sorted(people))))
        best: list[tuple[int, float]] = []
        after = -1

        def score(rows):
            mat = np.asarray([np.frombuffer(blob, dtype=np.float16) for _, _, blob in rows], dtype=np.float32)
            return np.einsum("ij,j->i", mat, q, dtype=np.float64).astype(np.float32)

        while True:
            query = select(t.c.key, t.c.persons, t.c.vec).where(*where, t.c.key > after).order_by(t.c.key).limit(1024)
            # La connexion appartient au worker du magasin, pas au thread de la boucle asyncio.
            rows = await self.store.run_views(lambda sql, query=query: sql.query(query))
            if not rows:
                break
            after = int(rows[-1][0])
            eligible = [(key, who, blob) for key, who, blob in rows
                        if (wanted is None or key in wanted) and (people is None or people.intersection(json.loads(who)))]
            if eligible:
                scores = await _compute(score, eligible)
                best = sorted([*best, *((int(r[0]), float(s)) for r, s in zip(eligible, scores, strict=True))],
                              key=lambda hit: (-hit[1], hit[0]))[:k]
            else:
                await asyncio.sleep(0)
        return best

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
        t = self._t

        def erase(sql: Any) -> int:
            keys = {int(r[0]) for r in sql.query(select(t.c.key).where(json_has(t.c.persons, subject)))}
            if keys:
                sql.execute(delete(t).where(t.c.key.in_(sorted(keys))))
            return len(keys)

        async with self._lock:
            removed = int(await self.store.run_views(erase) or 0)
            self._drop({int(self._keys[at]) for at in self._by_person.get(subject, ())})
        return removed

    async def remove(self, keys: Collection[int]) -> int:
        """Retire ces clés (l'élément a disparu de la mémoire : oublié, effacé)."""
        doomed = {int(k) for k in keys}
        if not doomed:
            return 0
        t, ids = self._t, sorted(doomed)

        def erase(sql: Any) -> None:
            for i in range(0, len(ids), 512):
                sql.execute(delete(t).where(t.c.key.in_(ids[i:i + 512])))

        async with self._lock:
            before = len(self._pos.keys() & doomed)
            if self._spilled:
                before = sum(int(self.store.query_views(
                    select(func.count()).select_from(t).where(t.c.model == self.model, t.c.key.in_(ids[i:i + 512])))[0][0])
                    for i in range(0, len(ids), 512))
            await self.store.run_views(erase)
            self._drop(doomed)
            return before

    def _drop(self, doomed: set[int]) -> None:
        """Retire ces clés de la matrice (rare : l'oubli) — elle se recompose, dans l'ordre des clés."""
        for key in sorted(doomed):
            at = self._pos.pop(key, None)
            if at is None:
                continue
            last = self._n - 1
            for person in self._persons[at]:
                self._by_person[person].remove(at)
                self._person_rows.pop(person, None)
                if not self._by_person[person]:
                    del self._by_person[person]
            if at != last:
                moved = int(self._keys[last])
                self._mat[at], self._keys[at], self._kinds[at] = self._mat[last], moved, self._kinds[last]
                self._persons[at] = self._persons[last]
                self._pos[moved] = at
                for person in self._persons[last]:
                    self._by_person[person].remove(last)
                    self._by_person[person].append(at)
                    self._person_rows.pop(person, None)
            self._persons.pop()
            self._mat[last] = 0
            self._n -= 1

    async def clear(self) -> None:
        t, model = self._t, self.model
        async with self._lock:
            await self.store.run_views(lambda sql: sql.execute(delete(t).where(t.c.model == model)))
            self._reset([])
            self._spilled = False

    def digest(self) -> str:
        h = hashlib.blake2b(digest_size=16)
        if self._spilled:
            after = -1
            t = self._t
            while rows := self.store.query_views(select(t.c.key, t.c.vec).where(t.c.model == self.model, t.c.key > after)
                                                 .order_by(t.c.key).limit(1024)):
                for key, blob in rows:
                    h.update(str(key).encode())
                    h.update(blob)
                after = int(rows[-1][0])
            return h.hexdigest()
        for key in sorted(self._pos):
            h.update(str(key).encode())
            h.update(self._mat[self._pos[key]].astype(np.float16).tobytes())
        return h.hexdigest()
