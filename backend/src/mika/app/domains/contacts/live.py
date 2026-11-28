"""La part de l'annuaire dans le direct (ADR 0308, 0310) : ce qu'une écriture de sa base change, et qui le voit.

Un contact est à qui l'a fait connaître : une touche de l'annuaire nomme les sources d'où il vient
(``source|compte``), et va à qui voit l'une d'elles — la règle même de ses routes (``api.reach``).
"""

from __future__ import annotations

from mika.app.domains.contacts.api import reach
from mika.app.domains.domain import LivePart
from mika.app.me.api import Call
from mika.app.me.touches import Touch
from mika.plugins.contacts import CONTACTS as PLUGIN
from mika.ports.changes import CONTACTS, Change

#: à qui va une touche de l'annuaire : à qui voit la source du contact
DIRECTORY = "directory"


def from_change(change: Change) -> list[Touch]:
    """Une écriture de sa base, une fois validée : ses sources touchées."""
    return [Touch(CONTACTS, DIRECTORY, owners=tuple(f"{s}|{a}" for s, a in change.places))]


def seen(call: Call) -> frozenset[str]:
    """Les sources de l'annuaire dont elle voit les contacts."""
    port = call.port("contacts")
    if port is None:
        return frozenset()
    return frozenset(f"{s}|{a}" for s, a in reach(call, port).visible)


LIVE = LivePart(params={PLUGIN.name: (CONTACTS,)}, changes={CONTACTS: from_change}, seen={DIRECTORY: seen})
