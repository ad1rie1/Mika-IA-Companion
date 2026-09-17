import asyncio
import os
import logging
import signal
import time

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

# Budget de chaque étape de l'arrêt, en secondes (OPS-02). Rien ne bornait
# l'arrêt : uvicorn n'a pas de timeout de lifespan, et `consolidator.stop()`
# attendait un tick entier — N tranches × 120 s d'appels IA — jusqu'à ce que
# le SIGKILL de systemd tombe au pire endroit. Chaque étape passe sous
# `wait_for` ; un dépassement est journalisé ET compté (`arret: <étape> hors
# budget`), jamais propagé — l'étape suivante s'exécute quand même. La somme
# (`BUDGET_ARRET_TOTAL_S`) reste sous le `TimeoutStopSec` de
# `deploy/mika.service`, ce qu'un test vérifie en lisant l'unit.
BUDGETS_ARRET_S: dict[str, float] = {
    "telegram": 3.0,
    "file de tours (drain)": float(DRAIN_TIMEOUT_S),
    "file de tours (stop)": 1.0,
    "conscience": 3.0,
    "modules": 5.0,
    "project runner": 2.0,
    "sleep cycle": 2.0,
    "emotion sync": 1.0,
    "memoire": 12.0,
    "emotion": 3.0,
    "diffusions differees": 2.0,
    "wal checkpoint": 1.0,
}
BUDGET_ARRET_TOTAL_S = sum(BUDGETS_ARRET_S.values())


def _arreter_le_serveur(exc: BaseException) -> None:
    """Crochet d'échec fatal du chargement différé de la mémoire longue.

    Le refus (`MemoryUnavailable`) remontait du lifespan et uvicorn sortait
    en code 3 ; le chargement partant désormais en tâche de fond après
    l'ouverture du port, le refus n'a plus de pile à remonter. On demande
    l'arrêt par le signal qu'uvicorn attend (SIGTERM → arrêt propre, lifespan
    shutdown compris), `/health` répond `failed` entre-temps, et `run.py`
    sort en code 3 en voyant l'état `failed` — la même sémantique qu'avant :
    MEMORY_REQUIRE_VECTOR_STORE=1 refuse, il ne dégrade pas.
    """
    from config.readiness import etat_processus

    etat_processus.echec_fatal = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
    logger.critical("Arrêt du processus demandé : mémoire longue refusée")
    signal.raise_signal(signal.SIGTERM)


async def _etape(nom: str, coro, budget_s: float) -> bool:
    """Une étape de l'arrêt, sous budget. Rend True si elle a abouti.

    Un dépassement annule l'étape (le `wait_for` annule la coroutine) et
    laisse la suivante s'exécuter ; une exception est journalisée. Ni l'un ni
    l'autre ne remonte : l'arrêt doit atteindre la sauvegarde de l'état
    émotionnel et le checkpoint WAL quoi qu'il arrive avant.
    """
    from utils.degradation import degradations

    debut = time.monotonic()
    try:
        await asyncio.wait_for(coro, timeout=budget_s)
        return True
    except asyncio.TimeoutError as exc:
        degradations.record(f"arret: {nom} hors budget", exc)
        logger.warning(
            "Arrêt : étape « %s » hors budget (%.1f s) — étape suivante", nom, budget_s,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        degradations.record(f"arret: {nom}", exc)
        logger.exception("Arrêt : étape « %s » en erreur — étape suivante", nom)
    finally:
        logger.info("Arrêt : « %s » en %.2f s", nom, time.monotonic() - debut)
    return False


def _wal_checkpoint_sync() -> None:
    """`PRAGMA wal_checkpoint(TRUNCATE)` sur la base SQLite, en dernier.

    Sous WAL, les écritures s'accumulent dans `vtuber.db-wal` et ne
    reviennent dans le fichier principal qu'au checkpoint automatique (1000
    pages). Après un arrêt propre, un `.db` seul n'est donc pas la base : la
    sauvegarde par copie de fichier (OPS-10) perdait ce que le WAL tenait.
    TRUNCATE replie tout et vide le journal ; il ne bloque pas — s'il reste
    un lecteur (une connexion d'un thread pas encore fermé), SQLite rend
    `busy=1` et laisse le WAL en place, ce qui est journalisé, pas fatal.
    Toutes les boucles sont arrêtées à ce stade ; les connexions des threads
    exécuteurs sont fermées avant pour ne pas être ce lecteur.
    """
    from django.db import connection, connections

    if connection.vendor != "sqlite":
        return
    connections.close_all()
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        busy, journal, repliees = cursor.fetchone()
    if busy:
        logger.warning(
            "WAL checkpoint incomplet (busy) : %d page(s) sur %d repliée(s)",
            repliees, journal,
        )
    else:
        logger.info("WAL checkpoint : %d page(s) repliée(s), journal tronqué", repliees)
    connections.close_all()


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
        from config.readiness import etat_processus

        etat_processus.passer_a("starting")
        from asgiref.sync import sync_to_async
        from conscience.engine import conscience_engine
        from emotion.engine import emotion_engine
        from emotion.sync import emotion_sync
        from memory.sleep import sleep_cycle
        from projects.runner import project_runner
        from utils.degradation import degradations

        # Hydrate the quota tracker from DB so counters survive restart.
        try:
            await sync_to_async(quota_tracker.hydrate, thread_sensitive=True)()
            logger.info("AI quota tracker hydrated")
        except Exception:
            logger.warning("Quota hydration failed", exc_info=True)

        # Le fil et la compaction sont prêts au retour ; la mémoire longue
        # (ChromaDB + encodeur, plusieurs secondes) se charge en thread
        # APRÈS l'ouverture du port — `/health` dit `starting` d'ici là, et un
        # tour reçu entre-temps se passe de rappel au lieu d'attendre. Un
        # refus (`MemoryUnavailable`) arrête le processus via le crochet.
        await memory_manager.initialize(
            differe=True, sur_echec_fatal=_arreter_le_serveur,
        )
        logger.info("Memory system initialized (mémoire longue en chargement)")

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
        except Exception as exc:
            # Comptee, pas seulement journalisee : quand cette remontee echoue,
            # le routage par concernement continue de declarer joignable tout
            # handle module et la livraison ne trouve plus personne — chaque
            # message proactif de ce run est perdu, et rien d'autre ne le dit.
            logger.exception("Could not restore durable module presence")
            degradations.record("presence: durable handle restore", exc)

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

        etat_processus.passer_a("started")

    async def _shutdown(self):
        """Arrêt supervisé — chaque étape sous budget, dans cet ordre :

        1. Telegram cesse de recevoir.
        2. La file de tours est vidée (borné) puis arrêtée : un tour coupé
           entre l'appel IA et sa persistance revient comme « tour
           interrompu » au prochain démarrage.
        3. Conscience, modules, project runner, sleep cycle, emotion sync
           sont arrêtés — AVANT les passes finales (OPS-04) : un `notify_ai`
           de module ou un acte de la conscience passe hors file
           (`INTERNAL_TRIGGER` → `process_message` direct) et modifiait
           l'état émotionnel *après* sa sauvegarde, donc le perdait.
        4. Passes finales : mémoire (consolidateur borné, checkpoint par
           tranche) puis état émotionnel.
        5. Diffusions différées vidées, puis `wal_checkpoint(TRUNCATE)` en
           tout dernier — quand plus rien n'écrit.

        Un dépassement de budget n'arrête pas la séquence : il est compté
        (`utils.degradation`) et l'étape suivante s'exécute.
        """
        from communication.channels import telegram_channel
        from config.readiness import etat_processus
        from conscience.engine import conscience_engine
        from emotion.engine import emotion_engine
        from emotion.sync import emotion_sync
        from memory.sleep import sleep_cycle
        from pipeline.processor import flush_delayed_broadcasts
        from pipeline.turns import turn_queue
        from projects.runner import project_runner
        from asgiref.sync import sync_to_async

        etat_processus.passer_a("stopping")
        debut = time.monotonic()
        b = BUDGETS_ARRET_S

        await _etape("telegram", telegram_channel.stop(), b["telegram"])
        await _etape("file de tours (drain)", turn_queue.drain(), b["file de tours (drain)"])
        await _etape("file de tours (stop)", turn_queue.stop(), b["file de tours (stop)"])

        await _etape("conscience", conscience_engine.shutdown(), b["conscience"])
        await _etape("modules", module_manager.stop_all(), b["modules"])
        await _etape("project runner", project_runner.stop(), b["project runner"])
        await _etape("sleep cycle", sleep_cycle.stop(), b["sleep cycle"])
        await _etape("emotion sync", emotion_sync.stop(), b["emotion sync"])

        await _etape("memoire", memory_manager.shutdown(), b["memoire"])
        await _etape("emotion", emotion_engine.shutdown(), b["emotion"])

        await _etape(
            "diffusions differees",
            flush_delayed_broadcasts(timeout=b["diffusions differees"] - 0.5),
            b["diffusions differees"],
        )
        await _etape(
            "wal checkpoint",
            sync_to_async(_wal_checkpoint_sync, thread_sensitive=True)(),
            b["wal checkpoint"],
        )

        etat_processus.passer_a("stopped")
        logger.info(
            "VTuber Engine shut down in %.1f s (budget %.0f s)",
            time.monotonic() - debut, BUDGET_ARRET_TOTAL_S,
        )


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
