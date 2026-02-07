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

logger = logging.getLogger(__name__)


class TelegramModule(BaseModule):
    def __init__(self):
        super().__init__("telegram")
        self._chat_handler = None
        self._app: Application | None = None

    def set_chat_handler(self, handler):
        self._chat_handler = handler

    async def on_start(self):
        if not settings.TELEGRAM_TOKEN:
            self.logger.warning("No Telegram token configured, skipping")
            return

        self._app = Application.builder().token(settings.TELEGRAM_TOKEN).build()
        self._app.add_handler(CommandHandler("start", self._handle_start))
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        self.logger.info("Telegram bot started")

    async def on_stop(self):
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    async def on_message(self, message: str, source: str) -> str | None:
        return None

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(personality.greeting)

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return

        if self._chat_handler:
            person_id = f"tg_{update.message.from_user.id}"
            response_text, _ = await self._chat_handler(
                update.message.text, source="telegram", person_id=person_id,
            )
            await update.message.reply_text(response_text)
        else:
            await update.message.reply_text(
                "Je ne suis pas encore connectée au cerveau !"
            )
