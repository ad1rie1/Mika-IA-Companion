"""Le port de livraison : ce qu'elle dit part vers les transports.

La file de sortie appelle ``deliver`` après le commit, au moins une fois :
une livraison porte sa clé d'idempotence (l'identifiant de l'événement).
Un transport ne livre qu'aux personnes connectées ; une personne absente
rattrape par l'historique, jamais par une diffusion à tout le monde.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class EmotionView:
    emotion: str
    intensity: float
    blend: tuple[tuple[str, float], ...] = ()
    state: Mapping[str, Any] = field(default_factory=dict)
    declared: bool = False


@dataclass(frozen=True, slots=True)
class Delivery:
    key: str
    target: str | None  # poignée ; None = personne en particulier (groupe commun)
    channel: str | None
    room: str | None
    text: str  # jetons prosodiques compris : la voix en a besoin
    persona: str  # vocab.voice.SPEAKING | INNER
    emotion: EmotionView
    message_id: int
    reply_to: int | None = None
    client_msg_id: str | None = None
    source: str = "reply"
    sleep_phase: str = "awake"
    local_hour: int = 12
    kind: str = "speech"


class DeliveryPort(Protocol):
    async def deliver(self, d: Delivery) -> bool: ...
