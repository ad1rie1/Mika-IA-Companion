"""Sa part de la file « À valider » (ADR 0177, 0310) : ce que concerne une demande dont le contexte nomme une app
forgée (``forge:meteo``)."""

from __future__ import annotations

from mika.app.domains.domain import QueuePart
from mika.app.handmade.approval_sources import Concern
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import UI

#: la sorte de ce qu'une telle demande concerne ; la fiche d'une app forgée
FORGED, APP = "app", "app"


def concern(ui: UI, rest: str) -> Concern:
    """L'app que nomme le contexte d'un appel à une app forgée, et sa fiche."""
    return Concern(FORGED, f"app « {rest} »", rest, subject_url(APP, rest), link=f"L'app « {rest} »")


QUEUE = QueuePart(contexts={"forge": concern})
