"""Lire un source par l'AST : ce que plusieurs gardes d'architecture partagent.

Une garde qui cherche ``MEMORY.reducer`` ou ``PROJECTS.event`` par le nom seul laisse passer le même objet sous un
autre nom. ``aliases`` rend les noms sous lesquels un module le tient, ``held`` dit si une expression le désigne.

Ce qui leur échappe encore, et qu'aucun module de ``src`` ne fait : l'objet tiré d'un conteneur (``PAIR[0]``), rendu
par une fonction, ou lu par son nom en chaîne (``getattr(module, "MEMORY")``, ``importlib``).
"""

from __future__ import annotations

import ast


def aliases(tree: ast.AST, owner: str) -> set[str]:
    """Les noms sous lesquels un module tient ``owner`` (``MEMORY``, ``PROJECTS``) : le sien, celui sous lequel il
    l'importe (``from … import MEMORY as M``) et ceux qu'il lui donne ensuite (``M = MEMORY``, ``N = M``,
    ``M = faculty.MEMORY``)."""
    names = {owner}
    given: list[tuple[set[str], ast.expr]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {a.asname for a in node.names if a.name == owner and a.asname}
        elif isinstance(node, ast.Assign | ast.AnnAssign | ast.NamedExpr) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            given.append(({t.id for t in targets if isinstance(t, ast.Name)}, node.value))
    while True:
        more = {name for targets, value in given if held(value, names, owner) for name in targets} - names
        if not more:
            return names
        names |= more


def held(expr: ast.AST, names: set[str], owner: str) -> bool:
    """``expr`` désigne ``owner`` : un de ses noms dans le module (``aliases``), ou lu par son module
    (``faculty.MEMORY``)."""
    return (isinstance(expr, ast.Name) and expr.id in names) or (isinstance(expr, ast.Attribute) and expr.attr == owner)
