"""L'application web : l'assemblage de ses routes (``create_app``), sa configuration (``WebConfig``) et ses routes
ordinaires (``/health``, ``/api/…``, ``/files/…``, ``/ws``, ``/ws/camera``).

Où vit chaque sujet : la connexion (``/auth/*``) dans ``adapters/web/auth_routes.py`` ; les portes à clé (réveils,
Teams, téléphone, ADR 0213) dans ``adapters/web/doors.py`` ; le dialogue de ``/ws`` dans
``adapters/web/chat_session.py`` ; la lecture d'un corps dans ``adapters/web/body.py`` ; les cookies, le compte d'une
requête et le jeton CSRF dans ``adapters/web/session.py``. ``create_app`` les monte dans un seul ordre.

Sécurité, dans l'ordre où elle mord : CORS avec identifiants pour les seules
origines déclarées (y compris sur les erreurs) ; jeton CSRF à double
soumission (cookie ``csrftoken`` lisible, en-tête ``X-CSRFToken``) sur tout
POST — et sur la déconnexion, quelle que soit sa méthode ; session opaque en
cookie ``HttpOnly`` ; WebSocket refusé à une origine inconnue, et accepté
**puis** fermé en 4401 sans session quand l'authentification est exigée (c'est
ce que le client sait lire) — et dès que sa session est révoquée. Un client
natif (un écran, le téléphone, ADR 0051) n'a ni cookie ni ``Origin`` : il présente un
jeton de son compte (``Authorization: Bearer mw_…``), accepté **seulement sans**
``Origin`` (un navigateur ne peut pas poser cet en-tête sur un WebSocket).
"""

from __future__ import annotations

import base64
import binascii
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket, WebSocketDisconnect

from mika.adapters.web import protocol
from mika.adapters.web.accounts import CLIENT_MOBILE, TOKEN_KEY, Accounts
from mika.adapters.web.auth_routes import auth_routes, csrf_refused
from mika.adapters.web.body import PayloadTooLarge, json_fields, too_large
from mika.adapters.web.chat_session import ChatSession
from mika.adapters.web.doors import door_routes
from mika.adapters.web.gate import SlidingWindow, matches, token_digest
from mika.adapters.web.hub import WS_UNAUTHORIZED, Hub
from mika.adapters.web.session import SESSION_COOKIE, account_of, bearer, csrf_header_ok, native_token
from mika.contracts.entry import MindPort
from mika.ports import phone as phone_p
from mika.ports import teams as teams_p
from mika.ports import wakeup as wakeup_p
from mika.ports.preprocess import Preprocessor
from mika.ports.shares import valid_id
from mika.vocab import privacy
from mika.vocab.people import clean_display_name

log = logging.getLogger("mika.web")

#: les origines du frontend en développement (Vite) ; ``--origin`` les remplace
DEV_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:4173", "http://127.0.0.1:4173")
#: les fichiers qu'elle envoie : au plus tant de téléchargements par compte et par minute
FILES_RATE = (60, 60.0)
#: les sortes qu'un téléchargement peut annoncer telles quelles ; toute autre (du HTML, du SVG, un script…) part
#: en ``application/octet-stream`` : rien de ce qu'elle envoie ne s'exécute dans une page
SAFE_MIMES = frozenset({"text/plain", "text/markdown", "text/csv", "application/json", "image/png", "image/jpeg",
                        "image/webp", "image/gif", "application/pdf"})
#: un appareil (``/api/perceptions``) : tant de signaux par fenêtre (secondes) ; les appareils retenus sont bornés
#: comme les adresses d'une ``SlidingWindow`` (un nom d'appareil se choisit librement)
SENSED_RATE = (30, 60.0)
#: les en-têtes qu'un mandataire pose ; sans ``--behind-proxy``, ils trahissent un mandataire non déclaré
PROXY_HEADERS = (b"x-forwarded-for", b"x-real-ip", b"forwarded", b"via")
_PROXY_SAID: set[str] = set()  # l'avertissement du mandataire non déclaré : une fois par processus


def safe_mime(mime: str) -> str:
    base = str(mime or "").split(";", 1)[0].strip().lower()
    return base if base in SAFE_MIMES else "application/octet-stream"


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
    #: le code de premier démarrage (``app/server.py`` le tire et l'écrit au journal) : créer le premier compte depuis
    #: une autre machine que celle du serveur l'exige — le premier arrivé sur le réseau ne devient pas opérateur
    #: (audit du 2026-10-26) ; vide : pas de code (tests, un montage sans ``serve``)
    bootstrap_code: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class UndeclaredProxy:
    """Sans ``--behind-proxy``, une requête qui porte un en-tête de mandataire est dite une fois au journal (par
    processus) : derrière un mandataire non déclaré, l'étranglement par adresse verrait tous les clients en 127.0.0.1
    et les cookies partiraient sans ``Secure``."""

    def __init__(self, app: ASGIApp, cfg: WebConfig) -> None:
        self.app = app
        self.cfg = cfg

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and not self.cfg.behind_proxy and not _PROXY_SAID:
            names = {k for k, _ in scope.get("headers", ())}
            seen = [h.decode() for h in PROXY_HEADERS if h in names]
            if seen:
                _PROXY_SAID.add("proxy")
                log.warning("mandataire non déclaré : lance avec --behind-proxy (une requête de %s porte %s ; sans lui, "
                            "l'étranglement par adresse voit tout le monde ici et les cookies partent sans Secure)",
                            (scope.get("client") or ("?",))[0], ", ".join(seen))
        await self.app(scope, receive, send)


def create_app(port: MindPort, accounts: Accounts, hub: Hub, cfg: WebConfig | None = None,
               lifespan: Any = None, extra_routes: Sequence[Any] = (),
               preprocess: Preprocessor | None = None, camera: Any = None,
               sensor_digest: Callable[[], str] | None = None, wakeup: wakeup_p.WakeGate | None = None,
               teams: teams_p.TeamsGate | None = None, push_ready: Callable[[], bool] | None = None,
               phone: phone_p.PhoneGate | None = None) -> Starlette:
    cfg = cfg or WebConfig()
    accounts.on_revoke.append(lambda account_id: hub.revoke(account=account_id))
    accounts.on_token_revoke.append(lambda token_id: hub.revoke(session=f"{TOKEN_KEY}{token_id}"))

    async def health(request: Request) -> Response:
        """Une sonde : 200 quand elle peut répondre (même moins bien : ``degraded``),
        503 en démarrage ou en arrêt."""
        report = dict(port.health())
        return JSONResponse(report, status_code=200 if report["ready"] else 503,
                            headers={"Cache-Control": "no-store"})

    async def pending_decision(request: Request) -> Response:
        # un client natif pose lui-même cookie et en-tête : le double CSRF ne prouve rien pour lui, il n'écrit pas ici
        if native_token(request.headers) or not csrf_header_ok(request):
            return csrf_refused()
        account = account_of(request, accounts)
        if account is None:
            return JSONResponse({"error": "Authentification requise."}, status_code=401)
        if not account.operator:
            return JSONResponse({"error": "Réservé aux opérateurs."}, status_code=403)
        decision = request.path_params["decision"]
        if decision not in ("approve", "reject"):
            return JSONResponse({"error": "Décision inconnue (approve ou reject)."}, status_code=400)
        data = await json_fields(request)
        status = await port.resolve_effect(int(request.path_params["action_id"]), decision == "approve",
                                           by=account.handle, note=str(data.get("note") or "")[:500])
        if status == "unknown":
            return JSONResponse({"error": "Action inconnue ou déjà décidée."}, status_code=404)
        if status in ("changed", "blocked"):  # ce qui partirait n'est plus ce qui a été proposé
            return JSONResponse({"error": "Ce qui partirait a changé ou ne peut pas partir tel quel : décide depuis "
                                          "la console, qui le montre.", "status": status}, status_code=409)
        await hub.refresh_panels()  # chacun voit la file d'approbation à jour
        return JSONResponse({"ok": True, "status": status})

    downloads = SlidingWindow(*FILES_RATE)  # une fenêtre par compte

    async def shared_file(request: Request) -> Response:
        """Un fichier qu'elle a envoyé (ADR 0062) : à qui il est parti (un jeton de l'application, sans ``Origin`` ;
        sinon la session du navigateur) ; ou une pièce que ce compte a envoyée (ADR 0215). Inconnu ou pas à cette
        personne : le même 404 ; retiré : 410. Jamais rendu dans la page (``attachment``, ``nosniff``, bac à sable),
        et sous une sorte sûre seulement."""
        file = request.path_params["file"]
        if not valid_id(file):
            return JSONResponse({"error": "Fichier introuvable."}, status_code=404)
        account = account_of(request, accounts)
        if account is None:
            return JSONResponse({"error": "Authentification requise."}, status_code=401)
        if not downloads.allow(key=str(account.id), n=FILES_RATE[0]):
            return JSONResponse({"error": "Trop de téléchargements."}, status_code=429, headers={"Retry-After": "60"})
        got = await port.shared_file(file, handle=account.handle)
        if got is None:
            return JSONResponse({"error": "Fichier introuvable."}, status_code=404)
        if got.gone:
            return JSONResponse({"error": "Ce fichier a été retiré."}, status_code=410)
        name = "".join(ch for ch in got.name.replace("\\", "/").rsplit("/", 1)[-1] if ch.isprintable())[:200]
        return Response(got.data, media_type=safe_mime(got.mime), headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(name or "fichier", safe=""),
            "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
            "Content-Security-Policy": "sandbox; default-src 'none'"})

    sensed = SlidingWindow(*SENSED_RATE)  # une fenêtre par appareil, autant d'appareils au plus que d'adresses

    async def perceptions(request: Request) -> Response:
        """Un appareil signale quelque chose : ``{"device", "text", "pertinence", "emotion", "sensitivity"}``.
        Un opérateur connecté (avec CSRF), ou un jeton porteur (``mika sensors token`` : seule son empreinte est
        gardée, celle du jeton présenté lui est comparée)."""
        expected = sensor_digest() if sensor_digest is not None else ""
        given = bearer(request.headers.get("authorization"))
        by_token = bool(given) and matches(token_digest(given), expected)
        if not by_token:
            if not csrf_header_ok(request):
                return csrf_refused()
            account = account_of(request, accounts)
            if account is None:
                return JSONResponse({"error": "Authentification requise."}, status_code=401)
            if not account.operator:
                return JSONResponse({"error": "Réservé aux opérateurs."}, status_code=403)
        data = await json_fields(request)
        device = clean_display_name(str(data.get("device") or "appareil"), max_chars=40) or "appareil"
        text = str(data.get("text") or "").strip()
        if not text or len(text) > 400:
            return JSONResponse({"error": "Un texte, 400 caractères au plus."}, status_code=400)
        if sensed.blocked(device):
            return JSONResponse({"error": "Trop de signaux."}, status_code=429, headers={"Retry-After": "60"})
        sensed.fail(device)  # un signal de plus dans sa fenêtre
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
            # l'application du téléphone (ADR 0062) : une messagerie ; ouverte en arrière-plan, personne ne regarde
            channel = privacy.MOBILE if accounts.token_client(token_id) == CLIENT_MOBILE else privacy.WEB
            away = (websocket.headers.get(protocol.PRESENCE_HEADER) or "").strip().lower() == "away"
            await ChatSession(websocket, port, hub, native, preprocess, accounts=accounts,
                              session_key=f"{TOKEN_KEY}{token_id}", channel=channel, here=not away).run()
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
        session = ChatSession(websocket, port, hub, account, preprocess, accounts=accounts,
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
        *auth_routes(cfg, accounts, hub, push_ready),
        Route("/health", health, methods=["GET"]),
        Route("/api/projects/pending/{action_id:int}/{decision:str}", pending_decision, methods=["POST"]),
        Route("/api/perceptions", perceptions, methods=["POST"]),
        *door_routes(cfg, accounts, wakeup=wakeup, teams=teams, phone=phone),
        Route("/files/{file:str}", shared_file, methods=["GET"]),
        WebSocketRoute("/ws", ws),
        *extra_routes,
    ]
    middleware = [Middleware(UndeclaredProxy, cfg=cfg),
                  Middleware(CORSMiddleware, allow_origins=list(cfg.origins), allow_credentials=True,
                             allow_methods=["GET", "POST"], allow_headers=["content-type", "x-csrftoken",
                                                                           "authorization", "idempotency-key"])]
    return Starlette(routes=routes, middleware=middleware, lifespan=lifespan,
                     exception_handlers={PayloadTooLarge: too_large})
