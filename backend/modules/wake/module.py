import asyncio
import logging
from typing import Awaitable, Callable

from modules.base import BaseModule

logger = logging.getLogger(__name__)

DEFAULT_WAKE_PROMPT = (
    "Tu viens de te réveiller ! Dis bonjour à ton audience de manière naturelle, "
    "comme si tu revenais d'une pause. Sois toi-même."
)


class WakeModule(BaseModule):
    """Polls for wake requests and triggers AI responses."""

    def __init__(self, poll_interval: float = 30.0):
        super().__init__("wake")
        self._chat_handler: Callable[[str, str], Awaitable] | None = None
        self._poll_interval = poll_interval
        self._poll_task: asyncio.Task | None = None

    def set_chat_handler(self, handler: Callable[[str, str], Awaitable]):
        self._chat_handler = handler

    async def on_start(self):
        self._poll_task = asyncio.create_task(self._poll_loop())
        self.logger.info("Wake module started (polling every %.0fs)", self._poll_interval)

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

    async def _poll_loop(self):
        while self._running:
            try:
                await self._process_pending()
            except Exception:
                self.logger.exception("Error processing wake requests")
            await asyncio.sleep(self._poll_interval)

    async def _process_pending(self):
        from django.utils import timezone

        from modules.models import WakeRequest

        pending = WakeRequest.objects.filter(status=WakeRequest.Status.PENDING).order_by("created_at")
        async for req in pending:
            prompt = req.prompt or DEFAULT_WAKE_PROMPT
            self.logger.info("Processing wake request #%d from %s", req.pk, req.source)

            if self._chat_handler:
                try:
                    await self._chat_handler(
                        prompt, source=f"wake:{req.source}",
                        person_id=f"wake_{req.source}",
                    )
                except Exception:
                    self.logger.exception("Failed to process wake #%d", req.pk)

            req.status = WakeRequest.Status.PROCESSED
            req.processed_at = timezone.now()
            await req.asave()

    async def trigger_wake(self, source: str = "api", prompt: str | None = None) -> int:
        from modules.models import WakeRequest

        req = await WakeRequest.objects.acreate(source=source, prompt=prompt)
        self.logger.info("Wake request #%d created from %s", req.pk, source)
        return req.pk
