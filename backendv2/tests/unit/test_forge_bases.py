"""Une base par app de la Forge (ADR 0101, point 8) — sur SQLite, et sur MariaDB dans la voie ``--mariadb``.

- une app lit et écrit sa base par l'hôte : une instruction par appel, des paramètres nommés, un résultat borné ;
  une lecture ne peut pas écrire ;
- elle n'atteint rien d'autre : ni la base d'une autre app (pas même celle dont le nom ne diffère que là où « _ »
  serait un joker), ni celles de Mika ; sous SQLite, ni ``ATTACH`` ni ``VACUUM INTO`` ni ``PRAGMA`` ; sous MariaDB,
  ni tâche planifiée, ni déclencheur, ni fichier ;
- une instruction trop longue est interrompue ; une base pleine refuse ce qui l'agrandirait, jamais ce qui la vide ;
- son stockage clé/valeur est une table de sa base, qui revient si l'app la supprime ;
- vider rend une base vide ; supprimer exporte puis supprime (base et utilisateur) : recréée, l'app repart de rien ;
- son journal garde les dernières lignes, app par app.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from sqlalchemy import text

from mika.adapters.forge.bases import BaseLimits, ForgeBases, SqlRefused
from tests.fixtures import backend


@pytest.fixture
def make(tmp_path):
    made: list[ForgeBases] = []

    def build(**limits) -> ForgeBases:
        kw = {}
        if backend.active():
            kw = {"server": backend.url(), "prefix": backend.prefix(), "logs": backend.target(tmp_path, "views")}
        b = ForgeBases(tmp_path / "forge", limits=BaseLimits(**limits), **kw)
        made.append(b)
        return b

    yield build
    for b in made:
        for app in list(b._engines):
            b.drop(app, tmp_path / "corbeille" / app)
        b.close()


def _maria(b: ForgeBases) -> bool:
    return b.server is not None


def test_an_app_writes_and_reads_its_base_one_statement_at_a_time(make) -> None:
    b = make()
    auto = "INTEGER PRIMARY KEY AUTO_INCREMENT" if _maria(b) else "INTEGER PRIMARY KEY"
    b.execute("notes", f"CREATE TABLE notes (id {auto}, txt VARCHAR(200));")
    first = b.execute("notes", "INSERT INTO notes (txt) VALUES (:t)", {"t": "50 % d'avance"})
    assert first == {"rows": 1, "id": 1}
    assert b.execute("notes", "UPDATE notes SET txt = :t WHERE id = 1", {"t": "100 %"}) == {"rows": 1, "id": None}
    assert b.query("notes", "SELECT id, txt FROM notes WHERE txt LIKE '100%'") == [{"id": 1, "txt": "100 %"}]
    with pytest.raises(SqlRefused):
        b.execute("notes", "INSERT INTO notes (txt) VALUES ('a'); DROP TABLE notes")
    assert b.query("notes", "SELECT COUNT(*) AS n FROM notes") == [{"n": 1}]


def test_a_read_cannot_write(make) -> None:
    b = make()
    b.execute("notes", "CREATE TABLE notes (txt VARCHAR(20))")
    for sql in ("DELETE FROM notes", "DROP TABLE notes", "ATTACH 'x.db' AS x"):
        with pytest.raises(SqlRefused, match="lecture"):
            b.query("notes", sql)
    with pytest.raises(SqlRefused):  # une forme de lecture qui écrirait : la connexion de lecture la refuse
        b.query("notes", "WITH x AS (SELECT 1) DELETE FROM notes")
    for sql in ("SELECT 1", "DROP DATABASE x", "GRANT ALL ON *.* TO x", "SET autocommit = 0", "CREATE TRIGGER t"):
        with pytest.raises(SqlRefused, match="écriture"):
            b.execute("notes", sql)


def test_a_result_is_bounded(make) -> None:
    b = make(max_rows=3)
    b.execute("notes", "CREATE TABLE notes (n INTEGER)")
    for i in range(4):
        b.execute("notes", "INSERT INTO notes VALUES (:n)", {"n": i})
    assert len(b.query("notes", "SELECT n FROM notes LIMIT 3")) == 3
    with pytest.raises(SqlRefused, match="trop gros"):
        b.query("notes", "SELECT n FROM notes")


def test_an_app_reaches_neither_another_app_nor_her_bases(make, tmp_path) -> None:
    b = make()
    b.execute("my_app", "CREATE TABLE notes (txt VARCHAR(20))")
    b.execute("myxapp", "CREATE TABLE secret (txt VARCHAR(20))")  # « my_app » sans joker : ne la couvre pas
    b.execute("myxapp", "INSERT INTO secret VALUES ('CANARI')")
    with pytest.raises(SqlRefused):
        b.query("my_app", "SELECT * FROM secret")
    if not _maria(b):
        writer, _ = b._engines_of("my_app")
        other = b.path("myxapp")
        for sql in (f"ATTACH '{other}' AS o", f"VACUUM INTO '{tmp_path / 'copie.db'}'", "PRAGMA table_list"):
            with pytest.raises(SqlRefused):  # la forme passée de force : le contrôleur refuse
                b._run(writer, sql, {}, 0.0, rows=False)
        assert not (tmp_path / "copie.db").exists()
        return
    mind = backend.target(tmp_path, "mind")
    mind.ensure()
    engine = mind.engine(autocommit=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE events (data VARCHAR(20))"))
            conn.execute(text("INSERT INTO events VALUES ('CANARI-mind')"))
    finally:
        engine.dispose()
    writer, _ = b._engines_of("my_app")
    for sql in (f"SELECT * FROM `{mind.name}`.events", f"SELECT * FROM `{b.name('myxapp')}`.secret",
                "CREATE EVENT e ON SCHEDULE EVERY 1 HOUR DO DELETE FROM notes",
                "CREATE TRIGGER t BEFORE INSERT ON notes FOR EACH ROW SET NEW.txt = 'x'",
                "SELECT * FROM notes INTO OUTFILE '/tmp/forge-canari'", "CREATE DATABASE `mika_test_evil`"):
        with pytest.raises(SqlRefused):  # la forme passée de force : les droits du serveur refusent
            b._run(writer, sql, {}, 0.0, rows=True)


def test_a_statement_past_its_time_is_interrupted(make) -> None:
    b = make(statement_s=1.0)
    started = time.monotonic()
    slow = "SELECT SLEEP(5)" if _maria(b) else \
        "WITH RECURSIVE c(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM c) SELECT COUNT(*) FROM c"
    with pytest.raises(SqlRefused):
        b.query("lente", slow)
    assert time.monotonic() - started < 4


def test_a_full_base_refuses_to_grow_and_lets_itself_be_emptied(make) -> None:
    b = make(max_bytes=150_000)
    b.execute("plein", "CREATE TABLE big (x LONGTEXT)" if _maria(b) else "CREATE TABLE big (x TEXT)")
    with pytest.raises(SqlRefused, match="pleine"):  # au plus le double du plafond : la mesure suit ce qui entre
        for _ in range(5):
            b.execute("plein", "INSERT INTO big VALUES (:x)", {"x": "y" * 60_000})
            b._sizes.clear()  # sans attendre que la mesure vieillisse
    with pytest.raises(ValueError, match="pleine"):
        b.kv_set("plein", "clé", "valeur")
    assert b.execute("plein", "DELETE FROM big")["rows"] > 0
    b.execute("plein", "DROP TABLE big")


def test_the_key_value_store_is_a_table_of_her_base(make) -> None:
    b = make()
    b.kv_set("kv", "a/1", {"x": 1})
    b.kv_set("kv", "A/2", 2)
    assert b.kv_get("kv", "a/1") == {"x": 1} and b.kv_get("kv", "absente", "défaut") == "défaut"
    assert b.kv_keys("kv", "a/") == ["a/1"]  # la casse compte, sur les deux moteurs
    assert b.query("kv", "SELECT COUNT(*) AS n FROM _kv") == [{"n": 2}]
    b.kv_delete("kv", "a/1")
    assert b.kv_keys("kv") == ["A/2"]
    b.execute("kv", "DROP TABLE _kv")
    assert b.kv_get("kv", "A/2") is None  # revenue, vide
    b.kv_set("kv", "b", True)
    assert b.kv_keys("kv") == ["b"]


def test_reset_empties_and_drop_exports_then_forgets(make, tmp_path) -> None:
    b = make()
    b.execute("vie", "CREATE TABLE notes (txt VARCHAR(20))")
    b.execute("vie", "INSERT INTO notes VALUES ('gardée')")
    b.kv_set("vie", "k", 1)
    assert b.reset("vie") == 2
    assert [t["name"] for t in b.schema("vie")["tables"]] == ["_kv"]
    b.execute("vie", "CREATE TABLE notes (txt VARCHAR(20))")
    b.execute("vie", "INSERT INTO notes VALUES ('exportée')")
    dumped = b.drop("vie", tmp_path / "corbeille" / "vie-1")
    assert dumped is not None and dumped.exists()
    if _maria(b):
        data = json.loads(dumped.read_text())
        assert data["tables"]["notes"]["rows"] == [{"txt": "exportée"}]
        assert "CREATE TABLE" in data["tables"]["notes"]["create"]
    else:
        assert "exportée".encode() in dumped.read_bytes() and not b.path("vie").exists()
    assert [t["name"] for t in b.schema("vie")["tables"]] == ["_kv"]  # recréée : rien de l'ancienne


def test_the_schema_says_the_engine_tables_rows_and_size(make) -> None:
    b = make()
    b.execute("vue", "CREATE TABLE notes (id INTEGER PRIMARY KEY, txt VARCHAR(20))")
    b.execute("vue", "INSERT INTO notes (id, txt) VALUES (1, 'a')")
    b.execute("vue", "CREATE VIEW recent AS SELECT txt FROM notes")
    got = b.schema("vue")
    assert got["engine"] == ("mariadb" if _maria(b) else "sqlite") and got["size"] > 0 and got["max"] > 0
    notes = next(t for t in got["tables"] if t["name"] == "notes")
    assert notes["rows"] == 1 and [c["name"] for c in notes["columns"]] == ["id", "txt"]
    assert notes["columns"][0]["key"] and got["views"] == ["recent"]


def test_logs_keep_the_last_lines_app_by_app(make) -> None:
    b = make()
    for i in range(6):
        b.log("une", f"ligne {i}", keep=3)
    b.log("autre", "seule", keep=3)
    assert b.logs("une") == ["ligne 3", "ligne 4", "ligne 5"] and b.logs("une", 2) == ["ligne 4", "ligne 5"]
    assert b.logs("autre") == ["seule"]


def test_a_name_is_checked_before_anything(make) -> None:
    b = make()
    for bad in ("A", "1app", "app-x", "a" * 40, "x;drop"):
        with pytest.raises(SqlRefused):
            b.name(bad)
    assert not Path(b.root / "_bases").exists() or not any(Path(b.root / "_bases").glob("*;*"))
