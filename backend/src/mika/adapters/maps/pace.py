"""Ce qui sort vers les services de la carte (ADR 0194) : au plus tant de demandes par seconde, espacées — pour tout
le processus quand le service le demande (le Valhalla public de FOSSGIS : une par seconde) —, et un client HTTP qui
ne dit rien de la personne (l'agent de ce serveur, aucun cookie, pas de redirection)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import httpx

from mika.adapters.maps.tiles import USER_AGENT, no_cookies
from mika.ports.maps import MapsUnavailable


class Pace:
    """Au plus ``rate`` demandes par seconde, espacées d'autant : chacune prend son tour, et attend s'il le faut ;
    une file plus longue que ``wait_max`` secondes refuse la demande (en mots) plutôt que de la faire attendre."""

    def __init__(self, rate: float, *, wait_max: float = 10.0, busy: str = "",
                 now: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[object]] = asyncio.sleep) -> None:
        if rate <= 0:
            raise ValueError("un débit positif")
        self.rate = rate
        self.wait_max = wait_max
        self.busy = busy or "Ce service est très demandé : réessaie dans un instant."
        self._now = now
        self._sleep = sleep
        self._next = 0.0

    async def turn(self) -> None:
        now = self._now()
        slot = max(now, self._next)
        if slot - now > self.wait_max:
            raise MapsUnavailable(self.busy)
        self._next = slot + 1.0 / self.rate
        if slot > now:
            await self._sleep(slot - now)


def client(timeout: float, transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    """Un client pour un service de la carte : l'agent de ce serveur, sans cookie, sans suivre de redirection."""
    return httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT}, transport=transport,
                             follow_redirects=False, cookies=no_cookies())
