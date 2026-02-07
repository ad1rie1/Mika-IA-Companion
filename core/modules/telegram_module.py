import asyncio
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from core.config import personality, settings
from core.modules.base_module import BaseModule

logger = logging.getLogger(__name__)


class TelegramModule(BaseModule):
    def __init__(self):
        super().__init__("telegram")
        self._chat_handler = None
        self._app: Application | None = None

    def set_chat_handler(self, handler):
        """Set the function to call when a message is received.
        handler(message: str, source: str) -> (response_text, emotion)
        """
        self._chat_handler = handler

    async def on_start(self):
        if not settings.telegram_token:
            self.logger.warning("No Telegram token configured, skipping Telegram module")
            return

        self._app = Application.builder().token(settings.telegram_token).build()

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

        user_message = update.message.text

        if self._chat_handler:
            response_text, emotion = await self._chat_handler(
                user_message, source="telegram"
            )
            await update.message.reply_text(response_text)
        else:
            await update.message.reply_text("Je ne suis pas encore connectée au cerveau !")
