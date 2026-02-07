import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import personality, settings
from core.modules.telegram_module import TelegramModule
from core.modules.wake_module import WakeModule
from core.server.api_routes import handle_chat, memory, router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

telegram = TelegramModule()
wake = WakeModule(poll_interval=30.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    await memory.initialize()
    logger.info("Memory system initialized")

    telegram.set_chat_handler(handle_chat)
    await telegram.start()

    wake.set_chat_handler(handle_chat)
    await wake.start()

    yield

    # --- Shutdown ---
    await wake.stop()
    await telegram.stop()
    logger.info("VTuber Engine shut down cleanly")


app = FastAPI(title=f"VTuber Engine - {personality.name}", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


# --- Wake API routes ---


@app.post("/api/wake")
async def api_wake(body: dict | None = None):
    """Trigger a wake request via API.

    Body (optional JSON):
        {"prompt": "Custom wake prompt", "source": "cron"}

    If no prompt is provided, the default wake prompt is used.
    The wake module's poll loop will pick it up, or you can use
    /api/wake/now to trigger immediately.
    """
    body = body or {}
    source = body.get("source", "api")
    prompt = body.get("prompt")
    wake_id = await wake.trigger_wake(source=source, prompt=prompt)
    return {"status": "queued", "wake_id": wake_id}


@app.post("/api/wake/now")
async def api_wake_now(body: dict | None = None):
    """Trigger an immediate wake: creates the request AND processes it right away."""
    from core.memory import database as db

    body = body or {}
    source = body.get("source", "api")
    prompt = body.get("prompt")

    wake_id = await db.create_wake_request(source=source, prompt=prompt)
    await wake._process_pending_requests()
    return {"status": "processed", "wake_id": wake_id}


def main():
    logger.info("Starting VTuber Engine for %s", personality.name)
    logger.info("API: http://localhost:%d", settings.api_port)
    logger.info("WebSocket: ws://localhost:%d/ws", settings.api_port)
    uvicorn.run(app, host="0.0.0.0", port=settings.api_port)


if __name__ == "__main__":
    main()
