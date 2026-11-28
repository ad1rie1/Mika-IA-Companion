"""Le serveur : le noyau réel (horloge, identifiants, magasin, modèles),
l'adaptateur web par-dessus, un seul processus.

``python -m mika serve --port 8001`` puis, dans ``frontend/Web/`` (le client de tous
les jours) : ``npm run dev``.
Derrière un mandataire TLS : ``--origin https://mika.example --cookie-secure
--behind-proxy`` (voir ``deploy/README.md``).

Les journaux ne portent jamais un secret (``logs.py``).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import shutil
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Mount, Route

from mika.adapters.addresses import serving_on
from mika.adapters.llm.calls import CallLog
from mika.adapters.llm.claude_code import runtime_dir
from mika.adapters.llm.config import BackendSpec, LiveGateway, ModelLimits, build_gateway
from mika.adapters.llm.gateway import LLMTrace
from mika.adapters.llm.models import model_limits
from mika.adapters.mcp.relay import PREFIX as RELAY_PREFIX
from mika.adapters.mcp.relay import Relay
from mika.adapters.preprocess import LocalPreprocessor, whisper
from mika.adapters.push import FcmSender
from mika.adapters.shares import DiskShares
from mika.adapters.store_sql import SqlStore
from mika.adapters.system import RandomIdGen, RealClock
from mika.adapters.vectors import SqliteVectorIndex
from mika.adapters.web import protocol
from mika.adapters.web.accounts import Accounts
from mika.adapters.web.app import DEV_ORIGINS, WebConfig, create_app
from mika.adapters.web.hub import Hub
from mika.adapters.web.push import MobilePush
from mika.app import backup, composition, datadir, embeddings, schema, settings_sections
from mika.app import persona as persona_file
from mika.app.console import FACULTY_LABELS, LABELS, NAVIGATION, PARAM_FAMILIES
from mika.app.console_menu import menu_for
from mika.app.constellation import Constellation
from mika.app.domains import DOMAINS, gathered, part
from mika.app.handmade import access, approval_sources, rights, waiting
from mika.app.handmade.home import HomePage
from mika.app.handmade.now import NowPage
from mika.app.handmade.pages import DRAWN, OVERVIEWS, PLAIN_OWNERS
from mika.app.handmade.person import PersonOverview
from mika.app.handmade.tabs.people import PeoplePage
from mika.app.logs import configure_logging
from mika.app.me.assembly import MeApi
from mika.app.me.changes import LiveChanges
from mika.app.mindport import KernelPort
from mika.app.paths import PERSONA
from mika.app.settings import SecretBox, Settings, push_key_file
from mika.app.wiring import Wiring
from mika.contracts import attachments as attachments_c
from mika.contracts import identity as identity_c
from mika.contracts import self_ as self_c
from mika.contracts import social as social_c
from mika.contracts.self_ import PersonaDoc, name_of
from mika.inspector.app import assemble
from mika.inspector.mcp import PREFIX as CONSOLE_MCP_PREFIX
from mika.inspector.mcp import console_app
from mika.inspector.ui import PREFIX as CONSOLE_PREFIX
from mika.inspector.ui import InspectorDeps
from mika.kernel.events import Origin
from mika.ports.changes import ME, PHONE_PHONES
from mika.runtime.bootstrap import Kernel
from mika.vocab import privacy
from mika.vocab.people import clean_display_name

log = logging.getLogger("mika.server")

#: ce qu'uvicorn laisse au pong de son ping avant de fermer la connexion (1011). Un client n'intercale pas de pong
#: au milieu d'une trame qu'il envoie : le défaut (20 s) coupait toute montée plus longue — une trame de chat et ses
#: fichiers sur des données mobiles —, que le client renvoyait aussitôt. Couvre la plus grande trame admise montée à
#: 1 Mbit/s, plus un intervalle de ping ; une connexion morte est toujours fermée, seulement plus tard.
WS_PING_TIMEOUT_S = protocol.MAX_FRAME_BYTES * 8 / 1_000_000 + 20.0

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
    #: lit chez son fournisseur ce qu'accepte le modèle d'une fiche qu'on enregistre (ADR 0136) ; ``None`` : personne
    #: n'est interrogé (une passerelle fournie de l'extérieur, où les fournisseurs des réglages ne servent pas)
    read_limits: Callable[[BackendSpec], Awaitable[ModelLimits]] | None = None
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
    #: sa mémoire en une boule de points, et ce qui la parcourt (la console, ADR 0103)
    constellation: Constellation | None = None
    #: les objets vivants de chaque domaine qui a son câblage (ADR 0310), par son nom : les dessins (``imaging`` : la
    #: passerelle d'images, le port du même nom, son rechargement et sa trace, ADR 0061, 0317), les réveils par API
    #: (``wakeup`` : le port du même nom et la porte de ``POST /api/wake/<nom>``), ses outils venus
    #: d'ailleurs (``tools`` : le client MCP, le port ``mcp``, ADR 0064), la carte (``maps`` : le port du même nom,
    #: ADR 0194 ; et ``tiles`` : les tuiles de la carte de sa position, lues ou relayées par ce serveur, ADR 0193),
    #: Teams (``teams`` : la clé de l'extension et la porte de ``/api/teams/…``, ADR 0069)
    parts: dict[str, Any] = field(default_factory=dict)
    #: le direct (ADR 0308) : ce qui change ce que montrent les écrans de tous les jours, poussé sur leur ``/ws``
    changes: LiveChanges | None = None

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
        for domain in DOMAINS:  # ce que les réglages d'un domaine qui a sa fiche donnent à ses plugins (``inputs``)
            if domain.wiring is not None:
                out.update(part(domain.wiring, "inputs", _no_inputs)(self.settings))
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
        else:
            self.gateway.set(None)
        return problems


#: Ce qu'on attend au plus le modèle de plongements avant de la faire vivre (``kernel.live`` : reprises, premiers
#: messages) — au-delà, elle vit sans, et le premier rappel l'attendra comme avant.
WARM_WAIT_S = 30.0


def _unbound(wiring: Wiring) -> None:
    """Le ``bind`` d'un domaine qui n'en a pas : rien ne l'attend après le noyau."""


def _no_inputs(settings: Settings) -> dict[str, dict[str, Any]]:
    """Les ``inputs`` d'un domaine dont les réglages ne donnent rien aux paramètres de ses plugins."""
    return {}


async def _idle(wiring: Wiring) -> None:
    """Le ``start``, le ``stop`` ou le ``release`` d'un domaine qui n'en a pas."""


async def _warm(embedder: object) -> None:
    """Charge le modèle de plongements s'il sait le faire (``warm``) ; un échec n'empêche rien : le premier rappel
    le chargera, comme avant."""
    warm = getattr(embedder, "warm", None)
    if warm is None:
        return
    try:
        await warm()
    except Exception:  # noqa: BLE001 — un préchargement manqué ne doit pas faire tomber le démarrage
        log.exception("préchargement du modèle de plongements : échec (il se chargera au premier rappel)")


def build(data: Path, *, persona: Path = PERSONA, web: WebConfig | None = None,
          gateway: LiveGateway | None = None, embedder: Any = None, reports: Path | None = None,
          serving: bool = False, **deps: Any) -> tuple[Starlette, Live]:
    """L'application et ce qu'elle fait vivre. Tout est construit ici ; le
    cycle de vie ouvre, démarre et arrête. ``serving`` : le serveur sert pour de
    bon, ce que ``serve`` dit — un domaine peut alors joindre le dehors de
    lui-même (le courrier en direct, ADR 0308) ; un test ou l'aperçu qui monte
    le serveur ne joint ainsi aucun serveur de courrier sans le dire."""
    data.mkdir(parents=True, exist_ok=True)
    bases = schema.targets(data)  # des fichiers du dossier, ou les bases du serveur de MIKA_DATABASE_URL (ADR 0101)
    schema.migrate_data(data, bases)  # chaque base à sa dernière révision, avant que rien ne s'ouvre
    web = web or WebConfig()
    store = SqlStore(bases["mind"], bases["views"], threaded=True)
    clock = RealClock()
    fixed = gateway is not None
    gateway = gateway or LiveGateway()
    hub = Hub(port=None)  # type: ignore[arg-type] — relié au port juste après
    vectors = SqliteVectorIndex(store, embedder or embeddings.embedder())
    # les pièces jointes reçues ont leur propre index (le rapprochement de celui de la mémoire retire toute clé qui
    # n'est pas à elle), avec le même modèle de plongements (ADR 0106)
    piece_vectors = SqliteVectorIndex(store, vectors.embedder, table=attachments_c.VECTORS)
    settings = Settings(store, SecretBox.for_data(data))
    def her() -> str:
        """Son nom, celui de la persona en vigueur (journalisée) : ce que signent ses mails et ses enregistrements
        d'atelier — un adaptateur ne lit pas sa persona lui-même (ADR 0070)."""
        return name_of(kernel.mind.root.slices["self"].persona)

    # les fichiers qu'elle envoie (ADR 0062) : leurs octets hors du journal, sauvegardés avec le dossier
    outside: dict[str, Any] = {"shares": DiskShares(data / "partages")}
    # ce qu'on lui envoie (ADR 0106) : les octets des pièces jointes, leur index, et de quoi les relire de près
    outside[attachments_c.PORT] = DiskShares(data / "pieces")
    outside[attachments_c.VECTORS] = piece_vectors
    preprocess = outside["preprocess"] = LocalPreprocessor(gateway, transcribe=whisper(settings.stt))
    # ce que chaque domaine apporte (ADR 0310) : ses adaptateurs, ses ports, ses portes HTTP — sa fiche nomme son
    # câblage, que ce serveur appelle sans le connaître (``app/wiring.py``)
    wiring = Wiring(data=data, settings=settings, clock=clock, bases=bases, ports=outside, store=store, her=her,
                    serving=serving)
    wired = [d.wiring for d in DOMAINS if d.wiring is not None]
    # les ports que ce serveur pose lui-même, puis ceux que chaque domaine pose : un nom repris (« vectors », le port
    # d'un autre domaine) écraserait l'autre sans bruit dans les ports du noyau — il est refusé (``gathered``)
    posed: list[tuple[str, dict[str, Any]]] = [
        ("le serveur", {"delivery": hub, "activity": hub, "vectors": vectors, **outside})]
    for d in DOMAINS:
        if d.wiring is not None:
            before = dict(outside)
            part(d.wiring, "wire")(wiring)
            posed.append((f"le domaine « {d.name} »",
                          {k: v for k, v in outside.items() if k not in before or before[k] is not v}))
    gathered("un port du noyau", posed)
    kernel = Kernel(composition.deps(store=store, clock=clock, ids=RandomIdGen(), gateway=gateway,
                                     ports={"delivery": hub, "activity": hub, "vectors": vectors, **outside},
                                     access_tables=settings.access_tables, closeness=social_c.is_close,
                                     authors=settings.author_for, **deps))

    port = KernelPort(kernel)
    hub.port = port
    live = Live(kernel, hub, port, Accounts(store), settings, gateway, fixed, calls=CallLog(store),
                persona_file=persona, data=data, parts=wiring.parts, read_limits=None if fixed else model_limits)
    # l'exemple de l'autrice « Message », quand le sien est vide : le fil de référence de sa persona (ADR 0124), lu au
    # journal (lu à chaque épisode : jamais le YAML)
    settings.reference_thread = lambda: kernel.mind.frame().get(self_c.PERSONA).reference_thread
    # les notifications du téléphone fermé (ADR 0077) : par Firebase, la clé relue à chaque envoi — collée dans la
    # console, sinon le fichier ``firebase-service-account.json`` du dossier de données
    push_sender = FcmSender(lambda: settings.push() or push_key_file(data))
    hub.push = MobilePush(live.accounts, push_sender)
    # ce qui, dans un domaine, a besoin du noyau : son port d'entrée, le serveur vivant, les notifications
    wiring.port, wiring.live, wiring.push = port, live, hub.push
    for module in wired:
        part(module, "bind", _unbound)(wiring)
    # sa mémoire en une boule de points, et ce qui la parcourt (console, opérateurs) : ne traduit rien sans lecteur
    constellation = live.constellation = Constellation(kernel, vectors, live.accounts)
    kernel.mind.subscribe(constellation.listen)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        datadir.hold(data)  # un seul Mika par dossier : un second processus est refusé, pas mêlé au journal
        # le modèle de plongements se charge pendant la relecture de sa vie, pas au premier message
        warming = asyncio.create_task(_warm(vectors.embedder))
        # deux temps : relire sa vie et sa configuration, brancher tout ce qui fait sortir sa parole
        # (passerelle des modèles, budget, écrans), puis seulement la vie (reprises, processus,
        # file de sortie) — sinon une reprise au démarrage partait sans modèle ni canal.
        await kernel.boot(configure=lambda k: composition.configure(k, live.persona(), settings.overrides(),
                                                                    live.inputs()))
        await live.settings.open()
        await live.accounts.open()
        if live.accounts.count() == 0 and web.bootstrap_code:
            log.warning("aucun compte n'existe : le premier (opérateur) se crée sur la page de connexion. Depuis une "
                        "autre machine que celle-ci, elle demande le code de premier démarrage : %s", web.bootstrap_code)
        await register_accounts(kernel, live.accounts)  # ceux d'avant, et ceux créés hors ligne (mika account)

        async def accounts_changed() -> None:
            await register_accounts(kernel, live.accounts)
            # un nom, un téléphone branché ou révoqué : ce qu'en montrent les écrans de chacune (ADR 0308)
            live_changes.everyone(ME, PHONE_PHONES)

        live.accounts.on_change = accounts_changed
        await live.calls.open()
        problems = await live.reload_llm()
        if not gateway.configured and not problems:
            log.warning("aucun modèle ne sert « répondre » : elle ne peut pas parler. Déclare un fournisseur dans "
                        "la console, %s (ou `python -m mika llm backend --help`)",
                        f"{live.console_url}/reglages/fournisseurs" if live.console_url else
                        "Réglages › Modèles de texte › Fournisseurs")
        for problem in problems:
            log.warning("configuration des modèles : %s", problem)
        hub.start()
        live_changes.start()
        constellation.start()
        for module in wired:  # ce que chaque domaine démarre, une fois le direct en marche (``start``)
            await part(module, "start", _idle)(wiring)
        # sa mémoire prête avant sa première réponse : un message qui attendait au démarrage, une reprise, ne passent
        # pas sans souvenirs parce que le modèle de plongements finissait de se charger (borné : ``WARM_WAIT_S``)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(asyncio.shield(warming), WARM_WAIT_S)
        await kernel.live()
        try:
            yield
        finally:
            warming.cancel()
            for module in reversed(wired):  # ce que chaque domaine arrête, avant le direct (``stop``)
                await part(module, "stop", _idle)(wiring)
            await constellation.stop()
            await live_changes.stop()
            await hub.stop()

            async def release() -> None:
                # les épisodes déjà annulés (une réponse en cours reste à reprendre) : seulement
                # alors les fournisseurs se ferment, et le registre des appels se vide magasin ouvert
                for module in reversed(wired):  # ce que chaque domaine ferme, ses épisodes annulés (``release``)
                    await part(module, "release", _idle)(wiring)
                await gateway.aclose()
                await push_sender.aclose()
                await live.calls.flush()

            await kernel.stop(release)
            datadir.release(data)

    # la vue d'ensemble d'une personne, dessinée à la main (ADR 0121) : le premier onglet de sa fiche
    person_overview = PersonOverview()
    # la console, et ses pages sans requête : la console en MCP lit les mêmes (santé, épisodes, « pourquoi »…)
    inspector, console_pages = assemble(
        InspectorDeps(kernel, live.accounts, live.settings, gateway.traces, port=port, calls=live.calls,
                      bootstrap_code=web.bootstrap_code,
                      after_decision=hub.refresh_panels, reconfigure=live.reconfigure,
                      reports=reports, navigation=NAVIGATION, menu=menu_for(reports),
                      sections=settings_sections.sections(live), settings_tabs=settings_sections.RUBRICS,
                      parameters=settings_sections.parameters(live), param_families=PARAM_FAMILIES,
                      faculty_labels=FACULTY_LABELS, labels=LABELS,
                      backups=lambda: backup.overview(data), relay=live.relay,
                      overviews={"person": person_overview, **OVERVIEWS},
                      drawn=DRAWN, approval_sources=approval_sources.sources, queue=waiting.QUEUE,
                      nameable=access.people_with_accounts, canal_instances=access.instances_from_settings,
                      family_href=access.family_href,
                      plain_owners=PLAIN_OWNERS, **wiring.inspector),
        cookie_secure=web.cookie_secure)
    # les pages dessinées à la main dans le cadre de la console, qui croisent ses facultés (ADR 0121) : l'accueil ;
    # elle, en ce moment ; les gens qu'elle connaît
    home_page = HomePage(console_pages.ui)
    now_page, people_page = NowPage(console_pages.ui), PeoplePage(console_pages.ui)
    live.preprocess = preprocess
    relay = Mount(RELAY_PREFIX, app=live.relay.app)
    console_mcp = Mount(CONSOLE_MCP_PREFIX, app=console_app(kernel, settings.console_mcp_digest, console_pages,
                                                            settings.console_mcp_served, settings.console_mcp_network))
    # ce que le client web montre à qui est connecté, et seulement à elle (ADR 0187) ; sa borne des trajets vaut aussi pour
    # le GPX d'un voyage qu'un opérateur tire de la console, sur son compte (ADR 0204)
    moi = MeApi(kernel, live.accounts, origins=web.origins,
                settings=live.settings, reconfigure=live.reconfigure, **wiring.me)
    # le direct (ADR 0308) : le journal, les bases tenues à côté (chacune prévient de ses écritures validées), l'étape
    # de son travail ; à chaque personne connectée, ce qu'elle voit — et la boîte d'envoi réveille l'extension
    live_changes = live.changes = LiveChanges(kernel, hub, moi)
    kernel.mind.subscribe(live_changes.listen)
    for base in wiring.watched:  # les bases des domaines
        base.on_change(live_changes.touch)
    kernel.runner.on_step = live_changes.step
    # ce qui est tenu hors du journal sans être une base à côté : les réglages (chaque enregistrement) ; ce qu'un
    # domaine signale de lui-même (la fin de l'attente d'un code Microsoft, la présence de l'extension Teams, la
    # connexion d'un compte d'agenda), son câblage le branche (``bind``)
    settings.on_saved = live_changes.saved
    return create_app(port, live.accounts, hub, web, lifespan=lifespan,
                      extra_routes=[Route("/", _root, methods=["GET", "HEAD"]), *constellation.routes(),
                                    *moi.routes(),
                                    *home_page.routes(), *now_page.routes(), *people_page.routes(),
                                    *person_overview.routes(console_pages.ui, outbound=moi.outbound),
                                    *rights.routes(console_pages.ui),
                                    *inspector, relay, console_mcp,
                                    *wiring.routes],
                      preprocess=preprocess, sensor_digest=settings.sensors_digest,
                      push_ready=push_sender.configured, **wiring.web), live


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


def web_config(*, origins: Sequence[str] = (), cookie_secure: bool = False, behind_proxy: bool = False,
               bootstrap_code: str = "") -> WebConfig:
    """La configuration web d'un déploiement : les origines du frontend (par défaut celles du
    développement), des cookies ``Secure`` derrière TLS, l'adresse du client lue chez le mandataire, et le code de
    premier démarrage que le premier compte créé depuis une autre machine doit donner."""
    clean = tuple(dict.fromkeys(o.strip().rstrip("/") for o in origins if o.strip()))
    return WebConfig(origins=clean or DEV_ORIGINS, cookie_secure=cookie_secure or behind_proxy,
                     behind_proxy=behind_proxy, bootstrap_code=bootstrap_code)


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
    # le premier compte : depuis cette machine, rien à prouver ; depuis une autre, ce code, tiré à chaque démarrage
    # et écrit au journal tant qu'aucun compte n'existe (audit du 2026-10-26 : le premier arrivé devenait opérateur)
    app, live = build(data, reports=reports, web=web_config(origins=origins, cookie_secure=cookie_secure,
                                                            behind_proxy=behind_proxy,
                                                            bootstrap_code=secrets.token_urlsafe(9)), serving=True)
    live.relay_base = relay_base(host, port)
    live.console_url = console_url(host, port)
    serving_on(port)  # ni une app de la Forge ni un article d'un flux ne joignent Mika, même par une adresse relayée
    log.info("console : %s/", live.console_url)
    # un arrêt (SIGTERM) laisse 20 s aux connexions, puis le cycle de vie arrête le noyau. Les en-têtes de
    # mandataire ne sont crus que derrière un mandataire déclaré (local) ; ailleurs, l'adresse vue fait foi.
    # ``log_config=None`` : les journaux d'uvicorn passent par les nôtres (et leur masque des secrets).
    # ``loop="asyncio"`` : uvloop (qu'installe uvicorn[standard], et qu'uvicorn prend d'office) donne aux processus
    # qu'elle lance des sockets pour entrée et sortie, pas des tubes ; pasta, qui isole le réseau d'un serveur MCP
    # (son serveur web, ADR 0066), sort alors aussitôt, sans un mot — le web ne lui était jamais offert (sonde du
    # 2026-10-13, ADR 0105).
    uvicorn.run(app, host=host, port=port, ws_max_size=protocol.MAX_FRAME_BYTES, log_level="info", loop="asyncio",
                ws_ping_timeout=WS_PING_TIMEOUT_S, timeout_graceful_shutdown=20, log_config=None,
                proxy_headers=behind_proxy, forwarded_allow_ips="127.0.0.1,::1" if behind_proxy else None)
