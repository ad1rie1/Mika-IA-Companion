"""L'assemblage de l'API par personne (ADR 0187, 0310) : ``MeApi``, ses routes et ce qu'elle compte.

Les routes viennent des modules du cadre, puis du module de chaque domaine qui a sa fiche (``Domain.api``), dans
l'ordre des fiches. Cet ordre ne décide de rien : aucune route de ``/api/moi`` n'en masque une autre (chaque module a
son préfixe), ce que ``tests/unit/test_moi_frame.py`` garde. C'est ici, et nulle part ailleurs dans le paquet,
qu'on lit les fiches : ``mika.app.me`` reste importable par un domaine.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starlette.routing import Route

from mika.app.domains import DOMAINS, part
from mika.app.domains.phone import api as phone
from mika.app.me import (
    agenda,
    mail,
    maps,
    mcp,
    project_activity,
    project_code,
    project_docs,
    project_manage,
    projects,
    rights,
    settings,
    sharing,
    teams,
    writing,
)
from mika.app.me.api import Call, MeApiBase

__all__ = ["COUNTERS", "MODULES", "MeApi", "who"]

#: les modules : chacun rend ses routes — ceux du cadre, puis celui de chaque domaine
MODULES: tuple[Callable[[MeApiBase], list[Route]], ...] = (
    mail.routes, teams.routes, phone.routes, rights.routes, settings.routes, mcp.routes, sharing.routes, maps.routes,
    projects.routes, project_code.routes, project_docs.routes, project_manage.routes, project_activity.routes,
    writing.routes, agenda.routes,
    *(part(d.api, "routes") for d in DOMAINS if d.api is not None))
#: ce que chacun compte pour la barre du haut
COUNTERS: tuple[tuple[str, Callable[[Call], int]], ...] = (
    ("mail", mail.count), ("teams", teams.count), ("phone", phone.count), ("projects", projects.count),
    ("agenda", agenda.count),
    *((name, count) for d in DOMAINS for name, count in part(d.api, "COUNTERS", {}).items()))


async def who(req: Call) -> dict[str, Any]:
    """Qui est connecté : son compte et sa personne, ce qui l'attend (des comptes par domaine), et si « Corriger »
    marche (un modèle lui est donné, ADR 0307)."""
    me = req.me
    counts = {name: counter(req) for name, counter in COUNTERS}
    return {"username": me.account.username, "name": me.name, "handle": me.handle, "person": me.person,
            "operator": me.operator, "owner": me.owner, "counts": counts, "correct": writing.available(req)}


class MeApi(MeApiBase):
    """L'API par personne : le cadre, et les routes de chaque module."""

    def routes(self) -> list[Route]:
        return [self.route("", who), *(r for module in MODULES for r in module(self))]
