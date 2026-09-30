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
import base64
import binascii
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
from mika.ports.preprocess import Perceived, Preprocessor, Upload, render
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
               lifespan: Any = None, extra_routes: Sequence[Any] = (),
               preprocess: Preprocessor | None = None, camera: Any = None,
               sensor_token: Any = None) -> Starlette:
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
        """Une sonde : 200 quand elle peut répondre (même moins bien : ``degraded``),
        503 en démarrage ou en arrêt."""
        report = port.health()
        return JSONResponse(report, status_code=200 if report["ready"] else 503,
                            headers={"Cache-Control": "no-store"})

    async def pending_decision(request: Request) -> Response:
        if not csrf_ok(request):
            return csrf_refused()
        account = account_of(request)
        if account is None:
            return JSONResponse({"error": "Authentification requise."}, status_code=401)
        if not account.operator:
            return JSONResponse({"error": "Réservé aux opérateurs."}, status_code=403)
        decision = request.path_params["decision"]
        if decision not in ("approve", "reject"):
            return JSONResponse({"error": "Décision inconnue (approve ou reject)."}, status_code=400)
        data = await body(request)
        status = await port.resolve_effect(int(request.path_params["action_id"]), decision == "approve",
                                           by=account.handle, note=str(data.get("note") or "")[:500])
        if status == "unknown":
            return JSONResponse({"error": "Action inconnue ou déjà décidée."}, status_code=404)
        if status in ("changed", "blocked"):  # ce qui partirait n'est plus ce qui a été proposé
            return JSONResponse({"error": "Ce qui partirait a changé ou ne peut pas partir tel quel : décide depuis "
                                          "la console, qui le montre.", "status": status}, status_code=409)
        await hub.refresh_panels()  # chacun voit la file d'approbation à jour
        return JSONResponse({"ok": True, "status": status})

    sensed: dict[str, deque[float]] = defaultdict(deque)

    async def perceptions(request: Request) -> Response:
        """Un appareil signale quelque chose : ``{"device", "text", "pertinence", "emotion", "sensitivity"}``.
        Un opérateur connecté (avec CSRF), ou un jeton porteur (``mika sensors token``)."""
        token = sensor_token() if sensor_token is not None else ""
        given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        by_token = bool(token) and bool(given) and secrets.compare_digest(token, given)
        if not by_token:
            if not csrf_ok(request):
                return csrf_refused()
            account = account_of(request)
            if account is None:
                return JSONResponse({"error": "Authentification requise."}, status_code=401)
            if not account.operator:
                return JSONResponse({"error": "Réservé aux opérateurs."}, status_code=403)
        data = await body(request)
        device = clean_display_name(str(data.get("device") or "appareil"), max_chars=40) or "appareil"
        text = str(data.get("text") or "").strip()
        if not text or len(text) > 400:
            return JSONResponse({"error": "Un texte, 400 caractères au plus."}, status_code=400)
        window = sensed[device]
        now = time.monotonic()
        while window and now - window[0] >= 60:
            window.popleft()
        if len(window) >= 30:
            return JSONResponse({"error": "Trop de signaux."}, status_code=429, headers={"Retry-After": "60"})
        window.append(now)
        try:
            pertinence = float(data.get("pertinence", 0.5))
            sensitivity = int(data.get("sensitivity", 1))
        except (TypeError, ValueError):
            return JSONResponse({"error": "pertinence (0–1) et sensitivity (0–3) sont des nombres."}, status_code=400)
        seq = await port.sense(device, text, pertinence=pertinence, emotion=str(data.get("emotion") or ""),
                               sensitivity=sensitivity)
        return JSONResponse({"ok": seq is not None, "seq": seq}, status_code=202)

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
        session = _Session(websocket, port, hub, account, preprocess)
        await session.run()

    async def camera_ws(websocket: WebSocket) -> None:
        """Un appareil envoie ses images : ``{"type": "frame", "mime": "image/jpeg", "data": base64}``.
        Réservé aux opérateurs ; une origine annoncée doit être connue (un appareil natif n'en a pas)."""
        origin = websocket.headers.get("origin")
        account = accounts.session(websocket.cookies.get(SESSION_COOKIE))
        if camera is None or (origin and origin not in cfg.origins):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        if account is None or not account.operator:
            await websocket.close(code=WS_UNAUTHORIZED)
            return
        device = clean_display_name(websocket.query_params.get("device") or "camera", max_chars=40) or "camera"
        try:
            while True:
                frame = await websocket.receive_json()
                if not isinstance(frame, dict) or frame.get("type") != "frame":
                    continue
                try:
                    data = base64.b64decode(str(frame.get("data") or "").split(",")[-1], validate=True)
                except (ValueError, binascii.Error):
                    continue
                ok = camera.put(device, str(frame.get("mime") or "image/jpeg")[:40], data)
                await websocket.send_json({"type": "ack", "ok": ok})
        except (WebSocketDisconnect, ValueError):
            return

    routes = [
        WebSocketRoute("/ws/camera", camera_ws),
        Route("/auth/whoami", whoami, methods=["GET"]),
        Route("/auth/login", login, methods=["POST"]),
        Route("/auth/bootstrap", bootstrap, methods=["POST"]),
        Route("/auth/logout", logout, methods=["GET", "POST"]),
        Route("/health", health, methods=["GET"]),
        Route("/api/projects/pending/{action_id:int}/{decision:str}", pending_decision, methods=["POST"]),
        Route("/api/perceptions", perceptions, methods=["POST"]),
        WebSocketRoute("/ws", ws),
        *extra_routes,
    ]
    middleware = [Middleware(CORSMiddleware, allow_origins=list(cfg.origins), allow_credentials=True,
                             allow_methods=["GET", "POST"], allow_headers=["content-type", "x-csrftoken",
                                                                           "authorization"])]
    return Starlette(routes=routes, middleware=middleware, lifespan=lifespan)


class _Session:
    """Une connexion WebSocket : sa poignée, ses limites, son dialogue."""

    def __init__(self, websocket: WebSocket, port: MindPort, hub: Hub, account: Account | None,
                 preprocess: Preprocessor | None = None) -> None:
        self.ws = websocket
        self.port = port
        self.preprocess = preprocess
        self.hub = hub
        self.account = account
        self._lock = asyncio.Lock()
        self._watchers: set[asyncio.Future[Any]] = set()
        kw: dict[str, Any] = {}
        if account is not None:
            kw = {"handle": account.handle, "authenticated": True, "account": account.id,
                  "operator": account.operator, "display_name": account.display_name}
        self.conn: Conn = hub.attach(self.send, **kw)

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
            self.hub.detach(self.conn)
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
        seen = await self._perceive(kept)
        body = "\n".join(x for x in [text, render(seen)] if x).strip()
        perception = PerceptionReceived(
            handle=c.handle, channel="web", text=Content.of(body), authenticated=c.authenticated,
            client_msg_id=cid or None, display_name=c.display_name,
            attachments=tuple(AttachmentMeta(name=a.name, kind=a.kind, mime=a.mime, extracted=p.extracted,
                                             error=p.error) for a, p in zip(kept, seen, strict=True)),
        )
        admission = await self.port.perceive(perception, dedupe_key=f"{c.handle}:{cid}" if cid else None)
        await self.send(protocol.ack(cid, admission.status, rejected))
        if admission.reply is not None:
            task = asyncio.ensure_future(self._watch(admission, cid or None))
            self._watchers.add(task)
            task.add_done_callback(self._watchers.discard)

    async def _perceive(self, kept: list[Any]) -> list[Perceived]:
        """Ce qu'elle perçoit des pièces jointes, au bord (avant d'entrer dans sa vie)."""
        if not kept:
            return []
        if self.preprocess is None:
            return [Perceived(a.name, a.kind, "reçu, mais je ne peux pas encore le lire", False) for a in kept]
        return await self.preprocess.perceive([Upload(a.name, a.mime, a.data) for a in kept])

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
