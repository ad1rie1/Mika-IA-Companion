"""Ce que la console montre de la présence (Personnes › Présents) : les connexions vivantes en ce moment, leur
audience, la fiche de la personne derrière chaque adresse ; et le vital « Présents ».
"""

from __future__ import annotations

from mika.contracts import identity as identity_c
from mika.faculties.presence import PRESENCE, Link, PresenceState, linked_handles
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
    plural,
)
from mika.vocab.privacy import ChannelTrust

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
        Stats((Stat("connexions vivantes", len(s.links)), Stat("moyens de communication présents", len(linked_handles(s))))),
        Table(("personne", "moyen de communication", "nom", "canal", "connexion", "présente depuis", "audience"),
              tuple(rows),
              title="Présents", pager=pager, empty="personne n'est connecté"),
    ]


@PRESENCE.vital("presents", label="Présents", order=40)
def _present_vital(s: PresenceState, frame: Frame) -> Vital:
    handles = sorted(linked_handles(s), key=lambda h: (-s.since.get(h, 0), h))
    names = [_who(frame, h)[0] or h for h in handles]
    hint = ", ".join(names[:VITAL_NAMES]) + (f" et {plural(len(names) - VITAL_NAMES, 'autre', 'autres')}"
                                            if len(names) > VITAL_NAMES else "")
    return Vital(str(len(handles)), tone="info" if handles else "", hint=hint or "personne n'est connecté",
                 href=Ref.view("presence", "presents", "Présents"))
