"""Contrat de ``presence`` : qui est là, maintenant (volatile).

Les connexions ne survivent pas à un redémarrage : la tranche repart vide et
se remplit quand les clients se reconnectent. Les événements restent au
journal pour les autres (``identity`` y apprend les adresses).

``presence.read`` : jusqu'où la personne a lu son fil — ce que dit son
application, si elle l'a permis (« Lui dire quand j'ai lu »). Une seule valeur,
« lu jusqu'ici » : ni l'heure à laquelle on est en ligne, ni le temps passé à
l'écran.

``presence.composing`` : la personne commence à écrire un message, ou cesse
(ce que dit son application). Jamais une frappe : le début et la fin d'une
saisie ; le message envoyé la clôt sans rien écrire de plus. Tant qu'elle
écrit encore, la réponse à son message d'avant attend la suite, et Mika ne
prend pas d'elle-même la parole vers elle — au plus ``COMPOSING_MAX_US``.
"""

from __future__ import annotations

from mika.kernel.clock import US
from mika.kernel.events import Payload, event_type
from mika.kernel.facts import FactFamily, FactKey

OWNER = "presence"
#: au-delà de tant de saisie continue, elle n'attend plus la suite : une saisie de deux minutes ne retient pas une
#: réponse deux minutes (l'adaptateur écrit lui-même la fin à ce plafond)
COMPOSING_MAX_US = 45 * US


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


class Composing(Payload):
    """La personne commence (``on``) ou cesse d'écrire un message, sur cette connexion."""

    handle: str
    connection: str
    on: bool


CONNECTED = event_type("presence.connected", OWNER, Connected, public=True, subjects=("handle",))
DISCONNECTED = event_type("presence.disconnected", OWNER, Disconnected, public=True, subjects=("handle",))
READ = event_type("presence.read", OWNER, Read, public=True, subjects=("handle",))
COMPOSE = event_type("presence.composing", OWNER, Composing, public=True, subjects=("handle",))
ALL = (CONNECTED, DISCONNECTED, READ, COMPOSE)

#: Les adresses connectées, triées.
PRESENT = FactKey("presence.present", type=tuple, doc="adresses avec au moins une connexion vivante")
#: Depuis quand cette adresse est là (début de la présence en cours), ou None.
SINCE = FactFamily("presence.since", arg=str, type=int)
#: Depuis quand la personne derrière cette adresse écrit un message (début de la saisie en cours), ou None — aussi
#: au-delà de ``COMPOSING_MAX_US`` de saisie continue.
COMPOSING = FactFamily("presence.composing", arg=str, type=int, time_varying=True,
                       doc="début de la saisie en cours d'une adresse (bornée)")
