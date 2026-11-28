"""Contrat du plugin ``camera`` : ce qu'elle voit.

Ce qu'elle voit est un **signal** (dosé, habitué) ; une description est faite
d'une image, et une image peut contenir du texte : c'est une donnée citée,
jamais une consigne. Ce qu'elle voit de la pièce n'est pas pour tout le
monde (des personnes y sont peut-être).
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.contracts.attention import Signal
from mika.kernel.events import event_type
from mika.kernel.facts import FactKey

OWNER = "camera"
VIEW = "view"


class Seen(Signal):
    device: str
    digest: str
    notable: bool = False


SEEN = event_type("camera.seen", OWNER, Seen, public=True, content=("summary",))
ALL = (SEEN,)


@dataclass(frozen=True, slots=True)
class View:
    device: str
    at: int
    notable: bool
    summary_ref: str


#: Ce qu'elle a vu en dernier, par appareil (le plus récent d'abord).
VIEWS = FactKey("camera.views", type=tuple)
