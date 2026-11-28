"""Identifiants injectés.

Les identifiants d'événements sont des ULID : 48 bits de temps (millisecondes)
puis 80 bits d'aléa, encodés en base32 de Crockford (26 caractères). En
simulation l'aléa vient d'un générateur graine ; en production d'un adaptateur.
"""

from __future__ import annotations

import random
from typing import Protocol

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def encode_ulid(ms: int, rand80: int) -> str:
    value = ((ms & ((1 << 48) - 1)) << 80) | (rand80 & ((1 << 80) - 1))
    out = []
    for _ in range(26):
        out.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(out))


class IdGen(Protocol):
    def new(self, at: int) -> str: ...


class SeededIdGen:
    """ULID déterministes et monotones : même graine, mêmes identifiants."""

    def __init__(self, seed: int | str = 0) -> None:
        self._rng = random.Random(f"ids:{seed}")
        self._last_ms = -1
        self._last_rand = 0

    def new(self, at: int) -> str:
        ms = int(at) // 1000
        if ms <= self._last_ms:
            ms = self._last_ms
            rand = self._last_rand + 1
        else:
            rand = self._rng.getrandbits(80)
        self._last_ms, self._last_rand = ms, rand
        return encode_ulid(ms, rand)
