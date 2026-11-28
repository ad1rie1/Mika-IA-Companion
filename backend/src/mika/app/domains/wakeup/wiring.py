"""Le câblage des réveils par API (ADR 0068, 0310) : leur porte, qui est aussi le port ``wakeup`` du noyau."""

from __future__ import annotations

from mika.app.domains.wakeup.desk import WakeupDesk
from mika.app.domains.wakeup.settings import WakeupSettings
from mika.app.wiring import Wiring

NAME = "wakeup"


def wire(w: Wiring) -> None:
    """Leurs réglages et leurs clés, et la porte qui admet un appel (``POST /api/wake/<nom>``)."""
    desk = WakeupDesk(w.settings.of(WakeupSettings), w.clock.now)
    w.ports[NAME] = w.parts[NAME] = desk
    w.web[NAME] = desk.call


def bind(w: Wiring) -> None:
    w.parts[NAME].port = w.port
