"""Le monde simulé : des interlocuteurs, un transport, des pannes.

Le noyau est le vrai (même composition que le serveur, fournie par
l'appelant) ; seuls l'horloge, le modèle et le transport sont simulés. Une
panne (``crash``) abandonne le noyau comme un ``kill -9`` : rien n'est
terminé proprement ; le redémarrage relit instantané + queue du même
magasin, et le monde continue.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mika.adapters.forge import ForgeHost
from mika.adapters.llm.gateway import Gateway
from mika.adapters.store_sqlite import SqliteStore
from mika.adapters.vectors import HashEmbedder, SqliteVectorIndex
from mika.adapters.workshop import BwrapWorkshop
from mika.contracts import presence as presence_c
from mika.contracts.runtime import PerceptionReceived
from mika.kernel.events import Content, Origin
from mika.kernel.ids import SeededIdGen
from mika.ports.delivery import REPLY_OUTCOMES, Delivery
from mika.ports.llm import LLMBackend
from mika.runtime.bootstrap import Kernel, KernelDeps
from mika.runtime.effects import with_content
from mika.sim.clock import SimClock
from mika.sim.outside import FakeFeeds, FakeMail
from mika.vocab.episodes import FALLBACKS


@dataclass(frozen=True, slots=True)
class Composition:
    """Ce que la racine de composition fournit au simulateur."""

    deps: Callable[..., KernelDeps]
    configure: Callable[[Kernel, Any], Awaitable[Any]]
    persona: Any
    voice_roles: frozenset[str]


@dataclass(frozen=True, slots=True)
class Heard:
    """Ce qu'un interlocuteur a reçu."""

    at: int
    key: str
    target: str | None
    text: str
    emotion: str
    declared: bool
    message_id: int
    reply_to: int | None
    room: str | None = None
    kind: str = "speech"


class Transport:
    """Le transport simulé : idempotent par clé (comme doit l'être tout
    transport réel) ; il compte les relivraisons de la file de sortie, et peut
    « mourir » pendant un envoi (``fail_next``) pour éprouver la reprise."""

    def __init__(self, clock: SimClock, online: Callable[[str], bool]) -> None:
        self.clock = clock
        self.online = online
        self.heard: list[Heard] = []
        self.delivered: set[str] = set()
        self.repeats = 0
        self.failures = 0
        self.fail_next = False
        self.states = 0
        #: les messages que le transport a appris sans réponse : (message, issue)
        self.no_replies: list[tuple[int | None, str]] = []

    async def deliver(self, d: Delivery) -> bool:
        if d.kind == "state":
            self.states += 1
            return True
        if d.kind in REPLY_OUTCOMES:
            self.no_replies.append((d.reply_to, d.source))
            return True
        if self.fail_next:
            self.fail_next = False
            self.failures += 1
            raise ConnectionError("le processus meurt pendant l'envoi")
        if d.key in self.delivered:
            self.repeats += 1
            return True  # déjà livré : on n'affiche pas deux fois
        self.delivered.add(d.key)
        if d.target is not None and not self.online(d.target):
            return True  # hors ligne : rattrapage par l'historique
        self.heard.append(Heard(self.clock.now(), d.key, d.target, d.text, d.emotion.emotion, d.emotion.declared,
                                d.message_id, d.reply_to, d.room, d.source))
        return True


@dataclass(slots=True)
class Driver:
    root: Path
    composition: Composition
    llm: LLMBackend
    clock: SimClock
    seed: int | str = 0
    slots: int = 1
    kernel: Kernel | None = None
    boots: int = 0
    crashes: int = 0
    online: set[str] = field(default_factory=set)
    connections: dict[str, str] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    #: les adresses d'opératrices (ses propriétaires, connectées avec leur compte)
    operators: set[str] = field(default_factory=set)
    transport: Transport | None = None
    #: le monde extérieur (il survit aux redémarrages du noyau)
    mail: FakeMail = field(default_factory=FakeMail)
    feeds: FakeFeeds = field(default_factory=FakeFeeds)
    #: les plongements de la mémoire (un vrai modèle pour la sonde ; par défaut, le hachage, déterministe et rapide)
    embedder: Any = None

    def __post_init__(self) -> None:
        # une messagerie (Telegram) reçoit même hors ligne : on y écrit à quelqu'un d'absent
        self.transport = Transport(self.clock, lambda h: h in self.online or h.startswith("tg_"))

    # ── cycle de vie ──
    async def boot(self) -> Kernel:
        roles = {r: self.llm.name for r in self.composition.voice_roles}
        gateway = Gateway({self.llm.name: self.llm}, roles, clock=self.clock,
                          voice_roles=self.composition.voice_roles, slots={self.llm.name: self.slots},
                          preempt=frozenset({self.llm.name}) if self.slots == 1 else frozenset(),
                          fallbacks={str(k): str(v) for k, v in FALLBACKS.items()})
        store = SqliteStore(self.root / "mind.db", self.root / "views.db", threaded=False)
        ports = {"delivery": self.transport, "vectors": SqliteVectorIndex(store, self.embedder or HashEmbedder()),
                 "workshop": BwrapWorkshop(self.root / "ateliers"), "mail": self.mail, "feeds": self.feeds,
                 "forge": ForgeHost(self.root / "forge")}
        deps = self.composition.deps(store=store, clock=self.clock, ids=SeededIdGen(f"{self.seed}:{self.boots}"),
                                     gateway=gateway, ports=ports, seed=f"{self.seed}:{self.boots}")
        self.kernel = Kernel(deps)
        self.boots += 1
        await self.kernel.start(configure=lambda k: self.composition.configure(k, self.composition.persona))
        # les clients encore là se reconnectent (la présence est volatile)
        for handle in sorted(self.online):
            await self._announce(handle)
        return self.kernel

    async def crash(self) -> None:
        assert self.kernel is not None
        await self.kernel.abort()
        self.crashes += 1
        self.kernel = None

    async def restart(self) -> Kernel:
        await self.crash()
        return await self.boot()

    async def stop(self) -> None:
        if self.kernel is not None:
            await self.kernel.lanes.join()
            await self.kernel.stop()
            self.kernel = None

    # ── le monde ──
    async def _announce(self, handle: str, name: str = "") -> None:
        assert self.kernel is not None
        conn = f"sim-{handle}-{self.boots}"
        self.connections[handle] = conn
        await self.kernel.mind.append(
            [presence_c.CONNECTED.draft(handle=handle, channel="web", connection=conn, authenticated=True,
                                        account=int(handle.split("_", 1)[1]) if handle.startswith("user_") else None,
                                        operator=handle in self.operators,
                                        display_name=name or self.names.get(handle, ""))],
            emitter="presence", correlation=f"sim:{conn}", origin=Origin.EXTERNAL,
        )

    async def connect(self, handle: str, name: str = "") -> None:
        self.names[handle] = name or self.names.get(handle, "")
        self.online.add(handle)
        await self._announce(handle, name)

    async def disconnect(self, handle: str) -> None:
        assert self.kernel is not None
        self.online.discard(handle)
        conn = self.connections.pop(handle, f"sim-{handle}")
        await self.kernel.mind.append([presence_c.DISCONNECTED.draft(handle=handle, connection=conn)],
                                      emitter="presence", correlation=f"sim:{conn}", origin=Origin.EXTERNAL)

    async def say(self, handle: str, text: str, *, wait: bool = True, key: str | None = None,
                  room: str | None = None, addressed: bool = True) -> Any:
        """Un message : web authentifié pour ``user_…``, Telegram pour ``tg_…``
        (privé, ou dans le salon ``room``)."""
        assert self.kernel is not None
        telegram = handle.startswith("tg_")
        p = PerceptionReceived(handle=handle, channel="telegram" if telegram else "web", text=Content.of(text),
                               authenticated=not telegram, display_name=self.names.get(handle, ""),
                               client_msg_id=key, room=room, public=room is not None, addressed=addressed,
                               reply_ref=room or (handle[3:] if telegram else None))
        got = await self.kernel.perceive(p, dedupe_key=f"{handle}:{key}" if key else None)
        if wait and got.reply is not None:
            try:
                return await got.reply
            except asyncio.CancelledError:
                return None
        return got

    def read_events(self) -> list[Any]:
        """Le journal complet, textes restitués (pour les mesures)."""
        assert self.kernel is not None
        mind = self.kernel.mind
        return [with_content(mind, mind.decode(s)) for s in mind.store.read()]
