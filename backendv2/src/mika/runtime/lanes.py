"""Les voies d'épisodes : une file à priorité et une capacité par voie.

La voie ``conversation`` a une capacité de 1 — une seule voix à la fois — et
fait passer le premier plan (répondre à quelqu'un) devant les initiatives.
Au-delà de ``max_pending`` demandes en attente, une nouvelle demande est
refusée à voix haute (``overloaded``), jamais oubliée.

**Une réponse par tour.** Les demandes de réponse d'une même personne au même
endroit se fondent tant qu'elles attendent leur tour : la demande en file
répond désormais au dernier message (et le modèle verra les précédents dans
le fil) ; chacun de ceux qui attendaient reçoit ce même compte rendu.

**Une réponse n'attend pas.** Quand une demande de premier plan arrive dans
une voie pleine d'épisodes moins prioritaires (une initiative en train de se
composer, qui attend peut-être elle-même un modèle tenu par le fond), l'un
d'eux est interrompu (``preempted``) : l'arbitre le reproposera plus tard.
"""

from __future__ import annotations

import asyncio
import itertools
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from mika.runtime.boundary import Failed, acall
from mika.runtime.pipeline import EpisodeReport, EpisodeRequest, EpisodeRunner

REPORTS_KEPT = 256


@dataclass(slots=True)
class _Slot:
    """Une demande en file — celle d'un tour de réponse se met à jour tant qu'elle attend."""

    req: EpisodeRequest
    futures: list[asyncio.Future[EpisodeReport]] = field(default_factory=list)
    key: tuple[str, str, str | None] | None = None


class Lanes:
    def __init__(
        self,
        runner: EpisodeRunner,
        *,
        capacities: Mapping[str, int] | None = None,
        max_pending: int = 100,
    ) -> None:
        self.runner = runner
        self.capacities = dict(capacities or {"conversation": 1, "background": 2})
        self.max_pending = max_pending
        self._queues: dict[str, asyncio.PriorityQueue[Any]] = {
            name: asyncio.PriorityQueue() for name in self.capacities
        }
        self._counter = itertools.count()
        self._workers: list[asyncio.Task[None]] = []
        #: les tours de réponse en file (pas encore commencés), par (type, adresse, salon)
        self._waiting: dict[tuple[str, str, str | None], _Slot] = {}
        #: les épisodes en cours par voie
        self._busy: dict[str, int] = dict.fromkeys(self.capacities, 0)
        self._stopping = False
        #: les derniers comptes rendus d'épisode (bornés : le détail durable est
        #: dans le journal et les traces d'épisode)
        self.reports: deque[EpisodeReport] = deque(maxlen=REPORTS_KEPT)

    def lane_of(self, kind: str) -> str:
        policy = self.runner.policies[kind]
        return policy.lane if policy.lane in self._queues else "background"

    def pending(self, lane: str) -> int:
        return self._queues[lane].qsize()

    def full(self, kind: str) -> bool:
        """Une demande de ce type serait-elle refusée faute de place ?"""
        return self._queues[self.lane_of(kind)].qsize() >= self.max_pending

    def submit(self, req: EpisodeRequest) -> asyncio.Future[EpisodeReport] | None:
        lane = self.lane_of(req.kind)
        fut: asyncio.Future[EpisodeReport] = asyncio.get_running_loop().create_future()
        key = _turn_key(req)
        slot = self._waiting.get(key) if key is not None else None
        if slot is not None:
            # le même tour attend déjà : il répondra au dernier message
            if req.reply_to is not None and (slot.req.reply_to is None or req.reply_to > slot.req.reply_to):
                slot.req = replace(req, priority=min(req.priority, slot.req.priority))
            slot.futures.append(fut)
            return fut
        q = self._queues[lane]
        if q.qsize() >= self.max_pending:
            return None
        slot = _Slot(req, [fut], key)
        if key is not None:
            self._waiting[key] = slot
        q.put_nowait((req.priority, next(self._counter), slot))
        if req.priority == 0 and self._busy.get(lane, 0) >= self.capacities.get(lane, 1):
            preempt = getattr(self.runner, "preempt", None)
            if preempt is not None:
                preempt(lane)  # une réponse ne passe pas derrière une initiative
        return fut

    def start(self) -> None:
        for lane, n in self.capacities.items():
            for i in range(n):
                self._workers.append(asyncio.create_task(self._worker(lane), name=f"voie:{lane}:{i}"))

    async def _worker(self, lane: str) -> None:
        q = self._queues[lane]
        while True:
            _prio, _n, slot = await q.get()
            if slot.key is not None and self._waiting.get(slot.key) is slot:
                del self._waiting[slot.key]  # il commence : un nouveau message le supplantera
            self._busy[lane] = self._busy.get(lane, 0) + 1
            try:
                try:
                    out = await acall(self.runner.run, slot.req, label=f"épisode {slot.req.kind}")
                except asyncio.CancelledError:
                    if self._stopping:
                        raise
                    # une annulation égarée (une préemption arrivée après le règlement) : l'épisode est
                    # réglé, la voie, elle, ne meurt pas — sinon plus rien n'y passerait jamais
                    me = asyncio.current_task()
                    if me is not None:
                        me.uncancel()
                    out = Failed(RuntimeError("épisode annulé hors de son déroulé"))
                if isinstance(out, Failed):
                    for fut in slot.futures:
                        if not fut.done():
                            fut.set_exception(out.error)
                else:
                    self.reports.append(out)
                    for fut in slot.futures:
                        if not fut.done():
                            fut.set_result(out)
            finally:
                self._busy[lane] -= 1
                q.task_done()

    async def join(self) -> None:
        for q in self._queues.values():
            await q.join()

    async def stop(self) -> None:
        self._stopping = True
        for t in self._workers:
            t.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()


def _turn_key(req: EpisodeRequest) -> tuple[str, str, str | None] | None:
    """Le tour d'une demande de réponse : (type, adresse, salon). ``None`` pour ce qui ne répond à rien."""
    if req.reply_to is None or not req.target:
        return None
    return (req.kind, req.target, req.room)
