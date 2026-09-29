"""Les actions d'opérateur : ce qu'un opérateur peut faire depuis la console.

Une faculté déclare ``@f.action(nom, title=…, args=<modèle>, emits=[…])`` une
fonction ``(tranche, frame, args, ctx) -> Done`` (ou sa coroutine). Elle ne
fait rien elle-même : elle rend des **brouillons** d'événements (les siens),
que le runtime ajoute au journal avec l'origine « extérieure », sous garde,
dédoublonnés, suivis d'un événement d'audit. Refuser se dit par
``Refused(message, champs)``.

Ce sont des actions d'exploitation (lier une poignée, confier un projet,
recharger une app) — jamais une réécriture de ses souvenirs, de ses pensées ou
de son humeur : une règle d'architecture fige la liste.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from mika.kernel.events import Draft
from mika.kernel.guards import Guard
from mika.kernel.inspect import Ref


class Refused(Exception):
    """Un refus dit en français ; ``fields`` : un message par champ du formulaire."""

    def __init__(self, message: str, fields: Mapping[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.fields = dict(fields or {})


@dataclass(frozen=True, slots=True)
class ActionContext:
    """Ce que reçoit une action : qui agit, sur quel objet, et de quoi lire."""

    #: la poignée de l'opérateur (``user_1``)
    by: str
    #: la clé de l'objet, sur une fiche (``""`` sinon)
    subject: str
    now: int
    ports: Mapping[str, Any] = field(default_factory=dict)
    #: lecture seule : ``query_mind``, ``query_views``, ``content``
    store: Any = None


@dataclass(frozen=True, slots=True)
class Done:
    """Ce qu'une action a décidé : des brouillons à journaliser (sous ``guard``),
    un message pour l'opérateur, une page où aller, ou des blocs à montrer en
    place (le résultat d'un test)."""

    drafts: tuple[Draft[Any], ...] = ()
    message: str = ""
    tone: str = "ok"
    guard: Guard | None = None
    go: Ref | None = None
    show: tuple[Any, ...] = ()
