"""Une base par app de la Forge (ADR 0101, point 8) : créée avec l'app, vidée ou supprimée avec elle.

- **Sous MariaDB** : la base ``<préfixe>forge_<app>`` et un utilisateur du même nom, qui n'a de droits que sur elle
  — lire, écrire, créer et modifier ses tables, index et vues ; ni ``EVENT`` (une tâche planifiée survivrait au
  disjoncteur), ni procédure, ni déclencheur, ni ``GRANT``, ni ``FILE``, aucun droit global —, borné (connexions,
  requêtes par heure, durée d'une instruction). Son mot de passe est tiré au hasard à chaque démarrage de l'hôte et
  ne quitte pas sa mémoire (``ALTER USER`` le repose) : rien à sceller, rien à montrer. Le compte de Mika crée la base
  et l'utilisateur ; il lui faut ``CREATE USER`` et ``GRANT OPTION`` sur ses bases (``deploy/README.md``).
- **Sous SQLite** (les tests, le simulateur, une installation sans serveur) : un fichier à elle (``_bases/<app>.db``),
  ouvert avec un contrôleur qui refuse ``ATTACH`` (lire ou écrire un autre fichier, ``VACUUM INTO`` compris) et
  ``PRAGMA`` ; ses lectures passent par une connexion en lecture seule ; une instruction est interrompue à son
  échéance.

L'app ne voit ni mot de passe ni socket : elle demande ses requêtes à l'hôte (``api.query``, ``api.execute``), une
instruction par appel, des paramètres nommés (``:nom``), que l'hôte exécute sous son identité, résultat borné. L'hôte
vérifie la forme — une lecture commence par ``SELECT`` ou ``WITH``, une écriture par ``INSERT``, ``UPDATE``,
``DELETE``, ``REPLACE``, ``CREATE``/``DROP`` d'une table, d'un index ou d'une vue, ``ALTER TABLE`` — ; c'est une
politesse : la défense, ce sont les droits du serveur (et sous SQLite le contrôleur et la lecture seule).

MariaDB n'a pas de quota par base : l'hôte mesure la taille de chaque base et, au-delà de ``max_bytes``, refuse ce
qui l'agrandirait (une suppression passe toujours : de quoi faire de la place), en le disant à l'app.

Le stockage clé/valeur d'une app (``api.kv_*``) est la table ``_kv`` de sa base ; son journal, la table
``forge_logs`` de ``views`` (jetable).
"""

from __future__ import annotations

import base64
import datetime as dt
import decimal
import json
import re
import secrets
import sqlite3
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Column,
    Engine,
    Index,
    MetaData,
    Table,
    create_engine,
    delete,
    event,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.pool import NullPool

from mika.adapters.database import MARIADB_CHARSET, MARIADB_COLLATION, Target, ensure_database, sqlite_engine
from mika.ports.sql import TABLE_OPTIONS, Id, Key, LongText, ViewsBase, table_args, upsert

__all__ = ["BaseLimits", "ForgeBases", "ForgeLogRow", "SqlRefused"]

APP = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
#: ce qu'une lecture peut être ; ce qu'une écriture peut être ; ce qui ne fait que libérer de la place
READ = re.compile(r"^(SELECT|WITH)\b", re.I)
WRITE = re.compile(r"^(INSERT|UPDATE|DELETE|REPLACE|CREATE\s+(TABLE|INDEX|UNIQUE\s+INDEX|VIEW)|"
                   r"DROP\s+(TABLE|INDEX|VIEW)|ALTER\s+TABLE)\b", re.I)
FREEING = re.compile(r"^(DELETE|DROP)\b", re.I)
#: la table de son stockage clé/valeur
KV = "_kv"
KV_MAX_KEYS = 1000
KV_MAX_KEY = 200
KV_MAX_VALUE = 16_000
#: les droits d'une app sur sa base (ni EVENT, ni ROUTINE, ni TRIGGER, ni GRANT OPTION ; rien hors d'elle)
PRIVILEGES = "SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, INDEX, ALTER, CREATE VIEW, SHOW VIEW, REFERENCES"
#: combien de temps une mesure de taille vaut (secondes)
SIZE_TTL_S = 10.0
DEFAULT_PREFIX = "mika_"


class SqlRefused(ValueError):
    """Une requête d'app refusée (forme, base pleine, erreur du moteur) : le message est pour l'app."""


@dataclass(frozen=True, slots=True)
class BaseLimits:
    #: la taille au-delà de laquelle sa base n'accepte plus que ce qui libère de la place
    max_bytes: int = 100 * 1024 * 1024
    #: la durée d'une instruction (le serveur l'interrompt ; sous SQLite, l'hôte)
    statement_s: float = 5.0
    #: ce qu'une lecture rend au plus : lignes, et octets (en JSON)
    max_rows: int = 500
    max_result: int = 256_000
    #: la longueur d'une instruction
    max_sql: int = 20_000
    #: sous MariaDB : connexions simultanées, requêtes par heure
    connections: int = 4
    queries_per_hour: int = 36_000


class ForgeLogRow(ViewsBase):
    """Le journal des apps de la Forge (``views`` : jetable), ``MAX_LOGS`` lignes par app."""

    __tablename__ = "forge_logs"
    __table_args__ = table_args(Index("forge_logs_app", "app", "id"))
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    app: Mapped[str] = mapped_column(Key(31))
    at: Mapped[float]
    line: Mapped[str] = mapped_column(LongText)


_KV_META = MetaData()
KV_TABLE = Table(KV, _KV_META, Column("k", Key(KV_MAX_KEY), primary_key=True), Column("v", LongText, nullable=False),
                 **TABLE_OPTIONS)
_LOGS = ForgeLogRow.__table__


def _authorize(action: int, _a1: Any, _a2: Any, _db: Any, _trigger: Any) -> int:
    """Le contrôleur d'une base d'app sous SQLite : ni un autre fichier (``ATTACH``, ``VACUUM INTO``), ni ``PRAGMA``."""
    if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH, sqlite3.SQLITE_PRAGMA):
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _plain(value: Any) -> Any:
    """Une valeur lue, telle qu'une app la reçoit (du JSON)."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode()
    if isinstance(value, decimal.Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (dt.date, dt.time, dt.datetime)):
        return value.isoformat()
    return value


def _statement(sql: str, limit: int) -> str:
    sql = str(sql or "").strip()
    while sql.endswith(";"):
        sql = sql[:-1].rstrip()
    if not sql:
        raise SqlRefused("une instruction SQL vide")
    if len(sql) > limit:
        raise SqlRefused(f"instruction trop longue (au plus {limit} caractères)")
    return sql


def _params(params: Any) -> dict[str, Any]:
    if params is None:
        return {}
    if not isinstance(params, Mapping):
        raise SqlRefused("les paramètres sont un dictionnaire (« :nom » dans la requête)")
    return {str(k): v for k, v in params.items()}


def _mb(n: int) -> str:
    return f"{n / 1_000_000:.1f} Mo".replace(".", ",")


def _engine_error(exc: Exception) -> SqlRefused:
    orig = getattr(exc, "orig", None) or exc
    return SqlRefused(str(orig).strip()[:300] or type(orig).__name__)


class ForgeBases:
    """Les bases des apps d'un hôte de la Forge, et le journal de ses apps.

    ``server`` : l'adresse d'un serveur MariaDB, sans base (``MIKA_DATABASE_URL``) ; sans elle, des fichiers SQLite
    sous ``root/_bases``. ``prefix`` : le début du nom des bases (celui des bases de Mika). ``logs`` : la base du
    journal (``views``) ; par défaut, un fichier sous ``root/_bases``."""

    def __init__(self, root: Path, *, server: str | None = None, prefix: str = DEFAULT_PREFIX,
                 logs: Target | None = None, limits: BaseLimits = BaseLimits()) -> None:
        self.root = Path(root)
        self.server = server
        self.prefix = prefix
        self.limits = limits
        self._logs_target = logs or Target(path=self.root / "_bases" / "journal.db")
        self._logs: Engine | None = None
        self._lock = threading.RLock()
        #: app → (moteur qui écrit, moteur qui lit), pour ce processus
        self._engines: dict[str, tuple[Engine, Engine]] = {}
        #: app → (instant, taille) : la dernière mesure
        self._sizes: dict[str, tuple[float, int]] = {}

    # ── où vit une base ──
    @property
    def engine_name(self) -> str:
        return "mariadb" if self.server else "sqlite"

    def _check(self, app: str) -> str:
        if not APP.match(app):
            raise SqlRefused("un nom d'app : des minuscules, chiffres et _, commençant par une lettre (2 à 31)")
        return app

    def name(self, app: str) -> str:
        """Le nom de sa base (et de son utilisateur) sur le serveur."""
        out = f"{self.prefix}forge_{self._check(app)}"
        if len(out) > 64:
            raise SqlRefused("nom de base trop long")
        return out

    def path(self, app: str) -> Path:
        """Son fichier, sous SQLite."""
        return self.root / "_bases" / f"{self._check(app)}.db"

    # ── l'administration (le compte de Mika) ──
    def _admin(self) -> Engine:
        assert self.server is not None
        return create_engine(make_url(self.server).set(database=None), poolclass=NullPool,
                             isolation_level="AUTOCOMMIT")

    def _user(self, app: str) -> str:
        return f"'{self.name(app)}'@'localhost'"

    def ensure(self, app: str) -> None:
        """Sa base existe, son utilisateur aussi (mot de passe neuf pour ce processus), et sa table ``_kv``."""
        self._engines_of(app)

    def _engines_of(self, app: str) -> tuple[Engine, Engine]:
        with self._lock:
            got = self._engines.get(app)
            if got is None:
                got = self._engines[app] = self._open(app)
            return got

    def _open(self, app: str) -> tuple[Engine, Engine]:
        if self.server is None:
            path = self.path(app)
            path.parent.mkdir(parents=True, exist_ok=True)
            writer = self._sqlite(path, read_only=False)
            with writer.begin() as conn:
                KV_TABLE.create(conn, checkfirst=True)
            return writer, self._sqlite(path, read_only=True)
        name, user = self.name(app), self._user(app)
        password = secrets.token_urlsafe(32)
        ensure_database(self.server, name)
        lim = self.limits
        escaped = name.replace("_", "\\_")  # dans un GRANT, « _ » est un joker : seulement cette base
        admin = self._admin()
        try:
            with admin.connect() as conn:
                conn.exec_driver_sql(f"CREATE USER IF NOT EXISTS {user} IDENTIFIED BY %s", (password,))
                conn.exec_driver_sql(
                    f"ALTER USER {user} IDENTIFIED BY %s WITH MAX_USER_CONNECTIONS {int(lim.connections)} "
                    f"MAX_QUERIES_PER_HOUR {int(lim.queries_per_hour)} MAX_STATEMENT_TIME {float(lim.statement_s):g}",
                    (password,))
                try:
                    conn.exec_driver_sql(f"GRANT {PRIVILEGES} ON `{escaped}`.* TO {user}")
                except SQLAlchemyError:
                    conn.exec_driver_sql(f"DROP USER IF EXISTS {user}")  # pas d'utilisateur sans ses droits
                    raise
        finally:
            admin.dispose()
        url = make_url(self.server).set(username=name, password=password, database=name)
        writer, reader = self._mariadb(url, read_only=False), self._mariadb(url, read_only=True)
        with writer.connect() as conn:
            KV_TABLE.create(conn, checkfirst=True)
        return writer, reader

    @staticmethod
    def _sqlite(path: Path, *, read_only: bool) -> Engine:
        # une base d'app reste en journal classique (pas WAL) : sa lecture seule s'ouvre sans rien créer à côté
        return sqlite_engine(path, autocommit=True, check_same_thread=False, wal=False, read_only=read_only)

    @staticmethod
    def _mariadb(url: Any, *, read_only: bool) -> Engine:
        query = dict(url.query)
        query.setdefault("charset", MARIADB_CHARSET)
        engine = create_engine(url.set(query=query), poolclass=NullPool, isolation_level="AUTOCOMMIT")

        @event.listens_for(engine, "connect")
        def _setup(dbapi: Any, _record: Any) -> None:
            cursor = dbapi.cursor()
            try:
                cursor.execute("SET time_zone = '+00:00'")
                cursor.execute(f"SET collation_connection = '{MARIADB_COLLATION}'")
                if read_only:
                    cursor.execute("SET SESSION TRANSACTION READ ONLY")
            finally:
                cursor.close()

        return engine

    def _forget_engines(self, app: str) -> None:
        with self._lock:
            got = self._engines.pop(app, None)
            self._sizes.pop(app, None)
        if got is not None:
            for engine in got:
                engine.dispose()

    # ── ce qu'une app demande ──
    def _run(self, engine: Engine, sql: str, params: dict[str, Any], deadline: float, *, rows: bool) -> Any:
        end = min(deadline or float("inf"), time.monotonic() + self.limits.statement_s)
        with engine.connect() as conn:
            dbapi = conn.connection.dbapi_connection
            if self.server is None:
                # le contrôleur, le temps de l'instruction de l'app (l'hôte, lui, relit son schéma par PRAGMA) ; et
                # SQLite n'a pas de délai par instruction : l'hôte l'interrompt
                dbapi.set_authorizer(_authorize)
                dbapi.set_progress_handler(lambda: 1 if time.monotonic() > end else 0, 10_000)
            try:
                result = conn.execute(text(sql), params)
                if not rows:
                    inserted = re.match(r"(INSERT|REPLACE)\b", sql, re.I) is not None
                    return {"rows": max(0, int(result.rowcount or 0)),
                            "id": (getattr(result, "lastrowid", None) or None) if inserted else None}
                if not result.returns_rows:
                    return []
                out, size = [], 2
                for row in result.mappings():
                    item = {k: _plain(v) for k, v in row.items()}
                    size += len(json.dumps(item, ensure_ascii=False, default=str)) + 1
                    if len(out) >= self.limits.max_rows or size > self.limits.max_result:
                        raise SqlRefused(f"résultat trop gros (au plus {self.limits.max_rows} lignes et "
                                         f"{self.limits.max_result // 1000} Ko) : ajoute LIMIT ou filtre")
                    out.append(item)
                return out
            except SqlRefused:
                raise
            except (SQLAlchemyError, sqlite3.Error) as exc:
                raise _engine_error(exc) from None
            finally:
                if self.server is None:
                    dbapi.set_progress_handler(None, 0)
                    dbapi.set_authorizer(None)

    def query(self, app: str, sql: str, params: Any = None, deadline: float = 0.0) -> list[dict[str, Any]]:
        """Une lecture (``SELECT``, ``WITH``) : ses lignes, en dictionnaires."""
        sql = _statement(sql, self.limits.max_sql)
        if not READ.match(sql):
            raise SqlRefused("une lecture commence par SELECT ou WITH (pour écrire : api.execute)")
        _, reader = self._engines_of(app)
        return self._run(reader, sql, _params(params), deadline, rows=True)

    def execute(self, app: str, sql: str, params: Any = None, deadline: float = 0.0) -> dict[str, Any]:
        """Une écriture : combien de lignes, et l'identifiant inséré (s'il y en a un)."""
        sql = _statement(sql, self.limits.max_sql)
        if not WRITE.match(sql):
            raise SqlRefused("une écriture : INSERT, UPDATE, DELETE, REPLACE, CREATE ou DROP d'une table, d'un index "
                             "ou d'une vue, ALTER TABLE (pour lire : api.query)")
        if not FREEING.match(sql):
            self._room(app)
        writer, _ = self._engines_of(app)
        out = self._run(writer, sql, _params(params), deadline, rows=False)
        with self._lock:
            self._sizes.pop(app, None)
        return out

    def _room(self, app: str) -> None:
        size = self.size(app)
        if size > self.limits.max_bytes:
            raise SqlRefused(f"ta base est pleine ({_mb(size)}, au plus {_mb(self.limits.max_bytes)}) : supprime ce "
                             f"qui ne sert plus")

    # ── sa taille, son schéma ──
    def size(self, app: str, *, fresh: bool = False) -> int:
        """Sa taille, en octets (mesurée au plus toutes les ``SIZE_TTL_S`` secondes)."""
        now = time.monotonic()
        with self._lock:
            got = self._sizes.get(app)
        if got is not None and not fresh and now - got[0] < SIZE_TTL_S:
            return got[1]
        if self.server is None:
            path = self.path(app)
            size = sum(Path(f"{path}{s}").stat().st_size for s in ("", "-journal") if Path(f"{path}{s}").exists())
        else:
            # InnoDB ne remet ses tailles à jour que de loin en loin (3 Mo insérés : toujours 32 Ko) : ses statistiques
            # d'abord (``ANALYZE TABLE`` lit quelques pages, quelle que soit la taille), sa taille ensuite
            writer, _ = self._engines_of(app)
            with writer.connect() as conn:
                quote = conn.dialect.identifier_preparer.quote
                where = {"name": self.name(app)}
                tables = [r[0] for r in conn.execute(text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = :name "
                    "AND table_type = 'BASE TABLE'"), where)]
                if tables:
                    conn.execute(text("ANALYZE TABLE " + ", ".join(quote(t) for t in tables))).all()
                size = int(conn.execute(text(
                    "SELECT COALESCE(SUM(data_length + index_length), 0) FROM information_schema.tables "
                    "WHERE table_schema = :name"), where).scalar() or 0)
        with self._lock:
            self._sizes[app] = (now, size)
        return size

    def schema(self, app: str) -> dict[str, Any]:
        """Ses tables (colonnes, nombre de lignes) et ses vues, sa taille et son plafond."""
        _, reader = self._engines_of(app)
        try:
            with reader.connect() as conn:
                found = inspect(conn)
                quote = conn.dialect.identifier_preparer.quote
                tables = []
                for name in sorted(found.get_table_names()):
                    pk = set(found.get_pk_constraint(name).get("constrained_columns") or ())
                    columns = [{"name": c["name"], "type": str(c["type"]), "nullable": bool(c.get("nullable", True)),
                                "key": c["name"] in pk} for c in found.get_columns(name)]
                    count = conn.execute(text(f"SELECT COUNT(*) FROM {quote(name)}")).scalar() or 0
                    tables.append({"name": name, "rows": int(count), "columns": columns})
                views = sorted(found.get_view_names())
        except SQLAlchemyError as exc:
            raise _engine_error(exc) from None
        return {"engine": self.engine_name, "size": self.size(app, fresh=True), "max": self.limits.max_bytes,
                "tables": tables, "views": views}

    # ── son stockage clé/valeur (la table ``_kv``) ──
    def _kv(self, app: str, fn: Any) -> Any:
        writer, _ = self._engines_of(app)
        for attempt in (1, 2):
            try:
                with writer.begin() as conn:
                    return fn(conn)
            except DBAPIError:
                if attempt == 2:
                    raise
                with writer.begin() as conn:  # l'app a pu supprimer sa table : elle revient, vide
                    KV_TABLE.create(conn, checkfirst=True)
        return None

    def kv_get(self, app: str, key: str, default: Any = None) -> Any:
        row = self._kv(app, lambda c: c.execute(select(KV_TABLE.c.v).where(KV_TABLE.c.k == str(key)[:KV_MAX_KEY]))
                       .first())
        return json.loads(row[0]) if row else default

    def kv_set(self, app: str, key: str, value: Any) -> bool:
        key, raw = str(key)[:KV_MAX_KEY], json.dumps(value, ensure_ascii=False)
        if len(raw) > KV_MAX_VALUE:
            raise ValueError(f"valeur trop grosse (> {KV_MAX_VALUE // 1000} Ko)")
        self._room(app)

        def put(conn: Any) -> None:
            count = conn.execute(select(func.count()).select_from(KV_TABLE)).scalar() or 0
            exists = conn.execute(select(KV_TABLE.c.k).where(KV_TABLE.c.k == key)).first()
            if count >= KV_MAX_KEYS and not exists:
                raise ValueError(f"trop de clés (> {KV_MAX_KEYS})")
            upsert(conn, KV_TABLE, {"k": key, "v": raw}, keys=("k",))

        self._kv(app, put)
        return True

    def kv_delete(self, app: str, key: str) -> bool:
        self._kv(app, lambda c: c.execute(delete(KV_TABLE).where(KV_TABLE.c.k == str(key)[:KV_MAX_KEY])))
        return True

    def kv_keys(self, app: str, prefix: str = "") -> list[str]:
        start = str(prefix or "")  # filtré ici : ``LIKE`` ne compare pas la casse pareil sur les deux moteurs
        rows = self._kv(app, lambda c: c.execute(select(KV_TABLE.c.k).order_by(KV_TABLE.c.k).limit(KV_MAX_KEYS)).all())
        return [r[0] for r in rows if r[0].startswith(start)]

    # ── vider, supprimer ──
    def reset(self, app: str) -> int:
        """Vide sa base (tables et vues ; ``_kv`` revient vide) ; rend combien de lignes il y avait."""
        writer, _ = self._engines_of(app)
        total = 0
        try:
            with writer.connect() as conn:
                found = inspect(conn)
                quote = conn.dialect.identifier_preparer.quote
                for view in found.get_view_names():
                    conn.execute(text(f"DROP VIEW IF EXISTS {quote(view)}"))
                for name in found.get_table_names():
                    total += int(conn.execute(text(f"SELECT COUNT(*) FROM {quote(name)}")).scalar() or 0)
                    conn.execute(text(f"DROP TABLE IF EXISTS {quote(name)}"))
                KV_TABLE.create(conn, checkfirst=True)
        finally:
            with self._lock:
                self._sizes.pop(app, None)
        return total

    def drop(self, app: str, into: Path) -> Path | None:
        """Exporte sa base dans ``into`` (à côté de son code, dans la corbeille) puis la supprime, avec son
        utilisateur ; rend le fichier exporté (``None`` : elle n'avait pas de base)."""
        self._check(app)
        self._forget_engines(app)
        into.mkdir(parents=True, exist_ok=True)
        if self.server is None:
            path = self.path(app)
            if not path.exists():
                return None
            journal = Path(f"{path}-journal")  # une écriture interrompue : son journal la suit
            if journal.exists():
                journal.replace(into / "base.db-journal")
            target = into / "base.db"
            path.replace(target)
            return target
        name = self.name(app)
        target = into / "base.json"
        admin = self._admin()
        try:
            with admin.connect() as conn:
                exists = conn.execute(text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :n"),
                                      {"n": name}).first()
                if exists:
                    target.write_text(json.dumps(self._dump(conn, name), ensure_ascii=False, default=str),
                                      encoding="utf-8")
                conn.exec_driver_sql(f"DROP DATABASE IF EXISTS `{name}`")
                conn.exec_driver_sql(f"DROP USER IF EXISTS {self._user(app)}")
        finally:
            admin.dispose()
        return target if target.exists() else None

    @staticmethod
    def _dump(conn: Any, name: str) -> dict[str, Any]:
        """Ce que contenait une base MariaDB : la définition de chaque table et ses lignes (de quoi la relire à la
        main)."""
        out: dict[str, Any] = {"engine": "mariadb", "base": name, "tables": {}}
        tables = [r[0] for r in conn.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = :n ORDER BY table_name"), {"n": name})]
        for table in tables:
            create = conn.exec_driver_sql(f"SHOW CREATE TABLE `{name}`.`{table}`").first()
            rows = [{k: _plain(v) for k, v in r.items()}
                    for r in conn.exec_driver_sql(f"SELECT * FROM `{name}`.`{table}`").mappings()]
            out["tables"][table] = {"create": create[1] if create else "", "rows": rows}
        return out

    # ── le journal des apps ──
    def _logs_engine(self) -> Engine:
        with self._lock:
            if self._logs is None:
                target = self._logs_target
                target.ensure()
                engine = target.engine(autocommit=False)
                with engine.begin() as conn:
                    _LOGS.create(conn, checkfirst=True)
                self._logs = engine
            return self._logs

    def log(self, app: str, line: str, keep: int) -> None:
        engine = self._logs_engine()
        with engine.begin() as conn:
            conn.execute(_LOGS.insert().values(app=app, at=time.time(), line=line[:1000]))
            # au-delà de ``keep`` lignes pour cette app : les plus anciennes partent (le seuil d'abord, une
            # suppression ensuite : MariaDB refuse une sous-requête sur la table qu'on modifie)
            edge = conn.execute(select(_LOGS.c.id).where(_LOGS.c.app == app).order_by(_LOGS.c.id.desc())
                                .offset(keep).limit(1)).scalar()
            if edge is not None:
                conn.execute(delete(_LOGS).where(_LOGS.c.app == app, _LOGS.c.id <= edge))

    def logs(self, app: str, n: int = 20) -> list[str]:
        engine = self._logs_engine()
        with engine.connect() as conn:
            rows = conn.execute(select(_LOGS.c.line).where(_LOGS.c.app == app).order_by(_LOGS.c.id.desc())
                                .limit(n)).all()
        return [r[0] for r in reversed(rows)]

    def close(self) -> None:
        with self._lock:
            apps = list(self._engines)
        for app in apps:
            self._forget_engines(app)
        with self._lock:
            if self._logs is not None:
                self._logs.dispose()
                self._logs = None
