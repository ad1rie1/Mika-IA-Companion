"""Le câblage de ses sens (ADR 0310) : ses flux, le port ``feeds`` du noyau, relevés d'après ses réglages et rangés
dans leur base ; sa caméra, le port ``camera``, que l'application web remplit aussi (``/ws/camera``)."""

from __future__ import annotations

from mika.adapters.camera import CameraBuffer
from mika.adapters.feeds import HttpFeeds
from mika.app.domains.senses.settings import SensesSettings
from mika.app.wiring import Wiring


def wire(w: Wiring) -> None:
    w.ports["feeds"] = HttpFeeds(w.settings.of(SensesSettings).feeds, w.bases["feeds"])
    camera = CameraBuffer(w.clock.now)
    w.ports["camera"] = w.web["camera"] = camera
