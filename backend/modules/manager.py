import asyncio
import logging
from typing import Awaitable, Callable

from modules.base import BaseModule

logger = logging.getLogger(__name__)

DEFAULT_TICK_INTERVAL = 60  # seconds


class ModuleManager:
    """Central registry and scheduler — the core never imports specific modules.

    Modules register themselves in ModulesConfig.ready().
    The core only talks to this manager.
    """

    def __init__(self):
        self._modules: dict[str, BaseModule] = {}
        self._scheduler_task: asyncio.Task | None = None
        self._tick_interval: int = DEFAULT_TICK_INTERVAL

    def register(self, module: BaseModule):
        if module.name in self._modules:
            raise ValueError(f"Module '{module.name}' is already registered")
        self._modules[module.name] = module
        logger.info("Module registered: %s", module.name)

    def get_module(self, name: str) -> BaseModule | None:
        return self._modules.get(name)

    async def start_all(self, chat_handler: Callable[[str, str], Awaitable]):
        from django.conf import settings

        self._tick_interval = getattr(settings, "CRON_TICK_INTERVAL", DEFAULT_TICK_INTERVAL)

        for module in self._modules.values():
            if hasattr(module, "set_chat_handler"):
                module.set_chat_handler(chat_handler)
            await module.start()

        # Start the cron scheduler after all modules are up
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info("Cron scheduler started (interval=%ds)", self._tick_interval)

    async def stop_all(self):
        # Stop the scheduler first
        if self._scheduler_task and not self._scheduler_task.done():
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
            logger.info("Cron scheduler stopped")

        # Then stop modules in reverse order
        for module in reversed(list(self._modules.values())):
            if module.is_running:
                try:
                    await module.stop()
                except Exception:
                    logger.exception("Error stopping module %s", module.name)

    async def _scheduler_loop(self):
        """Core cron loop: every tick_interval seconds, call on_tick() on
        each running module."""
        while True:
            try:
                await asyncio.sleep(self._tick_interval)
                await self._tick_all()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Scheduler tick error")

    async def _tick_all(self):
        """Iterate over all running modules and call on_tick()."""
        for module in self._modules.values():
            if module.is_running:
                try:
                    await module.on_tick()
                except Exception:
                    logger.exception("Error in on_tick() for module %s", module.name)


module_manager = ModuleManager()
