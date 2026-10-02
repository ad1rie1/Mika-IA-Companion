"""Contrat de ``place`` : où elle est dans sa chambre.

Un vocabulaire fermé — jamais des coordonnées : le modèle choisit un lieu, le
corps (le frontend) fait le chemin, contourne les meubles, s'assoit ou
s'allonge. Le lieu est un ÉTAT, pas un ordre : le renvoyer (une reconnexion,
un outil appelé deux fois) ne fait rien.
"""

from __future__ import annotations

import enum
from typing import Literal

from mika.kernel.events import Payload, event_type
from mika.kernel.facts import FactKey

OWNER = "place"


class Place(enum.StrEnum):
    CENTER = "center"  # debout au milieu, sur le tapis — face à qui lui parle
    WINDOW = "window"
    DESK = "desk"  # assise à son bureau
    BED = "bed"  # assise sur son lit ; allongée quand elle dort
    BOOKSHELF = "bookshelf"
    DOOR = "door"


class Moved(Payload):
    place: Place
    #: qui l'a mise là : elle-même (un outil), ou le sommeil (elle va se coucher)
    by: Literal["tool", "sleep"] = "tool"


MOVED = event_type("place.moved", OWNER, Moved, public=True)
ALL = (MOVED,)

#: Où elle est maintenant.
PLACE = FactKey("place.current", type=Place, doc="où elle est dans sa chambre")
#: Depuis quand (0 : depuis toujours — le premier démarrage).
SINCE = FactKey("place.since", type=int, doc="l'instant où elle y est arrivée")
