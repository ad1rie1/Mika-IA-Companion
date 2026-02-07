import logging

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import personality, settings
from core.modules.telegram_module import TelegramModule
from core.server.api_routes import handle_chat, memory, router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title=f"VTuber Engine - {personality.name}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


telegram = TelegramModule()


@app.on_event("startup")
async def startup():
    await memory.initialize()
    logger.info("Memory system initialized")

    # Start Telegram module
    telegram.set_chat_handler(handle_chat)
    await telegram.start()


def main():
    logger.info("Starting VTuber Engine for %s", personality.name)
    logger.info("API: http://localhost:%d", settings.api_port)
    logger.info("WebSocket: ws://localhost:%d/ws", settings.api_port)
    uvicorn.run(app, host="0.0.0.0", port=settings.api_port)


if __name__ == "__main__":
    main()
