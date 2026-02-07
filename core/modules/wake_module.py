import asyncio
import logging
from typing import Callable, Awaitable

from fastapi import APIRouter

from core.memory import database as db
from core.modules.base_module import BaseModule

logger = logging.getLogger(__name__)

# Default prompt sent to the AI when woken up without a custom prompt
DEFAULT_WAKE_PROMPT = (
    "Tu viens de te réveiller ! Dis bonjour à ton audience de manière naturelle, "
    "comme si tu revenais d'une pause. Sois toi-même."
)


class WakeModule(BaseModule):
    """Module that periodically checks for wake requests and triggers AI responses.

    Wake requests can be created via:
    - The REST API endpoint POST /api/wake
    - External cron jobs calling the API
    - Direct DB inserts from other modules

    When a pending wake request is found, the module triggers a chat response
    and broadcasts it to all connected WebSocket clients.
    """

    def __init__(self, poll_interval: float = 30.0):
        super().__init__("wake")
        self._chat_handler: Callable[[str, str], Awaitable] | None = None
        self._poll_interval = poll_interval
        self._poll_task: asyncio.Task | None = None

    def set_chat_handler(self, handler: Callable[[str, str], Awaitable]):
        self._chat_handler = handler

    async def on_start(self):
        self._poll_task = asyncio.create_task(self._poll_loop())
        self.logger.info(
            "Wake module started (polling every %.0fs)", self._poll_interval
        )

    async def on_stop(self):
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        self.logger.info("Wake module stopped")

    async def on_message(self, message: str, source: str) -> str | None:
        return None

    # ---- API router (collected by ModuleManager) ----

    def get_router(self) -> APIRouter:
        router = APIRouter(prefix="/api/wake", tags=["wake"])
        module = self  # capture for closures

        @router.post("")
        async def api_wake(body: dict | None = None):
            """Queue a wake request. The poll loop processes it within poll_interval."""
            body = body or {}
            wake_id = await module.trigger_wake(
                source=body.get("source", "api"),
                prompt=body.get("prompt"),
            )
            return {"status": "queued", "wake_id": wake_id}

        @router.post("/now")
        async def api_wake_now(body: dict | None = None):
            """Create AND process a wake request immediately."""
            body = body or {}
            wake_id = await db.create_wake_request(
                source=body.get("source", "api"),
                prompt=body.get("prompt"),
            )
            await module._process_pending_requests()
            return {"status": "processed", "wake_id": wake_id}

        return router

    # ---- Internal logic ----

    async def _poll_loop(self):
        while self._running:
            try:
                await self._process_pending_requests()
            except Exception:
                self.logger.exception("Error processing wake requests")
            await asyncio.sleep(self._poll_interval)

    async def _process_pending_requests(self):
        requests = await db.get_pending_wake_requests()
        for req in requests:
            wake_id = req["id"]
            source = req["source"]
            prompt = req["prompt"] or DEFAULT_WAKE_PROMPT

            self.logger.info("Processing wake request #%d from %s", wake_id, source)

            if self._chat_handler:
                try:
                    await self._chat_handler(prompt, f"wake:{source}")
                except Exception:
                    self.logger.exception(
                        "Failed to process wake request #%d", wake_id
                    )

            await db.mark_wake_processed(wake_id)

    async def trigger_wake(self, source: str = "api", prompt: str | None = None) -> int:
        wake_id = await db.create_wake_request(source=source, prompt=prompt)
        self.logger.info("Wake request #%d created from %s", wake_id, source)
        return wake_id
