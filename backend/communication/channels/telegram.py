"""Telegram channel — direct ``communication`` app citizen.

Telegram is not a plugin. It is one of the ways Mika can be reached,
on the same footing as the WebSocket frontend. The channel is started
and stopped by the ASGI lifespan alongside memory, emotion, and the
plugin bus.

Incoming Telegram messages are lifted into a ``Perception`` and pushed
through ``pipeline.router.perceive()`` — identical flow to the web
frontend channel.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config.personality import personality
from pipeline.voice import VoiceSink
from utils.degradation import degradations

logger = logging.getLogger(__name__)


class TelegramChannel:
    """Bot lifecycle + message-to-perception bridge."""

    # Telegram voice notes are played on the recipient's terms, so the time
    # of day doesn't gate them (see pipeline/voice.py). Delivery still falls
    # back to text whenever no synthesizer is installed.
    VOICE_SINK = VoiceSink.MESSAGE

    def __init__(self) -> None:
        self._app: Application | None = None
        self._running: bool = False

    # ── Availability ────────────────────────────────────────────

    @staticmethod
    def is_available() -> bool:
        from configs.service import config_service
        return bool(config_service.get("telegram.token", default=""))

    @property
    def is_running(self) -> bool:
        return self._running

    # ── Lifecycle ───────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        if not self.is_available():
            logger.info("Telegram channel skipped: no token configured")
            return

        from configs.service import config_service
        token = config_service.get("telegram.token", default="")

        self._app = Application.builder().token(token).build()
        self._app.add_handler(CommandHandler("start", self._handle_start))
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )
        # Inbound media: photos → vision caption, voice/audio → transcript,
        # documents → text extraction. The pipeline's preprocessors do the
        # heavy lifting; this handler only downloads + lifts to a Perception.
        self._app.add_handler(
            MessageHandler(
                filters.PHOTO | filters.VOICE | filters.AUDIO | filters.Document.ALL,
                self._handle_media,
            )
        )

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        self._running = True
        # Declare ourselves as the deliverer for presence targets tagged
        # "telegram" — we are a channel, not a module, so module_manager
        # cannot resolve us.
        from communication.delivery import register_channel
        register_channel("telegram", self)
        logger.info("Telegram bot started")

    async def stop(self) -> None:
        if not self._app:
            return
        try:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        finally:
            self._app = None
            self._running = False
            from communication.delivery import unregister_channel
            unregister_channel("telegram")
            logger.info("Telegram bot stopped")

    # ── Handlers ────────────────────────────────────────────────

    async def _handle_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await update.message.reply_text(personality.greeting)

    @staticmethod
    def _is_public_chat(message) -> bool:
        """True when the message came from a group / channel, not a DM.

        This is the "média public" case: in a room where anyone can type,
        a Telegram account id still identifies the *account*, but the
        conversation around it is not private, so Mika must not read out
        someone's personal history on the strength of a display name.
        """
        chat_type = getattr(getattr(message, "chat", None), "type", "") or ""
        return chat_type in ("group", "supergroup", "channel")

    async def _register_interlocutor(self, message) -> tuple[str, bool]:
        """Register presence + identity for the sender.

        Returns ``(person_id, is_public)``. Registering makes this user
        PROACTIVELY reachable later (the external API is push-capable any
        time we hold the chat_id) and stops a telegram turn from leaking to
        the global websocket broadcast: the recipient is resolvable, and
        broadcast skips the originating module's echo.

        Trust is the platform account, never more: ``tg_<id>`` proves the
        same account came back, not who is holding it. In a group it drops
        to public. Either way Mika has to be convinced before she treats
        this person as someone she knows.
        """
        person_id = f"tg_{message.from_user.id}"
        chat_id = message.chat_id
        display_name = message.from_user.full_name or ""
        is_public = self._is_public_chat(message)

        from communication.presence import presence_registry

        presence_registry.register(
            person_id=person_id,
            channel="telegram",
            kind="module",
            delivery_ref=str(chat_id),
            display_name=display_name,
        )
        from identity.resolver import identity_resolver
        from identity.trust import ChannelTrust

        await identity_resolver.link_handle(
            person_id=person_id,
            channel="telegram",
            kind="module",
            delivery_ref=str(chat_id),
            display_name=display_name,
            trust=ChannelTrust.PUBLIC if is_public else ChannelTrust.ACCOUNT,
        )
        return person_id, is_public

    async def _handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        if not update.message or not update.message.text:
            return

        person_id, is_public = await self._register_interlocutor(update.message)

        from pipeline.perception import Perception
        from pipeline.router import perceive

        perception = Perception.from_text(
            update.message.text,
            source="telegram",
            person_id=person_id,
            metadata={"authenticated": False, "is_public": is_public},
        )
        # Reactive reply: we echo here. The pipeline's broadcast routing skips
        # the originating module on a reactive turn, so there is no double-send.
        output = await perceive(perception)
        if output and output.text:
            await update.message.reply_text(output.text)

    async def _handle_media(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Photos, voice notes, audio files, documents — with optional caption.

        Downloads the payload, wraps it as a MediaAttachment, and routes a
        MIXED Perception. The preprocessors turn it into text (caption /
        transcript / extraction) before the AI sees it — same path as a
        frontend upload.
        """
        message = update.message
        if not message:
            return

        person_id, is_public = await self._register_interlocutor(message)

        attachment = await self._download_media(message)
        if attachment is None:
            return

        from pipeline.perception import Perception
        from pipeline.router import perceive

        perception = Perception.from_mixed(
            text=message.caption or "",
            attachments=[attachment],
            source="telegram",
            person_id=person_id,
            metadata={"authenticated": False, "is_public": is_public},
        )
        output = await perceive(perception)
        if output and output.text:
            await message.reply_text(output.text)

    async def _download_media(self, message):
        """Pick the richest media on the message and download it.

        Returns a validated ``MediaAttachment`` or None (unsupported type,
        oversized payload, or download failure — all logged, none fatal).
        """
        from pipeline.media import (
            MAX_FILE_SIZE_BYTES,
            MediaAttachment,
            _categorize,
        )

        if message.voice:
            media = message.voice
            name = "note_vocale.ogg"
            mime = media.mime_type or "audio/ogg"
        elif message.audio:
            media = message.audio
            name = media.file_name or "audio.mp3"
            mime = media.mime_type or "audio/mpeg"
        elif message.photo:
            media = message.photo[-1]  # largest resolution
            name = "photo.jpg"
            mime = "image/jpeg"
        elif message.document:
            media = message.document
            name = media.file_name or "document"
            mime = media.mime_type or "application/octet-stream"
        else:
            return None

        size = getattr(media, "file_size", None)
        if size and size > MAX_FILE_SIZE_BYTES:
            logger.info(
                "Telegram media ignoré (trop grand): %s (%d o)", name, size
            )
            try:
                await message.reply_text(
                    "(fichier trop lourd pour moi — 5 Mo max)"
                )
            except Exception as exc:
                degradations.record("communication.channels.telegram._download_media", exc)
            return None

        try:
            import base64

            tg_file = await media.get_file()
            data = bytes(await tg_file.download_as_bytearray())
        except Exception:
            logger.exception("Téléchargement du média Telegram échoué (%s)", name)
            return None

        mime = mime.lower().split(";")[0].strip()
        return MediaAttachment(
            name=name,
            media_type=mime,
            data=base64.b64encode(data).decode("ascii"),
            category=_categorize(mime),
        )

    # ── Outbound delivery (proactive push) ────────────────────────

    async def deliver_voice(self, clip, output, interlocutor) -> bool:
        """Send the reply as a Telegram voice note, captioned with the text.

        Telegram wants OGG/Opus for a true voice bubble; anything else is
        sent as an audio document. Falling back to ``False`` puts the caller
        back on the text path.
        """
        if not self._app or not self.is_running:
            return False
        chat_id = interlocutor.delivery_ref
        if not chat_id:
            return False
        try:
            if clip.mime_type in ("audio/ogg", "audio/opus"):
                await self._app.bot.send_voice(
                    chat_id=int(chat_id), voice=clip.data,
                    caption=output.text[:1024],
                )
            else:
                await self._app.bot.send_audio(
                    chat_id=int(chat_id), audio=clip.data,
                    caption=output.text[:1024],
                )
            return True
        except Exception:
            logger.exception(
                "Telegram voice delivery failed for %s", interlocutor.person_id
            )
            return False

    async def deliver(self, output, interlocutor) -> bool:
        """Send a message to a Telegram user via the bot API (chat_id)."""
        if not self._app or not self.is_running:
            return False
        chat_id = interlocutor.delivery_ref
        if not chat_id:
            return False
        try:
            await self._app.bot.send_message(chat_id=int(chat_id), text=output.text)
            return True
        except Exception:
            logger.exception(
                "Telegram deliver failed for %s", interlocutor.person_id
            )
            return False


telegram_channel = TelegramChannel()
