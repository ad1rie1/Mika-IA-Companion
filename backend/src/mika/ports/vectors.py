"""Le port des vecteurs : plonger des textes, retrouver les plus proches.

L'index est un **cache** : tout ce qu'il contient se déduit du journal
(textes des souvenirs, des croyances, des extraits d'échanges). On peut le
jeter et le reconstruire — à l'identique, le plongement étant déterministe.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class VectorItem:
    key: int  # le ``seq`` de l'événement qui a créé l'élément
    kind: str  # "souvenir" | "belief" | "promise" | "event" | "chunk" | "room_chunk" (un échange dans un salon)
    text: str
    persons: tuple[str, ...] = ()


class Embedder(Protocol):
    name: str
    dims: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, texts: Sequence[str]) -> list[list[float]]:
        """Plonger ce qu'on cherche (un modèle de recherche ne plonge pas une requête comme un document)."""
        ...


class VectorIndex(Protocol):
    model: str

    async def open(self) -> None: ...

    async def upsert(self, items: Sequence[VectorItem]) -> int: ...

    async def search(self, query: str, k: int, *, kinds: Collection[str] | None = None,
                     keys: Collection[int] | None = None, persons: Collection[str] | None = None,
                     document: bool = False) -> list[tuple[int, float]]:
        """Les ``k`` plus proches (clé, similarité), du plus proche au plus lointain, ex æquo départagés par la clé.
        Filtres cumulables : ces sortes, ces clés, au moins une de ces personnes (``VectorItem.persons``).

        La similarité est centrée sur le fond du modèle (ADR 0111) : 0 pour un texte quelconque, 1 pour l'identique,
        la même échelle pour tout modèle. ``document`` : ``query`` est un texte de sa mémoire comparé à d'autres (un
        doublon, une confrontation), plongé comme eux ; sinon c'est une recherche, plongée comme une question."""
        ...

    async def forget(self, subject: str) -> int: ...

    async def remove(self, keys: Collection[int]) -> int: ...

    def indexed(self) -> set[int]: ...

    def digest(self) -> str: ...
