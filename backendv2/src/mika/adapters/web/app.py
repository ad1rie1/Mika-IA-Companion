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
L'application du téléphone (ADR 0062) obtient le sien par identifiant et mot de
passe (``POST /auth/token``, refusé à un navigateur), le rend en partant
(``DELETE /auth/token``), et le présente aussi aux routes HTTP qui lisent un
compte (``/auth/whoami``, ``/files/…``) — jamais à côté d'une ``Origin``. Elle dit
où la notifier quand elle est fermée (``POST /auth/push`` : son jeton Firebase et la
clé qui scelle, ADR 0077), et cesse de le vouloir par ``DELETE /auth/push``.

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
import hashlib
import hmac
import json
import logging
import secrets
import time
from collections import deque
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

from mika.adapters.push import key_from
from mika.adapters.push.fcm import MAX_DEVICE_TOKEN
from mika.adapters.web import protocol
from mika.adapters.web.accounts import (
    CLIENT_MOBILE,
    CLIENT_SCREEN,
    SOURCE_LOGIN,
    TOKEN_CLIENTS,
    TOKEN_KEY,
    Account,
    Accounts,
    password_problems,
)
from mika.adapters.web.hub import WS_UNAUTHORIZED, Conn, Hub
from mika.contracts.entry import MindPort
from mika.contracts.presence import Connected
from mika.contracts.runtime import AttachmentMeta, PerceptionReceived
from mika.kernel.events import Content
from mika.ports import phone as phone_p
from mika.ports import teams as teams_p
from mika.ports import wakeup as wakeup_p
from mika.ports.preprocess import Perceived, Preprocessor, Upload, render
from mika.ports.shares import valid_id
from mika.vocab import privacy
from mika.vocab.people import clean_display_name, client_claim_allowed

log = logging.getLogger("mika.web")

SESSION_COOKIE = "sessionid"
CSRF_COOKIE = "csrftoken"
#: les origines du frontend en développement (Vite) ; ``--origin`` les remplace
DEV_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:4173", "http://127.0.0.1:4173")
#: au-delà, des messages attendent déjà leur tour sur cette connexion : refusé (« saturée »)
MAX_QUEUED_CHATS = 8
#: les fichiers qu'elle envoie : au plus tant de téléchargements par compte et par minute
FILES_RATE = (60, 60.0)
#: les sortes qu'un téléchargement peut annoncer telles quelles ; toute autre (du HTML, du SVG, un script…) part
#: en ``application/octet-stream`` : rien de ce qu'elle envoie ne s'exécute dans une page
SAFE_MIMES = frozenset({"text/plain", "text/markdown", "text/csv", "application/json", "image/png", "image/jpeg",
                        "image/webp", "image/gif", "application/pdf"})
#: le corps JSON d'une route ordinaire (connexion, premier compte, jeton, notifications, décision, appareil) : au
#: plus tant d'octets, 413 au-delà — ni Starlette ni uvicorn ne bornent un corps
BODY_MAX_BYTES = 64 * 1024
#: un appareil (``/api/perceptions``) : tant de signaux par fenêtre (secondes) ; les appareils retenus sont bornés
#: comme les adresses de ``LoginThrottle`` (un nom d'appareil se choisit librement)
SENSED_RATE = (30, 60.0)
#: les en-têtes qu'un mandataire pose ; sans ``--behind-proxy``, ils trahissent un mandataire non déclaré
PROXY_HEADERS = (b"x-forwarded-for", b"x-real-ip", b"forwarded", b"via")
_PROXY_SAID: set[str] = set()  # l'avertissement du mandataire non déclaré : une fois par processus
#: un réveil par API (ADR 0068) : la taille d'une requête au plus (le JSON d'un service, GitHub par exemple, ADR 0117),
#: et les échecs d'authentification tolérés par IP
WAKE_MAX_BYTES = 512 * 1024
WAKE_FAILURES = (20, 60.0)
#: ce que dit chaque issue d'un appel de réveil, en HTTP
WAKE_STATUS = {wakeup_p.ACCEPTED: 202, wakeup_p.IGNORED: 200, wakeup_p.UNKNOWN: 401, wakeup_p.DISABLED: 403,
               wakeup_p.INVALID: 400, wakeup_p.BUSY: 429, wakeup_p.REFUSED: 409}
#: ce que les services de webhooks envoient (ADR 0117), le premier présent l'emporte : la clé recopiée telle quelle
#: (le « secret token » de GitLab), la signature du corps par la clé, l'évènement, l'identifiant de la livraison (qui
#: sert de clé d'idempotence : une livraison rejouée rend le même appel)
WAKE_KEY_HEADERS = ("x-gitlab-token",)
WAKE_SIGNATURE_HEADERS = ("x-hub-signature-256", "x-gitea-signature", "x-forgejo-signature", "x-signature-256")
WAKE_EVENT_HEADERS = ("x-github-event", "x-gitea-event", "x-forgejo-event", "x-gitlab-event")
WAKE_DELIVERY_HEADERS = ("idempotency-key", "x-github-delivery", "x-gitea-delivery", "x-forgejo-delivery")


def first_header(headers: Any, names: tuple[str, ...], limit: int = 200) -> str:
    """Le premier de ces en-têtes qui est là, réduit à ses caractères imprimables et borné (vide : aucun)."""
    for name in names:
        value = "".join(ch for ch in (headers.get(name) or "") if ch.isprintable()).strip()
        if value:
            return value[:limit]
    return ""
#: l'extension Teams (ADR 0069) : la taille d'un lot au plus, les échecs de clé tolérés par IP, et chaque issue en HTTP
TEAMS_MAX_BYTES = 512 * 1024
#: un lot du téléphone (ADR 0120), au plus : 200 messages de 4 000 caractères
PHONE_MAX_BYTES = 2 * 1024 * 1024
PHONE_STATUS = {phone_p.ACCEPTED: 200, phone_p.FORBIDDEN: 403, phone_p.DISABLED: 403, phone_p.INVALID: 400,
                phone_p.BUSY: 429}
TEAMS_FAILURES = (20, 60.0)
TEAMS_STATUS = {teams_p.ACCEPTED: 200, teams_p.UNKNOWN: 401, teams_p.DISABLED: 403, teams_p.INVALID: 400,
                teams_p.BUSY: 429, teams_p.MISSING: 404, teams_p.CONFLICT: 409}
#: les origines d'une extension de navigateur : une page web ne peut pas s'en réclamer
EXTENSION_ORIGINS = ("chrome-extension://", "moz-extension://")


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


class PayloadTooLarge(Exception):
    """Un corps au-delà de sa borne : la route répond 413 (``too_large``, posé par ``create_app`` pour les routes
    ordinaires ; les portes des services le font elles-mêmes, avec leurs en-têtes)."""


async def read_bounded(request: Request, limit: int) -> bytes:
    """Le corps d'une requête, borné à ``limit`` octets : un ``Content-Length`` au-delà, ou un flux (un envoi par
    morceaux, sans longueur annoncée) qui le dépasse, lèvent ``PayloadTooLarge`` avant d'avoir tout gardé."""
    try:
        size = int(request.headers.get("content-length") or 0)
    except ValueError:
        size = 0
    if size > limit:
        raise PayloadTooLarge
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise PayloadTooLarge
        chunks.append(chunk)
    return b"".join(chunks)


async def too_large(request: Request, exc: Exception) -> Response:
    return JSONResponse({"error": "Requête trop grande."}, status_code=413, headers={"Cache-Control": "no-store"})


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


def from_this_machine(request: Request) -> bool:
    """La requête vient-elle de la machine du serveur (l'adresse que le serveur voit : derrière un mandataire déclaré,
    celle du client) ? Elle seule crée le premier compte sans le code de premier démarrage."""
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost")


def bootstrap_code_required(request: Request, cfg: WebConfig) -> bool:
    return bool(cfg.bootstrap_code) and not from_this_machine(request)


def _whoami(account: Account | None, cfg: WebConfig, accounts: Accounts, *, code_required: bool = False) -> dict[str, Any]:
    if account is None:
        needs = accounts.count() == 0
        return {"authenticated": False, "auth_required": cfg.auth_required, "needs_bootstrap": needs,
                "bootstrap_code_required": needs and code_required}
    return {
        "authenticated": True, "auth_required": cfg.auth_required, "needs_bootstrap": False,
        "bootstrap_code_required": False,
        "username": account.username, "display_name": account.display_name, "person_id": account.handle,
        "operator": account.operator,
    }


def native_token(headers: Any) -> str:
    """Le jeton porteur d'un client natif : seulement **sans** ``Origin`` (avec une, c'est un navigateur, et seule
    sa session compte — une page ne peut pas faire valoir un jeton volé à côté de ses cookies)."""
    if headers.get("origin") is not None:
        return ""
    return bearer(headers.get("authorization"))


def create_app(port: MindPort, accounts: Accounts, hub: Hub, cfg: WebConfig | None = None,
               lifespan: Any = None, extra_routes: Sequence[Any] = (),
               preprocess: Preprocessor | None = None, camera: Any = None,
               sensor_digest: Callable[[], str] | None = None, wakeup: wakeup_p.WakeGate | None = None,
               teams: teams_p.TeamsGate | None = None, push_ready: Callable[[], bool] | None = None,
               phone: phone_p.PhoneGate | None = None) -> Starlette:
    cfg = cfg or WebConfig()
    by_name = LoginThrottle(cfg.login_failures, cfg.login_window_s)
    by_ip = LoginThrottle(cfg.login_ip_failures, cfg.login_window_s)
    wake_failures = LoginThrottle(*WAKE_FAILURES)
    teams_failures = LoginThrottle(*TEAMS_FAILURES)
    accounts.on_revoke.append(lambda account_id: hub.revoke(account=account_id))
    accounts.on_token_revoke.append(lambda token_id: hub.revoke(session=f"{TOKEN_KEY}{token_id}"))

    def account_of(request: Request) -> Account | None:
        """Le compte d'une requête : son jeton de client natif (sans ``Origin``), sinon sa session. Les routes qui
        écrivent exigent en plus le jeton CSRF, qu'un client natif n'a pas : rien n'est élargi."""
        token = native_token(request.headers)
        if token:
            found = accounts.token(token)
            return found[0] if found is not None else None
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
        """Le JSON d'une route ordinaire, borné (``BODY_MAX_BYTES`` ; au-delà, ``PayloadTooLarge`` → 413) ;
        illisible, ou pas un objet : ``{}``."""
        try:
            data = json.loads(await read_bounded(request, BODY_MAX_BYTES) or b"{}")
        except (ValueError, RecursionError):
            return {}
        return data if isinstance(data, dict) else {}

    async def logged_in(request: Request, account: Account) -> Response:
        key = await accounts.open_session(account)
        response = JSONResponse(_whoami(account, cfg, accounts))
        response.set_cookie(SESSION_COOKIE, key, max_age=14 * 24 * 3600, httponly=True, samesite="lax",
                            secure=cfg.cookie_secure)
        return with_csrf(request, response)

    async def whoami(request: Request) -> Response:
        token = native_token(request.headers)
        if token:
            # un client natif : son jeton dit qui il est (rien de planté : il n'a pas de cookies)
            found = accounts.token(token)
            report = _whoami(found[0] if found else None, cfg, accounts)
            if found is not None:
                report |= {"client": accounts.token_client(found[1]), "token_id": found[1]}
            return JSONResponse(report, headers={"Cache-Control": "no-store"})
        return with_csrf(request, JSONResponse(_whoami(account_of(request), cfg, accounts,
                                                       code_required=bootstrap_code_required(request, cfg))))

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
        if bootstrap_code_required(request, cfg) and not hmac.compare_digest(str(data.get("code") or "").strip(),
                                                                             cfg.bootstrap_code):
            # depuis une autre machine : le code écrit au journal du serveur prouve qu'on est chez soi
            return JSONResponse({"error": "Le code de premier démarrage ne correspond pas : il est dans le journal "
                                          "du serveur."}, status_code=403)
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

    async def token_login(request: Request) -> Response:
        """L'application du téléphone se connecte : identifiant et mot de passe contre un jeton de client natif,
        montré une seule fois. Refusé à un navigateur (il a sa session) ; mêmes étranglements que ``/auth/login``."""
        if request.headers.get("origin") is not None:
            return JSONResponse({"error": "Un navigateur se connecte par sa session."}, status_code=403)
        data = await body(request)
        username = str(data.get("username") or "").strip()
        password = str(data.get("password") or "")
        client = str(data.get("client") or CLIENT_SCREEN)
        if not username or not password:
            return JSONResponse({"error": "Nom d'utilisateur et mot de passe requis."}, status_code=400)
        if client not in TOKEN_CLIENTS:
            return JSONResponse({"error": "Sorte de client inconnue (screen ou mobile)."}, status_code=400)
        ip = request.client.host if request.client else "?"
        keys = (f"ip:{ip}", f"ip:{ip}:nom:{username.lower()}")
        if by_ip.blocked(keys[0]) or by_name.blocked(keys[1]):
            return JSONResponse({"error": "Trop de tentatives."}, status_code=429, headers={"Retry-After": "60"})
        account = await accounts.verify(username, password)
        if account is None:
            by_ip.fail(keys[0])
            by_name.fail(keys[1])
            return JSONResponse({"error": "Identifiants invalides."}, status_code=401)
        label = str(data.get("label") or "")
        info, raw = await accounts.create_token(account.id, label, client=client, source=SOURCE_LOGIN)
        await accounts.prune_login_tokens(account.id)
        report = _whoami(account, cfg, accounts) | {"token": raw, "token_id": info.id, "client": info.client}
        return JSONResponse(report, headers={"Cache-Control": "no-store"})

    async def token_logout(request: Request) -> Response:
        """L'application rend son jeton en se déconnectant : il ne vaut plus rien, ses connexions se ferment."""
        found = accounts.token(native_token(request.headers))
        if found is None:
            return JSONResponse({"error": "Jeton invalide."}, status_code=401)
        await accounts.revoke_token(found[1])
        return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})

    def phone_of(request: Request) -> int | JSONResponse:
        """Le jeton de l'application du téléphone qui appelle (ADR 0077), sinon le refus à rendre."""
        if request.headers.get("origin") is not None:
            return JSONResponse({"error": "Un navigateur ne reçoit pas de notifications."}, status_code=403)
        found = accounts.token(native_token(request.headers))
        if found is None:
            return JSONResponse({"error": "Jeton invalide."}, status_code=401)
        if accounts.token_client(found[1]) != CLIENT_MOBILE:
            return JSONResponse({"error": "Seule l'application du téléphone reçoit des notifications."},
                                status_code=403)
        return found[1]

    async def push_register(request: Request) -> Response:
        """L'application dit où la notifier quand elle est fermée : son jeton Firebase et la clé (base64, 32 octets)
        qui scellera ce qui lui part. ``available`` : le serveur a une clé Firebase (sinon rien ne partira)."""
        token_id = phone_of(request)
        if isinstance(token_id, JSONResponse):
            return token_id
        data = await body(request)
        device = str(data.get("token") or "").strip()
        if not device or len(device) > MAX_DEVICE_TOKEN or any(c.isspace() for c in device):
            return JSONResponse({"error": "Jeton Firebase manquant ou illisible."}, status_code=400)
        key = str(data.get("key") or "").strip()
        try:
            key_from(key)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        await accounts.set_push(token_id, device, key)
        available = bool(push_ready()) if push_ready is not None else False
        return JSONResponse({"ok": True, "available": available}, headers={"Cache-Control": "no-store"})

    async def push_unregister(request: Request) -> Response:
        """L'application ne veut plus de notifications (ou se déconnecte sans rendre son jeton)."""
        token_id = phone_of(request)
        if isinstance(token_id, JSONResponse):
            return token_id
        await accounts.clear_push(token_id)
        return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})

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

    downloads: dict[int, protocol.RateLimiter] = {}

    async def shared_file(request: Request) -> Response:
        """Un fichier qu'elle a envoyé (ADR 0062) : à qui il est parti (un jeton de l'application, sans ``Origin`` ;
        sinon la session du navigateur). Inconnu ou pas à cette personne : le même 404 ; retiré : 410. Jamais
        rendu dans la page (``attachment``, ``nosniff``, bac à sable), et sous une sorte sûre seulement."""
        file = request.path_params["file"]
        if not valid_id(file):
            return JSONResponse({"error": "Fichier introuvable."}, status_code=404)
        account = account_of(request)
        if account is None:
            return JSONResponse({"error": "Authentification requise."}, status_code=401)
        limiter = downloads.get(account.id)
        if limiter is None:
            limiter = downloads[account.id] = protocol.RateLimiter(*FILES_RATE)
        if not limiter.allow():
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

    sensed = LoginThrottle(*SENSED_RATE)  # une fenêtre par appareil, autant d'appareils au plus que d'adresses

    async def perceptions(request: Request) -> Response:
        """Un appareil signale quelque chose : ``{"device", "text", "pertinence", "emotion", "sensitivity"}``.
        Un opérateur connecté (avec CSRF), ou un jeton porteur (``mika sensors token`` : seule son empreinte est
        gardée, celle du jeton présenté lui est comparée)."""
        expected = sensor_digest() if sensor_digest is not None else ""
        given = bearer(request.headers.get("authorization"))
        by_token = bool(expected) and bool(given) \
            and hmac.compare_digest(hashlib.sha256(given.encode()).hexdigest(), expected)
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

    async def wake(request: Request) -> Response:
        """Un réveil par API (ADR 0068, 0117) : ``{"text": "…", "context": …}`` ou le JSON d'un service ; sa clé en
        ``Authorization: Bearer`` (ou ``X-Gitlab-Token``), ou le corps signé par elle (``X-Hub-Signature-256``) ; une
        clé d'idempotence facultative (``Idempotency-Key``, sinon l'identifiant de la livraison). Réveil inconnu et
        mauvaise clé : le même 401 (et trop d'échecs d'une même adresse : 429) ; désactivé : 403 ; rien à lire :
        400 ; trop d'appels : 429 ; son projet n'est pas actif : 409 ; un « ping » : 200 ; reçu : 202. Rien n'est
        journalisé avant que la porte l'ait admis."""
        headers = {"Cache-Control": "no-store"}
        if wakeup is None:
            return JSONResponse({"error": "Les réveils par API ne sont pas branchés."}, status_code=404,
                                headers=headers)
        origin = request.headers.get("origin")
        if origin is not None and origin not in cfg.origins:
            return JSONResponse({"error": "Origine refusée."}, status_code=403, headers=headers)
        ip = request.client.host if request.client else "?"
        if wake_failures.blocked(f"ip:{ip}"):
            return JSONResponse({"error": "Trop de tentatives."}, status_code=429,
                                headers={**headers, "Retry-After": "60"})
        try:
            raw = await read_bounded(request, WAKE_MAX_BYTES)  # borné aussi sans Content-Length
        except PayloadTooLarge:
            return JSONResponse({"error": "Requête trop grande."}, status_code=413, headers=headers)
        try:
            data = json.loads(raw) if raw else None
        except (ValueError, RecursionError):  # illisible (et, selon la version de Python, trop imbriqué)
            data = None
        h = request.headers
        got = await wakeup(wakeup_p.WakeRequest(
            name=request.path_params["name"][:60], key=bearer(h.get("authorization")) or first_header(h, WAKE_KEY_HEADERS),
            body=raw, data=data, signature=first_header(h, WAKE_SIGNATURE_HEADERS),
            event=first_header(h, WAKE_EVENT_HEADERS, 60), idempotency=first_header(h, WAKE_DELIVERY_HEADERS)))
        if got.outcome == wakeup_p.UNKNOWN:
            wake_failures.fail(f"ip:{ip}")
        status = WAKE_STATUS.get(got.outcome, 400)
        if got.outcome == wakeup_p.BUSY and got.retry_after:
            headers["Retry-After"] = str(got.retry_after)
        if status in (200, 202):
            return JSONResponse({"ok": True, "call": got.call}, status_code=status, headers=headers)
        return JSONResponse({"error": got.message or "Refusé."}, status_code=status, headers=headers)

    async def teams_call(request: Request, kind: str) -> Response:
        """L'extension Teams (ADR 0069) : ``POST /api/teams/inbox`` (un lot de messages), ``GET /api/teams/outbox``
        (ce qui doit repartir), ``POST /api/teams/outbox/<id>`` (un accusé). Sa clé en ``Authorization: Bearer`` ;
        une origine d'extension, ou aucune (une page web, jamais). Clé absente ou fausse : le même 401 (et trop
        d'échecs d'une même adresse : 429) ; Teams désactivé : 403 ; requête illisible : 400 ; trop de requêtes :
        429 ; élément inconnu : 404 ; accusé impossible : 409. Rien n'est rangé avant que la porte l'ait admis."""
        headers = {"Cache-Control": "no-store"}
        if teams is None:
            return JSONResponse({"error": "Teams n'est pas branché."}, status_code=404, headers=headers)
        origin = request.headers.get("origin")
        if origin is not None and not origin.startswith(EXTENSION_ORIGINS) and origin not in cfg.origins:
            return JSONResponse({"error": "Origine refusée."}, status_code=403, headers=headers)
        ip = request.client.host if request.client else "?"
        if teams_failures.blocked(f"ip:{ip}"):
            return JSONResponse({"error": "Trop de tentatives."}, status_code=429,
                                headers={**headers, "Retry-After": "60"})
        key = bearer(request.headers.get("authorization"))
        if not key.startswith(teams_p.KEY_PREFIX) or len(key) > 200:  # sans clé valable, le corps n'est pas lu
            teams_failures.fail(f"ip:{ip}")
            return JSONResponse({"error": "Clé refusée."}, status_code=401, headers=headers)
        data: Any = {}
        if request.method == "POST":
            try:
                raw = await read_bounded(request, TEAMS_MAX_BYTES)  # borné aussi sans Content-Length
            except PayloadTooLarge:
                return JSONResponse({"error": "Requête trop grande."}, status_code=413, headers=headers)
            try:
                data = json.loads(raw or b"{}")
            except (ValueError, RecursionError):  # illisible (et, selon la version de Python, trop imbriqué)
                data = None
            if not isinstance(data, dict):
                return JSONResponse({"error": "Un objet JSON."}, status_code=400, headers=headers)
        if kind == "inbox":
            got = await teams.inbox(key, data)
        elif kind == "outbox":
            got = await teams.outbox(key)
        else:
            got = await teams.ack(key, request.path_params["item"][:40], data)
        if got.outcome == teams_p.UNKNOWN:
            teams_failures.fail(f"ip:{ip}")
        status = TEAMS_STATUS.get(got.outcome, 400)
        if got.outcome == teams_p.BUSY and got.retry_after:
            headers["Retry-After"] = str(got.retry_after)
        if status == 200:
            return JSONResponse({"ok": True, **got.data}, status_code=202 if kind == "inbox" else 200,
                                headers=headers)
        return JSONResponse({"error": got.message or "Refusé."}, status_code=status, headers=headers)

    async def teams_inbox(request: Request) -> Response:
        return await teams_call(request, "inbox")

    async def phone_call(request: Request, kind: str) -> Response:
        """L'application du téléphone (ADR 0120) : ``POST /api/phone/inbox`` (les messages qu'elle a lus dans ses
        notifications), ``POST /api/phone/settled`` (ce que sont devenues les réponses proposées). Sous son jeton
        (``mw_…``, client ``mobile``, sans ``Origin``) : jeton absent ou faux, 401 ; pas l'application du téléphone,
        pas une propriétaire, ou coupé, 403 ; illisible, 400 ; trop grand, 413 ; trop de requêtes ou pas prête, 429.
        Rien ne s'écrit avant que la porte l'ait admis."""
        headers = {"Cache-Control": "no-store"}
        if phone is None:
            return JSONResponse({"error": "Les messages du téléphone ne sont pas branchés."}, status_code=404,
                                headers=headers)
        token_id = phone_of(request)
        if isinstance(token_id, JSONResponse):
            return token_id
        found = accounts.token(native_token(request.headers))
        if found is None or not found[0].active:
            return JSONResponse({"error": "Jeton invalide."}, status_code=401, headers=headers)
        try:
            raw = await read_bounded(request, PHONE_MAX_BYTES)  # borné aussi sans Content-Length
        except PayloadTooLarge:
            return JSONResponse({"error": "Requête trop grande."}, status_code=413, headers=headers)
        try:
            data = json.loads(raw or b"{}")
        except (ValueError, RecursionError):
            data = None
        if not isinstance(data, dict):
            return JSONResponse({"error": "Un objet JSON."}, status_code=400, headers=headers)
        handle = found[0].handle
        got = await (phone.inbox(handle, data) if kind == "inbox" else phone.settled(handle, data))
        status = PHONE_STATUS.get(got.outcome, 400)
        if got.outcome == phone_p.BUSY and got.retry_after:
            headers["Retry-After"] = str(got.retry_after)
        if status == 200:
            return JSONResponse({"ok": True, **got.data}, headers=headers)
        return JSONResponse({"error": got.message or "Refusé."}, status_code=status, headers=headers)

    async def phone_inbox(request: Request) -> Response:
        return await phone_call(request, "inbox")

    async def phone_settled(request: Request) -> Response:
        return await phone_call(request, "settled")

    async def teams_outbox(request: Request) -> Response:
        return await teams_call(request, "outbox")

    async def teams_ack(request: Request) -> Response:
        return await teams_call(request, "ack")

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
            await _Session(websocket, port, hub, native, preprocess, accounts=accounts,
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
        Route("/auth/token", token_login, methods=["POST"]),
        Route("/auth/token", token_logout, methods=["DELETE"]),
        Route("/auth/push", push_register, methods=["POST"]),
        Route("/auth/push", push_unregister, methods=["DELETE"]),
        Route("/health", health, methods=["GET"]),
        Route("/api/projects/pending/{action_id:int}/{decision:str}", pending_decision, methods=["POST"]),
        Route("/api/perceptions", perceptions, methods=["POST"]),
        Route("/api/wake/{name:str}", wake, methods=["POST"]),
        Route("/api/teams/inbox", teams_inbox, methods=["POST"]),
        Route("/api/teams/outbox", teams_outbox, methods=["GET"]),
        Route("/api/teams/outbox/{item:str}", teams_ack, methods=["POST"]),
        Route("/api/phone/inbox", phone_inbox, methods=["POST"]),
        Route("/api/phone/settled", phone_settled, methods=["POST"]),
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


class _Session:
    """Une connexion WebSocket : son adresse, ses limites, son dialogue."""

    def __init__(self, websocket: WebSocket, port: MindPort, hub: Hub, account: Account | None,
                 preprocess: Preprocessor | None = None, *, accounts: Accounts | None = None,
                 session_key: str | None = None, channel: str = privacy.WEB, here: bool = True) -> None:
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
        #: le prochain rapprochement de la présence (aller : tout de suite ; partir : après la grâce)
        self._presence_task: asyncio.Future[Any] | None = None
        #: la prochaine écriture de ce qu'elle a lu, quand la fenêtre de ``PRESENCE_RATE`` est pleine
        self._read_task: asyncio.Future[Any] | None = None
        #: la prochaine écriture de la saisie, quand la fenêtre de ``COMPOSING_RATE`` est pleine ; et son plafond
        self._composing_task: asyncio.Future[Any] | None = None
        self._composing_cap: asyncio.Future[Any] | None = None
        kw: dict[str, Any] = {"session": session_key, "close": self.close, "valid": self._session_valid,
                              "channel": channel, "here": here}
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

    async def _arrive(self) -> None:
        """Quelqu'un est là, devant cet écran : c'est ce que sa présence (et le journal) en savent."""
        c = self.conn
        await self.port.connected(Connected(
            handle=c.handle, channel=c.channel, connection=c.id, authenticated=c.authenticated, account=c.account,
            operator=c.operator, display_name=c.display_name,
        ))
        c.announced = True

    async def _depart(self) -> None:
        c = self.conn
        c.announced = False
        # partie, elle n'écrit plus : la déconnexion clôt aussi sa saisie au journal (``presence``)
        c.composing = c.composing_said = False
        self._uncap_composing()
        await self.port.disconnected(c.handle, c.id)

    async def _refresh(self) -> None:
        # l'état intérieur tout de suite (sommeil, énergie, et où elle est dans sa chambre) : sans lui, un
        # écran qui s'ouvre la montrait au milieu de la pièce jusqu'au prochain changement d'état
        await self.hub.push_face(self.conn.handle, force=True)
        await self.hub.refresh_panels([self.conn.handle])
        await self.hub.push_approvals([self.conn.handle], if_any=True)

    async def announce(self) -> None:
        """Un écran qui s'ouvre : la présence, le fil initial, le visage, le panneau."""
        c = self.conn
        await self._arrive()
        await self.send(self.hub.history("initial", self.port.recent(c.handle, protocol.HISTORY_INITIAL),
                                         verdicts=self._judges()))
        await self._refresh()
        listed = getattr(self.port, "strands", None)
        if self._judges() and listed is not None:
            # ses fils de travail (ADR 0164), après le visage et le panneau : l'ouverture garde son ordre
            await self.send(protocol.strands(listed(c.handle)))

    async def run(self) -> None:
        try:
            if self.account is not None and self.conn.here:
                await self.announce()
            # ouverte en arrière-plan (ADR 0062) : rien de non sollicité, le client demande ce qu'il a manqué (sync)
            while not self._closed:
                raw = await self.ws.receive_text()
                await self.dispatch(raw)
        except (WebSocketDisconnect, RuntimeError):
            pass  # RuntimeError : la socket fermée par le serveur (révocation) pendant une lecture
        finally:
            if self._presence_task is not None:
                self._presence_task.cancel()
            if self._read_task is not None:
                self._read_task.cancel()  # le client redit ce qu'il a lu à sa prochaine connexion
            self._uncap_composing()  # la déconnexion clôt la saisie au journal
            if self._composing_task is not None:
                self._composing_task.cancel()
            self.hub.detach(self.conn)
            if self.conn.announced:
                await self.port.disconnected(self.conn.handle, self.conn.id)

    # ── aller et venir (ADR 0062) ──
    async def presence(self, frame: dict[str, Any]) -> None:
        """``{"type": "presence", "here": bool}`` : l'application passe au premier plan, ou le quitte. Revenir vaut
        tout de suite ; partir, après ``AWAY_GRACE_S`` (une photo prise et l'on revient : rien au journal)."""
        here = frame.get("here")
        if not isinstance(here, bool) or self.account is None:
            return
        c = self.conn
        was = c.here
        c.here = here
        if here:
            if self._presence_task is not None:
                self._presence_task.cancel()
                self._presence_task = None
            await self._reconcile()
            if not was:
                await self._refresh()  # l'écran revient : un visage et un panneau frais
        else:
            self._reconcile_after(protocol.AWAY_GRACE_S)

    def _reconcile_after(self, delay: float) -> None:
        if self._presence_task is not None:
            self._presence_task.cancel()
        self._presence_task = asyncio.ensure_future(self._reconcile_later(delay))

    async def _reconcile_later(self, delay: float) -> None:
        await asyncio.sleep(delay)
        self._presence_task = None
        try:
            await self._reconcile()
        except (WebSocketDisconnect, RuntimeError, OSError) as exc:
            log.debug("présence non rapprochée (%s) : %r", self.conn.id, exc)

    async def _reconcile(self) -> None:
        """Le journal suit ce que veut la connexion (``here``), au plus ``PRESENCE_RATE`` fois : au-delà, l'état
        voulu s'applique quand la fenêtre le permet — jamais perdu, jamais une rafale."""
        c = self.conn
        if self._closed or c.here == c.announced:
            return
        if not c.presence.allow(self.hub._monotonic()):
            n, window = protocol.PRESENCE_RATE
            self._reconcile_after(window / n)
            return
        if c.here:
            await self._arrive()
        else:
            await self._depart()

    # ── ce qu'elle a lu (« Lui dire quand j'ai lu ») ──
    async def read(self, frame: dict[str, Any]) -> None:
        """``{"type": "read", "up_to": n}`` : la personne a lu son fil jusqu'au message ``n`` (son application le
        dit, si elle l'a permis). Une connexion authentifiée seulement ; un numéro qui n'est pas dans son fil, ou
        qui n'avance pas ce qu'on sait déjà de cette adresse, est ignoré. Seule la dernière valeur compte."""
        up_to = frame.get("up_to")
        c = self.conn
        if self.account is None or not c.authenticated or isinstance(up_to, bool) or not isinstance(up_to, int):
            return
        if up_to <= max(c.read_up_to, self.hub.read_up_to.get(c.handle, 0)):
            return
        head = self.port.recent(c.handle, 1)
        if not head or up_to > head[-1].id:
            return  # pas un message de son fil (un curseur d'une autre vie, un numéro inventé)
        c.read_up_to = up_to
        await self._write_read()

    def _write_read_after(self, delay: float) -> None:
        if self._read_task is not None:
            self._read_task.cancel()
        self._read_task = asyncio.ensure_future(self._write_read_later(delay))

    async def _write_read_later(self, delay: float) -> None:
        await asyncio.sleep(delay)
        self._read_task = None
        try:
            await self._write_read()
        except (WebSocketDisconnect, RuntimeError, OSError) as exc:
            log.debug("lecture non écrite (%s) : %r", self.conn.id, exc)

    async def _write_read(self) -> None:
        """Au journal, au plus ``PRESENCE_RATE`` fois : au-delà, la dernière valeur voulue s'écrit quand la
        fenêtre le permet — jamais une rafale."""
        c = self.conn
        if self._closed or c.read_up_to <= self.hub.read_up_to.get(c.handle, 0):
            return
        if not c.reads.allow(self.hub._monotonic()):
            n, window = protocol.PRESENCE_RATE
            self._write_read_after(window / n)
            return
        self.hub.read_up_to[c.handle] = c.read_up_to
        await self.port.read(c.handle, c.read_up_to)

    # ── où elle est (« Lui dire où je suis », ADR 0119) ──
    async def where(self, frame: dict[str, Any]) -> None:
        """``{"type": "where", "lat", "lon", "accuracy", "label", "age_ms"}`` : où est la personne, d'après son
        téléphone (l'application ouverte, si elle l'a permis) ; ``{"type": "where", "off": true}`` : elle ne le
        permet plus, sa dernière position s'efface. Une connexion authentifiée seulement ; une position invalide est
        ignorée, une position qui n'a pas bougé (même lieu, moins de ``WHERE_STILL_M``) ne se réécrit qu'au bout de
        ``WHERE_REFRESH_S`` ; au plus ``WHERE_RATE`` écritures (au-delà, la suivante passera)."""
        c = self.conn
        if self.account is None or not c.authenticated or not self._session_valid():
            return
        if frame.get("off") is True:
            self.hub.located.pop(c.handle, None)
            await self.port.unlocate(c.handle)
            return
        fix = protocol.where_fix(frame)
        if fix is None:
            return
        now = self.hub._monotonic()
        last = self.hub.located.get(c.handle)
        if last is not None and last[0].label == fix.label and now - last[1] < protocol.WHERE_REFRESH_S \
                and protocol.where_moved(last[0], fix) < protocol.WHERE_STILL_M:
            return
        if not c.places.allow(now):
            return
        self.hub.located[c.handle] = (fix, now)
        await self.port.locate(c.handle, lat=fix.lat, lon=fix.lon, accuracy_m=fix.accuracy_m, label=fix.label,
                               age_ms=fix.age_ms)

    # ── en train d'écrire ──
    async def composing(self, frame: dict[str, Any]) -> None:
        """``{"type": "composing", "on": bool}`` : la personne commence à écrire un message sur cet écran, ou cesse
        (tout effacé, quelques secondes sans frappe — l'envoi, lui, la clôt de lui-même). Une connexion authentifiée
        et présente seulement. Tant qu'elle écrit, la réponse à son message d'avant attend la suite. Au journal, le
        début et la fin, au plus ``COMPOSING_RATE`` fois ; et jamais au-delà de ``COMPOSING_MAX_S`` de saisie
        continue : l'adaptateur en écrit lui-même la fin."""
        on = frame.get("on")
        c = self.conn
        if not isinstance(on, bool) or self.account is None or not c.announced:
            return
        if on and not c.composing:
            self._uncap_composing()
            self._composing_cap = asyncio.ensure_future(self._composing_capped(protocol.COMPOSING_MAX_S))
        elif not on:
            self._uncap_composing()
        c.composing = on
        await self._write_composing()

    def _uncap_composing(self) -> None:
        if self._composing_cap is not None:
            self._composing_cap.cancel()
            self._composing_cap = None

    async def _composing_capped(self, delay: float) -> None:
        """Le plafond d'une saisie continue : elle n'attend plus la suite."""
        await asyncio.sleep(delay)
        self._composing_cap = None
        self.conn.composing = False
        await self._settle_composing()

    def _write_composing_after(self, delay: float) -> None:
        if self._composing_task is not None:
            self._composing_task.cancel()
        self._composing_task = asyncio.ensure_future(self._write_composing_later(delay))

    async def _write_composing_later(self, delay: float) -> None:
        await asyncio.sleep(delay)
        self._composing_task = None
        await self._settle_composing()

    async def _settle_composing(self) -> None:
        try:
            await self._write_composing()
        except (WebSocketDisconnect, RuntimeError, OSError) as exc:
            log.debug("saisie non écrite (%s) : %r", self.conn.id, exc)

    async def _write_composing(self) -> None:
        """Le journal suit ce que dit la connexion (``composing``), au plus ``COMPOSING_RATE`` fois : au-delà, l'état
        voulu s'écrit quand la fenêtre le permet — jamais une rafale."""
        c = self.conn
        if self._closed or not c.announced or c.composing == c.composing_said:
            return
        if not c.typing.allow(self.hub._monotonic()):
            n, window = protocol.COMPOSING_RATE
            self._write_composing_after(window / n)
            return
        c.composing_said = c.composing
        await self.port.composing(c.handle, c.id, c.composing)

    async def dispatch(self, raw: str) -> None:
        self.conn.seen_at = self.hub._monotonic()  # n'importe quelle trame prouve la vie, même illisible
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
        elif kind == "presence":
            await self.presence(frame)
        elif kind == "composing":
            await self.composing(frame)
        elif kind == "read":
            if self.conn.control.allow():
                await self.read(frame)
        elif kind == "where":
            if self.conn.control.allow():
                await self.where(frame)
        elif kind == "approval":
            if self.conn.control.allow():
                await self.approval(frame)
        elif kind == "verdict":
            if self.conn.control.allow():
                await self.verdict(frame)
        elif kind == "strand":
            if self.conn.control.allow():
                await self.set_strand(frame)
        elif kind == "strand_history":
            if self.conn.control.allow():
                await self.strand_history(frame)
        elif kind == "chat":
            self.enqueue_chat(frame)

    async def approval(self, frame: dict[str, Any]) -> None:
        """Une carte d'accord décidée (ADR 0064) : par la personne à qui elle est adressée, connectée et
        authentifiée, telle qu'elle était montrée (``digest``). La réponse dit le sort ; la liste suit."""
        try:
            proposal = int(frame.get("id"))
        except (TypeError, ValueError):
            return
        decision = frame.get("decision")
        if decision not in ("accept", "refuse"):
            return
        if not self.conn.authenticated or self.account is None or not self._session_valid():
            await self.send({"type": "approval_result", "id": proposal, "status": "forbidden"})
            return
        decide = getattr(self.port, "decide_card", None)
        status = await decide(self.conn.handle, proposal, decision == "accept", str(frame.get("digest") or "")[:128]) \
            if decide is not None else "unknown"
        await self.send({"type": "approval_result", "id": proposal, "status": status})
        await self.hub.push_approvals([self.conn.handle])
        await self.hub.refresh_panels()

    async def set_strand(self, frame: dict[str, Any]) -> None:
        """Un fil de travail réglé depuis le chat (ADR 0164) : son titre, sa petite description, archivé ou non — le
        réglage entier. Par une opératrice connectée et authentifiée, pour ses propres fils. La réponse dit le sort ;
        la liste suit, à tous ses écrans."""
        strand = protocol.strand_id(frame.get("id"))
        if strand is None:
            return
        reply = {"type": "strand_result", "id": strand}
        if not self._judges() or self.account is None or not self._session_valid():
            await self.send(reply | {"status": "forbidden"})
            return
        title, description = frame.get("title"), frame.get("description")
        setter = getattr(self.port, "set_strand", None)
        status = await setter(self.conn.handle, strand, title=title if isinstance(title, str) else "",
                              description=description if isinstance(description, str) else "",
                              archived=frame.get("archived") is True) if setter is not None else "failed"
        await self.send(reply | {"status": status})
        if status == "ok":
            await self.hub.push_strands(self.conn.handle)

    async def strand_history(self, frame: dict[str, Any]) -> None:
        """Les messages d'un de ses fils de travail (ADR 0164), pour un écran qui l'ouvre sans les avoir : les plus
        récents avant ``before`` (tous s'il est absent). Une opératrice authentifiée seulement."""
        strand = protocol.strand_id(frame.get("id"))
        history = getattr(self.port, "strand_history", None)
        if strand is None or history is None or not self._judges() or not self._session_valid():
            return
        try:
            before = int(frame["before"]) if frame.get("before") is not None else None
        except (TypeError, ValueError):
            before = None
        rows, more = history(self.conn.handle, strand, before, protocol.HISTORY_MAX)
        await self.send(self.hub.history("strand", rows, life=self.hub.life(), verdicts=True)
                        | {"strand": strand, "more": more})

    def _judges(self) -> bool:
        """Une connexion d'opératrice, authentifiée : elle voit et donne son avis sur ses réponses (ADR 0113)."""
        return bool(self.conn.operator and self.conn.authenticated)

    async def verdict(self, frame: dict[str, Any]) -> None:
        """Une de ses réponses jugée depuis le chat (ADR 0113) : par une opératrice connectée et authentifiée
        seulement — ``verdict`` ``ok``, ``ko``, ou vide pour retirer l'avis ; ``comment`` : ce qu'elle aurait dû
        dire, ou pourquoi. La réponse dit le sort (``ok``, ``forbidden``, ``invalid``, ``failed``)."""
        try:
            seq = int(frame.get("message_id"))
        except (TypeError, ValueError):
            return
        verdict = frame.get("verdict") or ""
        if verdict not in ("ok", "ko", ""):
            return
        comment = str(frame.get("comment") or "")[:2000]
        reply = {"type": "verdict_result", "message_id": seq, "verdict": verdict}
        if not self._judges() or self.account is None or not self._session_valid():
            await self.send({**reply, "status": "forbidden"})
            return
        judge = getattr(self.port, "judge", None)
        status = await judge(self.conn.handle, seq, verdict, comment) if judge is not None else "failed"
        await self.send({**reply, "status": status, "comment": comment if status == "ok" else ""})

    def enqueue_chat(self, frame: dict[str, Any]) -> None:
        """Le chat avance dans sa propre tâche : la lecture des trames continue pendant
        qu'une pièce jointe se décrit (le client, sans pong, se reconnecterait). Ce qui attend
        devant lui se compte ici, à la réception : une rafale lue d'un trait crée toutes ses
        tâches avant qu'aucune ne démarre, et chacune, comptée à son premier pas, voyait la
        rafale entière — tous refusés, pas seulement les derniers."""
        # le message envoyé clôt la saisie : sa perception la clôt au journal, sans rien écrire de plus
        self.conn.composing = False
        self._uncap_composing()
        ahead = len(self._chats)
        task = asyncio.ensure_future(self._chat_in_turn(frame, ahead))
        self._chats.add(task)
        task.add_done_callback(self._chats.discard)

    async def _chat_in_turn(self, frame: dict[str, Any], ahead: int) -> None:
        cid = str(frame.get("client_msg_id") or "")[: protocol.MAX_CLIENT_MSG_ID]
        if ahead >= MAX_QUEUED_CHATS:
            await self._safe_send(protocol.ack(cid, "overloaded"))
            await self._settle_composing()  # refusé : la fin de sa saisie s'écrit
            return
        async with self._chat_lock:
            try:
                await self.chat(frame)
            except (WebSocketDisconnect, RuntimeError, OSError) as exc:  # la connexion est partie en route
                log.debug("message non accusé (%s) : %r", self.conn.id, exc)
        # refusé, la fin de sa saisie s'écrit ; reçu pendant qu'elle écrivait déjà la suite, son début
        await self._settle_composing()

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
        if not self._session_valid():  # avant tout historique : un identifiant qui ne vaut plus ne relit pas le fil
            await self.hub.revoke(session=self.session_key)
            return
        if not c.announced and c.here and self.account is None:
            await self.announce()
        try:
            after_id = max(0, int(frame.get("after_id") or 0))
        except (TypeError, ValueError):
            after_id = 0
        life = self.hub.life()
        if after_id:
            head = self.port.recent(c.handle, 1)
            if after_id > (head[-1].id if head else 0):
                # un curseur venu d'ailleurs (une vie restaurée plus ancienne, un fil oublié) : un
                # « rattrapage » vide le laisserait cacher tout ce qui est plus petit que lui — le fil initial
                # remplace ce que l'écran montre
                rows = self.port.recent(c.handle, protocol.HISTORY_INITIAL)
                await self.send(self.hub.history("initial", rows, life=life, reset=True, verdicts=self._judges()))
                return
            rows, truncated = self.port.after(c.handle, after_id, protocol.HISTORY_MAX)
        else:
            rows, truncated = self.port.recent(c.handle, protocol.HISTORY_INITIAL), False
        await self.send(self.hub.history("catchup", rows, after_id=after_id, truncated=truncated, life=life,
                                         verdicts=self._judges()))

    def _session_valid(self) -> bool:
        """Revérifiée à chaque message, avant chaque rattrapage, et par le concentrateur à chaque
        ``CREDENTIAL_CHECK_S`` : une session effacée ailleurs (un autre processus, une expiration), un
        jeton révoqué (``mika token revoke``) ou des droits changés ne parlent plus, ne relisent plus le
        fil, ne reçoivent plus rien — la règle de ``/ws/world`` (``Accounts.still_valid``)."""
        if self.session_key is None or self.accounts is None:
            return True
        return self.accounts.still_valid(self.session_key, operator=self.conn.operator)

    async def chat(self, frame: dict[str, Any]) -> None:
        c = self.conn
        cid = str(frame.get("client_msg_id") or "")[: protocol.MAX_CLIENT_MSG_ID]
        if not self._session_valid():
            await self.hub.revoke(session=self.session_key)
            return
        if not c.chat.allow():
            await self.send(protocol.ack(cid, "rate_limited"))
            return
        if not c.announced and c.here and self.account is None:
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
        # ses octets gardés avant que le message n'entre dans sa vie : il les désigne (ADR 0106)
        files = await self.port.keep_attachments(c.handle, [a.data for a in kept]) if kept else []
        body = "\n".join(x for x in [text, render(seen)] if x).strip()
        mode = protocol.chat_mode(frame.get("mode")) if self._judges() else ""
        perception = PerceptionReceived(
            handle=c.handle, channel=c.channel, text=Content.of(body), authenticated=c.authenticated,
            client_msg_id=cid or None, display_name=c.display_name,
            # le mode pro (ADR 0116) : demandé par une opératrice seulement ; ailleurs, la conversation ordinaire
            mode=mode,
            # son fil de travail (ADR 0164) : seulement en mode pro
            strand=protocol.strand_id(frame.get("strand")) if mode else None,
            # ce qu'elle a tapé est le début du texte ; la suite, ce que ses pièces jointes ont donné à percevoir
            # (pour le prompt) — le fil relu ne montre que le premier, et les fichiers par leur nom (G-6)
            typed_chars=len(text) if seen else None,
            attachments=tuple(AttachmentMeta(name=a.name, kind=a.kind, mime=a.mime, extracted=p.extracted,
                                             error=p.error, file=f)
                              for a, p, f in zip(kept, seen, files, strict=True)),
        )
        admission = await self.port.perceive(perception, dedupe_key=f"{c.handle}:{cid}" if cid else None)
        if admission.status == "accepted" and not admission.duplicate:
            c.composing_said = False  # sa perception a clos la saisie au journal (``presence``)
        await self.send(protocol.ack(cid, admission.status, rejected))
        if perception.strand is not None and admission.status == "accepted" and not admission.duplicate:
            await self.hub.push_strands(c.handle)  # un fil ouvert, ou qui avance (ADR 0164)
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
