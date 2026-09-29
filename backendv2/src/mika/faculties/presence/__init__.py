"""``presence`` : les connexions vivantes (volatile, reconstruite par les
adaptateurs au démarrage)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from mika.contracts import identity as identity_c
from mika.contracts import presence as c
from mika.kernel.faculty import Faculty
from mika.kernel.frame import Frame
from mika.kernel.inspect import Block, Fields, InspectContext, Note, Ref, Table
from mika.kernel.state import FrozenDict
from mika.vocab.privacy import ChannelTrust


@dataclass(frozen=True, slots=True)
class Link:
    handle: str
    channel: str
    #: l'audience de la connexion (un salon, un groupe) : pour l'inspecteur
    room: str | None = None
    public: bool = False


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
    link = Link(d.handle, d.channel, d.room, d.public)
    return replace(s, links=s.links.set(d.connection, link), since=since)


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


# ── Inspection ────────────────────────────────────────────────────────────

#: Au plus tant de connexions listées.
MAX_LINKS = 200


def _audience(link: Link, trust: ChannelTrust) -> str:
    """Comme l'audience d'un épisode : un salon, ou un canal qui ne prouve
    rien, est public."""
    if link.room:
        return f"publique (salon « {link.room} »)"
    if link.public:
        return "publique (groupe)"
    if trust is ChannelTrust.PUBLIC:
        return "publique (rien ne prouve qui écrit)"
    return "privée"


@PRESENCE.inspect("presents", title="Présents")
def _inspect(s: PresenceState, frame: Frame, ctx: InspectContext) -> list[Block]:
    links = sorted(s.links.items(), key=lambda kv: (-s.since.get(kv[1].handle, 0), kv[0]))
    rows = []
    for connection, link in links[:MAX_LINKS]:
        view = frame.get(identity_c.IDENTITY(link.handle))
        since = s.since.get(link.handle)
        rows.append((Ref("view", "identity/personne", link.handle, (("handle", link.handle),)), view.name or "—",
                     link.channel or "—", connection, ctx.when(since) if since else "—",
                     _audience(link, view.trust),
                     Ref("view", "transcript/fil", "son fil", (("handle", link.handle),))))
    blocks: list[Block] = [
        Fields((("connexions vivantes", len(s.links)), ("poignées présentes", len(_handles(s))))),
        Table(("poignée", "nom", "canal", "connexion", "présente depuis", "audience", ""), tuple(rows),
              empty="personne n'est connecté"),
    ]
    if len(links) > MAX_LINKS:
        blocks.append(Note(f"Seules les {MAX_LINKS} connexions les plus récentes sont listées (sur {len(links)}).",
                           tone="mut"))
    return blocks
