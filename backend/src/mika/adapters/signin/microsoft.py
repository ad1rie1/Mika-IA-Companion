"""Se connecter à un compte Microsoft sans mot de passe : OAuth2 par code d'appareil (ADR 0166, 0238, 0318).

Se connecter n'est à aucun domaine : une boîte Hotmail (le courrier, ``adapters/mail/oauth.py::mail_signin``) et un
agenda Outlook.com (``adapters/agenda/oauth.py::microsoft_signin``) entrent par ce même moteur, chacun avec sa portée,
ses connexions et ses mots.

- **Se connecter** : le flux « code d'appareil » (RFC 8628). La console montre un code et la page de Microsoft où
  l'entrer ; la personne s'y connecte chez Microsoft, avec son mot de passe et sa double authentification, que Mika
  ne voit jamais. Pendant ce temps, on demande le jeton à Microsoft au rythme qu'il fixe, jusqu'au feu vert ou à
  l'expiration du code (un quart d'heure). Ce code vit en mémoire : un redémarrage l'oublie, on recommence.
- **Ce qu'on garde** : le jeton de renouvellement, avec l'application et l'annuaire qui l'ont délivré (``Grant``),
  scellé dans les réglages du domaine par le ``GrantStore`` qu'il fournit (``grants.py``). Changer d'application ou
  d'annuaire demande de se reconnecter. Microsoft renouvelle souvent ce jeton : le nouveau remplace l'ancien. Le jeton
  d'accès (une heure) reste en mémoire, renouvelé avant d'expirer.
- **L'application** : Microsoft ne délivre un jeton qu'à une application inscrite, un client public de Microsoft
  Entra. C'est celle que Mika livre (``DEFAULT_APPLICATION``), ou celle que l'instance s'est donnée (``application``,
  ADR 0238 : un réglage du cadre, ``app/connections.py``) ; celle que le compte déclare lui-même
  (``oauth_client_id``) passe devant. Son identifiant et l'annuaire se vérifient ici (``application_id``,
  ``tenant_id``) : ils entrent dans l'adresse de Microsoft.
- Une panne (réseau, refus de Microsoft) est une ``OAuthError``, dite en français (les refus courants d'Entra par
  leur code ``AADSTS…`` : ``AADSTS_WORDS``). Un jeton que Microsoft ne renouvelle plus (``invalid_grant``, ou une
  nouvelle vérification exigée : ``interaction_required``) n'est plus présenté : le compte attend qu'on le reconnecte.
  Aucun jeton n'entre jamais dans un journal ni dans un message.
- **Ce que le domaine donne** : sa portée (``scopes``), ses connexions, ses mots (``not_signed_in``,
  ``no_application`` : ils nomment sa fiche et ses réglages) et le nom de ses journaux (``label``) ; un compte se lit
  par ``OAuthAccount`` (une boîte, un compte d'agenda).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from mika.adapters.signin.grants import Grant, GrantStore
from mika.ports.signin import SIGNED_IN, SIGNIN_NEEDED, SIGNIN_PENDING, SignIn

log = logging.getLogger("mika.mail")

AUTHORITY = "https://login.microsoftonline.com"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
#: la page où entrer le code, si Microsoft ne la dit pas
DEVICE_PAGE = "https://microsoft.com/devicelogin"
#: un jeton d'accès qui expire dans moins que ceci est renouvelé avant de servir (s)
MARGIN_S = 300.0
TIMEOUT_S = 20.0
#: ce que Microsoft accorde ensuite à un code entré trop lentement (« slow_down ») : tant de secondes de plus
SLOWER_S = 5.0

#: l'annuaire Microsoft des comptes personnels (Hotmail, Outlook.com, Live)
CONSUMERS = "consumers"
#: l'identifiant d'une application Microsoft (un GUID) ; un annuaire (``consumers``, ``organizations``, un domaine ou
#: un GUID) : il entre dans l'adresse de Microsoft, rien d'autre n'y passe
_CLIENT_ID = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_TENANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,99}$")

#: l'application Microsoft que Mika livre (ADR 0238) : un client public inscrit dans Microsoft Entra (comptes
#: personnels, flux de clients publics), dont l'identifiant n'est pas un secret. Une instance peut donner la sienne.
DEFAULT_APPLICATION = "ed7003c6-4cc5-4af8-91a9-724a66281d58"

NO_STORE = "la connexion Microsoft n'a pas où garder son jeton"
EXPIRED = "le code a expiré avant d'être entré chez Microsoft"
#: ce que Microsoft répond quand le jeton de renouvellement ne vaut plus
REVOKED = "Microsoft ne renouvelle plus sa connexion (mot de passe changé, accès retiré, ou trop longtemps sans servir)"
#: les refus d'Entra qu'on sait dire, par le code qui ouvre leur description
_ADMIN = "ton organisation demande l'accord de son administrateur pour cette application (Entra › Applications d'entreprise)"
AADSTS_WORDS = {
    "AADSTS65001": "l'accès demandé n'a pas été accordé chez Microsoft : reconnecte-toi et accepte ce qui est demandé",
    "AADSTS65004": "l'accès demandé a été refusé chez Microsoft",
    "AADSTS90094": _ADMIN, "AADSTS90095": _ADMIN, "AADSTS90008": _ADMIN,
    "AADSTS700016": "cette application Microsoft n'existe pas dans cet annuaire (vérifie l'application et l'annuaire)",
    "AADSTS50020": "ce compte n'est pas de cet annuaire Microsoft (« consumers » pour un compte personnel, "
                   "« organizations » pour un compte pro)",
    "AADSTS53003": "une règle d'accès conditionnel de ton organisation bloque cette connexion",
    "AADSTS7000218": "l'application Microsoft n'autorise pas les flux de clients publics (Entra › Authentification)",
    "AADSTS50076": "Microsoft demande une nouvelle vérification (double authentification) : reconnecte-toi",
    "AADSTS50079": "Microsoft demande une nouvelle vérification (double authentification) : reconnecte-toi",
}
#: les refus qui demandent qu'on se reconnecte : la connexion n'est plus présentée
_DEAD = ("invalid_grant", "interaction_required")


def application_id(client_id: str) -> str:
    """L'identifiant d'une application Microsoft (client ID), mis en forme ; vide : aucune. ``ValueError`` s'il n'en
    a pas la forme."""
    client_id = client_id.strip()
    if client_id and not _CLIENT_ID.match(client_id):
        raise ValueError("l'application Microsoft se donne par son identifiant (client ID), de la forme "
                         "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
    return client_id.lower()


def tenant_id(tenant: str) -> str:
    """Un annuaire Microsoft (``consumers``, ``organizations``, un domaine ou un GUID), vide : ``consumers`` ;
    ``ValueError`` s'il n'en a pas la forme (il entre dans l'adresse de Microsoft). Une boîte et un compte d'agenda
    (ADR 0309) le vérifient de même."""
    tenant = tenant.strip() or CONSUMERS
    if not _TENANT.match(tenant):
        raise ValueError("l'annuaire Microsoft est « consumers », « organizations », un domaine ou un identifiant")
    return tenant


class OAuthError(RuntimeError):
    """La connexion Microsoft a échoué (dit en français, sans jeton)."""


class Unreachable(OAuthError):
    """Microsoft n'a pas répondu (réseau) : ce n'est pas un refus."""


class OAuthAccount(Protocol):
    """Ce qu'une connexion lit d'un compte (une boîte, un compte d'agenda) : l'application qu'il déclare (vide : celle
    de l'instance) et son annuaire."""

    @property
    def oauth_client_id(self) -> str: ...

    @property
    def oauth_tenant(self) -> str: ...


def _refused(body: dict[str, Any]) -> str:
    """Le refus de Microsoft, en français (son code, et le début de sa description)."""
    error = str(body.get("error") or "erreur")[:60]
    code = str(body.get("error_description") or "").split(":", 1)[0].strip()
    if code in AADSTS_WORDS:
        return AADSTS_WORDS[code]
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
    """Les connexions Microsoft des comptes d'un domaine (ses boîtes, ses comptes d'agenda) : les commencer
    (``start``), où elles en sont (``state``), et le jeton d'accès d'un compte connecté (``token``)."""

    def __init__(self, grants: GrantStore | None = None, *, now: Callable[[], datetime] = lambda: datetime.now(UTC),
                 transport: httpx.AsyncBaseTransport | None = None,
                 sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
                 application: Callable[[], str] = lambda: "", scopes: str, not_signed_in: str,
                 no_application: str, label: str) -> None:
        self._grants = grants
        #: ce qu'elle demande à Microsoft, et ses mots : ceux du domaine qui s'en sert (le courrier, l'agenda)
        self._scopes = scopes
        self._not_signed_in, self._no_application, self._label = not_signed_in, no_application, label
        #: l'application de l'instance (son client ID ; vide : aucune), relue à chaque fois
        self._application = application
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
        #: prévenu quand l'attente d'un code finit (la boîte connectée, un refus, un code échu) : ce que montre
        #: ``state`` a changé (ADR 0308 : les écrans de la boîte le relisent ; posé par le serveur)
        self.on_state: Callable[[str], None] | None = None

    def _t(self) -> float:
        return self._now().timestamp()

    def _client_id(self, account: OAuthAccount) -> str:
        """L'application par laquelle cette boîte entre : la sienne si elle en déclare une, sinon celle de
        l'instance (ADR 0238) ; vide : aucune."""
        return account.oauth_client_id or self._application()

    def _grant(self, key: str, account: OAuthAccount) -> Grant | None:
        grant = self._grants.grant(key) if self._grants is not None else None
        fits = grant is not None and grant.fits(self._client_id(account), account.oauth_tenant)
        return grant if fits else None

    # ── où elle en est ──
    def state(self, key: str, account: OAuthAccount) -> SignIn:
        pending = self._pending.get(key)
        if pending is not None and pending.until > self._t():
            return SignIn(SIGNIN_PENDING, code=pending.code, url=pending.url, until=int(pending.until * 1_000_000))
        grant = self._grant(key, account)
        revoked = self._revoked.get(key)
        if grant is not None and (revoked is None or revoked[0] != grant):
            return SignIn(SIGNED_IN)
        if grant is None and not self._client_id(account):
            return SignIn(SIGNIN_NEEDED, error=self._no_application)
        stale = revoked[1] if grant is not None and revoked is not None else ""
        return SignIn(SIGNIN_NEEDED, error=self._failed.get(key) or stale)

    # ── le jeton d'accès ──
    async def token(self, key: str, account: OAuthAccount) -> str:
        """Le jeton d'accès d'une boîte connectée (renouvelé s'il expire bientôt) ; ``OAuthError`` si elle ne l'est
        pas, ou plus."""
        async with self._locks.setdefault(key, asyncio.Lock()):
            if self._grants is None:
                raise OAuthError(NO_STORE)
            grant = self._grant(key, account)
            if grant is None:
                raise OAuthError(self._not_signed_in if self._client_id(account) else self._no_application)
            revoked = self._revoked.get(key)
            # Microsoft ne la renouvelle plus : on ne la lui représente pas à chaque relevé
            if revoked is not None and revoked[0] == grant:
                raise OAuthError(revoked[1])
            held = self._access.get(key)
            if held is not None and held[2] == grant and held[1] - MARGIN_S > self._t():
                return held[0]
            got = await self._post(grant.tenant, "token", {"grant_type": "refresh_token", "client_id": grant.client_id,
                                                           "refresh_token": grant.refresh, "scope": self._scopes})
            if got.get("error"):
                why = _refused(got)
                if got.get("error") in _DEAD:
                    self._revoked[key] = (grant, why)
                    log.warning("%s : la connexion Microsoft de %s ne vaut plus", self._label, key)
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
            await self._grants.save_grant(key, grant)
        try:
            lasts = float(got.get("expires_in") or 3600)
        except (TypeError, ValueError):
            lasts = 3600.0
        self._access[key] = (access, self._t() + lasts, grant)
        self._revoked.pop(key, None)
        self._failed.pop(key, None)
        return access

    def drop(self, key: str) -> None:
        """Le jeton d'accès de ce compte oublié (Microsoft vient de le refuser) : le prochain se renouvelle."""
        self._access.pop(key, None)

    # ── se connecter ──
    async def start(self, key: str, account: OAuthAccount) -> SignIn:
        """Demande un code à Microsoft et attend, en tâche de fond, que la personne l'entre ; rend le code à
        montrer. Une connexion en attente pour la même boîte est remplacée."""
        client_id = self._client_id(account)
        if not client_id:
            raise OAuthError(self._no_application)
        if self._grants is None:
            raise OAuthError(NO_STORE)
        got = await self._post(account.oauth_tenant, "devicecode", {"client_id": client_id, "scope": self._scopes})
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
        pending.task = asyncio.create_task(self._wait(key, client_id, account.oauth_tenant, device, interval,
                                                      pending), name=f"mail-oauth-{key}")
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
                log.info("%s : %s est connectée à Microsoft", self._label, key)
                return
            self._failed[key] = EXPIRED
        except OAuthError as exc:
            self._failed[key] = str(exc)
        except Exception as exc:  # garder la connexion a échoué (les réglages) : dit, jamais une tâche morte en silence
            log.warning("%s : la connexion Microsoft de %s n'a pas pu être gardée (%s)", self._label, key,
                        type(exc).__name__)
            self._failed[key] = "la connexion n'a pas pu être gardée"
        finally:
            if self._pending.get(key) is pending:
                del self._pending[key]
                self._said(key)

    def _said(self, key: str) -> None:
        if self.on_state is None:
            return
        try:
            self.on_state(key)
        except Exception:  # un écouteur en panne ne change rien à la connexion
            log.exception("courrier : la fin d'une connexion Microsoft n'a pas pu se dire (%s)", key)

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
