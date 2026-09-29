"""Les vues d'inspection : ce qu'une faculté montre d'elle à un opérateur.

Une faculté déclare ``@f.inspect("nom", title=…, params=…)`` une fonction
``(frame, ctx) -> Sequence[Block]`` ; l'inspecteur les rend toutes de la même
façon et les range sous leur propriétaire, sans connaître aucune faculté.

Lecture seule : une vue lit le frame, les projections et les caches des
ports, jamais n'écrit. Tout y est montré (l'inspecteur est réservé aux
opérateurs) ; un contenu oublié s'affiche comme tel.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Ref:
    """Un lien vers une autre page de l'inspecteur.

    ``kind`` : ``"episode"`` (clé = corrélation), ``"event"`` (clé = seq, la
    chaîne causale), ``"view"`` (clé = ``"<propriétaire>/<nom>"``, avec
    ``params``)."""

    kind: str
    key: str
    text: str
    params: tuple[tuple[str, str], ...] = ()


Cell = str | int | float | bool | Ref | None


@dataclass(frozen=True, slots=True)
class Table:
    columns: tuple[str, ...]
    rows: tuple[tuple[Cell, ...], ...]
    title: str = ""
    empty: str = "rien pour l'instant"


@dataclass(frozen=True, slots=True)
class Fields:
    pairs: tuple[tuple[str, Cell], ...]
    title: str = ""


@dataclass(frozen=True, slots=True)
class Note:
    text: str
    #: ``""``, ``"ok"``, ``"ko"`` ou ``"mut"``
    tone: str = ""


@dataclass(frozen=True, slots=True)
class Prose:
    """Un texte long (un récit, un journal, un prompt), rendu tel quel."""

    text: str
    title: str = ""


Block = Table | Fields | Note | Prose


@dataclass(frozen=True, slots=True)
class InspectContext:
    """Ce qu'une vue reçoit en plus du frame."""

    #: lecture seule : ``query_mind``, ``query_views``, ``content``
    store: Any
    #: les ports (caches des plugins : courrier, flux, Forge…)
    ports: Mapping[str, Any]
    #: la requête (``?q=…``), des chaînes ; une vue valide ce qu'elle lit
    params: Mapping[str, str] = field(default_factory=dict)
    #: un instant, lisible en heure locale
    when: Callable[[int], str] = str
    #: le journal : ``events(types, limit=50, where=(champ, valeur), before=seq, correlations=…)``
    #: → événements décodés (contenus résolus, « oubliés » à ``None``), du plus récent
    #: au plus ancien
    journal: Callable[..., list[Any]] | None = None
    #: ``tally(type, champ)`` → (valeur, nombre, dernier instant), par valeur
    counter: Callable[[str, str], list[tuple[Any, int, int]]] | None = None

    def events(self, types: Sequence[Any], limit: int = 50, *, where: tuple[str, Any] | None = None,
               before: int | None = None, correlations: Sequence[str] | None = None) -> list[Any]:
        """Les derniers événements de ces types (``EventType`` ou noms), d'un
        champ donné, ou de ces épisodes."""
        if self.journal is None:
            return []
        names = [getattr(t, "name", t) for t in types]
        return self.journal(names, limit, where=where, before=before, correlations=correlations)

    def tally(self, event_type: Any, field: str) -> list[tuple[Any, int, int]]:
        if self.counter is None:
            return []
        return self.counter(getattr(event_type, "name", event_type), field)

    def param(self, name: str, default: str = "") -> str:
        return str(self.params.get(name, default) or default).strip()[:200]

    def int_param(self, name: str, default: int = 0) -> int:
        try:
            return int(self.params.get(name, default))
        except (TypeError, ValueError):
            return default


def rows(items: Sequence[Sequence[Cell]]) -> tuple[tuple[Cell, ...], ...]:
    return tuple(tuple(r) for r in items)
