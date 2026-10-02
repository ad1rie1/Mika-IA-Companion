"""Des champs décrits (``kernel/forms.py``) aux contrôles que rend
``_blocks.html`` : libellé, aide, valeur en texte, erreur. Un secret n'a jamais
de valeur rendue (vide = inchangé)."""

from __future__ import annotations

import dataclasses
import json
import secrets as _secrets
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from mika.kernel import forms
from mika.kernel.faculty import ActionSpec

#: les sortes de champ que le gabarit sait rendre ; les autres deviennent du texte
TEMPLATE_KINDS = {"bool": "bool", "select": "select", "textarea": "textarea", "lines": "lines", "yaml": "yaml",
                  "secret": "secret", "slider": "slider", "int": "int", "float": "float", "duration": "text",
                  "subject": "text", "text": "text", "datetime": "datetime", "file": "file"}
#: ce qu'une case à cocher envoie quand elle l'est (un formulaire remontré relit ces textes)
_CHECKED = frozenset({"on", "true", "1", "oui"})


def checked(value: Any) -> bool:
    """Une case cochée : ``True``, ou le texte qu'une case cochée poste (« on »)."""
    return value is True or (isinstance(value, str) and value.strip().lower() in _CHECKED)


def field_view(f: forms.FormField, value: Any, *, error: str = "", prefix: str = "f") -> dict[str, Any] | None:
    if f.kind in ("group", "records", "mapping", "hidden"):
        return None
    kind = TEMPLATE_KINDS.get(f.kind, "text")
    text = forms.as_text(f, value) if value is not None and kind not in ("bool", "file") else ""
    return {
        "path": f.path, "id": f"{prefix}-{f.path.replace('.', '-')}", "label": f.label,
        "help": f.help, "kind": kind, "value": checked(value) if kind == "bool" else "" if kind == "file" else text,
        "error": error, "unit": _unit(f), "readonly": f.readonly,
        "required": f.required and kind != "bool", "choices": list(f.choices), "lo": f.lo, "hi": f.hi,
        "step": f.step, "has_value": bool(value) if kind == "secret" else False,
        "only": only_attr(f),
        "rows": _rows(text, kind), "group": f.group,
    }


#: l'unité d'un champ telle qu'on la lit en français
UNITS_FR = {"tokens": "jetons", "us": "µs"}


def _unit(f: forms.FormField) -> str:
    """L'unité montrée à côté du libellé : jamais pour un curseur (sa valeur s'affiche) ni pour une
    durée (elle se tape avec son unité : « 1 h 30 »)."""
    if f.kind in ("slider", "duration"):
        return ""
    return UNITS_FR.get(f.unit, f.unit)


def only_attr(f: forms.FormField) -> str:
    """Les conditions d'affichage d'un champ pour ``console.js`` : ``chemin=v1|v2``
    reliées par « ; » (toutes), et des alternatives reliées par « || » (l'une)."""
    def one(only: forms.Only) -> str:
        return ";".join(f"{path}={'|'.join(vals)}" for path, vals in only)

    if not f.only and not f.only_any:
        return ""
    alternatives = [tuple(f.only) + tuple(alt) for alt in f.only_any] or [tuple(f.only)]
    return "||".join(one(alt) for alt in alternatives)


def _rows(text: str, kind: str) -> int:
    """Une zone de texte à la taille de ce qu'elle contient (bornée)."""
    lines = text.count("\n") + 1 + len(text) // 110
    return max(3 if kind != "yaml" else 6, min(16, lines + 1))


def action_view(spec: ActionSpec, *, csrf: str, back: str, subject: str = "", initial: Mapping[str, Any] | None = None,
                values: Mapping[str, Any] | None = None, errors: Mapping[str, str] | None = None,
                dynamic: Sequence[forms.FormField] | None = None,
                subjects: Callable[[str], Sequence[tuple[str, str]]] | None = None) -> dict[str, Any]:
    """Le formulaire d'une action : ses champs (depuis son modèle d'arguments, ou
    ``dynamic`` pour une action aux champs connus à l'exécution), son jeton de
    formulaire et son jeton d'unicité (un double envoi ne refait rien). Les valeurs
    initiales qui ne sont pas des champs sont reposées telles quelles (``_fixes``)."""
    errors = dict(errors or {})
    fields = tuple(dynamic) if dynamic is not None else forms.describe(spec.args)
    defaults = {f.path: f.default for f in fields}
    given = {**defaults, **dict(initial or {}), **dict(values or {})}
    if subjects is not None:  # une personne, un but… : un choix parmi ceux que la console connaît
        fields = tuple(_as_choice(f, subjects(f.subject), given.get(f.path)) if f.kind == "subject" and f.subject
                       else f for f in fields)
    prefix = f"a-{spec.owner}-{spec.name}-{_secrets.token_hex(3)}"
    views = [v for f in fields if (v := field_view(f, given.get(f.path), error=errors.get(f.path, ""),
                                                   prefix=prefix)) is not None]
    # un champ caché (posé par la page) repart comme une valeur fixée, pas comme un champ
    paths = {f.path for f in fields if f.kind != "hidden"}
    fixed = [(k, str(v)) for k, v in dict(initial or {}).items() if k not in paths and not k.startswith("_")]
    button = str(dict(initial or {}).get("_bouton", "") or spec.title)
    return {"url": f"/inspecteur/action/{spec.key}", "csrf": csrf, "nonce": _secrets.token_urlsafe(12),
            "back": back, "title": button, "description": spec.description, "fields": views,
            "retype": spec.retype, "subject": subject, "confirm": spec.confirm, "danger": spec.danger,
            "button": button, "errors": errors, "id": prefix, "key": spec.key, "fixed": fixed,
            "multipart": any(f.kind == "file" for f in fields)}


def _as_choice(f: forms.FormField, choices: Sequence[tuple[str, str]], value: Any) -> forms.FormField:
    pairs = tuple(choices)
    if not pairs:
        return f  # rien de connu : le champ reste à taper
    if value not in (None, "") and str(value) not in {v for v, _ in pairs}:
        pairs = ((str(value), f"{value} (tapé)"), *pairs)
    return dataclasses.replace(f, kind="select", choices=pairs)


def visible_fields(view: Mapping[str, Any]) -> int:
    """Combien de champs un opérateur remplit dans ce formulaire (au-delà de deux : une page à part)."""
    return len([f for f in view.get("fields", ()) if f.get("kind") != "hidden"])


def slot_key(action: str, initial: Sequence[tuple[str, str]] | Mapping[str, str]) -> str:
    """La clé d'un formulaire en place (``ActionSlot``) : l'action et ses valeurs initiales."""
    return f"{action}|{json.dumps(dict(initial), sort_keys=True)}"
