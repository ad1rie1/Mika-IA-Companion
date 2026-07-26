"""Validation statique + environnement d'exécution confiné des modules forgés.

Modèle de menace : empêcher un module écrit par l'IA (ou influencé par une
injection de prompt dans un contenu qu'elle lit) de toucher à l'hôte —
fichiers, réseau non déclaré, processus, introspection Python
(``__class__``, ``__globals__``, ``object.__subclasses__``…).

Trois couches :
  1. ``validate_source()`` — AST : pas d'import, pas de dunder, pas de
     builtins dangereux, pas de ``.format`` (traversée d'attributs), pas
     d'async (les handlers sont synchrones et chronométrés).
  2. ``build_globals()`` — builtins filtrés + modules sûrs pré-injectés
     en lecture seule. Tout le reste passe par l'objet ``api`` capacitaire.
  3. ``run_with_deadline()`` — exécution dans un thread avec un tracer
     qui interrompt les boucles infinies pures-Python au-delà du délai.

Ce n'est PAS une isolation OS parfaite (le code reste in-process) : c'est
un garde-fou robuste contre les accidents et les évasions classiques,
proportionné au fait que le code est généré localement par Mika elle-même.
"""

from __future__ import annotations

import ast
import base64
import collections
import copy
import datetime as _datetime
import functools
import hashlib
import itertools
import json as _json
import math
import random
import re as _re
import statistics
import sys
import time
import types
import uuid as _uuid

MAX_SOURCE_BYTES = 128 * 1024
MAX_AST_NODES = 20_000

# Builtins réellement utiles pour du code de traitement de données.
_SAFE_BUILTIN_NAMES = [
    "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes",
    "callable", "chr", "complex", "dict", "divmod", "enumerate", "filter",
    "float", "format", "frozenset", "hash", "hex", "int", "isinstance",
    "issubclass", "iter", "len", "list", "map", "max", "min", "next",
    "oct", "ord", "pow", "range", "repr", "reversed", "round", "set",
    "slice", "sorted", "str", "sum", "tuple", "zip",
    "staticmethod", "classmethod", "property", "super",
]

_SAFE_EXCEPTIONS = [
    "BaseException", "Exception", "ArithmeticError", "AttributeError",
    "IndexError", "KeyError", "LookupError", "NotImplementedError",
    "OverflowError", "RuntimeError", "StopIteration", "TypeError",
    "ValueError", "ZeroDivisionError", "UnicodeError",
]

# Références interdites même si absentes des builtins (message clair
# à la validation plutôt qu'un NameError cryptique à l'exécution).
FORBIDDEN_NAMES = frozenset({
    "eval", "exec", "compile", "open", "input", "breakpoint", "exit",
    "quit", "globals", "locals", "vars", "dir", "getattr", "setattr",
    "delattr", "hasattr", "type", "object", "memoryview", "id", "help",
    "copyright", "credits", "license", "__import__", "__builtins__",
    "__build_class__", "__name__", "__loader__", "__spec__", "__package__",
    "__debug__", "__doc__",
})

# ``.format``/``.format_map`` sur str permettent la traversée d'attributs
# ("{0.__class__}") sans apparaître comme Attribute dans l'AST → interdits
# (les f-strings couvrent le besoin et SONT analysées par l'AST).
FORBIDDEN_ATTRIBUTES = frozenset({"format", "format_map", "mro"})

# Méthodes dunder autorisées en DÉFINITION dans un corps de classe
# (jamais en accès explicite).
ALLOWED_DUNDER_DEFS = frozenset({
    "__init__", "__repr__", "__str__", "__eq__", "__ne__", "__lt__",
    "__le__", "__gt__", "__ge__", "__hash__", "__len__", "__iter__",
    "__next__", "__contains__", "__getitem__", "__setitem__",
    "__delitem__", "__call__", "__enter__", "__exit__", "__add__",
    "__sub__", "__mul__", "__bool__", "__post_init__",
})

_DUNDER = _re.compile(r"^__.*__$")

HANDLER_PREFIXES = ("on_start", "on_tick", "on_event", "get_context",
                    "view_", "action_")


class SandboxViolation(Exception):
    """Le code soumis viole les règles du bac à sable."""


class ForgeTimeout(Exception):
    """Le handler a dépassé son budget temps."""


# ── Validation AST ────────────────────────────────────────────────


def _is_dunder(name: str | None) -> bool:
    return bool(name) and bool(_DUNDER.match(name))


def validate_source(source: str) -> list[str]:
    """Analyse ``source`` et retourne la liste des violations (vide = OK).

    Les messages sont en français : c'est Mika qui les lit pour corriger
    son propre code.
    """
    errors: list[str] = []
    if len(source.encode("utf-8", errors="replace")) > MAX_SOURCE_BYTES:
        return [f"source trop longue (max {MAX_SOURCE_BYTES // 1024} Ko)"]

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"erreur de syntaxe ligne {exc.lineno}: {exc.msg}"]

    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_AST_NODES:
        return [f"code trop complexe ({len(nodes)} nœuds AST, max {MAX_AST_NODES})"]

    # Noms de méthodes dunder autorisés uniquement en définition directe
    # dans un corps de classe.
    allowed_def_nodes: set[int] = set()
    for node in nodes:
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if (
                    isinstance(item, ast.FunctionDef)
                    and item.name in ALLOWED_DUNDER_DEFS
                ):
                    allowed_def_nodes.add(id(item))

    def err(node: ast.AST, msg: str) -> None:
        line = getattr(node, "lineno", "?")
        errors.append(f"ligne {line}: {msg}")

    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            err(node, "import interdit — les modules sûrs (math, json, re, "
                      "datetime, random, statistics, collections, itertools, "
                      "functools, hashlib, base64, uuid, copy, string) sont "
                      "déjà disponibles sans import")
        elif isinstance(node, (ast.AsyncFunctionDef, ast.Await,
                               ast.AsyncFor, ast.AsyncWith)):
            err(node, "code async interdit — les handlers sont synchrones")
        elif isinstance(node, ast.FunctionDef):
            if _is_dunder(node.name) and id(node) not in allowed_def_nodes:
                err(node, f"définition dunder interdite: {node.name}")
        elif isinstance(node, ast.ClassDef):
            if _is_dunder(node.name):
                err(node, f"nom de classe interdit: {node.name}")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                err(node, f"accès attribut préfixé '_' interdit: .{node.attr} "
                          "(nomme tes attributs sans underscore initial)")
            elif node.attr in FORBIDDEN_ATTRIBUTES:
                err(node, f"attribut interdit: .{node.attr} "
                          "(utilise les f-strings pour formater)")
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES:
                err(node, f"nom interdit: {node.id}")
            elif _is_dunder(node.id):
                err(node, f"nom dunder interdit: {node.id}")
        elif isinstance(node, ast.arg):
            if _is_dunder(node.arg) or node.arg in FORBIDDEN_NAMES:
                err(node, f"nom d'argument interdit: {node.arg}")
        elif isinstance(node, ast.keyword):
            if _is_dunder(node.arg or ""):
                err(node, f"argument nommé interdit: {node.arg}")
        elif isinstance(node, ast.alias):
            err(node, "import interdit")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                if _is_dunder(name) or name in FORBIDDEN_NAMES:
                    err(node, f"nom interdit: {name}")
        elif isinstance(node, ast.ExceptHandler):
            if _is_dunder(node.name):
                err(node, f"nom interdit: {node.name}")

    return errors


def list_handlers(source: str) -> list[str]:
    """Noms des fonctions top-level qui ressemblent à des points d'entrée."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith(HANDLER_PREFIXES):
            out.append(node.name)
    return out


# ── Environnement d'exécution ─────────────────────────────────────


class FrozenModule:
    """Proxy lecture seule vers un module réel (bloque le monkey-patch
    inter-modules et l'accès aux attributs privés)."""

    def __init__(self, module, public_name: str):
        object.__setattr__(self, "_forge_mod", module)
        object.__setattr__(self, "_forge_name", public_name)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(
                f"attribut privé inaccessible: {self._forge_name}.{name}"
            )
        return getattr(object.__getattribute__(self, "_forge_mod"), name)

    def __setattr__(self, name, value):
        raise AttributeError(
            f"module en lecture seule: {object.__getattribute__(self, '_forge_name')}"
        )

    def __repr__(self):
        return f"<module sûr '{object.__getattribute__(self, '_forge_name')}'>"


_STRING_SUBSET = types.SimpleNamespace(
    ascii_letters="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    ascii_lowercase="abcdefghijklmnopqrstuvwxyz",
    ascii_uppercase="ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    digits="0123456789",
    hexdigits="0123456789abcdefABCDEF",
    punctuation=r"""!"#$%&'()*+,-./:;<=>?@[\]^_`{|}~""",
    whitespace=" \t\n\r\x0b\x0c",
)

SAFE_MODULES = {
    "math": math,
    "json": _json,
    "re": _re,
    "datetime": _datetime,
    "random": random,
    "statistics": statistics,
    "collections": collections,
    "itertools": itertools,
    "functools": functools,
    "hashlib": hashlib,
    "base64": base64,
    "uuid": _uuid,
    "copy": copy,
}


def build_globals(api, print_fn) -> dict:
    """Construit le dict de globals pour ``exec`` du code d'un module forgé.

    ``api`` est l'objet capacitaire (ForgeAPI) ; ``print_fn`` capture les
    ``print()`` vers le journal du module.
    """
    import builtins as _b

    safe_builtins: dict = {}
    for name in _SAFE_BUILTIN_NAMES + _SAFE_EXCEPTIONS:
        obj = getattr(_b, name, None)
        if obj is not None:
            safe_builtins[name] = obj
    safe_builtins["print"] = print_fn
    safe_builtins["True"] = True
    safe_builtins["False"] = False
    safe_builtins["None"] = None
    # Nécessaire pour que l'instruction ``class`` fonctionne ; la source
    # ne peut pas y faire référence (dunder bloqué à la validation).
    safe_builtins["__build_class__"] = _b.__build_class__

    env: dict = {
        "__builtins__": safe_builtins,
        "__name__": "forge_module",
        "api": api,
        "string": _STRING_SUBSET,
    }
    for public_name, module in SAFE_MODULES.items():
        env[public_name] = FrozenModule(module, public_name)
    return env


# ── Exécution bornée dans le temps ────────────────────────────────


def run_with_deadline(fn, args: tuple, timeout_s: float):
    """Appelle ``fn(*args)`` avec un tracer qui lève ``ForgeTimeout`` si le
    budget est dépassé. À exécuter DANS le thread worker (pas sur la loop).

    Interrompt les boucles pures-Python ; un appel C bloquant (regex
    pathologique) n'est pas interruptible — le pool borné + le timeout
    côté asyncio limitent les dégâts.
    """
    deadline = time.monotonic() + timeout_s
    counter = 0

    def tracer(frame, event, arg):
        nonlocal counter
        counter += 1
        if counter % 64 == 0 and time.monotonic() > deadline:
            raise ForgeTimeout(f"budget temps dépassé ({timeout_s:.1f}s)")
        return tracer

    old = sys.gettrace()
    sys.settrace(tracer)
    try:
        return fn(*args)
    finally:
        sys.settrace(old)
