"""Contrôles d'après-course : le monde réel a-t-il fui dans la simulation ?"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

from mika.ports.store import StoredEvent
from mika.sim.env import looks_like_sentinel

_MIN_US = 10**14  # un entier plus petit n'est pas un instant en microsecondes


def _numbers(value: Any) -> Iterator[int]:
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _numbers(v)
    elif isinstance(value, list):
        for v in value:
            yield from _numbers(v)


def sentinel_leaks(events: Iterable[StoredEvent]) -> list[tuple[int, str]]:
    """Événements dont l'horodatage ou une charge utile trahit l'heure système figée."""
    leaks = []
    for e in events:
        if looks_like_sentinel(e.at):
            leaks.append((e.seq, "at"))
            continue
        for n in _numbers(json.loads(e.data)):
            if n > _MIN_US and looks_like_sentinel(n):
                leaks.append((e.seq, "data"))
                break
    return leaks
