"""Le serveur : le noyau réel (horloge, identifiants, magasin, modèles),
l'adaptateur web par-dessus, un seul processus.

``python -m mika serve --port 8001`` puis, dans ``frontend/`` : ``npm run dev``.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from starlette.applications import Starlette
from starlette.routing import Mount

from mika.adapters.camera import CameraBuffer
from mika.adapters.feeds import HttpFeeds
from mika.adapters.forge import ForgeHost
from mika.adapters.llm.calls import CallLog
from mika.adapters.llm.config import LiveGateway, build_gateway
from mika.adapters.llm.gateway import LLMTrace
from mika.adapters.mail import ImapSmtpMail
from mika.adapters.mcp.relay import PREFIX as RELAY_PREFIX
from mika.adapters.mcp.relay import Relay
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
from mika.app import backup, composition, datadir, reglages
from mika.app.console import FACULTY_LABELS, NAVIGATION, PARAM_FAMILIES
from mika.app.delivery import Router
from mika.app.mindport import KernelPort
from mika.app.paths import PERSONA
from mika.app.settings import SecretBox, Settings
from mika.contracts.self_ import PersonaDoc
from mika.faculties.self import load
from mika.inspector.app import routes
from mika.inspector.mcp import PREFIX as CONSOLE_MCP_PREFIX
from mika.inspector.mcp import console_app
from mika.inspector.ui import InspectorDeps
from mika.kernel.prompt import Budget
from mika.runtime.bootstrap import Kernel

log = logging.getLogger("mika.server")


class ForgeSettingsStore:
    """Le port ``forge_settings`` : ce qu'un opérateur règle pour une app forgée,
    rangé par ``Settings``. Un secret y est **scellé** (``SecretBox``) et rendu en
    clair à l'app seulement (``values`` sert ``api.config``) ; une liste y est
    rangée en lignes. Ce qui n'est plus déclaré par l'app n'est plus rendu."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.host: ForgeHost | None = None

    def _fields(self, app: str) -> dict[str, Any]:
        info = self.host.info(app) if self.host is not None else None
        return {f.path: f for f in info.config_fields} if info is not None else {}

    def values(self, app: str) -> dict[str, Any]:
        fields = self._fields(app)
        out: dict[str, Any] = {}
        for key, value in self.settings.forge_config(app).items():
            f = fields.get(key)
            if f is None:
                continue
            if f.kind == "secret":
                out[key] = self.settings.box.open(str(value)) if value else ""
            elif f.kind == "lines" and isinstance(value, str):
                out[key] = [line for line in value.split("\n") if line]
            else:
                out[key] = value
        return out

    async def save(self, app: str, values: Mapping[str, Any]) -> None:
        fields = self._fields(app)
        clean: dict[str, Any] = {}
        for key, value in values.items():
            f = fields.get(key)
            if f is None or value is None:
                continue
            if f.kind == "secret":
                if value:
                    clean[key] = self.settings.box.seal(str(value))
            elif f.kind == "lines":
                clean[key] = "\n".join(str(v) for v in value) if isinstance(value, list | tuple) else str(value)
            else:
                clean[key] = value
        await self.settings.save_forge_config(app, clean)


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
    #: le relais MCP des fournisseurs Claude Code (monté sous /mcp/relais, local seulement)
    relay: Relay = field(default_factory=Relay)
    #: l'adresse locale où le serveur l'écoute (fixée par ``serve``) ; vide : pas joignable
    relay_base: str = ""
    data: Path | None = None

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

    def inputs(self) -> dict[str, dict[str, Any]]:
        """Ce que les réglages d'exploitation fournissent aux paramètres des facultés
        (jamais des surcharges : une reconfiguration ne les efface pas)."""
        out: dict[str, dict[str, Any]] = {"kernel": {"tz": self.persona().timezone}}
        owners = self.settings.telegram()["owners"]
        if owners:
            out["identity"] = {"owners": tuple(handle_of(o) for o in owners)}
        accounts = self.settings.email().accounts
        drafting = tuple(sorted(k for k, a in accounts.items() if a.autodraft and a.enabled))
        if drafting:
            out["email"] = {"autodraft": drafting,
                            "autodraft_skip": tuple(sorted({s for k in drafting for s in accounts[k].autodraft_skip}))}
        return out

    async def reconfigure(self) -> list[str]:
        """Rejournalise la persona et les paramètres qui en dérivent (sans redémarrer)."""
        try:
            await composition.configure(self.kernel, self.persona(), self.settings.overrides(), self.inputs())
        except (ValueError, TypeError) as exc:
            return [str(exc)]
        return []

    async def start_telegram(self) -> None:
        """Le robot Telegram, s'il est configuré (``mika telegram token …``)."""
        cfg = self.settings.telegram()
        for problem in await self.reconfigure():  # les propriétaires sont une entrée de l'identité
            log.warning("Telegram : %s", problem)
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
            self.gateway.set(build_gateway(cfg, self.kernel.deps.clock, on_trace=self.trace, relay=self.relay,
                                           relay_base=lambda: self.relay_base,
                                           work_dir=self.data / "claude-code" if self.data else None))
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
    forge_settings = ForgeSettingsStore(settings)
    forge = forge_settings.host = ForgeHost(data / "forge", config=forge_settings.values)
    world = {"mail": ImapSmtpMail(settings.email, data / "mail.db"),
             "feeds": HttpFeeds(settings.feeds, data / "feeds.db"),
             "workshop": BwrapWorkshop(data / "ateliers"), "camera": camera,
             "forge": forge, "forge_settings": forge_settings}
    kernel = Kernel(composition.deps(store=store, clock=clock, ids=RandomIdGen(), gateway=gateway,
                                     ports={"delivery": router, "vectors": vectors, **world}, **deps))
    port = KernelPort(kernel)
    hub.port = port
    live = Live(kernel, hub, port, Accounts(store), settings, gateway, router, fixed, calls=CallLog(store),
                persona_file=persona, data=data)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        datadir.hold(data)  # un seul Mika par dossier : un second processus est refusé, pas mêlé au journal
        await kernel.start(configure=lambda k: composition.configure(k, live.persona(), settings.overrides(),
                                                                     live.inputs()))
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
            await gateway.aclose()
            await live.calls.flush()
            await kernel.stop()
            datadir.release(data)

    async def restart_telegram() -> None:
        await live.stop_telegram()
        await live.start_telegram()

    inspector = routes(InspectorDeps(kernel, live.accounts, live.settings, live.reload_llm, gateway.traces,
                                     port=port, calls=live.calls, reconfigure=live.reconfigure,
                                     restart_telegram=restart_telegram, after_decision=hub.refresh_panels,
                                     reports=reports, navigation=NAVIGATION,
                                     sections=reglages.sections(live), settings_tabs=reglages.TABS,
                                     parameters=reglages.parameters(live), param_families=PARAM_FAMILIES,
                                     faculty_labels=FACULTY_LABELS, backups=lambda: backup.overview(data)),
                       cookie_secure=(web.cookie_secure if web else False))
    preprocess = LocalPreprocessor(gateway, transcribe=whisper(settings.stt))
    live.preprocess = preprocess
    relay = Mount(RELAY_PREFIX, app=live.relay.app)
    console_mcp = Mount(CONSOLE_MCP_PREFIX, app=console_app(kernel, settings.console_mcp_token))
    return create_app(port, live.accounts, hub, web, lifespan=lifespan,
                      extra_routes=[*inspector, relay, console_mcp],
                      preprocess=preprocess, camera=camera, sensor_token=settings.sensors_token), live


def relay_base(host: str, port: int) -> str:
    """Où la CLI de Claude Code joint le relais : la boucle locale (le relais
    ne sert qu'elle). Un serveur qui n'écoute que sur une autre adresse ne peut
    pas servir de relais : vide, et les appels Claude Code échouent en le disant."""
    if host in ("", "127.0.0.1", "0.0.0.0", "localhost"):
        return f"http://127.0.0.1:{port}"
    if host in ("::1", "::"):
        return f"http://[::1]:{port}"
    return ""


def serve(*, host: str = "127.0.0.1", port: int = 8001, data: Path = Path("data/v2"),
          reports: Path | None = None) -> None:
    import uvicorn  # noqa: PLC0415 — seul le serveur réel en a besoin

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
    datadir.hold(data)  # avant d'ouvrir quoi que ce soit : refusé tout de suite, en le disant
    app, live = build(data, reports=reports)
    live.relay_base = relay_base(host, port)
    # un arrêt (SIGTERM) laisse 20 s aux connexions, puis le cycle de vie arrête le noyau
    uvicorn.run(app, host=host, port=port, ws_max_size=protocol.MAX_FRAME_BYTES, log_level="info",
                timeout_graceful_shutdown=20)
