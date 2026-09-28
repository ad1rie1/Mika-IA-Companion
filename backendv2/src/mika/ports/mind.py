"""Le port d'entrée : ce que les adaptateurs (web, Telegram…) peuvent
demander au cœur. Ils ne voient jamais le Mind ni les facultés : ils
soumettent des stimulus, lisent des vues, et reçoivent les livraisons.
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Protocol

from mika.contracts.presence import Connected
from mika.contracts.runtime import PerceptionReceived
from mika.kernel.frame import Frame


@dataclass(frozen=True, slots=True)
class Admission:
    """Ce qu'est devenu un message soumis."""

    status: str  # "accepted" | "overloaded"
    seq: int | None = None
    duplicate: bool = False
    reply: Awaitable[Any] | None = None


@dataclass(frozen=True, slots=True)
class HistoryRow:
    id: int
    at: int
    role: str
    text: str
    source: str
    emotion: str | None
    emotion_intensity: float | None
    attachments: str


class MindPort(Protocol):
    async def perceive(self, p: PerceptionReceived, *, dedupe_key: str | None = None) -> Admission: ...

    async def connected(self, c: Connected) -> None: ...

    async def disconnected(self, handle: str, connection: str) -> None: ...

    def frame(self) -> Frame: ...

    def recent(self, handle: str, limit: int) -> list[HistoryRow]: ...

    def after(self, handle: str, after_id: int, limit: int) -> tuple[list[HistoryRow], bool]: ...

    def ready(self) -> bool: ...
