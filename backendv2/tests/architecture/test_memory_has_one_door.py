"""Une politique : hors de la mémoire, on ne lit ce qu'elle sait que par sa porte (ADR 0078).

Les tables de la mémoire (``memory_items``, ``memory_about``, ``memory_told``…) sont à elle. Les autres facultés,
les plugins, l'application, la console et le simulateur lisent les **vues** que ``contracts.memory`` nomme
(``KNOWLEDGE_VIEW``…) et passent chaque ligne par le verdict commun (``vocab.knowledge`` → ``vocab.lineage.admits``).
Avant, une douzaine de lecteurs refaisaient chacun leur filtre sur la table brute, et plusieurs fuyaient (audit du
2026-10-09). Ce qu'elle a cru et ne croit plus (``FORMER_VIEW``) et le grand livre (``LEDGER_VIEW``, tout, statut
compris) ne sont pas pour les facultés : seule la pensée d'une révision a besoin de l'ancienne croyance.

Le contrôle porte sur l'arbre du code (``ast``) — les noms et les chaînes, docstrings exceptées —, jamais sur le
texte du fichier : les commentaires nomment justement ce qu'il ne faut pas faire.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "mika"
#: ce qui appartient à la mémoire : ses tables y sont chez elles
OWNERS = (SRC / "faculties" / "memory", SRC / "contracts" / "memory.py")
#: les noms de ses tables, comme constantes de ``contracts.memory`` et comme texte SQL
TABLE_NAMES = frozenset({"ITEMS_TABLE", "ABOUT_TABLE", "TOLD_TABLE", "TOLD_LINES_TABLE", "FORGETS_TABLE"})
TABLE_TEXT = re.compile(r"\bmemory_(?:items|about|told_lines|told|refs|changes|forgets|testimonies|contests)\b")
#: ce que les facultés et les plugins ne lisent pas (sauf la raison nommée)
BEHIND = frozenset({"LEDGER_VIEW", "FORMER_VIEW", "SELECT_FORMER"})
ALLOWED_BEHIND = {
    # la pensée d'une croyance révisée cite l'ancienne et la nouvelle (sous la filiation des deux)
    (SRC / "faculties" / "attention" / "watch.py", "SELECT_FORMER"),
}


def _modules(*roots: Path) -> list[Path]:
    return sorted(p for r in roots for p in r.rglob("*.py") if "__pycache__" not in p.parts)


def _owned(path: Path) -> bool:
    return any(path == o or o in path.parents for o in OWNERS)


def _docstrings(tree: ast.AST) -> set[int]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                out.add(id(first.value))
    return out


def _uses(path: Path) -> Iterator[tuple[int, str]]:
    """Chaque nom d'attribut et chaque chaîne du module (morceaux fixes des f-strings compris, docstrings non)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docs = _docstrings(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            yield node.lineno, node.attr
        elif isinstance(node, ast.Name):
            yield node.lineno, node.id
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            yield node.lineno, node.value


def test_no_one_reads_her_tables_behind_her_back():
    offences = []
    for path in _modules(SRC):
        if _owned(path):
            continue
        for line, used in _uses(path):
            if used in TABLE_NAMES or TABLE_TEXT.search(used):
                offences.append(f"{path.relative_to(ROOT)}:{line} lit {used!r}")
    assert offences == [], "hors de la mémoire, on lit ses vues (contracts.memory) :\n" + "\n".join(offences)


def test_faculties_and_plugins_read_what_she_still_holds():
    offences = []
    for path in _modules(SRC / "faculties", SRC / "plugins"):
        if _owned(path):
            continue
        for line, used in _uses(path):
            if used in BEHIND and (path, used) not in ALLOWED_BEHIND:
                offences.append(f"{path.relative_to(ROOT)}:{line} lit {used!r}")
    assert offences == [], "une faculté lit ce qu'elle tient pour sien (KNOWLEDGE_VIEW) :\n" + "\n".join(offences)


def test_the_check_sees_a_raw_read():
    """Le contrôle n'est pas vide : une lecture brute, sous forme de constante ou de texte SQL, est vue."""
    probe = ast.parse('rows = q(f"SELECT text FROM {memory_c.ITEMS_TABLE}")\nq("SELECT 1 FROM memory_about")')
    attrs = {n.attr for n in ast.walk(probe) if isinstance(n, ast.Attribute)}
    texts = [n.value for n in ast.walk(probe) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert attrs & TABLE_NAMES and any(TABLE_TEXT.search(t) for t in texts)
    assert not TABLE_TEXT.search("SELECT item FROM memory_knowledge_about")  # la vue, elle, est permise
