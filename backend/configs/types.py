"""Declarative config schema types.

Any app / module declares its configurable settings as ``ConfigItem``
or ``ConfigRecordList`` instances wrapped in ``ConfigSection`` groups.
The central ``ConfigRegistry`` aggregates them and the ``ConfigService``
resolves live values.

Design notes:
  - **Pure dataclasses, no Django.** Import me from anywhere without
    pulling the app registry.
  - **Extensible type enum.** The current UI handles scalar types; new
    structural types (record / record_list) can be declared now and
    consumed later.
  - **One declared default per knob.** There is deliberately no bridge
    back to ``.env``: a ``ConfigItem`` carrying an ``env_fallback`` meant
    two declared defaults for one setting, the settings one silently
    winning at seed time, so the ``default`` below — the one a reader
    looks at — was decorative and free to drift.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

ValueType = Literal[
    "str", "text", "int", "float", "bool",
    "secret",              # sensitive — redacted in read path
    "select",              # choices required
    "multiselect",
    "list",                # list of scalars
    "record_list",         # list of objects, item schema via ``record``
    "yaml_block",          # for personality.yaml-style structured blocks
]

Validator = Callable[[Any], str | None]  # returns error msg or None


@dataclass(frozen=True)
class ConfigSection:
    """One sidebar entry under Configuration.

    Sections without items are ignored by the UI but reserved for future
    expansion (e.g. a module appearing before declaring any setting).
    """
    key: str
    label: str
    icon: str = "⚙"
    description: str = ""
    order: int = 100


@dataclass(frozen=True)
class ConfigItem:
    """One configurable setting.

    The ``key`` is a dotted path — e.g. ``conscience.act_threshold``.
    The first segment conventionally matches the ``section`` key,
    but that is not enforced.
    """
    key: str
    type: ValueType
    section: str
    label: str
    group: str = ""
    description: str = ""
    default: Any = None
    choices: tuple = ()             # for select / multiselect
    min: float | None = None
    max: float | None = None
    sensitive: bool = False
    hot_reload: bool = False
    restart_required: bool = False
    validators: tuple[Validator, ...] = ()
    hint: str = ""
    readonly: bool = False
    # for record_list only:
    record: "ConfigRecord | None" = None
    min_items: int = 0
    max_items: int | None = None


@dataclass(frozen=True)
class ConfigRecord:
    """Sub-schema for one element of a ``record_list``.

    ``fields`` are ``ConfigItem`` instances *without* ``section`` —
    the parent record_list carries the section.
    """
    name: str
    label: str
    fields: tuple["ConfigItem", ...]
    description: str = ""


def record_item(**kw) -> ConfigItem:
    """Helper to declare a field inside a ``ConfigRecord`` — the
    ``section`` attribute is irrelevant for sub-fields but the
    dataclass requires it, so we fill a sentinel."""
    kw.setdefault("section", "__record__")
    return ConfigItem(**kw)


# ── Choix ───────────────────────────────────────────────────────
#
# ``choices`` accepte deux formes : une valeur nue (``"claude"``), ou un
# couple ``(valeur, libellé)`` quand ce qui est stocké n'est pas ce qu'on veut
# lire. Le cas qui l'a rendu nécessaire : l'humeur par défaut du tempérament.
# La valeur stockée est le nom canonique d'``emotion/types.py`` — celui que le
# modèle produit dans sa balise ``[EMOTION:...]`` et qui compose la variable
# CSS — mais une liste déroulante d'administration en français ne peut pas
# proposer « mischievous ». Traduire à l'affichage sans toucher au stockage
# suppose donc de séparer les deux, ici plutôt que dans chaque déclarant.

def choice_values(choices) -> tuple:
    """Les valeurs acceptables, quelle que soit la forme déclarée."""
    return tuple(
        c[0] if isinstance(c, (tuple, list)) else c
        for c in (choices or ())
    )


def choice_options(choices) -> list[tuple[str, str]]:
    """Couples ``(valeur, libellé)`` prêts pour un ``<option>``.

    Une valeur nue est son propre libellé — c'est le cas courant, et il ne
    doit rien coûter à déclarer.
    """
    out: list[tuple[str, str]] = []
    for c in choices or ():
        if isinstance(c, (tuple, list)):
            value = c[0]
            label = c[1] if len(c) > 1 else value
        else:
            value = label = c
        out.append((str(value), str(label)))
    return out
