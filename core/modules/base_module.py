from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)


class BaseModule(ABC):
    """Base class for all VTuber engine modules."""

    def __init__(self, name: str):
        self.name = name
        self._running = False
        self.logger = logging.getLogger(f"module.{name}")

    @abstractmethod
    async def on_start(self):
        """Called when the module starts."""
        ...

    @abstractmethod
    async def on_stop(self):
        """Called when the module stops."""
        ...

    @abstractmethod
    async def on_message(self, message: str, source: str) -> str | None:
        """Handle an incoming message. Return response or None."""
        ...

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
