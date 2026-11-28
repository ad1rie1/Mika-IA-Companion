"""L'API par personne des projets (ADR 0282, 0286, 0288, 0289, 0290, 0293, 0310) : ses projets et « À faire »
(``projects.py``), leur code (``code.py``), leur documentation (``docs.py``), ce qu'on y gère (``manage.py``), leur
activité (``activity.py``) ; et, pour la barre du haut, ce qui attend son geste (``COUNTERS``).
"""

from __future__ import annotations

from starlette.routing import Route

from mika.app.domains.projects.api import activity, code, docs, manage, projects
from mika.app.me.api import MeApiBase

COUNTERS = {"projects": projects.count}


def routes(api: MeApiBase) -> list[Route]:
    """Leurs routes, module par module, dans l'ordre où l'assemblage de l'API les mettait."""
    return [*projects.routes(api), *code.routes(api), *docs.routes(api), *manage.routes(api), *activity.routes(api)]
