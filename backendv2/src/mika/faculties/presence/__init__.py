"""``presence`` : les connexions vivantes (volatile, reconstruite par les
adaptateurs au démarrage)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from mika.contracts import presence as c
from mika.kernel.faculty import Faculty
from mika.kernel.state import FrozenDict


@dataclass(frozen=True, slots=True)
class Link:
    handle: str
    channel: str


@dataclass(frozen=True, slots=True)
class PresenceState:
    links: FrozenDict[str, Link] = field(default_factory=FrozenDict)  # connexion → poignée
    since: FrozenDict[str, int] = field(default_factory=FrozenDict)  # poignée → début de présence


PRESENCE = Faculty("presence", state=PresenceState, init=lambda p: PresenceState(), volatile=True)
PRESENCE.declare(*c.ALL)


def _handles(s: PresenceState) -> set[str]:
    return {link.handle for link in s.links.values()}


@PRESENCE.reducer(c.CONNECTED)
def _connected(s: PresenceState, e, cx) -> PresenceState:
    d = e.data
    since = s.since if d.handle in s.since else s.since.set(d.handle, e.at)
    return replace(s, links=s.links.set(d.connection, Link(d.handle, d.channel)), since=since)


@PRESENCE.reducer(c.DISCONNECTED)
def _disconnected(s: PresenceState, e, cx) -> PresenceState:
    link = s.links.get(e.data.connection)
    if link is None:
        return s
    s = replace(s, links=s.links.delete(e.data.connection))
    if link.handle not in _handles(s):
        s = replace(s, since=s.since.delete(link.handle))
    return s


@PRESENCE.fact(c.PRESENT)
def _present(s: PresenceState, cx) -> tuple[str, ...]:
    return tuple(sorted(_handles(s)))


@PRESENCE.fact(c.SINCE)
def _since(s: PresenceState, cx, handle: str) -> int | None:
    return s.since.get(handle)
