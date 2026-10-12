"""Les moteurs SQL (ADR 0101) : un fichier SQLite aujourd'hui, une base MariaDB demain, derrière la même
``Engine`` de SQLAlchemy.

Deux sortes de connexion :

- **qui écrit** (``autocommit=False``) : une transaction ne commence que quand on la demande (``begin``, ou la
  première requête d'une session) et finit à sa validation ou à son annulation — sous SQLite, le ``BEGIN`` implicite
  du module ``sqlite3`` est coupé, et c'est SQLAlchemy qui l'émet (sinon une lecture, ou un DDL, échapperait à la
  transaction) ;
- **qui lit** (``autocommit=True``) : chaque requête voit ce qui est validé, sans retenir d'instantané (une connexion
  de lecture qui garderait une transaction ouverte ne verrait plus ce que Mika vient d'écrire).

``shared=True`` garde une seule connexion pour tout le moteur (un adaptateur qui sérialise lui-même ses accès sous
un verrou) ; sinon chaque ``connect`` en ouvre une neuve.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool, StaticPool

#: ce qu'une connexion SQLite attend avant de dire « base verrouillée » (millisecondes)
BUSY_TIMEOUT_MS = 30_000


def sqlite_url(path: str | Path) -> URL:
    return URL.create("sqlite", database=str(path))


def sqlite_engine(path: str | Path, *, synchronous: str = "NORMAL", autocommit: bool = False, shared: bool = False,
                  check_same_thread: bool = True) -> Engine:
    """Un moteur sur un fichier SQLite (créé, avec son dossier, s'il n'existe pas) : WAL, ``synchronous`` donné, pages
    libérées remises à zéro (``secure_delete`` : l'oubli efface vraiment, ADR 0073)."""
    if synchronous not in ("OFF", "NORMAL", "FULL", "EXTRA"):
        raise ValueError(f"synchronous inconnu : {synchronous!r}")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        sqlite_url(path),
        poolclass=StaticPool if shared else NullPool,
        connect_args={"check_same_thread": check_same_thread and not shared},
        isolation_level="AUTOCOMMIT" if autocommit else None,
    )

    @event.listens_for(engine, "connect")
    def _setup(dbapi: Any, _record: Any) -> None:
        dbapi.isolation_level = None  # aucune transaction implicite : SQLAlchemy dit quand elles commencent
        dbapi.execute("PRAGMA journal_mode=WAL")
        dbapi.execute(f"PRAGMA synchronous={synchronous}")
        dbapi.execute("PRAGMA secure_delete=ON")
        dbapi.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")

    if not autocommit:
        @event.listens_for(engine, "begin")
        def _begin(conn: Any) -> None:
            conn.exec_driver_sql("BEGIN")

    return engine


def dbapi_of(conn: Any) -> Any:
    """La connexion du pilote sous une connexion SQLAlchemy (le SQL écrit en clair y passe sans détour)."""
    return conn.connection.dbapi_connection


def dbapi_in_transaction(conn: Any) -> bool:
    """Le pilote tient-il une transaction ouverte ? (Une validation qui a échoué peut la laisser ouverte alors que
    SQLAlchemy la croit finie.)"""
    return bool(getattr(dbapi_of(conn), "in_transaction", False))


def truncate_log(conn: Any) -> None:
    """Après l'oubli, le journal d'écriture de SQLite (WAL) est tronqué : ce qui a été effacé n'y traîne plus. Hors
    de toute transaction. Sous MariaDB, rien d'équivalent à demander ici (ADR 0101, point 9)."""
    if conn.dialect.name == "sqlite":
        dbapi_of(conn).execute("PRAGMA wal_checkpoint(TRUNCATE)")


__all__ = ["BUSY_TIMEOUT_MS", "dbapi_in_transaction", "dbapi_of", "sqlite_engine", "sqlite_url", "truncate_log"]
