"""Les requêtes préparées (``mika.ports.sql.Prepared``) : compilées une fois par moteur, exécutées au curseur du pilote.

- une liste (``IN``) se déplie, une liste vide ne trouve rien ;
- les valeurs écrites dans la requête (``== "pending"``, ``limit(1)``) n'ont pas à être données ;
- une insertion en lot passe, et une valeur trop longue pour sa ``Key`` y est refusée comme ailleurs ;
- le SQL compilé pour MariaDB a la même forme (paramètres ``?``, la liste à déplier).
"""

from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, bindparam, insert, select
from sqlalchemy.dialects.mysql.mariadb import loader

from mika.ports.sql import Key, KeyTooLong, LongText, Prepared, projection_table
from tests.fixtures.sqldb import SqlDB

T = projection_table("probe_prepared", Column("id", Integer, primary_key=True, autoincrement=False),
                     Column("tag", Key(8), nullable=False), Column("text", LongText, nullable=False))
INSERT = Prepared(insert(T), columns=("id", "tag", "text"))
BY_IDS = Prepared(select(T.c.id, T.c.text).where(T.c.id.in_(bindparam("ids", expanding=True)), T.c.tag == "a")
                  .order_by(T.c.id).limit(2))


@pytest.fixture
def db():
    db = SqlDB()
    db.create(T)
    db.execute(INSERT, [{"id": i, "tag": "a" if i % 2 else "b", "text": f"t{i}"} for i in range(1, 8)])
    yield db
    db.close()


def test_a_list_unfolds_and_the_fixed_values_need_not_be_given(db) -> None:
    assert db.query(BY_IDS, {"ids": [1, 2, 3, 5, 7]}) == [(1, "t1"), (3, "t3")]  # tag « a », deux au plus


def test_an_empty_list_finds_nothing(db) -> None:
    assert db.query(BY_IDS, {"ids": []}) == []


def test_a_batch_insert_checks_the_bounds_of_its_keys(db) -> None:
    with pytest.raises(KeyTooLong):
        db.execute(INSERT, [{"id": 20, "tag": "ok", "text": ""}, {"id": 21, "tag": "beaucoup trop long", "text": ""}])
    with pytest.raises(KeyTooLong):
        db.execute(INSERT, {"id": 22, "tag": "beaucoup trop long", "text": ""})


def test_the_mariadb_form_is_the_same() -> None:
    dialect = loader("mariadbconnector").__new__(loader("mariadbconnector"))
    dialect.__init__()
    sql, names, expanding, fixed = BY_IDS._sql(dialect)
    assert "?" in sql and "__[POSTCOMPILE_ids]" in sql and "LIMIT" in sql
    assert expanding == {"ids"} and "ids" in names and set(fixed.values()) >= {"a"}
