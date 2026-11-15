"""La connexion du transport web : ``/auth/*``, et deux aides que les autres routes lisent.

Sécurité : jeton CSRF à double soumission (cookie ``csrftoken`` lisible, en-tête ``X-CSRFToken``) sur tout POST — et
sur la déconnexion, quelle que soit sa méthode ; session opaque en cookie ``HttpOnly`` (``adapters/web/session.py``).
L'application du téléphone (ADR 0062) obtient son jeton par identifiant et mot de passe (``POST /auth/token``, refusé
à un navigateur), le rend en partant (``DELETE /auth/token``), et le présente aussi aux routes HTTP qui lisent un
compte (``/auth/whoami``, ``/files/…``) — jamais à côté d'une ``Origin``. Elle dit où la notifier quand elle est fermée
(``POST /auth/push`` : son jeton Firebase et la clé qui scelle, ADR 0077), et cesse de le vouloir par
``DELETE /auth/push``.

Connexion : un seul scrypt par essai, compte connu ou non, et hors de la
boucle ; étranglement par adresse IP **et** par (IP, nom), mémoire purgée.

``auth_routes`` rend les huit routes de ``/auth/*``, que ``create_app`` (``adapters/web/app.py``) monte à leur place ;
``csrf_refused`` sert aussi ses routes ordinaires, ``phone_of`` les portes du téléphone (``adapters/web/doors.py``).
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from mika.adapters.push import key_from
from mika.adapters.push.fcm import MAX_DEVICE_TOKEN
from mika.adapters.web.accounts import (
    CLIENT_MOBILE,
    CLIENT_SCREEN,
    SOURCE_LOGIN,
    TOKEN_CLIENTS,
    Account,
    Accounts,
    password_problems,
)
from mika.adapters.web.body import json_fields
from mika.adapters.web.gate import SlidingWindow, same_secret
from mika.adapters.web.hub import Hub
from mika.adapters.web.session import CSRF_COOKIE, SESSION_COOKIE, account_of, csrf_header_ok, native_token

if TYPE_CHECKING:
    from mika.adapters.web.app import WebConfig


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


def csrf_refused() -> JSONResponse:
    return JSONResponse({"error": "Requête refusée (CSRF)."}, status_code=403)


def phone_of(request: Request, accounts: Accounts) -> tuple[Account, int] | JSONResponse:
    """Le compte (actif : ``Accounts.token``) et le jeton de l'application du téléphone qui appelle (ADR 0077,
    0120), lus une fois ; sinon le refus à rendre : une ``Origin`` ou un jeton d'un autre client, 403 ; pas de
    jeton valable, 401. Ces routes ne parlent pas toutes de notifications (``/auth/push``, ``/api/phone/…``) : le
    refus ne dit que qui elles admettent."""
    headers = {"Cache-Control": "no-store"}
    if request.headers.get("origin") is not None:
        return JSONResponse({"error": "Réservé à l'application du téléphone."}, status_code=403, headers=headers)
    found = accounts.token(native_token(request.headers))
    if found is None:
        return JSONResponse({"error": "Jeton invalide."}, status_code=401, headers=headers)
    if accounts.token_client(found[1]) != CLIENT_MOBILE:
        return JSONResponse({"error": "Réservé à l'application du téléphone."}, status_code=403, headers=headers)
    return found


def auth_routes(cfg: WebConfig, accounts: Accounts, hub: Hub,
                push_ready: Callable[[], bool] | None) -> list[Route]:
    """Les huit routes de ``/auth/*``, dans l'ordre où ``create_app`` les monte ; chaque appel a ses deux fenêtres de
    connexion (par nom, par adresse), réglées par ``cfg``."""
    by_name = SlidingWindow(cfg.login_failures, cfg.login_window_s)
    by_ip = SlidingWindow(cfg.login_ip_failures, cfg.login_window_s)

    def with_csrf(request: Request, response: Response) -> Response:
        if not request.cookies.get(CSRF_COOKIE):
            response.set_cookie(CSRF_COOKIE, secrets.token_urlsafe(32), max_age=365 * 24 * 3600, httponly=False,
                                samesite="lax", secure=cfg.cookie_secure)
        return response

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
        return with_csrf(request, JSONResponse(_whoami(account_of(request, accounts), cfg, accounts,
                                                       code_required=bootstrap_code_required(request, cfg))))

    async def login(request: Request) -> Response:
        if not csrf_header_ok(request):
            return csrf_refused()
        data = await json_fields(request)
        username = str(data.get("username") or "").strip()
        ip = request.client.host if request.client else "?"
        keys = (f"ip:{ip}", f"ip:{ip}:nom:{username.lower()}")
        if by_ip.blocked(keys[0]) or by_name.blocked(keys[1]):
            return JSONResponse({"error": "Trop de tentatives."}, status_code=429, headers={"Retry-After": "60"})
        by_ip.fail(keys[0])  # compté d'avance, rendu s'il réussit : la vérification attend (scrypt)
        by_name.fail(keys[1])
        account = await accounts.verify(username, str(data.get("password") or ""))
        if account is None:
            return JSONResponse({"error": "Identifiants invalides."}, status_code=401)
        by_ip.forgive(keys[0])
        by_name.forgive(keys[1])
        return await logged_in(request, account)

    async def bootstrap(request: Request) -> Response:
        if not csrf_header_ok(request):
            return csrf_refused()
        if accounts.count() > 0:
            return JSONResponse({"error": "Un compte existe déjà : connecte-toi."}, status_code=409)
        data = await json_fields(request)
        if bootstrap_code_required(request, cfg) and not same_secret(str(data.get("code") or "").strip(),
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
        if not csrf_header_ok(request):
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
        data = await json_fields(request)
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
        by_ip.fail(keys[0])  # compté d'avance, rendu s'il réussit (comme ``login``)
        by_name.fail(keys[1])
        account = await accounts.verify(username, password)
        if account is None:
            return JSONResponse({"error": "Identifiants invalides."}, status_code=401)
        by_ip.forgive(keys[0])
        by_name.forgive(keys[1])
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

    async def push_register(request: Request) -> Response:
        """L'application dit où la notifier quand elle est fermée : son jeton Firebase et la clé (base64, 32 octets)
        qui scellera ce qui lui part. ``available`` : le serveur a une clé Firebase (sinon rien ne partira)."""
        found = phone_of(request, accounts)
        if isinstance(found, JSONResponse):
            return found
        data = await json_fields(request)
        device = str(data.get("token") or "").strip()
        if not device or len(device) > MAX_DEVICE_TOKEN or any(c.isspace() for c in device):
            return JSONResponse({"error": "Jeton Firebase manquant ou illisible."}, status_code=400)
        key = str(data.get("key") or "").strip()
        try:
            key_from(key)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        await accounts.set_push(found[1], device, key)
        available = bool(push_ready()) if push_ready is not None else False
        return JSONResponse({"ok": True, "available": available}, headers={"Cache-Control": "no-store"})

    async def push_unregister(request: Request) -> Response:
        """L'application ne veut plus de notifications (ou se déconnecte sans rendre son jeton)."""
        found = phone_of(request, accounts)
        if isinstance(found, JSONResponse):
            return found
        await accounts.clear_push(found[1])
        return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})

    return [
        Route("/auth/whoami", whoami, methods=["GET"]),
        Route("/auth/login", login, methods=["POST"]),
        Route("/auth/bootstrap", bootstrap, methods=["POST"]),
        Route("/auth/logout", logout, methods=["GET", "POST"]),
        Route("/auth/token", token_login, methods=["POST"]),
        Route("/auth/token", token_logout, methods=["DELETE"]),
        Route("/auth/push", push_register, methods=["POST"]),
        Route("/auth/push", push_unregister, methods=["DELETE"]),
    ]
