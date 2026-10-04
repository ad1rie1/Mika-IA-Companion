"""Un validateur minimal de JSON schema, pour les outils que d'autres décrivent (ADR 0064).

Il ne prétend pas tout vérifier — le serveur reste juge de ses arguments — mais refuse avant de faire partir quoi
que ce soit ce qui ne peut pas être juste : un argument requis absent, un type de premier niveau faux, une valeur
hors d'une énumération, une propriété inconnue quand le schéma les interdit. Rendu : la liste des problèmes, en
français (vide : rien à redire).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_TYPES: Mapping[str, tuple[type, ...]] = {
    "string": (str,), "integer": (int,), "number": (int, float), "boolean": (bool,), "array": (list, tuple),
    "object": (dict, Mapping), "null": (type(None),),
}
#: au-delà, on ne descend plus (un schéma récursif ne fait pas tourner en rond)
MAX_DEPTH = 4


def problems(schema: Mapping[str, Any], value: Any) -> list[str]:
    out: list[str] = []
    _check(schema, value, "les arguments", out, 0)
    return out[:10]


def _check(schema: Any, value: Any, where: str, out: list[str], depth: int) -> None:
    if not isinstance(schema, Mapping) or depth > MAX_DEPTH:
        return
    expected = schema.get("type")
    if expected is not None and not _is(value, expected):
        out.append(f"{where} : attendu {_words(expected)}")
        return
    if isinstance(schema.get("enum"), Sequence) and not isinstance(schema["enum"], str) \
            and value not in list(schema["enum"]):
        out.append(f"{where} : une valeur parmi {', '.join(repr(v) for v in list(schema['enum'])[:8])}")
    if isinstance(value, Mapping):
        props = schema.get("properties") if isinstance(schema.get("properties"), Mapping) else {}
        for name in schema.get("required") or ():
            if isinstance(name, str) and name not in value:
                out.append(f"« {name} » manque")
        if schema.get("additionalProperties") is False:
            for name in value:
                if name not in props:
                    out.append(f"« {name} » n'est pas un argument de cet outil")
        for name, sub in props.items():
            if name in value:
                _check(sub, value[name], f"« {name} »", out, depth + 1)
    elif isinstance(value, (list, tuple)) and isinstance(schema.get("items"), Mapping):
        for i, item in enumerate(value[:50]):
            _check(schema["items"], item, f"{where}[{i}]", out, depth + 1)


def _is(value: Any, expected: Any) -> bool:
    kinds = expected if isinstance(expected, list) else [expected]
    for kind in kinds:
        types = _TYPES.get(str(kind))
        if types is None:
            return True  # un type inconnu : on laisse le serveur juger
        if kind in ("integer", "number") and isinstance(value, bool):
            continue
        if kind == "integer" and isinstance(value, float) and value.is_integer():
            return True
        if isinstance(value, types):
            return True
    return False


def _words(expected: Any) -> str:
    names = {"string": "un texte", "integer": "un entier", "number": "un nombre", "boolean": "vrai ou faux",
             "array": "une liste", "object": "un objet", "null": "rien"}
    kinds = expected if isinstance(expected, list) else [expected]
    return " ou ".join(names.get(str(k), str(k)) for k in kinds)
