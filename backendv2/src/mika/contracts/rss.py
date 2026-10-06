"""Contrat du plugin ``rss`` : ce qu'elle remarque dans ses flux.

Un titre remarqué est un **signal** : l'attention le dose et l'habitue — le
quarantième titre du jour n'est plus un événement. Un titre qui touche ses
centres d'intérêt peut devenir une curiosité, et une curiosité, une
exploration (« en savoir plus »).

En relevant ses flux, elle pense aussi à ses amies : un titre qui touche ce
qu'une amie ou une proche lui a dit aimer (sa fiche, ``social.interests_ref``)
devient quelque chose à **lui** montrer (``THOUGHT_OF``) — jamais à une autre,
jamais en salon. Ce n'est pas un signal pour son attention : ça ne la touche
pas elle, ça la fait penser à quelqu'un.
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.contracts.attention import Signal
from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily, FactKey

OWNER = "rss"
ENTRY = "entry"
#: Raison de preuve d'initiative : un titre qui lui a fait penser à cette personne (une petite envie de le lui
#: montrer, seulement quand l'envie de compagnie est déjà là).
FOR_FRIEND = "rss_for"


class EntryNoticed(Signal):
    entry: str
    feed: str


class ThoughtOf(Payload):
    """Un titre lui a fait penser à une amie : il touche ce que cette personne lui a dit aimer. Le titre est
    gardé pour elle seule (``subjects``) : l'oubli de la personne l'efface."""

    entry: str
    person: str
    score: float
    feed: str
    summary: Content


NOTICED = event_type("rss.noticed", OWNER, EntryNoticed, public=True, content=("summary",))
THOUGHT_OF = event_type("rss.thought_of", OWNER, ThoughtOf, content=("summary",), subjects=("person",))
ALL = (NOTICED, THOUGHT_OF)


@dataclass(frozen=True, slots=True)
class Headline:
    entry: str
    feed: str
    pertinence: float
    at: int
    summary_ref: str


#: Les titres remarqués, les plus récents d'abord.
HEADLINES = FactKey("rss.headlines", type=tuple)
#: ``FOR_PERSON(personne)`` : les titres qui lui ont fait penser à cette personne (``Headline``), les plus récents
#: d'abord — leur résumé est la copie gardée pour elle.
FOR_PERSON = FactFamily("rss.for_person", arg=str, type=tuple)
