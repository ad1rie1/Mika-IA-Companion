"""Le fichier de sa persona (``persona/mika.yaml``), lu pour un humain.

Un fichier qui ne se lit pas (une phrase « Elle ne fait pas de live : … », que YAML
lit comme une clé ; une tabulation ; un champ inconnu) arrêtait le démarrage sur une
trace pydantic en anglais. Ici, il se dit en français — le fichier, la ligne, la
cause, et comment la réparer — et le serveur démarre sur la dernière persona valide
gardée au journal (chaque persona prise y est journalisée). Seule une installation qui
n'en a encore jamais gardé aucune refuse de démarrer, en le disant, sans trace.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from mika.adapters.store_sqlite import SqliteStore
from mika.app.paths import ROOT
from mika.contracts import self_ as self_c
from mika.contracts.self_ import PersonaDoc
from mika.faculties.self import load
from mika.kernel import forms

#: la clé des réglages où vit la persona rédigée dans la console (``Settings.persona_yaml``)
CONSOLE_KEY = "persona"
#: des problèmes YAML courants, en mots (le message de PyYAML commence par…)
_YAML_FR = (
    ("mapping values are not allowed", "un « : » suivi d'une espace, au milieu d'une phrase : mets la phrase entre "
                                       "guillemets"),
    ("found character '\\t'", "une tabulation : indente avec des espaces"),
    ("could not find expected ':'", "une ligne qui n'est ni « clé: valeur » ni « - élément » (une indentation ?)"),
    ("did not find expected '-' indicator", "un élément de liste mal aligné : chaque « - » au même retrait"),
    ("expected <block end>, but found '-'", "un élément de liste mal aligné : chaque « - » au même retrait"),
    ("found unexpected end of stream", "des guillemets ouverts et jamais fermés"),
)


class PersonaInvalid(ValueError):
    """Le fichier de persona ne se lit pas ; ``problem`` le dit en français (fichier, ligne, cause)."""

    def __init__(self, problem: str) -> None:
        self.problem = problem
        super().__init__(problem)


class PersonaUnavailable(RuntimeError):
    """Aucune persona valide : le fichier ne se lit pas, et ni la console ni le journal n'en gardent une."""


def shown(path: Path) -> str:
    """Le chemin tel qu'on le montre : relatif au dépôt quand il y est (« persona/mika.yaml »)."""
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def read(path: Path) -> PersonaDoc:
    """La persona du fichier ; ``PersonaInvalid`` (en français) s'il ne se lit pas."""
    try:
        return load(path)
    except OSError as exc:
        raise PersonaInvalid(f"{shown(path)} : illisible ({exc.strerror or exc})") from None
    except yaml.YAMLError as exc:
        raise PersonaInvalid(_yaml_problem(path, exc)) from None
    except ValidationError as exc:
        raise PersonaInvalid(_validation_problem(path, exc)) from None


def _yaml_problem(path: Path, exc: yaml.YAMLError) -> str:
    mark = getattr(exc, "problem_mark", None)
    where = f", ligne {mark.line + 1}" if mark is not None else ""
    problem = str(getattr(exc, "problem", "") or exc)
    meaning = next((fr for en, fr in _YAML_FR if problem.startswith(en) or en in problem), "")
    return f"{shown(path)}{where} : le YAML ne se lit pas — {meaning or problem}"


def _validation_problem(path: Path, exc: ValidationError) -> str:
    """Le premier problème, sa ligne dans le fichier, et combien d'autres."""
    errors = exc.errors(include_url=False)
    try:
        tree = yaml.compose(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        tree = None
    labels = {f.path: f.label for f in forms.describe(PersonaDoc)}
    first = errors[0]
    loc = tuple(first.get("loc") or ())
    node = _node_at(tree, loc)
    where = f", ligne {node.start_mark.line + 1}" if node is not None else ""
    field = labels.get(str(loc[0]), str(loc[0])) if loc else "le document"
    if first.get("type") == "string_type" and isinstance(node, yaml.MappingNode):
        cause = ("un « : » suivi d'une espace transforme la phrase en clé ; mets-la entre guillemets "
                 "(« - \"Elle … : …\" »)")
    else:
        cause = forms.message_fr(first)
    more = f" (et {len(errors) - 1} autre(s) problème(s))" if len(errors) > 1 else ""
    return f"{shown(path)}{where} ({field}) : {cause}{more}"


def _node_at(tree: Any, loc: Sequence[Any]) -> Any:
    """Le nœud YAML que désigne un chemin d'erreur (« facts », 4) — ``None`` s'il n'y est pas."""
    node = tree
    for part in loc:
        if isinstance(node, yaml.MappingNode):
            node = next((v for k, v in node.value if getattr(k, "value", None) == str(part)), None)
        elif isinstance(node, yaml.SequenceNode) and isinstance(part, int) and 0 <= part < len(node.value):
            node = node.value[part]
        else:
            return node
        if node is None:
            return None
    return node


async def _kept(data: Path) -> tuple[bool, bool]:
    """(une persona valide rédigée dans la console, une persona gardée au journal)."""
    if not (data / "mind.db").exists():
        return False, False
    store = SqliteStore(data / "mind.db", data / "views.db", threaded=False)
    await store.open()
    try:
        journaled = bool(store.latest([self_c.PERSONA_REVISED.name], 1))
        try:
            rows = store.query_mind("SELECT value FROM settings WHERE key=?", (CONSOLE_KEY,))
        except sqlite3.OperationalError:  # pas encore de table des réglages : pas de persona de console
            rows = []
        return bool(rows) and _valid_console(rows[0][0]), journaled
    finally:
        await store.close()


def _valid_console(raw: str) -> bool:
    """La persona rédigée dans la console (un texte YAML rangé en JSON) se lit-elle ?"""
    try:
        text = json.loads(raw)
        if not isinstance(text, str) or not text:
            return False
        PersonaDoc.model_validate(yaml.safe_load(text) or {})
    except (ValueError, yaml.YAMLError):
        return False
    return True


def startup(data: Path, path: Path) -> tuple[str, bool]:
    """Avant de démarrer : ``(problème, bloquant)``. Rien à dire : ``("", False)``. Un fichier illisible n'est
    bloquant que si rien d'autre ne tient lieu de persona (ni la console, ni le journal) ; repris du journal, le
    serveur le dit lui-même en relisant sa persona."""
    try:
        read(path)
    except PersonaInvalid as exc:
        console, journaled = asyncio.run(_kept(data))
        if console:
            return f"{exc.problem} — la persona rédigée dans la console fait foi", False
        if journaled:  # le serveur le dira en la relisant (``Live.persona``) : rien à ajouter ici
            return "", False
        return (f"{exc.problem} — et aucune persona valide n'est gardée (première fois) : corrige le fichier, "
                "puis relance"), True
    return "", False
