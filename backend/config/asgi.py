import os
import logging

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django_asgi_app = get_asgi_application()

from chat.routing import websocket_urlpatterns
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
        from chat.consumers import handle_chat
        from emotion.engine import emotion_engine
        from conscience.engine import conscience_engine

        await memory_manager.initialize()
        logger.info("Memory system initialized")

        await emotion_engine.initialize()
        logger.info("Emotion engine initialized")

        await conscience_engine.initialize()
        module_manager.set_conscience(conscience_engine.observe)
        logger.info("Conscience initialized and wired to event bus")

        await module_manager.start_all(handle_chat)
        logger.info("All modules started")

    async def _shutdown(self):
        from emotion.engine import emotion_engine
        from conscience.engine import conscience_engine

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
