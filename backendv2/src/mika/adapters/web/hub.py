"""Le concentrateur des connexions WebSocket, et la livraison vers elles.

Une connexion appartient à une poignée ; une poignée peut avoir plusieurs
onglets. Ce qu'elle dit à quelqu'un ne part qu'aux connexions de cette
poignée — une personne absente rattrape par l'historique, jamais par une
diffusion à tout le monde. Seul ce qui n'est adressé à personne (une pensée
à voix haute) part à tous.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from mika.adapters.web import protocol
from mika.contracts import affect as affect_c
from mika.contracts import identity as identity_c
from mika.contracts.entry import MindPort
from mika.ports.delivery import Delivery
from mika.vocab.people import is_internal

log = logging.getLogger("mika.web")

Send = Callable[[dict[str, Any]], Awaitable[None]]
SYNC_INTERVAL_S = 3.0
MIN_INTENSITY_DELTA = 0.04


@dataclass(slots=True)
class Conn:
    id: str
    send: Send
    handle: str
    authenticated: bool = False
    account: int | None = None
    operator: bool = False
    display_name: str = ""
    announced: bool = False
    chat: protocol.RateLimiter = field(default_factory=lambda: protocol.RateLimiter(*protocol.CHAT_RATE))
    control: protocol.RateLimiter = field(default_factory=lambda: protocol.RateLimiter(*protocol.CONTROL_RATE))


class Hub:
    def __init__(self, port: MindPort) -> None:
        self.port = port
        self.conns: dict[str, Conn] = {}
        self._counter = itertools.count(1)
        self._sent_face: dict[str, tuple[str, float, tuple[str, ...]]] = {}
        self._sync_task: asyncio.Task[None] | None = None
        self.delivered: list[str] = []

    # ── connexions ──
    def attach(self, send: Send, *, handle: str | None = None, **kw: Any) -> Conn:
        cid = f"ws{next(self._counter)}-{secrets.token_hex(4)}"
        conn = Conn(cid, send, handle or f"anon_{secrets.token_hex(6)}", **kw)
        self.conns[cid] = conn
        return conn

    def detach(self, conn: Conn) -> None:
        self.conns.pop(conn.id, None)
        if not self.of(conn.handle):
            self._sent_face.pop(conn.handle, None)

    def of(self, handle: str) -> list[Conn]:
        return [c for c in self.conns.values() if c.handle == handle]

    async def _send(self, conns: list[Conn], frame: dict[str, Any]) -> int:
        sent = 0
        for c in conns:
            try:
                await c.send(frame)
                sent += 1
            except Exception as exc:  # une connexion morte ne bloque pas les autres
                log.debug("envoi impossible sur %s : %r", c.id, exc)
        return sent

    async def send_to(self, handle: str, frame: dict[str, Any]) -> int:
        return await self._send(self.of(handle), frame)

    # ── livraison (port) ──
    async def deliver(self, d: Delivery) -> bool:
        if d.kind == "state":
            # son état a changé (elle s'endort, s'éveille) : sans parole, pour tout le monde
            await self._send(list(self.conns.values()), protocol.inner_state_update(self.port.frame(), None))
            return True
        if d.target is None or is_internal(d.target):
            targets = list(self.conns.values())
        else:
            targets = self.of(d.target)
        if not targets:
            return True  # personne de connecté : rattrapage par l'historique
        await self._send(targets, protocol.speech(d, present=True))
        self.delivered.append(d.key)
        frame = self.port.frame()
        if d.target is None:
            await self._send(targets, protocol.inner_state_update(frame, None))
        else:
            await self._send(targets, protocol.inner_state_update(frame, d.target, self.panel(d.target)))
        return True

    def panel(self, handle: str) -> dict[str, Any] | None:
        getter = getattr(self.port, "person_panel", None)
        if getter is None:
            return None
        try:
            return getter(handle)
        except Exception as exc:  # le panneau ne doit jamais empêcher une livraison
            log.debug("panneau de %s : %r", handle, exc)
            return None

    # ── émotion entre deux tours ──
    def face(self, handle: str) -> affect_c.Face:
        frame = self.port.frame()
        return frame.get(affect_c.FACE(frame.get(identity_c.PERSON(handle))))

    async def push_face(self, handle: str, *, force: bool = False) -> bool:
        face = self.face(handle)
        sig = protocol.face_signature(face)
        prev = self._sent_face.get(handle)
        if not force and prev is not None:
            moved = (sig[0] != prev[0] or sig[2] != prev[2] or abs(sig[1] - prev[1]) >= MIN_INTENSITY_DELTA)
            if not moved:
                return False
        self._sent_face[handle] = sig
        await self._send(self.of(handle), protocol.emotion_update(handle, face))
        return True

    async def sync_once(self) -> int:
        pushed = 0
        for handle in sorted({c.handle for c in self.conns.values()}):
            if await self.push_face(handle):
                pushed += 1
        return pushed

    async def run_sync(self, interval_s: float = SYNC_INTERVAL_S) -> None:
        while True:
            await asyncio.sleep(interval_s)
            try:
                await self.sync_once()
            except Exception as exc:  # la synchro ne doit jamais tomber
                log.warning("synchro d'émotion : %r", exc)

    def start(self) -> None:
        if self._sync_task is None:
            self._sync_task = asyncio.create_task(self.run_sync(), name="emotion-sync")

    async def stop(self) -> None:
        if self._sync_task is not None:
            self._sync_task.cancel()
            await asyncio.gather(self._sync_task, return_exceptions=True)
            self._sync_task = None
