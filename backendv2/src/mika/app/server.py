"""Le serveur : le noyau réel (horloge, identifiants, magasin, modèles),
l'adaptateur web par-dessus, un seul processus.

``python -m mika serve --port 8001`` puis, dans ``frontend/Web/`` : ``npm run dev``.
Derrière un mandataire TLS : ``--origin https://mika.example --cookie-secure
--behind-proxy`` (voir ``deploy/README.md``). Un moteur de jeu se connecte au monde
sur ``/ws/world`` (ADR 0051) avec un jeton de son compte : ``python -m mika token
create <compte> --label "Unity"``.

Les journaux ne portent jamais un secret : un jeton passé en paramètre d'URL
(un flux), un ``Bearer`` sont masqués ; ``httpx``/``httpcore`` ne parlent qu'en
avertissement.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import shutil
from collections.abc import AsyncIterator, Mapping, Sequence
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
from mika.adapters.imaging.config import LiveImaging
from mika.adapters.imaging.config import build_gateway as build_image_gateway
from mika.adapters.imaging.gateway import ImageTrace
from mika.adapters.llm.calls import CallLog
from mika.adapters.llm.claude_code import runtime_dir
from mika.adapters.llm.config import LiveGateway, build_gateway
from mika.adapters.llm.gateway import LLMTrace
from mika.adapters.mail import ImapSmtpMail
from mika.adapters.mcp.hub import McpHub
from mika.adapters.mcp.relay import PREFIX as RELAY_PREFIX
from mika.adapters.mcp.relay import Relay
from mika.adapters.mcp.system import SystemServers
from mika.adapters.preprocess import LocalPreprocessor, whisper
from mika.adapters.shares import DiskShares
from mika.adapters.store_sqlite import SqliteStore
from mika.adapters.system import RandomIdGen, RealClock
from mika.adapters.vectors import SentenceEmbedder, SqliteVectorIndex
from mika.adapters.web import protocol
from mika.adapters.web.accounts import Accounts
from mika.adapters.web.app import DEV_ORIGINS, WebConfig, create_app
from mika.adapters.web.hub import Hub
from mika.adapters.workshop import BwrapWorkshop
from mika.adapters.world.server import WorldHub
from mika.app import backup, composition, datadir, reglages, system_mcp
from mika.app import persona as persona_file
from mika.app.console import FACULTY_LABELS, LABELS, NAVIGATION, PARAM_FAMILIES
from mika.app.mindport import KernelPort
from mika.app.paths import PERSONA
from mika.app.settings import SecretBox, Settings
from mika.contracts import identity as identity_c
from mika.contracts.self_ import PersonaDoc
from mika.inspector.app import routes
from mika.inspector.mcp import PREFIX as CONSOLE_MCP_PREFIX
from mika.inspector.mcp import console_app
from mika.inspector.ui import PREFIX as CONSOLE_PREFIX
from mika.inspector.ui import InspectorDeps
from mika.kernel.builtin import PARAMS_CHANGED
from mika.kernel.events import Origin
from mika.kernel.prompt import Budget
from mika.runtime.bootstrap import Kernel
from mika.vocab import privacy
from mika.vocab.people import clean_display_name

log = logging.getLogger("mika.server")

#: ce qu'un journal ne doit jamais montrer
_SECRETS = (
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
    #: une passerelle fournie de l'extérieur (tests, simulateur) n'est pas rechargée
    fixed: bool = False
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
    #: les clients du monde (``/ws/world``, ADR 0051) : moteurs de jeu et écrans
    world: WorldHub | None = None
    #: la génération d'images (désactivée tant qu'aucun fournisseur n'est branché, ADR 0061)
    imaging: LiveImaging = field(default_factory=LiveImaging)
    #: une génération d'images fournie de l'extérieur (tests) n'est pas rechargée
    imaging_fixed: bool = False
    #: les serveurs MCP branchés (ADR 0064), le port ``mcp``
    mcp: McpHub | None = None

    def trace(self, tr: LLMTrace) -> None:
        self.gateway.traces.append(tr)
        if self.calls is not None:
            self.calls.record(tr)

    def trace_image(self, tr: ImageTrace) -> None:
        """Un appel d'images : gardé en mémoire, et au registre des appels sous le rôle ``image.<rôle>`` — ce
        qu'il a coûté s'ajoute à celui des modèles."""
        self.imaging.traces.append(tr)
        if self.calls is not None:
            self.calls.record(LLMTrace(
                at=tr.at, role=f"image.{tr.role}", backend=tr.backend, model=tr.model, lane=tr.lane,
                priority=tr.priority, latency_us=tr.latency_us, wait_us=tr.wait_us,
                input_tokens=tr.text_tokens + tr.image_tokens, output_tokens=tr.output_tokens, outcome=tr.outcome,
                call_id=tr.call_id, cost_usd=tr.cost_usd, correlation=tr.correlation))

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

    async def reload_imaging(self) -> list[str]:
        """Rebranche la génération d'images sur ses réglages ; sans fournisseur, elle n'existe pas."""
        if self.imaging_fixed:
            return []
        cfg = self.settings.imaging()
        problems = cfg.problems()
        if cfg.backends and not problems:
            self.imaging.set(build_image_gateway(cfg, self.kernel.deps.clock, on_trace=self.trace_image))
        else:
            self.imaging.set(None)
        return problems


def build(data: Path, *, persona: Path = PERSONA, web: WebConfig | None = None,
          gateway: LiveGateway | None = None, embedder: Any = None, reports: Path | None = None,
          imaging: LiveImaging | None = None, **deps: Any) -> tuple[Starlette, Live]:
    """L'application et ce qu'elle fait vivre. Tout est construit ici ; le
    cycle de vie ouvre, démarre et arrête."""
    data.mkdir(parents=True, exist_ok=True)
    web = web or WebConfig()
    store = SqliteStore(data / "mind.db", data / "views.db", threaded=True)
    clock = RealClock()
    fixed = gateway is not None
    gateway = gateway or LiveGateway()
    imaging_fixed = imaging is not None
    imaging = imaging or LiveImaging()
    hub = Hub(port=None)  # type: ignore[arg-type] — relié au port juste après
    vectors = SqliteVectorIndex(store, embedder or SentenceEmbedder())
    camera = CameraBuffer(clock.now)
    settings = Settings(store, SecretBox.for_data(data))
    forge_settings = ForgeSettingsStore(settings)
    forge = forge_settings.host = ForgeHost(data / "forge", config=forge_settings.values)
    world = {"mail": ImapSmtpMail(settings.email, data / "mail.db"),
             "feeds": HttpFeeds(settings.feeds, data / "feeds.db"),
             "workshop": BwrapWorkshop(data / "ateliers", credentials=settings.git), "camera": camera,
             "forge": forge, "forge_settings": forge_settings, "imaging": imaging}
    # les fichiers qu'elle envoie (ADR 0062) : leurs octets hors du journal, sauvegardés avec le dossier
    world["shares"] = DiskShares(data / "partages")
    # les outils venus d'ailleurs (ADR 0064) : la configuration relue à chaque usage, les décisions aussi — plus les
    # serveurs de ses plugins système, d'après leurs paramètres, approuvés d'office (ADR 0066)
    system = SystemServers(lambda: system_mcp.provided(
        lambda owner: kernel.mind.registry.params_of(owner, kernel.mind.root)))
    mcp = world["mcp"] = McpHub(lambda: system.config(settings.mcp()), lambda: system.reviews(settings.mcp_tools()),
                                system.saving(settings.save_mcp_tools), local_root=data / "mcp")
    kernel = Kernel(composition.deps(store=store, clock=clock, ids=RandomIdGen(), gateway=gateway,
                                     ports={"delivery": hub, "vectors": vectors, **world}, **deps))

    reconfiguring: set[asyncio.Task[None]] = set()

    def reconfigure_mcp(events: Sequence[Any], root: Any) -> None:
        """Les paramètres d'un plugin qui apporte un serveur ont changé (activé, désactivé, réglé) : le client MCP
        ferme ce qui a changé et rejoint ce qui doit l'être ; ses outils suivent."""
        if not any(e.type is PARAMS_CHANGED and e.data.owner in system_mcp.OWNERS for e in events):
            return
        try:
            task = asyncio.get_running_loop().create_task(mcp.reconfigure())
        except RuntimeError:  # pas de boucle (une commande hors ligne) : il se reconfigurera au démarrage
            return
        reconfiguring.add(task)
        task.add_done_callback(reconfiguring.discard)

    kernel.mind.subscribe(reconfigure_mcp)
    port = KernelPort(kernel)
    hub.port = port
    live = Live(kernel, hub, port, Accounts(store), settings, gateway, fixed, calls=CallLog(store),
                persona_file=persona, data=data, imaging=imaging, imaging_fixed=imaging_fixed, mcp=mcp)
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
        # (passerelle des modèles, budget, écrans), puis seulement la vie (reprises, processus,
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
        for problem in await live.reload_imaging():
            log.warning("configuration des images : %s", problem)
        mcp.on_change(kernel.refresh_tools)  # son offre change : ses outils aussi (ADR 0064)
        mcp.start()  # chaque serveur actif est joint en tâche de fond
        hub.start()
        world_hub.start()
        await kernel.live()
        try:
            yield
        finally:
            await world_hub.stop()
            await hub.stop()

            async def release() -> None:
                # les épisodes déjà annulés (une réponse en cours reste à reprendre) : seulement
                # alors les fournisseurs se ferment, et le registre des appels se vide magasin ouvert
                await mcp.aclose()
                await gateway.aclose()
                await imaging.aclose()
                await live.calls.flush()

            await kernel.stop(release)
            datadir.release(data)

    inspector = routes(InspectorDeps(kernel, live.accounts, live.settings, live.reload_llm, gateway.traces,
                                     port=port, calls=live.calls, reconfigure=live.reconfigure,
                                     after_decision=hub.refresh_panels,
                                     reports=reports, navigation=NAVIGATION,
                                     sections=reglages.sections(live), settings_tabs=reglages.TABS,
                                     parameters=reglages.parameters(live), param_families=PARAM_FAMILIES,
                                     faculty_labels=FACULTY_LABELS, labels=LABELS,
                                     backups=lambda: backup.overview(data), relay=live.relay),
                       cookie_secure=web.cookie_secure)
    preprocess = LocalPreprocessor(gateway, transcribe=whisper(settings.stt))
    live.preprocess = preprocess
    relay = Mount(RELAY_PREFIX, app=live.relay.app)
    console_mcp = Mount(CONSOLE_MCP_PREFIX, app=console_app(kernel, settings.console_mcp_token))
    return create_app(port, live.accounts, hub, web, lifespan=lifespan,
                      extra_routes=[Route("/", _root, methods=["GET", "HEAD"]), *inspector, relay, console_mcp,
                                    world_hub.route()],
                      preprocess=preprocess, camera=camera, sensor_token=settings.sensors_token), live


async def register_accounts(kernel: Kernel, accounts: Accounts) -> int:
    """Chaque compte du système existe comme personne, sous son nom, dès sa création :
    un ``identity.registered`` pour ceux dont l'identité diffère du compte (nouveau, renommé,
    promu, désactivé) — comparer d'abord rend l'appel idempotent, et un renommage aller-retour
    s'écrit quand même (une clé de dédoublonnage l'aurait avalé). Rend le nombre écrit.

    Il dit aussi si la personne a une application qui reçoit hors ligne (un jeton ``mobile`` vivant, ADR 0062) :
    elle peut alors lui écrire absente ; le jeton révoqué, elle ne le peut plus."""
    frame = kernel.mind.frame()
    drafts = []
    for a in accounts.all():
        view = frame.get(identity_c.IDENTITY(a.handle))
        name = clean_display_name(a.display_name)
        operator = a.operator and a.active
        messaging = privacy.MOBILE if a.active and accounts.has_mobile(a.id) else ""
        if (view.known and view.authenticated and view.name == name and view.operator == operator
                and view.push == bool(messaging)):
            continue
        drafts.append(identity_c.REGISTERED.draft(handle=a.handle, name=name, operator=a.operator, active=a.active,
                                                  messaging=messaging))
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
