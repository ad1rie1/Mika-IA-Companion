"""Le port des flux (RSS, Atom) : ce qui paraît, et lire un article.

Un article ne se lit que s'il vient d'un flux relevé (par son identifiant) :
jamais une adresse arbitraire qu'un texte lui aurait soufflée.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Entry:
    id: str  # stable (guid, id, lien)
    feed: str  # le titre du flux
    title: str
    link: str
    summary: str  # texte brut, borné
    published: int = 0  # instant (µs), 0 si inconnu


class FeedPort(Protocol):
    def configured(self) -> bool: ...

    async def poll(self, limit: int) -> list[Entry]:
        """Les articles parus depuis le dernier relevé (chacun rendu une fois)."""
        ...

    async def entry(self, entry_id: str) -> Entry | None: ...

    async def recent(self, limit: int) -> list[Entry]: ...

    async def article(self, entry_id: str) -> str:
        """Le texte d'un article relevé (borné) ; ``""`` s'il est illisible."""
        ...
