"""La porte de la console : se connecter, créer le compte opérateur tant qu'aucun n'existe, se déconnecter. Le freinage
des tentatives vit dans ``UI`` (``login_blocked``, ``login_failed``)."""

from __future__ import annotations

import hmac

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from mika.adapters.web.accounts import password_problems
from mika.inspector.ui import PREFIX, SESSION_COOKIE, UI, secure


class Auth:
    def __init__(self, ui: UI) -> None:
        self.ui = ui

    async def login(self, request: Request) -> Response:
        """La porte de la console. Sans aucun compte, elle crée le compte opérateur (le même chemin que
        ``/auth/bootstrap`` : mêmes règles de mot de passe, et seulement tant qu'aucun compte n'existe). Un compte
        du chat déjà connecté apprend que ce compte n'ouvre pas la console, au lieu d'être renvoyé ici sans un
        mot."""
        accounts = self.ui.deps.accounts
        if accounts.count() == 0:
            return await self._bootstrap(request)
        error, username = "", ""
        if request.method == "GET":
            current = accounts.session(request.cookies.get(SESSION_COOKIE))
            if current is not None and current.operator:
                return secure(RedirectResponse(PREFIX + "/", status_code=303))
            if current is not None:
                error = (f"Ce compte ({current.display_name or current.username}) n'ouvre pas la console : "
                         "demande à un opérateur, ou connecte-toi avec un compte opérateur.")
        if request.method == "POST":
            data = await self.ui.form(request)
            ip = request.client.host if request.client else "?"
            username = str((data or {}).get("username", "")).strip()[:200]
            if data is None:
                error = "Jeton de formulaire invalide : recharge la page."
            elif self.ui.login_blocked(ip, username):
                response = self.ui.bare(request, "login.html", "Connexion", status=429,
                                        error="Trop de tentatives : réessaie dans une minute.", username=username)
                response.headers["Retry-After"] = "60"
                return response
            else:
                acc = await self.ui.deps.accounts.verify(username, data.get("password", ""))
                if acc is None or not acc.operator:
                    self.ui.login_failed(ip, username)
                    error = "Identifiants invalides, ou compte non opérateur."
                else:
                    key = await self.ui.deps.accounts.open_session(acc)
                    response = RedirectResponse(PREFIX + "/", status_code=303)
                    response.set_cookie(SESSION_COOKIE, key, httponly=True, samesite="lax",
                                        secure=self.ui.cookie_secure)
                    return secure(response)
        return self.ui.bare(request, "login.html", "Connexion", error=error, username=username)

    async def _bootstrap(self, request: Request) -> Response:
        """Aucun compte encore : créer le compte opérateur, comme ``/auth/bootstrap`` (``password_problems``,
        ``Accounts.bootstrap`` qui refuse dès qu'un compte existe — deux onglets ne créent pas deux comptes)."""
        accounts = self.ui.deps.accounts
        error, username = "", ""
        # depuis une autre machine, le code de premier démarrage écrit au journal du serveur est exigé : le premier
        # arrivé sur le réseau ne devient pas opérateur (audit du 2026-10-26) ; la machine du serveur en est dispensée
        code_required = bool(self.ui.deps.bootstrap_code) and not _from_this_machine(request)
        if request.method == "POST":
            data = await self.ui.form(request)
            username = str((data or {}).get("username", "")).strip()[:150]
            password = str((data or {}).get("password", ""))
            if data is None:
                error = "Jeton de formulaire invalide : recharge la page."
            elif code_required and not hmac.compare_digest(str(data.get("code", "")).strip(),
                                                           self.ui.deps.bootstrap_code):
                error = "Le code de premier démarrage ne correspond pas (il est dans le journal du serveur)."
            elif not username:
                error = "Donne un identifiant."
            elif password != str(data.get("password2", "")):
                error = "Les deux mots de passe ne sont pas les mêmes."
            else:
                problems = password_problems(password, username)
                if problems:
                    error = " ".join(problems)
                else:
                    account = await accounts.bootstrap(username, password)
                    if account is None:  # créé entre-temps (un autre onglet) : se connecter, maintenant
                        return secure(RedirectResponse(PREFIX + "/connexion", status_code=303))
                    key = await accounts.open_session(account)
                    response = RedirectResponse(PREFIX + "/", status_code=303)
                    response.set_cookie(SESSION_COOKIE, key, httponly=True, samesite="lax",
                                        secure=self.ui.cookie_secure)
                    return secure(response)
        return self.ui.bare(request, "login.html", "Créer le compte opérateur", error=error, bootstrap=True,
                            code_required=code_required, username=username, status=400 if error else 200)

    async def logout(self, request: Request) -> Response:
        data = await self.ui.form(request)
        if data is not None:
            key = request.cookies.get(SESSION_COOKIE)
            if key:
                await self.ui.deps.accounts.close_session(key)
        response = RedirectResponse(PREFIX + "/connexion", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        return secure(response)


def _from_this_machine(request: Request) -> bool:
    """La requête vient-elle de la machine du serveur (boucle locale, l'adresse vue par le serveur — derrière un
    mandataire déclaré, celle du client) ?"""
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost")
