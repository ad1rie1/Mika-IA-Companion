"""La frontière d'erreurs : le seul endroit où une exception quelconque est
attrapée. Ailleurs dans le domaine, une erreur est un fait (un événement, une
issue d'épisode), jamais un silence."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

log = logging.getLogger("mika")

T = TypeVar("T")


class Failed:
    """Résultat d'un appel qui a levé."""

    __slots__ = ("error",)

    def __init__(self, error: BaseException) -> None:
        self.error = error

    def __repr__(self) -> str:
        return f"Failed({self.error!r})"


def describe(error: BaseException) -> str:
    """Ce qu'une panne dit d'elle, brut (son type et son message, bornés) : pour une trace ou le détail d'un
    règlement. Ce n'est pas ``ports.errors.describe_error``, qui la traduit pour un opérateur."""
    return f"{type(error).__name__}: {error}"[:500]


def call(fn: Callable[..., T], *args: Any, label: str = "") -> T | Failed:
    try:
        return fn(*args)
    except Exception as exc:
        log.warning("%s a levé : %r", label or getattr(fn, "__name__", "?"), exc)
        return Failed(exc)


async def acall(fn: Callable[..., Awaitable[T]], *args: Any, label: str = "") -> T | Failed:
    try:
        return await fn(*args)
    except Exception as exc:
        log.warning("%s a levé : %r", label or getattr(fn, "__name__", "?"), exc)
        return Failed(exc)
