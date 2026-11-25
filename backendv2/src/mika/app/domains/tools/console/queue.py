"""Sa part de la file « À valider » (ADR 0177, 0310) : ce que concerne une demande dont le contexte nomme un de ses
services (``mcp:agenda``)."""

from __future__ import annotations

from mika.app.domains.domain import QueuePart
from mika.app.domains.tools.console.subject import KIND
from mika.app.handmade.approval_sources import Concern
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import UI

#: la sorte de ce qu'une telle demande concerne
SERVICE = "service"


def concern(ui: UI, rest: str) -> Concern:
    """Le service que nomme le contexte d'un appel à un serveur MCP, et sa fiche."""
    return Concern(SERVICE, f"service « {rest} »", rest, subject_url(KIND, rest), link=f"Le service « {rest} »")


QUEUE = QueuePart(contexts={"mcp": concern})
