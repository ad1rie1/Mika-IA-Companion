"""Le serveur : le noyau réel (horloge, identifiants, magasin, modèles),
l'adaptateur web par-dessus, un seul processus.

``python -m mika serve --port 8001`` puis, dans ``frontend/`` : ``npm run dev``.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from starlette.applications import Starlette

from mika.adapters.camera import CameraBuffer
from mika.adapters.feeds import HttpFeeds
from mika.adapters.forge import ForgeHost
from mika.adapters.llm.calls import CallLog
from mika.adapters.llm.config import LiveGateway, build_gateway
from mika.adapters.llm.gateway import LLMTrace
from mika.adapters.mail import ImapSmtpMail
from mika.adapters.preprocess import LocalPreprocessor, whisper
from mika.adapters.store_sqlite import SqliteStore
from mika.adapters.system import RandomIdGen, RealClock
from mika.adapters.telegram import TelegramChannel, TelegramConfig, handle_of
from mika.adapters.telegram.ptb import Poller
from mika.adapters.vectors import SentenceEmbedder, SqliteVectorIndex
from mika.adapters.web import protocol
from mika.adapters.web.accounts import Accounts
from mika.adapters.web.app import WebConfig, create_app
from mika.adapters.web.hub import Hub
from mika.adapters.workshop import BwrapWorkshop
from mika.app import composition
from mika.app.delivery import Router
from mika.app.mindport import KernelPort
from mika.app.paths import PERSONA
from mika.app.settings import SecretBox, Settings
from mika.contracts.self_ import PersonaDoc
from mika.faculties.identity import IdentityParams
from mika.faculties.self import load
from mika.inspector.app import routes
from mika.inspector.ui import InspectorDeps
from mika.kernel.events import Origin
from mika.kernel.prompt import Budget
from mika.plugins.forge import SWITCHED
from mika.runtime.bootstrap import Kernel

log = logging.getLogger("mika.server")


@dataclass(slots=True)
class Live:
    kernel: Kernel
    hub: Hub
    port: KernelPort
    accounts: Accounts
    settings: Settings
    gateway: LiveGateway
    router: Router
    #: une passerelle fournie de l'extérieur (tests, simulateur) n'est pas rechargée
    fixed: bool = False
    telegram: Any = None
    preprocess: Any = None
    calls: CallLog | None = None
    persona_file: Path = PERSONA

    def trace(self, tr: LLMTrace) -> None:
        self.gateway.traces.append(tr)
        if self.calls is not None:
            self.calls.record(tr)

    def persona(self) -> PersonaDoc:
        """La persona rédigée dans l'inspecteur si elle existe et se lit ; sinon le fichier."""
        text = self.settings.persona_yaml()
        if text:
            try:
                return PersonaDoc.model_validate(yaml.safe_load(text) or {})
            except (ValueError, yaml.YAMLError) as exc:
                log.warning("persona de l'inspecteur illisible, le fichier fait foi : %s", exc)
        return load(self.persona_file)

    async def reconfigure(self) -> list[str]:
        """Rejournalise la persona et les paramètres qui en dérivent (sans redémarrer)."""
        try:
            await composition.configure(self.kernel, self.persona(), self.settings.overrides())
        except (ValueError, TypeError) as exc:
            return [str(exc)]
        return []

    async def switch_app(self, app: str, state: str) -> None:
        """Une décision d'opérateur sur une app forgée (``promoted``, ``demoted``…)."""
        await self.kernel.mind.append([SWITCHED.draft(app=app, state=state)], emitter="forge",
                                      correlation=f"opérateur:forge:{app}", origin=Origin.EXTERNAL)

    async def start_telegram(self) -> None:
        """Le robot Telegram, s'il est configuré (``mika telegram token …``)."""
        cfg = self.settings.telegram()
        await self.kernel.set_params("identity", IdentityParams(owners=tuple(handle_of(o) for o in cfg["owners"])))
        if not cfg["token"]:
            return
        config = TelegramConfig(allowed_chats=frozenset(cfg["allowed_chats"]))
        poller = Poller(cfg["token"], lambda bot: TelegramChannel(self.port, bot, config, preprocess=self.preprocess))
        await poller.start()
        self.telegram = poller
        self.router.telegram = poller.channel
        log.info("Telegram : relève démarrée (%s)", "liste blanche" if config.allowed_chats else "ouvert à tous")

    async def stop_telegram(self) -> None:
        if self.telegram is not None:
            self.router.telegram = None
            await self.telegram.stop()
            self.telegram = None

    async def reload_llm(self) -> list[str]:
        if self.fixed:
            return []
        cfg = self.settings.llm()
        problems = cfg.problems()
        if cfg.backends and not problems:
            self.gateway.set(build_gateway(cfg, self.kernel.deps.clock, on_trace=self.trace))
            self.kernel.runner.budget = Budget(max_tokens=cfg.context_tokens)
        else:
            self.gateway.set(None)
        return problems


def build(data: Path, *, persona: Path = PERSONA, web: WebConfig | None = None,
          gateway: LiveGateway | None = None, embedder: Any = None, reports: Path | None = None,
          **deps: Any) -> tuple[Starlette, Live]:
    """L'application et ce qu'elle fait vivre. Tout est construit ici ; le
    cycle de vie ouvre, démarre et arrête."""
    data.mkdir(parents=True, exist_ok=True)
    store = SqliteStore(data / "mind.db", data / "views.db", threaded=True)
    clock = RealClock()
    fixed = gateway is not None
    gateway = gateway or LiveGateway()
    hub = Hub(port=None)  # type: ignore[arg-type] — relié au port juste après
    router = Router(hub)
    vectors = SqliteVectorIndex(store, embedder or SentenceEmbedder())
    camera = CameraBuffer(clock.now)
    settings = Settings(store, SecretBox.for_data(data))
    world = {"mail": ImapSmtpMail(settings.email, data / "mail.db"),
             "feeds": HttpFeeds(settings.feeds, data / "feeds.db"),
             "workshop": BwrapWorkshop(data / "ateliers"), "camera": camera,
             "forge": ForgeHost(data / "forge", config=settings.forge_config)}
    kernel = Kernel(composition.deps(store=store, clock=clock, ids=RandomIdGen(), gateway=gateway,
                                     ports={"delivery": router, "vectors": vectors, **world}, **deps))
    port = KernelPort(kernel)
    hub.port = port
    live = Live(kernel, hub, port, Accounts(store), settings, gateway, router, fixed, calls=CallLog(store),
                persona_file=persona)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        await kernel.start(configure=lambda k: composition.configure(k, live.persona(), settings.overrides()))
        await live.settings.open()
        await live.accounts.open()
        await live.calls.open()
        problems = await live.reload_llm()
        if not gateway.configured and not problems:
            log.warning("aucun modèle configuré : voir `python -m mika llm --help`")
        for problem in problems:
            log.warning("configuration des modèles : %s", problem)
        hub.start()
        try:
            await live.start_telegram()
        except Exception as exc:  # noqa: BLE001 — un robot mal configuré n'empêche pas le reste de vivre
            log.warning("Telegram : démarrage impossible (%r)", exc)
        try:
            yield
        finally:
            await live.stop_telegram()
            await hub.stop()
            await live.calls.flush()
            await kernel.stop()

    async def restart_telegram() -> None:
        await live.stop_telegram()
        await live.start_telegram()

    inspector = routes(InspectorDeps(kernel, live.accounts, live.settings, live.reload_llm, gateway.traces,
                                     port=port, calls=live.calls, reconfigure=live.reconfigure,
                                     restart_telegram=restart_telegram, after_decision=hub.refresh_panels,
                                     reports=reports, forge_switch=live.switch_app),
                       cookie_secure=(web.cookie_secure if web else False))
    preprocess = LocalPreprocessor(gateway, transcribe=whisper(settings.stt))
    live.preprocess = preprocess
    return create_app(port, live.accounts, hub, web, lifespan=lifespan, extra_routes=inspector,
                      preprocess=preprocess, camera=camera, sensor_token=settings.sensors_token), live


def serve(*, host: str = "127.0.0.1", port: int = 8001, data: Path = Path("data/v2"),
          reports: Path | None = None) -> None:
    import uvicorn  # noqa: PLC0415 — seul le serveur réel en a besoin

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
    app, _ = build(data, reports=reports)
    # un arrêt (SIGTERM) laisse 20 s aux connexions, puis le cycle de vie arrête le noyau
    uvicorn.run(app, host=host, port=port, ws_max_size=protocol.MAX_FRAME_BYTES, log_level="info",
                timeout_graceful_shutdown=20)
