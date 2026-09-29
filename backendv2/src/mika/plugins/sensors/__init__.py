"""Le plugin ``sensors`` : l'entrée des appareils. Il ne fait que porter
l'événement (l'attention, qui reçoit tous les signaux, fait le reste)."""

from __future__ import annotations

from dataclasses import dataclass

from mika.contracts import sensors as c
from mika.kernel.faculty import Faculty


@dataclass(frozen=True, slots=True)
class SensorsState:
    pass


SENSORS = Faculty("sensors", state=SensorsState, init=lambda p: SensorsState())
SENSORS.declare(*c.ALL)
