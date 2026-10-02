"""La colle avec python-telegram-bot : relever les messages (polling) et les
traduire en ``Inbound`` ; envoyer par le robot. Tout le reste (liste blanche,
limites, perceptions, livraison) vit dans ``channel`` et se teste sans réseau.

- Les mises à jour sont traitées **en parallèle** (un message qui télécharge
  une photo ne retient pas les autres conversations), mais **une à la fois par
  conversation** (un verrou par chat : l'ordre d'un fil est gardé).
- Une **édition** n'est pas un nouveau message : écartée (elle recevait une
  seconde réponse).
- Les **mentions** se lisent dans les entités du message (``@robot`` exact, ou
  la mention d'un compte qui est le robot) — jamais par sous-chaîne
  (``@mika_bot_officiel`` n'est pas ``@mika_bot``).
- ``/start`` (la personne ouvre la conversation) est une arrivée, perçue comme
  telle ; les autres commandes sont ignorées.
- Les noms de fichiers reçus sont assainis (contrôles, chemins, longueur).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import OrderedDict
from typing import Any

from mika.adapters.telegram.channel import Inbound, Media, TelegramChannel

log = logging.getLogger("mika.telegram")

#: les verrous de conversation gardés (les plus anciens libres sont oubliés)
LOCKS_KEPT = 1024
FILENAME_MAX = 80
_UNSAFE = re.compile(r"[\x00-\x1f\x7f/\\]+")


def safe_name(name: Any, default: str) -> str:
    """Un nom de fichier sûr à montrer : sans caractères de contrôle ni chemin, borné."""
    text = _UNSAFE.sub(" ", str(name or "")).strip().lstrip(".")
    return (" ".join(text.split()) or default)[:FILENAME_MAX]


def media_of(message: Any) -> tuple[Media, ...]:
    """Les fichiers joints d'un message (la plus grande taille d'une photo)."""
    out: list[Media] = []
    photos = getattr(message, "photo", None) or ()
    if photos:
        best = photos[-1]
        out.append(Media(str(best.file_id), "photo.jpg", "image/jpeg", int(getattr(best, "file_size", 0) or 0)))
    voice = getattr(message, "voice", None)
    if voice is not None:
        out.append(Media(str(voice.file_id), "vocal.ogg", str(getattr(voice, "mime_type", "") or "audio/ogg")[:100],
                         int(getattr(voice, "file_size", 0) or 0)))
    for attr, default_name, default_mime in (("audio", "audio", "audio/mpeg"),
                                             ("document", "document", "application/octet-stream")):
        f = getattr(message, attr, None)
        if f is not None:
            out.append(Media(str(f.file_id), safe_name(getattr(f, "file_name", ""), default_name),
                             str(getattr(f, "mime_type", "") or default_mime)[:100],
                             int(getattr(f, "file_size", 0) or 0)))
    return tuple(out)


def _mentions(message: Any, text: str, bot_id: int, bot_username: str) -> bool:
    """La mention du robot, lue dans les entités du message (texte ou légende)."""
    wanted = f"@{bot_username}".lower() if bot_username else ""
    given = (getattr(message, "entities", None), getattr(message, "caption_entities", None))
    if given == (None, None):  # une forme sans entités du tout : le nom exact, borné (jamais une sous-chaîne)
        return bool(wanted) and re.search(rf"(?<![\w@]){re.escape(wanted)}(?![\w])", text.lower()) is not None
    entities = [e for group in given for e in (group or ())]
    for e in entities:
        kind = str(getattr(e, "type", "") or "").lower().rsplit(".", 1)[-1]
        if kind == "text_mention":
            user = getattr(e, "user", None)
            if user is not None and getattr(user, "id", None) == bot_id:
                return True
        elif kind == "mention" and wanted:
            offset, length = int(getattr(e, "offset", 0) or 0), int(getattr(e, "length", 0) or 0)
            if _utf16_slice(text, offset, length).lower() == wanted:
                return True
    return False


def _utf16_slice(text: str, offset: int, length: int) -> str:
    """Telegram compte les positions des entités en unités UTF-16."""
    raw = text.encode("utf-16-le")
    return raw[offset * 2:(offset + length) * 2].decode("utf-16-le", errors="ignore")


def inbound_from_update(update: Any, bot_id: int, bot_username: str, *, opened: bool = False) -> Inbound | None:
    """Un ``telegram.Update`` → ``Inbound`` (``None`` : rien à percevoir). Une édition
    (``edited_message``) n'est pas un nouveau message."""
    message = getattr(update, "message", None)
    if message is None:
        return None
    media = media_of(message)
    if not getattr(message, "text", None) and not media and not opened:
        return None
    user = getattr(message, "from_user", None)
    chat = getattr(message, "chat", None)
    if user is None or chat is None or getattr(user, "is_bot", False):
        return None
    text = str(getattr(message, "text", None) or getattr(message, "caption", None) or "")
    replied = getattr(message, "reply_to_message", None)
    reply_to_me = bool(replied and getattr(replied, "from_user", None) and replied.from_user.id == bot_id)
    name = " ".join(p for p in (getattr(user, "first_name", ""), getattr(user, "last_name", "")) if p)
    return Inbound(
        update_id=int(update.update_id), chat_id=int(chat.id), chat_type=str(chat.type), user_id=int(user.id),
        name=name or str(getattr(user, "username", "") or ""), text="" if opened else text,
        mentions_me=_mentions(message, text, bot_id, bot_username), reply_to_me=reply_to_me, media=media,
        message_id=int(getattr(message, "message_id", 0) or 0), opened=opened,
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


class ChatLocks:
    """Un verrou par conversation : en parallèle entre conversations, dans l'ordre dans chacune."""

    def __init__(self, kept: int = LOCKS_KEPT) -> None:
        self.kept = kept
        self._locks: OrderedDict[int, asyncio.Lock] = OrderedDict()

    def of(self, chat_id: int) -> asyncio.Lock:
        lock = self._locks.get(chat_id)
        if lock is None:
            lock = self._locks[chat_id] = asyncio.Lock()
        self._locks.move_to_end(chat_id)
        while len(self._locks) > self.kept:
            oldest, held = next(iter(self._locks.items()))
            if held.locked():
                break
            del self._locks[oldest]
        return lock


class Poller:
    """Relève les messages et les passe au canal ; démarre et s'arrête avec
    le serveur."""

    def __init__(self, token: str, make_channel: Any) -> None:
        from telegram.ext import (  # noqa: PLC0415 — seulement si configuré
            Application,
            CommandHandler,
            MessageHandler,
            filters,
        )

        self.app = Application.builder().token(token).concurrent_updates(True).build()
        self.channel: TelegramChannel = make_channel(PtbBot(self.app.bot))
        self.locks = ChatLocks()
        wanted = filters.TEXT | filters.PHOTO | filters.VOICE | filters.AUDIO | filters.Document.ALL
        # les éditions sont écartées : elles recevaient une seconde réponse
        self.app.add_handler(MessageHandler(wanted & ~filters.COMMAND & filters.UpdateType.MESSAGE, self._on_message))
        self.app.add_handler(CommandHandler("start", self._on_start, filters=filters.UpdateType.MESSAGE))

    async def _on_message(self, update: Any, context: Any) -> None:
        me = self.app.bot
        await self._handle(inbound_from_update(update, me.id, me.username or ""))

    async def _on_start(self, update: Any, context: Any) -> None:
        me = self.app.bot
        await self._handle(inbound_from_update(update, me.id, me.username or "", opened=True))

    async def _handle(self, got: Inbound | None) -> None:
        if got is None:
            return
        async with self.locks.of(got.chat_id):
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
