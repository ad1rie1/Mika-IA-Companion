"""Magasin SQLite à deux bases, un seul écrivain.

- ``mind.db`` (``synchronous=FULL``) : journal, contenus, dédoublonnage,
  instantanés, file de sortie, tables des projections T0 (appliquées dans la
  transaction d'ajout). C'est sa vie : c'est ce qu'on sauvegarde.
- ``views.db`` (``synchronous=NORMAL``) : projections différées et vecteurs,
  jetable et reconstructible.

En mode ``threaded`` (production), toutes les écritures passent par un fil
dédié ; sinon (simulation, tests) elles s'exécutent en ligne. Les lectures
utilisent leurs propres connexions (WAL), en autocommit.

Les connexions sont celles de SQLAlchemy (ADR 0101), les tables celles de
``mika.ports.journal`` ; toute requête du magasin est une requête SQLAlchemy,
compilée pour le moteur. Le port ``Sql`` accepte encore du SQL écrit en clair
(il va au curseur du pilote, paramètres ``?``) ; ``Sql.session`` est une session
ORM qui travaille dans la même transaction ; ``Sql.create`` / ``Sql.drop`` créent
et suppriment des tables déclarées (entités, tables de projection).
"""

from __future__ import annotations

import asyncio
import functools
import json
import queue
import re
import secrets
import threading
from collections.abc import Callable, Collection, Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, bindparam, delete, func, insert, select, update
from sqlalchemy.orm import Session

from mika.adapters.database import dbapi_in_transaction, dbapi_of, sqlite_engine, truncate_log
from mika.kernel.clock import DAY
from mika.ports.journal import (
    DEDUPE_KEY_MAX,
    MIND_TABLES,
    SUBJECT_MAX,
    VIEWS_TABLES,
    JournalContent,
    JournalDedupe,
    JournalEvent,
    JournalOutbox,
    JournalSnapshot,
    JournalSubject,
    ProjectorState,
)
from mika.ports.sql import Prepared, fit, insert_ignore, json_field, upsert
from mika.ports.store import (
    AppendBatch,
    ContentRow,
    OutboxRow,
    SnapshotRow,
    Sql,
    StoredEvent,
)

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
        if isinstance(sql, Prepared):
            return sql.execute(self.conn, params or None)
        if isinstance(sql, str):
            cur = dbapi_of(self.conn).cursor()
            cur.execute(sql, params)
            return cur
        return self.conn.execute(sql, params or None)

    def executemany(self, sql: Any, rows: Sequence[Any]) -> Any:
        self._flush()
        if isinstance(sql, Prepared):
            return sql.execute(self.conn, list(rows))
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

    def drop(self, *entities: Any) -> None:
        """Supprime les tables de ces entités (ou tables de projection) si elles existent."""
        self._flush()
        for e in entities:
            getattr(e, "__table__", e).drop(self.conn, checkfirst=True)

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
    if isinstance(sql, Prepared):
        return sql.fetch(conn, params or None)
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
        _transaction((mind,), lambda: SqlConn(mind).create(*MIND_TABLES))
        views = sqlite_engine(self.views_path, synchronous="NORMAL", check_same_thread=not self._threaded).connect()
        _transaction((views,), lambda: SqlConn(views).create(*VIEWS_TABLES))
        return mind, views

    async def open(self) -> None:
        self._writer.start()
        self._mind_reader = sqlite_engine(self.mind_path, autocommit=True)
        self._views_reader = sqlite_engine(self.views_path, autocommit=True)
        self._mind_r = self._mind_reader.connect()
        self._views_r = self._views_reader.connect()
        row = self._mind_r.execute(select(JournalEvent.seq, JournalEvent.at)
                                   .order_by(JournalEvent.seq.desc()).limit(1)).first()
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
            _transaction((m,), lambda: m.execute(insert(JournalEvent.__table__), [_event_row(e) for e in events]))

        self._writer.run_sync(fn)
        if events:
            self._head, self._last_at = events[-1].seq, events[-1].at

    async def mark_outbox(self, key: str, status: str, error: str | None = None) -> None:
        if self._sealed:
            raise StoreSealed("magasin scellé")

        def fn(m: Connection, v: Connection) -> None:
            _transaction((m,), lambda: m.execute(update(JournalOutbox).where(JournalOutbox.key == key).values(
                status=status, attempts=JournalOutbox.attempts + 1, last_error=error)))

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
                key = fit(subject, SUBJECT_MAX)
                refs = [r[0] for r in ms.query(select(JournalSubject.ref).where(JournalSubject.subject == key))]
                _forget_contents(ms, refs)
                # ce que les projections lui ont rattaché sans que le texte le nomme (un renfort) : effacé aussi
                extra = sorted({r for r in (purge(ms, vs) or ()) if r and r not in refs})
                _forget_contents(ms, extra)
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

                    # Pages bornées : même l'oubli ne charge pas des années de journal en RAM. La base écarte
                    # d'abord les enveloppes qui ne contiennent pas la clé (sous ses deux graphies JSON) :
                    # seules celles qui la portent sont décodées en Python.
                    needles = (json.dumps(subject, ensure_ascii=False)[1:-1], json.dumps(subject)[1:-1])
                    holds = (func.instr(JournalEvent.data, needles[0]) > 0) | (func.instr(JournalEvent.data, needles[1]) > 0)
                    after = 0
                    while True:
                        rows = ms.query(select(JournalEvent.seq, JournalEvent.data)
                                        .where(JournalEvent.seq > after, holds).order_by(JournalEvent.seq).limit(256))
                        if not rows:
                            break
                        for seq, raw in rows:
                            before = json.loads(raw)
                            clean = redact(before)
                            if clean != before:
                                # la forme compacte de ``model_dump_json``, celle de toutes les autres enveloppes
                                ms.execute(update(JournalEvent).where(JournalEvent.seq == seq).values(
                                    data=json.dumps(clean, ensure_ascii=False, separators=(",", ":"))))
                        after = rows[-1][0]
                    ms.execute(delete(JournalSnapshot))
                return len(refs) + len(extra)

            try:
                removed = _transaction((m, v), body)
            finally:
                ms.close()
                vs.close()
            for c in (m, v):
                truncate_log(c)
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
        rows = _P_DEDUPE.fetch(self._r(), {"type": type_name, "key": fit(key, DEDUPE_KEY_MAX)})
        row = rows[0] if rows else None
        return int(row[0]) if row else None

    def read(
        self, after: int = 0, types: Collection[str] | None = None, upto: int | None = None
    ) -> Iterator[StoredEvent]:
        if types is not None:
            types = list(types)
            if not types:
                return iter(())
        params: dict[str, Any] = {"after": after, "upto": upto, "types": types}
        # Connexion dédiée : un itérateur long ne doit pas gêner les autres lectures (et le journal se relit
        # magasin fermé, depuis son fichier).
        conn = (self._mind_reader or sqlite_engine(self.mind_path, autocommit=True)).connect()
        cur = _read_query(upto is not None, types is not None).execute(conn, params)

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
        rows = _P_EVENTS.fetch(self._r(), {"seqs": seqs})
        return [StoredEvent(*r) for r in rows]

    def latest(self, types: Collection[str], limit: int, *, where: tuple[str, Any] | None = None,
               before: int | None = None, correlations: Collection[str] | None = None) -> list[StoredEvent]:
        types = list(types)
        corrs = list(correlations)[:500] if correlations is not None else None
        if not types or limit <= 0 or corrs == []:
            return []
        query = select(*_EVENT_COLUMNS).where(JournalEvent.type.in_(types))
        if where is not None:
            query = query.where(json_field(JournalEvent.data, _field(where[0])) == _as_text(where[1]))
        if before is not None:
            query = query.where(JournalEvent.seq < before)
        if corrs is not None:
            query = query.where(JournalEvent.correlation.in_(corrs))
        query = query.order_by(JournalEvent.seq.desc()).limit(min(int(limit), 10_000))
        return [StoredEvent(*r) for r in self._r().execute(query).all()]

    def tally(self, type_name: str, field: str) -> list[tuple[Any, int, int]]:
        value = json_field(JournalEvent.data, _field(field)).label("value")
        last = func.max(JournalEvent.at).label("last")
        rows = self._r().execute(select(value, func.count(), last).where(JournalEvent.type == type_name)
                                 .group_by(value).order_by(last.desc(), value)).all()
        return [(r[0], int(r[1]), int(r[2])) for r in rows]

    def content(self, refs: Collection[str]) -> dict[str, str]:
        refs = list(refs)
        if not refs:
            return {}
        rows = [r for i in range(0, len(refs), 500) for r in _P_CONTENT.fetch(self._r(), {"refs": refs[i:i + 500]})]
        return {r[0]: r[1] for r in rows}

    def subjects(self, prefix: str) -> list[str]:
        # l'index par sujet : un parcours d'intervalle, jamais de toute la table
        query = select(JournalSubject.subject).distinct()
        if prefix:
            end = prefix[:-1] + chr(ord(prefix[-1]) + 1)
            query = query.where(JournalSubject.subject >= prefix, JournalSubject.subject < end)
        rows = self._r().execute(query.order_by(JournalSubject.subject)).all()
        return [str(r[0]) for r in rows]

    def latest_snapshot(self) -> SnapshotRow | None:
        row = self._r().execute(select(JournalSnapshot.seq, JournalSnapshot.at, JournalSnapshot.data)
                                .order_by(JournalSnapshot.seq.desc()).limit(1)).first()
        return SnapshotRow(int(row[0]), int(row[1]), row[2]) if row else None

    def pending_outbox(self) -> list[OutboxRow]:
        rows = _P_PENDING.fetch(self._r())
        return [OutboxRow(*r) for r in rows]

    def outbox_status(self, key: str) -> str | None:
        rows = _P_STATUS.fetch(self._r(), {"key": key})
        row = rows[0] if rows else None
        return row[0] if row else None

    def projector_state(self, name: str) -> tuple[int, int] | None:
        rows = _P_PROJECTOR.fetch(self._v(), {"name": name})
        row = rows[0] if rows else None
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
    if batch.events:
        m.execute(_P_INSERT_EVENTS, [_event_row(e) for e in batch.events])
    if batch.contents:
        m.execute(_P_INSERT_CONTENT, [{"ref": c.ref, "seq": c.seq, "level": c.level, "text": c.text}
                                      for c in batch.contents])
        insert_ignore(m, JournalSubject, [{"ref": c.ref, "subject": fit(s, SUBJECT_MAX)}
                                          for c in batch.contents for s in c.subjects])
    if batch.dedupe:
        m.execute(_P_INSERT_DEDUPE, [{"type": t, "key": fit(k, DEDUPE_KEY_MAX), "seq": q} for t, k, q in batch.dedupe])
    if batch.outbox:
        m.execute(_P_INSERT_OUTBOX, [{"key": o.key, "seq": o.seq, "effect": o.effect, "status": o.status,
                                      "attempts": o.attempts, "last_error": o.last_error} for o in batch.outbox])
    if batch.t0 is not None:
        batch.t0(m)
        m.close()  # ce que la session des projections avait en attente part avant l'instantané
    if batch.snapshot is not None:
        snap = batch.snapshot
        upsert(m, JournalSnapshot, {"seq": snap.seq, "at": snap.at, "data": snap.data}, keys=["seq"])
        # les plus récents gardés : lus d'abord (MariaDB ne supprime pas d'une table relue avec ``LIMIT``)
        kept = [r[0] for r in m.query(select(JournalSnapshot.seq).order_by(JournalSnapshot.seq.desc())
                                      .limit(SNAPSHOTS_KEPT))]
        m.execute(delete(JournalSnapshot).where(JournalSnapshot.seq.not_in(kept)))
        _prune_outbox(m, snap.at)


def _prune_outbox(m: SqlConn, at: int) -> None:
    """Efface les lignes parties de la file de sortie depuis plus de ``OUTBOX_DONE_KEPT_US`` (à chaque instantané,
    quelques fois par jour : une recherche dichotomique dans le journal et une suppression indexée)."""
    upto = _seq_before(m, at - OUTBOX_DONE_KEPT_US)
    if upto:
        m.execute(delete(JournalOutbox).where(JournalOutbox.status == "done", JournalOutbox.seq <= upto))


def _seq_before(m: SqlConn, t: int) -> int:
    """Le dernier ``seq`` du journal écrit avant l'instant ``t`` (0 s'il n'y en a pas). Les instants du journal ne
    décroissent jamais : une dichotomie sur la clé, jamais un parcours."""
    first = m.query(select(JournalEvent.seq, JournalEvent.at).order_by(JournalEvent.seq).limit(1))
    if not first or int(first[0][1]) >= t:
        return 0
    lo, hi = int(first[0][0]), int(m.query(select(func.max(JournalEvent.seq)))[0][0])
    while lo < hi:  # l'événement ``lo`` est d'avant ``t``
        mid = (lo + hi + 1) // 2
        seq, at = m.query(select(JournalEvent.seq, JournalEvent.at).where(JournalEvent.seq >= mid)
                          .order_by(JournalEvent.seq).limit(1))[0]
        if int(at) < t:
            lo = int(seq)
        else:
            hi = mid - 1
    return lo


_EVENT_COLUMNS = (JournalEvent.seq, JournalEvent.id, JournalEvent.type, JournalEvent.v, JournalEvent.at,
                  JournalEvent.causation, JournalEvent.correlation, JournalEvent.basis, JournalEvent.origin,
                  JournalEvent.data)
_OUTBOX_COLUMNS = (JournalOutbox.key, JournalOutbox.seq, JournalOutbox.effect, JournalOutbox.status,
                   JournalOutbox.attempts, JournalOutbox.last_error)


#: les requêtes qu'on passe à chaque ajout ou presque (le journal) : préparées une fois par moteur
_EVENT_FIELDS = ("seq", "id", "type", "v", "at", "causation", "correlation", "basis", "origin", "data")
_P_INSERT_EVENTS = Prepared(insert(JournalEvent.__table__), columns=_EVENT_FIELDS)
_P_INSERT_CONTENT = Prepared(insert(JournalContent.__table__), columns=("ref", "seq", "level", "text"))
_P_INSERT_DEDUPE = Prepared(insert(JournalDedupe.__table__), columns=("type", "key", "seq"))
_P_INSERT_OUTBOX = Prepared(insert(JournalOutbox.__table__),
                            columns=("key", "seq", "effect", "status", "attempts", "last_error"))
_P_CONTENT = Prepared(select(JournalContent.ref, JournalContent.text)
                      .where(JournalContent.ref.in_(bindparam("refs", expanding=True))))
_P_EVENTS = Prepared(select(*_EVENT_COLUMNS).where(JournalEvent.seq.in_(bindparam("seqs", expanding=True)))
                     .order_by(JournalEvent.seq))
_P_DEDUPE = Prepared(select(JournalDedupe.seq).where(JournalDedupe.type == bindparam("type"),
                                                     JournalDedupe.key == bindparam("key")))
_P_PENDING = Prepared(select(*_OUTBOX_COLUMNS).where(JournalOutbox.status == "pending").order_by(JournalOutbox.seq))
_P_STATUS = Prepared(select(JournalOutbox.status).where(JournalOutbox.key == bindparam("key")))
_P_PROJECTOR = Prepared(select(ProjectorState.version, ProjectorState.applied_seq)
                        .where(ProjectorState.name == bindparam("name")))


@functools.cache
def _read_query(bounded: bool, typed: bool) -> Prepared:
    """La relecture du journal (au démarrage, à chaque reconstruction) : préparée pour chacune de ses quatre formes."""
    query = select(*_EVENT_COLUMNS).where(JournalEvent.seq > bindparam("after"))
    if bounded:
        query = query.where(JournalEvent.seq <= bindparam("upto"))
    if typed:
        query = query.where(JournalEvent.type.in_(bindparam("types", expanding=True)))
    return Prepared(query.order_by(JournalEvent.seq))


def _event_row(e: StoredEvent) -> dict[str, Any]:
    return {"seq": e.seq, "id": e.id, "type": e.type, "v": e.v, "at": e.at, "causation": e.causation,
            "correlation": e.correlation, "basis": e.basis, "origin": e.origin, "data": e.data}


def _forget_contents(m: SqlConn, refs: Collection[str]) -> None:
    refs = list(refs)
    for i in range(0, len(refs), 500):
        chunk = refs[i:i + 500]
        m.execute(delete(JournalContent).where(JournalContent.ref.in_(chunk)))
        m.execute(delete(JournalSubject).where(JournalSubject.ref.in_(chunk)))


def _as_text(value: Any) -> Any:
    """Une valeur comparée à un champ JSON lu en texte (``json_field``) : un nombre ou un booléen y est écrit en
    texte JSON (``5``, ``true``) ; ``None`` reste ``None``."""
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value)


__all__ = ["SqliteStore", "SqlConn", "StoreSealed", "ContentRow", "OutboxRow", "SnapshotRow", "StoredEvent"]
