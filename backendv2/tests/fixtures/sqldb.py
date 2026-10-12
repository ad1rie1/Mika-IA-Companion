"""Un faux magasin pour les tests unitaires (ADR 0101) : une base SQLite en mémoire derrière le même objet ``Sql``
que le vrai magasin — SQL écrit en clair ou requêtes SQLAlchemy, ``create`` / ``drop`` de tables déclarées,
``session``, ``dialect`` — et les lectures (``query_mind``, ``query_views``, ``read_*``) et écritures (``run_*``) du
port, toutes sur cette base. Chaque requête est validée seule (autocommit).

Un test qui avait sa propre classe sur ``sqlite3.connect(":memory:")`` en hérite : ``class DB(SqlDB)``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from mika.adapters.store_sql.store import SqlConn
from tests.fixtures import backend


class SqlDB:
    def __init__(self) -> None:
        if backend.active():  # la voie MariaDB : une base jetable du serveur
            target = backend.target(Path("."), "sqldb")
            target.ensure()
            engine = target.engine(autocommit=True)
        else:
            engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False},
                                   isolation_level="AUTOCOMMIT")
        self.engine = engine
        self.conn = engine.connect()
        self.sql = SqlConn(self.conn)

    # ── le port ``Sql`` ──
    @property
    def dialect(self) -> Any:
        return self.conn.dialect

    @property
    def session(self) -> Any:
        return self.sql.session

    def execute(self, sql: Any, args: Any = ()) -> Any:
        return self.sql.execute(sql, args)

    def executemany(self, sql: Any, rows: Any) -> Any:
        return self.sql.executemany(sql, rows)

    def query(self, sql: Any, args: Any = ()) -> list[tuple[Any, ...]]:
        return self.sql.query(sql, args)

    def create(self, *entities: Any) -> None:
        self.sql.create(*entities)

    def drop(self, *entities: Any) -> None:
        self.sql.drop(*entities)

    # ── le magasin ──
    query_mind = query
    query_views = query

    def read_mind(self, fn: Callable[[Any], Any]) -> Any:
        return fn(self)

    read_views = read_mind

    async def run_mind(self, fn: Callable[[Any], Any]) -> Any:
        out = fn(self)
        self.sql.close()
        return out

    run_views = run_mind

    def close(self) -> None:
        self.sql.close()
        self.conn.close()
        self.engine.dispose()
