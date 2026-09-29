"""Harnais M1 : Mika composée pour de vrai, sur horloge virtuelle, avec un
LLM scripté et un port de livraison qui enregistre."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from mika.adapters.llm.gateway import Gateway
from mika.adapters.store_sqlite import SqliteStore
from mika.adapters.vectors import HashEmbedder, SqliteVectorIndex
from mika.app import composition
from mika.contracts import presence as presence_c
from mika.contracts import social as social_c
from mika.contracts.runtime import PerceptionReceived
from mika.faculties.self import load
from mika.kernel.clock import instant
from mika.kernel.events import Content, Origin
from mika.kernel.ids import SeededIdGen
from mika.ports.delivery import Delivery
from mika.ports.llm import LLMRequest, LLMResponse
from mika.runtime.bootstrap import Kernel
from mika.sim.clock import SimClock
from mika.sim.llm.scripted import ScriptedLLM
from mika.vocab.episodes import VOICE_ROLES, Role

PARIS = ZoneInfo("Europe/Paris")
PERSONA_PATH = Path(__file__).resolve().parents[2] / "persona" / "mika.yaml"
DOC = load(PERSONA_PATH)


def at_paris(year: int, month: int, day: int, hour: int, minute: int = 0) -> int:
    return instant(datetime(year, month, day, hour, minute, tzinfo=PARIS))


#: Un lundi à 14 h, heure de Paris.
AFTERNOON = at_paris(2026, 9, 28, 14, 0)


class Deliveries:
    def __init__(self) -> None:
        self.items: list[Delivery] = []

    async def deliver(self, d: Delivery) -> bool:
        self.items.append(d)
        return True


def reply(text: str) -> Callable[[LLMRequest], LLMResponse]:
    return lambda req: LLMResponse(text)


def build(
    tmp: Path,
    respond: Callable[[LLMRequest], Any],
    *,
    latency: Callable[[LLMRequest], float] | float = 0.0,
    start: int = AFTERNOON,
    seed: int = 0,
    clock: SimClock | None = None,
    **kw: Any,
) -> tuple[Kernel, SimClock, ScriptedLLM, Deliveries]:
    clock = clock or SimClock(start)
    llm = ScriptedLLM(clock, respond, latency=latency)
    llm = kw.pop("llm", None) or llm
    gateway = Gateway({"fake": llm}, {str(r): "fake" for r in Role}, clock=clock,
                      voice_roles=frozenset(str(r) for r in VOICE_ROLES), slots={"fake": 1},
                      preempt=frozenset({"fake"}))
    store = SqliteStore(tmp / "mind.db", tmp / "views.db", threaded=False)
    deliveries = Deliveries()
    ports = {"delivery": deliveries, "vectors": SqliteVectorIndex(store, HashEmbedder()), **kw.pop("ports", {})}
    deps = composition.deps(store=store, clock=clock, ids=SeededIdGen(seed), gateway=gateway, ports=ports,
                            seed=seed, **kw)
    return Kernel(deps), clock, llm, deliveries


async def boot(kernel: Kernel, doc=DOC) -> None:
    await kernel.start(configure=lambda k: composition.configure(k, doc))


async def connect(kernel: Kernel, handle: str, name: str = "", *, authenticated: bool = True,
                  connection: str | None = None, operator: bool = False) -> str:
    connection = connection or f"c-{handle}"
    account = int(handle.split("_", 1)[1]) if authenticated and handle.startswith("user_") else None
    await kernel.mind.append(
        [presence_c.CONNECTED.draft(handle=handle, channel="web", connection=connection,
                                    authenticated=authenticated, account=account, operator=operator,
                                    display_name=name)],
        emitter="presence", correlation=f"ws:{connection}", origin=Origin.EXTERNAL,
    )
    return connection


async def disconnect(kernel: Kernel, handle: str, connection: str | None = None) -> None:
    await kernel.mind.append(
        [presence_c.DISCONNECTED.draft(handle=handle, connection=connection or f"c-{handle}")],
        emitter="presence", correlation=f"ws:{connection or handle}", origin=Origin.EXTERNAL,
    )


async def befriend(kernel: Kernel, person: str, closeness: str = "friend") -> None:
    """La genèse d'un lien : un opérateur déclare la proximité (on ne la
    fabrique pas à la main dans l'état)."""
    await kernel.mind.append([social_c.CLOSENESS_SET.draft(person=person, closeness=closeness)], emitter="social",
                             correlation=f"genese:{person}", origin=Origin.GENESIS)


def said(handle: str, text: str, **kw: Any) -> PerceptionReceived:
    return PerceptionReceived(handle=handle, channel=kw.pop("channel", "web"), text=Content.of(text),
                              authenticated=kw.pop("authenticated", handle.startswith("user_")), **kw)
