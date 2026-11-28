"""``presence`` : les connexions vivantes (volatile, reconstruite par les
adaptateurs au démarrage), et qui est en train de lui écrire."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from mika.contracts import presence as c
from mika.contracts import runtime as rt
from mika.kernel.faculty import Faculty
from mika.kernel.state import FrozenDict


@dataclass(frozen=True, slots=True)
class Link:
    handle: str
    channel: str
    #: l'audience de la connexion (un salon, un groupe) : pour l'inspecteur
    room: str | None = None
    public: bool = False


@dataclass(frozen=True, slots=True)
class Typing:
    """Une saisie en cours : depuis quand (la première connexion qui l'a dit), et sur quelles connexions."""

    since: int
    connections: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PresenceState:
    links: FrozenDict[str, Link] = field(default_factory=FrozenDict)  # connexion → adresse
    since: FrozenDict[str, int] = field(default_factory=FrozenDict)  # adresse → début de présence
    composing: FrozenDict[str, Typing] = field(default_factory=FrozenDict)  # adresse → saisie en cours


PRESENCE = Faculty("presence", state=PresenceState, init=lambda p: PresenceState(), volatile=True)
PRESENCE.declare(*c.ALL)


def linked_handles(s: PresenceState) -> set[str]:
    return {link.handle for link in s.links.values()}


def _stop_typing(s: PresenceState, handle: str, connection: str) -> PresenceState:
    """Cette connexion n'écrit plus ; la saisie de l'adresse se clôt quand plus aucune n'écrit."""
    typing = s.composing.get(handle)
    if typing is None or connection not in typing.connections:
        return s
    rest = tuple(x for x in typing.connections if x != connection)
    composing = s.composing.set(handle, replace(typing, connections=rest)) if rest else s.composing.delete(handle)
    return replace(s, composing=composing)


@PRESENCE.reducer(c.CONNECTED)
def _connected(s: PresenceState, e, cx) -> PresenceState:
    d = e.data
    since = s.since if d.handle in s.since else s.since.set(d.handle, e.at)
    link = Link(d.handle, d.channel, d.room, d.public)
    return replace(s, links=s.links.set(d.connection, link), since=since)


@PRESENCE.reducer(c.DISCONNECTED)
def _disconnected(s: PresenceState, e, cx) -> PresenceState:
    link = s.links.get(e.data.connection)
    if link is None:
        return s
    s = replace(s, links=s.links.delete(e.data.connection))
    if link.handle not in linked_handles(s):
        s = replace(s, since=s.since.delete(link.handle))
    return _stop_typing(s, link.handle, e.data.connection)


@PRESENCE.reducer(c.COMPOSE)
def _composing(s: PresenceState, e, cx) -> PresenceState:
    """Le début d'une saisie (sur une connexion vivante de cette adresse), ou sa fin. Une saisie déjà en cours
    garde son début : le plafond compte la saisie continue, pas chaque écran."""
    d = e.data
    if not d.on:
        return _stop_typing(s, d.handle, d.connection)
    link = s.links.get(d.connection)
    if link is None or link.handle != d.handle:
        return s
    typing = s.composing.get(d.handle)
    if typing is None:
        typing = Typing(e.at, (d.connection,))
    elif d.connection not in typing.connections:
        typing = replace(typing, connections=(*typing.connections, d.connection))
    return replace(s, composing=s.composing.set(d.handle, typing))


@PRESENCE.reducer(rt.PERCEPTION_RECEIVED)
def _sent(s: PresenceState, e, cx) -> PresenceState:
    """Le message envoyé clôt la saisie de son adresse, sans rien écrire de plus."""
    if e.data.handle not in s.composing:
        return s
    return replace(s, composing=s.composing.delete(e.data.handle))


@PRESENCE.fact(c.PRESENT)
def _present(s: PresenceState, cx) -> tuple[str, ...]:
    return tuple(sorted(linked_handles(s)))


@PRESENCE.fact(c.SINCE)
def _since(s: PresenceState, cx, handle: str) -> int | None:
    return s.since.get(handle)


@PRESENCE.fact(c.COMPOSING)
def _composing_since(s: PresenceState, cx, handle: str) -> int | None:
    """Le début de la saisie en cours ; au-delà du plafond, plus rien : elle n'attend pas indéfiniment."""
    typing = s.composing.get(handle)
    if typing is None or cx.now - typing.since >= c.COMPOSING_MAX_US:
        return None
    return typing.since


# la console : les connexions vivantes, et le vital « Présents »
from mika.faculties.presence import inspect as inspect  # noqa: E402 — s'enregistre sur PRESENCE
