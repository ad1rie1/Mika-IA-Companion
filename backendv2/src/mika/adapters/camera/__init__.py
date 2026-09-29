"""La caméra réelle : un tampon en mémoire, alimenté par la route
WebSocket ``/ws/camera?device=…`` (opérateurs seulement)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from mika.ports.camera import Snapshot

MAX_BYTES = 3_000_000
MAX_DEVICES = 8


class CameraBuffer:
    def __init__(self, now: Callable[[], int]) -> None:
        self._now = now
        self._latest: dict[str, Snapshot] = {}

    def put(self, device: str, mime: str, data: bytes) -> bool:
        if not data or len(data) > MAX_BYTES or not mime.startswith("image/"):
            return False
        if device not in self._latest and len(self._latest) >= MAX_DEVICES:
            return False
        # une empreinte grossière (un échantillon) : un bruit de capteur ne compte pas comme un changement
        sample = data[:: max(1, len(data) // 4096)][:4096]
        digest = hashlib.sha256(bytes(b >> 4 for b in sample)).hexdigest()[:16]
        self._latest[device[:40]] = Snapshot(device[:40], mime, data, self._now(), digest)
        return True

    def devices(self) -> list[str]:
        return sorted(self._latest)

    def latest(self, device: str) -> Snapshot | None:
        return self._latest.get(device)
