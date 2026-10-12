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
sauf doublon), ``greatest`` / ``least`` (le ``max(a, b)`` scalaire de SQLite). Le reste s'écrit avec les requêtes de
SQLAlchemy (``select``, ``insert``, ``update``, ``delete``), qui se traduisent seules ; jamais ``INSERT OR``,
``ON CONFLICT``, ``json_each``, ``||``, ``rowid``, ``PRAGMA`` ni ``MAX(a, b)`` écrits en clair.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Double,
    Engine,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Text,
    event,
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
    columns = list(update) if update is not None else [c for c in sample if c not in keys]  # type: ignore[union-attr]
    name = dialect_of(target)
    if name == "sqlite":
        stmt = sqlite_dialect.insert(table)
        stmt = stmt.on_conflict_do_update(index_elements=list(keys),
                                          set_={c: stmt.excluded[c] for c in columns}) if columns \
            else stmt.on_conflict_do_nothing(index_elements=list(keys))
    elif name in _MARIADB:
        stmt = mysql.insert(table)
        first = list(keys)[0]
        stmt = stmt.on_duplicate_key_update({c: stmt.inserted[c] for c in columns} if columns
                                            else {first: stmt.table.c[first]})
    else:
        raise NotImplementedError(f"upsert : moteur {name} inconnu")
    return target.execute(stmt, list(rows) if many else dict(rows))  # type: ignore[arg-type]


def insert_ignore(target: Any, table: Any, rows: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> int:
    """Insère ce qui n'est pas déjà là (un doublon de clé est ignoré) ; rend combien de lignes sont entrées.

    MariaDB fait de ``INSERT IGNORE`` un avertissement pour d'autres erreurs que le doublon : une valeur trop longue
    n'y arrive jamais, ``Key`` la refuse avant."""
    table = getattr(table, "__table__", table)  # une insertion de Core : elle rend combien de lignes sont entrées
    many = not isinstance(rows, Mapping)
    if many and not rows:
        return 0
    name = dialect_of(target)
    if name == "sqlite":
        stmt = sqlite_dialect.insert(table).on_conflict_do_nothing()
    elif name in _MARIADB:
        stmt = mysql.insert(table).prefix_with("IGNORE")
    else:
        raise NotImplementedError(f"insert_ignore : moteur {name} inconnu")
    result = target.execute(stmt, list(rows) if many else dict(rows))  # type: ignore[arg-type]
    return max(0, int(result.rowcount or 0))


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


__all__ = [
    "DATABASES", "FEEDS", "FIT_DIGEST", "MAIL", "MIND", "NAMING", "TABLE_OPTIONS", "TEAMS", "VIEWS",
    "FeedsBase", "Id", "Key", "KeyTooLong", "LongBlob", "LongText", "MailBase", "MindBase", "TeamsBase", "ViewsBase",
    "dialect_of", "fit", "greatest", "insert_ignore", "least", "table_args", "upsert",
]
