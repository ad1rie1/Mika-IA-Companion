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
    kind: str  # "souvenir" | "belief" | "promise" | "chunk"
    text: str
    persons: tuple[str, ...] = ()


class Embedder(Protocol):
    name: str
    dims: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class VectorIndex(Protocol):
    model: str

    async def open(self) -> None: ...

    async def upsert(self, items: Sequence[VectorItem]) -> int: ...

    async def search(self, query: str, k: int, *, kinds: Collection[str] | None = None,
                     keys: Collection[int] | None = None) -> list[tuple[int, float]]: ...

    async def forget(self, subject: str) -> int: ...

    async def remove(self, keys: Collection[int]) -> int: ...

    def indexed(self) -> set[int]: ...

    def digest(self) -> str: ...
