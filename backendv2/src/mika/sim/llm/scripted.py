"""LLM factices déterministes : scripté, et modèles de latence.

La latence est un vrai délai *simulé* : un message peut arriver pendant qu'un
épisode attend le modèle, exactement comme en production.
"""

from __future__ import annotations

import inspect
import math
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from mika.kernel.clock import US, Clock
from mika.kernel.codec import h64
from mika.ports.llm import LLMRequest, LLMResponse, Usage

Responder = Callable[[LLMRequest], "LLMResponse | Awaitable[LLMResponse]"]


class UnexpectedCall(AssertionError):
    pass


@dataclass(frozen=True, slots=True)
class LognormalLatency:
    median_s: float
    sigma: float = 0.5
    seed: int | str = 0

    def __call__(self, req: LLMRequest) -> float:
        r = random.Random(h64("latence", self.seed, req.call_id, len(req.messages)))
        return self.median_s * math.exp(self.sigma * r.gauss(0.0, 1.0))


class ScriptedLLM:
    """Répond par une fonction (ou lève si aucune réponse n'est prévue)."""

    def __init__(
        self,
        clock: Clock,
        respond: Responder,
        *,
        latency: Callable[[LLMRequest], float] | float = 0.0,
        name: str = "scripted",
        model: str = "fake-1",
    ) -> None:
        self.clock = clock
        self.respond = respond
        self.latency = latency
        self.name = name
        self.model = model
        self.calls: list[LLMRequest] = []

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.calls.append(req)
        lat = self.latency(req) if callable(self.latency) else float(self.latency)
        if lat > 0:
            await self.clock.sleep_until(self.clock.now() + round(lat * US))
        out = self.respond(req)
        if inspect.isawaitable(out):
            out = await out
        if out is None:
            raise UnexpectedCall(f"appel non prévu : rôle {req.role}, {req.call_id}")
        if not out.model:
            out = LLMResponse(out.text, out.tool_calls, out.stop, _usage(req, out), self.model, out.truncated_tool_call)
        return out


def _usage(req: LLMRequest, resp: LLMResponse) -> Usage:
    chars = len(req.system_stable) + len(req.system_volatile) + sum(len(m.content) for m in req.messages)
    return Usage(input_tokens=chars // 4, output_tokens=len(resp.text) // 4)


def text(t: str) -> LLMResponse:
    return LLMResponse(t)
