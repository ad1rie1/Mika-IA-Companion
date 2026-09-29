"""L'inspecteur : voir ce qu'elle vit, et pourquoi.

Des vues génériques sur le journal et l'état — rien n'y est propre à une
faculté : chacune déclare ses vues (``@f.inspect``) et y apparaît seule.
Réservé aux opérateurs (session du frontend ou formulaire de connexion ici),
formulaires protégés par jeton CSRF à double soumission.

- vivre : vue d'ensemble, chronologie, décisions, facultés, approbations ;
- comprendre : état et faits, graphe des contributions, épisodes et
  événements (« pourquoi a-t-elle dit ça ? ») ;
- exploiter : santé, appels de modèle (coûts, cache), simulations ;
- régler : modèles et clés, persona, tempérament et surcharges, canaux, sens,
  apps forgées, comptes.
"""

from __future__ import annotations

from starlette.routing import Route

from mika.inspector import journal, mind, operations, settings
from mika.inspector.ui import UI, InspectorDeps

__all__ = ["InspectorDeps", "routes"]


def routes(deps: InspectorDeps, *, cookie_secure: bool = False) -> list[Route]:
    ui = UI(deps, cookie_secure=cookie_secure)
    return [*journal.routes(ui), *mind.routes(ui), *operations.routes(ui), *settings.routes(ui)]
