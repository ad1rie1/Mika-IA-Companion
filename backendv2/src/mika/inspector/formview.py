"""Des champs décrits (``kernel/forms.py``) aux contrôles que rend
``_blocks.html`` : libellé, aide, valeur en texte, erreur. Un secret n'a jamais
de valeur rendue (vide = inchangé)."""

from __future__ import annotations

import json
import secrets as _secrets
from collections.abc import Mapping, Sequence
from typing import Any

from mika.kernel import forms
from mika.kernel.faculty import ActionSpec

#: les sortes de champ que le gabarit sait rendre ; les autres deviennent du texte
TEMPLATE_KINDS = {"bool": "bool", "select": "select", "textarea": "textarea", "lines": "lines", "yaml": "yaml",
                  "secret": "secret", "slider": "slider", "int": "int", "float": "float", "duration": "text",
                  "subject": "text", "text": "text"}


def field_view(f: forms.FormField, value: Any, *, error: str = "", prefix: str = "f") -> dict[str, Any] | None:
    if f.kind in ("group", "records", "mapping"):
        return None
    kind = TEMPLATE_KINDS.get(f.kind, "text")
    text = forms.as_text(f, value) if value is not None else ""
    return {
        "path": f.path, "id": f"{prefix}-{f.path.replace('.', '-')}", "label": f.label,
        "help": f.help, "kind": kind, "value": (value is True) if kind == "bool" else text,
        "error": error, "unit": f.unit if kind != "slider" else "", "readonly": f.readonly,
        "required": f.required and kind != "bool", "choices": list(f.choices), "lo": f.lo, "hi": f.hi,
        "step": f.step, "has_value": bool(value) if kind == "secret" else False,
        "only": "|".join(f"{path}={'|'.join(vals)}" for path, vals in f.only[:1]) if f.only else "",
        "rows": 8 if kind in ("textarea", "yaml") else 4,
    }


def action_view(spec: ActionSpec, *, csrf: str, back: str, subject: str = "", initial: Mapping[str, Any] | None = None,
                values: Mapping[str, Any] | None = None, errors: Mapping[str, str] | None = None,
                dynamic: Sequence[forms.FormField] | None = None) -> dict[str, Any]:
    """Le formulaire d'une action : ses champs (depuis son modèle d'arguments, ou
    ``dynamic`` pour une action aux champs connus à l'exécution), son jeton de
    formulaire et son jeton d'unicité (un double envoi ne refait rien). Les valeurs
    initiales qui ne sont pas des champs sont reposées telles quelles (``_fixes``)."""
    errors = dict(errors or {})
    fields = tuple(dynamic) if dynamic is not None else forms.describe(spec.args)
    defaults = {f.path: f.default for f in fields}
    given = {**defaults, **dict(initial or {}), **dict(values or {})}
    prefix = f"a-{spec.owner}-{spec.name}-{_secrets.token_hex(3)}"
    views = [v for f in fields if (v := field_view(f, given.get(f.path), error=errors.get(f.path, ""),
                                                   prefix=prefix)) is not None]
    paths = {f.path for f in fields}
    fixed = [(k, str(v)) for k, v in dict(initial or {}).items() if k not in paths and not k.startswith("_")]
    button = str(dict(initial or {}).get("_bouton", "") or spec.title)
    return {"url": f"/inspecteur/action/{spec.key}", "csrf": csrf, "nonce": _secrets.token_urlsafe(12),
            "back": back, "title": button, "description": spec.description, "fields": views,
            "retype": spec.retype, "subject": subject, "confirm": spec.confirm, "danger": spec.danger,
            "button": button, "errors": errors, "id": prefix, "key": spec.key, "fixed": fixed}


def slot_key(action: str, initial: Sequence[tuple[str, str]] | Mapping[str, str]) -> str:
    """La clé d'un formulaire en place (``ActionSlot``) : l'action et ses valeurs initiales."""
    return f"{action}|{json.dumps(dict(initial), sort_keys=True)}"
