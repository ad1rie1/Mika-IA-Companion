"""Joindre un agenda en ligne (ADR 0309, lot 2) : l'API JSON de Google Agenda et celle de Microsoft Graph, avec un
jeton porteur, ses pannes dites en mots (``AgendaError``).

- **Leurs hôtes seulement** (``Api.hosts`` : ``www.googleapis.com``, ``graph.microsoft.com``), en https : une adresse
  qu'une réponse donnerait ailleurs (le ``@odata.nextLink`` de Graph, une redirection) est refusée en mots, jamais
  suivie. Les points OAuth (``oauth2.googleapis.com``, ``login.microsoftonline.com``) sont ceux de leur connexion
  (``adapters/signin/google.py``, ``adapters/signin/microsoft.py``), à des adresses fixes.
- **Le jeton** vient de la connexion du compte, à chaque requête (``Session``) ; refusé (401), il est renouvelé une
  fois ; refusé encore, le compte est à reconnecter (``SignInNeeded``, en mots).
- **Des bornes** : une réponse lue au plus jusqu'à ``BODY_MAX`` octets, un délai par requête.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable, Collection, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from mika.adapters.agenda.http import USER_AGENT
from mika.ports.agenda import AgendaError

TIMEOUT = httpx.Timeout(30.0, connect=10.0)
#: une réponse lue au plus jusqu'à tant d'octets
BODY_MAX = 20_000_000

#: le jeton d'un compte : ``force`` vrai, le précédent vient d'être refusé (il se renouvelle)
TokenOf = Callable[[bool], Awaitable[str]]


class SignInNeeded(AgendaError):
    """Le fournisseur ne reconnaît plus la connexion (révoquée, expirée, jamais faite) : le compte est à
    reconnecter."""


@dataclass(frozen=True, slots=True)
class Answer:
    """Une réponse : son code, ses en-têtes, son JSON (``None`` : pas de corps, ou illisible)."""

    status: int
    headers: httpx.Headers
    data: Any

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def error(self) -> tuple[str, str]:
        """(code, message) de l'erreur que la réponse décrit (Graph : ``error.code`` ; Google : la raison de sa
        première erreur, sinon son ``status``), bornés."""
        err = self.data.get("error") if isinstance(self.data, dict) else None
        if isinstance(err, str):
            return err[:80], str(self.data.get("error_description") or "")[:300]
        if not isinstance(err, dict):
            return "", ""
        code = str(err.get("code") or "")
        errors = err.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict) and errors[0].get("reason"):
            code = str(errors[0]["reason"])
        elif code.isdigit() and err.get("status"):
            code = str(err["status"])
        return code[:80], str(err.get("message") or "")[:300]


class Api:
    """Un service d'agendas en ligne : son nom (dans les mots d'une panne), ses hôtes, ses requêtes (``transport`` :
    les tests en posent un faux)."""

    def __init__(self, name: str, hosts: Collection[str], *, transport: httpx.AsyncBaseTransport | None = None,
                 timeout: httpx.Timeout = TIMEOUT) -> None:
        self.name = name
        self.hosts = frozenset(h.lower() for h in hosts)
        self._transport = transport
        self._timeout = timeout

    def allowed(self, url: str) -> bool:
        """Cette adresse est-elle celle du service (https, un de ses hôtes, son port) ?"""
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            return False
        return parts.scheme == "https" and (parts.hostname or "").lower() in self.hosts and port in (None, 443)

    @asynccontextmanager
    async def session(self, token: TokenOf) -> AsyncIterator[Session]:
        """Des requêtes pour un compte (``token`` : son jeton), sur une même connexion."""
        client = httpx.AsyncClient(transport=self._transport, timeout=self._timeout, follow_redirects=False,
                                   headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            yield Session(self, client, token)
        finally:
            await client.aclose()


class Session:
    """Les requêtes d'un compte : son jeton à chacune, renouvelé une fois s'il est refusé."""

    def __init__(self, api: Api, client: httpx.AsyncClient, token: TokenOf) -> None:
        self.api = api
        self._client = client
        self._token = token

    async def send(self, method: str, url: str, *, params: Mapping[str, Any] | None = None, body: Any = None,
                   headers: Mapping[str, str] | None = None) -> Answer:
        """Une requête (``body`` : son JSON) ; une adresse qui n'est pas celle du service est refusée, une
        redirection n'est pas suivie, une panne du réseau se dit en mots. Le code de la réponse n'est pas jugé ici
        (sauf un jeton refusé deux fois) : chaque fournisseur dit le sien."""
        if not self.api.allowed(url):
            raise AgendaError(f"{self.api.name} renvoie vers une adresse qui n'est pas la sienne : refusé")
        answer = await self._once(method, url, params, body, headers, await self._token(False))
        if answer.status == 401:  # un jeton refusé : renouvelé une fois
            answer = await self._once(method, url, params, body, headers, await self._token(True))
            if answer.status == 401:
                raise SignInNeeded(f"à reconnecter : {self.api.name} refuse l'accès de ce compte")
        if 300 <= answer.status < 400:
            raise AgendaError(f"{self.api.name} renvoie ailleurs (réponse {answer.status}) : pas suivi")
        return answer

    async def _once(self, method: str, url: str, params: Mapping[str, Any] | None, body: Any,
                    headers: Mapping[str, str] | None, token: str) -> Answer:
        sent = {"Authorization": f"Bearer {token}", **(headers or {})}
        content = None
        if body is not None:
            content = json.dumps(body, ensure_ascii=False).encode("utf-8")
            sent["Content-Type"] = "application/json"
        name = self.api.name
        target = httpx.URL(url)
        if params:  # ajoutés à ceux de l'adresse (un ``@odata.nextLink`` porte les siens), jamais à leur place
            target = target.copy_merge_params({k: str(v) for k, v in params.items()})
        try:
            async with self._client.stream(method, target, content=content, headers=sent) as resp:
                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > BODY_MAX:
                        raise AgendaError(f"{name} renvoie plus de {BODY_MAX // 1_000_000} Mo : pas lu")
                    chunks.append(chunk)
                raw = b"".join(chunks)
                status, got = resp.status_code, resp.headers
        except httpx.TimeoutException:
            raise AgendaError(f"{name} ne répond pas à temps") from None
        except httpx.ConnectError:
            raise AgendaError(f"{name} est injoignable") from None
        except httpx.HTTPError as exc:
            raise AgendaError(f"{name} a coupé la connexion ({type(exc).__name__})") from None
        data: Any = None
        if raw.strip():
            try:
                data = json.loads(raw)
            except ValueError:
                data = None
        return Answer(status, got, data)


def refused_words(name: str, answer: Answer, what: str) -> str:
    """Ce qu'un refus dit en commun chez les deux : le compte à reconnecter, trop de requêtes, une panne ; vide pour
    le reste (chacun dit le sien)."""
    if answer.status == 429:
        return f"{name} demande d'attendre (trop de requêtes)"
    if answer.status >= 500:
        return f"{name} est en panne (réponse {answer.status})"
    if answer.status in (404, 410):
        return f"{what} n'existe plus chez {name} (supprimé ailleurs ?) : la copie est relue"
    if answer.status == 412:
        return (f"{what} a changé chez {name} pendant qu'on l'écrivait : la copie est relue, redis ce que tu voulais "
                "y changer")
    return ""


__all__ = ["BODY_MAX", "USER_AGENT", "Answer", "Api", "Session", "SignInNeeded", "TokenOf", "refused_words"]
