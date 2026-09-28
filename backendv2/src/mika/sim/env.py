"""L'environnement d'une simulation : pièges contre les fuites du monde réel.

- **Sentinelle d'horloge** : l'heure ambiante du processus est figée au
  1er janvier 1999 ; un code qui lit l'heure système au lieu de l'horloge
  injectée produit des dates absurdes, que les contrôles détectent.
- **Fuseau piège** : ``TZ=Pacific/Kiritimati`` (UTC+14) — un calcul d'heure
  locale qui passe par le fuseau du processus décale tout d'environ 12 h.
- **Garde réseau** : toute connexion réseau lève.
"""

from __future__ import annotations

import contextlib
import os
import socket
import time
from collections.abc import Iterator
from datetime import UTC, datetime

import time_machine

from mika.sim.clock import RealIOInSimulation

SENTINEL = datetime(1999, 1, 1, tzinfo=UTC)
TRAP_TZ = "Pacific/Kiritimati"


@contextlib.contextmanager
def sim_environment(*, freeze: bool = True, trap_tz: bool = True, block_network: bool = True) -> Iterator[None]:
    saved_tz = os.environ.get("TZ")
    saved_connect = socket.socket.connect
    saved_getaddrinfo = socket.getaddrinfo
    traveller = time_machine.travel(SENTINEL, tick=False) if freeze else None
    try:
        # Figer d'abord : time-machine repose le fuseau du processus en démarrant.
        if traveller is not None:
            traveller.start()
            traveller = _Started(traveller)
        if trap_tz:
            os.environ["TZ"] = TRAP_TZ
            time.tzset()
        if block_network:
            def _no_connect(self: socket.socket, *args: object, **kwargs: object) -> None:
                raise RealIOInSimulation(f"connexion réseau en simulation : {args!r}")

            def _no_dns(*args: object, **kwargs: object) -> list[object]:
                raise RealIOInSimulation(f"résolution DNS en simulation : {args!r}")

            socket.socket.connect = _no_connect  # type: ignore[method-assign]
            socket.getaddrinfo = _no_dns  # type: ignore[assignment]
        yield
    finally:
        if isinstance(traveller, _Started):
            traveller.inner.stop()
        socket.socket.connect = saved_connect  # type: ignore[method-assign]
        socket.getaddrinfo = saved_getaddrinfo  # type: ignore[assignment]
        if trap_tz:
            if saved_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = saved_tz
            time.tzset()


class _Started:
    """Un voyage dans le temps démarré (à arrêter en sortie)."""

    def __init__(self, inner: time_machine.travel) -> None:
        self.inner = inner


def looks_like_sentinel(t_us: int) -> bool:
    """Un instant proche de la sentinelle trahit une lecture de l'heure système."""
    sentinel_us = int(SENTINEL.timestamp()) * 1_000_000
    return abs(t_us - sentinel_us) < 400 * 86_400 * 1_000_000
