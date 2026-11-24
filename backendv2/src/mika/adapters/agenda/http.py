"""Ce que l'agenda demande aux serveurs du dehors (ADR 0309, lot 1) : un abonnement iCal, un serveur CalDAV — par
``httpx``, une requête à la fois, ses pannes dites en mots (``AgendaError``).

- **L'adresse** (``server_url``) : ``webcal://`` se lit ``https://`` (``webcals://`` aussi) ; un nom nu reçoit
  ``https://``. ``server_host`` est l'hôte qu'un compte fait joindre : l'API par personne le vérifie quand une
  personne qui n'est pas opératrice le donne (Internet seulement : ``app/me/hosts.py::public_only``), comme le
  serveur d'une boîte.
- **Ne pas quitter Internet** : une redirection, ou une adresse qu'un serveur CalDAV donne (sa maison d'agendas, ses
  agendas), qui mène à un autre hôte que celui du compte, doit mener à une machine publique — la règle
  d'``adapters/addresses.py`` (ADR 0228), celle des flux : l'hôte est résolu une fois, chacune de ses adresses doit
  être publique et pas celle de la machine, et la connexion se fait vers l'adresse vérifiée. L'hôte du compte, lui,
  est celui que son propriétaire a choisi (une opératrice peut viser DavMail sur cette machine).
- **Le mot de passe ne part que chez son serveur** : vers l'hôte du compte, ou un hôte du même domaine (iCloud
  répond depuis ``pNN-caldav.icloud.com``) ; jamais ailleurs, même redirigé. Basic d'abord, Digest si le serveur
  le demande.
- **Des bornes** : une réponse lue au plus jusqu'à ``limit`` octets (au-delà, refusée en mots), cinq redirections,
  un délai par requête.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import AsyncIterator, Awaitable, Callable, Collection, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from mika.adapters.addresses import IP, LOCAL, MACHINE, PORT, PRIVATE, refusal
from mika.ports.agenda import AgendaError

USER_AGENT = "Mika/2 (agenda)"
#: au plus tant de redirections par requête
MAX_REDIRECTS = 5
#: une réponse lue au plus jusqu'à tant d'octets (sauf ``limit`` dit)
BODY_MAX = 20_000_000
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_REDIRECTS = (301, 302, 303, 307, 308)

#: une résolution de nom : ``(hôte, port)`` → les adresses IP
Resolver = Callable[[str, int], Awaitable[Sequence[str]]]

#: ce qu'un refus dit, selon la règle d'``adapters/addresses.py`` (jamais l'adresse entière : elle peut être secrète)
REFUSED = {PRIVATE: "mène à une machine privée ou locale", MACHINE: "mène à cette machine elle-même",
           PORT: "vise le port de ce serveur lui-même"}


class TooBig(AgendaError):
    """Une réponse plus grosse que ce qu'on lit."""

    def __init__(self, what: str, limit: int) -> None:
        super().__init__(f"{what} renvoie plus de {limit // 1_000_000} Mo : pas lu")
        self.limit = limit


def server_url(url: str) -> str:
    """L'adresse telle qu'on la demande : ``webcal://`` et ``webcals://`` lus ``https://`` ; un nom sans schéma
    reçoit ``https://``. Vide : vide."""
    url = (url or "").strip()
    if not url:
        return ""
    lower = url.lower()
    for prefix in ("webcals://", "webcal://"):
        if lower.startswith(prefix):
            return "https://" + url[len(prefix):]
    if "://" not in url:
        return "https://" + url
    return url


def server_host(url: str) -> str:
    """L'hôte qu'un compte fait joindre (sans le port), pour la règle d'Internet seulement ; vide s'il n'y en a pas."""
    try:
        return (urlsplit(server_url(url)).hostname or "").lower()
    except ValueError:
        return ""


def _same_domain(host: str, start: str) -> bool:
    """``host`` est-il l'hôte du compte, ou un hôte de son domaine (``pNN-caldav.icloud.com`` pour
    ``caldav.icloud.com``) ? Une adresse IP n'a que elle-même."""
    host, start = host.lower().rstrip("."), start.lower().rstrip(".")
    if host == start:
        return True
    try:
        ipaddress.ip_address(start.strip("[]"))
        return False
    except ValueError:
        pass
    labels = start.split(".")
    parent = ".".join(labels[1:]) if len(labels) >= 3 else start
    return host == parent or host.endswith("." + parent)


async def system_resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


@dataclass(frozen=True, slots=True)
class Reply:
    """Une réponse : son code, ses en-têtes, son corps (borné), l'adresse qui a répondu (après les redirections)."""

    status: int
    headers: httpx.Headers
    body: bytes
    url: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


def status_words(status: int, host: str, what: str) -> str:
    """Un code de réponse en mots, pour la fiche du compte et la santé."""
    if status == 401:
        return f"identifiant ou mot de passe refusé par {host}"
    if status == 403:
        return f"{host} refuse l'accès"
    if status in (404, 410):
        return f"{what} introuvable à cette adresse ({host})"
    if status in (405, 501):
        return f"{host} ne sait pas répondre à cette demande à cette adresse"
    if status == 429:
        return f"{host} demande d'attendre (trop de requêtes)"
    if status >= 500:
        return f"{host} est en panne (réponse {status})"
    return f"{host} répond {status}"


class Web:
    """Les requêtes de l'agenda vers le dehors : ``transport`` (les tests en posent un faux), ``resolve`` et
    ``local`` (la résolution et les adresses de la machine, pour la règle d'Internet seulement), ``server_ports``
    (les ports où Mika écoute)."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None, resolve: Resolver | None = None,
                 local: Collection[IP] | None = None, server_ports: Collection[int] | None = None,
                 timeout: httpx.Timeout = TIMEOUT) -> None:
        self._transport = transport
        self._resolve = resolve or system_resolve
        self._local = local
        self._server_ports = server_ports
        self._timeout = timeout

    @asynccontextmanager
    async def session(self, start: str, *, username: str = "", password: str = "", what: str = "le serveur",
                      internet: bool = False) -> AsyncIterator[Session]:
        """Une suite de requêtes vers le serveur d'un compte (``start`` : son adresse), sur une même connexion.
        ``internet`` : l'hôte du compte lui-même est revérifié (``public``) à chaque requête et joint à l'adresse
        vérifiée — un compte qu'une personne qui n'est pas opératrice a réglé (un nom peut changer de réponse entre
        l'enregistrement et la synchro)."""
        client = httpx.AsyncClient(transport=self._transport, timeout=self._timeout, follow_redirects=False,
                                   headers={"User-Agent": USER_AGENT})
        try:
            yield Session(self, client, server_url(start), username=username, password=password, what=what,
                          internet=internet)
        finally:
            await client.aclose()

    async def public(self, url: str) -> tuple[str, dict[str, str], dict[str, Any]]:
        """L'adresse à demander pour un hôte qui n'est pas celui du compte, vérifiée (``refusal``) : l'hôte résolu,
        chacune de ses adresses publique et pas celle de la machine, le port pas celui de Mika ; la requête part vers
        l'adresse vérifiée (l'hôte reste dans ``Host`` et dans le SNI)."""
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if not host:
            raise AgendaError("une adresse sans hôte")
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            ips: Sequence[str] = [str(literal)]
        else:
            try:
                ips = await self._resolve(host, port)
            except (OSError, UnicodeError):
                raise AgendaError(f"{host} : nom inconnu") from None
        if not ips:
            raise AgendaError(f"{host} : nom inconnu")
        local = self._local if self._local is not None else await asyncio.to_thread(LOCAL.get)
        try:
            resolved = [ipaddress.ip_address(ip.split("%", 1)[0]) for ip in ips]
        except ValueError:
            raise AgendaError(f"le serveur renvoie vers {host}, qui {REFUSED[PRIVATE]} : refusé") from None
        why = refusal(resolved, port, local=local, server_ports=self._server_ports)
        if why is not None:
            raise AgendaError(f"le serveur renvoie vers {host}, qui {REFUSED[why]} : refusé")
        ip = ips[0]
        netloc = (f"[{ip}]" if ":" in ip else ip) + (f":{parts.port}" if parts.port else "")
        extensions = {"sni_hostname": host} if parts.scheme == "https" and literal is None else {}
        target = urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
        return target, {"Host": parts.netloc.rsplit("@", 1)[-1]}, extensions


class Session:
    """Des requêtes vers le serveur d'un compte : ses redirections suivies à la main, ce qui quitte son hôte vérifié,
    son mot de passe seulement chez lui."""

    def __init__(self, web: Web, client: httpx.AsyncClient, start: str, *, username: str, password: str,
                 what: str, internet: bool = False) -> None:
        self.web = web
        self.client = client
        self.start = start
        self.host = server_host(start)
        self.what = what
        self.internet = internet
        self._credentials = (username, password) if username or password else None
        self._digest = False

    def url(self, href: str, base: str | None = None) -> str:
        """Une adresse que le serveur donne (un chemin, ou une adresse entière), rendue entière."""
        return urljoin(base or self.start, href)

    def _auth(self, host: str) -> httpx.Auth | None:
        if self._credentials is None or not _same_domain(host, self.host):
            return None
        user, password = self._credentials
        return httpx.DigestAuth(user, password) if self._digest else httpx.BasicAuth(user, password)

    async def send(self, method: str, url: str, *, headers: Mapping[str, str] | None = None,
                   body: bytes | None = None, limit: int = BODY_MAX) -> Reply:
        """Une requête, ses redirections suivies (cinq au plus) ; une panne du réseau dite en mots. Le code de la
        réponse n'est pas jugé ici : chacun dit le sien (``status_words``)."""
        current = self.url(url)
        for _hop in range(MAX_REDIRECTS + 1):
            parts = urlsplit(current)
            if parts.scheme.lower() not in ("http", "https"):
                raise AgendaError("une adresse en http ou https seulement")
            host = (parts.hostname or "").lower()
            if host == self.host and not self.internet:
                target, extra, extensions = current, {}, {}
            else:
                target, extra, extensions = await self.web.public(current)
            reply = await self._once(method, target, {**(headers or {}), **extra}, extensions, body, limit, host)
            if reply.status == 401 and not self._digest and self._auth(host) is not None \
                    and "digest" in reply.headers.get("www-authenticate", "").lower():
                self._digest = True
                reply = await self._once(method, target, {**(headers or {}), **extra}, extensions, body, limit, host)
            if reply.status in _REDIRECTS and reply.headers.get("location"):
                current = urljoin(current, reply.headers["location"])
                if reply.status == 303:
                    method, body = "GET", None
                continue
            return Reply(reply.status, reply.headers, reply.body, current)
        raise AgendaError(f"{self.host} redirige trop de fois")

    async def _once(self, method: str, target: str, headers: Mapping[str, str], extensions: dict[str, Any],
                    body: bytes | None, limit: int, host: str) -> Reply:
        try:
            async with self.client.stream(method, target, headers=dict(headers), content=body,
                                          auth=self._auth(host), extensions=extensions) as resp:
                chunks: list[bytes] = []
                size = 0
                if resp.status_code not in _REDIRECTS:
                    async for chunk in resp.aiter_bytes():
                        size += len(chunk)
                        if size > limit:
                            raise TooBig(self.what, limit)
                        chunks.append(chunk)
                return Reply(resp.status_code, resp.headers, b"".join(chunks), target)
        except httpx.TimeoutException:
            raise AgendaError(f"{host} ne répond pas à temps") from None
        except httpx.ConnectError as exc:
            if "CERTIFICATE" in str(exc).upper() or "SSL" in str(exc).upper():
                raise AgendaError(f"le certificat de {host} est refusé") from None
            raise AgendaError(f"{self.what} est injoignable ({host})") from None
        except httpx.HTTPError as exc:
            raise AgendaError(f"{host} a coupé la connexion ({type(exc).__name__})") from None


__all__ = ["BODY_MAX", "MAX_REDIRECTS", "REFUSED", "USER_AGENT", "Reply", "Session", "TooBig", "Web", "server_host",
           "server_url", "status_words", "system_resolve"]
