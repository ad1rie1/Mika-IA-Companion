"""Magasin SQLite à deux bases, un seul écrivain.

- ``mind.db`` (``synchronous=FULL``) : journal, contenus, dédoublonnage,
  instantanés, file de sortie, tables des projections T0 (appliquées dans la
  transaction d'ajout). C'est sa vie : c'est ce qu'on sauvegarde.
- ``views.db`` (``synchronous=NORMAL``) : projections différées et vecteurs,
  jetable et reconstructible.

En mode ``threaded`` (production), toutes les écritures passent par un fil
dédié ; sinon (simulation, tests) elles s'exécutent en ligne. Les lectures
utilisent leurs propres connexions (WAL), en autocommit.

Les connexions sont celles de SQLAlchemy (ADR 0101). Le SQL écrit en clair passe
au pilote tel quel, par son curseur (paramètres ``?``, que SQLite et le pilote
MariaDB comprennent tous deux : sans le coût d'une compilation) ; une requête
SQLAlchemy (``select``, ``insert``…) est compilée pour le moteur ; ``Sql.session``
est une session ORM qui travaille dans la même transaction. Le journal et les
projections sont encore écrits en clair ; les entités des autres (comptes,
réglages, traces…) créent leurs tables par ``Sql.create``.
"""

from __future__ import annotations

import asyncio
import json
import queue
import re
import secrets
import threading
from collections.abc import Callable, Collection, Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine
from sqlalchemy.orm import Session

from mika.adapters.database import dbapi_in_transaction, dbapi_of, sqlite_engine
from mika.kernel.clock import DAY
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
CREATE INDEX IF NOT EXISTS events_cause ON events(causation);
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
#: Une ligne « partie » de la file de sortie se garde tant de temps, puis s'efface à l'instantané suivant : elle ne
#: sert plus qu'à la console (« Sorties ») — le journal garde l'événement, et une clé de sortie ne revient jamais
#: (l'identifiant de l'événement en fait partie). Ce qui n'est pas parti (en attente, en cours, échoué, interrompu,
#: périmé, vu) reste, quel que soit son âge (ADR 0059).
OUTBOX_DONE_KEPT_US = 30 * DAY


class SqlConn:
    """Le port ``Sql`` sur une connexion SQLAlchemy : le SQL écrit en clair va au curseur du pilote (il rend ce
    curseur), une requête SQLAlchemy est compilée pour le moteur ; ``session`` travaille dans la même transaction
    (ce qu'elle a en attente part avant toute autre requête, l'ordre des écritures reste celui du code)."""

    __slots__ = ("conn", "_session")

    def __init__(self, conn: Connection) -> None:
        self.conn = conn
        self._session: Session | None = None

    @property
    def dialect(self) -> Any:
        """Le moteur derrière (``upsert``, ``insert_ignore`` le lisent)."""
        return self.conn.dialect

    @property
    def session(self) -> Session:
        if self._session is None:
            self._session = Session(bind=self.conn, autoflush=True, expire_on_commit=False)
        return self._session

    def _flush(self) -> None:
        if self._session is not None:
            self._session.flush()

    def execute(self, sql: Any, params: Any = ()) -> Any:
        self._flush()
        if isinstance(sql, str):
            cur = dbapi_of(self.conn).cursor()
            cur.execute(sql, params)
            return cur
        return self.conn.execute(sql, params or None)

    def executemany(self, sql: Any, rows: Sequence[Any]) -> Any:
        self._flush()
        if isinstance(sql, str):
            cur = dbapi_of(self.conn).cursor()
            cur.executemany(sql, rows)
            return cur
        return self.conn.execute(sql, list(rows))

    def query(self, sql: Any, params: Any = ()) -> list[tuple[Any, ...]]:
        self._flush()
        return _query(self.conn, sql, params)

    def executescript(self, script: str) -> None:
        """Des instructions séparées par ``;`` (du DDL : aucune chaîne n'y contient de ``;``), dans la transaction en
        cours — l'``executescript`` de sqlite3 validerait d'abord ce qui est en cours."""
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def create(self, *entities: Any) -> None:
        """Crée les tables de ces entités si elles n'existent pas (les tests, le simulateur ; en production, les
        migrations les ont déjà créées)."""
        self._flush()
        by_meta: dict[int, tuple[Any, list[Any]]] = {}
        for e in entities:
            table = getattr(e, "__table__", e)
            by_meta.setdefault(id(table.metadata), (table.metadata, []))[1].append(table)
        for meta, tables in by_meta.values():
            meta.create_all(self.conn, tables=tables, checkfirst=True)

    def close(self) -> None:
        """Ce que la session avait en attente part ; la session se ferme (la transaction, elle, reste à qui l'a
        ouverte)."""
        if self._session is not None:
            try:
                self._session.flush()
            finally:
                self._session.close()
                self._session = None


def _query(conn: Connection, sql: Any, params: Any = ()) -> list[tuple[Any, ...]]:
    if isinstance(sql, str):
        cur = dbapi_of(conn).cursor()
        cur.execute(sql, params)
        return cur.fetchall()
    return [tuple(r) for r in conn.execute(sql, params or None)]


def _in_job(conn: Connection, fn: Callable[[Sql], Any]) -> Any:
    """``fn`` sur ``conn`` ; sa session (s'il s'en sert) envoie ce qu'elle a en attente et se ferme avant la suite."""
    sql = SqlConn(conn)
    try:
        return fn(sql)
    finally:
        sql.close()


Job = Callable[[Connection, Connection], Any]
Done = Callable[[Any, BaseException | None], None]


class _Writer:
    """Exécute les écritures en ligne ou dans un fil dédié (un seul écrivain)."""

    def __init__(self, threaded: bool, opener: Callable[[], tuple[Connection, Connection]]) -> None:
        self.threaded = threaded
        self._opener = opener
        self._mind: Connection | None = None
        self._views: Connection | None = None
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
        self._mind_r: Connection | None = None
        self._views_r: Connection | None = None
        #: les moteurs des lectures (une connexion à part pour chaque ``read``)
        self._mind_reader: Engine | None = None
        self._views_reader: Engine | None = None
        self._head = 0
        self._last_at = 0
        self._sealed = False
        self._on_append: list[Callable[[AppendBatch], None]] = []

    # ── cycle de vie ──
    def _open_writers(self) -> tuple[Connection, Connection]:
        mind = sqlite_engine(self.mind_path, synchronous=self._mind_sync, check_same_thread=not self._threaded).connect()
        dbapi_of(mind).executescript(_MIND_SCHEMA)  # hors de toute transaction : à l'ouverture
        views = sqlite_engine(self.views_path, synchronous="NORMAL", check_same_thread=not self._threaded).connect()
        dbapi_of(views).executescript(_VIEWS_SCHEMA)
        return mind, views

    async def open(self) -> None:
        self._writer.start()
        self._mind_reader = sqlite_engine(self.mind_path, autocommit=True)
        self._views_reader = sqlite_engine(self.views_path, autocommit=True)
        self._mind_r = self._mind_reader.connect()
        self._views_r = self._views_reader.connect()
        row = _cursor(self._mind_r, "SELECT seq, at FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        if row:
            self._head, self._last_at = int(row[0]), int(row[1])

    async def close(self) -> None:
        self._writer.stop()
        for c in (self._mind_r, self._views_r):
            if c is not None:
                c.close()
        self._mind_r = self._views_r = None
        for e in (self._mind_reader, self._views_reader):
            if e is not None:
                e.dispose()
        self._mind_reader = self._views_reader = None

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

        def fn(m: Connection, v: Connection) -> None:
            _transaction((m,), lambda: SqlConn(m).executemany(
                "INSERT INTO events(seq,id,type,v,at,causation,correlation,basis,origin,data) VALUES(?,?,?,?,?,?,?,?,?,?)",
                [(e.seq, e.id, e.type, e.v, e.at, e.causation, e.correlation, e.basis, e.origin, e.data) for e in events],
            ))

        self._writer.run_sync(fn)
        if events:
            self._head, self._last_at = events[-1].seq, events[-1].at

    async def mark_outbox(self, key: str, status: str, error: str | None = None) -> None:
        if self._sealed:
            raise StoreSealed("magasin scellé")

        def fn(m: Connection, v: Connection) -> None:
            SqlConn(m).execute(
                "UPDATE outbox SET status=?, attempts=attempts+1, last_error=? WHERE key=?",
                (status, error, key),
            )

        await self._writer.run(fn)

    async def run_views(self, fn: Callable[[Sql], Any]) -> Any:
        if self._sealed:
            raise StoreSealed("magasin scellé")

        def wrapped(m: Connection, v: Connection) -> Any:
            return _transaction((v,), lambda: _in_job(v, fn))

        return await self._writer.run(wrapped)

    async def run_mind(self, fn: Callable[[Sql], Any]) -> Any:
        if self._sealed:
            raise StoreSealed("magasin scellé")

        def wrapped(m: Connection, v: Connection) -> Any:
            return _transaction((m,), lambda: _in_job(m, fn))

        return await self._writer.run(wrapped)

    async def forget_subject(self, subject: str, purge: Callable[[Sql, Sql], Iterable[str] | None]) -> int:
        """Efface les contenus d'un sujet et ce que les projections en reprennent, dans une transaction par
        base : une purge qui lève défait tout (les deux bases), et l'écrivain reste utilisable. Les pages
        libérées sont mises à zéro par ``secure_delete`` et le WAL tronqué : pas de ``VACUUM``, qui
        réécrirait toute la base sous l'unique fil d'écriture (et figerait Mika le temps de le faire)."""

        def fn(m: Connection, v: Connection) -> int:
            ms, vs = SqlConn(m), SqlConn(v)

            def body() -> int:
                refs = [r[0] for r in ms.execute("SELECT ref FROM content_subjects WHERE subject=?", (subject,))]
                for ref in refs:
                    ms.execute("DELETE FROM content WHERE ref=?", (ref,))
                    ms.execute("DELETE FROM content_subjects WHERE ref=?", (ref,))
                # ce que les projections lui ont rattaché sans que le texte le nomme (un renfort) : effacé aussi
                extra = sorted({r for r in (purge(ms, vs) or ()) if r and r not in refs})
                for ref in extra:
                    ms.execute("DELETE FROM content WHERE ref=?", (ref,))
                    ms.execute("DELETE FROM content_subjects WHERE ref=?", (ref,))
                if subject.startswith("name:"):
                    # Ces anciennes clés contiennent le nom en clair. L'oubli conserve des
                    # enveloppes rejouables, mais remplace cette clé partout par un jeton opaque.
                    replacement = "forgotten:" + secrets.token_hex(16)

                    def redact(value):
                        if isinstance(value, str):
                            if value == subject:
                                return replacement
                            if "|" in value:
                                return "|".join(",".join(replacement if part == subject else part
                                                       for part in group.split(",")) for group in value.split("|"))
                            return value
                        if isinstance(value, list):
                            return [redact(part) for part in value]
                        if isinstance(value, dict):
                            return {redact(key): redact(part) for key, part in value.items()}
                        return value

                    # Pages bornées : même l'oubli ne charge pas des années de journal en RAM. SQLite écarte
                    # d'abord les enveloppes qui ne contiennent pas la clé (sous ses deux graphies JSON) :
                    # seules celles qui la portent sont décodées en Python.
                    needles = (json.dumps(subject, ensure_ascii=False)[1:-1], json.dumps(subject)[1:-1])
                    after = 0
                    while True:
                        rows = ms.execute("SELECT seq,data FROM events WHERE seq>? AND "
                                         "(instr(data,?)>0 OR instr(data,?)>0) ORDER BY seq LIMIT 256",
                                         (after, *needles)).fetchall()
                        if not rows:
                            break
                        for seq, raw in rows:
                            before = json.loads(raw)
                            clean = redact(before)
                            if clean != before:
                                # la forme compacte de ``model_dump_json``, celle de toutes les autres enveloppes
                                ms.execute("UPDATE events SET data=? WHERE seq=?",
                                          (json.dumps(clean, ensure_ascii=False, separators=(",", ":")), seq))
                        after = rows[-1][0]
                    ms.execute("DELETE FROM snapshots")
                return len(refs) + len(extra)

            try:
                removed = _transaction((m, v), body)
            finally:
                ms.close()
                vs.close()
            for c in (m, v):
                dbapi_of(c).execute("PRAGMA wal_checkpoint(TRUNCATE)")  # hors transaction, au pilote
            return removed

        return await self._writer.run(fn)

    # ── lecture ──
    def head(self) -> int:
        return self._head

    def last_at(self) -> int:
        return self._last_at

    def _r(self) -> Connection:
        assert self._mind_r is not None, "magasin non ouvert"
        return self._mind_r

    def _v(self) -> Connection:
        assert self._views_r is not None, "magasin non ouvert"
        return self._views_r

    def find_dedupe(self, type_name: str, key: str) -> int | None:
        row = _cursor(self._r(), "SELECT seq FROM dedupe WHERE type=? AND key=?", (type_name, key)).fetchone()
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
        # Connexion dédiée : un itérateur long ne doit pas gêner les autres lectures (et le journal se relit
        # magasin fermé, depuis son fichier).
        conn = (self._mind_reader or sqlite_engine(self.mind_path, autocommit=True)).connect()
        cur = _cursor(conn, sql, params)

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
        rows = _cursor(self._r(),
            f"SELECT seq,id,type,v,at,causation,correlation,basis,origin,data FROM events WHERE seq IN ({','.join('?' * len(seqs))}) ORDER BY seq",
            seqs,
        ).fetchall()
        return [StoredEvent(*r) for r in rows]

    def latest(self, types: Collection[str], limit: int, *, where: tuple[str, Any] | None = None,
               before: int | None = None, correlations: Collection[str] | None = None) -> list[StoredEvent]:
        types = list(types)
        corrs = list(correlations)[:500] if correlations is not None else None
        if not types or limit <= 0 or corrs == []:
            return []
        sql = (f"SELECT seq,id,type,v,at,causation,correlation,basis,origin,data FROM events "
               f"WHERE type IN ({','.join('?' * len(types))})")
        params: list[Any] = list(types)
        if where is not None:
            sql += " AND json_extract(data, ?) = ?"
            params += [f"$.{_field(where[0])}", where[1]]
        if before is not None:
            sql += " AND seq < ?"
            params.append(before)
        if corrs is not None:
            sql += f" AND correlation IN ({','.join('?' * len(corrs))})"
            params += corrs
        sql += " ORDER BY seq DESC LIMIT ?"
        params.append(min(int(limit), 10_000))
        return [StoredEvent(*r) for r in _cursor(self._r(), sql, params).fetchall()]

    def tally(self, type_name: str, field: str) -> list[tuple[Any, int, int]]:
        rows = _cursor(self._r(),
            "SELECT json_extract(data, ?), COUNT(*), MAX(at) FROM events WHERE type=? GROUP BY 1 ORDER BY 3 DESC",
            (f"$.{_field(field)}", type_name)).fetchall()
        return [(r[0], int(r[1]), int(r[2])) for r in rows]

    def content(self, refs: Collection[str]) -> dict[str, str]:
        refs = list(refs)
        if not refs:
            return {}
        rows = _cursor(self._r(),
            f"SELECT ref, text FROM content WHERE ref IN ({','.join('?' * len(refs))})", refs
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def subjects(self, prefix: str) -> list[str]:
        # l'index par sujet : un parcours d'intervalle, jamais de toute la table
        end = prefix[:-1] + chr(ord(prefix[-1]) + 1) if prefix else ""
        sql = "SELECT DISTINCT subject FROM content_subjects" + (" WHERE subject >= ? AND subject < ?" if prefix else "")
        rows = _cursor(self._r(), sql + " ORDER BY subject", (prefix, end) if prefix else ()).fetchall()
        return [str(r[0]) for r in rows]

    def latest_snapshot(self) -> SnapshotRow | None:
        row = _cursor(self._r(), "SELECT seq, at, data FROM snapshots ORDER BY seq DESC LIMIT 1").fetchone()
        return SnapshotRow(int(row[0]), int(row[1]), row[2]) if row else None

    def pending_outbox(self) -> list[OutboxRow]:
        rows = _cursor(self._r(),
            "SELECT key, seq, effect, status, attempts, last_error FROM outbox WHERE status='pending' ORDER BY seq"
        ).fetchall()
        return [OutboxRow(*r) for r in rows]

    def outbox_status(self, key: str) -> str | None:
        row = _cursor(self._r(), "SELECT status FROM outbox WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def projector_state(self, name: str) -> tuple[int, int] | None:
        row = _cursor(self._v(), "SELECT version, applied_seq FROM projector_state WHERE name=?", (name,)).fetchone()
        return (int(row[0]), int(row[1])) if row else None

    def query_views(self, sql: Any, params: Any = ()) -> list[tuple[Any, ...]]:
        """Une lecture de ``views`` : du SQL écrit en clair, ou une requête SQLAlchemy (des tuples dans les deux cas)."""
        return _query(self._v(), sql, params)

    def query_mind(self, sql: Any, params: Any = ()) -> list[tuple[Any, ...]]:
        """Une lecture de ``mind`` : du SQL écrit en clair, ou une requête SQLAlchemy (des tuples dans les deux cas)."""
        return _query(self._r(), sql, params)

    def read_mind(self, fn: Callable[[Sql], Any]) -> Any:
        """``fn`` sur la connexion de lecture de ``mind`` (``Sql.session`` pour lire des entités) ; jamais pour
        écrire : chaque requête y est validée seule."""
        return _in_job(self._r(), fn)

    def read_views(self, fn: Callable[[Sql], Any]) -> Any:
        """Comme ``read_mind``, sur ``views``."""
        return _in_job(self._v(), fn)


def _field(name: str) -> str:
    """Un nom de champ de charge utile (jamais un morceau de SQL ou de chemin JSON)."""
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,40}", name):
        raise ValueError(f"nom de champ invalide : {name!r}")
    return name


class StoreSealed(RuntimeError):
    pass


def _cursor(conn: Connection, sql: str, params: Any = ()) -> Any:
    """Le SQL écrit en clair, au curseur du pilote de ``conn``."""
    cur = dbapi_of(conn).cursor()
    cur.execute(sql, params)
    return cur


def _transaction(conns: Sequence[Connection], body: Callable[[], Any]) -> Any:
    """``body`` dans une transaction sur chaque connexion : validées ensemble, ou toutes défaites — une
    validation qui échoue (disque plein, base verrouillée) défait aussi, jamais une transaction laissée
    ouverte (l'écrivain unique serait empoisonné : plus aucun ``BEGIN`` ne passerait). Une validation
    refusée peut laisser le pilote dans sa transaction alors que SQLAlchemy la croit finie : on le lui
    demande à lui."""
    for c in conns:
        c.begin()
    try:
        result = body()
        for c in conns:
            c.commit()
    except BaseException:
        for c in conns:
            try:
                if c.in_transaction():
                    c.rollback()
            finally:
                if dbapi_in_transaction(c):
                    dbapi_of(c).rollback()
        raise
    return result


def _write_batch(m: Connection, batch: AppendBatch) -> None:
    sql = SqlConn(m)
    try:
        _transaction((m,), lambda: _write_rows(sql, batch))
    finally:
        sql.close()


def _write_rows(m: SqlConn, batch: AppendBatch) -> None:
    """Le corps d'une transaction d'ajout (voir ``_write_batch``) ; les projections T0 écrivent sur la même
    connexion, dans la même transaction."""
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
        batch.t0(m)
        m.close()  # ce que la session des projections avait en attente part avant l'instantané
    if batch.snapshot is not None:
        s = batch.snapshot
        m.execute("INSERT OR REPLACE INTO snapshots(seq, at, data) VALUES(?,?,?)", (s.seq, s.at, s.data))
        m.execute(
            "DELETE FROM snapshots WHERE seq NOT IN (SELECT seq FROM snapshots ORDER BY seq DESC LIMIT ?)",
            (SNAPSHOTS_KEPT,),
        )
        _prune_outbox(m, s.at)


def _prune_outbox(m: SqlConn, at: int) -> None:
    """Efface les lignes parties de la file de sortie depuis plus de ``OUTBOX_DONE_KEPT_US`` (à chaque instantané,
    quelques fois par jour : une recherche dichotomique dans le journal et une suppression indexée)."""
    upto = _seq_before(m, at - OUTBOX_DONE_KEPT_US)
    if upto:
        m.execute("DELETE FROM outbox WHERE status='done' AND seq <= ?", (upto,))


def _seq_before(m: SqlConn, t: int) -> int:
    """Le dernier ``seq`` du journal écrit avant l'instant ``t`` (0 s'il n'y en a pas). Les instants du journal ne
    décroissent jamais : une dichotomie sur la clé, jamais un parcours."""
    first = m.execute("SELECT seq, at FROM events ORDER BY seq LIMIT 1").fetchone()
    if first is None or int(first[1]) >= t:
        return 0
    lo, hi = int(first[0]), int(m.execute("SELECT MAX(seq) FROM events").fetchone()[0])
    while lo < hi:  # l'événement ``lo`` est d'avant ``t``
        mid = (lo + hi + 1) // 2
        seq, at = m.execute("SELECT seq, at FROM events WHERE seq >= ? ORDER BY seq LIMIT 1", (mid,)).fetchone()
        if int(at) < t:
            lo = int(seq)
        else:
            hi = mid - 1
    return lo


__all__ = ["SqliteStore", "SqlConn", "StoreSealed", "ContentRow", "OutboxRow", "SnapshotRow", "StoredEvent"]
