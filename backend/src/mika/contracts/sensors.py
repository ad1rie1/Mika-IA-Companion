"""Contrat du plugin ``sensors`` : ce que lui signalent des appareils (une
sonnette, une domotique, un script) par ``POST /api/perceptions``.

C'est un **signal**, pas le message d'une personne : l'attention le dose et
l'habitue comme le reste ; son texte est cité, jamais obéi.
"""

from __future__ import annotations

from mika.contracts.attention import Signal
from mika.kernel.events import event_type

OWNER = "sensors"


class Sensed(Signal):
    device: str


SENSED = event_type("sensors.sensed", OWNER, Sensed, public=True, content=("summary",))
ALL = (SENSED,)
