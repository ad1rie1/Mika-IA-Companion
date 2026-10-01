"""Où part ce qu'elle dit : chaque énoncé vers le transport de son adresse."""

from __future__ import annotations

from typing import Any

from mika.adapters.telegram.channel import CHANNEL, HANDLE_PREFIX, ROOM_PREFIX
from mika.ports.delivery import Delivery


class Router:
    """Telegram pour ses adresses et ses salons ; le web pour le reste (y
    compris les pensées à voix haute, adressées à personne)."""

    def __init__(self, web: Any, telegram: Any = None) -> None:
        self.web = web
        self.telegram = telegram

    @staticmethod
    def is_telegram(d: Delivery) -> bool:
        return (d.channel == CHANNEL or (d.room or "").startswith(ROOM_PREFIX)
                or (d.target or "").startswith(HANDLE_PREFIX))

    async def deliver(self, d: Delivery) -> bool:
        if d.kind == "state":
            return bool(await self.web.deliver(d))  # un changement d'état se montre, ne s'écrit pas
        if self.is_telegram(d):
            if self.telegram is None:
                return True  # pas de robot configuré : rien à faire (le fil garde la trace)
            return bool(await self.telegram.deliver(d))
        return bool(await self.web.deliver(d))
