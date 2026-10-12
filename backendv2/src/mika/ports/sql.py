"""Le schéma déclaré (ADR 0101) : les bases, la façon d'y déclarer une table, des types qui veulent dire la même
chose sur SQLite (les tests, le simulateur, le jumeau) et sur MariaDB (sa vie, en production), et les quelques
écritures que les deux moteurs disent autrement.

**Une base, une** ``MetaData`` : ``MIND`` (sa vie : sauvegardée), ``VIEWS`` (reconstructible), ``MAIL``, ``FEEDS``,
``TEAMS``. Une entité se déclare dans le paquet qui la possède, sur la base de sa base (``MindBase``…), avec
``Mapped[...]`` ; une table qui ajoute des index les passe par ``table_args(...)``, qui garde la collation binaire.

**Les types.** Un entier est un ``BIGINT`` (les instants sont en microsecondes) ; une clé primaire numérique est
``Id`` (l'alias de ``rowid`` sous SQLite, ``AUTO_INCREMENT`` sous MariaDB). Toute colonne indexée, ou clé, est une
``Key(n)`` : un ``VARCHAR(n)`` dont la borne est **vérifiée ici, à chaque écriture**, sur les deux moteurs — SQLite
ne borne rien, MariaDB refuse : sans ce contrôle, un test passerait là où la production échoue (une recherche avec
une valeur trop longue, elle, ne trouve rien, comme sous MariaDB). Tout texte libre est
``LongText`` (``TEXT`` sous MariaDB ne garde que 64 Ko), tout octet ``LongBlob``. La collation par défaut est
binaire et sans remplissage (``utf8mb4_nopad_bin``, le ``BINARY`` de SQLite) : ``name:Élodie`` et ``name:elodie``
restent deux clés, et une recherche insensible aux accents compare des textes repliés en Python (``fold_text``).

**Les écritures qui diffèrent** : ``upsert`` (insérer ou remplacer quelques colonnes), ``insert_ignore`` (insérer
sauf doublon), ``greatest`` / ``least`` (le ``max(a, b)`` scalaire de SQLite), ``json_field`` (un champ d'un objet
JSON, en texte), ``json_has`` (une liste JSON contient-elle cette valeur ?). Le reste s'écrit avec les requêtes de
SQLAlchemy (``select``, ``insert``, ``update``, ``delete``), qui se traduisent seules ; jamais ``INSERT OR``,
``ON CONFLICT``, ``json_each``, ``json_extract``, ``||``, ``rowid``, ``PRAGMA``, ``strftime`` ni ``MAX(a, b)`` écrits
en clair. Toute écriture passe par SQLAlchemy (une écriture en clair échapperait aux bornes des ``Key``).

**Les projections** (ADR 0101, point 6) : leurs tables évoluent par leur version et une reconstruction depuis le
journal, jamais par une migration. ``projection_table`` les déclare pour les deux moteurs, sous leur nom suffixé de
version, dans ``PROJECTIONS`` — une ``MetaData`` que les migrations ignorent. Leurs vues (la porte de la mémoire,
ADR 0078) se créent par ``create_view`` à partir d'une requête, compilée pour le moteur ; ``view_table`` en déclare
les colonnes pour les lire par des requêtes.

**Pièges des deux moteurs** que rien ne relève tout seul : une colonne nue à côté d'un agrégat (``SELECT x, MAX(at)
… GROUP BY k``) prend sous SQLite la valeur de la ligne du maximum, sous MariaDB celle d'une ligne quelconque — on
la lit par une sous-requête ou une fenêtre ; ``a / b`` entre entiers est une division entière sous SQLite, décimale
sous MariaDB — ``a - a % b`` pour une tranche, ``//`` en Python ; un tri sans départage total peut rendre les ex æquo
dans un autre ordre — on départage par la clé.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Double,
    Engine,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    event,
    literal,
    type_coerce,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.dialects import sqlite as sqlite_dialect
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import functions

#: les noms des contraintes et des index sans nom explicite (MariaDB borne un identifiant à 64 caractères)
NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}

MIND = MetaData(naming_convention=NAMING)
VIEWS = MetaData(naming_convention=NAMING)
MAIL = MetaData(naming_convention=NAMING)
FEEDS = MetaData(naming_convention=NAMING)
TEAMS = MetaData(naming_convention=NAMING)

#: les tables des projections et les vues de la mémoire : déclarées pour les deux moteurs, hors des migrations
PROJECTIONS = MetaData(naming_convention=NAMING)
#: les colonnes des vues, pour les lire par des requêtes (jamais créées par ``create_all``)
VIEW_COLUMNS = MetaData()

#: chaque base par son nom (les migrations, la sauvegarde, les tests)
DATABASES: dict[str, MetaData] = {"mind": MIND, "views": VIEWS, "mail": MAIL, "feeds": FEEDS, "teams": TEAMS}

#: ce que toute table déclare pour MariaDB (SQLite l'ignore)
TABLE_OPTIONS: dict[str, str] = {
    "mariadb_engine": "InnoDB",
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_nopad_bin",
}

_MARIADB = ("mysql", "mariadb")

#: une clé primaire numérique : l'alias de ``rowid`` sous SQLite (un ``BIGINT`` ne l'est pas), ``AUTO_INCREMENT``
Id = BigInteger().with_variant(Integer(), "sqlite")
#: un texte libre, sans borne pratique
LongText = Text().with_variant(mysql.LONGTEXT(), *_MARIADB)
#: des octets, sans borne pratique
LongBlob = LargeBinary().with_variant(mysql.LONGBLOB(), *_MARIADB)


class KeyTooLong(ValueError):
    """Une valeur écrite dépasse la borne de sa colonne : refusée pareil sur les deux moteurs."""


class Key(String):
    """Un ``VARCHAR(n)`` : une clé, ou une colonne indexée. Sa borne est vérifiée à chaque écriture (``INSERT``,
    ``UPDATE`` : par l'ORM ou par une requête), en caractères comme MariaDB la compte, sur les deux moteurs — SQLite
    ne borne rien. Une recherche avec une valeur plus longue ne lève pas : elle ne trouve rien, comme sous MariaDB."""

    cache_ok = True


def _key_columns(table: Any) -> list[Any]:
    return [c for c in getattr(table, "columns", ()) if isinstance(c.type, Key) and c.type.length]


@event.listens_for(Engine, "before_cursor_execute")
def _bounded_writes(conn: Any, cursor: Any, statement: Any, parameters: Any, context: Any, executemany: bool) -> None:
    """Les bornes des ``Key`` à l'écriture (le SQL écrit en clair, qui va au pilote sans passer ici, n'en a pas)."""
    if context is None or not (context.isinsert or context.isupdate):
        return
    compiled = getattr(context, "compiled", None)
    table = getattr(getattr(compiled, "statement", None), "table", None)
    columns = _key_columns(table)
    if not columns:
        return
    for params in context.compiled_parameters or ():
        for col in columns:
            for name, value in params.items():
                if (name == col.key or name.startswith(col.key + "_m")) and isinstance(value, str) \
                        and len(value) > col.type.length:
                    raise KeyTooLong(f"{table.name}.{col.key} : valeur trop longue ({len(value)} caractères, "
                                     f"au plus {col.type.length})")


#: la borne d'une adresse de personne ou d'un sujet (``user_7``, ``name:alice``, ``mail:<adresse>``…) dans une clé : les
#: adresses venues de l'extérieur y sont ramenées dès leur fabrication (``fit``)
HANDLE_MAX = 400

#: les chiffres hexadécimaux d'empreinte que ``fit`` garde d'une valeur trop longue
FIT_DIGEST = 24


def fit(value: str | None, size: int) -> str:
    """Une valeur venue d'ailleurs, ramenée à ``size`` caractères au plus pour tenir dans sa ``Key`` : telle quelle si
    elle tient ; sinon son début, ``#`` et ``FIT_DIGEST`` chiffres hexadécimaux de l'empreinte (sha256) de toute la
    valeur — exactement ``size`` caractères. Déterministe, pareil sur les deux moteurs, et ``fit`` de ce qu'il rend le
    rend tel quel : on l'applique à l'écriture **et** à la lecture (pour retrouver ce qui a été écrit)."""
    value = value or ""
    if len(value) <= size:
        return value
    digest = hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()[:FIT_DIGEST]
    return (value[:max(0, size - FIT_DIGEST - 1)] + "#" + digest)[:size]


def table_args(*items: Any) -> tuple[Any, ...]:
    """Les ``__table_args__`` d'une table qui déclare ses index ou contraintes : ils gardent ``TABLE_OPTIONS``."""
    return (*items, dict(TABLE_OPTIONS))


_TYPES = {int: BigInteger(), float: Double(), bool: Boolean(), bytes: LongBlob}


class MindBase(DeclarativeBase):
    """Les entités de ``mind`` : sa vie, ce qu'on sauvegarde."""

    metadata = MIND
    __table_args__ = TABLE_OPTIONS
    type_annotation_map = _TYPES


class ViewsBase(DeclarativeBase):
    """Les entités de ``views`` : reconstructibles, jetables."""

    metadata = VIEWS
    __table_args__ = TABLE_OPTIONS
    type_annotation_map = _TYPES


class MailBase(DeclarativeBase):
    """Les entités du courrier."""

    metadata = MAIL
    __table_args__ = TABLE_OPTIONS
    type_annotation_map = _TYPES


class FeedsBase(DeclarativeBase):
    """Les entités des flux."""

    metadata = FEEDS
    __table_args__ = TABLE_OPTIONS
    type_annotation_map = _TYPES


class TeamsBase(DeclarativeBase):
    """Les entités de Teams."""

    metadata = TEAMS
    __table_args__ = TABLE_OPTIONS
    type_annotation_map = _TYPES


# ── ce que les deux moteurs écrivent autrement ──
def dialect_of(target: Any) -> str:
    """Le nom du moteur derrière une connexion, une session ou un moteur (``sqlite``, ``mariadb``…)."""
    dialect = getattr(target, "dialect", None)
    if dialect is None:
        dialect = target.get_bind().dialect
    return str(dialect.name)


def upsert(target: Any, table: Any, rows: Mapping[str, Any] | Sequence[Mapping[str, Any]], *,
           keys: Sequence[str], update: Sequence[str] | None = None) -> Any:
    """Insère ``rows`` ; une ligne dont la clé ``keys`` existe déjà voit ses colonnes ``update`` remplacées (toutes les
    autres colonnes insérées si ``update`` est omis). Exécuté sur ``target`` (connexion ou session).

    Sous MariaDB, le remplacement joue pour un conflit sur **n'importe quelle** clé unique de la table, pas seulement
    ``keys`` : une table qui en a plusieurs ne s'en sert pas."""
    table = getattr(table, "__table__", table)  # la table, pas l'entité : une insertion de Core, pas « en lot » de l'ORM
    many = not isinstance(rows, Mapping)
    sample = rows[0] if many and rows else rows
    if many and not rows:
        return None
    columns = tuple(update) if update is not None else tuple(c for c in sample if c not in keys)  # type: ignore[union-attr]
    stmt = _upsert_statement(dialect_of(target), table, tuple(keys), columns)
    return target.execute(stmt, list(rows) if many else dict(rows))  # type: ignore[arg-type]


@functools.lru_cache(maxsize=1024)
def _upsert_statement(name: str, table: Table, keys: tuple[str, ...], columns: tuple[str, ...]) -> Any:
    """La requête d'un ``upsert``, construite une fois par table, clé, colonnes et moteur (les valeurs ne passent qu'à
    l'exécution) : ``excluded`` et ``inserted`` recopient toutes les colonnes de la table à chaque construction."""
    if name == "sqlite":
        stmt = sqlite_dialect.insert(table)
        return stmt.on_conflict_do_update(index_elements=list(keys), set_={c: stmt.excluded[c] for c in columns}) \
            if columns else stmt.on_conflict_do_nothing(index_elements=list(keys))
    if name in _MARIADB:
        stmt = mysql.insert(table)
        first = keys[0]
        return stmt.on_duplicate_key_update({c: stmt.inserted[c] for c in columns} if columns
                                            else {first: stmt.table.c[first]})
    raise NotImplementedError(f"upsert : moteur {name} inconnu")


def insert_ignore(target: Any, table: Any, rows: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> int:
    """Insère ce qui n'est pas déjà là (un doublon de clé est ignoré) ; rend combien de lignes sont entrées.

    MariaDB fait de ``INSERT IGNORE`` un avertissement pour d'autres erreurs que le doublon : une valeur trop longue
    n'y arrive jamais, ``Key`` la refuse avant."""
    table = getattr(table, "__table__", table)  # une insertion de Core : elle rend combien de lignes sont entrées
    many = not isinstance(rows, Mapping)
    if many and not rows:
        return 0
    stmt = _ignore_statement(dialect_of(target), table)
    result = target.execute(stmt, list(rows) if many else dict(rows))  # type: ignore[arg-type]
    return max(0, int(result.rowcount or 0))


@functools.lru_cache(maxsize=1024)
def _ignore_statement(name: str, table: Table) -> Any:
    if name == "sqlite":
        return sqlite_dialect.insert(table).on_conflict_do_nothing()
    if name in _MARIADB:
        return mysql.insert(table).prefix_with("IGNORE")
    raise NotImplementedError(f"insert_ignore : moteur {name} inconnu")


@functools.cache
def alias_of(table: Table, name: str) -> Any:
    """L'alias ``name`` d'une table, construit une seule fois : un alias recopie toutes les colonnes de sa table la
    première fois qu'on les lit — le reconstruire à chaque requête coûte plus que la requête."""
    return table.alias(name)


class greatest(functions.GenericFunction[Any]):
    """La plus grande de ses valeurs (``max(a, b)`` sous SQLite, ``GREATEST`` ailleurs)."""

    name = "greatest"
    inherit_cache = True


class least(functions.GenericFunction[Any]):
    """La plus petite de ses valeurs (``min(a, b)`` sous SQLite, ``LEAST`` ailleurs)."""

    name = "least"
    inherit_cache = True


@compiles(greatest, "sqlite")
def _greatest_sqlite(element: Any, compiler: Any, **kw: Any) -> str:
    return f"max({compiler.process(element.clauses, **kw)})"


@compiles(least, "sqlite")
def _least_sqlite(element: Any, compiler: Any, **kw: Any) -> str:
    return f"min({compiler.process(element.clauses, **kw)})"


# ── les requêtes préparées : le chemin le plus chaud ──
class Prepared:
    """Une requête SQLAlchemy compilée une fois par moteur, puis exécutée au curseur du pilote. Le SQL reste déclaré
    (compilé pour SQLite ou pour MariaDB, rien d'écrit en clair) sans le coût de SQLAlchemy à chaque appel — une
    requête construite à chaque fois coûte 50 à 90 µs, préparée environ 2 µs, autant que le SQL écrit en clair. À
    réserver aux requêtes qu'on passe des milliers de fois (le journal, ce qui tourne à chaque événement).

    Ses paramètres sont des ``bindparam`` nommés, donnés à l'exécution par un dictionnaire ; un
    ``bindparam(nom, expanding=True)`` reçoit une liste (``IN``, jamais ``NOT IN`` : une liste vide n'y trouve rien).
    Une insertion se prépare par ``Prepared(insert(table), columns=(…))`` et s'exécute avec une ligne ou une liste de
    lignes. Les valeurs vont au pilote telles quelles (nombres, textes, octets, booléens) et les lignes lues en
    reviennent telles quelles (un booléen est un entier). Les bornes des ``Key`` sont vérifiées à l'écriture, comme
    pour toute autre écriture."""

    __slots__ = ("stmt", "columns", "_compiled", "_bounds")

    def __init__(self, stmt: Any, *, columns: Sequence[str] | None = None) -> None:
        self.stmt = stmt
        self.columns = tuple(columns) if columns is not None else None
        self._compiled: dict[tuple[str, str], tuple[str, tuple[str, ...], frozenset[str], dict[str, Any]]] = {}
        table = getattr(stmt, "table", None) if getattr(stmt, "is_dml", False) else None
        self._bounds = tuple((c.key, c.type.length) for c in _key_columns(table))

    def _sql(self, dialect: Any) -> tuple[str, tuple[str, ...], frozenset[str], dict[str, Any]]:
        # par moteur et par forme des paramètres : deux pilotes d'un même moteur ne marquent pas pareil (``?``, ``%s``)
        key = (dialect.name, getattr(dialect, "paramstyle", "qmark"))
        got = self._compiled.get(key)
        if got is None:
            kw: dict[str, Any] = {"column_keys": list(self.columns)} if self.columns is not None else {}
            compiled = self.stmt.compile(dialect=dialect, **kw)
            names = tuple(compiled.positiontup or ())
            expanding = frozenset(n for n in names if f"__[POSTCOMPILE_{n}]" in compiled.string)
            # les valeurs écrites dans la requête (``status == "pending"``, ``limit(1)``) sont des paramètres anonymes
            fixed = {n: b.effective_value for n, b in compiled.binds.items() if n in names and not b.required}
            got = self._compiled[key] = (compiled.string, names, expanding, fixed)
        return got

    def _check(self, rows: Sequence[Mapping[str, Any]]) -> None:
        for row in rows:
            for key, length in self._bounds:
                value = row.get(key)
                if isinstance(value, str) and len(value) > length:
                    raise KeyTooLong(f"{self.stmt.table.name}.{key} : valeur trop longue ({len(value)} caractères, "
                                     f"au plus {length})")

    def _bind(self, dialect: Any, params: Mapping[str, Any]) -> tuple[str, list[Any]]:
        sql, names, expanding, fixed = self._sql(dialect)
        if not expanding:
            return sql, [params[n] if n in params else fixed[n] for n in names]
        values: list[Any] = []
        for n in names:
            if n in expanding:
                items = list(params[n] if n in params else fixed[n])
                mark = "?" if getattr(dialect, "paramstyle", "qmark") == "qmark" else "%s"
                sql = sql.replace(f"__[POSTCOMPILE_{n}]", ", ".join([mark] * len(items)) if items else "NULL", 1)
                values.extend(items)
            else:
                values.append(params[n] if n in params else fixed[n])
        return sql, values

    def execute(self, conn: Any, params: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None) -> Any:
        """Exécute sur une connexion SQLAlchemy (dans sa transaction, s'il y en a une) ; rend le curseur du pilote.
        Une liste de lignes : une insertion en lot."""
        cursor = conn.connection.dbapi_connection.cursor()
        if params is not None and not isinstance(params, Mapping):
            rows = list(params)
            if self._bounds:
                self._check(rows)
            sql, names, _expanding, fixed = self._sql(conn.dialect)
            cursor.executemany(sql, [[r[n] if n in r else fixed[n] for n in names] for r in rows])
            return cursor
        given = params or {}
        if self._bounds:
            self._check([given])
        sql, values = self._bind(conn.dialect, given)
        cursor.execute(sql, values)
        return cursor

    def fetch(self, conn: Any, params: Mapping[str, Any] | None = None) -> list[tuple[Any, ...]]:
        return [tuple(r) for r in self.execute(conn, params).fetchall()]


# ── les projections : tables versionnées, vues ──
def projection_table(name: str, *items: Any) -> Table:
    """La table d'une projection sous son nom complet (suffixe de version compris) : ses colonnes et ses index (nommés
    avec ce nom), avec les options de MariaDB. Déclarée une fois par nom : un second appel rend la même table."""
    existing = PROJECTIONS.tables.get(name)
    if existing is not None:
        return existing
    return Table(name, PROJECTIONS, *items, **TABLE_OPTIONS)


def view_table(name: str, *columns: Any) -> Table:
    """Les colonnes d'une vue, pour la lire par des requêtes (``select(vue.c.text)``) ; la vue elle-même se crée par
    ``create_view``."""
    existing = VIEW_COLUMNS.tables.get(name)
    if existing is not None:
        return existing
    return Table(name, VIEW_COLUMNS, *columns)


def create_view(target: Any, name: str, query: Any) -> None:
    """Crée la vue ``name`` (si elle n'existe pas) sur ``query`` : une requête SQLAlchemy, compilée pour le moteur de
    ``target`` (ses valeurs écrites dans le texte de la vue), ou du SQL standard."""
    body = query if isinstance(query, str) else str(query.compile(dialect=target.dialect,
                                                                   compile_kwargs={"literal_binds": True}))
    target.execute(f"CREATE VIEW IF NOT EXISTS {_ident(name)} AS {body}")


def drop_view(target: Any, name: str) -> None:
    target.execute(f"DROP VIEW IF EXISTS {_ident(name)}")


def _ident(name: str) -> str:
    """Un nom de table ou de vue écrit dans du DDL : jamais un morceau de SQL."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name):
        raise ValueError(f"nom de table invalide : {name!r}")
    return name


# ── le JSON ──
_JSON_PATH = re.compile(r"\$(\.[A-Za-z_][A-Za-z0-9_]*)*")


def json_field(column: Any, key: str) -> Any:
    """Le champ ``key`` d'un objet JSON rangé dans ``column``, en texte (``NULL`` s'il manque) : la même valeur sur
    les deux moteurs — ``json_extract`` de SQLite rend un nombre pour un nombre, ``JSON_EXTRACT`` de MariaDB garde les
    guillemets d'une chaîne ; ici, c'est du texte des deux côtés."""
    return type_coerce(column, JSON)[key].as_string()


class json_has(functions.GenericFunction[bool]):
    """Vrai si la liste JSON de ``column`` (à ``path``, ``$`` : la valeur entière) contient ``value`` (un texte ou un
    nombre). ``json_each`` sous SQLite, ``JSON_CONTAINS`` sous MariaDB."""

    name = "json_has"
    type = Boolean()
    inherit_cache = True

    def __init__(self, column: Any, value: Any, path: str = "$", **kw: Any) -> None:
        if not _JSON_PATH.fullmatch(path):
            raise ValueError(f"chemin JSON invalide : {path!r}")
        super().__init__(column, literal(path), literal(value), literal(json.dumps(value, ensure_ascii=False)), **kw)


@compiles(json_has, "sqlite")
def _json_has_sqlite(element: Any, compiler: Any, **kw: Any) -> str:
    column, path, value, _candidate = (compiler.process(c, **kw) for c in element.clauses)
    return f"EXISTS (SELECT 1 FROM json_each({column}, {path}) AS je WHERE je.value = {value})"


@compiles(json_has)
def _json_has_default(element: Any, compiler: Any, **kw: Any) -> str:
    clauses = list(element.clauses)
    column, path, candidate = (compiler.process(clauses[i], **kw) for i in (0, 1, 3))
    return f"JSON_CONTAINS({column}, {candidate}, {path})"


def json_values(raw: Any) -> list[Any]:
    """Les valeurs d'une liste JSON lue d'une colonne (une liste vide pour ``NULL`` ou du texte illisible) : ce que
    ``json_each`` dépliait dans le SQL se déplie en Python, après la lecture."""
    if raw is None or raw == "":
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return list(value) if isinstance(value, list) else []


Builder = Callable[[str], Table]


__all__ = [
    "DATABASES", "FEEDS", "FIT_DIGEST", "HANDLE_MAX", "MAIL", "MIND", "NAMING", "TABLE_OPTIONS", "TEAMS", "VIEWS",
    "FeedsBase", "Id", "Key", "KeyTooLong", "LongBlob", "LongText", "MailBase", "MindBase", "TeamsBase", "ViewsBase",
    "PROJECTIONS", "VIEW_COLUMNS", "Builder", "Prepared", "alias_of", "create_view", "drop_view", "json_field", "json_has", "json_values",
    "projection_table", "view_table",
    "dialect_of", "fit", "greatest", "insert_ignore", "least", "table_args", "upsert",
]
