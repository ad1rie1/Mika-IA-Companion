"""Ce que la fiche d'une personne et les parts des domaines lisent ensemble (ADR 0310) : la personne de la page
(``Who``), la tranche d'une faculté ou d'un plugin (``state_slice``), et une personne d'un partage avec son niveau
(``share_person``, ``LEVEL_FR``). La part d'un domaine (``PersonPart`` : ses onglets,
ce qu'il y compte) les prend ici, dans un module feuille, et jamais dans ``person/__init__.py`` : la fiche lit les
parts, une part ne lit pas la fiche."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mika.app.handmade import Look
from mika.vocab.access import PERSON, SHARES

#: le niveau d'un partage (ADR 0188), tel que la fiche le nomme ; sa sorte, sa part la dit (``SharingPart.word``)
LEVEL_FR = {level: label.lower() for level, label in SHARES}


@dataclass(frozen=True, slots=True)
class Who:
    """La personne de la page : sa clé, son nom, ses adresses, et toutes les clés sous lesquelles sa mémoire a pu la
    noter (ses adresses, les noms dont on lui a parlé et qui la désignent)."""

    person: str
    name: str
    handles: tuple[str, ...]
    keys: tuple[str, ...]


def state_slice(look: Look, name: str) -> Any:
    """La tranche d'une faculté ou d'un plugin ; ``None`` quand il n'est pas composé ici."""
    try:
        return look.frame.state(name)
    except KeyError:
        return None


def share_person(look: Look, who: str, level: str) -> dict[str, str]:
    """Une personne d'un partage (``personne:<clé>``, ou sa clé) et son niveau, pour la fiche."""
    person = who.removeprefix(PERSON)
    return {"name": look.name(person), "person_href": look.href(person), "level": LEVEL_FR.get(level, level)}
