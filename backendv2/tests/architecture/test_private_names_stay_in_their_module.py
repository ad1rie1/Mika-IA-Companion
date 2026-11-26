"""Un nom privé ne se lit pas d'un autre module (ADR 0314).

Dans ``src/mika``, un nom qui commence par un soulignement est à son module : aucun autre ne l'importe
(``from x import _nom``) ni ne le lit par son module (``x._nom``). Ce qu'un autre module lit porte un nom public, là
où il est défini ; une aide que plusieurs modules partagent a un module à elle.

Lu par l'AST : un commentaire ou une docstring qui cite un nom privé ne compte pas. Les noms à double soulignement
(``__all__``, ``__name__``) et les sous-modules ne sont pas des noms privés. Les tests, eux, lisent ce qu'ils veulent.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import mika

ROOT = Path(mika.__file__).parent.parent


def _private(name: str) -> bool:
    return name.startswith("_") and not name.startswith("__")


def _module_of(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _is_module(name: str) -> bool:
    path = ROOT.joinpath(*name.split("."))
    return path.with_suffix(".py").exists() or (path / "__init__.py").exists()


def _source(reader: str, package: bool, node: ast.ImportFrom) -> str:
    """Le module que nomme un ``from … import`` — un import relatif résolu depuis celui qui le lit."""
    if not node.level:
        return node.module or ""
    base = reader.split(".") if package else reader.split(".")[:-1]
    base = base[: len(base) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


def reads(path: Path) -> Iterator[tuple[int, str, str]]:
    """Les noms privés d'un autre module de ``mika`` que ce fichier lit : la ligne, le module lu, le nom."""
    reader = _module_of(path)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: dict[str, str] = {}  # un nom local qui désigne un module -> ce module
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                modules[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            source = _source(reader, path.name == "__init__.py", node)
            for a in node.names:
                if _is_module(f"{source}.{a.name}"):
                    modules[a.asname or a.name] = f"{source}.{a.name}"
                elif _private(a.name) and source != reader and _is_module(source):
                    yield node.lineno, source, a.name
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Attribute) and _private(node.attr)):
            continue
        chain: list[str] = []
        value = node.value
        while isinstance(value, ast.Attribute):
            chain.append(value.attr)
            value = value.value
        if not isinstance(value, ast.Name) or value.id not in modules:
            continue
        module = modules[value.id]
        for part in reversed(chain):
            module = f"{module}.{part}"
        if module != reader and _is_module(module) and not _is_module(f"{module}.{node.attr}"):
            yield node.lineno, module, node.attr


def test_no_module_reads_the_private_name_of_another():
    found = [f"{path.relative_to(ROOT).as_posix()}:{line} lit {module}.{name}"
             for path in sorted(ROOT.rglob("*.py")) if "__pycache__" not in path.parts
             for line, module, name in reads(path)]
    assert not found, (
        "Un nom privé ne se lit pas d'un autre module (ADR 0314) : donne-lui un nom public là où il est défini, ou "
        "range l'aide partagée dans un module à elle.\n" + "\n".join(found))


def test_the_guard_sees_both_ways_of_reading(tmp_path: Path, monkeypatch):
    """La garde voit les deux écritures — ``from x import _nom`` et ``x._nom`` —, et pas ce qui n'en est pas : un
    nom public, un nom à double soulignement, l'attribut privé d'un objet."""
    pkg = tmp_path / "mika" / "zone"
    pkg.mkdir(parents=True)
    (tmp_path / "mika" / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text("")
    (pkg / "tool.py").write_text("_hidden = 1\nshown = 2\n")
    (pkg / "by_name.py").write_text("from mika.zone.tool import _hidden, shown\n")
    (pkg / "by_module.py").write_text("from mika.zone import tool\nfrom . import tool as same\n"
                                      "a = tool._hidden\nb = same._hidden\nc = tool.shown\nd = tool.__doc__\n")
    (pkg / "clean.py").write_text("from mika.zone.tool import shown\nclass K:\n    _own = 1\nk = K()\ne = k._own\n")
    monkeypatch.setattr(f"{__name__}.ROOT", tmp_path)
    assert list(reads(pkg / "by_name.py")) == [(1, "mika.zone.tool", "_hidden")]
    assert list(reads(pkg / "by_module.py")) == [(3, "mika.zone.tool", "_hidden"), (4, "mika.zone.tool", "_hidden")]
    assert list(reads(pkg / "clean.py")) == []
