"""Formulaires d'actions de panneaux : même validation en natif et en Forge."""
from __future__ import annotations

from dataclasses import dataclass
from copy import copy
import hashlib
import json
import math
import re

from django import forms

FIELD_TYPES = {"text", "textarea", "integer", "number", "boolean", "select", "email", "url", "hidden"}
KEY = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


@dataclass(frozen=True)
class Input:
    key: str
    label: str = ""
    type: str = "text"
    required: bool | None = None
    initial: object = None
    help: str = ""
    choices: tuple = ()  # (valeur, libellé)
    minimum: float | None = None
    maximum: float | None = None
    max_length: int = 4000

    def __post_init__(self):
        if self.required is None:
            object.__setattr__(self, "required", self.type != "boolean")


class InvalidAction(Exception):
    def __init__(self, key, form):
        self.key, self.form = key, form
        super().__init__("Corrigez les champs signalés avant de continuer.")


def action_instance(key, initial):
    return hashlib.sha256(json.dumps([key, initial or {}], sort_keys=True, default=str).encode()).hexdigest()[:16]


def request_for_panel(request, path):
    """Représente la page après une erreur, en conservant la saisie POST.

    Les handlers construisent leurs liens depuis cette URL de lecture et non
    depuis l'endpoint d'action, qui refuse les GET. La requête initiale reste
    intacte pour les middlewares.
    """
    page_request = copy(request)
    page_request.path = path
    page_request.path_info = path.removeprefix(request.META.get("SCRIPT_NAME", ""))
    return page_request


def input_from_spec(raw) -> Input:
    if not isinstance(raw, dict) or not KEY.fullmatch(str(raw.get("key", ""))):
        raise ValueError("clé de champ invalide")
    unknown = set(raw) - set(Input.__dataclass_fields__)
    if unknown:
        raise ValueError(f"options de champ inconnues : {', '.join(sorted(map(str, unknown)))}")
    kind = raw.get("type", "text")
    if kind not in FIELD_TYPES:
        raise ValueError(f"type de champ inconnu : {kind}")
    if "required" in raw and not isinstance(raw["required"], bool):
        raise ValueError("required doit être un booléen")
    choices = raw.get("choices", [])
    if not isinstance(choices, list) or len(choices) > 100:
        raise ValueError("choices doit contenir au plus 100 choix")
    opts = []
    for value in choices:
        if isinstance(value, dict):
            if set(value) != {"value", "label"}:
                raise ValueError("un choix requiert value et label")
            opts.append((str(value["value"]), str(value["label"])))
        elif isinstance(value, str):
            opts.append((str(value), str(value)))
        else:
            raise ValueError("un choix doit être une chaîne ou un objet {value, label}")
    if kind == "select" and not opts:
        raise ValueError("un champ select requiert des choices")
    limits = []
    for name in ("minimum", "maximum"):
        value = raw.get(name)
        if value is not None:
            value = float(value)
            if not math.isfinite(value):
                raise ValueError(f"{name} doit être fini")
        limits.append(value)
    if all(v is not None for v in limits) and limits[0] > limits[1]:
        raise ValueError("minimum supérieur à maximum")
    return Input(str(raw["key"]), str(raw.get("label") or raw["key"])[:100], kind,
                 raw.get("required"), raw.get("initial"), str(raw.get("help", ""))[:500],
                 tuple(opts), *limits, max(1, min(20000, int(raw.get("max_length", 4000)))))


def build_form(action, *, data=None, initial=None, prefix=None):
    form = forms.Form(data=data, initial=initial, prefix=prefix)
    for spec in action.fields:
        kw = dict(label=spec.label or spec.key, required=spec.required,
                  initial=spec.initial, help_text=spec.help)
        if spec.type in {"number", "integer"}:
            cls = forms.IntegerField if spec.type == "integer" else forms.FloatField
            field = cls(min_value=spec.minimum, max_value=spec.maximum, **kw)
        elif spec.type == "boolean":
            field = forms.BooleanField(**kw)
        elif spec.type == "select":
            choices = spec.choices if spec.required else (("", "—"),) + spec.choices
            field = forms.ChoiceField(choices=choices, **kw)
        else:
            cls = {"email": forms.EmailField, "url": forms.URLField}.get(spec.type, forms.CharField)
            widget = {"textarea": forms.Textarea, "hidden": forms.HiddenInput}.get(spec.type)
            field = cls(max_length=spec.max_length, **kw, **({"widget": widget} if widget else {}))
        form.fields[spec.key] = field
    return form
