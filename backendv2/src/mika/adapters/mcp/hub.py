"""Le hub des serveurs MCP (ADR 0064) : le port ``mcp``.

Il joint chaque serveur déclaré (au démarrage, à la demande de l'opérateur, et quand la faculté le relance), garde
ce que le serveur propose **maintenant**, et rend l'instantané **approuvé** : un outil n'est offert que si
l'opérateur l'a activé, que son serveur a été joint et listé depuis sa dernière connexion, qu'il n'est pas en
panne, et que l'empreinte de l'outil est celle qui a été approuvée. Un serveur a son disjoncteur : N pannes de
transport d'affilée le coupent (ses outils quittent l'offre) jusqu'à ce qu'il réponde de nouveau.

Une session est ouverte paresseusement et gardée ; changer les réglages de connexion d'un serveur la ferme.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mika.adapters.mcp.client import (
    McpError,
    McpRemoteError,
    McpSession,
    ServerInfo,
    SessionExpired,
    Transport,
)
from mika.adapters.mcp.config import (
    MAX_DESCRIPTION,
    McpConfig,
    McpServer,
    StoredReview,
    tool_name,
    valid_choice,
)
from mika.adapters.mcp.http import HttpTransport
from mika.adapters.mcp.stdio import Launcher, Sandbox, StdioTransport
from mika.ports.mcp import (
    APPROVALS,
    NATURES,
    CallResult,
    LiveTool,
    OfferedTool,
    ServerStatus,
    ToolReview,
)
from mika.ports.preprocess import inert

log = logging.getLogger("mika.mcp")

#: les décisions de l'opérateur : serveur → outil → décision
Reviews = dict[str, dict[str, StoredReview]]
UNAVAILABLE = "Ce service n'est pas disponible en ce moment."
KEPT_MAX = 200


@dataclass(slots=True)
class _Server:
    name: str
    #: l'empreinte des réglages de connexion de la session ouverte
    conn: str = ""
    session: McpSession | None = None
    info: ServerInfo | None = None
    live: tuple[LiveTool, ...] = ()
    #: listé depuis sa dernière connexion (ses outils peuvent être offerts)
    listed: bool = False
    error: str = ""
    last_ok_at: int = 0
    last_error_at: int = 0
    calls: int = 0
    failures: int = 0
    consecutive: int = 0
    broken: bool = False
    #: la fin de sa sortie d'erreur (un serveur local), gardée quand il tombe
    log: tuple[str, ...] = ()
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


Connect = Callable[[str, McpServer], Transport]


class McpHub:
    def __init__(self, config: Callable[[], McpConfig], reviews: Callable[[], Reviews],
                 save_reviews: Callable[[Reviews], Awaitable[Any]], *, connect: Connect | None = None,
                 now_us: Callable[[], int] | None = None, local_root: Path | None = None,
                 sandbox: Sandbox | None = None) -> None:
        self._config = config
        self._reviews = reviews
        self._save_reviews = save_reviews
        #: les serveurs lancés ici : leur dossier (``<données>/mcp/<nom>``) et leur cage
        self.launcher = Launcher(local_root, sandbox) if local_root is not None else None
        self._connect = connect or self.open_transport
        self._now = now_us or (lambda: time.time_ns() // 1000)
        self._servers: dict[str, _Server] = {}
        self._listeners: list[Callable[[], Any]] = []
        self._tasks: set[asyncio.Task[Any]] = set()
        self._last_offer: tuple[Any, ...] | None = None
        #: les réponses d'appels exécutés après accord, le temps d'être journalisées (bornées)
        self._kept: dict[str, str] = {}

    # ── cycle de vie (``start`` une fois les réglages lus ; le noyau appelle ``shutdown`` à l'arrêt) ──
    def start(self) -> None:
        """Joindre en tâche de fond chaque serveur actif (le démarrage n'attend aucun d'eux)."""
        self._spawn(self.refresh())

    def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()

    async def aclose(self) -> None:
        self.shutdown()
        for st in self._servers.values():
            await self._drop(st)

    def on_change(self, fn: Callable[[], Any]) -> None:
        self._listeners.append(fn)

    # ── ce qui est offert ──
    def offered(self) -> list[OfferedTool]:
        cfg = self._safe_config()
        reviews = self._safe_reviews()
        out: list[OfferedTool] = []
        taken: set[str] = set()
        for name, spec in sorted(cfg.servers.items()):
            st = self._servers.get(name)
            if not spec.enabled or not spec.ready or st is None or st.broken or not st.listed:
                continue
            live = {t.remote: t for t in st.live}
            for remote, rv in sorted(reviews.get(name, {}).items()):
                tool = live.get(remote)
                if not rv.enabled or tool is None or tool.fingerprint != rv.fingerprint:
                    continue
                mine = tool_name(name, remote, taken)
                taken.add(mine)
                episodes = frozenset(k for k, on in (("conversation", spec.in_conversation),
                                                     ("initiative", spec.in_initiative),
                                                     ("travail", spec.in_work)) if on)
                out.append(OfferedTool(
                    server=name, remote=remote, name=mine,
                    description=rv.description or rv.server_description or tool.description,
                    schema=rv.schema_ or tool.schema, nature=rv.nature, approval=rv.approval,
                    audience=spec.audience, episodes=episodes, in_hand=spec.in_hand, max_calls=spec.max_calls,
                    max_result_chars=spec.max_result_chars, purpose=inert(spec.purpose, 400),
                    when_to_use=inert(spec.when_to_use, 400), local=spec.local, fingerprint=rv.fingerprint))
        return out

    def statuses(self) -> list[ServerStatus]:
        cfg = self._safe_config()
        return [s for s in (self.status(n) for n in sorted(cfg.servers)) if s is not None]

    def status(self, server: str) -> ServerStatus | None:
        spec = self._safe_config().servers.get(server)
        if spec is None:
            return None
        st = self._servers.get(server) or _Server(server)
        problems = spec.problems()
        if not spec.enabled:
            state, detail = "inactif", ""
        elif problems:
            state, detail = "incomplet", "; ".join(problems)
        elif st.broken:
            state, detail = "panne", st.error
        elif st.error and st.consecutive:
            state, detail = "erreur", st.error
        elif st.listed:
            state, detail = "connecte", ""
        else:
            state, detail = "jamais", ""
        info = st.info
        reviews = {r: _review(r, v) for r, v in self._safe_reviews().get(server, {}).items()}
        episodes = tuple(k for k, on in (("conversation", spec.in_conversation), ("initiative", spec.in_initiative),
                                         ("travail", spec.in_work)) if on)
        address = spec.url.strip() if not spec.local else " ".join((spec.command, *spec.args)).strip()
        return ServerStatus(
            name=server, kind=spec.transport, enabled=spec.enabled, ready=not problems, state=state, detail=detail,
            purpose=spec.purpose, when_to_use=spec.when_to_use, address=address[:300], audience=spec.audience,
            episodes=episodes, in_hand=spec.in_hand,
            server_name=info.name if info else "", server_version=info.version if info else "",
            protocol=info.protocol if info else "", instructions=info.instructions if info else "",
            live=st.live, reviews=reviews, last_ok_at=st.last_ok_at, last_error_at=st.last_error_at,
            calls=st.calls, failures=st.failures, consecutive=st.consecutive, log=st.log)

    def keep(self, request: str, text: str) -> None:
        self._kept[request] = text
        while len(self._kept) > KEPT_MAX:
            self._kept.pop(next(iter(self._kept)))

    def take(self, request: str) -> str | None:
        return self._kept.pop(request, None)

    def failing(self) -> list[str]:
        """Les serveurs actifs en panne (la santé : dégradée)."""
        cfg = self._safe_config()
        return sorted(n for n, st in self._servers.items()
                      if st.broken and n in cfg.servers and cfg.servers[n].enabled)

    # ── joindre, lister, tester ──
    async def refresh(self, server: str | None = None) -> None:
        """Joindre et lister un serveur actif (ou tous) ; une panne est notée, jamais levée."""
        cfg = self._safe_config()
        names = [server] if server is not None else sorted(cfg.servers)
        for name in names:
            spec = cfg.servers.get(name)
            if spec is None or not spec.enabled or not spec.ready:
                continue
            try:
                await self._list(name, spec)
            except (McpError, McpRemoteError, OSError) as exc:
                self._fail(self._server(name), spec, exc)
        self._changed()

    async def test(self, server: str) -> tuple[bool, str]:
        """Rouvrir une session et lister ses outils, actif ou non (l'opérateur essaie avant d'activer)."""
        spec = self._safe_config().servers.get(server)
        if spec is None:
            return False, "Ce serveur n'existe pas."
        problems = spec.problems()
        if problems:
            return False, "Incomplet : " + "; ".join(problems) + "."
        st = self._server(server)
        await self._drop(st)
        started = time.monotonic()
        try:
            tools = await self._list(server, spec)
        except (McpError, McpRemoteError, OSError) as exc:
            self._fail(st, spec, exc)
            self._changed()
            return False, f"Injoignable : {_said(exc)}"
        self._changed()
        took = (time.monotonic() - started) * 1000
        s = self.status(server)
        info = st.info
        who = f"{info.name} {info.version}".strip() if info else "le serveur"
        extra = []
        if s is not None and s.new:
            extra.append(f"{len(s.new)} à regarder")
        if s is not None and s.changed:
            extra.append(f"{len(s.changed)} changé(s) depuis ton accord, suspendu(s)")
        if s is not None and s.missing:
            extra.append(f"{len(s.missing)} approuvé(s) qu'il ne propose plus")
        more = f" ({', '.join(extra)})" if extra else ""
        return True, (f"Joint en {took:.0f} ms : {who} (protocole {info.protocol if info else '?'}), "
                      f"{len(tools)} outil(s){more}.")

    async def reconfigure(self) -> None:
        """Après un changement de réglages : fermer les sessions dont la connexion a changé (ou dont le serveur
        n'existe plus), puis rejoindre les serveurs actifs qui n'en ont pas."""
        cfg = self._safe_config()
        for name, st in list(self._servers.items()):
            spec = cfg.servers.get(name)
            if spec is None or not spec.enabled or spec.connection() != st.conn:
                await self._drop(st)
                st.listed, st.live, st.broken, st.consecutive, st.error = False, (), False, 0, ""
                if spec is None:
                    self._servers.pop(name, None)
        self._changed()
        self._spawn(self.refresh())

    async def _list(self, name: str, spec: McpServer) -> list[LiveTool]:
        st = self._server(name)
        session = await self._ensure(st, spec)
        try:
            tools = await session.list_tools(spec.timeout_s)
        except SessionExpired:
            await self._drop(st)
            session = await self._ensure(st, spec)
            tools = await session.list_tools(spec.timeout_s)
        st.live, st.listed = tuple(tools), True
        st.error, st.consecutive, st.broken = "", 0, False
        st.last_ok_at = self._now()
        return tools

    async def _ensure(self, st: _Server, spec: McpServer) -> McpSession:
        async with st.lock:
            conn = spec.connection()
            if st.session is not None and st.conn == conn:
                return st.session
            await self._drop(st)
            session = McpSession(self._connect(st.name, spec))
            try:
                st.info = await session.initialize(spec.timeout_s)
            except BaseException:
                tail = getattr(session.transport, "stderr_tail", None)
                if callable(tail):  # un serveur local qui tombe au démarrage : ce qu'il a dit en tombant
                    st.log = tuple(tail(8))
                await _quiet_close(session)
                raise
            st.session, st.conn = session, conn
            return session

    async def _drop(self, st: _Server) -> None:
        session, st.session = st.session, None
        if session is not None:
            await _quiet_close(session)

    # ── appeler ──
    async def call(self, server: str, remote: str, args: Mapping[str, Any], *,
                   timeout_s: float | None = None) -> CallResult:
        spec = self._safe_config().servers.get(server)
        st = self._servers.get(server)
        if spec is None or not spec.enabled or not spec.ready or st is None or st.broken:
            return CallResult(False, UNAVAILABLE, reached=False)
        timeout = timeout_s or spec.timeout_s
        st.calls += 1
        for attempt in (0, 1):
            try:
                session = await self._ensure(st, spec)
                out = await session.call_tool(remote, args, timeout)
            except SessionExpired:
                await self._drop(st)
                if attempt == 0:
                    continue  # la requête n'a pas été traitée : une session neuve, une fois
                self._fail(st, spec, McpError("la session a expiré deux fois"))
                self._changed()
                return CallResult(False, UNAVAILABLE, reached=False)
            except McpRemoteError as exc:
                st.failures += 1
                st.consecutive, st.last_ok_at = 0, self._now()
                return CallResult(False, f"Le service a refusé : {_said(exc)}", reached=True)
            except (McpError, OSError) as exc:
                self._fail(st, spec, exc)
                self._changed()
                return CallResult(False, f"Le service n'a pas répondu : {_said(exc)}", reached=False)
            st.consecutive, st.last_ok_at = 0, self._now()
            if out.is_error:
                st.failures += 1
            return CallResult(not out.is_error, out.text, reached=True)
        return CallResult(False, UNAVAILABLE, reached=False)

    # ── les décisions de l'opérateur ──
    async def review(self, server: str, remote: str, *, enabled: bool, nature: str, approval: str,
                     description: str, by: str) -> ToolReview:
        """Approuver (ou désactiver) un outil tel que le serveur le propose maintenant : c'est cet instantané-là
        qui sera servi ; s'il change, l'outil est suspendu jusqu'à un nouvel accord."""
        if not valid_choice(nature, NATURES) or not valid_choice(approval, APPROVALS):
            raise ValueError("nature ou accord inconnus")
        reviews = self._safe_reviews()
        current = reviews.get(server, {}).get(remote)
        st = self._servers.get(server)
        tool = next((t for t in (st.live if st else ()) if t.remote == remote), None)
        if tool is None and (enabled or current is None):
            raise ValueError("le serveur ne propose pas cet outil en ce moment : teste-le d'abord")
        if tool is not None:
            stored = StoredReview(fingerprint=tool.fingerprint, enabled=enabled, nature=nature, approval=approval,
                                  description=inert(description, MAX_DESCRIPTION), server_description=tool.description,
                                  title=tool.title, schema=dict(tool.schema), by=by, at=self._now())
        else:
            assert current is not None
            stored = current.model_copy(update={"enabled": False, "by": by, "at": self._now()})
        updated = {s: dict(v) for s, v in reviews.items()}
        updated.setdefault(server, {})[remote] = stored
        await self._save_reviews(updated)
        self._changed()
        return _review(remote, stored)

    def open_transport(self, name: str, spec: McpServer) -> Transport:
        """Le transport d'un serveur : à une adresse (HTTP), ou lancé ici dans sa cage (stdio)."""
        if not spec.local:
            return HttpTransport(spec.url.strip(), headers=spec.headers(), verify=spec.ca_file.strip() or True)
        if self.launcher is None:
            raise McpError("pas de dossier pour les serveurs lancés ici")
        argv, env, cwd = self.launcher.command(name, spec)
        secrets = tuple(v for v in (spec.token, *spec.secret_vars().values()) if v)
        return StdioTransport(argv, env, cwd, preexec=self.launcher.limiter(), secrets=secrets)

    # ── détails ──
    def _server(self, name: str) -> _Server:
        st = self._servers.get(name)
        if st is None:
            st = self._servers[name] = _Server(name)
        return st

    def _fail(self, st: _Server, spec: McpServer, exc: BaseException) -> None:
        tail = getattr(st.session.transport, "stderr_tail", None) if st.session is not None else None
        if callable(tail):
            st.log = tuple(tail(8))
        st.error = _said(exc)
        st.last_error_at = self._now()
        st.failures += 1
        st.consecutive += 1
        if st.consecutive >= spec.breaker and not st.broken:
            st.broken = True
            log.warning("mcp : %s coupé après %d pannes d'affilée (%s)", st.name, st.consecutive, st.error)
        # la session est détachée tout de suite (l'appel suivant en rouvre une), fermée en arrière-plan
        session, st.session = st.session, None
        if session is not None:
            self._spawn(_quiet_close(session))

    def _changed(self) -> None:
        """Prévenir (une fois par changement réel de l'offre) : le noyau recalcule ses outils."""
        key = tuple((t.name, t.server, t.remote, t.description, t.approval, t.nature, tuple(sorted(t.episodes)),
                     t.audience, t.in_hand) for t in self.offered())
        if key == self._last_offer:
            return
        self._last_offer = key
        for fn in list(self._listeners):
            try:
                got = fn()
                if inspect.isawaitable(got):
                    self._spawn(got)
            except Exception:  # noqa: BLE001 — un auditeur en panne n'arrête pas les autres
                log.exception("mcp : un auditeur de changement a échoué")

    def _spawn(self, aw: Awaitable[Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            if inspect.iscoroutine(aw):
                aw.close()
            return
        task = loop.create_task(aw)  # type: ignore[arg-type]
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _safe_config(self) -> McpConfig:
        try:
            return self._config()
        except Exception:  # noqa: BLE001 — des réglages illisibles : aucun serveur, jamais une panne
            log.exception("mcp : réglages illisibles")
            return McpConfig()

    def _safe_reviews(self) -> Reviews:
        try:
            return self._reviews()
        except Exception:  # noqa: BLE001
            log.exception("mcp : décisions illisibles")
            return {}




def _review(remote: str, v: StoredReview) -> ToolReview:
    return ToolReview(remote=remote, fingerprint=v.fingerprint, enabled=v.enabled, nature=v.nature,
                      approval=v.approval, description=v.description, server_description=v.server_description,
                      title=v.title, schema=v.schema_, by=v.by, at=v.at)


def _said(exc: BaseException) -> str:
    return (str(exc) or type(exc).__name__)[:300]


async def _quiet_close(session: McpSession) -> None:
    try:
        await asyncio.wait_for(session.aclose(), 3.0)
    except Exception:  # noqa: BLE001 — fermer ne doit jamais rien casser
        pass
