"""Le port des flux (RSS, Atom) : ce qui paraît, et lire un article.

Un article ne se lit que s'il vient d'un flux relevé (par son identifiant) :
jamais une adresse arbitraire qu'un texte lui aurait soufflée.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mika.ports.paging import Page


@dataclass(frozen=True, slots=True)
class Entry:
    id: str  # stable (guid, id, lien)
    feed: str  # le titre du flux
    title: str
    link: str
    summary: str  # texte brut, borné
    published: int = 0  # instant (µs), 0 si inconnu


class FeedPort(Protocol):
    def entries_page(self, feed: str = "", text: str = "", page: int = 1, size: int = 25) -> Page[Entry]: ...

    def entry_count(self, feed: str = "", exclude: tuple[str, ...] = ()) -> int: ...

    def feed_counts(self) -> dict[str, int]: ...

    def configured(self) -> bool: ...

    async def poll(self, limit: int) -> list[Entry]:
        """Les articles parus depuis le dernier relevé (chacun rendu une fois)."""
        ...

    async def entry(self, entry_id: str) -> Entry | None: ...

    async def recent(self, limit: int) -> list[Entry]: ...

    def cached(self, limit: int) -> list[Entry]:
        """Les derniers articles déjà relevés, sans relever (lecture seule : l'inspecteur)."""
        ...

    def cached_count(self) -> int:
        """Nombre d'articles en cache, y compris ceux d'un ancien abonnement."""
        ...

    def followed(self) -> list[tuple[str, str]]:
        """Les flux suivis : (titre s'il est connu, adresse montrable — sans
        identifiants ni valeurs de paramètres, qui peuvent porter un jeton)."""
        ...

    def health(self) -> list[dict[str, object]]:
        """Pour chaque flux suivi, ce que son dernier relevé a donné (lecture seule) : ``title``, ``url``
        (montrable), ``attempted_at``, ``ok_at`` (µs), ``error`` (vide : il va bien), ``failures`` (d'affilée),
        ``items`` (lus au dernier relevé), ``added`` (nouveaux), ``kept`` (dans le cache)."""
        ...

    async def article(self, entry_id: str) -> str:
        """Le texte d'un article relevé (borné) ; ``""`` s'il est illisible."""
        ...
