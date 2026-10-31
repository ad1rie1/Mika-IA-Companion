"""Entrer dans une boîte Microsoft sans mot de passe : OAuth2 et XOAUTH2 (ADR 0166).

Hotmail, Outlook.com et Live refusent le mot de passe en IMAP et en SMTP. On y entre avec un jeton d'accès, que
présente le mécanisme SASL ``XOAUTH2`` (``answer``) ; Microsoft 365 aussi, si son administrateur le permet.

- **Se connecter** : le flux « code d'appareil » (RFC 8628). La console montre un code et la page de Microsoft où
  l'entrer ; la personne s'y connecte chez Microsoft, avec son mot de passe et sa double authentification, que Mika
  ne voit jamais. Pendant ce temps, on demande le jeton à Microsoft au rythme qu'il fixe, jusqu'au feu vert ou à
  l'expiration du code (un quart d'heure). Ce code vit en mémoire : un redémarrage l'oublie, on recommence.
- **Ce qu'on garde** : le jeton de renouvellement, avec l'application et l'annuaire qui l'ont délivré (``Grant``),
  scellé dans les réglages par le ``GrantStore`` que l'application fournit. Changer d'application ou d'annuaire
  demande de se reconnecter. Microsoft renouvelle souvent ce jeton : le nouveau remplace l'ancien. Le jeton
  d'accès (une heure) reste en mémoire, renouvelé avant d'expirer.
- **L'application** : Microsoft ne délivre un jeton qu'à une application inscrite, dont on donne l'identifiant
  (``oauth_client_id``) : un client public, inscrit par la personne elle-même dans Microsoft Entra.
- Une panne (réseau, refus de Microsoft) est une ``OAuthError``, dite en français. Un jeton que Microsoft ne
  renouvelle plus (``invalid_grant``) n'est plus présenté : la boîte attend qu'on la reconnecte. Aucun jeton
  n'entre jamais dans un journal ni dans un message.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from mika.adapters.mail.config import MailAccount
from mika.ports.mail import SIGNED_IN, SIGNIN_NEEDED, SIGNIN_PENDING, SignIn

log = logging.getLogger("mika.mail")

AUTHORITY = "https://login.microsoftonline.com"
#: lire et ranger (IMAP), envoyer (SMTP), et un jeton de renouvellement (``offline_access``)
SCOPES = "offline_access https://outlook.office.com/IMAP.AccessAsUser.All https://outlook.office.com/SMTP.Send"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
#: la page où entrer le code, si Microsoft ne la dit pas
DEVICE_PAGE = "https://microsoft.com/devicelogin"
#: un jeton d'accès qui expire dans moins que ceci est renouvelé avant de servir (s)
MARGIN_S = 300.0
TIMEOUT_S = 20.0
#: ce que Microsoft accorde ensuite à un code entré trop lentement (« slow_down ») : tant de secondes de plus
SLOWER_S = 5.0

NOT_SIGNED_IN = "pas encore connectée à Microsoft : « Se connecter à Microsoft » sur la fiche de la boîte"
NO_APPLICATION = ("aucune application Microsoft déclarée (son identifiant, le client ID, se donne dans les réglages "
                  "de la boîte)")
NO_STORE = "la connexion Microsoft n'a pas où garder son jeton"
EXPIRED = "le code a expiré avant d'être entré chez Microsoft"
#: ce que Microsoft répond quand le jeton de renouvellement ne vaut plus
REVOKED = "Microsoft ne renouvelle plus sa connexion (mot de passe changé, accès retiré, ou trop longtemps sans servir)"


class OAuthError(RuntimeError):
    """La connexion Microsoft a échoué (dit en français, sans jeton)."""


class Unreachable(OAuthError):
    """Microsoft n'a pas répondu (réseau) : ce n'est pas un refus."""


@dataclass(frozen=True, slots=True)
class Grant:
    """Ce qu'on garde d'une connexion : le jeton de renouvellement, et l'application et l'annuaire qui l'ont délivré."""

    refresh: str
    client_id: str
    tenant: str

    def fits(self, account: MailAccount) -> bool:
        return self.client_id == account.oauth_client_id and self.tenant == account.oauth_tenant


class GrantStore(Protocol):
    """Où les connexions se gardent, scellées (les réglages)."""

    def mail_grant(self, account: str) -> Grant | None: ...

    async def save_mail_grant(self, account: str, grant: Grant) -> None: ...


def xoauth2(user: str, token: str) -> str:
    """La réponse SASL ``XOAUTH2``, avant son base64."""
    return f"user={user}\x01auth=Bearer {token}\x01\x01"


def answer(user: str, token: str) -> Callable[..., str]:
    """De quoi répondre au serveur (``imaplib.authenticate``, ``smtplib.auth``) : la réponse ``XOAUTH2`` la première
    fois ; si le serveur renvoie un défi (son erreur, en JSON), une réponse vide, qui clôt l'échange par un refus."""
    said = False

    def respond(challenge: bytes | None = None) -> str:
        nonlocal said
        if said:
            return ""
        said = True
        return xoauth2(user, token)

    return respond


def _refused(body: dict[str, Any]) -> str:
    """Le refus de Microsoft, en français (son code, et le début de sa description)."""
    error = str(body.get("error") or "erreur")[:60]
    if error == "invalid_grant":
        return REVOKED
    if error == "authorization_declined":
        return "la connexion a été refusée chez Microsoft"
    if error == "expired_token":
        return EXPIRED
    detail = str(body.get("error_description") or "").split("\n")[0].strip()
    return f"Microsoft a refusé ({error}) : {detail[:200]}" if detail else f"Microsoft a refusé ({error})"


@dataclass(slots=True)
class _Pending:
    code: str
    url: str
    until: float
    task: asyncio.Task[None] | None = field(default=None, repr=False)


class MicrosoftSignIn:
    """Les connexions Microsoft des boîtes : les commencer (``start``), où elles en sont (``state``), et le jeton
    d'accès d'une boîte connectée (``token``)."""

    def __init__(self, grants: GrantStore | None = None, *, now: Callable[[], datetime] = lambda: datetime.now(UTC),
                 transport: httpx.AsyncBaseTransport | None = None,
                 sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep) -> None:
        self._grants = grants
        self._now = now
        self._transport = transport
        self._sleep = sleep
        #: par boîte : le jeton d'accès, sa fin (s), et la connexion qui l'a donné
        self._access: dict[str, tuple[str, float, Grant]] = {}
        self._pending: dict[str, _Pending] = {}
        #: par boîte : la connexion que Microsoft ne renouvelle plus, et pourquoi (un nouveau code ne l'efface pas : seule
        #: une connexion neuve la remplace)
        self._revoked: dict[str, tuple[Grant, str]] = {}
        #: par boîte : pourquoi le dernier code n'a rien donné
        self._failed: dict[str, str] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _t(self) -> float:
        return self._now().timestamp()

    def _grant(self, key: str, account: MailAccount) -> Grant | None:
        grant = self._grants.mail_grant(key) if self._grants is not None else None
        return grant if grant is not None and grant.fits(account) else None

    # ── où elle en est ──
    def state(self, key: str, account: MailAccount) -> SignIn:
        pending = self._pending.get(key)
        if pending is not None and pending.until > self._t():
            return SignIn(SIGNIN_PENDING, code=pending.code, url=pending.url, until=int(pending.until * 1_000_000))
        grant = self._grant(key, account)
        revoked = self._revoked.get(key)
        if grant is not None and (revoked is None or revoked[0] != grant):
            return SignIn(SIGNED_IN)
        if grant is None and not account.oauth_client_id:
            return SignIn(SIGNIN_NEEDED, error=NO_APPLICATION)
        stale = revoked[1] if grant is not None and revoked is not None else ""
        return SignIn(SIGNIN_NEEDED, error=self._failed.get(key) or stale)

    # ── le jeton d'accès ──
    async def token(self, key: str, account: MailAccount) -> str:
        """Le jeton d'accès d'une boîte connectée (renouvelé s'il expire bientôt) ; ``OAuthError`` si elle ne l'est
        pas, ou plus."""
        async with self._locks.setdefault(key, asyncio.Lock()):
            if self._grants is None:
                raise OAuthError(NO_STORE)
            grant = self._grant(key, account)
            if grant is None:
                raise OAuthError(NOT_SIGNED_IN if account.oauth_client_id else NO_APPLICATION)
            revoked = self._revoked.get(key)
            # Microsoft ne la renouvelle plus : on ne la lui représente pas à chaque relevé
            if revoked is not None and revoked[0] == grant:
                raise OAuthError(revoked[1])
            held = self._access.get(key)
            if held is not None and held[2] == grant and held[1] - MARGIN_S > self._t():
                return held[0]
            got = await self._post(grant.tenant, "token", {"grant_type": "refresh_token", "client_id": grant.client_id,
                                                           "refresh_token": grant.refresh, "scope": SCOPES})
            if got.get("error"):
                why = _refused(got)
                if got.get("error") == "invalid_grant":
                    self._revoked[key] = (grant, why)
                    log.warning("courrier : la connexion Microsoft de %s ne vaut plus", key)
                raise OAuthError(why)
            return await self._keep(key, grant.client_id, grant.tenant, got, previous=grant)

    async def _keep(self, key: str, client_id: str, tenant: str, got: dict[str, Any], *,
                    previous: Grant | None) -> str:
        """Garde ce que Microsoft vient de rendre : le jeton d'accès en mémoire, le jeton de renouvellement scellé
        (s'il a changé)."""
        access = str(got.get("access_token") or "")
        refresh = str(got.get("refresh_token") or "") or (previous.refresh if previous is not None else "")
        if not access:
            raise OAuthError("Microsoft n'a pas rendu de jeton d'accès")
        if not refresh:
            raise OAuthError("Microsoft n'a pas rendu de jeton de renouvellement (l'accès « offline_access » manque)")
        grant = Grant(refresh, client_id, tenant)
        if grant != previous:
            assert self._grants is not None
            await self._grants.save_mail_grant(key, grant)
        try:
            lasts = float(got.get("expires_in") or 3600)
        except (TypeError, ValueError):
            lasts = 3600.0
        self._access[key] = (access, self._t() + lasts, grant)
        self._revoked.pop(key, None)
        self._failed.pop(key, None)
        return access

    # ── se connecter ──
    async def start(self, key: str, account: MailAccount) -> SignIn:
        """Demande un code à Microsoft et attend, en tâche de fond, que la personne l'entre ; rend le code à
        montrer. Une connexion en attente pour la même boîte est remplacée."""
        if not account.oauth_client_id:
            raise OAuthError(NO_APPLICATION)
        if self._grants is None:
            raise OAuthError(NO_STORE)
        got = await self._post(account.oauth_tenant, "devicecode", {"client_id": account.oauth_client_id,
                                                                    "scope": SCOPES})
        if got.get("error"):
            raise OAuthError(_refused(got))
        device, code = str(got.get("device_code") or ""), str(got.get("user_code") or "")
        if not device or not code:
            raise OAuthError("Microsoft n'a pas rendu de code à entrer")
        try:
            lasts, interval = float(got.get("expires_in") or 900), max(1.0, float(got.get("interval") or 5))
        except (TypeError, ValueError):
            lasts, interval = 900.0, 5.0
        old = self._pending.pop(key, None)
        if old is not None and old.task is not None:
            old.task.cancel()
        pending = _Pending(code[:40], str(got.get("verification_uri") or DEVICE_PAGE)[:200], self._t() + lasts)
        self._pending[key] = pending
        self._failed.pop(key, None)
        pending.task = asyncio.create_task(self._wait(key, account.oauth_client_id, account.oauth_tenant, device,
                                                      interval, pending), name=f"mail-oauth-{key}")
        return self.state(key, account)

    async def _wait(self, key: str, client_id: str, tenant: str, device: str, interval: float,
                    pending: _Pending) -> None:
        try:
            while self._t() < pending.until:
                await self._sleep(interval)
                try:
                    got = await self._post(tenant, "token", {"grant_type": DEVICE_GRANT, "client_id": client_id,
                                                             "device_code": device})
                except Unreachable:
                    continue  # un raté du réseau n'arrête pas l'attente : le code vaut encore
                error = got.get("error")
                if error == "authorization_pending":
                    continue
                if error == "slow_down":
                    interval += SLOWER_S
                    continue
                if error:
                    self._failed[key] = _refused(got)
                    return
                await self._keep(key, client_id, tenant, got, previous=None)
                log.info("courrier : %s est connectée à Microsoft", key)
                return
            self._failed[key] = EXPIRED
        except OAuthError as exc:
            self._failed[key] = str(exc)
        except Exception as exc:  # garder la connexion a échoué (les réglages) : dit, jamais une tâche morte en silence
            log.warning("courrier : la connexion Microsoft de %s n'a pas pu être gardée (%s)", key, type(exc).__name__)
            self._failed[key] = "la connexion n'a pas pu être gardée"
        finally:
            if self._pending.get(key) is pending:
                del self._pending[key]

    # ── Microsoft ──
    async def _post(self, tenant: str, endpoint: str, data: dict[str, str]) -> dict[str, Any]:
        """Un appel au point OAuth2 de Microsoft ; rend sa réponse JSON, erreurs OAuth comprises (``error``)."""
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=self._transport) as client:
                got = await client.post(f"{AUTHORITY}/{tenant}/oauth2/v2.0/{endpoint}", data=data,
                                        headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise Unreachable(f"Microsoft ne répond pas ({type(exc).__name__})") from None
        try:
            body = got.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise OAuthError(f"Microsoft a répondu {got.status_code}, sans réponse lisible")
        if got.status_code >= 400 and not body.get("error"):
            raise OAuthError(f"Microsoft a répondu {got.status_code}")
        return body

    def close(self) -> None:
        for pending in self._pending.values():
            if pending.task is not None:
                pending.task.cancel()
        self._pending.clear()
