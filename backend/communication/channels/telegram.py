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

logger = logging.getLogger(__name__)


class TelegramChannel:
    """Bot lifecycle + message-to-perception bridge."""

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

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        self._running = True
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
            logger.info("Telegram bot stopped")

    # ── Handlers ────────────────────────────────────────────────

    async def _handle_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await update.message.reply_text(personality.greeting)

    async def _handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        if not update.message or not update.message.text:
            return

        person_id = f"tg_{update.message.from_user.id}"
        chat_id = update.message.chat_id
        display_name = update.message.from_user.full_name or ""

        # Register the interlocutor so Mika can reach this user PROACTIVELY
        # later (the external API is push-capable any time we hold the chat_id),
        # and persist the handle so it survives restarts. Also stops a telegram
        # turn from leaking to the global websocket broadcast: the recipient is
        # now resolvable, and broadcast skips the originating module's echo.
        from communication.presence import presence_registry

        presence_registry.register(
            person_id=person_id,
            channel="telegram",
            kind="module",
            delivery_ref=str(chat_id),
            display_name=display_name,
        )
        from identity.resolver import identity_resolver

        await identity_resolver.link_handle(
            person_id=person_id,
            channel="telegram",
            kind="module",
            delivery_ref=str(chat_id),
            display_name=display_name,
        )

        from pipeline.perception import Perception
        from pipeline.router import perceive

        perception = Perception.from_text(
            update.message.text,
            source="telegram",
            person_id=person_id,
        )
        # Reactive reply: we echo here. The pipeline's broadcast routing skips
        # the originating module on a reactive turn, so there is no double-send.
        output = await perceive(perception)
        if output and output.text:
            await update.message.reply_text(output.text)

    # ── Outbound delivery (proactive push) ────────────────────────

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
