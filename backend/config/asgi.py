import os
import logging

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django_asgi_app = get_asgi_application()

from communication.routing import websocket_urlpatterns
from memory.manager import memory_manager
from modules.manager import module_manager

logger = logging.getLogger(__name__)


class LifespanWrapper:
    """Wraps a Channels ASGI app with lifespan support for startup/shutdown."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await self._startup()
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await self._shutdown()
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        else:
            await self.app(scope, receive, send)

    async def _startup(self):
        from ai.quota import quota_tracker
        from asgiref.sync import sync_to_async
        from conscience.engine import conscience_engine
        from emotion.engine import emotion_engine

        # Hydrate the quota tracker from DB so counters survive restart.
        try:
            await sync_to_async(quota_tracker.hydrate, thread_sensitive=True)()
            logger.info("AI quota tracker hydrated")
        except Exception:
            logger.warning("Quota hydration failed", exc_info=True)

        await memory_manager.initialize()
        logger.info("Memory system initialized")

        await emotion_engine.initialize()
        logger.info("Emotion engine initialized")

        await conscience_engine.initialize()
        module_manager.set_conscience(conscience_engine.observe)
        logger.info("Conscience initialized and wired to event bus")

        await module_manager.start_all()
        logger.info("All modules started")

        # Communication channels (not plugins) — started here on the
        # same footing as the WebSocket consumer, which is wired via
        # ``communication.routing``.
        from communication.channels import telegram_channel
        try:
            await telegram_channel.start()
        except Exception:
            logger.exception("Telegram channel failed to start")

    async def _shutdown(self):
        from communication.channels import telegram_channel
        from emotion.engine import emotion_engine
        from conscience.engine import conscience_engine

        try:
            await telegram_channel.stop()
        except Exception:
            logger.exception("Telegram channel failed to stop cleanly")

        await conscience_engine.shutdown()
        logger.info("Conscience shut down")

        await emotion_engine.shutdown()
        logger.info("Emotion engine shut down")

        await memory_manager.shutdown()
        logger.info("Memory system shut down")

        await module_manager.stop_all()
        logger.info("VTuber Engine shut down cleanly")


inner_app = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": URLRouter(websocket_urlpatterns),
    }
)

application = LifespanWrapper(inner_app)
