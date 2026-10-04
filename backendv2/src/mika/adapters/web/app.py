"""L'application web : ``/auth/*``, ``/health``, ``/api/…`` et ``/ws``.

Sécurité, dans l'ordre où elle mord : CORS avec identifiants pour les seules
origines déclarées (y compris sur les erreurs) ; jeton CSRF à double
soumission (cookie ``csrftoken`` lisible, en-tête ``X-CSRFToken``) sur tout
POST — et sur la déconnexion, quelle que soit sa méthode ; session opaque en
cookie ``HttpOnly`` ; WebSocket refusé à une origine inconnue, et accepté
**puis** fermé en 4401 sans session quand l'authentification est exigée (c'est
ce que le client sait lire) — et dès que sa session est révoquée. Un client
natif (un moteur de jeu, ADR 0051) n'a ni cookie ni ``Origin`` : il présente un
jeton de son compte (``Authorization: Bearer mw_…``), accepté **seulement sans**
``Origin`` (un navigateur ne peut pas poser cet en-tête sur un WebSocket).

Connexion : un seul scrypt par essai, compte connu ou non, et hors de la
boucle ; étranglement par adresse IP **et** par (IP, nom), mémoire purgée.

Une connexion WebSocket lit ses trames sans jamais attendre un message en
cours de traitement : le chat (et le prétraitement de ses pièces jointes)
avance dans une tâche à part, un message après l'autre ; pings, accusés et
rattrapages restent libres.
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
from collections.abc import Callable, Sequence
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
from mika.adapters.web.accounts import TOKEN_KEY, Account, Accounts, password_problems
from mika.adapters.web.hub import WS_UNAUTHORIZED, Conn, Hub
from mika.contracts.entry import MindPort
from mika.contracts.presence import Connected
from mika.contracts.runtime import AttachmentMeta, PerceptionReceived
from mika.kernel.events import Content
from mika.ports.preprocess import Perceived, Preprocessor, Upload, render
from mika.vocab.people import clean_display_name, client_claim_allowed

log = logging.getLogger("mika.web")

SESSION_COOKIE = "sessionid"
CSRF_COOKIE = "csrftoken"
#: les origines du frontend en développement (Vite) ; ``--origin`` les remplace
DEV_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:4173", "http://127.0.0.1:4173")
#: au-delà, des messages attendent déjà leur tour sur cette connexion : refusé (« saturée »)
MAX_QUEUED_CHATS = 8


@dataclass(slots=True)
class WebConfig:
    auth_required: bool = True
    origins: Sequence[str] = DEV_ORIGINS
    cookie_secure: bool = False
    #: derrière un mandataire TLS (le serveur lit l'adresse du client dans ses en-têtes ; le MCP local est fermé)
    behind_proxy: bool = False
    #: échecs de connexion tolérés par (IP, nom) dans la fenêtre
    login_failures: int = 5
    #: échecs de connexion tolérés par IP, tous noms confondus, dans la fenêtre
    login_ip_failures: int = 20
    login_window_s: float = 60.0
    extra: dict[str, Any] = field(default_factory=dict)


class LoginThrottle:
    """Fenêtres glissantes d'échecs par clé ; les clés vides sont oubliées, et la
    mémoire est bornée (un balayage d'adresses ne la fait pas grossir sans fin)."""

    MAX_KEYS = 10_000

    def __init__(self, n: int, window: float, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        self.n = n
        self.window = window
        self._now = monotonic
        self._fails: dict[str, deque[float]] = {}

    def _prune(self, key: str, now: float) -> deque[float] | None:
        q = self._fails.get(key)
        if q is None:
            return None
        while q and now - q[0] >= self.window:
            q.popleft()
        if not q:
            del self._fails[key]
            return None
        return q

    def blocked(self, key: str) -> bool:
        q = self._prune(key, self._now())
        return q is not None and len(q) >= self.n

    def fail(self, key: str) -> None:
        now = self._now()
        if len(self._fails) >= self.MAX_KEYS:
            for k in list(self._fails):
                self._prune(k, now)
            while len(self._fails) >= self.MAX_KEYS:  # encore plein : les plus anciennes clés partent
                del self._fails[next(iter(self._fails))]
        self._fails.setdefault(key, deque()).append(now)

    def __len__(self) -> int:
        return len(self._fails)


def bearer(header: str | None) -> str:
    """Le jeton d'un en-tête ``Authorization: Bearer …`` (vide sans en-tête, ou pour un autre schéma)."""
    scheme, _, value = (header or "").strip().partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


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
    by_name = LoginThrottle(cfg.login_failures, cfg.login_window_s)
    by_ip = LoginThrottle(cfg.login_ip_failures, cfg.login_window_s)
    accounts.on_revoke.append(lambda account_id: hub.revoke(account=account_id))
    accounts.on_token_revoke.append(lambda token_id: hub.revoke(session=f"{TOKEN_KEY}{token_id}"))

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
        ip = request.client.host if request.client else "?"
        keys = (f"ip:{ip}", f"ip:{ip}:nom:{username.lower()}")
        if by_ip.blocked(keys[0]) or by_name.blocked(keys[1]):
            return JSONResponse({"error": "Trop de tentatives."}, status_code=429, headers={"Retry-After": "60"})
        account = await accounts.verify(username, str(data.get("password") or ""))
        if account is None:
            by_ip.fail(keys[0])
            by_name.fail(keys[1])
            return JSONResponse({"error": "Identifiants invalides."}, status_code=401)
        return await logged_in(request, account)

    async def bootstrap(request: Request) -> Response:
        if not csrf_ok(request):
            return csrf_refused()
        if accounts.count() > 0:
            return JSONResponse({"error": "Un compte existe déjà : connecte-toi."}, status_code=409)
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
            return JSONResponse({"error": "Un compte existe déjà : connecte-toi."}, status_code=409)
        return await logged_in(request, account)

    async def logout(request: Request) -> Response:
        """Le client l'appelle en GET avec l'en-tête CSRF (contrat inchangé) : la méthode
        reste permise, le jeton devient exigé — une image ou un lien d'une autre page
        ne déconnecte plus personne."""
        if not csrf_ok(request):
            return csrf_refused()
        key = request.cookies.get(SESSION_COOKIE)
        if key:
            await accounts.close_session(key)
            await hub.revoke(session=key)  # ses WebSockets ouvertes ne valent plus
        response = JSONResponse({"ok": True})
        response.delete_cookie(SESSION_COOKIE)
        return response

    async def health(request: Request) -> Response:
        """Une sonde : 200 quand elle peut répondre (même moins bien : ``degraded``),
        503 en démarrage ou en arrêt."""
        report = dict(port.health())
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
        token = bearer(websocket.headers.get("authorization"))
        if origin is None and token:
            # un client natif (ADR 0051) : pas d'Origin, un jeton de son compte. Un navigateur ne peut pas poser
            # cet en-tête sur un WebSocket : avec une Origin, seule la session compte.
            await websocket.accept()
            found = await accounts.use_token(token)
            if found is None:
                await websocket.close(code=WS_UNAUTHORIZED)
                return
            native, token_id = found
            await _Session(websocket, port, hub, native, preprocess, accounts=accounts,
                           session_key=f"{TOKEN_KEY}{token_id}").run()
            return
        if not origin or origin not in cfg.origins:
            await websocket.close(code=1008)
            return
        key = websocket.cookies.get(SESSION_COOKIE)
        account = accounts.session(key)
        await websocket.accept()
        if account is None and cfg.auth_required:
            await websocket.close(code=WS_UNAUTHORIZED)
            return
        session = _Session(websocket, port, hub, account, preprocess, accounts=accounts,
                           session_key=key if account is not None else None)
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
    """Une connexion WebSocket : son adresse, ses limites, son dialogue."""

    def __init__(self, websocket: WebSocket, port: MindPort, hub: Hub, account: Account | None,
                 preprocess: Preprocessor | None = None, *, accounts: Accounts | None = None,
                 session_key: str | None = None) -> None:
        self.ws = websocket
        self.port = port
        self.preprocess = preprocess
        self.hub = hub
        self.account = account
        self.accounts = accounts
        self.session_key = session_key
        self._lock = asyncio.Lock()
        #: un message à la fois, dans l'ordre (asyncio.Lock réveille dans l'ordre d'arrivée)
        self._chat_lock = asyncio.Lock()
        self._chats: set[asyncio.Future[Any]] = set()
        self._watchers: set[asyncio.Future[Any]] = set()
        self._closed = False
        kw: dict[str, Any] = {"session": session_key, "close": self.close}
        if account is not None:
            kw |= {"handle": account.handle, "authenticated": True, "account": account.id,
                   "operator": account.operator, "display_name": account.display_name}
        self.conn: Conn = hub.attach(self.send, **kw)

    async def send(self, frame: dict[str, Any]) -> None:
        async with self._lock:
            await self.ws.send_json(frame)

    async def close(self, code: int) -> None:
        """Fermée par le serveur (session révoquée) : le client lit 4401 et ne réessaie pas."""
        self._closed = True
        async with self._lock:
            await self.ws.close(code=code)

    async def announce(self) -> None:
        c = self.conn
        await self.port.connected(Connected(
            handle=c.handle, channel="web", connection=c.id, authenticated=c.authenticated, account=c.account,
            operator=c.operator, display_name=c.display_name,
        ))
        c.announced = True
        await self.send(protocol.history("initial", self.port.recent(c.handle, protocol.HISTORY_INITIAL),
                                         life=self.hub.life()))
        await self.hub.push_face(c.handle, force=True)
        # l'état intérieur tout de suite (sommeil, énergie, et où elle est dans sa chambre) : sans lui, un
        # écran qui s'ouvre la montrait au milieu de la pièce jusqu'au prochain changement d'état
        await self.hub.refresh_panels([c.handle])

    async def run(self) -> None:
        try:
            if self.account is not None:
                await self.announce()
            while not self._closed:
                raw = await self.ws.receive_text()
                await self.dispatch(raw)
        except (WebSocketDisconnect, RuntimeError):
            pass  # RuntimeError : la socket fermée par le serveur (révocation) pendant une lecture
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
            self.enqueue_chat(frame)

    def enqueue_chat(self, frame: dict[str, Any]) -> None:
        """Le chat avance dans sa propre tâche : la lecture des trames continue pendant
        qu'une pièce jointe se décrit (le client, sans pong, se reconnecterait)."""
        task = asyncio.ensure_future(self._chat_in_turn(frame))
        self._chats.add(task)
        task.add_done_callback(self._chats.discard)

    async def _chat_in_turn(self, frame: dict[str, Any]) -> None:
        cid = str(frame.get("client_msg_id") or "")[: protocol.MAX_CLIENT_MSG_ID]
        if len(self._chats) > MAX_QUEUED_CHATS:
            await self._safe_send(protocol.ack(cid, "overloaded"))
            return
        async with self._chat_lock:
            try:
                await self.chat(frame)
            except (WebSocketDisconnect, RuntimeError, OSError) as exc:  # la connexion est partie en route
                log.debug("message non accusé (%s) : %r", self.conn.id, exc)

    async def _safe_send(self, frame: dict[str, Any]) -> None:
        try:
            await self.send(frame)
        except (WebSocketDisconnect, RuntimeError, OSError) as exc:
            log.debug("envoi impossible sur %s : %r", self.conn.id, exc)

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
        if wanted != c.handle or not c.announced or name != c.display_name:
            # une autre adresse, ou un nouveau nom (le client renvoie identify quand on le change)
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
        life = self.hub.life()
        if after_id:
            head = self.port.recent(c.handle, 1)
            if after_id > (head[-1].id if head else 0):
                # un curseur venu d'ailleurs (l'ancien moteur, une vie restaurée plus ancienne, un fil oublié) : un
                # « rattrapage » vide le laisserait cacher tout ce qui est plus petit que lui — le fil initial
                # remplace ce que l'écran montre
                rows = self.port.recent(c.handle, protocol.HISTORY_INITIAL)
                await self.send(protocol.history("initial", rows, life=life, reset=True))
                return
            rows, truncated = self.port.after(c.handle, after_id, protocol.HISTORY_MAX)
        else:
            rows, truncated = self.port.recent(c.handle, protocol.HISTORY_INITIAL), False
        await self.send(protocol.history("catchup", rows, after_id=after_id, truncated=truncated, life=life))

    def _session_valid(self) -> bool:
        """Revérifiée à chaque message : une session effacée ailleurs (un autre processus,
        une expiration) ou un jeton révoqué (``mika token revoke``) ne parle plus."""
        if self.session_key is None or self.accounts is None:
            return True
        return self.accounts.credential(self.session_key) is not None

    async def chat(self, frame: dict[str, Any]) -> None:
        c = self.conn
        cid = str(frame.get("client_msg_id") or "")[: protocol.MAX_CLIENT_MSG_ID]
        if not self._session_valid():
            await self.hub.revoke(session=self.session_key)
            return
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
        self.hub.note_asked(c, cid)
        seen = await self._perceive(kept)
        body = "\n".join(x for x in [text, render(seen)] if x).strip()
        perception = PerceptionReceived(
            handle=c.handle, channel="web", text=Content.of(body), authenticated=c.authenticated,
            client_msg_id=cid or None, display_name=c.display_name,
            # ce qu'elle a tapé est le début du texte ; la suite, ce que ses pièces jointes ont donné à percevoir
            # (pour le prompt) — le fil relu ne montre que le premier, et les fichiers par leur nom (G-6)
            typed_chars=len(text) if seen else None,
            attachments=tuple(AttachmentMeta(name=a.name, kind=a.kind, mime=a.mime, extracted=p.extracted,
                                             error=p.error) for a, p in zip(kept, seen, strict=True)),
        )
        admission = await self.port.perceive(perception, dedupe_key=f"{c.handle}:{cid}" if cid else None)
        await self.send(protocol.ack(cid, admission.status, rejected))
        if admission.held:
            # elle dort : la réponse attend son réveil — « Mika écrit… » ne tourne pas pendant sa nuit
            await self.send(protocol.silence(c.handle, self.hub.face(c.handle), user_message_id=admission.seq,
                                             client_msg_id=cid or None, reason=protocol.ASLEEP))
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
        """Si la réponse échoue ou qu'elle choisit de se taire, la personne l'apprend
        (sinon « Mika écrit… » tourne pour rien)."""
        try:
            report = await admission.reply
        except Exception as exc:  # l'épisode a levé : même effet qu'un échec
            report = None
            detail = repr(exc)
        else:
            detail = str(getattr(report, "detail", ""))
        outcome = str(getattr(report, "outcome", "failed")) if report is not None else "failed"
        if outcome in protocol.FAILED_OUTCOMES or outcome == protocol.ABSTAINED_OUTCOME:
            await self.hub.settle_reply(self.conn.handle, admission.seq, cid, outcome, detail)
