"""La passerelle LLM : routage par rôle, persona exigée, créneaux à priorité.

- Un rôle « voix » sans persona est refusé (``MissingPersona``) : tout ce
  qu'elle dit, pense, écrit ou rêve passe par la même persona.
- Chaque fournisseur a un nombre de créneaux ; un appel au premier plan
  (priorité 0) passe devant les appels de fond en attente et, sur un
  fournisseur à préemption (un modèle local à un créneau), interrompt l'appel
  de fond en cours — qui se règle en ``preempted`` et sera reproposé.
- Chaque appel laisse une trace (rôle, fournisseur, modèle, jetons, cache,
  coût, latence, issue).
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from mika.adapters.llm.pricing import price_usd
from mika.kernel.clock import Clock
from mika.ports.llm import PREEMPTED, LLMBackend, LLMRequest, LLMResponse, MissingPersona, Usage

#: les derniers appels gardés en mémoire
TRACES_KEPT = 2000


class UnconfiguredRole(LookupError):
    def __init__(self, role: str) -> None:
        self.role = role
        super().__init__(f"aucun modèle associé au rôle « {role} »")


@dataclass(slots=True)
class LLMTrace:
    at: int
    role: str
    backend: str
    model: str
    lane: str
    priority: int
    latency_us: int
    wait_us: int
    input_tokens: int
    output_tokens: int
    outcome: str
    call_id: str
    cache_read: int = 0
    cache_write: int = 0
    cost_usd: float = 0.0
    #: l'épisode (ou le passage d'un processus) qui a fait l'appel : de quoi
    #: retrouver ses appels après un redémarrage
    correlation: str = ""


def correlation_of(req: LLMRequest) -> str:
    """L'épisode d'un appel : ``meta["episode"]`` s'il est dit, sinon ce qui
    précède ``#`` dans l'identifiant d'appel (``<passage>#<n>``)."""
    episode = req.meta.get("episode") if req.meta else None
    if episode:
        return str(episode)
    return req.call_id.split("#", 1)[0]


class PrioritySlots:
    """``n`` créneaux ; les demandes de plus basse priorité numérique passent d'abord."""

    def __init__(self, n: int) -> None:
        self.n = max(1, n)
        self._used = 0
        self._waiters: list[tuple[int, int, asyncio.Future[None]]] = []
        self._counter = itertools.count()
        self._holders: dict[int, tuple[int, asyncio.Task[Any] | None]] = {}
        self._tokens = itertools.count()

    @property
    def busy(self) -> int:
        return self._used

    async def acquire(self, priority: int, *, preempt: bool = False) -> int:
        if self._used < self.n and not self._waiters:
            self._used += 1
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
                self._used -= 1  # octroyé puis annulé avant de reprendre : on le rend
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
        if self._holders.pop(token, None) is None:
            return
        self._used -= 1
        self._wake_next()

    def _wake_next(self) -> None:
        while self._waiters and self._used < self.n:
            _p, _c, fut = heapq.heappop(self._waiters)
            if not fut.done():
                self._used += 1
                fut.set_result(None)


class Gateway:
    def __init__(
        self,
        backends: Mapping[str, LLMBackend],
        routes: Mapping[str, str],
        *,
        clock: Clock,
        voice_roles: frozenset[str] = frozenset(),
        fallbacks: Mapping[str, str] | None = None,
        slots: Mapping[str, int] | None = None,
        preempt: frozenset[str] = frozenset(),
        on_trace: Callable[[LLMTrace], None] | None = None,
        pricing: Mapping[str, tuple[str, str]] | None = None,
    ) -> None:
        self.backends = dict(backends)
        self.routes = dict(routes)
        self.clock = clock
        self.voice_roles = voice_roles
        self.fallbacks = dict(fallbacks or {})
        self._slots = {name: PrioritySlots((slots or {}).get(name, 4)) for name in self.backends}
        self.preempt = preempt
        #: les derniers appels (bornés : le détail durable va dans ``CallLog``)
        self.traces: deque[LLMTrace] = deque(maxlen=TRACES_KEPT)
        self._on_trace = on_trace
        #: fournisseur → (type, durée du cache) : de quoi chiffrer un appel
        self.pricing = dict(pricing or {})

    def is_voice(self, role: str) -> bool:
        return role in self.voice_roles

    def resolve(self, role: str) -> str:
        seen = set()
        r: str | None = role
        while r is not None and r not in seen:
            seen.add(r)
            if r in self.routes and self.routes[r] in self.backends:
                return self.routes[r]
            r = self.fallbacks.get(r)
        raise UnconfiguredRole(role)

    async def call(self, req: LLMRequest) -> LLMResponse:
        if self.is_voice(req.role) and req.persona is None:
            raise MissingPersona(f"le rôle voix « {req.role} » exige une persona")
        name = self.resolve(req.role)
        backend = self.backends[name]
        slots = self._slots[name]
        t_wait = self.clock.now()
        token = await slots.acquire(req.priority, preempt=name in self.preempt)
        t0 = self.clock.now()
        outcome = "ok"
        resp: LLMResponse | None = None
        try:
            resp = await backend.complete(req)
            return resp
        except asyncio.CancelledError as exc:
            outcome = "preempted" if PREEMPTED in exc.args else "cancelled"
            raise
        except TimeoutError:
            outcome = "timeout"
            raise
        except Exception as exc:
            outcome = f"error:{type(exc).__name__}"
            raise
        finally:
            slots.release(token)
            self._trace(req, name, resp, t_wait, t0, outcome)

    def _trace(self, req: LLMRequest, backend: str, resp: LLMResponse | None, t_wait: int, t0: int, outcome: str) -> None:
        now = self.clock.now()
        usage = resp.usage if resp else Usage()
        cost = 0.0
        if resp is not None and backend in self.pricing:
            kind, ttl = self.pricing[backend]
            cost = price_usd(resp.model, usage, provider=kind, cache_ttl=ttl)
        tr = LLMTrace(
            at=now, role=req.role, backend=backend, model=resp.model if resp else "", lane=req.lane,
            priority=req.priority, latency_us=now - t0, wait_us=t0 - t_wait,
            input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, outcome=outcome,
            call_id=req.call_id, cache_read=usage.cache_read, cache_write=usage.cache_write, cost_usd=cost,
            correlation=correlation_of(req),
        )
        self.traces.append(tr)
        if self._on_trace is not None:
            self._on_trace(tr)
