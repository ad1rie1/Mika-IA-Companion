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

from mika.app.domains import DOMAINS, gathered, part
from mika.app.me import (
    chat,
    rights,
    settings,
    sharing,
    writing,
)
from mika.app.me.api import Call, MeApiBase

__all__ = ["COUNTERS", "MODULES", "MeApi", "who"]

#: les modules : chacun rend ses routes — ceux du cadre, puis celui de chaque domaine
MODULES: tuple[Callable[[MeApiBase], list[Route]], ...] = (
    rights.routes, settings.routes, sharing.routes,
    writing.routes, chat.routes,
    *(part(d.api, "routes") for d in DOMAINS if d.api is not None))
#: ce que chacun compte pour la barre du haut, par son nom : un nom que deux domaines disent est refusé à l'import
#: (``gathered``), au lieu que le second remplace l'autre dans ``counts``
COUNTERS: tuple[tuple[str, Callable[[Call], int]], ...] = tuple(gathered(
    "un compteur de la barre du haut, COUNTERS",
    ((f"le domaine « {d.name} »", part(d.api, "COUNTERS", {})) for d in DOMAINS)).items())


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
