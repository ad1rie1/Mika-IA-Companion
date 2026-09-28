"""Magasin SQLite à deux bases, un seul écrivain.

- ``mind.db`` (``synchronous=FULL``) : journal, contenus, dédoublonnage,
  instantanés, file de sortie, tables des projections T0 (appliquées dans la
  transaction d'ajout). C'est sa vie : c'est ce qu'on sauvegarde.
- ``views.db`` (``synchronous=NORMAL``) : projections différées et vecteurs,
  jetable et reconstructible.

En mode ``threaded`` (production), toutes les écritures passent par un fil
dédié ; sinon (simulation, tests) elles s'exécutent en ligne. Les lectures
utilisent leurs propres connexions (WAL).
"""

from __future__ import annotations

import asyncio
import queue
import sqlite3
import threading
from collections.abc import Callable, Collection, Iterator, Sequence
from pathlib import Path
from typing import Any

from mika.ports.store import (
    AppendBatch,
    ContentRow,
    OutboxRow,
    SnapshotRow,
    Sql,
    StoredEvent,
)

_MIND_SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
    seq INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, type TEXT NOT NULL, v INTEGER NOT NULL,
    at INTEGER NOT NULL, causation TEXT, correlation TEXT NOT NULL, basis INTEGER NOT NULL,
    origin TEXT NOT NULL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_type ON events(type, seq);
CREATE INDEX IF NOT EXISTS events_corr ON events(correlation);
CREATE TABLE IF NOT EXISTS dedupe(type TEXT NOT NULL, key TEXT NOT NULL, seq INTEGER NOT NULL,
    PRIMARY KEY(type, key));
CREATE TABLE IF NOT EXISTS content(ref TEXT PRIMARY KEY, seq INTEGER NOT NULL, level INTEGER NOT NULL,
    text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS content_subjects(ref TEXT NOT NULL, subject TEXT NOT NULL,
    PRIMARY KEY(ref, subject));
CREATE INDEX IF NOT EXISTS content_by_subject ON content_subjects(subject);
CREATE TABLE IF NOT EXISTS snapshots(seq INTEGER PRIMARY KEY, at INTEGER NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outbox(key TEXT PRIMARY KEY, seq INTEGER NOT NULL, effect TEXT NOT NULL,
    status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT);
CREATE INDEX IF NOT EXISTS outbox_pending ON outbox(status, seq);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

_VIEWS_SCHEMA = """
CREATE TABLE IF NOT EXISTS projector_state(name TEXT PRIMARY KEY, version INTEGER NOT NULL,
    applied_seq INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS projector_quarantine(name TEXT NOT NULL, seq INTEGER NOT NULL, error TEXT,
    PRIMARY KEY(name, seq));
"""

SNAPSHOTS_KEPT = 3


class SqlConn:
    """Implémentation du port ``Sql`` sur une connexion sqlite3."""

    __slots__ = ("conn",)

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        return self.conn.execute(sql, params)

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> Any:
        return self.conn.executemany(sql, rows)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        return self.conn.execute(sql, params).fetchall()

    def executescript(self, script: str) -> None:
        self.conn.executescript(script)


def _connect(path: str, *, synchronous: str, readonly: bool = False, check_same_thread: bool = True) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(
            f"file:{path}?mode=ro", uri=True, check_same_thread=check_same_thread, isolation_level=None
        )
    else:
        conn = sqlite3.connect(path, check_same_thread=check_same_thread, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA synchronous={synchronous}")
        conn.execute("PRAGMA secure_delete=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


Job = Callable[[sqlite3.Connection, sqlite3.Connection], Any]
Done = Callable[[Any, BaseException | None], None]


class _Writer:
    """Exécute les écritures en ligne ou dans un fil dédié (un seul écrivain)."""

    def __init__(self, threaded: bool, opener: Callable[[], tuple[sqlite3.Connection, sqlite3.Connection]]) -> None:
        self.threaded = threaded
        self._opener = opener
        self._mind: sqlite3.Connection | None = None
        self._views: sqlite3.Connection | None = None
        self._queue: queue.Queue[tuple[Job, Done] | None] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.threaded:
            self._mind, self._views = self._opener()
            return
        ready = threading.Event()
        errors: list[BaseException] = []

        def run() -> None:
            try:
                self._mind, self._views = self._opener()
            except BaseException as exc:
                errors.append(exc)
                ready.set()
                return
            ready.set()
            while True:
                item = self._queue.get()
                if item is None:
                    break
                job, done = item
                try:
                    result = job(self._mind, self._views)
                except BaseException as exc:
                    done(None, exc)
                else:
                    done(result, None)
            for c in (self._mind, self._views):
                if c is not None:
                    c.close()

        self._thread = threading.Thread(target=run, name="mika-store-writer", daemon=True)
        self._thread.start()
        ready.wait()
        if errors:
            raise errors[0]

    async def run(self, job: Job) -> Any:
        if not self.threaded:
            assert self._mind is not None and self._views is not None
            return job(self._mind, self._views)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()

        def done(result: Any, exc: BaseException | None) -> None:
            def settle() -> None:
                if fut.done():
                    return
                if exc is not None:
                    fut.set_exception(exc)
                else:
                    fut.set_result(result)

            loop.call_soon_threadsafe(settle)

        self._queue.put((job, done))
        return await fut

    def run_sync(self, job: Job) -> Any:
        """Exécution bloquante (outils hors boucle, chargements massifs)."""
        if not self.threaded:
            assert self._mind is not None and self._views is not None
            return job(self._mind, self._views)
        finished = threading.Event()
        box: dict[str, Any] = {}

        def done(result: Any, exc: BaseException | None) -> None:
            box["r"], box["e"] = result, exc
            finished.set()

        self._queue.put((job, done))
        finished.wait()
        if box["e"] is not None:
            raise box["e"]
        return box["r"]

    def stop(self) -> None:
        if self.threaded and self._thread is not None:
            self._queue.put(None)
            self._thread.join(timeout=10)
            self._thread = None
        elif not self.threaded:
            for c in (self._mind, self._views):
                if c is not None:
                    c.close()
            self._mind = self._views = None


class SqliteStore:
    """Le port ``EventStore`` sur deux fichiers SQLite."""

    def __init__(
        self,
        mind_path: str | Path,
        views_path: str | Path,
        *,
        threaded: bool = True,
        mind_synchronous: str = "FULL",
    ) -> None:
        self.mind_path = str(mind_path)
        self.views_path = str(views_path)
        self._threaded = threaded
        self._mind_sync = mind_synchronous
        self._writer = _Writer(threaded, self._open_writers)
        self._mind_r: sqlite3.Connection | None = None
        self._views_r: sqlite3.Connection | None = None
        self._head = 0
        self._last_at = 0
        self._sealed = False
        self._on_append: list[Callable[[AppendBatch], None]] = []

    # ── cycle de vie ──
    def _open_writers(self) -> tuple[sqlite3.Connection, sqlite3.Connection]:
        for p in (self.mind_path, self.views_path):
            Path(p).parent.mkdir(parents=True, exist_ok=True)
        mind = _connect(self.mind_path, synchronous=self._mind_sync, check_same_thread=not self._threaded)
        mind.executescript(_MIND_SCHEMA)
        views = _connect(self.views_path, synchronous="NORMAL", check_same_thread=not self._threaded)
        views.executescript(_VIEWS_SCHEMA)
        return mind, views

    async def open(self) -> None:
        self._writer.start()
        self._mind_r = _connect(self.mind_path, synchronous="NORMAL")
        self._views_r = _connect(self.views_path, synchronous="NORMAL")
        row = self._mind_r.execute("SELECT seq, at FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        if row:
            self._head, self._last_at = int(row[0]), int(row[1])

    async def close(self) -> None:
        self._writer.stop()
        for c in (self._mind_r, self._views_r):
            if c is not None:
                c.close()
        self._mind_r = self._views_r = None

    # ── scellement (simulation d'un kill -9) ──
    def seal(self) -> None:
        self._sealed = True

    def unseal(self) -> None:
        self._sealed = False

    def on_append(self, hook: Callable[[AppendBatch], None]) -> None:
        self._on_append.append(hook)

    # ── écriture ──
    async def append(self, batch: AppendBatch) -> None:
        if self._sealed:
            raise StoreSealed("magasin scellé")
        await self._writer.run(lambda m, v: _write_batch(m, batch))
        if batch.events:
            self._head = batch.events[-1].seq
            self._last_at = batch.events[-1].at
        for hook in self._on_append:
            hook(batch)

    def bulk_load(self, events: Sequence[StoredEvent]) -> None:
        """Chargement massif (tests de performance) : une transaction."""

        def fn(m: sqlite3.Connection, v: sqlite3.Connection) -> None:
            m.execute("BEGIN")
            m.executemany(
                "INSERT INTO events(seq,id,type,v,at,causation,correlation,basis,origin,data) VALUES(?,?,?,?,?,?,?,?,?,?)",
                [(e.seq, e.id, e.type, e.v, e.at, e.causation, e.correlation, e.basis, e.origin, e.data) for e in events],
            )
            m.execute("COMMIT")

        self._writer.run_sync(fn)
        if events:
            self._head, self._last_at = events[-1].seq, events[-1].at

    async def mark_outbox(self, key: str, status: str, error: str | None = None) -> None:
        if self._sealed:
            raise StoreSealed("magasin scellé")

        def fn(m: sqlite3.Connection, v: sqlite3.Connection) -> None:
            m.execute(
                "UPDATE outbox SET status=?, attempts=attempts+1, last_error=? WHERE key=?",
                (status, error, key),
            )

        await self._writer.run(fn)

    async def run_views(self, fn: Callable[[Sql], Any]) -> Any:
        if self._sealed:
            raise StoreSealed("magasin scellé")

        def wrapped(m: sqlite3.Connection, v: sqlite3.Connection) -> Any:
            v.execute("BEGIN")
            try:
                result = fn(SqlConn(v))
            except BaseException:
                v.execute("ROLLBACK")
                raise
            v.execute("COMMIT")
            return result

        return await self._writer.run(wrapped)

    async def run_mind(self, fn: Callable[[Sql], Any]) -> Any:
        if self._sealed:
            raise StoreSealed("magasin scellé")

        def wrapped(m: sqlite3.Connection, v: sqlite3.Connection) -> Any:
            m.execute("BEGIN")
            try:
                result = fn(SqlConn(m))
            except BaseException:
                m.execute("ROLLBACK")
                raise
            m.execute("COMMIT")
            return result

        return await self._writer.run(wrapped)

    async def forget_subject(self, subject: str, purge: Callable[[Sql, Sql], None]) -> int:
        def fn(m: sqlite3.Connection, v: sqlite3.Connection) -> int:
            m.execute("BEGIN")
            v.execute("BEGIN")
            refs = [r[0] for r in m.execute("SELECT ref FROM content_subjects WHERE subject=?", (subject,))]
            for ref in refs:
                m.execute("DELETE FROM content WHERE ref=?", (ref,))
                m.execute("DELETE FROM content_subjects WHERE ref=?", (ref,))
            purge(SqlConn(m), SqlConn(v))
            m.execute("COMMIT")
            v.execute("COMMIT")
            for c in (m, v):
                c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                c.execute("VACUUM")
                c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return len(refs)

        return await self._writer.run(fn)

    # ── lecture ──
    def head(self) -> int:
        return self._head

    def last_at(self) -> int:
        return self._last_at

    def _r(self) -> sqlite3.Connection:
        assert self._mind_r is not None, "magasin non ouvert"
        return self._mind_r

    def find_dedupe(self, type_name: str, key: str) -> int | None:
        row = self._r().execute("SELECT seq FROM dedupe WHERE type=? AND key=?", (type_name, key)).fetchone()
        return int(row[0]) if row else None

    def read(
        self, after: int = 0, types: Collection[str] | None = None, upto: int | None = None
    ) -> Iterator[StoredEvent]:
        sql = "SELECT seq,id,type,v,at,causation,correlation,basis,origin,data FROM events WHERE seq>?"
        params: list[Any] = [after]
        if upto is not None:
            sql += " AND seq<=?"
            params.append(upto)
        if types is not None:
            types = list(types)
            if not types:
                return iter(())
            sql += f" AND type IN ({','.join('?' * len(types))})"
            params.extend(types)
        sql += " ORDER BY seq"
        # Connexion dédiée : un itérateur long ne doit pas gêner les autres lectures.
        conn = _connect(self.mind_path, synchronous="NORMAL")
        cur = conn.execute(sql, params)

        def gen() -> Iterator[StoredEvent]:
            try:
                while True:
                    rows = cur.fetchmany(2048)
                    if not rows:
                        break
                    for r in rows:
                        yield StoredEvent(*r)
            finally:
                conn.close()

        return gen()

    def get_events(self, seqs: Collection[int]) -> list[StoredEvent]:
        seqs = list(seqs)
        if not seqs:
            return []
        rows = self._r().execute(
            f"SELECT seq,id,type,v,at,causation,correlation,basis,origin,data FROM events WHERE seq IN ({','.join('?' * len(seqs))}) ORDER BY seq",
            seqs,
        ).fetchall()
        return [StoredEvent(*r) for r in rows]

    def content(self, refs: Collection[str]) -> dict[str, str]:
        refs = list(refs)
        if not refs:
            return {}
        rows = self._r().execute(
            f"SELECT ref, text FROM content WHERE ref IN ({','.join('?' * len(refs))})", refs
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def latest_snapshot(self) -> SnapshotRow | None:
        row = self._r().execute("SELECT seq, at, data FROM snapshots ORDER BY seq DESC LIMIT 1").fetchone()
        return SnapshotRow(int(row[0]), int(row[1]), row[2]) if row else None

    def pending_outbox(self) -> list[OutboxRow]:
        rows = self._r().execute(
            "SELECT key, seq, effect, status, attempts, last_error FROM outbox WHERE status='pending' ORDER BY seq"
        ).fetchall()
        return [OutboxRow(*r) for r in rows]

    def outbox_status(self, key: str) -> str | None:
        row = self._r().execute("SELECT status FROM outbox WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def projector_state(self, name: str) -> tuple[int, int] | None:
        assert self._views_r is not None
        row = self._views_r.execute(
            "SELECT version, applied_seq FROM projector_state WHERE name=?", (name,)
        ).fetchone()
        return (int(row[0]), int(row[1])) if row else None

    def query_views(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        assert self._views_r is not None
        return self._views_r.execute(sql, params).fetchall()

    def query_mind(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        return self._r().execute(sql, params).fetchall()


class StoreSealed(RuntimeError):
    pass


def _write_batch(m: sqlite3.Connection, batch: AppendBatch) -> None:
    m.execute("BEGIN")
    try:
        m.executemany(
            "INSERT INTO events(seq,id,type,v,at,causation,correlation,basis,origin,data) VALUES(?,?,?,?,?,?,?,?,?,?)",
            [(e.seq, e.id, e.type, e.v, e.at, e.causation, e.correlation, e.basis, e.origin, e.data) for e in batch.events],
        )
        if batch.contents:
            m.executemany(
                "INSERT INTO content(ref, seq, level, text) VALUES(?,?,?,?)",
                [(c.ref, c.seq, c.level, c.text) for c in batch.contents],
            )
            m.executemany(
                "INSERT OR IGNORE INTO content_subjects(ref, subject) VALUES(?,?)",
                [(c.ref, s) for c in batch.contents for s in c.subjects],
            )
        if batch.dedupe:
            m.executemany("INSERT INTO dedupe(type, key, seq) VALUES(?,?,?)", batch.dedupe)
        if batch.outbox:
            m.executemany(
                "INSERT INTO outbox(key, seq, effect, status, attempts, last_error) VALUES(?,?,?,?,?,?)",
                [(o.key, o.seq, o.effect, o.status, o.attempts, o.last_error) for o in batch.outbox],
            )
        if batch.t0 is not None:
            batch.t0(SqlConn(m))
        if batch.snapshot is not None:
            s = batch.snapshot
            m.execute("INSERT OR REPLACE INTO snapshots(seq, at, data) VALUES(?,?,?)", (s.seq, s.at, s.data))
            m.execute(
                "DELETE FROM snapshots WHERE seq NOT IN (SELECT seq FROM snapshots ORDER BY seq DESC LIMIT ?)",
                (SNAPSHOTS_KEPT,),
            )
    except BaseException:
        m.execute("ROLLBACK")
        raise
    m.execute("COMMIT")


__all__ = ["SqliteStore", "SqlConn", "StoreSealed", "ContentRow", "OutboxRow", "SnapshotRow", "StoredEvent"]
