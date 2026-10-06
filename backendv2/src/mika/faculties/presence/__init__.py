"""``presence`` : les connexions vivantes (volatile, reconstruite par les
adaptateurs au démarrage), et qui est en train de lui écrire."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from mika.contracts import identity as identity_c
from mika.contracts import presence as c
from mika.contracts import runtime as rt
from mika.kernel.faculty import Faculty
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    Badge,
    Block,
    InspectContext,
    Ref,
    Row,
    Stat,
    Stats,
    Table,
    Text,
    Vital,
    When,
    paginate,
)
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


def _handles(s: PresenceState) -> set[str]:
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
    if link.handle not in _handles(s):
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
    return tuple(sorted(_handles(s)))


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


# ── Inspection ────────────────────────────────────────────────────────────

#: Au plus tant de connexions par page ; tant de noms dans l'aide d'un vital.
PAGE = 50
VITAL_NAMES = 6


def _audience(link: Link, trust: ChannelTrust) -> Badge:
    """Comme l'audience d'un épisode : un salon, ou un canal qui ne prouve
    rien, est public."""
    if link.room:
        return Badge(f"publique (salon « {link.room} »)", "warn")
    if link.public:
        return Badge("publique (groupe)", "warn")
    if trust is ChannelTrust.PUBLIC:
        return Badge("publique (rien ne prouve qui écrit)", "warn")
    return Badge("privée", "ok")


def _who(frame: Frame, handle: str) -> tuple[str, Ref]:
    """Le nom affiché, et le lien vers la fiche de la personne derrière l'adresse."""
    view = frame.get(identity_c.IDENTITY(handle))
    person = frame.get(identity_c.PERSON(handle))
    name = frame.get(identity_c.IDENTITY(person)).name if person != handle else view.name
    return view.name or name or "", Ref.subject("person", person, name or view.name or person)


@PRESENCE.inspect("presents", title="Présents", section="personnes", order=30,
                  description="Les connexions vivantes en ce moment ; une ligne mène à la fiche de la personne.")
def _inspect(s: PresenceState, frame: Frame, ctx: InspectContext) -> list[Block]:
    links = sorted(s.links.items(), key=lambda kv: (-s.since.get(kv[1].handle, 0), kv[0]))
    page, pager = paginate(links, ctx.pager(size=PAGE))
    rows = []
    for connection, link in page:
        view = frame.get(identity_c.IDENTITY(link.handle))
        name, person = _who(frame, link.handle)
        since = s.since.get(link.handle)
        rows.append(Row((person, Ref.subject("handle", link.handle, link.handle), name or "—",
                         link.channel or "—", Text(connection, "mono"), When(since) if since else "—",
                         _audience(link, view.trust)), href=person))
    return [
        Stats((Stat("connexions vivantes", len(s.links)), Stat("adresses présentes", len(_handles(s))))),
        Table(("personne", "adresse", "nom", "canal", "connexion", "présente depuis", "audience"), tuple(rows),
              title="Présents", pager=pager, empty="personne n'est connecté"),
    ]


@PRESENCE.vital("presents", label="Présents", order=40)
def _present_vital(s: PresenceState, frame: Frame) -> Vital:
    handles = sorted(_handles(s), key=lambda h: (-s.since.get(h, 0), h))
    names = [_who(frame, h)[0] or h for h in handles]
    hint = ", ".join(names[:VITAL_NAMES]) + (f" et {len(names) - VITAL_NAMES} autre(s)"
                                            if len(names) > VITAL_NAMES else "")
    return Vital(str(len(handles)), tone="info" if handles else "", hint=hint or "personne n'est connecté",
                 href=Ref.view("presence", "presents", "Présents"))
