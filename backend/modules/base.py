import logging
from abc import ABC, abstractmethod


class BaseModule(ABC):
    """Base class for all VTuber engine modules."""

    def __init__(self, name: str):
        self.name = name
        self._running = False
        self.logger = logging.getLogger(f"module.{name}")

    @abstractmethod
    async def on_start(self):
        ...

    @abstractmethod
    async def on_stop(self):
        ...

    @abstractmethod
    async def on_message(self, message: str, source: str) -> str | None:
        ...

    async def on_tick(self):
        """Called by the scheduler on each cron tick (default: every 60s).
        Override in subclasses that need periodic work.
        Default is a no-op."""
        pass

    async def start(self):
        self.logger.info("Starting module: %s", self.name)
        self._running = True
        await self.on_start()

    async def stop(self):
        self.logger.info("Stopping module: %s", self.name)
        self._running = False
        await self.on_stop()

    @property
    def is_running(self) -> bool:
        return self._running
