"""Contrat de ``presence`` : qui est là, maintenant (volatile).

Les connexions ne survivent pas à un redémarrage : la tranche repart vide et
se remplit quand les clients se reconnectent. Les événements restent au
journal pour les autres (``identity`` y apprend les adresses).

``presence.read`` : jusqu'où la personne a lu son fil — ce que dit son
application, si elle l'a permis (« Lui dire quand j'ai lu »). Une seule valeur,
« lu jusqu'ici » : ni l'heure à laquelle on est en ligne, ni le temps passé à
l'écran.
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


class Read(Payload):
    """La personne a lu son fil jusqu'à ce message (``up_to`` : le ``seq`` d'un message du fil)."""

    handle: str
    up_to: int


CONNECTED = event_type("presence.connected", OWNER, Connected, public=True, subjects=("handle",))
DISCONNECTED = event_type("presence.disconnected", OWNER, Disconnected, public=True, subjects=("handle",))
READ = event_type("presence.read", OWNER, Read, public=True, subjects=("handle",))
ALL = (CONNECTED, DISCONNECTED, READ)

#: Les adresses connectées, triées.
PRESENT = FactKey("presence.present", type=tuple, doc="adresses avec au moins une connexion vivante")
#: Depuis quand cette adresse est là (début de la présence en cours), ou None.
SINCE = FactFamily("presence.since", arg=str, type=int)
