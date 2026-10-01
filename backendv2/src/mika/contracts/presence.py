"""Contrat de ``presence`` : qui est là, maintenant (volatile).

Les connexions ne survivent pas à un redémarrage : la tranche repart vide et
se remplit quand les clients se reconnectent. Les événements restent au
journal pour les autres (``identity`` y apprend les adresses).
"""

from __future__ import annotations

from mika.kernel.events import Payload, event_type
from mika.kernel.facts import FactFamily, FactKey

OWNER = "presence"


class Connected(Payload):
    handle: str
    channel: str
    connection: str
    authenticated: bool = False
    account: int | None = None
    operator: bool = False
    display_name: str = ""
    room: str | None = None
    public: bool = False


class Disconnected(Payload):
    handle: str
    connection: str


CONNECTED = event_type("presence.connected", OWNER, Connected, public=True, subjects=("handle",))
DISCONNECTED = event_type("presence.disconnected", OWNER, Disconnected, public=True, subjects=("handle",))
ALL = (CONNECTED, DISCONNECTED)

#: Les adresses connectées, triées.
PRESENT = FactKey("presence.present", type=tuple, doc="adresses avec au moins une connexion vivante")
#: Depuis quand cette adresse est là (début de la présence en cours), ou None.
SINCE = FactFamily("presence.since", arg=str, type=int)
