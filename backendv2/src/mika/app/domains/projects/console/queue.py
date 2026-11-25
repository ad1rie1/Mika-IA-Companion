"""Sa part de la file « À valider » (ADR 0177, 0310) : ce que concerne une demande dont le contexte nomme un projet
(``project:61``), et sa vue qui montre les mêmes demandes que la file."""

from __future__ import annotations

from mika.app.domains.domain import QueuePart
from mika.app.handmade.approval_sources import Concern
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import UI
from mika.vocab.episodes import PROJECT_PREFIX, project_of

#: la sorte de ce qu'une telle demande concerne
PROJECT = "projet"


def concern(ui: UI, rest: str) -> Concern | None:
    """Le projet que nomme le contexte d'une demande, et sa fiche ; ``None`` : ce n'est pas un numéro de projet."""
    project = project_of(PROJECT_PREFIX + rest)
    if project is None:
        return None
    return Concern(PROJECT, f"projet n° {project}", str(project), subject_url("project", str(project)),
                   link=f"Le projet n° {project}")


QUEUE = QueuePart(covers=("projets/tous",), contexts={PROJECT_PREFIX.rstrip(":"): concern})
