"""Firebase Cloud Messaging, par son API HTTP v1 (ADR 0077).

Ce qui parle à Google au nom du serveur : la clé d'un **compte de service** du projet Firebase (le fichier JSON que
la console Firebase télécharge), collée dans la console de Mika (Réglages › Canaux › Notifications du téléphone)
et chiffrée au repos. On en tire un jeton d'accès OAuth 2 — une assertion JWT signée RS256, échangée contre un
jeton d'une heure, gardé jusqu'à une minute de sa fin. Chaque notification est un message **de données** de
priorité haute (pas un message « notification » que le système afficherait lui-même) : l'application le reçoit
même fermée, le déchiffre et l'affiche.

Rien ne lève vers l'appelant : un envoi rend ``SendResult``. ``GONE`` dit que le jeton du téléphone ne vaut plus
(application désinstallée, données effacées, autre projet Firebase) : on l'oublie. Un 401 ou un 403 sur l'envoi
redemande une fois un jeton d'accès (une clé changée entre-temps) ; le reste est un échec dit au journal, jamais
réessayé — le message est dans le fil, la prochaine ouverture de l'application le montre.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

log = logging.getLogger("mika.push")

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
TOKEN_URI = "https://oauth2.googleapis.com/token"
SEND_URL = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"
#: la durée demandée pour un jeton d'accès (Google n'en donne pas plus d'une heure), et la marge avant sa fin
ACCESS_TTL_S = 3600
ACCESS_MARGIN_S = 60
TIMEOUT_S = 15.0
#: un jeton Firebase de téléphone, au plus (ils font ~160 caractères)
MAX_DEVICE_TOKEN = 4096

SENT = "sent"
#: le jeton du téléphone ne vaut plus : on l'oublie
GONE = "gone"
FAILED = "failed"
#: aucune clé de compte de service : rien n'est parti
UNCONFIGURED = "unconfigured"
#: le code d'erreur de l'API qui dit qu'un jeton de téléphone est mort (application désinstallée, données effacées)
_GONE_CODES = frozenset({"UNREGISTERED"})
#: la clé du serveur n'est pas celle du projet Firebase de l'application : une erreur de configuration, qui ne
#: dit rien du téléphone — on ne l'oublie pas, une clé corrigée le notifiera
SENDER_ID_MISMATCH = "SENDER_ID_MISMATCH"


@dataclass(frozen=True, slots=True)
class ServiceAccount:
    project_id: str
    client_email: str
    private_key: rsa.RSAPrivateKey
    token_uri: str = TOKEN_URI
    key_id: str = ""


@dataclass(frozen=True, slots=True)
class SendResult:
    outcome: str
    detail: str = ""


def parse_service_account(text: str) -> ServiceAccount:
    """La clé d'un compte de service (le JSON de la console Firebase) ; ``ValueError`` en français sinon."""
    try:
        data = json.loads(text)
    except ValueError:
        raise ValueError("Ce n'est pas du JSON : colle le fichier de clé du compte de service tel quel.") from None
    if not isinstance(data, dict) or data.get("type") != "service_account":
        raise ValueError("Ce JSON n'est pas une clé de compte de service (« type »: « service_account »). Elle se "
                         "télécharge dans la console Firebase : Paramètres du projet › Comptes de service.")
    missing = [k for k in ("project_id", "client_email", "private_key") if not str(data.get(k) or "").strip()]
    if missing:
        raise ValueError(f"Il manque à cette clé : {', '.join(missing)}.")
    try:
        key = serialization.load_pem_private_key(str(data["private_key"]).encode(), password=None)
    except (ValueError, TypeError):
        raise ValueError("La clé privée de ce compte de service ne se lit pas.") from None
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("La clé privée de ce compte de service n'est pas une clé RSA.")
    token_uri = str(data.get("token_uri") or TOKEN_URI)
    if not token_uri.startswith("https://"):
        raise ValueError("L'adresse « token_uri » de cette clé n'est pas en https.")
    return ServiceAccount(str(data["project_id"]).strip(), str(data["client_email"]).strip(), key, token_uri,
                          str(data.get("private_key_id") or ""))


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def assertion(account: ServiceAccount, now: float) -> str:
    """L'assertion JWT (RS256) qu'on échange contre un jeton d'accès."""
    header: dict[str, Any] = {"alg": "RS256", "typ": "JWT"}
    if account.key_id:
        header["kid"] = account.key_id
    issued = int(now)
    claims = {"iss": account.client_email, "scope": SCOPE, "aud": account.token_uri, "iat": issued,
              "exp": issued + ACCESS_TTL_S}
    signing = f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}." \
              f"{_b64url(json.dumps(claims, separators=(',', ':')).encode())}"
    signature = account.private_key.sign(signing.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing}.{_b64url(signature)}"


def _error_code(response: httpx.Response) -> str:
    """Le code d'erreur d'une réponse : FCM (``UNREGISTERED``…, sinon son statut ``NOT_FOUND``…) ou OAuth
    (``{"error": "invalid_grant"}`` : une chaîne) ; vide si la réponse n'en dit rien."""
    try:
        body = response.json()
    except ValueError:
        return ""
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, str):
        return error
    if not isinstance(error, dict):
        return ""
    for detail in error.get("details") or ():
        if isinstance(detail, dict) and detail.get("errorCode"):
            return str(detail["errorCode"])
    return str(error.get("status") or "")


class FcmSender:
    """Envoie des messages de données Firebase. ``credentials`` rend le JSON de la clé du compte de service (vide :
    pas configuré) ; relu à chaque envoi, une clé changée dans la console vaut dès le message suivant."""

    def __init__(self, credentials: Callable[[], str], *, now: Callable[[], float] = time.time,
                 client: httpx.AsyncClient | None = None) -> None:
        self._credentials = credentials
        self._now = now
        self._http = client or httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False)
        self._parsed: tuple[str, ServiceAccount | None] = ("", None)
        self._access: tuple[str, str, float] = ("", "", 0.0)  # (clé, jeton, fin)

    def account(self) -> ServiceAccount | None:
        """Le compte de service en vigueur (lu une fois par texte de clé) ; ``None`` : pas de clé, ou illisible."""
        try:
            text = self._credentials().strip()
        except Exception as exc:  # une lecture de réglage impossible : comme sans clé, dit au journal
            log.warning("notifications : clé Firebase illisible (%r)", exc)
            return None
        if not text:
            return None
        if text != self._parsed[0]:
            try:
                parsed: ServiceAccount | None = parse_service_account(text)
            except ValueError as exc:
                log.warning("notifications : %s", exc)
                parsed = None
            self._parsed = (text, parsed)
        return self._parsed[1]

    def configured(self) -> bool:
        return self.account() is not None

    async def send(self, device_token: str, data: Mapping[str, str]) -> SendResult:
        account = self.account()
        if account is None:
            return SendResult(UNCONFIGURED)
        message = {"message": {"token": device_token, "data": dict(data), "android": {"priority": "HIGH"}}}
        url = SEND_URL.format(project=account.project_id)
        for attempt in (1, 2):
            try:
                token = await self._access_token(account, fresh=attempt == 2)
            except (httpx.HTTPError, ValueError) as exc:
                return SendResult(FAILED, f"jeton d'accès refusé : {exc}"[:300])
            try:
                response = await self._http.post(url, json=message, headers={"Authorization": f"Bearer {token}"})
            except httpx.HTTPError as exc:
                return SendResult(FAILED, f"Firebase injoignable : {exc!r}"[:300])
            if response.status_code == 200:
                return SendResult(SENT)
            code = _error_code(response)
            if code == SENDER_ID_MISMATCH:
                return SendResult(FAILED, "la clé du serveur n'est pas celle du projet Firebase de l'application "
                                          "(SENDER_ID_MISMATCH)")
            if response.status_code == 404 or code in _GONE_CODES:
                return SendResult(GONE, code or str(response.status_code))
            if response.status_code in (401, 403) and attempt == 1:
                continue  # une clé changée, un jeton révoqué : un jeton d'accès neuf, une fois
            return SendResult(FAILED, f"HTTP {response.status_code} {code}".strip())
        return SendResult(FAILED, "accès refusé")

    async def _access_token(self, account: ServiceAccount, *, fresh: bool) -> str:
        now = self._now()
        key, token, until = self._access
        if not fresh and key == account.client_email and token and now < until - ACCESS_MARGIN_S:
            return token
        response = await self._http.post(account.token_uri, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion(account, now)})
        if response.status_code != 200:
            raise ValueError(f"HTTP {response.status_code} {_error_code(response)}".strip())
        body = response.json()
        token = str(body.get("access_token") or "")
        if not token:
            raise ValueError("réponse sans jeton d'accès")
        self._access = (account.client_email, token, now + float(body.get("expires_in") or ACCESS_TTL_S))
        return token

    async def aclose(self) -> None:
        await self._http.aclose()
