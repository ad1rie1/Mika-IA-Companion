"""Les voies d'épisodes : une file à priorité et une capacité par voie.

La voie ``conversation`` a une capacité de 1 — une seule voix à la fois — et
fait passer le premier plan (répondre à quelqu'un) devant les initiatives.
Au-delà de ``max_pending`` demandes en attente, une nouvelle demande est
refusée à voix haute (``overloaded``), jamais oubliée.
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Mapping
from typing import Any

from mika.runtime.boundary import Failed, acall
from mika.runtime.pipeline import EpisodeReport, EpisodeRequest, EpisodeRunner


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
        self.reports: list[EpisodeReport] = []

    def lane_of(self, kind: str) -> str:
        policy = self.runner.policies[kind]
        return policy.lane if policy.lane in self._queues else "background"

    def pending(self, lane: str) -> int:
        return self._queues[lane].qsize()

    def submit(self, req: EpisodeRequest) -> asyncio.Future[EpisodeReport] | None:
        lane = self.lane_of(req.kind)
        q = self._queues[lane]
        if q.qsize() >= self.max_pending:
            return None
        fut: asyncio.Future[EpisodeReport] = asyncio.get_running_loop().create_future()
        q.put_nowait((req.priority, next(self._counter), req, fut))
        return fut

    def start(self) -> None:
        for lane, n in self.capacities.items():
            for i in range(n):
                self._workers.append(asyncio.create_task(self._worker(lane), name=f"voie:{lane}:{i}"))

    async def _worker(self, lane: str) -> None:
        q = self._queues[lane]
        while True:
            _prio, _n, req, fut = await q.get()
            try:
                out = await acall(self.runner.run, req, label=f"épisode {req.kind}")
                if isinstance(out, Failed):
                    if not fut.done():
                        fut.set_exception(out.error)
                else:
                    self.reports.append(out)
                    if not fut.done():
                        fut.set_result(out)
            finally:
                q.task_done()

    async def join(self) -> None:
        for q in self._queues.values():
            await q.join()

    async def stop(self) -> None:
        for t in self._workers:
            t.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
