"""Observer pattern for external data sources.

Modules (email, telegram) use the event bus directly.
External sources (RSS, news APIs, YouTube) use observers
that are polled by the ConscienceEngine.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from modules.types import ModuleEvent

logger = logging.getLogger(__name__)


class BaseObserver(ABC):
    """Abstract observer for external data sources.

    Subclass this to add new data sources (RSS, news, YouTube, etc.).
    The ConscienceEngine polls all registered observers in its decision loop.
    """

    name: str
    poll_interval: int = 300  # seconds between polls

    def __init__(self, name: str, poll_interval: int = 300):
        self.name = name
        self.poll_interval = poll_interval
        self.logger = logging.getLogger(f"observer.{name}")

    @abstractmethod
    async def poll(self) -> list[ModuleEvent]:
        """Fetch new data and return as module events.

        Called periodically by the ConscienceEngine. Should return
        only NEW data since last poll (dedup internally).
        """
        ...

    async def start(self) -> None:
        """Initialize the observer (open connections, etc.). Default: no-op."""
        pass

    async def stop(self) -> None:
        """Clean up the observer. Default: no-op."""
        pass


class ObserverRegistry:
    """Manages external observers. Polled by ConscienceEngine."""

    def __init__(self):
        self._observers: dict[str, BaseObserver] = {}
        self._last_poll: dict[str, float] = {}

    def register(self, observer: BaseObserver) -> None:
        self._observers[observer.name] = observer
        self._last_poll[observer.name] = 0.0
        logger.info("Observer registered: %s (interval=%ds)", observer.name, observer.poll_interval)

    async def start_all(self) -> None:
        for obs in self._observers.values():
            try:
                await obs.start()
                logger.info("Observer started: %s", obs.name)
            except Exception:
                logger.exception("Failed to start observer: %s", obs.name)

    async def stop_all(self) -> None:
        for obs in reversed(list(self._observers.values())):
            try:
                await obs.stop()
            except Exception:
                logger.exception("Failed to stop observer: %s", obs.name)

    async def poll_due(self, now: float) -> list[ModuleEvent]:
        """Poll all observers that are due. Returns aggregated events."""
        events: list[ModuleEvent] = []

        for name, obs in self._observers.items():
            last = self._last_poll.get(name, 0.0)
            if now - last < obs.poll_interval:
                continue

            self._last_poll[name] = now
            try:
                new_events = await obs.poll()
                events.extend(new_events)
                if new_events:
                    logger.info(
                        "Observer %s polled: %d new events", name, len(new_events)
                    )
            except Exception:
                logger.exception("Observer %s poll failed", name)

        return events
