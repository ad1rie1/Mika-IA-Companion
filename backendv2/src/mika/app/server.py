"""Le serveur : le noyau réel (horloge, identifiants, magasin, modèles),
l'adaptateur web par-dessus, un seul processus.

``python -m mika serve --port 8001`` puis, dans ``frontend/`` : ``npm run dev``.
Derrière un mandataire TLS : ``--origin https://mika.example --cookie-secure
--behind-proxy`` (voir ``deploy/README.md``). Un moteur de jeu se connecte au monde
sur ``/ws/world`` (ADR 0051) avec un jeton de son compte : ``python -m mika token
create <compte> --label "Unity"``.

Les journaux ne portent jamais un secret : le jeton du robot Telegram (dans
l'URL de chaque relève), un jeton passé en paramètre d'URL (un flux), un
``Bearer`` sont masqués ; ``httpx``/``httpcore`` ne parlent qu'en avertissement.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import shutil
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Mount, Route

from mika.adapters.camera import CameraBuffer
from mika.adapters.feeds import HttpFeeds
from mika.adapters.forge import ForgeHost
from mika.adapters.llm.calls import CallLog
from mika.adapters.llm.claude_code import runtime_dir
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
from mika.adapters.web.app import DEV_ORIGINS, WebConfig, create_app
from mika.adapters.web.hub import Hub
from mika.adapters.workshop import BwrapWorkshop
from mika.adapters.world.server import WorldHub
from mika.app import backup, composition, datadir, reglages
from mika.app import persona as persona_file
from mika.app.console import FACULTY_LABELS, LABELS, NAVIGATION, PARAM_FAMILIES
from mika.app.delivery import Router
from mika.app.mindport import KernelPort
from mika.app.paths import PERSONA
from mika.app.settings import SecretBox, Settings, same_pairing_code
from mika.contracts import identity as identity_c
from mika.contracts.self_ import PersonaDoc
from mika.inspector.app import routes
from mika.inspector.mcp import PREFIX as CONSOLE_MCP_PREFIX
from mika.inspector.mcp import console_app
from mika.inspector.ui import PREFIX as CONSOLE_PREFIX
from mika.inspector.ui import InspectorDeps
from mika.kernel.clock import US
from mika.kernel.events import Origin
from mika.kernel.prompt import Budget
from mika.runtime import operations
from mika.runtime.bootstrap import Kernel
from mika.vocab.people import clean_display_name

log = logging.getLogger("mika.server")

#: la relance du robot Telegram après un démarrage raté : délai initial, plafond (secondes)
TELEGRAM_RETRY_MIN_S = 5.0
TELEGRAM_RETRY_MAX_S = 600.0
#: l'état du robot, pour ``/health`` (des états, jamais un contenu)
_TELEGRAM_HEALTH = {"running": "ok", "starting": "degraded", "retrying": "degraded", "closed": "degraded",
                    "pairing": "degraded", "invalid": "ko"}
_TELEGRAM_FR = {"running": "en marche", "starting": "démarrage…", "retrying": "relance en cours",
                "closed": "fermé : personne ne peut lui écrire",
                "pairing": "en attente d'appairage : personne ne peut encore lui écrire",
                "invalid": "jeton refusé", "off": "arrêté"}
#: un code d'appairage Telegram vaut tant (secondes), et une seule fois
PAIRING_TTL_S = 24 * 3600

#: ce qu'un journal ne doit jamais montrer
_SECRETS = (
    (re.compile(r"(/bot)\d+:[A-Za-z0-9_-]+"), r"\1<jeton>"),
    (re.compile(r"([?&](?:token|key|api[_-]?key|access_token|secret|password|passwd|auth|sig|signature)=)"
                r"[^&\s\"'#]+", re.IGNORECASE), r"\1…"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE), r"\1…"),
)


def redact(text: str) -> str:
    """Le texte d'un journal, secrets masqués."""
    for pattern, replacement in _SECRETS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    """Masque les secrets de chaque enregistrement (posé sur les gestionnaires : tous
    les journaux y passent, ceux des bibliothèques compris)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except (TypeError, ValueError):
            return True
        clean = redact(message)
        if clean != message:
            record.msg, record.args = clean, None
        return True


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
    for name in ("httpx", "httpcore"):  # chaque requête, URL comprise (le jeton du robot y est)
        logging.getLogger(name).setLevel(logging.WARNING)
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())


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
    #: l'adresse de la console telle que le journal de démarrage la donne (fixée par ``serve``)
    console_url: str = ""
    #: le fichier de persona ne se lit pas (en mots : le fichier, la ligne, la cause) ; vide : il se lit
    persona_problem: str = ""
    _persona_said: str = ""
    data: Path | None = None
    #: fabrique du robot (un faux en test) : ``(jeton, fabrique du canal) -> Poller``
    make_poller: Callable[..., Any] = Poller
    #: les clients du monde (``/ws/world``, ADR 0051) : moteurs de jeu et écrans
    world: WorldHub | None = None
    #: off | starting | running | retrying | closed | invalid
    telegram_status: str = "off"
    telegram_attempts: int = 0
    telegram_error: str = ""
    _telegram_task: asyncio.Task[None] | None = None

    def telegram_state(self) -> str:
        """L'état du robot, en mots (la console)."""
        text = _TELEGRAM_FR.get(self.telegram_status, self.telegram_status)
        if self.telegram_status == "retrying":
            text += f" ({self.telegram_attempts} essai(s), dernière erreur : {self.telegram_error})"
        return text

    def channel_health(self) -> dict[str, str]:
        """Ce que ``/health`` dit des canaux : un état par canal configuré."""
        state = _TELEGRAM_HEALTH.get(self.telegram_status)
        return {"telegram": state} if state else {}

    def trace(self, tr: LLMTrace) -> None:
        self.gateway.traces.append(tr)
        if self.calls is not None:
            self.calls.record(tr)

    def persona(self) -> PersonaDoc:
        """La persona rédigée dans l'inspecteur si elle existe et se lit ; sinon le fichier ; un fichier qui ne
        se lit pas (dit en français : la ligne, la cause) laisse la place à la dernière persona gardée au
        journal. Sans aucune : ``PersonaUnavailable``."""
        text = self.settings.persona_yaml()
        if text:
            try:
                return PersonaDoc.model_validate(yaml.safe_load(text) or {})
            except (ValueError, yaml.YAMLError) as exc:
                self._persona_note(f"la persona rédigée dans la console ne se lit pas ({str(exc)[:200]}) : le "
                                   "fichier fait foi")
        try:
            doc = persona_file.read(self.persona_file)
        except persona_file.PersonaInvalid as exc:
            state = self.kernel.mind.root.slices.get("self") if self.kernel is not None else None
            if state is None or not getattr(state, "revisions", 0):
                self._persona_note(exc.problem)
                raise persona_file.PersonaUnavailable(exc.problem) from None
            self.persona_problem = exc.problem
            self._persona_note(f"{exc.problem} — elle vit sur sa dernière persona gardée au journal")
            return state.persona
        self.persona_problem = ""
        return doc

    def _persona_note(self, text: str) -> None:
        """Dit au journal ce qui ne va pas avec sa persona — une fois par problème (on la relit souvent)."""
        if text != self._persona_said:
            self._persona_said = text
            log.warning("persona : %s", text)

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
        """Le robot Telegram, s'il est configuré (``mika telegram token …``). Fermé par
        défaut : sans liste blanche, ni propriétaire, ni ouverture explicite, personne
        ne peut lui écrire — la relève tourne alors **en mode appairage** : un code à
        usage unique (montré dans la console, page Telegram), envoyé au robot en privé
        (``/start <code>``), fait de son auteur une propriétaire. Un démarrage raté
        (réseau coupé au lancement) est relancé avec un délai croissant ; ``/health`` le dit."""
        await self.stop_telegram()
        cfg = self.settings.telegram()
        for problem in await self.reconfigure():  # les propriétaires sont une entrée de l'identité
            log.warning("Telegram : %s", problem)
        if not cfg["token"]:
            self.telegram_status = "off"
            return
        config = TelegramConfig(allowed_chats=frozenset(cfg["allowed_chats"]), owners=frozenset(cfg["owners"]),
                                open_to_all=cfg["open"], name=self.persona().name or "Mika")
        if config.closed:
            await self.telegram_pairing_code()  # un code valide, neuf s'il n'y en a pas
            log.warning("Telegram : ni liste blanche, ni propriétaire, ni ouverture à tous — personne ne peut lui "
                        "écrire. La relève tourne en mode appairage : le code est sur la page Telegram de la "
                        "console, à envoyer au robot en privé (/start <code>)")
        self.telegram_attempts, self.telegram_error, self.telegram_status = 0, "", "starting"
        self._telegram_task = asyncio.create_task(self._run_telegram(cfg["token"], config), name="telegram")

    def _now_s(self) -> int:
        return self.kernel.mind.clock.now() // US

    async def telegram_pairing_code(self, *, fresh: bool = False) -> tuple[str, int]:
        """Le code d'appairage en cours et son échéance (secondes) ; un neuf s'il n'y en a pas, s'il a expiré, ou
        si on le demande (l'ancien ne vaut plus)."""
        got = self.settings.telegram_pairing()
        if got is not None and not fresh and got[1] > self._now_s():
            return got
        code = await self.settings.new_telegram_pairing(self._now_s(), PAIRING_TTL_S)
        return code, self._now_s() + PAIRING_TTL_S

    async def pair_telegram(self, user_id: int, code: str, name: str) -> str:
        """``/start <code>`` en privé : le bon code, encore valable, fait de ce compte une propriétaire — comme
        si un opérateur l'avait ajouté (réglage enregistré, identité reconfigurée, opération journalisée). Le
        code sert une fois ; il n'entre jamais au journal."""
        expected = self.settings.telegram_pairing()
        if expected is None:
            return "none"
        if not same_pairing_code(code, expected[0]):
            log.warning("Telegram : appairage refusé (mauvais code) pour %s", handle_of(user_id))
            return "wrong"
        if expected[1] <= self._now_s():
            return "expired"
        owners = self.settings.telegram()["owners"]
        await self.settings.save_telegram(owners=[*owners, user_id])
        await self.settings.clear_telegram_pairing()
        await operations.audit(self.kernel, "console.telegram.appairage", by=handle_of(user_id),
                               subject_kind="handle", subject=handle_of(user_id))
        for problem in await self.reconfigure():  # sa conversation privée : celle d'une propriétaire
            log.warning("Telegram : %s", problem)
        if self.telegram_status == "pairing":
            self.telegram_status = "running"
        log.info("Telegram : %s est désormais propriétaire (appairage)", handle_of(user_id))
        return "paired"

    async def _run_telegram(self, token: str, config: TelegramConfig) -> None:
        delay = TELEGRAM_RETRY_MIN_S
        while True:
            self.telegram_status = "starting"
            self.telegram_attempts += 1
            poller = None
            try:
                poller = self.make_poller(token, lambda bot: TelegramChannel(self.port, bot, config,
                                                                             preprocess=self.preprocess,
                                                                             pair=self.pair_telegram))
                await poller.start()
            except asyncio.CancelledError:
                if poller is not None:
                    with contextlib.suppress(Exception):
                        await poller.stop()
                raise
            except Exception as exc:  # noqa: BLE001 — un robot qui ne démarre pas n'empêche pas le reste de vivre
                if poller is not None:
                    with contextlib.suppress(Exception):
                        await poller.stop()
                self.telegram_error = type(exc).__name__
                if self.telegram_error in ("InvalidToken", "Unauthorized"):
                    self.telegram_status = "invalid"
                    log.warning("Telegram : jeton refusé, relève abandonnée (mika telegram token …)")
                    return
                self.telegram_status = "retrying"
                log.warning("Telegram : démarrage impossible (%s), nouvel essai dans %.0f s", self.telegram_error,
                            delay)
                await asyncio.sleep(delay)
                delay = min(TELEGRAM_RETRY_MAX_S, delay * 2)
                continue
            self.telegram = poller
            self.router.telegram = poller.channel
            self.telegram_status = "pairing" if config.closed else "running"
            access = "en attente d'appairage" if config.closed else "ouvert à tous" if config.open_to_all else \
                "liste blanche" if config.allowed_chats else "propriétaires"
            log.info("Telegram : relève démarrée (%s)", access)
            return

    async def stop_telegram(self) -> None:
        task, self._telegram_task = self._telegram_task, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self.telegram is not None:
            self.router.telegram = None
            await self.telegram.stop()
            self.telegram = None
        self.telegram_status = "off"

    async def reload_llm(self) -> list[str]:
        if self.data is not None and (self.data / "claude-code").is_dir():
            # l'ancien emplacement des dossiers d'appel, dans le dossier de données (donc sauvegardé)
            shutil.rmtree(self.data / "claude-code", ignore_errors=True)
        if self.fixed:
            return []
        cfg = self.settings.llm()
        problems = cfg.problems()
        if cfg.backends and not problems:
            # les dossiers d'appel de la CLI (prompts privés, jeton de session MCP) hors du dossier de
            # données — donc hors des sauvegardes — et en mémoire (XDG_RUNTIME_DIR)
            self.gateway.set(build_gateway(cfg, self.kernel.deps.clock, on_trace=self.trace, relay=self.relay,
                                           relay_base=lambda: self.relay_base,
                                           work_dir=runtime_dir(self.data) if self.data else None))
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
    web = web or WebConfig()
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
             "workshop": BwrapWorkshop(data / "ateliers", credentials=settings.git), "camera": camera,
             "forge": forge, "forge_settings": forge_settings}
    kernel = Kernel(composition.deps(store=store, clock=clock, ids=RandomIdGen(), gateway=gateway,
                                     ports={"delivery": router, "vectors": vectors, **world}, **deps))
    port = KernelPort(kernel)
    hub.port = port
    live = Live(kernel, hub, port, Accounts(store), settings, gateway, router, fixed, calls=CallLog(store),
                persona_file=persona, data=data)
    # le monde (ADR 0051) : chaque lot commité qui change ce que montrent ses écrans leur part, traduit en trames
    world_hub = live.world = WorldHub(port, live.accounts, origins=web.origins, auth_required=web.auth_required)

    def publish_world(events: Sequence[Any], root: Any) -> None:
        if world_hub.listening:
            update = port.world_update(events, root)
            if update is not None:
                world_hub.publish(*update)

    kernel.mind.subscribe(publish_world)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        datadir.hold(data)  # un seul Mika par dossier : un second processus est refusé, pas mêlé au journal
        # deux temps : relire sa vie et sa configuration, brancher tout ce qui fait sortir sa parole
        # (passerelle des modèles, budget, écrans, Telegram), puis seulement la vie (reprises, processus,
        # file de sortie) — sinon une reprise au démarrage partait sans modèle ni canal.
        await kernel.boot(configure=lambda k: composition.configure(k, live.persona(), settings.overrides(),
                                                                    live.inputs()))
        await live.settings.open()
        await live.accounts.open()
        await register_accounts(kernel, live.accounts)  # ceux d'avant, et ceux créés hors ligne (mika account)
        live.accounts.on_change = lambda: register_accounts(kernel, live.accounts)
        await live.calls.open()
        problems = await live.reload_llm()
        if not gateway.configured and not problems:
            log.warning("aucun modèle ne sert « répondre » : elle ne peut pas parler. Déclare un fournisseur dans "
                        "la console, %s (ou `python -m mika llm backend --help`)",
                        f"{live.console_url}/reglages/fournisseurs" if live.console_url else
                        "Configuration › Fournisseurs")
        for problem in problems:
            log.warning("configuration des modèles : %s", problem)
        hub.start()
        world_hub.start()
        try:
            await live.start_telegram()
        except Exception as exc:  # noqa: BLE001 — un robot mal configuré n'empêche pas le reste de vivre
            log.warning("Telegram : démarrage impossible (%r)", exc)
        await kernel.live()
        try:
            yield
        finally:
            await world_hub.stop()
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
                                     faculty_labels=FACULTY_LABELS, labels=LABELS,
                                     backups=lambda: backup.overview(data)),
                       cookie_secure=web.cookie_secure)
    preprocess = LocalPreprocessor(gateway, transcribe=whisper(settings.stt))
    live.preprocess = preprocess
    relay = Mount(RELAY_PREFIX, app=live.relay.app)
    console_mcp = Mount(CONSOLE_MCP_PREFIX, app=console_app(kernel, settings.console_mcp_token))
    return create_app(port, live.accounts, hub, web, lifespan=lifespan,
                      extra_routes=[Route("/", _root, methods=["GET", "HEAD"]), *inspector, relay, console_mcp,
                                    world_hub.route()],
                      preprocess=preprocess, camera=camera, sensor_token=settings.sensors_token,
                      health_extra=live.channel_health), live


async def register_accounts(kernel: Kernel, accounts: Accounts) -> int:
    """Chaque compte du système existe comme personne, sous son nom, dès sa création :
    un ``identity.registered`` pour ceux dont l'identité diffère du compte (nouveau, renommé,
    promu, désactivé) — comparer d'abord rend l'appel idempotent, et un renommage aller-retour
    s'écrit quand même (une clé de dédoublonnage l'aurait avalé). Rend le nombre écrit."""
    frame = kernel.mind.frame()
    drafts = []
    for a in accounts.all():
        view = frame.get(identity_c.IDENTITY(a.handle))
        name = clean_display_name(a.display_name)
        operator = a.operator and a.active
        if view.known and view.authenticated and view.name == name and view.operator == operator:
            continue
        drafts.append(identity_c.REGISTERED.draft(handle=a.handle, name=name, operator=a.operator, active=a.active))
    if drafts:
        await kernel.mind.append(drafts, emitter=identity_c.OWNER, correlation="comptes", origin=Origin.EXTERNAL)
    return len(drafts)


def relay_base(host: str, port: int) -> str:
    """Où la CLI de Claude Code joint le relais : la boucle locale (le relais
    ne sert qu'elle). Un serveur qui n'écoute que sur une autre adresse ne peut
    pas servir de relais : vide, et les appels Claude Code échouent en le disant."""
    if host in ("", "127.0.0.1", "0.0.0.0", "localhost"):
        return f"http://127.0.0.1:{port}"
    if host in ("::1", "::"):
        return f"http://[::1]:{port}"
    return ""


def console_url(host: str, port: int) -> str:
    """L'adresse de la console sur cette machine (ce que le journal de démarrage montre)."""
    shown = "127.0.0.1" if host in ("", "0.0.0.0", "localhost") else "[::1]" if host in ("::", "::1") else host
    return f"http://{shown}:{port}{CONSOLE_PREFIX}"


async def _root(request: Request) -> Response:
    """``/`` : rien d'autre à servir ici que la console (le chat est le frontend, servi à part)."""
    return RedirectResponse(f"{CONSOLE_PREFIX}/", status_code=303)


def web_config(*, origins: Sequence[str] = (), cookie_secure: bool = False, behind_proxy: bool = False) -> WebConfig:
    """La configuration web d'un déploiement : les origines du frontend (par défaut celles du
    développement), des cookies ``Secure`` derrière TLS, l'adresse du client lue chez le mandataire."""
    clean = tuple(dict.fromkeys(o.strip().rstrip("/") for o in origins if o.strip()))
    return WebConfig(origins=clean or DEV_ORIGINS, cookie_secure=cookie_secure or behind_proxy,
                     behind_proxy=behind_proxy)


def serve(*, host: str = "127.0.0.1", port: int = 8001, data: Path = Path("data/v2"),
          reports: Path | None = None, origins: Sequence[str] = (), cookie_secure: bool = False,
          behind_proxy: bool = False) -> None:
    import uvicorn  # noqa: PLC0415 — seul le serveur réel en a besoin

    configure_logging()
    datadir.hold(data)  # avant d'ouvrir quoi que ce soit : refusé tout de suite, en le disant
    problem, blocking = persona_file.startup(data, PERSONA)
    if blocking:  # une persona illisible, et aucune gardée : dit en français, sans trace
        log.error("persona : %s", problem)
        datadir.release(data)
        raise SystemExit(2)
    if problem:
        log.warning("persona : %s", problem)
    app, live = build(data, reports=reports, web=web_config(origins=origins, cookie_secure=cookie_secure,
                                                            behind_proxy=behind_proxy))
    live.relay_base = relay_base(host, port)
    live.console_url = console_url(host, port)
    log.info("console : %s/", live.console_url)
    # un arrêt (SIGTERM) laisse 20 s aux connexions, puis le cycle de vie arrête le noyau. Les en-têtes de
    # mandataire ne sont crus que derrière un mandataire déclaré (local) ; ailleurs, l'adresse vue fait foi.
    # ``log_config=None`` : les journaux d'uvicorn passent par les nôtres (et leur masque des secrets).
    uvicorn.run(app, host=host, port=port, ws_max_size=protocol.MAX_FRAME_BYTES, log_level="info",
                timeout_graceful_shutdown=20, log_config=None, proxy_headers=behind_proxy,
                forwarded_allow_ips="127.0.0.1,::1" if behind_proxy else None)
