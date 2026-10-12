"""Le schéma déclaré (ADR 0101).

- chaque base passe à sa dernière révision et n'y diffère pas de ses entités : une entité changée sans révision
  échoue ici (l'équivalent d'``alembic check``) ; migrer deux fois ne change rien ;
- une base née de ses entités (``create`` : les tests, le simulateur), même en partie, est complétée puis marquée ;
- chaque table déclarée se crée sous MariaDB : InnoDB et collation binaire, toute clé ou colonne indexée est une
  ``Key`` bornée, un index tient dans les 3 072 octets d'InnoDB (768 caractères utf8mb4), un nom dans 64 caractères.
"""

from __future__ import annotations

import pytest
from sqlalchemy import String, UniqueConstraint, inspect
from sqlalchemy.dialects.mysql.mariadb import MariaDBDialect
from sqlalchemy.schema import CreateIndex, CreateTable

from mika.adapters.database import sqlite_engine
from mika.app import schema
from mika.ports.sql import DATABASES, MIND, TABLE_OPTIONS, Key
from tests.fixtures import backend

schema.load_models()
TABLES = [table for meta in DATABASES.values() for table in meta.sorted_tables]


def _engine(tmp_path, name):
    return sqlite_engine(tmp_path / schema.FILES[name])


def test_every_base_has_a_file_and_entities() -> None:
    assert set(schema.FILES) == set(DATABASES)
    assert all(DATABASES[name].tables for name in DATABASES)


@pytest.mark.sqlite_only  # les fichiers d'un dossier ; sur un serveur : la variante « on_mariadb »
@pytest.mark.parametrize("name", sorted(schema.FILES))
def test_each_base_reaches_its_last_revision_without_drift(tmp_path, name) -> None:
    schema.migrate_data(tmp_path)
    schema.migrate_data(tmp_path)  # deux fois : rien ne change
    engine = _engine(tmp_path, name)
    try:
        assert schema.differences(name, engine) == []
        with engine.connect() as conn:
            assert len(conn.exec_driver_sql("SELECT version_num FROM alembic_version").fetchall()) == 1
            assert set(DATABASES[name].tables) <= set(inspect(conn).get_table_names())
    finally:
        engine.dispose()


@pytest.mark.sqlite_only  # les fichiers d'un dossier ; sur un serveur : la variante « on_mariadb »
def test_a_base_born_of_its_entities_is_completed_and_marked(tmp_path) -> None:
    engine = _engine(tmp_path, "mind")
    try:
        first = MIND.sorted_tables[0]
        MIND.create_all(engine, tables=[first])  # en partie seulement
        schema.migrate_data(tmp_path)
        assert schema.differences("mind", engine) == []
        with engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT version_num FROM alembic_version").fetchall()
    finally:
        engine.dispose()


@pytest.mark.parametrize("table", TABLES, ids=lambda t: t.name)
def test_every_table_carries_the_mariadb_options(table) -> None:
    options = {f"mariadb_{k}": v for k, v in table.dialect_options["mariadb"].items() if f"mariadb_{k}" in TABLE_OPTIONS}
    assert options == TABLE_OPTIONS


@pytest.mark.parametrize("table", TABLES, ids=lambda t: t.name)
def test_keys_and_indexes_hold_under_mariadb(table) -> None:
    keyed = [list(table.primary_key.columns)] + [list(i.columns) for i in table.indexes] + \
        [list(c.columns) for c in table.constraints if isinstance(c, UniqueConstraint)]
    for columns in keyed:
        for column in columns:
            if isinstance(column.type, String):
                assert isinstance(column.type, Key) and column.type.length, f"{table.name}.{column.name} : une Key"
        assert sum(c.type.length for c in columns if isinstance(c.type, Key)) <= 768, \
            f"{table.name} : un index au-delà de 768 caractères ({[c.name for c in columns]})"
    names = [table.name, *(i.name for i in table.indexes), *(c.name for c in table.constraints if c.name)]
    assert all(len(str(n)) <= 64 for n in names), names


@pytest.mark.parametrize("table", TABLES, ids=lambda t: t.name)
def test_every_table_compiles_for_mariadb(table) -> None:
    dialect = MariaDBDialect()
    ddl = str(CreateTable(table).compile(dialect=dialect))
    assert "ENGINE=InnoDB" in ddl and "utf8mb4_nopad_bin" in ddl
    assert " TEXT" not in ddl and " BLOB" not in ddl.replace("LONGBLOB", "")  # 64 Ko : jamais assez
    for index in table.indexes:
        str(CreateIndex(index).compile(dialect=dialect))


@pytest.mark.parametrize("name", sorted(schema.FILES))
def test_each_base_reaches_its_last_revision_on_mariadb(tmp_path, name) -> None:
    """La même chose sur un serveur MariaDB (``--mariadb``) : les révisions d'Alembic y créent exactement les entités."""
    if not backend.active():
        pytest.skip("la voie MariaDB (--mariadb)")
    where = {n: backend.target(tmp_path, n) for n in schema.FILES}
    schema.migrate_data(tmp_path, where)
    schema.migrate_data(tmp_path, where)  # deux fois : rien ne change
    engine = where[name].engine()
    try:
        assert schema.differences(name, engine) == []
        with engine.connect() as conn:
            assert set(DATABASES[name].tables) <= set(inspect(conn).get_table_names())
            collations = {r[0] for r in conn.exec_driver_sql(
                "SELECT DISTINCT table_collation FROM information_schema.tables WHERE table_schema = DATABASE() "
                "AND table_name <> 'alembic_version'")}
            assert collations == {"utf8mb4_nopad_bin"}
    finally:
        engine.dispose()
