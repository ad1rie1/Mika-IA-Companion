"""Les tables de la mémoire (ADR 0101) : déclarées pour les deux moteurs, hors des migrations — une projection
évolue par sa version et une reconstruction depuis le journal. Une fonction par table, qui prend le suffixe de version
(``items("")`` : la table T0 ; ``items("_v3")``…).

Les types : un entier est un ``BIGINT`` (les instants sont en microsecondes), un réel un ``DOUBLE`` ; une clé ou une
colonne indexée est une ``Key`` (une adresse de personne ou un sujet ``name:…`` : ``HANDLE_MAX``, que la projection
garantit par ``fit`` à l'écriture plutôt que de faire échouer l'ajout) ; tout autre texte est un ``LongText`` (les
listes JSON — ``about``, ``told_by``… — en sont : elles peuvent dépasser toute borne). Les ``id`` reprennent le
``seq`` de l'événement qui a créé la ligne : jamais attribués par la base.

Les index sont nommés d'après la table suffixée. Celui des empreintes (``fingerprint``) ne couvre plus ``about``,
``told_by``, ``heard_by`` (des listes JSON, non indexables sous MariaDB) : l'empreinte d'un texte, avec sa sorte et
son statut, suffit à ne relire que ses quasi-doublons.

``memory_chunks`` est déclarée au contrat (``contracts.memory.chunks_table`` : la console la relit) ; le fil
(``transcript``) et le graphe des liens (``social``), que la mémoire relit, le sont aux leurs.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from functools import cache
from typing import Any

from sqlalchemy import BigInteger, Column, Double, Index, PrimaryKeyConstraint, Table, and_, select
from sqlalchemy.exc import DBAPIError

from mika.contracts import memory as c
from mika.ports.paging import fold_text
from mika.ports.sql import HANDLE_MAX, Key, LongText, fit, projection_table

#: élément → la référence de son texte (``Content.ref``)
REFS_TABLE = "memory_refs"
#: une croyance → ses témoignages (ADR 0080) : qui le lui a dit, qui l'a entendu, ce que ça pèse, secret ou non
TESTIMONIES_TABLE = "memory_testimonies"
#: deux croyances qui se contredisent sans que l'une remplace l'autre (``item``, ``other``, ``at``), dans les deux sens
#: (ADR 0081) : elle doute
CONTESTS_TABLE = "memory_contests"
#: élément → le dernier événement qui l'a touché (l'index des vecteurs suit ce qui a changé)
CHANGES_TABLE = "memory_changes"
DEFERRED_TABLE = "memory_extraction_queue"
#: ce qu'elle a lu (ADR 0085) : une ligne par lecture, jusqu'à ce que la nuit l'ait relue
READINGS_TABLE = "memory_readings"

#: la borne d'une sorte d'élément, d'un statut (``c.KIND_MAX``, ``c.STATUS_MAX``), de qui ressent (``theirs`` /
#: ``hers``) et d'un nom d'émotion
KIND, STATUS, WHOSE, EMOTION = c.KIND_MAX, c.STATUS_MAX, 16, 64


#: au plus tant de valeurs dans un ``IN (…)`` écrit par la mémoire (SQLite borne les paramètres d'une requête)
IN_MAX = 500


def batches(values: Iterable[Any], size: int = IN_MAX) -> Iterator[list[Any]]:
    """Des valeurs par paquets de ``size`` au plus, dans l'ordre (un ``IN`` par paquet)."""
    got = list(values)
    for at in range(0, len(got), size):
        yield got[at:at + size]


def prefixed(column: Any, prefix: str) -> Any:
    """``column`` commence par ``prefix``, à la casse près — un intervalle (``>=`` / ``<``) plutôt qu'un ``LIKE``,
    qui ignore la casse ASCII sous SQLite et pas sous MariaDB (et qui lit l'index)."""
    return and_(column >= prefix, column < prefix[:-1] + chr(ord(prefix[-1]) + 1))


def has_table(store: Any, table: Table) -> bool:
    """La table existe-t-elle dans ``mind`` (une projection pas encore créée : la console le dit) ? Une lecture d'essai
    — ce que les facultés reçoivent du magasin ne lit que par requêtes ; ni ``sqlite_master`` ni ``information_schema``,
    qui ne sont pas les mêmes d'un moteur à l'autre."""
    try:
        store.query_mind(select(*table.primary_key.columns).limit(1))
    except DBAPIError:
        return False
    return True


def searched(column: Any, text: str) -> Any:
    """Le texte replié de ``column`` (``fold_text`` : casse et accents ignorés) contient ``text`` — la recherche de la
    console, la même sur les deux moteurs (un ``LIKE`` sur le texte brut ignore la casse ASCII sous SQLite, et pas
    sous MariaDB en collation binaire) ; ``%`` et ``_`` y sont des caractères comme les autres."""
    return column.contains(fold_text(text), autoescape=True)


def handle_key(value: str) -> str:
    """Une adresse ou un sujet tel qu'une ``Key(HANDLE_MAX)`` le range (``fit`` : telle quelle si elle tient) — à
    l'écriture comme à la lecture."""
    return fit(value, HANDLE_MAX)


def _int(name: str, *, nullable: bool = False, default: int | None = None, **kw: object) -> Column[int]:
    return Column(name, BigInteger, nullable=nullable,
                  server_default=None if default is None else str(default), **kw)  # type: ignore[arg-type]


def _text(name: str, *, nullable: bool = False, default: str | None = None) -> Column[str]:
    return Column(name, LongText, nullable=nullable, server_default=default)


@cache
def items(sfx: str = "") -> Table:
    """``memory_items`` : souvenirs, croyances, promesses, moments — une ligne par élément (``c.LEDGER_COLUMNS``,
    dans cet ordre)."""
    name = f"{c.ITEMS_TABLE}{sfx}"
    return projection_table(
        name,
        Column("id", BigInteger, primary_key=True, autoincrement=False),
        Column("kind", Key(KIND), nullable=False),
        _text("text"),
        _text("about"),
        _int("sensitivity"),
        Column("importance", Double, nullable=False),
        Column("confidence", Double),
        _text("origin", nullable=True),
        _text("source", nullable=True),
        _text("emotion", nullable=True),
        _int("born_at"),
        _int("touched_at"),
        _int("recalled_at", default=0),
        _int("recalls", default=0),
        Column("status", Key(STATUS), nullable=False),
        _int("replaces", nullable=True),
        _text("recipient", nullable=True),
        _int("due", nullable=True),
        _text("sources"),
        _text("told_by", default="[]"),
        _text("heard_by", default="[]"),
        _int("secret", default=0),
        _text("informants", default="[]"),
        _int("about_self", default=0),
        _int("shown_at", default=0),
        _int("between_us", default=0),
        _text("knowledge_kind", default="claim"),
        _text("holder", nullable=True),
        _text("constraints", default="[]"),
        _int("internal_only", default=0),
        Column("fingerprint", Key(64), nullable=False, server_default=""),
        _int("superseded_by", nullable=True),
        _int("superseded_at", nullable=True),
        _int("as_of", nullable=True),
        _int("valid_until", nullable=True),
        _text("felt", default="[]"),
        _text("empathy", default="[]"),
        _int("until", nullable=True),
        _text("precision", default=""),
        Column("likelihood", Double),
        _text("gist", default=""),
        _text("veiled", default=""),
        _int("felt_from", nullable=True),
        # le texte replié (``fold_text``), que cherche la console
        _text("folded", default=""),
        Index(f"{name}_kind", "kind", "status", "born_at"),
        Index(f"{name}_fingerprint", "fingerprint", "kind", "status"),
    )


@cache
def about(sfx: str = "") -> Table:
    """``memory_about`` : qui concerne chaque élément, une clé par ligne, indexée par personne (ADR 0059)."""
    name = f"{c.ABOUT_TABLE}{sfx}"
    return projection_table(
        name,
        Column("item", BigInteger, nullable=False),
        Column("person", Key(HANDLE_MAX), nullable=False),
        PrimaryKeyConstraint("item", "person", name=f"{name}_pk"),
        Index(f"{name}_person", "person", "item"),
    )


@cache
def refs(sfx: str = "") -> Table:
    return projection_table(
        f"{REFS_TABLE}{sfx}",
        Column("item", BigInteger, primary_key=True, autoincrement=False),
        _text("ref"),
    )


@cache
def changes(sfx: str = "") -> Table:
    name = f"{CHANGES_TABLE}{sfx}"
    return projection_table(
        name,
        Column("item", BigInteger, primary_key=True, autoincrement=False),
        _int("seq"),
        Index(f"{name}_seq", "seq"),
    )


@cache
def forgets(sfx: str = "") -> Table:
    """``memory_forgets`` : une ligne (``id`` 1), combien de fois la mémoire a oublié quelqu'un."""
    return projection_table(
        f"{c.FORGETS_TABLE}{sfx}",
        Column("id", BigInteger, primary_key=True, autoincrement=False),
        _int("n"),
    )


TESTIMONY_COLUMNS = ("item", "seq", "told_by", "informants", "origin", "confidence", "heard_by", "sensitivity",
                     "secret", "between_us", "sources", "at", "speaks", "first_hand")


@cache
def testimonies(sfx: str = "") -> Table:
    name = f"{TESTIMONIES_TABLE}{sfx}"
    return projection_table(
        name,
        Column("item", BigInteger, nullable=False),
        Column("seq", BigInteger, nullable=False),
        _text("told_by"),
        _text("informants"),
        _text("origin"),
        Column("confidence", Double, nullable=False),
        _text("heard_by"),
        _int("sensitivity"),
        _int("secret"),
        _int("between_us"),
        _text("sources"),
        _int("at"),
        _int("speaks"),
        _int("first_hand", default=0),
        PrimaryKeyConstraint("item", "seq", name=f"{name}_pk"),
    )


@cache
def contests(sfx: str = "") -> Table:
    name = f"{CONTESTS_TABLE}{sfx}"
    return projection_table(
        name,
        Column("item", BigInteger, nullable=False),
        Column("other", BigInteger, nullable=False),
        _int("at"),
        PrimaryKeyConstraint("item", "other", name=f"{name}_pk"),
    )


@cache
def feelings(sfx: str = "") -> Table:
    """``memory_feelings`` : chaque élément relié à ses émotions (ADR 0083) — « ce qui t'énerve » se cherche par
    l'émotion."""
    name = f"{c.FEELINGS_TABLE}{sfx}"
    return projection_table(
        name,
        Column("item", BigInteger, nullable=False),
        Column("whose", Key(WHOSE), nullable=False),
        Column("emotion", Key(EMOTION), nullable=False),
        Column("intensity", Double, nullable=False),
        PrimaryKeyConstraint("item", "whose", "emotion", name=f"{name}_pk"),
        Index(f"{name}_emotion", "whose", "emotion", "intensity"),
    )


@cache
def told(sfx: str = "") -> Table:
    """``memory_told`` : à qui elle a répété quoi (``veiled`` : seulement sans nommer personne, ADR 0091)."""
    name = f"{c.TOLD_TABLE}{sfx}"
    return projection_table(
        name,
        Column("item", BigInteger, nullable=False),
        Column("handle", Key(HANDLE_MAX), nullable=False),
        _int("at"),
        _int("veiled", default=0),
        PrimaryKeyConstraint("item", "handle", name=f"{name}_pk"),
    )


@cache
def told_lines(sfx: str = "") -> Table:
    """``memory_told_lines`` : chaque énoncé qui lui montrait un récit sans nom (ADR 0092)."""
    name = f"{c.TOLD_LINES_TABLE}{sfx}"
    return projection_table(
        name,
        Column("item", BigInteger, nullable=False),
        Column("handle", Key(HANDLE_MAX), nullable=False),
        Column("utterance", BigInteger, nullable=False),
        _int("at"),
        PrimaryKeyConstraint("item", "handle", "utterance", name=f"{name}_pk"),
        Index(f"{name}_handle", "handle", "at"),
    )


@cache
def deferred(sfx: str = "") -> Table:
    """``memory_extraction_queue`` : les extractions remises à plus tard."""
    name = f"{DEFERRED_TABLE}{sfx}"
    return projection_table(
        name,
        Column("key", BigInteger, primary_key=True, autoincrement=False),
        _text("messages"),
        _text("about"),
        _int("attempts"),
        _int("retry_at"),
        Column("status", Key(STATUS), nullable=False),
        _text("reason"),
        _text("detail_ref"),
        _int("since"),
        _text("aside", default="[]"),
        Index(f"{name}_due", "status", "retry_at", "key"),
    )


READING_COLUMNS = ("seq", "source", "ref", "title_ref", "excerpt_ref", "depth", "at", "asked_by")


@cache
def readings(sfx: str = "") -> Table:
    return projection_table(
        f"{READINGS_TABLE}{sfx}",
        Column("seq", BigInteger, primary_key=True, autoincrement=False),
        _text("source"),
        _text("ref"),
        _text("title_ref"),
        _text("excerpt_ref"),
        _text("depth"),
        _int("at"),
        _text("asked_by", default=""),
    )


@cache
def life(sfx: str = "") -> Table:
    """``memory_life`` : les situations et les dates durables (``payload`` : le ``LifeEvent`` en JSON) ;
    ``ordinal`` : le jour de l'année (UTC) de ``when``, pour les dates qui reviennent chaque année."""
    name = f"{c.LIFE_TABLE}{sfx}"
    return projection_table(
        name,
        Column("id", BigInteger, primary_key=True, autoincrement=False),
        _text("payload"),
        _int("when_at"),
        _int("yearly"),
        _int("ongoing"),
        _int("ended_at"),
        _int("ordinal"),
        _int("thread", default=0),
        Index(f"{name}_thread", "thread"),
        Index(f"{name}_due", "yearly", "when_at"),
        Index(f"{name}_year", "yearly", "ordinal"),
    )


__all__ = [
    "CHANGES_TABLE", "CONTESTS_TABLE", "DEFERRED_TABLE", "READINGS_TABLE", "READING_COLUMNS", "REFS_TABLE",
    "TESTIMONIES_TABLE", "TESTIMONY_COLUMNS",
    "IN_MAX", "about", "batches", "changes", "contests", "deferred", "feelings", "forgets", "handle_key", "has_table", "items", "life", "prefixed", "readings",
    "refs", "searched", "testimonies", "told", "told_lines",
]
