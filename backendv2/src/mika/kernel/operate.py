"""Les actions d'opérateur : ce qu'un opérateur peut faire depuis la console.

Une faculté déclare ``@f.action(nom, title=…, args=<modèle>, emits=[…])`` une
fonction ``(tranche, frame, args, ctx) -> Done`` (ou sa coroutine). Elle ne
fait rien elle-même : elle rend des **brouillons** d'événements (les siens),
que le runtime ajoute au journal avec l'origine « extérieure », sous garde,
dédoublonnés, suivis d'un événement d'audit. Refuser se dit par
``Refused(message, champs)``.

Ce sont des actions d'exploitation (lier une adresse, confier un projet,
recharger une app) — jamais une réécriture de ses souvenirs, de ses pensées ou
de son humeur : une règle d'architecture fige la liste.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
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

    #: l'adresse de l'opérateur (``user_1``)
    by: str
    #: la clé de l'objet, sur une fiche (``""`` sinon)
    subject: str
    now: int
    ports: Mapping[str, Any] = field(default_factory=dict)
    #: lecture seule : ``query_mind``, ``query_views``, ``content``
    store: Any = None


@dataclass(frozen=True, slots=True)
class Preview:
    """Exactement ce qu'un effet ferait s'il partait maintenant (voir
    ``CapabilitySpec.preview``) : le texte montré à qui décide, son condensé, et
    ce qui l'empêcherait de partir tel quel (vide : rien)."""

    text: str
    digest: str
    blocked: str = ""


@dataclass(frozen=True, slots=True)
class Decision:
    """Décider d'une de ses propres propositions en attente (``effect.proposed``)
    depuis une fiche : l'approuver (telle que ``seen`` la montrait) ou la refuser."""

    proposal: int
    approved: bool
    note: str = ""
    #: le condensé de l'aperçu que l'opérateur a lu (vide : celui de la proposition)
    seen: str = ""


@dataclass(frozen=True, slots=True)
class Done:
    """Ce qu'une action a décidé : des brouillons à journaliser (sous ``guard``),
    un message pour l'opérateur, une page où aller, ou des blocs à montrer en
    place (le résultat d'un test). ``decide`` : des propositions de la faculté
    elle-même, approuvées ou refusées (le runtime journalise ``effect.resolved``)."""

    drafts: tuple[Draft[Any], ...] = ()
    message: str = ""
    tone: str = "ok"
    guard: Guard | None = None
    go: Ref | None = None
    show: tuple[Any, ...] = ()
    decide: tuple[Decision, ...] = ()
    #: aller sur la fiche de ce qui vient d'être créé : le type d'objet dont la clé est le
    #: numéro du premier événement journalisé (« project » : le projet qu'on vient de créer)
    go_created: str = ""
    #: une suite qui dépend des numéros que l'ajout vient de donner (les objectifs d'un projet qu'on vient
    #: de créer portent son numéro) : ``then(numéros) -> brouillons``, journalisés aussitôt après, sous la même
    #: corrélation et avec les mêmes règles (les siens seulement)
    then: Callable[[tuple[int, ...]], Sequence[Draft[Any]]] | None = None
