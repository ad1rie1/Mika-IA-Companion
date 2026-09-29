"""La colle avec python-telegram-bot : relever les messages (polling) et les
traduire en ``Inbound`` ; envoyer par le robot. Tout le reste (liste blanche,
limites, perceptions, livraison) vit dans ``channel`` et se teste sans réseau.
"""

from __future__ import annotations

import logging
from typing import Any

from mika.adapters.telegram.channel import Inbound, Media, TelegramChannel

log = logging.getLogger("mika.telegram")


def media_of(message: Any) -> tuple[Media, ...]:
    """Les fichiers joints d'un message (la plus grande taille d'une photo)."""
    out: list[Media] = []
    photos = getattr(message, "photo", None) or ()
    if photos:
        best = photos[-1]
        out.append(Media(str(best.file_id), "photo.jpg", "image/jpeg", int(getattr(best, "file_size", 0) or 0)))
    voice = getattr(message, "voice", None)
    if voice is not None:
        out.append(Media(str(voice.file_id), "vocal.ogg", str(getattr(voice, "mime_type", "") or "audio/ogg"),
                         int(getattr(voice, "file_size", 0) or 0)))
    for attr, default_name, default_mime in (("audio", "audio", "audio/mpeg"),
                                             ("document", "document", "application/octet-stream")):
        f = getattr(message, attr, None)
        if f is not None:
            out.append(Media(str(f.file_id), str(getattr(f, "file_name", "") or default_name),
                             str(getattr(f, "mime_type", "") or default_mime), int(getattr(f, "file_size", 0) or 0)))
    return tuple(out)


def inbound_from_update(update: Any, bot_id: int, bot_username: str) -> Inbound | None:
    """Un ``telegram.Update`` → ``Inbound`` (``None`` : rien à percevoir)."""
    message = getattr(update, "message", None) or getattr(update, "edited_message", None)
    if message is None:
        return None
    media = media_of(message)
    if not getattr(message, "text", None) and not media:
        return None
    user = getattr(message, "from_user", None)
    chat = getattr(message, "chat", None)
    if user is None or chat is None or getattr(user, "is_bot", False):
        return None
    text = str(getattr(message, "text", None) or getattr(message, "caption", None) or "")
    mention = f"@{bot_username}".lower() if bot_username else ""
    replied = getattr(message, "reply_to_message", None)
    reply_to_me = bool(replied and getattr(replied, "from_user", None) and replied.from_user.id == bot_id)
    name = " ".join(p for p in (getattr(user, "first_name", ""), getattr(user, "last_name", "")) if p)
    return Inbound(
        update_id=int(update.update_id), chat_id=int(chat.id), chat_type=str(chat.type), user_id=int(user.id),
        name=name or str(getattr(user, "username", "") or ""), text=text,
        mentions_me=bool(mention and mention in text.lower()), reply_to_me=reply_to_me, media=media,
    )


class PtbBot:
    """Le robot réel, vu par ``TelegramChannel`` (le protocole ``Bot``)."""

    def __init__(self, bot: Any) -> None:
        self._bot = bot

    async def send_message(self, chat_id: int, text: str) -> None:
        await self._bot.send_message(chat_id=chat_id, text=text)

    async def download(self, file_id: str) -> bytes:
        f = await self._bot.get_file(file_id)
        return bytes(await f.download_as_bytearray())


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
        wanted = filters.TEXT | filters.PHOTO | filters.VOICE | filters.AUDIO | filters.Document.ALL
        self.app.add_handler(MessageHandler(wanted & ~filters.COMMAND, self._on_message))

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
