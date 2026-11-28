"""Harnais : un noyau complet sur horloge virtuelle, LLM scripté, facultés jouets."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from mika.adapters.llm.gateway import Gateway
from mika.adapters.store_sql import SqlStore
from mika.contracts.runtime import PERCEPTION_RECEIVED, PerceptionReceived
from mika.kernel.episode import EpisodePolicy
from mika.kernel.events import Content
from mika.kernel.facts import FactFamily
from mika.kernel.faculty import Faculty
from mika.kernel.frame import Audience
from mika.kernel.ids import SeededIdGen
from mika.kernel.registry import ArbitrationPolicy
from mika.kernel.state import FrozenDict
from mika.ports.llm import LLMRequest, LLMResponse, PersonaRender
from mika.runtime.bootstrap import Kernel, KernelDeps
from mika.sim.clock import SimClock
from mika.sim.llm.scripted import ScriptedLLM
from mika.vocab.privacy import ChannelTrust
from tests.conftest import START
from tests.fixtures import backend

# ── une faculté « contacts » qui lit les perceptions du runtime ──────────


@dataclass(frozen=True, slots=True)
class ContactsState:
    last_inbound: FrozenDict[str, int] = FrozenDict()


CONTACTS = Faculty("contacts", state=ContactsState, init=lambda p: ContactsState())
LAST_SEEN = FactFamily("contacts.last_inbound", arg=str, type=int)


@CONTACTS.reducer(PERCEPTION_RECEIVED)
def _seen(s: ContactsState, e, cx) -> ContactsState:
    return replace(s, last_inbound=s.last_inbound.set(e.data.handle, e.at))


@CONTACTS.fact(LAST_SEEN)
def _last_seen(s: ContactsState, cx, who: str) -> int:
    return s.last_inbound.get(who, 0)


def persona(frame: Any, depth: str) -> PersonaRender:
    return PersonaRender("Tu es Mika.", "persona-test", depth)


DEFAULT_POLICIES = {
    "REPLY": EpisodePolicy(kind="REPLY", role="reply", priority=0, lane="conversation"),
    "INITIATIVE": EpisodePolicy(kind="INITIATIVE", role="initiative", priority=1, lane="conversation"),
    "STEP": EpisodePolicy(kind="STEP", role="step", priority=1, lane="background", delivered=False,
                          visible=False, tool_bundles=frozenset({"atelier"})),
}


def echo(req: LLMRequest) -> LLMResponse:
    last = req.messages[-1].content if req.messages else ""
    return LLMResponse(f"réponse à : {last[-60:]}")


def build(
    tmp: Path,
    faculties: Iterable[Faculty[Any, Any]],
    *,
    respond: Callable[[LLMRequest], LLMResponse] = echo,
    latency: Callable[[LLMRequest], float] | float = 0.0,
    policies: Mapping[str, EpisodePolicy] | None = None,
    arbitration: ArbitrationPolicy | None = None,
    start: int = START,
    seed: int = 0,
    clock: SimClock | None = None,
    **kw: Any,
) -> tuple[Kernel, SimClock, ScriptedLLM]:
    clock = clock or SimClock(start)
    llm = ScriptedLLM(clock, respond, latency=latency)
    gateway = Gateway(
        {"fake": llm}, {"reply": "fake", "initiative": "fake", "step": "fake"}, clock=clock,
        voice_roles=frozenset({"reply", "initiative", "step"}), slots={"fake": 1}, preempt=frozenset({"fake"}),
    )
    store = SqlStore(*backend.store_targets(tmp), threaded=False)
    deps = KernelDeps(
        faculties=list(faculties), store=store, clock=clock, ids=SeededIdGen(seed), gateway=gateway,
        policies=policies or DEFAULT_POLICIES, arbitration=arbitration, persona=persona, seed=seed, **kw,
    )
    return Kernel(deps), clock, llm


def said(handle: str, text: str, **kw: Any) -> PerceptionReceived:
    return PerceptionReceived(handle=handle, channel=kw.pop("channel", "web"), text=Content.of(text), **kw)


def facing(frame: Any, req: Any) -> Audience:
    """Qui est en face, dans un jouet sans faculté d'identité : la personne à qui l'épisode s'adresse, reconnue, en
    tête-à-tête — de quoi passer la porte de ses outils (ADR 0134 : sans personne en face, rien). À donner au noyau
    par ``build(..., audience_of=facing)`` ; sans lui, l'audience fermée du runtime."""
    target = str(getattr(req, "target", "") or "")
    return Audience(persons=(target,) if target else (), channel=getattr(req, "channel", None) or "web",
                    public=False, trust=ChannelTrust.AUTHENTICATED.value, person=target)


def events_of(kernel: Kernel, *types: str) -> list[Any]:
    names = set(types)
    return [kernel.mind.decode(s) for s in kernel.mind.store.read(types=names or None)]
