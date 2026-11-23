"""L'API par personne (ADR 0187) : ce que ``frontendv2`` montre à qui est connecté, et seulement à elle.

Chaque route lit la session du navigateur, ou le jeton d'un client natif présenté **sans** ``Origin`` (la règle de
``/auth/whoami``). Une route qui écrit exige en plus, d'un navigateur, le jeton CSRF (cookie ``csrftoken``, en-tête
``X-CSRFToken``) ; d'un client natif, que son jeton soit celui d'un téléphone (client ``mobile``, ADR 0235) : un
téléphone écrit, un écran (``screen``) ne fait que lire. Qui est connecté est une **personne** (``Me``) : son compte,
la clé de sa personne (``identity.person``), et si elle est une de ses propriétaires — les boîtes « à toi » (sans
propriétaire nommé, ADR 0185) sont alors les siennes.

Rien ici ne recopie une règle. Une ressource est à quelqu'un selon ses paramètres journalisés (``owners``) ; ce qu'on y
fait passe par les actions que la console déclare (``runtime.operations.perform``), au nom de la personne (``by``) :
journalisées et dédoublonnées comme dans la console, auditées depuis son espace (``moi.<action>``, ``via=SPACE``). Ce
qui se règle (son compte, ses boîtes, ses comptes Teams, ses services, ses partages) s'écrit dans les réglages du
serveur et s'audite (``moi.<geste>``) ; une création redite avec la même clé d'envoi ne refait rien (``Call.once``).
Une ressource qui n'est pas à elle n'existe pas : le même 404 qu'une ressource inconnue. Le contrat, route par route :
``docs/protocole-moi.md``.

Ce paquet réunit les modules (``mail``, ``teams``, ``contacts``…). Le cadre qu'ils emploient (``Me``, ``Call``, ``Denied``, la
déclaration d'une route) est dans ``api.py`` ; leurs petites aides dans ``common.py`` ; la règle de partage est dans
``vocab.ownership``, que ``common.py`` lit.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starlette.routing import Route

from mika.app.me import (
    contacts,
    mail,
    maps,
    mcp,
    phone,
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
from mika.app.me.api import OUTBOUND, PROBES, ROUTES_BUSY, Call, Denied, MeApiBase, form, missing, spend

__all__ = ["COUNTERS", "MODULES", "OUTBOUND", "PROBES", "ROUTES_BUSY", "Call", "Denied", "MeApi", "form", "missing",
           "spend", "who"]

#: les modules : chacun rend ses routes, et ce qu'il compte pour la barre du haut
MODULES: tuple[Callable[[MeApiBase], list[Route]], ...] = (mail.routes, teams.routes, phone.routes, rights.routes,
                                                           settings.routes, mcp.routes, sharing.routes, maps.routes,
                                                           projects.routes, project_code.routes,
                                                           project_docs.routes, project_manage.routes,
                                                           project_activity.routes, contacts.routes,
                                                           writing.routes)
COUNTERS: tuple[tuple[str, Callable[[Call], int]], ...] = (("mail", mail.count), ("teams", teams.count),
                                                            ("phone", phone.count), ("projects", projects.count))


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
