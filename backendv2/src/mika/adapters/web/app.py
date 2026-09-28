"""L'application web : ``/auth/*``, ``/health``, ``/api/…`` et ``/ws``.

Sécurité, dans l'ordre où elle mord : CORS avec identifiants pour les seules
origines déclarées (y compris sur les erreurs) ; jeton CSRF à double
soumission (cookie ``csrftoken`` lisible, en-tête ``X-CSRFToken``) sur tout
POST ; session opaque en cookie ``HttpOnly`` ; WebSocket refusé à une origine
inconnue, et accepté **puis** fermé en 4401 sans session quand
l'authentification est exigée (c'est ce que le client sait lire).
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from mika.adapters.web import protocol
from mika.adapters.web.accounts import Account, Accounts, password_problems
from mika.adapters.web.hub import Conn, Hub
from mika.contracts.entry import MindPort
from mika.contracts.presence import Connected
from mika.contracts.runtime import AttachmentMeta, PerceptionReceived
from mika.kernel.events import Content
from mika.vocab.people import clean_display_name, client_claim_allowed

log = logging.getLogger("mika.web")

SESSION_COOKIE = "sessionid"
CSRF_COOKIE = "csrftoken"
WS_UNAUTHORIZED = 4401


@dataclass(slots=True)
class WebConfig:
    auth_required: bool = True
    origins: Sequence[str] = ("http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:4173",
                              "http://127.0.0.1:4173")
    cookie_secure: bool = False
    login_failures: int = 5
    login_window_s: float = 60.0
    extra: dict[str, Any] = field(default_factory=dict)


class LoginThrottle:
    def __init__(self, n: int, window: float) -> None:
        self.n = n
        self.window = window
        self._fails: dict[str, deque[float]] = defaultdict(deque)

    def blocked(self, key: str) -> bool:
        q = self._fails[key]
        now = time.monotonic()
        while q and now - q[0] >= self.window:
            q.popleft()
        return len(q) >= self.n

    def fail(self, key: str) -> None:
        self._fails[key].append(time.monotonic())


def _whoami(account: Account | None, cfg: WebConfig, accounts: Accounts) -> dict[str, Any]:
    if account is None:
        return {"authenticated": False, "auth_required": cfg.auth_required, "needs_bootstrap": accounts.count() == 0}
    return {
        "authenticated": True, "auth_required": cfg.auth_required, "needs_bootstrap": False,
        "username": account.username, "display_name": account.display_name, "person_id": account.handle,
        "operator": account.operator,
    }


def create_app(port: MindPort, accounts: Accounts, hub: Hub, cfg: WebConfig | None = None,
               lifespan: Any = None, extra_routes: Sequence[Any] = ()) -> Starlette:
    cfg = cfg or WebConfig()
    throttle = LoginThrottle(cfg.login_failures, cfg.login_window_s)

    def account_of(request: Request) -> Account | None:
        return accounts.session(request.cookies.get(SESSION_COOKIE))

    def csrf_ok(request: Request) -> bool:
        cookie = request.cookies.get(CSRF_COOKIE, "")
        header = request.headers.get("x-csrftoken", "")
        return bool(cookie) and secrets.compare_digest(cookie, header)

    def with_csrf(request: Request, response: Response) -> Response:
        if not request.cookies.get(CSRF_COOKIE):
            response.set_cookie(CSRF_COOKIE, secrets.token_urlsafe(32), max_age=365 * 24 * 3600, httponly=False,
                                samesite="lax", secure=cfg.cookie_secure)
        return response

    def csrf_refused() -> JSONResponse:
        return JSONResponse({"error": "Requête refusée (CSRF)."}, status_code=403)

    async def body(request: Request) -> dict[str, Any]:
        try:
            data = json.loads(await request.body() or b"{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    async def logged_in(request: Request, account: Account) -> Response:
        key = await accounts.open_session(account)
        response = JSONResponse(_whoami(account, cfg, accounts))
        response.set_cookie(SESSION_COOKIE, key, max_age=14 * 24 * 3600, httponly=True, samesite="lax",
                            secure=cfg.cookie_secure)
        return with_csrf(request, response)

    async def whoami(request: Request) -> Response:
        return with_csrf(request, JSONResponse(_whoami(account_of(request), cfg, accounts)))

    async def login(request: Request) -> Response:
        if not csrf_ok(request):
            return csrf_refused()
        data = await body(request)
        username = str(data.get("username") or "").strip()
        key = f"{request.client.host if request.client else '?'}:{username.lower()}"
        if throttle.blocked(key):
            return JSONResponse({"error": "Trop de tentatives."}, status_code=429, headers={"Retry-After": "60"})
        account = accounts.authenticate(username, str(data.get("password") or ""))
        if account is None:
            throttle.fail(key)
            return JSONResponse({"error": "Identifiants invalides."}, status_code=401)
        return await logged_in(request, account)

    async def bootstrap(request: Request) -> Response:
        if not csrf_ok(request):
            return csrf_refused()
        if accounts.count() > 0:
            return JSONResponse({"error": "Un compte existe deja : connecte-toi."}, status_code=409)
        data = await body(request)
        username = str(data.get("username") or "").strip()
        password = str(data.get("password") or "")
        if not username:
            return JSONResponse({"error": "Nom d'utilisateur requis."}, status_code=400)
        problems = password_problems(password, username)
        if problems:
            return JSONResponse({"error": " ".join(problems)}, status_code=400)
        account = await accounts.bootstrap(username, password)
        if account is None:
            return JSONResponse({"error": "Un compte existe deja : connecte-toi."}, status_code=409)
        return await logged_in(request, account)

    async def logout(request: Request) -> Response:
        key = request.cookies.get(SESSION_COOKIE)
        if key:
            await accounts.close_session(key)
        response = JSONResponse({"ok": True})
        response.delete_cookie(SESSION_COOKIE)
        return response

    async def health(request: Request) -> Response:
        ready = port.ready()
        return JSONResponse({"status": "ok" if ready else "starting", "ready": ready},
                            status_code=200 if ready else 503)

    async def pending_decision(request: Request) -> Response:
        if not csrf_ok(request):
            return csrf_refused()
        account = account_of(request)
        if account is None:
            return JSONResponse({"error": "Authentification requise."}, status_code=401)
        if not account.operator:
            return JSONResponse({"error": "Réservé aux opérateurs."}, status_code=403)
        return JSONResponse({"error": "Action inconnue."}, status_code=404)

    async def ws(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        if not origin or origin not in cfg.origins:
            await websocket.close(code=1008)
            return
        account = accounts.session(websocket.cookies.get(SESSION_COOKIE))
        await websocket.accept()
        if account is None and cfg.auth_required:
            await websocket.close(code=WS_UNAUTHORIZED)
            return
        session = _Session(websocket, port, hub, account)
        await session.run()

    routes = [
        Route("/auth/whoami", whoami, methods=["GET"]),
        Route("/auth/login", login, methods=["POST"]),
        Route("/auth/bootstrap", bootstrap, methods=["POST"]),
        Route("/auth/logout", logout, methods=["GET", "POST"]),
        Route("/health", health, methods=["GET"]),
        Route("/api/projects/pending/{action_id:int}/{decision:str}", pending_decision, methods=["POST"]),
        WebSocketRoute("/ws", ws),
        *extra_routes,
    ]
    middleware = [Middleware(CORSMiddleware, allow_origins=list(cfg.origins), allow_credentials=True,
                             allow_methods=["GET", "POST"], allow_headers=["content-type", "x-csrftoken"])]
    return Starlette(routes=routes, middleware=middleware, lifespan=lifespan)


class _Session:
    """Une connexion WebSocket : sa poignée, ses limites, son dialogue."""

    def __init__(self, websocket: WebSocket, port: MindPort, hub: Hub, account: Account | None) -> None:
        self.ws = websocket
        self.port = port
        self.hub = hub
        self.account = account
        self._lock = asyncio.Lock()
        self._watchers: set[asyncio.Future[Any]] = set()
        kw: dict[str, Any] = {}
        if account is not None:
            kw = {"handle": account.handle, "authenticated": True, "account": account.id,
                  "operator": account.operator, "display_name": account.display_name}
        self.conn: Conn = hub.open(self.send, **kw)

    async def send(self, frame: dict[str, Any]) -> None:
        async with self._lock:
            await self.ws.send_json(frame)

    async def announce(self) -> None:
        c = self.conn
        await self.port.connected(Connected(
            handle=c.handle, channel="web", connection=c.id, authenticated=c.authenticated, account=c.account,
            operator=c.operator, display_name=c.display_name,
        ))
        c.announced = True
        await self.send(protocol.history("initial", self.port.recent(c.handle, protocol.HISTORY_INITIAL)))
        await self.hub.push_face(c.handle, force=True)

    async def run(self) -> None:
        try:
            if self.account is not None:
                await self.announce()
            while True:
                raw = await self.ws.receive_text()
                await self.dispatch(raw)
        except WebSocketDisconnect:
            pass
        finally:
            self.hub.close(self.conn)
            if self.conn.announced:
                await self.port.disconnected(self.conn.handle, self.conn.id)

    async def dispatch(self, raw: str) -> None:
        try:
            frame = json.loads(raw)
        except ValueError:
            return
        if not isinstance(frame, dict):
            return
        kind = frame.get("type")
        if kind == "ping":
            await self.send({"type": "pong", "t": frame.get("t")})
        elif kind == "identify":
            if self.conn.control.allow():
                await self.identify(frame)
        elif kind == "sync":
            if self.conn.control.allow():
                await self.sync(frame)
        elif kind == "chat":
            await self.chat(frame)

    async def identify(self, frame: dict[str, Any]) -> None:
        c = self.conn
        if c.authenticated:
            return  # la session fait foi : l'indice du client est ignoré
        wanted = frame.get("person_id")
        name = clean_display_name(frame.get("display_name"))
        if not isinstance(wanted, str) or not client_claim_allowed(wanted):
            if not c.announced:
                await self.announce()
            return
        if wanted != c.handle or not c.announced:
            if c.announced:
                await self.port.disconnected(c.handle, c.id)
                c.announced = False
            c.handle = wanted
            c.display_name = name
            await self.announce()

    async def sync(self, frame: dict[str, Any]) -> None:
        c = self.conn
        if not c.announced:
            await self.announce()
        try:
            after_id = max(0, int(frame.get("after_id") or 0))
        except (TypeError, ValueError):
            after_id = 0
        if after_id:
            rows, truncated = self.port.after(c.handle, after_id, protocol.HISTORY_MAX)
        else:
            rows, truncated = self.port.recent(c.handle, protocol.HISTORY_INITIAL), False
        await self.send(protocol.history("catchup", rows, after_id=after_id, truncated=truncated))

    async def chat(self, frame: dict[str, Any]) -> None:
        c = self.conn
        cid = str(frame.get("client_msg_id") or "")[: protocol.MAX_CLIENT_MSG_ID]
        if not c.chat.allow():
            await self.send(protocol.ack(cid, "rate_limited"))
            return
        if not c.announced:
            await self.announce()
        message = frame.get("message")
        text = message.strip() if isinstance(message, str) else ""
        kept, rejected = protocol.validate_attachments(frame.get("attachments"))
        if len(text) > protocol.MAX_MESSAGE_CHARS:
            await self.send(protocol.ack(cid, "too_long"))
            return
        if not text and not kept:
            await self.send(protocol.ack(cid, "attachments_rejected" if rejected else "empty", rejected))
            return
        notes = [f"[{a.name} : fichier reçu, que tu ne peux pas encore lire]" for a in kept]
        body = " ".join([text, *notes]).strip()
        perception = PerceptionReceived(
            handle=c.handle, channel="web", text=Content.of(body), authenticated=c.authenticated,
            client_msg_id=cid or None, display_name=c.display_name,
            attachments=tuple(AttachmentMeta(name=a.name, kind=a.kind, mime=a.mime) for a in kept),
        )
        admission = await self.port.perceive(perception, dedupe_key=f"{c.handle}:{cid}" if cid else None)
        await self.send(protocol.ack(cid, admission.status, rejected))
        if admission.reply is not None:
            task = asyncio.ensure_future(self._watch(admission, cid or None))
            self._watchers.add(task)
            task.add_done_callback(self._watchers.discard)

    async def _watch(self, admission: Any, cid: str | None) -> None:
        """Si la réponse échoue, la personne l'apprend (sinon elle attend pour rien)."""
        try:
            report = await admission.reply
        except Exception as exc:  # l'épisode a levé : même effet qu'un échec
            report = None
            detail = repr(exc)
        else:
            detail = str(getattr(report, "detail", ""))
        outcome = str(getattr(report, "outcome", "failed")) if report is not None else "failed"
        if outcome in protocol.FAILED_OUTCOMES:
            frame = protocol.fallback_speech(self.conn.handle, detail, user_message_id=admission.seq,
                                             client_msg_id=cid)
            await self.hub.send_to(self.conn.handle, frame)
