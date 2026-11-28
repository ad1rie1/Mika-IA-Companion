"""Les sources réelles du temps et des identifiants."""

from __future__ import annotations

import asyncio
import os
import time

from mika.kernel.clock import US, Instant
from mika.kernel.ids import encode_ulid


class RealClock:
    def now(self) -> Instant:
        return Instant(time.time_ns() // 1000)

    async def sleep_until(self, t: int) -> None:
        delay = (int(t) - self.now()) / US
        await asyncio.sleep(max(0.0, delay))


class RandomIdGen:
    """ULID monotones à aléa système."""

    def __init__(self) -> None:
        self._last_ms = -1
        self._last_rand = 0

    def new(self, at: int) -> str:
        ms = int(at) // 1000
        if ms <= self._last_ms:
            ms = self._last_ms
            rand = self._last_rand + 1
        else:
            rand = int.from_bytes(os.urandom(10), "big")
        self._last_ms, self._last_rand = ms, rand
        return encode_ulid(ms, rand)
