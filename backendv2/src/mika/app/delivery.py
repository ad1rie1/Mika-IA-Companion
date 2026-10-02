"""Où part ce qu'elle dit : chaque énoncé vers le transport de son adresse."""

from __future__ import annotations

from typing import Any

from mika.adapters.telegram.channel import CHANNEL, HANDLE_PREFIX, ROOM_PREFIX
from mika.ports import delivery as delivery_p
from mika.ports.delivery import Delivery
from mika.vocab import voice


class Router:
    """Telegram pour ses adresses et ses salons ; le web pour le reste. Une pensée
    à voix haute ne part jamais en message : elle va au web (les écrans de la
    personne visée, ou des opératrices), même quand elle concerne une adresse
    Telegram. Un canal pas (encore) là rend ``False`` : la livraison est à
    réessayer, pas faite."""

    def __init__(self, web: Any, telegram: Any = None) -> None:
        self.web = web
        self.telegram = telegram

    @staticmethod
    def is_telegram(d: Delivery) -> bool:
        return (d.channel == CHANNEL or (d.room or "").startswith(ROOM_PREFIX)
                or (d.target or "").startswith(HANDLE_PREFIX))

    async def deliver(self, d: Delivery) -> bool:
        if d.kind == delivery_p.STATE:
            return bool(await self.web.deliver(d))  # un changement d'état se montre, ne s'écrit pas
        if d.kind == delivery_p.SPEECH and d.persona == voice.INNER:
            return bool(await self.web.deliver(d))  # une pensée se murmure à un écran, jamais en message
        if self.is_telegram(d):
            if self.telegram is None:
                return False  # le robot n'est pas (encore) là : à réessayer, pas « fait »
            return bool(await self.telegram.deliver(d))
        return bool(await self.web.deliver(d))
