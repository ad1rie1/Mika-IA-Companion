"""Les moteurs SQL (ADR 0101) : un fichier SQLite (les tests, le simulateur, le jumeau) ou une base d'un serveur
MariaDB (sa vie), derrière la même ``Engine`` de SQLAlchemy.

Une **cible** (``Target``) dit où vit une base — un chemin, ou l'adresse d'un serveur et le nom de la base — et
fabrique ses moteurs. Deux sortes de connexion :

- **qui écrit** (``autocommit=False``) : une transaction ne commence que quand on la demande (``begin``, ou la
  première requête d'une session) et finit à sa validation ou à son annulation — sous SQLite, le ``BEGIN`` implicite
  du module ``sqlite3`` est coupé, et c'est SQLAlchemy qui l'émet (sinon une lecture, ou un DDL, échapperait à la
  transaction) ; sous MariaDB, en ``READ COMMITTED`` ;
- **qui lit** (``autocommit=True``) : chaque requête voit ce qui est validé, sans retenir d'instantané (une connexion
  de lecture qui garderait une transaction ouverte ne verrait plus ce que Mika vient d'écrire).

``shared=True`` garde, sous SQLite, une seule connexion pour tout le moteur (un adaptateur qui sérialise lui-même ses
accès sous un verrou) ; sinon chaque ``connect`` en ouvre une neuve. Sous MariaDB, chaque ``connect`` prend une
connexion au réservoir, vérifiée avant de resservir.

Sous MariaDB, chaque session parle ``utf8mb4`` et compte le temps en UTC ; une base absente est créée avec la
collation binaire (``utf8mb4_nopad_bin``, ADR 0101 point 4) ; une connexion gardée longtemps sans servir est vérifiée
avant de resservir (le serveur coupe une connexion oubliée : ``wait_timeout``, huit heures par défaut).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool, StaticPool

#: ce qu'une connexion SQLite attend avant de dire « base verrouillée » (millisecondes)
BUSY_TIMEOUT_MS = 30_000
#: la collation et le jeu de caractères d'une base créée sur un serveur MariaDB
MARIADB_CHARSET = "utf8mb4"
MARIADB_COLLATION = "utf8mb4_nopad_bin"
#: au-delà, une connexion gardée (l'écrivain, la lecture du magasin) est vérifiée avant de resservir (secondes)
IDLE_CHECK_S = 600.0

_NAME = re.compile(r"[A-Za-z0-9_]{1,64}")


@dataclass(frozen=True, slots=True)
class Target:
    """Où vit une base : un fichier SQLite (``path``), ou la base ``name`` du serveur ``url`` (sans base dans
    l'adresse : ``mariadb+pymysql://utilisateur@localhost/?unix_socket=…``)."""

    path: Path | None = None
    url: str | None = None
    name: str | None = None

    def __post_init__(self) -> None:
        if (self.path is None) == (self.url is None):
            raise ValueError("une cible est un fichier ou une base d'un serveur, pas les deux")
        if self.url is not None and not (self.name and _NAME.fullmatch(self.name)):
            raise ValueError(f"nom de base invalide : {self.name!r}")

    @property
    def is_sqlite(self) -> bool:
        return self.path is not None

    def __str__(self) -> str:
        return str(self.path) if self.path is not None else f"{self.name} ({_safe(self.url)})"

    def engine(self, *, synchronous: str = "NORMAL", autocommit: bool = False, shared: bool = False,
               check_same_thread: bool = True) -> Engine:
        if self.path is not None:
            return sqlite_engine(self.path, synchronous=synchronous, autocommit=autocommit, shared=shared,
                                 check_same_thread=check_same_thread)
        assert self.url is not None and self.name is not None
        # ``shared`` ne vaut que pour SQLite : sous MariaDB, chacun prend une connexion au réservoir (vérifiée avant de
        # resservir) — une connexion unique gardée des heures serait coupée par le serveur
        return mariadb_engine(self.url, self.name, autocommit=autocommit)

    def ensure(self) -> None:
        """La base existe (créée au besoin sur le serveur ; un fichier SQLite naît à sa première connexion)."""
        if self.url is not None:
            ensure_database(self.url, str(self.name))

    def drop(self) -> None:
        """Supprime la base (les tests : une base jetable par test)."""
        if self.path is not None:
            for suffix in ("", "-wal", "-shm"):
                Path(f"{self.path}{suffix}").unlink(missing_ok=True)
            return
        server = _server_engine(str(self.url))
        try:
            with server.connect() as conn:
                conn.exec_driver_sql(f"DROP DATABASE IF EXISTS `{self.name}`")
        finally:
            server.dispose()


def as_target(where: str | Path | Target) -> Target:
    return where if isinstance(where, Target) else Target(path=Path(where))


# ── SQLite ──
def sqlite_url(path: str | Path) -> URL:
    return URL.create("sqlite", database=str(path))


def sqlite_engine(path: str | Path, *, synchronous: str = "NORMAL", autocommit: bool = False, shared: bool = False,
                  check_same_thread: bool = True, wal: bool = True, read_only: bool = False) -> Engine:
    """Un moteur sur un fichier SQLite (créé, avec son dossier, s'il n'existe pas) : WAL (sauf ``wal=False`` : le
    journal classique), ``synchronous`` donné, pages libérées remises à zéro (``secure_delete`` : l'oubli efface
    vraiment, ADR 0073). ``read_only`` : une connexion qui ne peut pas écrire (le fichier doit exister ; une base en
    WAL a besoin de ses fichiers voisins, d'où ``wal=False`` pour ce qu'on lit ainsi)."""
    if synchronous not in ("OFF", "NORMAL", "FULL", "EXTRA"):
        raise ValueError(f"synchronous inconnu : {synchronous!r}")
    if read_only:
        url = URL.create("sqlite", database=f"file:{quote(str(path))}", query={"mode": "ro", "uri": "true"})
    else:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        url = sqlite_url(path)
    engine = create_engine(
        url,
        poolclass=StaticPool if shared else NullPool,
        connect_args={"check_same_thread": check_same_thread and not shared},
        isolation_level="AUTOCOMMIT" if autocommit else None,
    )

    @event.listens_for(engine, "connect")
    def _setup(dbapi: Any, _record: Any) -> None:
        dbapi.isolation_level = None  # aucune transaction implicite : SQLAlchemy dit quand elles commencent
        if wal and not read_only:
            dbapi.execute("PRAGMA journal_mode=WAL")
        dbapi.execute(f"PRAGMA synchronous={synchronous}")
        if not read_only:
            dbapi.execute("PRAGMA secure_delete=ON")
        dbapi.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")

    if not autocommit:
        @event.listens_for(engine, "begin")
        def _begin(conn: Any) -> None:
            conn.exec_driver_sql("BEGIN")

    return engine


# ── MariaDB ──
def _safe(url: str | None) -> str:
    """Une adresse de serveur montrable (sans son mot de passe)."""
    return make_url(url).render_as_string(hide_password=True) if url else ""


def _server_engine(url: str) -> Engine:
    return create_engine(make_url(url).set(database=None), poolclass=NullPool, isolation_level="AUTOCOMMIT")


def ensure_database(url: str, name: str) -> None:
    if not _NAME.fullmatch(name):
        raise ValueError(f"nom de base invalide : {name!r}")
    server = _server_engine(url)
    try:
        with server.connect() as conn:
            conn.exec_driver_sql(f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET {MARIADB_CHARSET} "
                                 f"COLLATE {MARIADB_COLLATION}")
    finally:
        server.dispose()


def mariadb_engine(url: str, name: str, *, autocommit: bool = False) -> Engine:
    """Un moteur sur la base ``name`` du serveur ``url`` : ``utf8mb4``, UTC, ``READ COMMITTED`` pour qui écrit,
    autocommit pour qui lit ; le réservoir vérifie une connexion avant de la redonner."""
    target = make_url(url).set(database=name)
    query = dict(target.query)
    query.setdefault("charset", MARIADB_CHARSET)
    extra: dict[str, Any] = {}
    if target.get_driver_name() in ("pymysql", "mysqldb"):
        # des paramètres positionnels (``%s``), comme ``?`` sous SQLite : les requêtes préparées les rangent par ordre
        extra["paramstyle"] = "format"
    engine = create_engine(
        target.set(query=query),
        pool_pre_ping=True,
        pool_recycle=3600,
        isolation_level="AUTOCOMMIT" if autocommit else "READ COMMITTED",
        **extra,
    )

    @event.listens_for(engine, "connect")
    def _setup(dbapi: Any, _record: Any) -> None:
        cursor = dbapi.cursor()
        try:
            cursor.execute("SET time_zone = '+00:00'")
            cursor.execute(f"SET collation_connection = '{MARIADB_COLLATION}'")
        finally:
            cursor.close()

    return engine


# ── la connexion du pilote ──
def dbapi_of(conn: Any) -> Any:
    """La connexion du pilote sous une connexion SQLAlchemy (le SQL écrit en clair y passe sans détour)."""
    return conn.connection.dbapi_connection


def dbapi_in_transaction(conn: Any) -> bool:
    """Le pilote tient-il une transaction ouverte ? (Une validation qui a échoué peut la laisser ouverte alors que
    SQLAlchemy la croit finie ; seul ``sqlite3`` le dit.)"""
    return bool(getattr(dbapi_of(conn), "in_transaction", False))


def placeholder(dialect: Any) -> str:
    """Le marqueur d'un paramètre positionnel pour ce moteur (``?`` sous SQLite, ``%s`` pour PyMySQL)."""
    return "?" if getattr(dialect, "paramstyle", "qmark") == "qmark" else "%s"


class Kept:
    """Une connexion gardée longtemps (l'écrivain du magasin, sa lecture) : vérifiée avant de resservir si elle n'a pas
    servi depuis ``IDLE_CHECK_S`` — sous MariaDB, le serveur l'a peut-être coupée ; SQLAlchemy en prend alors une
    neuve. Sous SQLite, rien à vérifier."""

    __slots__ = ("conn", "_used")

    def __init__(self, conn: Any) -> None:
        self.conn = conn
        self._used = time.monotonic()

    def get(self) -> Any:
        now = time.monotonic()
        if self.conn.dialect.name != "sqlite" and now - self._used > IDLE_CHECK_S:
            # entre deux travaux : aucune transaction à respecter (l'écrivain les ouvre et les ferme lui-même)
            try:
                self.conn.exec_driver_sql("SELECT 1")
            except Exception:  # noqa: BLE001 — coupée : SQLAlchemy l'a invalidée, la prochaine requête en reprend une
                pass
            if self.conn.in_transaction():
                self.conn.rollback()
        self._used = now
        return self.conn

    def close(self) -> None:
        """La refermer, même si le serveur l'a coupée pendant un long silence : une nuit sans un mot dépasse le
        ``wait_timeout`` de MariaDB (8 h). Il n'y a alors plus rien à annuler, et l'arrêt du serveur ne doit pas
        échouer pour si peu (le 2026-10-14, « MySQL server has gone away » interrompait l'arrêt en plein milieu)."""
        try:
            self.conn.close()
        except DBAPIError:
            pass  # coupée : SQLAlchemy l'a invalidée en levant


def truncate_log(conn: Any) -> None:
    """Après l'oubli, le journal d'écriture de SQLite (WAL) est tronqué : ce qui a été effacé n'y traîne plus. Hors
    de toute transaction. Sous MariaDB, rien d'équivalent à demander ici (ADR 0101, point 9)."""
    if conn.dialect.name == "sqlite":
        dbapi_of(conn).execute("PRAGMA wal_checkpoint(TRUNCATE)")


__all__ = [
    "BUSY_TIMEOUT_MS", "IDLE_CHECK_S", "MARIADB_CHARSET", "MARIADB_COLLATION", "Kept", "Target", "as_target",
    "dbapi_in_transaction", "dbapi_of", "ensure_database", "mariadb_engine", "placeholder", "sqlite_engine",
    "sqlite_url", "truncate_log",
]
