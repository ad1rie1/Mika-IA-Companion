"""Se connecter à Google Agenda et à Microsoft Graph (ADR 0309, lot 2) : le jeton de renouvellement d'un compte
d'agenda, scellé dans les réglages à part des comptes (``AgendaGrants`` : ``app/settings.py``, la clé
``agenda_oauth``), et le jeton d'accès, en mémoire, renouvelé avant sa fin.

- **Microsoft** (``microsoft_signin``) : le code d'appareil du courrier (``adapters/mail/oauth.py``,
  ``MicrosoftSignIn``, ADR 0166), une instance à part : la portée de Graph (``Calendars.ReadWrite`` et
  ``offline_access`` : un jeton à part de celui d'une boîte IMAP), les connexions des comptes d'agenda, ses mots.
  L'application est celle de l'instance, celle du courrier (ADR 0238), ou celle que le compte déclare
  (``oauth_client_id``), dans son annuaire (``oauth_tenant``).
- **Google** (``GoogleSignIn``) : OAuth 2 avec PKCE (RFC 7636) — Google refuse le code d'appareil pour l'agenda. Le
  serveur a **une application Google à lui** (``GoogleApplication`` : un client « Application de bureau » d'un projet
  Google Cloud, son identifiant et son secret, réglés par un opérateur) ; sans elle, brancher Google est refusé en
  mots. Le parcours a deux temps : **commencer** (``start`` : l'adresse de consentement de Google, ``access_type=
  offline``, ``prompt=consent``, un ``state`` et un vérificateur PKCE gardés ici un quart d'heure, une redirection
  vers ``http://127.0.0.1:<port>/`` — Google accepte tout port en boucle locale pour un client de bureau —, que le
  navigateur ne peut pas ouvrir), puis **finir** (``finish`` : l'adresse entière de la page qui n'a pas pu s'ouvrir,
  ou son code seul ; le ``state`` vérifié, le code échangé contre les jetons, la portée de l'agenda vérifiée — Google
  laisse décocher chaque case du consentement). Un client « Application Web » (``GoogleApplication.web``) redirige
  lui-même vers l'origine HTTPS du serveur (``RETURN_PATH``, que l'API par personne servira, lot 4) : la même fin,
  sans rien coller. Qui a commencé (``who``) est le seul à pouvoir finir.
- **Un jeton refusé** (``invalid_grant`` : révoqué, expiré — une application en mode test ne le garde que sept
  jours —, l'accès retiré) n'est plus présenté : le compte est à reconnecter (``SignInNeeded``, en mots), jusqu'à une
  connexion neuve. Changer d'application demande de se reconnecter. Aucun jeton n'entre dans un journal ni dans un
  message.
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
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx

from mika.adapters.agenda.cloud import TIMEOUT, USER_AGENT, SignInNeeded
from mika.adapters.mail.oauth import Grant, MicrosoftSignIn
from mika.ports.agenda import GOOGLE, MICROSOFT, AgendaError
from mika.ports.signin import SIGNED_IN, SIGNIN_NEEDED, SIGNIN_PENDING, SignIn

log = logging.getLogger("mika.agenda")

# ── Microsoft ───────────────────────────────────────────────────────────────

#: les agendas par Microsoft Graph, et un jeton de renouvellement
MICROSOFT_SCOPES = "offline_access https://graph.microsoft.com/Calendars.ReadWrite"
MICROSOFT_NOT_SIGNED_IN = "pas encore connecté à Microsoft : « Se connecter à Microsoft » sur la fiche du compte"
MICROSOFT_NO_APPLICATION = ("aucune application Microsoft déclarée : celle de l'instance, que le courrier partage, se "
                            "règle dans Courrier › Paramètres › Compte Microsoft (ou mika mail application) ; un "
                            "compte peut déclarer la sienne")


class AgendaGrants(Protocol):
    """Où les connexions des comptes d'agenda se gardent, scellées (les réglages), par compte et par sorte."""

    def agenda_grant(self, account: str, kind: str) -> Grant | None: ...

    async def save_agenda_grant(self, account: str, grant: Grant, kind: str) -> None: ...


class _KindGrants:
    """Les connexions d'une sorte de compte d'agenda, sous la forme que lit le code d'appareil du courrier
    (``adapters/mail/oauth.py::GrantStore``)."""

    def __init__(self, grants: AgendaGrants, kind: str) -> None:
        self._grants = grants
        self._kind = kind

    def mail_grant(self, account: str) -> Grant | None:
        return self._grants.agenda_grant(account, self._kind)

    async def save_mail_grant(self, account: str, grant: Grant) -> None:
        await self._grants.save_agenda_grant(account, grant, self._kind)


def microsoft_signin(grants: AgendaGrants | None, application: Callable[[], str] = lambda: "", *,
                     transport: httpx.AsyncBaseTransport | None = None, **more: Any) -> MicrosoftSignIn:
    """Les connexions Microsoft des comptes d'agenda : le code d'appareil du courrier, à la portée de Graph
    (``start(compte, connexion)``, ``state``, ``token``, ``drop``) ; ``application`` : celle de l'instance."""
    return MicrosoftSignIn(_KindGrants(grants, MICROSOFT) if grants is not None else None, transport=transport,
                           application=application, scopes=MICROSOFT_SCOPES, not_signed_in=MICROSOFT_NOT_SIGNED_IN,
                           no_application=MICROSOFT_NO_APPLICATION, label="agenda", **more)


# ── Google ──────────────────────────────────────────────────────────────────

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE = "https://oauth2.googleapis.com/revoke"
#: lire et écrire ses agendas (leur liste, leurs événements, en créer)
GOOGLE_SCOPE = "https://www.googleapis.com/auth/calendar"
#: où un client « Application Web » revient, sous l'origine HTTPS du serveur (la route est celle du lot 4)
RETURN_PATH = "/api/moi/agenda/google/retour"
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
GOOGLE_NOT_SIGNED_IN = "pas encore connecté à Google : « Se connecter à Google » sur la fiche du compte"
GOOGLE_REVOKED = ("à reconnecter : Google ne renouvelle plus l'accès (retiré depuis le compte Google, mot de passe "
                  "changé, ou une application Google en mode test, dont l'accès dure sept jours)")
GOOGLE_OTHER_APPLICATION = "à reconnecter : l'application Google du serveur a changé depuis la connexion"
GOOGLE_STALE = ("cette adresse ne vient pas d'une connexion commencée ici, ou elle a expiré : recommence « Se "
                "connecter à Google »")
GOOGLE_DECLINED = "la connexion a été refusée chez Google"
GOOGLE_NO_CALENDAR = ("Google n'a pas donné l'accès à l'agenda (sa case n'était pas cochée) : recommence et coche-la")


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
    """Les connexions Google des comptes d'agenda : commencer (``start``), finir (``finish``), où elles en sont
    (``state``), le jeton d'accès d'un compte connecté (``token``), l'oublier (``drop``), la retirer chez Google
    (``revoke``)."""

    def __init__(self, grants: AgendaGrants | None, application: Callable[[], GoogleApplication | None], *,
                 transport: httpx.AsyncBaseTransport | None = None, now: Callable[[], int] = _now_us,
                 secret: Callable[[int], str] = secrets.token_urlsafe, port: Callable[[], int] = _port) -> None:
        self._grants = grants
        self._application = application
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
        grant = self._grants.agenda_grant(key, GOOGLE) if self._grants is not None else None
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
        if grant is None and self._grants is not None and self._grants.agenda_grant(key, GOOGLE) is not None:
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
            raise AgendaError(GOOGLE_NO_APPLICATION)
        if self._grants is None:
            raise AgendaError("la connexion Google n'a pas où garder son jeton")
        if app.web:
            origin = origin.strip().rstrip("/")
            if not origin.lower().startswith("https://") or "/" in origin[len("https://"):]:
                raise AgendaError("l'application Google de ce serveur est une « Application Web » : elle revient à "
                                  "une origine HTTPS du serveur, qu'il n'a pas ici")
            redirect = origin + RETURN_PATH
        else:
            redirect = f"http://127.0.0.1:{self._port()}/"
        self._sweep()
        for state in [s for s, p in self._pending.items() if p.key == key]:
            del self._pending[state]
        while len(self._pending) >= PENDING_MAX:
            del self._pending[min(self._pending, key=lambda s: self._pending[s].until)]
        state, verifier = self._secret(24), self._secret(48)
        query = {"client_id": app.client_id, "redirect_uri": redirect, "response_type": "code",
                 "scope": GOOGLE_SCOPE, "access_type": "offline", "prompt": "consent", "state": state,
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
        échange le code, garde la connexion ; rend le compte connecté. Un refus se dit en mots (``AgendaError``)."""
        code, state, error = pasted(text)
        async with self._finishing:
            self._sweep()
            pending = self._pending.get(state) if state else None
            if not state and key:
                mine = [p for p in self._pending.values() if p.key == key]
                pending = mine[0] if len(mine) == 1 else None
            if pending is None or (key and pending.key != key) or pending.who != who:
                raise AgendaError(GOOGLE_STALE)
            account = pending.key
            if error:
                self._drop_pending(pending)
                why = GOOGLE_DECLINED if error == "access_denied" else f"Google a refusé ({error})"
                self._fail(account, why)
                raise AgendaError(why)
            if not code:
                raise AgendaError("l'adresse collée ne porte pas de code : colle l'adresse entière de la page qui "
                                  "n'a pas pu s'ouvrir")
            app = self._application()
            if app is None or app.client_id != pending.client_id:
                self._drop_pending(pending)
                raise AgendaError("l'application Google du serveur a changé entre-temps : recommence")
            got = await self._post(GOOGLE_TOKEN, {"grant_type": "authorization_code", "code": code,
                                                  "client_id": app.client_id, "client_secret": app.secret,
                                                  "redirect_uri": pending.redirect, "code_verifier": pending.verifier})
            self._drop_pending(pending)
            if got.get("error"):
                why = ("le code a déjà servi ou a expiré : recommence « Se connecter à Google »"
                       if got.get("error") == "invalid_grant" else _google_refused(got))
                self._fail(account, why)
                raise AgendaError(why)
            granted = str(got.get("scope") or "").split()
            if GOOGLE_SCOPE not in granted:
                self._fail(account, GOOGLE_NO_CALENDAR)
                raise AgendaError(GOOGLE_NO_CALENDAR)
            refresh = str(got.get("refresh_token") or "")
            if not refresh:
                self._fail(account, "Google n'a pas rendu de jeton de renouvellement : recommence")
                raise AgendaError("Google n'a pas rendu de jeton de renouvellement : recommence")
            grant = Grant(refresh, app.client_id, "")
            assert self._grants is not None
            await self._grants.save_agenda_grant(account, grant, GOOGLE)
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
            raise AgendaError("Google n'a pas rendu de jeton d'accès")
        try:
            lasts = int(float(got.get("expires_in") or 3600) * 1_000_000)
        except (TypeError, ValueError):
            lasts = 3600 * 1_000_000
        self._access[key] = (access, self._now() + lasts, grant)
        return access

    async def token(self, key: str) -> str:
        """Le jeton d'accès d'un compte connecté (renouvelé s'il expire bientôt) ; ``SignInNeeded`` s'il ne l'est
        pas, ou plus ; ``AgendaError`` si Google ne répond pas."""
        async with self._locks.setdefault(key, asyncio.Lock()):
            app = self._application()
            if app is None:
                raise SignInNeeded(GOOGLE_NO_APPLICATION)
            if self._grants is None:
                raise SignInNeeded(GOOGLE_NOT_SIGNED_IN)
            grant = self._grant(key)
            if grant is None:
                stored = self._grants.agenda_grant(key, GOOGLE)
                raise SignInNeeded(GOOGLE_OTHER_APPLICATION if stored is not None else GOOGLE_NOT_SIGNED_IN)
            revoked = self._revoked.get(key)
            if revoked is not None and revoked[0] == grant:  # Google ne la renouvelle plus : pas représentée
                raise SignInNeeded(revoked[1])
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
                    raise SignInNeeded(why)
                raise AgendaError(why)
            if got.get("refresh_token") and got["refresh_token"] != grant.refresh:  # Google l'a remplacé
                grant = Grant(str(got["refresh_token"]), grant.client_id, "")
                await self._grants.save_agenda_grant(key, grant, GOOGLE)
            return self._hold(key, grant, got)

    def drop(self, key: str) -> None:
        """Le jeton d'accès de ce compte oublié (Google vient de le refuser) : le prochain se renouvelle."""
        self._access.pop(key, None)

    async def revoke(self, key: str) -> bool:
        """La connexion de ce compte retirée chez Google (on le déconnecte) ; vrai si Google l'a retirée. La garder
        ou l'effacer des réglages est l'affaire de qui l'appelle."""
        grant = self._grants.agenda_grant(key, GOOGLE) if self._grants is not None else None
        self._access.pop(key, None)
        if grant is None:
            return False
        try:
            got = await self._post(GOOGLE_REVOKE, {"token": grant.refresh})
        except AgendaError as exc:
            log.info("agenda : la connexion Google de %s n'a pas pu être retirée chez Google (%s)", key, exc)
            return False
        return not got.get("error")

    # ── Google ──
    async def _post(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        """Un appel au point OAuth de Google ; rend sa réponse JSON, ses refus compris (``error``)."""
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, transport=self._transport, follow_redirects=False,
                                         headers={"User-Agent": USER_AGENT}) as client:
                got = await client.post(url, data=data, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise AgendaError(f"Google ne répond pas ({type(exc).__name__})") from None
        if not got.content.strip() and got.status_code < 400:
            return {}
        try:
            body = got.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise AgendaError(f"Google a répondu {got.status_code}, sans réponse lisible")
        if got.status_code >= 400 and not body.get("error"):
            raise AgendaError(f"Google a répondu {got.status_code}")
        return body


__all__ = ["GOOGLE_AUTH", "GOOGLE_NOT_SIGNED_IN", "GOOGLE_NO_APPLICATION", "GOOGLE_REVOKED", "GOOGLE_SCOPE",
           "GOOGLE_TOKEN", "MICROSOFT_NOT_SIGNED_IN", "MICROSOFT_NO_APPLICATION", "MICROSOFT_SCOPES", "RETURN_PATH",
           "AgendaGrants", "GoogleApplication", "GoogleSignIn", "google_client_id", "microsoft_signin", "pasted"]
