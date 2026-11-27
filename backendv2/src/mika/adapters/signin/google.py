"""Se connecter à un compte Google : OAuth 2 avec PKCE (RFC 7636 ; ADR 0309, 0318) — Google refuse le code d'appareil
pour la plupart de ses portées.

Se connecter n'est à aucun domaine : un agenda Google (``adapters/agenda/oauth.py::google_signin``) entre par ce
moteur, avec sa portée, sa route de retour, ses connexions, ses mots et ses erreurs ; un Drive y entrera de même.

- **L'application Google du serveur** (``GoogleApplication`` : un client « Application de bureau » d'un projet
  Google Cloud, son identifiant et son secret, réglés par un opérateur — un réglage du cadre, ``app/connections.py``) ;
  sans elle, se connecter est refusé en mots.
- **Le parcours a deux temps** : **commencer** (``start`` : l'adresse de consentement de Google, ``access_type=
  offline``, ``prompt=consent``, un ``state`` et un vérificateur PKCE gardés ici un quart d'heure, une redirection vers
  ``http://127.0.0.1:<port>/`` — Google accepte tout port en boucle locale pour un client de bureau —, que le
  navigateur ne peut pas ouvrir), puis **finir** (``finish`` : l'adresse entière de la page qui n'a pas pu s'ouvrir,
  ou son code seul, lu par ``pasted`` ; le ``state`` vérifié, le code échangé contre les jetons, la portée du domaine
  vérifiée — Google laisse décocher chaque case du consentement). Un client « Application Web »
  (``GoogleApplication.web``) redirige lui-même vers l'origine HTTPS du serveur (la route que le domaine donne,
  ``return_path``) : la même fin, sans rien coller. Qui a commencé (``who``) est le seul à pouvoir finir.
- **Ce qu'on garde** : le jeton de renouvellement (``Grant``), scellé par le domaine sous sa clé (``GrantStore``,
  ``grants.py``) ; le jeton d'accès en mémoire, renouvelé avant sa fin.
- **Un jeton refusé** (``invalid_grant`` : révoqué, expiré — une application en mode test ne le garde que sept
  jours —, l'accès retiré) n'est plus présenté : le compte est à reconnecter (l'erreur ``needed`` du domaine, en
  mots), jusqu'à une connexion neuve. Changer d'application demande de se reconnecter. Aucun jeton n'entre dans un
  journal ni dans un message.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx

from mika.adapters.signin.grants import Grant, GrantStore
from mika.ports.signin import SIGNED_IN, SIGNIN_NEEDED, SIGNIN_PENDING, SignIn

log = logging.getLogger("mika.agenda")

#: le délai d'un appel au point OAuth de Google (le même que celui de l'API des agendas, ``adapters/agenda/cloud.py``)
TIMEOUT = httpx.Timeout(30.0, connect=10.0)

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE = "https://oauth2.googleapis.com/revoke"
#: un parcours commencé se finit dans ce délai (µs) ; au plus tant à la fois
PENDING_US = 15 * 60 * 1_000_000
PENDING_MAX = 64
#: un jeton d'accès qui expire dans moins que ceci (µs) est renouvelé avant de servir
MARGIN_US = 300 * 1_000_000
#: une adresse collée, un code : au plus tant de caractères
PASTED_MAX, CODE_MAX = 4096, 512

_CLIENT_ID = re.compile(r"^[0-9]{6,30}-[0-9a-z]{8,64}\.apps\.googleusercontent\.com$")
_SECRET = re.compile(r"^[A-Za-z0-9_-]{8,128}$")

GOOGLE_NO_APPLICATION = ("aucune application Google sur ce serveur : un opérateur la règle (mika agenda google, ou "
                         "la console), puis on se connecte")
GOOGLE_REVOKED = ("à reconnecter : Google ne renouvelle plus l'accès (retiré depuis le compte Google, mot de passe "
                  "changé, ou une application Google en mode test, dont l'accès dure sept jours)")
GOOGLE_OTHER_APPLICATION = "à reconnecter : l'application Google du serveur a changé depuis la connexion"
GOOGLE_STALE = ("cette adresse ne vient pas d'une connexion commencée ici, ou elle a expiré : recommence « Se "
                "connecter à Google »")
GOOGLE_DECLINED = "la connexion a été refusée chez Google"


def _now_us() -> int:
    return time.time_ns() // 1000


def _port() -> int:
    return 49152 + secrets.randbelow(16384)


def google_client_id(client_id: str) -> str:
    """L'identifiant d'un client OAuth Google (``…-….apps.googleusercontent.com``), en minuscules ; vide : aucun.
    ``ValueError`` s'il n'en a pas la forme."""
    client_id = client_id.strip().lower()
    if client_id and not _CLIENT_ID.match(client_id):
        raise ValueError("l'application Google se donne par l'identifiant de son client OAuth, de la forme "
                         "123456789012-abc….apps.googleusercontent.com")
    return client_id


@dataclass(frozen=True, slots=True)
class GoogleApplication:
    """L'application Google du serveur : son client OAuth (identifiant et secret, jamais dans un ``repr``), et s'il est
    une « Application Web » (``web`` : il revient à l'origine HTTPS du serveur) plutôt qu'une « Application de
    bureau »."""

    client_id: str
    secret: str = field(repr=False)
    web: bool = False

    @classmethod
    def of(cls, client_id: str, secret: str, *, web: bool = False) -> GoogleApplication:
        """Vérifiée : ``ValueError`` si l'identifiant ou le secret n'en ont pas la forme."""
        client_id = google_client_id(client_id)
        if not client_id:
            raise ValueError("l'application Google se donne par l'identifiant de son client OAuth")
        secret = secret.strip()
        if not _SECRET.match(secret):
            raise ValueError("le secret du client Google (« GOCSPX-… ») manque, ou n'en a pas la forme")
        return cls(client_id, secret, web)


@dataclass(slots=True)
class _Pending:
    key: str
    who: str
    verifier: str
    redirect: str
    client_id: str
    url: str
    until: int


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def pasted(text: str) -> tuple[str, str, str]:
    """Ce qu'on a collé : l'adresse entière de la page de retour (son ``code``, son ``state``, son ``error``), ou le
    code seul. Rend (code, state, error)."""
    text = (text or "").strip()[:PASTED_MAX]
    if not text:
        return "", "", ""
    if "://" in text or text.startswith("?") or "code=" in text or "error=" in text:
        query = urlsplit(text).query if "://" in text else text.split("?", 1)[-1]
        found = dict(parse_qsl(query.split("#", 1)[0]))
        return found.get("code", "")[:CODE_MAX], found.get("state", "")[:200], found.get("error", "")[:80]
    return ("" if any(c.isspace() for c in text) else text[:CODE_MAX]), "", ""


def _google_refused(body: dict[str, Any]) -> str:
    """Un refus du point OAuth de Google, en mots (jamais un jeton)."""
    error = str(body.get("error") or "erreur")[:60]
    if error == "invalid_grant":
        return GOOGLE_REVOKED
    if error in ("invalid_client", "unauthorized_client", "deleted_client"):
        return f"Google refuse l'application Google de ce serveur ({error}) : identifiant ou secret à revoir"
    if error == "access_denied":
        return GOOGLE_DECLINED
    detail = str(body.get("error_description") or "").split("\n")[0].strip()
    return f"Google a refusé ({error}) : {detail[:200]}" if detail else f"Google a refusé ({error})"


class GoogleSignIn:
    """Les connexions Google des comptes d'un domaine (ses comptes d'agenda) : commencer (``start``), finir
    (``finish``), où elles en sont (``state``), le jeton d'accès d'un compte connecté (``token``), l'oublier
    (``drop``), la retirer chez Google (``revoke``). Le domaine dit sa portée (``scope``), où Google revient chez
    lui (``return_path``), ses mots (``not_signed_in``, ``no_scope`` : ils nomment sa fiche et ce qu'il demande),
    les erreurs qu'il attrape (``refused`` : un refus en mots ; ``needed`` : à reconnecter) et le nom qu'il donne
    à Google (``user_agent``)."""

    def __init__(self, grants: GrantStore | None, application: Callable[[], GoogleApplication | None], *,
                 scope: str, return_path: str, not_signed_in: str, no_scope: str, refused: type[Exception],
                 needed: type[Exception], user_agent: str,
                 transport: httpx.AsyncBaseTransport | None = None, now: Callable[[], int] = _now_us,
                 secret: Callable[[int], str] = secrets.token_urlsafe, port: Callable[[], int] = _port) -> None:
        self._grants = grants
        self._application = application
        #: ce que le domaine qui s'en sert demande à Google, où Google revient chez lui, ses mots, ses erreurs, son nom
        self._scope, self._return_path = scope, return_path
        self._not_signed_in, self._no_scope = not_signed_in, no_scope
        self._refused, self._needed = refused, needed
        self._user_agent = user_agent
        self._transport = transport
        self._now = now
        self._secret = secret
        self._port = port
        #: par ``state`` : un parcours commencé
        self._pending: dict[str, _Pending] = {}
        #: par compte : le jeton d'accès, sa fin (µs), et la connexion qui l'a donné
        self._access: dict[str, tuple[str, int, Grant]] = {}
        #: par compte : la connexion que Google ne renouvelle plus, et pourquoi
        self._revoked: dict[str, tuple[Grant, str]] = {}
        #: par compte : pourquoi la dernière fin n'a rien donné
        self._failed: dict[str, str] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._finishing = asyncio.Lock()
        #: prévenu quand un compte se connecte, ou qu'une fin échoue (ADR 0308 : les écrans le relisent ; posé par le
        #: serveur)
        self.on_state: Callable[[str], None] | None = None

    # ── où il en est ──
    def direct(self) -> bool:
        """L'application revient-elle d'elle-même au serveur (une « Application Web ») ? Sinon, on colle l'adresse."""
        app = self._application()
        return app is not None and app.web

    def _grant(self, key: str) -> Grant | None:
        app = self._application()
        grant = self._grants.mail_grant(key) if self._grants is not None else None
        return grant if grant is not None and app is not None and grant.fits(app.client_id, "") else None

    def state(self, key: str) -> SignIn:
        self._sweep()
        pending = next((p for p in self._pending.values() if p.key == key), None)
        if pending is not None:
            return SignIn(SIGNIN_PENDING, url=pending.url, until=pending.until)
        if self._application() is None:
            return SignIn(SIGNIN_NEEDED, error=GOOGLE_NO_APPLICATION)
        grant = self._grant(key)
        revoked = self._revoked.get(key)
        if grant is not None and (revoked is None or revoked[0] != grant):
            return SignIn(SIGNED_IN)
        stale = revoked[1] if grant is not None and revoked is not None else ""
        if grant is None and self._grants is not None and self._grants.mail_grant(key) is not None:
            stale = GOOGLE_OTHER_APPLICATION
        return SignIn(SIGNIN_NEEDED, error=self._failed.get(key) or stale)

    def _sweep(self) -> None:
        now = self._now()
        for state in [s for s, p in self._pending.items() if p.until <= now]:
            del self._pending[state]

    # ── commencer ──
    def start(self, key: str, *, who: str = "", origin: str = "", hint: str = "") -> SignIn:
        """Un parcours commencé pour ce compte (celui d'avant, s'il y en a un, est oublié) : l'adresse de
        consentement de Google à ouvrir (``SignIn.url``), jusqu'à quand le finir. ``who`` : qui le commence (seul à
        pouvoir le finir) ; ``origin`` : l'origine HTTPS du serveur, pour une « Application Web » ; ``hint`` :
        l'adresse du compte Google, que Google propose d'emblée."""
        app = self._application()
        if app is None:
            raise self._refused(GOOGLE_NO_APPLICATION)
        if self._grants is None:
            raise self._refused("la connexion Google n'a pas où garder son jeton")
        if app.web:
            origin = origin.strip().rstrip("/")
            if not origin.lower().startswith("https://") or "/" in origin[len("https://"):]:
                raise self._refused("l'application Google de ce serveur est une « Application Web » : elle revient à "
                                    "une origine HTTPS du serveur, qu'il n'a pas ici")
            redirect = origin + self._return_path
        else:
            redirect = f"http://127.0.0.1:{self._port()}/"
        self._sweep()
        for state in [s for s, p in self._pending.items() if p.key == key]:
            del self._pending[state]
        while len(self._pending) >= PENDING_MAX:
            del self._pending[min(self._pending, key=lambda s: self._pending[s].until)]
        state, verifier = self._secret(24), self._secret(48)
        query = {"client_id": app.client_id, "redirect_uri": redirect, "response_type": "code",
                 "scope": self._scope, "access_type": "offline", "prompt": "consent", "state": state,
                 "code_challenge": _challenge(verifier), "code_challenge_method": "S256",
                 "include_granted_scopes": "false"}
        if hint and "@" in hint and len(hint) <= 200:
            query["login_hint"] = hint.strip()
        url = f"{GOOGLE_AUTH}?{urlencode(query)}"
        until = self._now() + PENDING_US
        self._pending[state] = _Pending(key, who, verifier, redirect, app.client_id, url, until)
        self._failed.pop(key, None)
        return SignIn(SIGNIN_PENDING, url=url, until=until)

    # ── finir ──
    async def finish(self, text: str, *, key: str = "", who: str = "") -> str:
        """La fin d'un parcours : ce qu'on a collé (l'adresse de la page de retour, ou son code), ou la requête de la
        redirection directe. Vérifie le ``state`` (et, sans lui, qu'un seul parcours attend pour ``key``) et qui finit,
        échange le code, garde la connexion ; rend le compte connecté. Un refus se dit en mots (``refused``)."""
        code, state, error = pasted(text)
        async with self._finishing:
            self._sweep()
            pending = self._pending.get(state) if state else None
            if not state and key:
                mine = [p for p in self._pending.values() if p.key == key]
                pending = mine[0] if len(mine) == 1 else None
            if pending is None or (key and pending.key != key) or pending.who != who:
                raise self._refused(GOOGLE_STALE)
            account = pending.key
            if error:
                self._drop_pending(pending)
                why = GOOGLE_DECLINED if error == "access_denied" else f"Google a refusé ({error})"
                self._fail(account, why)
                raise self._refused(why)
            if not code:
                raise self._refused("l'adresse collée ne porte pas de code : colle l'adresse entière de la page qui "
                                    "n'a pas pu s'ouvrir")
            app = self._application()
            if app is None or app.client_id != pending.client_id:
                self._drop_pending(pending)
                raise self._refused("l'application Google du serveur a changé entre-temps : recommence")
            got = await self._post(GOOGLE_TOKEN, {"grant_type": "authorization_code", "code": code,
                                                  "client_id": app.client_id, "client_secret": app.secret,
                                                  "redirect_uri": pending.redirect, "code_verifier": pending.verifier})
            self._drop_pending(pending)
            if got.get("error"):
                why = ("le code a déjà servi ou a expiré : recommence « Se connecter à Google »"
                       if got.get("error") == "invalid_grant" else _google_refused(got))
                self._fail(account, why)
                raise self._refused(why)
            granted = str(got.get("scope") or "").split()
            if self._scope not in granted:
                self._fail(account, self._no_scope)
                raise self._refused(self._no_scope)
            refresh = str(got.get("refresh_token") or "")
            if not refresh:
                self._fail(account, "Google n'a pas rendu de jeton de renouvellement : recommence")
                raise self._refused("Google n'a pas rendu de jeton de renouvellement : recommence")
            grant = Grant(refresh, app.client_id, "")
            assert self._grants is not None
            await self._grants.save_mail_grant(account, grant)
            self._hold(account, grant, got)
            self._revoked.pop(account, None)
            self._failed.pop(account, None)
            log.info("agenda : %s est connecté à Google", account)
        self._said(account)
        return account

    def _drop_pending(self, pending: _Pending) -> None:
        for state in [s for s, p in self._pending.items() if p is pending]:
            del self._pending[state]

    def _fail(self, key: str, why: str) -> None:
        self._failed[key] = why
        self._said(key)

    def _said(self, key: str) -> None:
        if self.on_state is None:
            return
        try:
            self.on_state(key)
        except Exception:  # un écouteur en panne ne change rien à la connexion
            log.exception("agenda : la fin d'une connexion Google n'a pas pu se dire (%s)", key)

    # ── le jeton d'accès ──
    def _hold(self, key: str, grant: Grant, got: dict[str, Any]) -> str:
        access = str(got.get("access_token") or "")
        if not access:
            raise self._refused("Google n'a pas rendu de jeton d'accès")
        try:
            lasts = int(float(got.get("expires_in") or 3600) * 1_000_000)
        except (TypeError, ValueError):
            lasts = 3600 * 1_000_000
        self._access[key] = (access, self._now() + lasts, grant)
        return access

    async def token(self, key: str) -> str:
        """Le jeton d'accès d'un compte connecté (renouvelé s'il expire bientôt) ; ``needed`` s'il ne l'est pas,
        ou plus ; ``refused`` si Google ne répond pas."""
        async with self._locks.setdefault(key, asyncio.Lock()):
            app = self._application()
            if app is None:
                raise self._needed(GOOGLE_NO_APPLICATION)
            if self._grants is None:
                raise self._needed(self._not_signed_in)
            grant = self._grant(key)
            if grant is None:
                stored = self._grants.mail_grant(key)
                raise self._needed(GOOGLE_OTHER_APPLICATION if stored is not None else self._not_signed_in)
            revoked = self._revoked.get(key)
            if revoked is not None and revoked[0] == grant:  # Google ne la renouvelle plus : pas représentée
                raise self._needed(revoked[1])
            held = self._access.get(key)
            if held is not None and held[2] == grant and held[1] - MARGIN_US > self._now():
                return held[0]
            got = await self._post(GOOGLE_TOKEN, {"grant_type": "refresh_token", "refresh_token": grant.refresh,
                                                  "client_id": app.client_id, "client_secret": app.secret})
            if got.get("error"):
                why = _google_refused(got)
                if got.get("error") == "invalid_grant":
                    self._revoked[key] = (grant, why)
                    log.warning("agenda : la connexion Google de %s ne vaut plus", key)
                    raise self._needed(why)
                raise self._refused(why)
            if got.get("refresh_token") and got["refresh_token"] != grant.refresh:  # Google l'a remplacé
                grant = Grant(str(got["refresh_token"]), grant.client_id, "")
                await self._grants.save_mail_grant(key, grant)
            return self._hold(key, grant, got)

    def drop(self, key: str) -> None:
        """Le jeton d'accès de ce compte oublié (Google vient de le refuser) : le prochain se renouvelle."""
        self._access.pop(key, None)

    async def revoke(self, key: str) -> bool:
        """La connexion de ce compte retirée chez Google (on le déconnecte) ; vrai si Google l'a retirée. La garder
        ou l'effacer des réglages est l'affaire de qui l'appelle."""
        grant = self._grants.mail_grant(key) if self._grants is not None else None
        self._access.pop(key, None)
        if grant is None:
            return False
        try:
            got = await self._post(GOOGLE_REVOKE, {"token": grant.refresh})
        except self._refused as exc:
            log.info("agenda : la connexion Google de %s n'a pas pu être retirée chez Google (%s)", key, exc)
            return False
        return not got.get("error")

    # ── Google ──
    async def _post(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        """Un appel au point OAuth de Google ; rend sa réponse JSON, ses refus compris (``error``)."""
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, transport=self._transport, follow_redirects=False,
                                         headers={"User-Agent": self._user_agent}) as client:
                got = await client.post(url, data=data, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise self._refused(f"Google ne répond pas ({type(exc).__name__})") from None
        if not got.content.strip() and got.status_code < 400:
            return {}
        try:
            body = got.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise self._refused(f"Google a répondu {got.status_code}, sans réponse lisible")
        if got.status_code >= 400 and not body.get("error"):
            raise self._refused(f"Google a répondu {got.status_code}")
        return body


__all__ = ["GOOGLE_AUTH", "GOOGLE_NO_APPLICATION", "GOOGLE_REVOKED", "GOOGLE_TOKEN", "TIMEOUT", "GoogleApplication",
           "GoogleSignIn", "google_client_id", "pasted"]
