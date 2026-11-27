"""Un module qui inscrit une contribution est importé par son paquet.

Une faculté ou un plugin est un paquet dont le ``__init__.py`` importe chacun de ses modules à contributions
(« — contributions ») : c'est cet import qui les inscrit. Un module qui inscrit une section, un outil, un processus,
un réducteur… sans y figurer ne s'inscrit que parce qu'un autre module l'importe — et cesse de s'inscrire, loin de sa
cause, le jour où cet import s'en va (``veiled.py`` de la mémoire ne tenait ainsi qu'à ``recall.py``).

Lu par l'AST, sans importer aucun module de faculté ni de plugin (un import inscrirait justement ce qu'on vérifie) :

- une **contribution** est un appel ``X.<méthode>(…)`` ou un décorateur ``@X.<méthode>`` où ``X`` est un nom lié à un
  ``Faculty(…)`` — défini dans le module, ou importé d'un module qui le définit — et ``<méthode>`` une de celles qui
  inscrivent (``REGISTERING``) ;
- un module est **importé par son paquet** quand le ``__init__.py`` de son dossier l'importe lui-même (``from paquet
  import module``, ``import paquet.module``, ``from paquet.module import …``, ou leur forme relative) ; un sous-paquet
  qui porte des contributions (``plugins/email/inspect/``) l'est par le ``__init__.py`` du dossier du dessus.

Rien n'est excusé. Un propriétaire qui tient dans un seul module, sans paquet, n'est pas regardé.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping
from pathlib import Path

import mika
from mika.kernel.faculty import Faculty

SRC = Path(mika.__file__).parent
#: les couches dont chaque dossier est un propriétaire
OWNERS = ("faculties", "plugins")
#: les méthodes de ``Faculty`` qui inscrivent une contribution
REGISTERING = frozenset({
    "event", "declare", "reducer", "fact", "appraisal", "feels", "section", "enricher", "propose", "modulate",
    "process", "tool", "bundle", "tool_source", "projector", "capability", "effect", "inspect", "subject", "search",
    "download", "action", "rights", "vital", "series", "invariant", "prelude", "interpret",
})
#: celles qui n'inscrivent rien : ses réglages par défaut
PLAIN = frozenset({"default_params"})


def _faculty_names(tree: ast.Module) -> set[str]:
    """Les noms de tête que le module lie à un ``Faculty(…)`` (``MEMORY = Faculty(…)``, annoté ou non)."""
    out: set[str] = set()
    for node in tree.body:
        value = node.value if isinstance(node, ast.Assign | ast.AnnAssign) else None
        call = value.func if isinstance(value, ast.Call) else None
        while isinstance(call, ast.Subscript):  # ``Faculty[State, Params](…)``
            call = call.value
        named = call.id if isinstance(call, ast.Name) else call.attr if isinstance(call, ast.Attribute) else ""
        if named != "Faculty":
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        out |= {t.id for t in targets if isinstance(t, ast.Name)}
    return out


def _resolved(module: str, package: bool, node: ast.ImportFrom) -> str:
    """Le module que nomme un ``from … import``, un import relatif résolu depuis celui qui le lit."""
    if not node.level:
        return node.module or ""
    base = module.split(".") if package else module.split(".")[:-1]
    base = base[: len(base) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


def _imports(tree: ast.Module, module: str, package: bool) -> Iterator[tuple[str, str, str]]:
    """Chaque import du module : (module importé, nom importé ou vide, nom local)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name, "", a.asname or a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            source = _resolved(module, package, node)
            for a in node.names:
                yield source, a.name, a.asname or a.name


def unimported(sources: Mapping[str, str]) -> list[str]:
    """Chaque module à contributions que son paquet n'importe pas, en phrases. ``sources`` : le texte de chaque module,
    par son nom pointé (``mika.faculties.memory.veiled`` ; un ``__init__.py`` porte le nom de son paquet, suivi de
    ``.__init__``)."""
    trees = {name: ast.parse(text) for name, text in sources.items()}
    faculties = {name: _faculty_names(tree) for name, tree in trees.items()}

    def plain(name: str) -> str:
        return name.removesuffix(".__init__")

    known = {(plain(name), x) for name, found in faculties.items() for x in found}
    registering: dict[str, tuple[int, str]] = {}
    for name, tree in trees.items():
        package = name.endswith(".__init__")
        mine = set(faculties[name]) | {local for source, what, local in _imports(tree, plain(name), package)
                                       if (source, what) in known}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr in REGISTERING and isinstance(node.value, ast.Name)
                    and node.value.id in mine):
                registering.setdefault(name, (node.lineno, f"{node.value.id}.{node.attr}"))
    # un sous-paquet porte les contributions de ses modules : c'est lui que le dossier du dessus importe
    carriers = dict(registering)
    for name, where in registering.items():
        parts = plain(name).split(".")
        for depth in range(4, len(parts)):  # mika.<couche>.<propriétaire>.<sous-paquet>…
            parent = ".".join(parts[:depth])
            if f"{parent}.__init__" in trees and parent != plain(name):
                carriers.setdefault(f"{parent}.__init__", where)
    out = []
    for name, (line, what) in sorted(carriers.items()):
        module = plain(name)
        parts = module.split(".")
        if len(parts) <= 3 or (name.endswith(".__init__") and len(parts) == 3):
            continue  # un propriétaire d'un seul module, ou le paquet d'un propriétaire lui-même
        home = ".".join(parts[:-1])
        init = trees.get(f"{home}.__init__")
        if init is None:
            continue
        imported = {source if not what_ else f"{source}.{what_}" for source, what_, _ in _imports(init, home, True)}
        imported |= {source for source, _, _ in _imports(init, home, True)}
        if module not in imported:
            out.append(f"{module} inscrit une contribution (l. {line} : {what}) sans que {home}/__init__.py l'importe : "
                       "l'ajouter à sa liste « — contributions », sinon elle ne tient qu'à l'import d'un autre module "
                       "(ARCHITECTURE.md, « Écrire une faculté », point 3)")
    return out


def _sources() -> dict[str, str]:
    out = {}
    for layer in OWNERS:
        for path in sorted((SRC / layer).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            out[".".join(["mika", *path.relative_to(SRC).with_suffix("").parts])] = path.read_text(encoding="utf-8")
    return out


def test_every_module_that_registers_is_imported_by_its_package():
    sources = _sources()
    assert len(sources) > 200  # la lecture trouve bien les modules
    faults = unimported(sources)
    assert not faults, "\n".join(faults)


def test_every_method_of_a_faculty_is_known_to_register_or_not():
    """Une méthode neuve de ``Faculty`` se range : elle inscrit (``REGISTERING``) ou non (``PLAIN``) — sinon la garde
    ne verrait pas ce qu'elle inscrit."""
    public = {name for name, value in vars(Faculty).items() if callable(value) and not name.startswith("_")}
    assert public == REGISTERING | PLAIN, sorted(public ^ (REGISTERING | PLAIN))


def test_the_check_sees_a_module_kept_only_by_a_neighbour():
    """Un module qui inscrit une section sans être dans la liste de son paquet échoue, même si un voisin l'importe ;
    un module qui n'inscrit rien, un sous-paquet importé par son parent et un propriétaire d'un seul module passent."""
    toy = {
        "mika.faculties.toy.__init__": "from mika.faculties.toy import faculty, recall, inspect\n",
        "mika.faculties.toy.faculty": "TOY = Faculty('toy')\n\n\n@TOY.reducer(X)\ndef _x(s, e, cx): ...\n",
        "mika.faculties.toy.recall": ("from mika.faculties.toy import veiled\nfrom mika.faculties.toy.faculty import "
                                      "TOY\n\n\n@TOY.enricher('r')\ndef _r(ctx): ...\n"),
        "mika.faculties.toy.veiled": ("from mika.faculties.toy.faculty import TOY\n\n\n@TOY.section('veiled')\n"
                                      "def _veiled(s, f): ...\n"),
        "mika.faculties.toy.rules": "from mika.faculties.toy.faculty import TOY\n\n\ndef pure(x): return TOY.key\n",
        "mika.faculties.toy.inspect.__init__": "from mika.faculties.toy.inspect import views\n",
        "mika.faculties.toy.inspect.views": ("from ...toy.faculty import TOY as T\n\n\n@T.inspect('v')\n"
                                             "def _v(s, f, ctx): ...\n"),
        "mika.plugins.lone": "LONE = Faculty('lone')\n\n\n@LONE.tool('t')\nasync def _t(args, ctx): ...\n",
    }
    assert unimported(toy) == [
        "mika.faculties.toy.veiled inscrit une contribution (l. 4 : TOY.section) sans que "
        "mika.faculties.toy/__init__.py l'importe : l'ajouter à sa liste « — contributions », sinon elle ne tient "
        "qu'à l'import d'un autre module (ARCHITECTURE.md, « Écrire une faculté », point 3)"]
    toy["mika.faculties.toy.__init__"] = "from mika.faculties.toy import faculty, recall, veiled, inspect\n"
    assert unimported(toy) == []
    toy["mika.faculties.toy.__init__"] = "from . import faculty, recall, veiled\n"  # le sous-paquet n'y est plus
    assert [fault.split(" inscrit ")[0] for fault in unimported(toy)] == ["mika.faculties.toy.inspect"]
    toy["mika.faculties.toy.inspect.__init__"] = ""  # ni son module dans le sous-paquet
    assert [fault.split(" inscrit ")[0] for fault in unimported(toy)] == [
        "mika.faculties.toy.inspect", "mika.faculties.toy.inspect.views"]
