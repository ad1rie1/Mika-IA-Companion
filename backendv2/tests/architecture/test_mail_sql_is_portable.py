"""Une politique : le SQL du courrier se lit pareil sous SQLite (les tests) et sous MariaDB (sa vie) — ADR 0101.

- **aucune construction propre à SQLite écrite en clair** dans le paquet ``adapters/mail`` : ni ``INSERT OR`` /
  ``UPDATE OR``, ni ``ON CONFLICT``, ni ``json_each`` / ``json_extract``, ni ``||`` (un OU logique sous MariaDB), ni
  ``rowid``, ``PRAGMA``, ``sqlite_master``, ``WITHOUT ROWID``, ni ``ESCAPE`` écrit à la main, ni ``MAX(a, b)`` à deux
  arguments ; pas de ``sqlite3``, pas de fonction Python appelée depuis le SQL (``create_function``), pas de SQL
  passé tel quel (``text``, ``exec_driver_sql``, ``executescript``) ;
- **un schéma que MariaDB accepte** : chaque colonne de texte est une ``Key(n)`` (une clé, un index) ou un
  ``LongText`` ; chaque index est nommé (64 caractères au plus) et tient en 3 072 octets (768 caractères utf8mb4).

Le contrôle porte sur l'arbre du code (``ast``) — les noms et les chaînes, docstrings exceptées —, jamais sur le
texte du fichier : les commentaires nomment justement ce qu'il ne faut pas faire.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import BigInteger, Boolean, Integer, LargeBinary, String, Text

import mika.adapters.mail.models  # noqa: F401  (les tables s'inscrivent dans MAIL)
from mika.ports.sql import MAIL, Key

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "mika" / "adapters" / "mail"

FORBIDDEN = re.compile(
    r"\bINSERT\s+OR\b|\bUPDATE\s+OR\b|\bREPLACE\s+INTO\b|\bON\s+CONFLICT\b|\bjson_each\b|\bjson_extract\b|\|\|"
    r"|\browid\b|\bPRAGMA\b|\bsqlite_master\b|\bWITHOUT\s+ROWID\b|\bESCAPE\b|\b(?:MAX|MIN)\s*\([^()]*,",
    re.IGNORECASE)
#: ce qui passerait du SQL au pilote sans SQLAlchemy, ou appellerait Python depuis le SQL
RAW_CALLS = frozenset({"text", "literal_column", "exec_driver_sql", "executescript", "create_function",
                       "create_aggregate", "executemany"})


def _modules() -> list[Path]:
    return sorted(p for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts)


def _docstrings(tree: ast.AST) -> set[int]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                out.add(id(first.value))
    return out


def _strings(tree: ast.AST) -> Iterator[tuple[int, str]]:
    """Chaque chaîne du module (morceaux fixes des f-strings compris, docstrings non)."""
    docs = _docstrings(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            yield node.lineno, node.value


def _called(node: ast.Call) -> str:
    return node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")


def test_the_mail_package_writes_no_sqlite_only_sql():
    found = []
    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(ROOT)
        found += [f"{rel}:{line} : {text!r}" for line, text in _strings(tree) if FORBIDDEN.search(text)]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                names = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) else [])
                found += [f"{rel}:{node.lineno} : import {n}" for n in names if n and n.split(".")[0] == "sqlite3"]
            elif isinstance(node, ast.Call):
                name = _called(node)
                if name in RAW_CALLS:
                    found.append(f"{rel}:{node.lineno} : {name}(…)")
                # ``func.max(a, b)`` : un agrégat sous MariaDB, pas le plus grand des deux (``greatest``)
                if name in ("max", "min") and isinstance(node.func, ast.Attribute) and \
                        getattr(node.func.value, "id", "") == "func" and len(node.args) > 1:
                    found.append(f"{rel}:{node.lineno} : func.{name} à {len(node.args)} arguments")
    assert not found, "du SQL propre à SQLite dans le courrier :\n" + "\n".join(found)


def test_the_check_sees_what_it_looks_for():
    tree = ast.parse('"""rowid, json_each : une docstring en parle."""\n'
                     'q = f"INSERT OR IGNORE INTO t SELECT a || b, MAX(x, y) FROM json_each({v}) WHERE rowid=1"\n'
                     'db.create_function("fold", 1, f)\n')
    texts = [t for _, t in _strings(tree)]
    # les deux morceaux fixes de la f-string sont vus ; la docstring ne compte pas
    assert [t for t in texts if FORBIDDEN.search(t)] == [
        "INSERT OR IGNORE INTO t SELECT a || b, MAX(x, y) FROM json_each(", ") WHERE rowid=1"]
    assert texts[-1] == "fold"
    for bad in ("INSERT OR REPLACE", "UPDATE OR REPLACE", "ON CONFLICT(x) DO", "a || b", "x.rowid", "PRAGMA x",
                "max(a, b)", "LIKE ? ESCAPE '\\'", "json_extract(j.value,'$[1]')", "sqlite_master"):
        assert FORBIDDEN.search(bad), bad
    for good in ("max(x)", "INSERT INTO", "ordre", "role"):
        assert not FORBIDDEN.search(good), good
    assert [_called(n) for n in ast.walk(tree) if isinstance(n, ast.Call)] == ["create_function"]


def _width(column) -> int:
    """La place d'une colonne dans une clé d'index InnoDB, en octets (utf8mb4 : 4 octets par caractère)."""
    kind = column.type
    if isinstance(kind, Key):
        return 4 * kind.length
    assert isinstance(kind, BigInteger | Integer | Boolean), f"{column} : indexé, mais ni Key ni entier"
    return 8


def test_the_mail_schema_fits_mariadb():
    assert MAIL.tables, "aucune table déclarée"
    for table in MAIL.tables.values():
        for column in table.columns:
            kind = column.type
            if isinstance(kind, String) and not isinstance(kind, Key):
                assert isinstance(kind, Text), f"{table.name}.{column.name} : un texte ni Key ni LongText"
            if isinstance(kind, Key):
                assert kind.length, f"{table.name}.{column.name} : une Key sans borne"
            assert not isinstance(kind, LargeBinary) or column.name == "source", f"{table.name}.{column.name}"
        keys = [(f"index {ix.name}", list(ix.columns)) for ix in table.indexes]
        keys += [(f"contrainte {c.name}", list(c.columns)) for c in table.constraints if list(c.columns)]
        for what, columns in keys:
            name = what.split(" ", 1)[1]
            assert name and name != "None" and len(name) <= 64, f"{table.name} : {what} sans nom court"
            assert sum(_width(c) for c in columns) <= 3072, f"{table.name} : {what} trop large pour InnoDB"
