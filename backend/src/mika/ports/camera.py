"""Le port de la caméra : la dernière image de chaque appareil.

Les appareils (un portable, une webcam de bureau) envoient des images ; le
port garde la dernière de chacun, en mémoire — une image n'entre jamais dans
sa vie : seulement ce qu'elle y a vu.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Snapshot:
    device: str
    mime: str
    data: bytes
    at: int  # instant (µs) de réception
    digest: str  # empreinte grossière : l'image a-t-elle changé ?


class CameraPort(Protocol):
    def devices(self) -> list[str]: ...

    def latest(self, device: str) -> Snapshot | None: ...
