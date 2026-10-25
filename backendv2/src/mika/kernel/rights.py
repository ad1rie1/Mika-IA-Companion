"""Ce qu'un propriétaire dit de ses droits (ADR 0133) : ses tableaux de règles, en mots, et ce qu'ils accordent à qui
est en face, avec la ligne qui en décide.

Chaque propriétaire déclare son type de règles (``Faculty.rights``) : ses tableaux (``RuleTable``, un par ressource —
un service, un projet, ce qu'elle envoie) et, pour une audience à un moment, ce qu'elle y aurait (``Grant``). La
console les rassemble sur une page ; ce n'est jamais une recopie : chacun les tire du moteur qu'il applique
(``vocab.access``). Des types de valeur, sans un mot du domaine.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RuleTable:
    """Un tableau de règles d'une ressource, en mots : ses colonnes, ses lignes dans leur ordre, sa ligne par défaut,
    ce qu'aucune ligne n'ouvre (``floors``) et où il se règle (``href`` : un ``Ref`` de la console)."""

    resource: str
    title: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    default: tuple[str, ...]
    href: Any = None
    floors: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True, slots=True)
class Grant:
    """Ce qu'une audience aurait d'une ressource, à un moment : chaque action et ce qui en décide (``what`` : action,
    décision en mots) ; ``why`` : la ligne qui en décide (« ligne 2 », « comportement par défaut »), ou pourquoi
    jamais ici."""

    resource: str
    title: str
    what: tuple[tuple[str, str], ...]
    why: str
    href: Any = None
    #: rien n'y est ouvert à cette audience (la page peut le taire)
    closed: bool = False


@dataclass(frozen=True, slots=True)
class RightsSpec:
    """Un type de règles : ``tables(tranche, frame, ctx) -> [RuleTable]`` ; ``grants(tranche, frame, ctx, audience,
    kind) -> [Grant]``, ce qu'elles accordent (``None`` : un type qui ne dépend pas de qui est en face — le
    destinataire d'un envoi)."""

    owner: str
    key: str
    title: str
    description: str
    tables: Callable[..., Any]
    grants: Callable[..., Any] | None = None
    order: int = 100


@dataclass(frozen=True, slots=True)
class Rights:
    """Les tableaux de droits qu'un opérateur a réglés (ADR 0134), tels que l'application les donne au registre
    (``Registry.access_tables``) : ``canals`` (les tableaux des canaux, ``vocab.canals.Canals``), ``families``
    (famille d'outils → tableau, ``vocab.access.Table[ToolRule]``), ``in_hand`` (outil → « hand » ou « ask »,
    l'offre réglée). Des valeurs du vocabulaire, inconnues ici."""

    canals: Any = None
    families: Mapping[str, Any] = field(default_factory=dict)
    in_hand: Mapping[str, str] = field(default_factory=dict)


def why_words(index: int) -> str:
    """La ligne qui décide, en mots : « ligne 2 », ou le comportement par défaut (``index`` 0)."""
    return f"ligne {index}" if index else "comportement par défaut"
