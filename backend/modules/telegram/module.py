"""Telegram module — bot integration via python-telegram-bot."""

from __future__ import annotations

import logging

from django.conf import settings
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config.personality import personality
from modules.base import BaseModule
from modules.types import ModuleNotification

logger = logging.getLogger(__name__)


class TelegramModule(BaseModule):
    def __init__(self):
        super().__init__("telegram")
        self._app: Application | None = None

    # ── Lifecycle ─────────────────────────────────────────────────

    def is_available(self) -> bool:
        return bool(settings.TELEGRAM_TOKEN)

    async def instantiate(self) -> None:
        self._app = Application.builder().token(settings.TELEGRAM_TOKEN).build()
        self._app.add_handler(CommandHandler("start", self._handle_start))
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        self.logger.info("Telegram bot started")

    async def shutdown(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    # ── Handlers ──────────────────────────────────────────────────

    async def _handle_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await update.message.reply_text(personality.greeting)

    async def _handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        if not update.message or not update.message.text:
            return

        if self._notify_ai:
            person_id = f"tg_{update.message.from_user.id}"
            decision = await self._notify_ai(
                ModuleNotification(
                    source_module=self.name,
                    summary=f"Telegram message from user {update.message.from_user.id}",
                    details=update.message.text,
                    urgency="normal",
                    metadata={"person_id": person_id},
                )
            )
            await update.message.reply_text(decision.response_text)
        else:
            await update.message.reply_text(
                "Je ne suis pas encore connectée au cerveau !"
            )

    # ── Context ───────────────────────────────────────────────────

    def get_context(self) -> str:
        if self._app and self.is_running:
            return "Telegram bot is connected and receiving messages."
        return ""
