"""Des créneaux à priorité : ``n`` appels à la fois vers un fournisseur, le
premier plan d'abord.

Partagés par les passerelles (modèles de langage, images) : les demandes de plus
basse priorité numérique passent d'abord ; ``reserved`` créneaux ne servent
qu'au premier plan (priorité 0) ; à la demande, le premier plan interrompt un
appel de fond en cours (``PREEMPTED``) quand tous les créneaux sont pris.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
from typing import Any

#: le message d'annulation d'un appel de fond interrompu par le premier plan
PREEMPTED = "préempté par le premier plan"


class PrioritySlots:
    """``n`` créneaux ; les demandes de plus basse priorité numérique passent
    d'abord ; ``reserved`` créneaux ne servent qu'au premier plan (priorité 0)."""

    def __init__(self, n: int, *, reserved: int = 0) -> None:
        self.n = max(1, n)
        self.reserved = max(0, min(reserved, self.n - 1))
        self._used = 0
        self._background = 0
        self._waiters: list[tuple[int, int, asyncio.Future[None]]] = []
        self._counter = itertools.count()
        self._holders: dict[int, tuple[int, asyncio.Task[Any] | None]] = {}
        self._tokens = itertools.count()

    @property
    def busy(self) -> int:
        return self._used

    @property
    def waiting(self) -> int:
        return sum(1 for _p, _c, fut in self._waiters if not fut.done())

    def _fits(self, priority: int) -> bool:
        if self._used >= self.n:
            return False
        return priority == 0 or self._background < self.n - self.reserved

    def _ahead(self, priority: int) -> bool:
        """Quelqu'un attend-il déjà, d'une priorité au moins aussi haute ?"""
        return any(not fut.done() and p <= priority for p, _c, fut in self._waiters)

    def _take(self, priority: int) -> None:
        self._used += 1
        if priority > 0:
            self._background += 1

    def _give_back(self, priority: int) -> None:
        self._used -= 1
        if priority > 0:
            self._background -= 1

    async def acquire(self, priority: int, *, preempt: bool = False) -> int:
        if self._fits(priority) and not self._ahead(priority):
            self._take(priority)
            return self._register(priority)
        if preempt and priority == 0 and self._used >= self.n:
            for _token, (prio, task) in list(self._holders.items()):
                if prio > 0 and task is not None and not task.done():
                    task.cancel(PREEMPTED)
                    break
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        entry = (priority, next(self._counter), fut)
        heapq.heappush(self._waiters, entry)
        try:
            await fut  # à l'octroi, _wake_next a déjà compté le créneau
        except BaseException:
            if fut.done() and not fut.cancelled():
                self._give_back(priority)  # octroyé puis annulé avant de reprendre : on le rend
                self._wake_next()
            else:
                try:
                    self._waiters.remove(entry)
                    heapq.heapify(self._waiters)
                except ValueError:
                    pass
            raise
        return self._register(priority)

    def _register(self, priority: int) -> int:
        token = next(self._tokens)
        self._holders[token] = (priority, asyncio.current_task())
        return token

    def release(self, token: int) -> None:
        held = self._holders.pop(token, None)
        if held is None:
            return
        self._give_back(held[0])
        self._wake_next()

    def _wake_next(self) -> None:
        while self._waiters:
            priority, _c, fut = self._waiters[0]
            if fut.done():
                heapq.heappop(self._waiters)
                continue
            if not self._fits(priority):
                return  # le premier en file est du fond, et le fond a sa part : le créneau réservé attend
            heapq.heappop(self._waiters)
            self._take(priority)
            fut.set_result(None)
