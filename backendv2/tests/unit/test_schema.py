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


# ── une base d'avant, marquée à jour sans l'être (audit du 2026-10-26) ──────────────────────────────────────────


def _droppable(meta, *, nullable: bool):
    """Une colonne qu'on peut retirer sous SQLite (ni clé, ni indexée, ni étrangère, sans défaut) : la base
    d'une version d'avant des entités."""
    for table in meta.sorted_tables:
        indexed = {c.name for i in table.indexes for c in i.columns}
        for c in table.constraints:
            if isinstance(c, UniqueConstraint):
                indexed |= {col.name for col in c.columns}
        for col in table.columns:
            if col.primary_key or col.name in indexed or col.foreign_keys or col.default is not None \
                    or col.server_default is not None:
                continue
            if col.nullable == nullable:
                return table, col
    return None


def _drop(engine, table, column) -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql(f'ALTER TABLE "{table.name}" DROP COLUMN "{column.name}"')


@pytest.mark.sqlite_only
def test_a_base_from_older_entities_gets_its_missing_columns(tmp_path) -> None:
    """Née des entités d'avant (une colonne de moins), jamais marquée : marquée, puis complétée — jamais marquée à
    jour sans l'être."""
    found = _droppable(MIND, nullable=True)
    assert found, "aucune colonne facultative à retirer pour le test"
    table, column = found
    engine = _engine(tmp_path, "mind")
    try:
        MIND.create_all(engine)
        _drop(engine, table, column)
        schema.migrate_data(tmp_path)
        assert schema.differences("mind", engine) == []
        assert column.name in {c["name"] for c in inspect(engine).get_columns(table.name)}
    finally:
        engine.dispose()


@pytest.mark.sqlite_only
def test_a_base_already_marked_but_incomplete_is_completed_too(tmp_path) -> None:
    """Le cas de ``data/v2`` : marquée à la dernière révision avec une table d'avant — le démarrage suivant la
    complète."""
    table, column = _droppable(MIND, nullable=True)
    schema.migrate_data(tmp_path)
    engine = _engine(tmp_path, "mind")
    try:
        _drop(engine, table, column)
        assert schema.differences("mind", engine) != []
        schema.migrate_data(tmp_path)
        assert schema.differences("mind", engine) == []
    finally:
        engine.dispose()


@pytest.mark.sqlite_only
def test_a_drift_that_cannot_be_repaired_refuses_to_start(tmp_path) -> None:
    """Ce qu'on ne sait pas compléter seul (ici une colonne en trop, d'une version d'avant qui en avait une de
    plus) : la base est refusée en nommant la différence, plutôt que marquée à jour."""
    table = MIND.sorted_tables[0]
    schema.migrate_data(tmp_path)
    engine = _engine(tmp_path, "mind")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'ALTER TABLE "{table.name}" ADD COLUMN surplus_d_avant TEXT')
        with pytest.raises(schema.SchemaDrift) as caught:
            schema.migrate_data(tmp_path)
        assert f"{table.name}.surplus_d_avant" in str(caught.value)
    finally:
        engine.dispose()
