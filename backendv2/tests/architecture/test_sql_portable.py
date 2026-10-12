"""Le SQL des modules passés aux entités ne dit rien que MariaDB lirait autrement (ADR 0101).

Le SQL écrit en clair de ces modules est relu par l'AST (chaînes, f-chaînes et concaténations ; jamais les
docstrings ni les commentaires, qui nomment justement ce qu'il ne faut pas faire) ; aucune fonction Python n'est
enregistrée dans un moteur. Tout ``src`` y passe, sauf les exceptions nommées (``EXEMPT``) et leur raison.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "mika"

#: ce qui reste hors de la règle, et pourquoi (le lot qui le reprend)
EXEMPT = {
    "adapters/database.py": "le seul module qui parle de SQLite par nature (sa mise en route, la troncature du WAL)",
    "adapters/forge/__init__.py": "la Forge : lot 4 (une base par app)",
    "app/backup.py": "la sauvegarde : lot 5",
}

#: tout ``src`` (les révisions générées d'Alembic à part), sauf ``EXEMPT``
PORTED = sorted(
    rel for rel in (str(p.relative_to(SRC)) for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)
    if not rel.startswith("app/migrations/") and rel not in EXEMPT
)
PORTED = list(dict.fromkeys(PORTED))  # un module nommé deux fois (à la main, puis par son paquet) : relu une fois

_SQL = re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|WITH|REPLACE|PRAGMA|ALTER|DROP)\b", re.I)
FORBIDDEN = {
    "INSERT OR / UPDATE OR": re.compile(r"\b(INSERT|UPDATE)\s+OR\b", re.I),
    "ON CONFLICT": re.compile(r"\bON\s+CONFLICT\b", re.I),
    "json_each / json_extract": re.compile(r"\bjson_(each|extract)\b", re.I),
    "|| (un OU sous MariaDB)": re.compile(r"\|\|"),
    "rowid": re.compile(r"\browid\b", re.I),
    "PRAGMA": re.compile(r"\bPRAGMA\b", re.I),
    "sqlite_master": re.compile(r"\bsqlite_master\b", re.I),
    "WITHOUT ROWID": re.compile(r"\bWITHOUT\s+ROWID\b", re.I),
    "MAX/MIN(a, b)": re.compile(r"\b(MAX|MIN)\s*\([^()]*,[^()]*\)", re.I),
    "LIMIT -1": re.compile(r"\bLIMIT\s+-1\b", re.I),
    "strftime / unixepoch / julianday": re.compile(r"\b(strftime|unixepoch|julianday)\s*\(", re.I),
    "total() (SQLite)": re.compile(r"\btotal\s*\(", re.I),
}


def _docstrings(tree: ast.AST) -> set[int]:
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                out.add(id(first.value))
    return out


def _text(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _text(node.left), _text(node.right)
        return (left or "") + (right or "") if left is not None or right is not None else None
    return None


def sql_strings(source: str) -> list[tuple[int, str]]:
    tree = ast.parse(source)
    skip = _docstrings(tree)
    out = []
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        text = _text(node)
        if text and _SQL.match(text):
            out.append((getattr(node, "lineno", 0), text))
    return out


def registered_functions(source: str) -> list[int]:
    return [n.lineno for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr in {"create_function", "create_aggregate", "create_collation"}]


def offences(source: str) -> list[str]:
    found = [f"ligne {line} : {name} — {text[:80]!r}" for line, text in sql_strings(source)
             for name, rx in FORBIDDEN.items() if rx.search(text)]
    found += [f"ligne {line} : une fonction Python dans le moteur" for line in registered_functions(source)]
    return found


@pytest.mark.parametrize("path", PORTED)
def test_the_sql_of_a_ported_module_is_portable(path: str) -> None:
    assert offences((SRC / path).read_text(encoding="utf-8")) == []


def test_the_checker_sees_what_it_must_and_spares_the_prose() -> None:
    bad = '''
"""Jamais INSERT OR REPLACE, ni rowid, ni || : une docstring le dit."""
A = "INSERT OR REPLACE INTO t(a) VALUES(?)"
B = f"SELECT a || b FROM {T} WHERE rowid=?"
C = "SELECT MAX(a, b) FROM t"
db.create_function("fold", 1, f)
'''
    found = offences(bad)
    assert any("INSERT OR" in f for f in found) and any("||" in f for f in found)
    assert any("rowid" in f for f in found) and any("MAX/MIN" in f for f in found)
    assert any("fonction Python" in f for f in found)
    assert not any("ligne 2" in f for f in found)  # la docstring
    assert offences('X = "SELECT MAX(at) FROM t"\nY = "le rowid, en prose"') == []


def test_every_exemption_names_a_real_module() -> None:
    assert all((SRC / path).is_file() for path in EXEMPT)
