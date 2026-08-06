import asyncio
import os
import logging

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import OriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django_asgi_app = get_asgi_application()

from communication.routing import websocket_urlpatterns
from memory.manager import memory_manager
from modules.manager import module_manager

logger = logging.getLogger(__name__)

# How long shutdown waits for an in-flight turn to finish writing its reply.
# Above a normal turn, below any patience a restart has: past this the turn
# is cancelled and picked up again on the next boot via ``awaiting_reply``.
DRAIN_TIMEOUT_S = 10


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
        from emotion.sync import emotion_sync
        from memory.sleep import sleep_cycle
        from projects.runner import project_runner

        # Hydrate the quota tracker from DB so counters survive restart.
        try:
            await sync_to_async(quota_tracker.hydrate, thread_sensitive=True)()
            logger.info("AI quota tracker hydrated")
        except Exception:
            logger.warning("Quota hydration failed", exc_info=True)

        await memory_manager.initialize()
        logger.info("Memory system initialized")

        # The pool that actually answers people. Started before anything can
        # submit to it, and before the sockets are served: a turn queued by a
        # connection arriving during startup must find a worker, not a
        # lazily-created one racing the lifespan.
        from pipeline.turns import turn_queue

        await turn_queue.start()

        await emotion_engine.initialize()
        logger.info("Emotion engine initialized")

        # Les handles durables (Telegram & co) vivent en base, la presence
        # vit en RAM : sans cette remontee, tout contact qui n'avait pas
        # ecrit depuis le boot etait declare joignable par le routage par
        # concernement et introuvable au moment de livrer. Avant la
        # conscience, dont le premier cycle de decision peut deja choisir un
        # destinataire.
        from identity.resolver import identity_resolver

        try:
            restored = await identity_resolver.restore_module_presence()
            logger.info("Presence restored for %d durable handle(s)", restored)
        except Exception:
            logger.exception("Could not restore durable module presence")

        await conscience_engine.initialize()
        module_manager.set_conscience(conscience_engine.observe)
        logger.info("Conscience initialized and wired to event bus")

        await module_manager.start_all()
        logger.info("All modules started")

        # Dedicated background loops (decoupled from the consolidator since
        # 2026-04) — one ticks sleep_cycle.run_if_due(), the other ticks
        # project_runner.tick(). Each has its own configurable cadence.
        await sleep_cycle.start()
        await project_runner.start()

        # The oscillators move all day; the frontend only ever heard about
        # them when Mika spoke. This loop pushes the current emotion to each
        # connected client when it actually changes.
        await emotion_sync.start()

        # Communication channels (not plugins) — started here on the
        # same footing as the WebSocket consumer, which is wired via
        # ``communication.routing``.
        from communication.channels import telegram_channel
        try:
            await telegram_channel.start()
        except Exception:
            logger.exception("Telegram channel failed to start")

        # Les questions ecrites mais jamais repondues — le processus est mort
        # en plein tour. Remises en file *en dernier*, deliberement : ``submit``
        # ne bloque pas, donc un tour rejoue plus tot courait contre la fin du
        # demarrage. Sur un canal push comme Telegram, sa reponse partait alors
        # vers une presence pas encore remontee ou vers un canal que
        # ``communication.delivery.get_channel`` ne connait qu'apres
        # ``telegram_channel.start()`` — abandonnee pour de bon, Telegram
        # n'ayant aucun rattrapage par curseur. On reste malgre tout avant
        # l'ouverture au public : rien n'est servi tant que ``_startup`` n'a
        # pas rendu la main.
        from pipeline.turns import resume_interrupted_turns

        try:
            await resume_interrupted_turns()
        except Exception:
            logger.exception("Could not resume interrupted turns")

    async def _shutdown(self):
        from communication.channels import telegram_channel
        from emotion.engine import emotion_engine
        from emotion.sync import emotion_sync
        from conscience.engine import conscience_engine
        from memory.sleep import sleep_cycle
        from projects.runner import project_runner

        try:
            await telegram_channel.stop()
        except Exception:
            logger.exception("Telegram channel failed to stop cleanly")

        # Stop accepting turns, but let the in-flight one finish writing: a
        # reply cut off between the AI call and its persistence would come
        # back as an "interrupted turn" and be replayed on the next boot.
        from pipeline.turns import turn_queue

        try:
            await asyncio.wait_for(turn_queue.drain(), timeout=DRAIN_TIMEOUT_S)
        except (asyncio.TimeoutError, Exception):
            logger.warning("Turn queue did not drain in time — cancelling")
        try:
            await turn_queue.stop()
        except Exception:
            logger.exception("Turn queue failed to stop cleanly")

        # Stop dedicated loops first — they only call into sleep_cycle /
        # project_runner state and don't own DB connections, so they shut
        # down quickly and cannot starve the managers below.
        try:
            await emotion_sync.stop()
        except Exception:
            logger.exception("Emotion sync loop failed to stop cleanly")

        try:
            await project_runner.stop()
        except Exception:
            logger.exception("Project runner loop failed to stop cleanly")

        try:
            await sleep_cycle.stop()
        except Exception:
            logger.exception("Sleep cycle loop failed to stop cleanly")

        await conscience_engine.shutdown()
        logger.info("Conscience shut down")

        await emotion_engine.shutdown()
        logger.info("Emotion engine shut down")

        await memory_manager.shutdown()
        logger.info("Memory system shut down")

        await module_manager.stop_all()
        logger.info("VTuber Engine shut down cleanly")


def _websocket_application():
    """The WebSocket stack: origin check → session auth → routing.

    **AuthMiddlewareStack** resolves the session cookie into ``scope["user"]``.
    Without it the key is simply absent, so every consumer sees an anonymous
    connection — and with CONSUMER_REQUIRE_AUTH on (the default), that means
    *every* connection is refused with 4401, valid session or not.

    **OriginValidator** is the other half, and it only became necessary once
    the socket started authenticating by cookie. CORS does not apply to
    WebSockets: any page the user visits can open ``ws://.../ws``, and the
    browser will attach their session cookie. Without an origin check that is
    cross-site WebSocket hijacking — a third-party page holding a live,
    authenticated conversation with Mika, reading back memories and profiles
    as her owner. The allow-list is the same one CORS uses, because "may talk
    to the backend" is one decision, not two.

    A missing ``Origin`` header is rejected (unless the list is ``*``): real
    browsers always send one on a WebSocket handshake.
    """
    from django.conf import settings

    if getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False):
        allowed = ["*"]
    else:
        allowed = list(getattr(settings, "CORS_ALLOWED_ORIGINS", []))

    return OriginValidator(
        AuthMiddlewareStack(URLRouter(websocket_urlpatterns)), allowed,
    )


inner_app = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": _websocket_application(),
    }
)

application = LifespanWrapper(inner_app)
