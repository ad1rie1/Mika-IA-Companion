"""Les tables et la porte de la mémoire, déclarées pour les deux moteurs (ADR 0101).

Ce que SQLite laisse passer et que MariaDB lirait autrement, épinglé ici sur SQLite : les vues ont les colonnes que
leur contrat déclare (les autres facultés les lisent par des requêtes) ; aucune clé n'est un texte sans borne ; une
clé démesurée est ramenée à sa borne plutôt que de faire échouer l'ajout ; « cette liste contient ce sujet » est une
égalité exacte (le ``LIKE`` d'avant prenait le ``_`` d'une adresse pour un joker) ; nommé une fois, nommé pour de bon,
même dans un seul lot ; le jour de l'année d'un moment, en UTC ; la recherche de la console, pareille sur les deux
moteurs (casse et accents ignorés).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import Float, Integer, inspect, select

from mika.contracts import memory as mc
from mika.contracts import runtime as rt
from mika.faculties.memory import tables as tb
from mika.faculties.memory.archive import LifeArchive
from mika.faculties.memory.night import joinable_pairs
from mika.faculties.memory.projections import ITEM_COLUMNS, Chunks, ExtractionQueue, Items, Readings, Told
from mika.kernel.clock import DAY
from mika.kernel.events import Content, VoiceProvenance
from mika.ports.sql import HANDLE_MAX, PROJECTIONS, Key
from tests.fixtures.sqldb import SqlDB
from tests.unit.test_audit_regressions import event

ALICE, BOB = "user_2", "user_3"


class DB(SqlDB):
    def __init__(self) -> None:
        super().__init__()
        for cls in (Items, Chunks, Told, ExtractionQueue, Readings, LifeArchive):
            cls().create(self, "")


def believed(text: str, about: tuple[str, ...], told_by: tuple[str, ...] = ()) -> object:
    return mc.BELIEVED.draft(text=Content.of(text, level=1), about=about, told_by=told_by, sensitivity=1)


def said_to(target: str, *provenance: str) -> object:
    return rt.UTTERANCE.draft(kind="REPLY", text=Content.of("…"), target=target, visible=True,
                              voice=VoiceProvenance(call_id="t", persona_hash="h", role="reply", model="m"),
                              provenance=provenance)


# ── la porte ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("view", [mc.KNOWLEDGE, mc.KNOWLEDGE_ABOUT, mc.FORMER, mc.RETOLD, mc.SELF_CHANGES, mc.LIVED,
                                  mc.LEDGER, mc.FEELINGS], ids=lambda v: v.name)
def test_each_view_has_the_columns_its_contract_declares(view):
    """Les autres facultés lisent la porte par ``view_table`` : une colonne déclarée que la vue n'a pas, ou dans un
    autre ordre, ne se verrait qu'à la première lecture."""
    db = DB()
    found = [col["name"] for col in inspect(db.conn).get_columns(view.name)]
    assert found == [col.name for col in view.c]


def test_the_ledger_is_every_column_of_an_item_and_the_door_reads_by_queries():
    assert [col.name for col in tb.items().c] == list(mc.LEDGER_COLUMNS)
    # les colonnes de la porte ont les types de la table : un texte, une clé bornée, un entier, un réel
    for view in (mc.LEDGER, mc.KNOWLEDGE, mc.FORMER, mc.LIVED):
        for col in view.c:
            kept = tb.items().c[col.name].type
            assert type(col.type) is type(kept) and getattr(col.type, "length", None) == getattr(kept, "length", None), \
                (view.name, col.name)
    assert set(ITEM_COLUMNS) <= set(mc.LEDGER_COLUMNS) and set(mc.KNOWN_COLUMNS) <= set(ITEM_COLUMNS)
    db = DB()
    Items().apply(db, [event(believed("Alice aime le jazz", (ALICE,), (ALICE,)), 5)], "")
    rows = db.query(mc.select_known().where(mc.concerning(mc.KNOWLEDGE, [ALICE])))
    assert [r[mc.KNOWN_COLUMNS.index("text")] for r in rows] == ["Alice aime le jazz"]
    assert db.query(mc.select_known().where(mc.concerning(mc.KNOWLEDGE, [BOB]))) == []


# ── les tables ───────────────────────────────────────────────────────────


def _memory_tables() -> list:
    return [t for t in PROJECTIONS.tables.values() if t.name.startswith("memory_")]


def test_every_key_is_bounded_and_every_index_fits_mariadb():
    """Une clé ou une colonne indexée est une ``Key`` (MariaDB n'indexe pas un ``LONGTEXT``) ; un index est nommé
    d'après sa table, en 64 caractères au plus, et ne dépasse pas 768 caractères (3 072 octets en utf8mb4)."""
    DB()  # les tables sont déclarées en les créant
    tables = _memory_tables()
    assert {t.name for t in tables} >= {mc.ITEMS_TABLE, mc.ABOUT_TABLE, mc.CHUNKS_TABLE, mc.TOLD_TABLE,
                                        mc.TOLD_LINES_TABLE, mc.LIFE_TABLE, mc.FEELINGS_TABLE, tb.DEFERRED_TABLE,
                                        tb.READINGS_TABLE, tb.TESTIMONIES_TABLE}
    for table in tables:
        keyed = [list(table.primary_key.columns), *(list(ix.columns) for ix in table.indexes)]
        for columns in keyed:
            assert all(isinstance(col.type, (Key, Integer, Float)) for col in columns), \
                (table.name, [col.name for col in columns])
            assert all(col.type.length for col in columns if isinstance(col.type, Key))
            assert sum(col.type.length if isinstance(col.type, Key) else 8 for col in columns) <= 768, table.name
        for ix in table.indexes:
            assert ix.name.startswith(table.name) and len(ix.name) <= 64, ix.name


def test_a_mention_too_long_for_its_key_is_kept_and_forgotten_by_its_bound():
    """Un « nom » démesuré venu d'une extraction : l'élément entre quand même (la clé est ramenée à sa borne), et
    l'oubli de ce sujet l'atteint."""
    huge = "name:" + "x" * (HANDLE_MAX + 100)
    db = DB()
    Items().apply(db, [event(believed("quelqu'un aime le jazz", (huge,)), 5)], "")
    about = tb.about()
    (person,) = db.query(select(about.c.person))[0]
    assert len(person) == HANDLE_MAX and person == tb.handle_key(huge)
    Items().forget(db, huge, "")
    assert db.query(select(tb.items().c.id)) == []


def test_forgetting_a_subject_is_an_exact_match_not_a_pattern():
    """``user_7`` n'est pas ``userX7`` (le ``_`` d'un ``LIKE``), ni ``User_7`` : l'oubli de l'un ne touche pas ce que
    l'autre a confié."""
    db = DB()
    Items().apply(db, [event(believed("Sam a un vélo rouge", ("name:sam",), ("userX7",)), 5),
                       event(believed("Sam aime la pluie", ("name:sam",), ("User_7",)), 6),
                       event(believed("Sam a un chien", ("name:sam",), ("user_7",)), 7)], "")
    Items().forget(db, "user_7", "")
    t = tb.items()
    assert [r[0] for r in db.query(select(t.c.id).order_by(t.c.id))] == [5, 6]


def test_named_once_stays_named_even_within_one_batch():
    """Un récit sans nom puis nommé dans le même lot, ou l'inverse : il reste nommé (``veiled`` 0) et date de la
    dernière fois — sans « ON CONFLICT … MIN(…) », lu puis écrit."""
    db = DB()
    told = tb.told()
    Told().apply(db, [event(said_to(BOB, "veiled:5"), 50, DAY), event(said_to(BOB, "memory:5"), 51, 2 * DAY)], "")
    Told().apply(db, [event(said_to(BOB, "memory:6"), 52, 3 * DAY), event(said_to(BOB, "veiled:6"), 53, 4 * DAY)], "")
    Told().apply(db, [event(said_to(BOB, "veiled:6"), 54, 5 * DAY)], "")
    rows = db.query(select(told.c.item, told.c.at, told.c.veiled).order_by(told.c.item))
    assert rows == [(5, 2 * DAY, 0), (6, 5 * DAY, 0)]


def test_a_moment_knows_its_day_of_the_year_in_utc():
    """Le jour de l'année d'un moment (les dates qui reviennent chaque année le cherchent) : en UTC, calculé ici — le
    ``strftime('%j', …, 'unixepoch')`` d'avant n'existe pas sous MariaDB."""
    db = DB()
    when = int(datetime(2026, 12, 31, 23, 30, tzinfo=UTC).timestamp() * 1_000_000)
    LifeArchive().apply(db, [event(mc.EVENT_NOTED.draft(text=Content.of("son anniversaire", level=1), when=when,
                                                        about=(ALICE,), yearly=True), 7)], "")
    life = tb.life()
    assert db.query(select(life.c.ordinal, life.c.when_at)) == [(365, when)]
    assert json.loads(db.query(select(life.c.payload))[0][0])["id"] == 7


def test_the_console_search_ignores_case_and_accents_on_both_engines():
    db = DB()
    Items().apply(db, [event(believed("Élodie adore le café", ("name:elodie",)), 5),
                       event(believed("100% d'accord_avec lui", ("name:sam",)), 6)], "")
    t = tb.items()
    assert db.query(select(t.c.id).where(tb.searched(t.c.folded, "ELODIE ADORE"))) == [(5,)]
    assert db.query(select(t.c.id).where(tb.searched(t.c.folded, "% d'accord_"))) == [(6,)]
    assert db.query(select(t.c.id).where(tb.searched(t.c.folded, "d_accord"))) == []  # ``_`` n'est pas un joker


def test_the_same_words_on_other_people_are_not_joined_at_night():
    """La nuit joint la même croyance notée deux fois — sur les mêmes personnes seulement : la base ne groupe que par
    l'empreinte, les listes se comparent entières en Python (MariaDB ne grouperait un texte que par son début)."""
    db = DB()
    Items().apply(db, [event(believed("aime le jazz", (ALICE,), (ALICE,)), 5),
                       event(believed("aime le jazz", (BOB,), (BOB,)), 6),
                       event(believed("aime le jazz", (ALICE,), (BOB,)), 7)], "")
    assert joinable_pairs(db, type("P", (), {"night_max_joins": 10})()) == ((5, 7),)


def test_a_projection_not_yet_created_is_said_not_raised():
    db = SqlDB()
    assert not tb.has_table(db, tb.items())
    Items().create(db, "")
    assert tb.has_table(db, tb.items())
