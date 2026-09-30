"""Une page de données : le port découpe avant de construire les documents."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


def fold_text(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(text).casefold()) if not unicodedata.combining(c))


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    items: tuple[T, ...]
    total: int
    number: int = 1
    size: int = 25

    @staticmethod
    def bounds(total: int, number: int, size: int) -> tuple[int, int, int]:
        size = max(1, min(100, size))
        number = min(max(1, number), max(1, (total + size - 1) // size))
        return number, size, (number - 1) * size

    @classmethod
    def of(cls, items, number: int = 1, size: int = 25):
        number, size, offset = cls.bounds(len(items), number, size)
        return cls(tuple(items[offset:offset + size]), len(items), number, size)


def page_slice(fetch, offset: int, limit: int):
    """Lire une tranche arbitraire avec au plus deux pages de 100 objets."""
    offset, limit = max(0, offset), max(1, min(100, limit))
    page = fetch(offset // 100 + 1, 100)
    if offset >= page.total:
        return []
    items = list(page.items[offset % 100:offset % 100 + limit])
    if len(items) < limit and offset + len(items) < page.total:
        items += list(fetch(page.number + 1, 100).items[:limit - len(items)])
    return items
