"""L'API par personne (ADR 0187) : ce que ``frontendv2`` montre à qui est connecté, et seulement à elle.

Chaque route lit la session du navigateur, ou le jeton d'un client natif présenté **sans** ``Origin`` (la règle de
``/auth/whoami``) ; une route qui écrit exige en plus le jeton CSRF (cookie ``csrftoken``, en-tête ``X-CSRFToken``),
qu'un client natif n'a pas : rien n'est élargi. Qui est connecté est une **personne** (``Me``) : son compte, la clé de
sa personne (``identity.person``), et si elle est une de ses propriétaires — les boîtes « à toi » (sans propriétaire
nommé, ADR 0185) sont alors les siennes.

Rien ici ne recopie une règle. Une ressource est à quelqu'un selon ses paramètres journalisés (``owners``) ; ce qu'on y
fait passe par les actions que la console déclare (``runtime.operations.perform``), au nom de la personne (``by``) :
journalisées et dédoublonnées comme dans la console, auditées depuis son espace (``moi.<action>``, ``via=SPACE``). Ce
qui se règle (son compte, ses boîtes, ses comptes Teams, ses services, ses partages) s'écrit dans les réglages du
serveur et s'audite (``moi.<geste>``) ; une création redite avec la même clé d'envoi ne refait rien (``Call.once``).
Une ressource qui n'est pas à elle n'existe pas : le même 404 qu'une ressource inconnue. Le contrat, route par route :
``docs/protocole-moi.md``.

Ce paquet réunit les modules (``mail``, ``teams``…). Le cadre qu'ils emploient (``Me``, ``Call``, ``Denied``, la
déclaration d'une route) est dans ``api.py``, leurs petites aides et la règle de partage dans ``common.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starlette.routing import Route

from mika.app.moi import carte, mail, mcp, phone, rights, settings, shares, teams
from mika.app.moi.api import OUTBOUND, PROBES, ROUTES_BUSY, Call, Denied, MeApiBase, form, missing, spend

__all__ = ["COUNTERS", "MODULES", "OUTBOUND", "PROBES", "ROUTES_BUSY", "Call", "Denied", "MeApi", "form", "missing",
           "spend", "who"]

#: les modules : chacun rend ses routes, et ce qu'il compte pour la barre du haut
MODULES: tuple[Callable[[MeApiBase], list[Route]], ...] = (mail.routes, teams.routes, phone.routes, rights.routes,
                                                           settings.routes, mcp.routes, shares.routes, carte.routes)
COUNTERS: tuple[tuple[str, Callable[[Call], int]], ...] = (("mail", mail.count), ("teams", teams.count),
                                                            ("phone", phone.count))


async def who(req: Call) -> dict[str, Any]:
    """Qui est connecté : son compte et sa personne, ce qui l'attend (des comptes par domaine)."""
    me = req.me
    counts = {name: counter(req) for name, counter in COUNTERS}
    return {"username": me.account.username, "name": me.name, "handle": me.handle, "person": me.person,
            "operator": me.operator, "owner": me.owner, "counts": counts}


class MeApi(MeApiBase):
    """L'API par personne : le cadre, et les routes de chaque module."""

    def routes(self) -> list[Route]:
        return [self.route("", who), *(r for module in MODULES for r in module(self))]
