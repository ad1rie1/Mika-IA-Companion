"""Le port d'entrée : ce que les adaptateurs (web, Telegram…) peuvent
demander au cœur. Ils ne voient jamais le Mind ni les facultés : ils
soumettent des stimulus, lisent des vues, et reçoivent les livraisons.

Rangé dans ``contracts`` : c'est le contrat public du cœur envers les
adaptateurs, et il parle la langue des contrats (perceptions, présence).
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
    #: elle dort : la réponse attend son réveil (l'écran ne montre pas « Mika écrit… » pendant ce temps)
    held: bool = False


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

    def health(self) -> dict[str, Any]:
        """``{"status", "ready", "checks": {nom: état}}`` : des noms et des états,
        jamais un contenu (la route est publique)."""
        ...

    def person_panel(self, handle: str) -> dict[str, Any] | None:
        """Ce que le panneau montre de la personne (identité ; profil et
        promesses seulement si sa fiche est ouverte ; projets et actions en
        attente seulement pour une propriétaire)."""
        ...

    async def sense(self, device: str, text: str, *, pertinence: float = 0.5, emotion: str = "",
                    sensitivity: int = 1) -> int | None:
        """Un appareil lui signale quelque chose ; rend le ``seq`` (``None`` : refusé)."""
        ...

    async def resolve_effect(self, proposal: int, approved: bool, *, by: str, note: str = "",
                             seen: str = "") -> str:
        """Approuver ou refuser un effet externe proposé : ``"approved"``,
        ``"rejected"``, ``"unknown"`` (rien en attente sous ce numéro)."""
        ...
