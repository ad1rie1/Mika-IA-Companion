"""Une politique : toute audience réelle dit ce qui se dit nommément de la vie d'autrui à qui n'a aucun lien avec
la personne (``Audience.untied_level``, ADR 0092).

Le champ est facultatif pour qu'une audience de test ou une situation de console reste lisible ; une audience que le
moteur construit pour quelqu'un qui écoute (``level=`` posé) doit le préciser, sinon la vie d'Alice redeviendrait
dicible nommément à toute amie de Mika sans que rien ne le dise.

Le contrôle porte sur l'arbre du code (``ast``), jamais sur le texte du fichier.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "mika"


def _audiences_without_untied() -> list[str]:
    out: list[str] = []
    for path in sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else \
                node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if name != "Audience":
                continue
            keys = {k.arg for k in node.keywords}
            if "level" in keys and "untied_level" not in keys:
                out.append(f"{path.relative_to(SRC)}:{node.lineno}")
    return out


def test_every_audience_says_what_she_may_name_without_a_tie():
    assert _audiences_without_untied() == []


def test_the_guard_sees_an_audience():
    """La garde n'est pas vide : elle trouve les audiences du code."""
    found = 0
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found += sum(1 for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                     and n.func.id == "Audience" and any(k.arg == "untied_level" for k in n.keywords))
    assert found >= 5
