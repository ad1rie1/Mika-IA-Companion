"""La colle avec python-telegram-bot : relever les messages (polling) et les
traduire en ``Inbound`` ; envoyer par le robot. Tout le reste (liste blanche,
limites, perceptions, livraison) vit dans ``channel`` et se teste sans réseau.
"""

from __future__ import annotations

import logging
from typing import Any

from mika.adapters.telegram.channel import Inbound, TelegramChannel

log = logging.getLogger("mika.telegram")


def inbound_from_update(update: Any, bot_id: int, bot_username: str) -> Inbound | None:
    """Un ``telegram.Update`` → ``Inbound`` (``None`` : rien à percevoir)."""
    message = getattr(update, "message", None) or getattr(update, "edited_message", None)
    if message is None or not getattr(message, "text", None):
        return None
    user = getattr(message, "from_user", None)
    chat = getattr(message, "chat", None)
    if user is None or chat is None or getattr(user, "is_bot", False):
        return None
    text = str(message.text)
    mention = f"@{bot_username}".lower() if bot_username else ""
    replied = getattr(message, "reply_to_message", None)
    reply_to_me = bool(replied and getattr(replied, "from_user", None) and replied.from_user.id == bot_id)
    name = " ".join(p for p in (getattr(user, "first_name", ""), getattr(user, "last_name", "")) if p)
    return Inbound(
        update_id=int(update.update_id), chat_id=int(chat.id), chat_type=str(chat.type), user_id=int(user.id),
        name=name or str(getattr(user, "username", "") or ""), text=text,
        mentions_me=bool(mention and mention in text.lower()), reply_to_me=reply_to_me,
    )


class PtbBot:
    """Le robot réel, vu par ``TelegramChannel`` (le protocole ``Bot``)."""

    def __init__(self, bot: Any) -> None:
        self._bot = bot

    async def send_message(self, chat_id: int, text: str) -> None:
        await self._bot.send_message(chat_id=chat_id, text=text)


class Poller:
    """Relève les messages et les passe au canal ; démarre et s'arrête avec
    le serveur."""

    def __init__(self, token: str, make_channel: Any) -> None:
        from telegram.ext import (  # noqa: PLC0415 — seulement si configuré
            Application,
            MessageHandler,
            filters,
        )

        self.app = Application.builder().token(token).build()
        self.channel: TelegramChannel = make_channel(PtbBot(self.app.bot))
        self._filters = filters
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message))

    async def _on_message(self, update: Any, context: Any) -> None:
        me = self.app.bot
        got = inbound_from_update(update, me.id, me.username or "")
        if got is None:
            return
        try:
            status = await self.channel.receive(got)
        except Exception as exc:  # un message ne fait jamais tomber la relève
            log.warning("message Telegram non traité : %r", exc)
            return
        if status not in ("accepted", "duplicate", "ignored"):
            log.info("message Telegram %s (chat %s)", status, got.chat_id)

    async def start(self) -> None:
        await self.app.initialize()
        await self.app.start()
        assert self.app.updater is not None
        await self.app.updater.start_polling(drop_pending_updates=False)

    async def stop(self) -> None:
        try:
            if self.app.updater is not None and self.app.updater.running:
                await self.app.updater.stop()
            if self.app.running:
                await self.app.stop()
        finally:
            await self.app.shutdown()
