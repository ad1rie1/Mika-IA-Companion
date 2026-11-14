"""Le langage des arguments d'un outil d'app et des champs d'une action de ses vues (ADR 0105).

Un seul vocabulaire (``ArgSpec``) pour les deux : ``arg_specs`` le lit de la surface normalisée par la relecture,
``args_schema`` en fait le schéma que lit le modèle, ``check_args`` est la vérification par l'hôte (présence, type,
bornes, choix, longueur, forme), avec ses messages et ses bornes, et ``said_args`` le dit en quelques mots. Le port
de la Forge et la surface déclarée d'une app sont dans ``ports/forge.py``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ArgSpec:
    """Un argument déclaré — d'un outil d'app, ou un champ d'une action : **le même vocabulaire partout** (ADR 0105).
    ``type`` : ``text`` | ``textarea`` | ``int`` | ``number`` | ``bool`` | ``select`` | ``email`` | ``url`` |
    ``lines`` (une liste de textes)."""

    key: str
    type: str = "text"
    label: str = ""
    description: str = ""
    required: bool = False
    default: Any = None
    choices: tuple[str, ...] = ()
    lo: float | None = None
    hi: float | None = None
    max_length: int = 0


def number_or_none(raw: Any) -> float | None:
    """Une borne déclarée (``min``, ``max`` d'un argument, d'un champ ou d'un réglage) : un nombre, ou ``None``
    (un vrai/faux n'en est pas un)."""
    return float(raw) if isinstance(raw, int | float) and not isinstance(raw, bool) else None


# ── Les arguments déclarés : un vocabulaire, un schéma, une vérification (ADR 0105) ──

#: ce qu'un argument de chaque type devient dans le schéma que lit le modèle
_JSON_TYPES: Mapping[str, str] = {"text": "string", "textarea": "string", "email": "string", "url": "string",
                                  "select": "string", "int": "integer", "number": "number", "bool": "boolean",
                                  "lines": "array"}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
URL = re.compile(r"^https?://[^\s/?#@\\]+(?:[/?#][^\s\\]*)?$", re.IGNORECASE)
_TRUE = frozenset({"true", "vrai", "oui", "yes", "on", "1"})
_FALSE = frozenset({"false", "faux", "non", "no", "off", "0", ""})
#: une liste de textes : au plus tant d'éléments, chacun au plus tant de caractères
LINES_MAX, LINE_MAX = 100, 500


def arg_specs(raw: Sequence[Mapping[str, Any]]) -> tuple[ArgSpec, ...]:
    """Les arguments normalisés par la relecture (``{key, type, label, description, required, default, choices,
    min, max, max_length}``), en specs."""
    return tuple(ArgSpec(str(a["key"]), str(a.get("type") or "text"), str(a.get("label") or a["key"]),
                         str(a.get("description") or ""), bool(a.get("required")), a.get("default"),
                         tuple(str(c[0]) if isinstance(c, list | tuple) else str(c) for c in a.get("choices") or ()),
                         number_or_none(a.get("min")), number_or_none(a.get("max")), int(a.get("max_length") or 0))
                 for a in raw)


def args_schema(specs: Sequence[ArgSpec]) -> dict[str, Any]:
    """Le schéma JSON que voit le modèle : chaque argument, son type, ce qu'il veut dire, ses bornes et ses choix —
    rien d'autre n'est accepté."""
    props: dict[str, Any] = {}
    for a in specs:
        prop: dict[str, Any] = {"type": _JSON_TYPES.get(a.type, "string")}
        words = " — ".join(x for x in (a.label if a.label != a.key else "", a.description) if x)
        if words:
            prop["description"] = words[:400]
        if a.type == "lines":
            prop["items"] = {"type": "string"}
        if a.choices:
            prop["enum"] = list(a.choices)
        for name, bound in (("minimum", a.lo), ("maximum", a.hi)):
            if bound is not None:
                prop[name] = int(bound) if float(bound).is_integer() else bound
        if a.max_length:
            prop["maxLength"] = a.max_length
        if a.type == "email":
            prop["format"] = "email"
        elif a.type == "url":
            prop["format"] = "uri"
        if a.default is not None:
            prop["default"] = a.default
        props[a.key] = prop
    return {"type": "object", "properties": props, "required": [a.key for a in specs if a.required],
            "additionalProperties": False}


def _empty_of(a: ArgSpec) -> Any:
    return False if a.type == "bool" else [] if a.type == "lines" else \
        None if a.type in ("int", "number", "select") else ""


def _bounded(a: ArgSpec, value: float) -> str:
    if (a.lo is not None and value < a.lo) or (a.hi is not None and value > a.hi):
        return f"doit être entre {a.lo:g} et {a.hi:g}" if a.lo is not None and a.hi is not None \
            else "hors de ses bornes"
    return ""


def _one(a: ArgSpec, value: Any) -> tuple[Any, str]:
    """(la valeur vérifiée, ou le problème en français)."""
    if a.type == "bool":
        if isinstance(value, bool):
            return value, ""
        word = str(value).strip().lower()
        return (True, "") if word in _TRUE else (False, "") if word in _FALSE else (None, "vrai ou faux attendu")
    if a.type in ("int", "number"):
        if isinstance(value, bool):
            return None, "un nombre est attendu"
        try:
            number = float(value) if isinstance(value, str) else value
        except ValueError:
            return None, "un entier est attendu" if a.type == "int" else "un nombre est attendu"
        if not isinstance(number, int | float) or number != number or number in (float("inf"), float("-inf")):
            return None, "un entier est attendu" if a.type == "int" else "un nombre est attendu"
        if a.type == "int":
            if float(number) != int(number):
                return None, "un entier est attendu"
            number = int(number)
        return number, _bounded(a, number)
    if a.type == "lines":
        items = value.splitlines() if isinstance(value, str) else value
        if not isinstance(items, list | tuple) or not all(isinstance(x, str | int | float) for x in items):
            return None, "une liste de textes est attendue"
        if len(items) > LINES_MAX:
            return None, f"{LINES_MAX} éléments au plus"
        return [str(x)[:LINE_MAX] for x in items if str(x).strip()], ""
    if not isinstance(value, str | int | float) or isinstance(value, bool):
        return None, "un texte est attendu"
    text = str(value)
    if a.type == "select":
        if a.choices and text not in a.choices:
            return None, f"un de ces choix : {', '.join(a.choices)}"
        return text, ""
    if a.max_length and len(text) > a.max_length:
        return text, f"trop long : {a.max_length} caractères au plus"
    if a.type == "email" and not EMAIL.match(text.strip()):
        return text, "une adresse e-mail est attendue (nom@exemple.fr)"
    if a.type == "url" and not URL.match(text.strip()):
        return text, "une adresse http(s)://… est attendue"
    return text, ""


def check_args(specs: Sequence[ArgSpec], data: Mapping[str, Any], *, defaults: bool = True,
               strict: bool = True) -> tuple[dict[str, Any], dict[str, str]]:
    """Des arguments vérifiés un par un : présence, type, bornes, choix, longueur, forme d'un e-mail ou d'une
    adresse. Rend (valeurs, problèmes par argument). ``defaults`` : un argument absent prend son défaut déclaré (un
    outil ; un formulaire, lui, envoie ce qu'on y a laissé) ; ``strict`` : un argument non déclaré est un problème."""
    out: dict[str, Any] = {}
    errors: dict[str, str] = {}
    known = {a.key for a in specs}
    if strict:
        for key in data:
            if key not in known:
                errors[str(key)[:40]] = "argument inconnu"
    for a in specs:
        if a.key not in data and defaults and a.default is not None:
            value: Any = list(a.default) if isinstance(a.default, list) else a.default
        else:
            value = data.get(a.key)
        empty = value is None or (isinstance(value, str) and not value.strip() and a.type != "bool") or \
            (a.type == "lines" and isinstance(value, list | tuple) and not value)
        if empty and a.type != "bool":
            if a.required:
                errors[a.key] = "valeur requise"
            out[a.key] = _empty_of(a)
            continue
        if value is None:  # un vrai/faux absent : faux
            out[a.key] = False
            continue
        got, problem = _one(a, value)
        if problem:
            errors[a.key] = problem
        out[a.key] = got if got is not None else _empty_of(a)
    return out, errors


def said_args(specs: Sequence[ArgSpec]) -> str:
    """Les arguments d'un outil en quelques mots : « symbole (text), n (int, requis) » (vide : aucun)."""
    return ", ".join(f"{a.key} ({a.type}{', requis' if a.required else ''})" for a in specs)
