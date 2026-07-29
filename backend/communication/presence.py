"""Presence registry — the runtime directory of reachable interlocutors.

Every channel (consumer or module) registers *who* it can currently reach and
*where* (the delivery handle). This is the bridge that lets the pipeline route
an outbound message to a specific person on a specific transport instead of
broadcasting to everyone.

Ownership distinction (mirrors the consumer/module split):
- **Consumer** (web, app — transports we own): reachable only while connected.
  Registered on connect, unregistered on disconnect.
- **Module** (Telegram, Discord — external APIs): reachable as long as we hold
  a handle (chat_id), because we can push to the API at any time.

The registry is in-memory and process-local (consistent with the rest of the
engine running single-process). The persistent identity layer — mapping memory
``Entity`` names to these handles for concern-based routing — builds on top of
this in a later step.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Iterable

logger = logging.getLogger(__name__)

# Channels group names must be ASCII alnum / hyphen / period / underscore.
_GROUP_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def person_group(person_id: str) -> str:
    """Return the per-person WebSocket group name for a consumer target."""
    safe = _GROUP_SAFE.sub("-", person_id)[:80]
    return f"vtuber_person_{safe}"


@dataclass
class Interlocutor:
    """A reachable conversation endpoint for one person on one channel."""

    person_id: str
    channel: str                 # "web", "telegram", ... (module name for modules)
    kind: str                    # "consumer" | "module"
    delivery_ref: str = ""       # consumer: per-person group; module: chat_id/etc.
    display_name: str = ""
    reachable: bool = True
    last_inbound_at: float | None = None
    last_outbound_at: float | None = None
    meta: dict = field(default_factory=dict)
    # Live connections backing this entry, by opaque connection id (a
    # consumer's ``channel_name``). One entry can have several: two browser
    # tabs, or the overlap between a dying socket and its replacement. Empty
    # for module handles, which are not backed by a connection at all.
    connections: set[str] = field(default_factory=set)

    @property
    def is_consumer(self) -> bool:
        return self.kind == "consumer"

    @property
    def is_module(self) -> bool:
        return self.kind == "module"


class PresenceRegistry:
    """Process-local directory of who Mika can currently reach, and where.

    Keyed by ``(person_id, channel)`` so the same person reachable on several
    channels keeps one entry per channel.
    """

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], Interlocutor] = {}
        self._lock = threading.Lock()

    # ── Registration ──────────────────────────────────────────────

    def register(
        self,
        person_id: str,
        channel: str,
        kind: str,
        delivery_ref: str = "",
        display_name: str = "",
        reachable: bool = True,
        connection_id: str = "",
        **meta,
    ) -> Interlocutor:
        """Register (or refresh) a reachable interlocutor.

        Called by consumers on connect and by modules when they see a user.
        Refreshing keeps the entry's timestamps but updates the handle.

        ``connection_id`` identifies the socket behind this registration. It
        is what makes a second tab additive rather than a no-op, and what
        stops the first tab's disconnect from erasing it — see
        :meth:`unregister`. Modules pass nothing: their reachability is not
        backed by a connection.
        """
        key = (person_id, channel)
        with self._lock:
            existing = self._by_key.get(key)
            if existing:
                existing.delivery_ref = delivery_ref or existing.delivery_ref
                existing.display_name = display_name or existing.display_name
                existing.reachable = reachable
                if meta:
                    existing.meta.update(meta)
                interlocutor = existing
            else:
                interlocutor = Interlocutor(
                    person_id=person_id,
                    channel=channel,
                    kind=kind,
                    delivery_ref=delivery_ref,
                    display_name=display_name,
                    reachable=reachable,
                    meta=dict(meta),
                )
                self._by_key[key] = interlocutor
            if connection_id:
                interlocutor.connections.add(connection_id)
        logger.debug("Presence register: %s on %s (%s)", person_id, channel, kind)
        return interlocutor

    def unregister(
        self, person_id: str, channel: str, connection_id: str = "",
    ) -> None:
        """Drop one connection's claim on an interlocutor.

        The entry itself survives while *any* other connection still backs
        it. This is not a refinement, it is the difference between working
        and not: the registry is keyed by ``(person_id, channel)``, so two
        browser tabs share one entry, and an unconditional removal on the
        first disconnect left the second tab connected, in its group, and
        never sent anything again — ``broadcast_to_websocket`` deliberately
        stays silent when a person resolves to nothing. The same race
        happens with a single tab: ``reconnectNow()`` opens the replacement
        socket before the old one's ``disconnect`` is dispatched, so the
        late arrival would have erased a live connection's presence.

        Called without a ``connection_id`` — modules, tests, forced eviction
        — it removes the entry outright, which is the old behaviour.
        """
        with self._lock:
            entry = self._by_key.get((person_id, channel))
            if entry is None:
                return
            if connection_id and entry.connections:
                entry.connections.discard(connection_id)
                if entry.connections:
                    logger.debug(
                        "Presence keep: %s on %s (%d connection(s) left)",
                        person_id, channel, len(entry.connections),
                    )
                    return
            self._by_key.pop((person_id, channel), None)
        logger.debug("Presence unregister: %s on %s", person_id, channel)

    def mark_unreachable(self, person_id: str, channel: str) -> None:
        """Keep the handle but mark it currently unreachable (e.g. module offline)."""
        with self._lock:
            entry = self._by_key.get((person_id, channel))
            if entry:
                entry.reachable = False

    # ── Lookup ────────────────────────────────────────────────────

    def resolve(self, person_id: str) -> list[Interlocutor]:
        """All channels on which a person is currently reachable."""
        with self._lock:
            return [
                i for (pid, _), i in self._by_key.items()
                if pid == person_id and i.reachable
            ]

    def resolve_on(self, person_id: str, channel: str) -> Interlocutor | None:
        with self._lock:
            entry = self._by_key.get((person_id, channel))
            return entry if entry and entry.reachable else None

    def reachable(self) -> list[Interlocutor]:
        """Everyone Mika can reach right now (used by concern-based routing)."""
        with self._lock:
            return [i for i in self._by_key.values() if i.reachable]

    def all(self) -> Iterable[Interlocutor]:
        with self._lock:
            return list(self._by_key.values())


# Module-level singleton, consistent with the other engine singletons.
presence_registry = PresenceRegistry()
