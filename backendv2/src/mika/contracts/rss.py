"""Contrat du plugin ``rss`` : ce qu'elle remarque dans ses flux.

Un titre remarqué est un **signal** : l'attention le dose et l'habitue — le
quarantième titre du jour n'est plus un événement. Un titre qui touche ses
centres d'intérêt peut devenir une curiosité, et une curiosité, une
exploration (« en savoir plus »).
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.contracts.attention import Signal
from mika.kernel.events import event_type
from mika.kernel.facts import FactKey

OWNER = "rss"
ENTRY = "entry"


class EntryNoticed(Signal):
    entry: str
    feed: str


NOTICED = event_type("rss.noticed", OWNER, EntryNoticed, public=True, content=("summary",))
ALL = (NOTICED,)


@dataclass(frozen=True, slots=True)
class Headline:
    entry: str
    feed: str
    pertinence: float
    at: int
    summary_ref: str


#: Les titres remarqués, les plus récents d'abord.
HEADLINES = FactKey("rss.headlines", type=tuple)
