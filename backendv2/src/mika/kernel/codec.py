"""Encodage canonique : même valeur → mêmes octets, quel que soit le hasard
de hachage du processus. Sert aux empreintes (gardes, instantanés, tests de
déterminisme)."""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel


def to_plain(value: Any) -> Any:
    """Réduit une valeur à des types JSON, clés triées, ordre stable."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return repr(value)
        return value
    if isinstance(value, enum.Enum):
        return to_plain(value.value)
    if isinstance(value, BaseModel):
        return {k: to_plain(v) for k, v in sorted(value.model_dump(mode="python").items())}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {str(k): to_plain(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [to_plain(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((to_plain(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    if hasattr(value, "items") and callable(value.items):
        return {str(k): to_plain(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    raise TypeError(f"valeur non canonisable : {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(to_plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any, size: int = 16) -> str:
    return hashlib.blake2b(canonical_json(value).encode(), digest_size=size).hexdigest()


def h64(*parts: Any) -> int:
    """Entier 64 bits stable dérivé de ses arguments (graines de hasard)."""
    raw = "\x1f".join(str(p) for p in parts).encode()
    return int.from_bytes(hashlib.blake2b(raw, digest_size=8).digest(), "big")
