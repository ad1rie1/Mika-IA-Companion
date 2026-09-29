"""Ce que le soi garde de ses nuits (typé : les instantanés le sérialisent)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Journal:
    day: str
    text_ref: str
    about: tuple[str, ...]
    dominant: str
    at: int


@dataclass(frozen=True, slots=True)
class Dream:
    id: int
    night: str
    text_ref: str
    kind: str
    vividness: float
    emotion: str
    about: tuple[str, ...]
    sensitivity: int
    at: int
    recalled: bool = False
