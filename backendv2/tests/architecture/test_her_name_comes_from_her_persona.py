"""Une politique : son nom vient de sa persona, jamais du code (ADR 0070).

Un « Mika » écrit en dur dans une consigne (« Tu es la mémoire de Mika »),
une étiquette de réplique ou un libellé de la console lui rendait un nom qui
n'est plus le sien dès qu'elle en change — une persona incarnée l'entendait
dans chaque relecture de sa mémoire. Le nom se lit dans sa persona
(``self_.name_of``) ; le seul endroit où il s'écrit est le défaut du champ
``PersonaDoc.name`` — plus, chacune avec sa raison, des chaînes qui nomment le
logiciel et non elle.

Le contrôle porte sur les chaînes du code (``ast``), jamais sur le texte du
fichier : les commentaires et les docstrings racontent son histoire, et le
simulateur (``sim/``) comme les tests gardent « Mika ».
"""

from __future__ import annotations

import ast
import functools
import re
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "mika"
#: ce qui n'est pas son nom en dur : le simulateur fait vivre la persona livrée, avec ses interlocuteurs écrits
SKIPPED = ("sim",)
NAME = re.compile(r"\bMika\b")

#: (module, chaîne exacte) → pourquoi elle peut dire « Mika »
ALLOWED = {
    ("contracts/self_.py", "Mika"): "le défaut de PersonaDoc.name (DEFAULT_NAME) : le nom de la persona livrée, "
                                    "d'où tout le reste le tient",
    ("adapters/feeds/__init__.py", "Mika/2 (lecteur de flux)"): "l'identifiant du logiciel auprès des serveurs de "
                                                                 "flux (User-Agent) : le programme, pas elle",
    ("adapters/forge/__init__.py", "Mika-Forge/2"): "l'identifiant du logiciel auprès des sites que ses apps lisent "
                                                    "(User-Agent) : le programme, pas elle",
}


def _modules() -> list[Path]:
    return sorted(p for p in PACKAGE.rglob("*.py")
                  if "__pycache__" not in p.parts and p.relative_to(PACKAGE).parts[0] not in SKIPPED)


def _docstrings(tree: ast.AST) -> set[int]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                out.add(id(first.value))
    return out


def _strings(path: Path) -> Iterator[tuple[int, str]]:
    """Chaque chaîne du module (morceaux fixes d'une f-string compris), hors docstrings."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docs = _docstrings(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            yield node.lineno, node.value


def _named(path: Path) -> list[tuple[int, str]]:
    return [(line, value) for line, value in _strings(path) if NAME.search(value)]


@functools.cache
def _package_named() -> tuple[tuple[str, int, str], ...]:
    """Chaque chaîne du paquet qui dit « Mika » : (module, ligne, chaîne) — lu une fois."""
    return tuple((path.relative_to(PACKAGE).as_posix(), line, value) for path in _modules()
                 for line, value in _named(path))


def test_the_policy_sees_the_whole_package_but_the_simulator():
    names = {p.relative_to(PACKAGE).as_posix() for p in _modules()}
    assert {"faculties/memory/extraction.py", "faculties/self/__init__.py", "adapters/mail/compose.py",
            "app/cli.py"} <= names
    assert not any(n.startswith("sim/") for n in names)


def test_no_string_of_the_code_writes_her_name():
    offences = [f"{module}:{line} : {value[:90]!r}" for module, line, value in _package_named()
                if (module, value) not in ALLOWED]
    assert offences == [], ("son nom vient de sa persona (self_.name_of), jamais du code :\n" + "\n".join(offences))


def test_every_allowed_string_is_still_there():
    """Une exception qui ne sert plus se retire : sinon la liste grandit sans que personne ne la relise."""
    found = {(module, value) for module, _line, value in _package_named()}
    assert set(ALLOWED) <= found, set(ALLOWED) - found


def test_the_policy_catches_what_it_forbids(tmp_path):
    """Non vide : une consigne, une étiquette, un morceau de f-string sont vus ; un commentaire, une docstring et
    un mot qui le contient (« Mikachu ») ne le sont pas."""
    sample = tmp_path / "consigne.py"
    sample.write_text('"""La mémoire de Mika (une docstring raconte)."""\n'
                      'SYSTEM = "Tu es la mémoire de Mika."\n'
                      'def label(seq):\n'
                      '    """Mika parle."""\n'
                      '    return f"{seq} Mika : bonjour"  # Mika, en commentaire\n'
                      'NICK = "salut Mikachu"\n',
                      encoding="utf-8")
    assert sorted(line for line, _value in _named(sample)) == [2, 5]
