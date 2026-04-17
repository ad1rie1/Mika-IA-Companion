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
  - ``env_fallback`` bridges the existing ``.env``: until a subsystem
    migrates to ``config_service.get(...)``, the effective value still
    flows through Django settings; the registry just surfaces it.
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
    env_fallback: str = ""          # Django settings attribute name to read as legacy default
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
