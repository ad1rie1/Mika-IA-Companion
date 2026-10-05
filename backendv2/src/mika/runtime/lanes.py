"""Les voies d'épisodes : une file à priorité et des ouvriers par voie.

La voie ``conversation`` fait passer le premier plan (répondre à quelqu'un)
devant les initiatives. Elle peut avoir plusieurs ouvriers
(``app/composition.py``) : des réponses à des personnes différentes se
composent alors en même temps — quelqu'un qui écrit « coucou » n'attend pas
qu'une longue recherche faite pour une autre soit finie. Mais **une seule
réponse à la fois par personne** (rien ne commence vers quelqu'un à qui elle est
en train de répondre), et au plus ``secondary_caps`` épisodes qui ne sont pas du
premier plan en cours dans la voie (une initiative, un murmure : un à la fois).
Ce qui ne peut pas encore commencer attend sans tenir d'ouvrier ; la fin d'un
épisode de la voie le remet en file, à sa place.
Au-delà de ``max_pending`` demandes en attente, une nouvelle demande est
refusée à voix haute (``overloaded``), jamais oubliée.

**Une réponse par tour.** Les demandes de réponse d'une même personne au même
endroit se fondent tant qu'elles attendent leur tour : la demande en file
répond désormais au dernier message (et le modèle verra les précédents dans
le fil) ; chacun de ceux qui attendaient reçoit ce même compte rendu.

**Une réponse n'attend pas.** Quand une demande de premier plan arrive dans
une voie pleine, ou qu'un épisode moins prioritaire y est en cours (une
initiative en train de se composer, qui attend peut-être elle-même un modèle
tenu par le fond), l'un d'eux est interrompu (``preempted``) — comme avec un
seul ouvrier : l'arbitre le reproposera plus tard.
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
        secondary_caps: Mapping[str, int] | None = None,
        max_pending: int = 100,
    ) -> None:
        self.runner = runner
        #: les ouvriers de chaque voie
        self.capacities = dict(capacities or {"conversation": 1, "background": 2})
        #: au plus combien d'épisodes qui ne sont pas du premier plan (priorité > 0) en cours, par voie ; une
        #: voie absente n'a que ses ouvriers pour borne
        self.secondary_caps = {name: max(1, n) for name, n in (secondary_caps or {"conversation": 1}).items()}
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
        #: ceux d'entre eux qui ne sont pas du premier plan
        self._secondary: dict[str, int] = dict.fromkeys(self.capacities, 0)
        #: les réponses en cours, par (voie, adresse) : une seule à la fois par personne
        self._answering: dict[tuple[str, str], int] = {}
        #: les demandes tirées de la file qui ne pouvaient pas encore commencer, par voie
        self._parked: dict[str, list[tuple[int, int, _Slot]]] = {name: [] for name in self.capacities}
        self._stopping = False
        #: les derniers comptes rendus d'épisode (bornés : le détail durable est
        #: dans le journal et les traces d'épisode)
        self.reports: deque[EpisodeReport] = deque(maxlen=REPORTS_KEPT)

    def lane_of(self, kind: str) -> str:
        policy = self.runner.policies[kind]
        return policy.lane if policy.lane in self._queues else "background"

    def pending(self, lane: str) -> int:
        return self._queues[lane].qsize() + len(self._parked[lane])

    def full(self, kind: str) -> bool:
        """Une demande de ce type serait-elle refusée faute de place ?"""
        return self.pending(self.lane_of(kind)) >= self.max_pending

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
        if self.pending(lane) >= self.max_pending:
            return None
        slot = _Slot(req, [fut], key)
        if key is not None:
            self._waiting[key] = slot
        self._queues[lane].put_nowait((req.priority, next(self._counter), slot))
        workers = self.capacities.get(lane, 1)
        # une réponse ne passe pas derrière une initiative : plus d'ouvrier libre, ou la voie a son compte
        # d'épisodes secondaires (l'initiative en cours cède, comme avec un seul ouvrier)
        if req.priority == 0 and (self._busy.get(lane, 0) >= workers
                                  or self._secondary.get(lane, 0) >= self.secondary_caps.get(lane, workers)):
            preempt = getattr(self.runner, "preempt", None)
            if preempt is not None:
                preempt(lane)
        return fut

    def start(self) -> None:
        for lane, n in self.capacities.items():
            for i in range(n):
                self._workers.append(asyncio.create_task(self._worker(lane), name=f"voie:{lane}:{i}"))

    async def _worker(self, lane: str) -> None:
        q = self._queues[lane]
        while True:
            item = await q.get()
            slot = item[2]
            if not self._may_start(lane, slot.req):
                # elle attend sans tenir l'ouvrier (et son tour peut encore se mettre à jour) ; la fin d'un
                # épisode de la voie la remet en file
                self._parked[lane].append(item)
                continue
            if slot.key is not None and self._waiting.get(slot.key) is slot:
                del self._waiting[slot.key]  # il commence : un nouveau message le supplantera
            req = slot.req
            answering = (lane, req.target) if req.priority == 0 and req.target else None
            self._busy[lane] = self._busy.get(lane, 0) + 1
            if req.priority > 0:
                self._secondary[lane] = self._secondary.get(lane, 0) + 1
            if answering is not None:
                self._answering[answering] = self._answering.get(answering, 0) + 1
            try:
                try:
                    out = await acall(self.runner.run, req, label=f"épisode {req.kind}")
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
                if req.priority > 0:
                    self._secondary[lane] -= 1
                if answering is not None:
                    left = self._answering.pop(answering) - 1
                    if left > 0:
                        self._answering[answering] = left
                self._unpark(lane)
                q.task_done()

    def _may_start(self, lane: str, req: EpisodeRequest) -> bool:
        """Peut-elle commencer maintenant ? Pas tant qu'une réponse à sa personne est en cours (une seule voix
        à la fois pour quelqu'un : la demande attend son tour, et un nouveau message s'y fond encore), ni,
        si elle n'est pas du premier plan, tant que la voie a déjà son compte d'épisodes secondaires."""
        if req.target and self._answering.get((lane, req.target), 0) > 0:
            return False
        cap = self.secondary_caps.get(lane)
        return req.priority == 0 or cap is None or self._secondary.get(lane, 0) < cap

    def _unpark(self, lane: str) -> None:
        """Ce qui attendait et peut maintenant commencer repart dans la file, à sa place (même priorité, même
        rang). Remis en file avant d'être compté comme traité : ``join`` ne voit jamais la voie vide entre deux."""
        parked = self._parked[lane]
        if not parked:
            return
        q = self._queues[lane]
        kept = []
        for item in parked:
            if self._may_start(lane, item[2].req):
                q.put_nowait(item)
                q.task_done()
            else:
                kept.append(item)
        self._parked[lane] = kept

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
