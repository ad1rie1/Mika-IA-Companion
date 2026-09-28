"""Le serveur (HTTP + WebSocket) — construit en M1."""

from __future__ import annotations

from pathlib import Path


def serve(*, host: str, port: int, data: Path) -> None:
    raise NotImplementedError("le serveur arrive avec M1")
