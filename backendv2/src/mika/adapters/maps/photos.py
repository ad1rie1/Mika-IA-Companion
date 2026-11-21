"""Les photos relayées (ADR 0245) : celles des fiches DATAtourisme, et celles du cache des avis (Google Places,
ADR 0256), servies par ce serveur — le navigateur et le téléphone ne joignent jamais un autre hôte.

**Une référence** (``p:<hash>``, ``photo_ref``) ne vient que des données : chaque source (``PhotoSource``) dit l'adresse
d'une photo qu'elle a reçue, et la relève ne va chercher que celle-là — jamais une adresse donnée par un client (pas
de SSRF). Une référence qu'aucune source ne connaît est refusée. Une source branche ses photos en les inscrivant chez
elle (la base des données touristiques : sa table ``photo``) et en répondant à ``photo_origin(ref)`` ; ``PhotoRelay``
les interroge dans l'ordre (``add_source``). Une source dont l'adresse ne se garde pas (Google : elle se demande à son
API, un appel compté) la donne au moment de la relève (``PhotoOrigin.resolve``), et peut borner les hôtes où l'image se
cherche (``PhotoOrigin.hosts``, redirections comprises).

**La relève** : l'adresse en http(s), sur un hôte qui n'est ni cette machine ni le réseau local (redirections suivies
à la main, trois au plus, chacune vérifiée), une image (JPEG, PNG, WebP, GIF : lue à ses premiers octets, jamais au
seul ``Content-Type``) d'au plus ``PHOTO_MAX_BYTES``. **La garde** porte deux fois : sur l'adresse écrite
(``public_url`` : un nom d'hôte, ou une adresse publique — jamais une forme héritée comme « 127.1 », « 0177.0.0.1 »,
« 0x7f.1 » ou un entier, que le système lirait comme une adresse), puis sur l'adresse résolue, au moment de la
connexion (``guarded_transport`` : chaque saut se connecte à l'adresse que le DNS vient de rendre, seulement si toutes
celles qu'il rend sont publiques, ``joinable`` — un nom qui change d'adresse entre la vérification et la connexion ne
passe pas). Elle est gardée dans ``cartes/photos/`` (un fichier par
référence), borné à ``CACHE_MAX_BYTES`` en tout : les moins récemment servies partent d'abord. **Les droits** : une
photo dont la fin des droits est passée (``rights_end``, DATAtourisme) ne se sert plus, et son fichier s'efface."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import ipaddress
import os
import re
import socket
import sqlite3
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx

from mika.adapters.maps.pace import Pace, client
from mika.adapters.maps.tiles import read_capped
from mika.ports.maps import MapsBadMedia, MapsNotFound, MapsUnavailable

#: les adresses d'un hôte (son nom, son port) : le DNS du système par défaut ; un faux dans les tests
Resolver = Callable[[str, int], Sequence[str]]

PHOTO_MAX_BYTES = 8 * 1024 * 1024
CACHE_MAX_BYTES = 512 * 1024 * 1024
#: après un dépassement, le cache redescend à cette part de sa borne
CACHE_LOW = 0.9
TIMEOUT_S = 20.0
PER_SECOND = 4.0
REDIRECTS_MAX = 3
REF = re.compile(r"^p:([0-9a-f]{32})$")
UNKNOWN = "Cette photo n'est pas connue de ce serveur."
EXPIRED = "Les droits de cette photo ont pris fin : elle ne se montre plus."
OUT_OF_REACH = "Cette photo est à une adresse qu'on ne joint pas."
UNWRITTEN = "Le cache de la carte ne s'écrit pas en ce moment : cette photo n'a pas pu se relever."
#: les anciennes adresses locales au site (IPv6, abandonnées mais encore routables chez certains)
_SITE_LOCAL = ipaddress.ip_network("fec0::/10")
#: le type d'une image, d'après ses premiers octets
_MAGIC = ((b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG\r\n\x1a\n", "image/png"), (b"GIF87a", "image/gif"),
          (b"GIF89a", "image/gif"))


def photo_ref(url: str) -> str:
    """La référence d'une photo : l'empreinte de son adresse (la même partout, pour toutes les sources)."""
    return "p:" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


def media_of(head: bytes) -> str:
    """Le type d'une image d'après ses premiers octets ; vide : ce n'en est pas une qu'on sert."""
    for magic, media in _MAGIC:
        if head.startswith(magic):
            return media
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return ""


@dataclass(frozen=True, slots=True)
class PhotoOrigin:
    """D'où vient une photo : son adresse, sa source (``datatourisme``, ``google``), la fin de ses droits (ISO 8601,
    vide : sans fin) ; ``resolve`` : l'adresse demandée au moment de la relève, quand elle ne se garde pas (``url``
    vide ; seulement si la photo n'est pas déjà gardée) ; ``hosts`` : les seuls hôtes où l'image se cherche (et leurs
    sous-domaines), redirections comprises — vide : tout hôte public."""

    url: str
    source: str
    rights_end: str = ""
    resolve: Callable[[], Awaitable[str]] | None = None
    hosts: tuple[str, ...] = ()


class PhotoSource(Protocol):
    def photo_origin(self, ref: str) -> PhotoOrigin | None:
        """L'origine d'une photo que cette source a reçue ; ``None`` : elle ne la connaît pas. Appelée hors de la
        boucle (elle peut lire une base)."""
        ...


def public_url(url: str) -> bool:
    """Une adresse qu'on peut joindre, telle qu'écrite : http(s), un nom d'hôte ou une adresse publique — ni cette
    machine, ni le réseau local, ni une adresse réservée. Un hôte qui n'est pas une adresse doit être un nom (des
    labels, le dernier commençant par une lettre) : « 127.1 », « 0177.0.0.1 », « 0x7f.1 », « 2130706433 » ne passent
    pas, le système les lirait comme une adresse. L'adresse qu'un nom résout se juge à la connexion
    (``guarded_transport``)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").rstrip(".").lower()
    if parts.scheme not in ("http", "https") or not host or parts.username or parts.password:
        return False
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa")):
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        labels = host.split(".")
        return len(labels) >= 2 and all(labels) and labels[-1][:1].isalpha()
    return joinable(host)


def joinable(address: str) -> bool:
    """Une adresse IP qu'on joint : publique — ni cette machine, ni le réseau local, ni locale au lien ou au site, ni
    multidiffusion, ni réservée, ni non spécifiée ; une IPv4 cachée dans une IPv6 (mappée, 6to4, Teredo) se juge
    elle-même. Ce qui n'est pas une adresse : non."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    inner: list[ipaddress.IPv4Address] = []
    if isinstance(ip, ipaddress.IPv6Address):
        if ip in _SITE_LOCAL:
            return False
        inner = [a for a in (ip.ipv4_mapped, ip.sixtofour, ip.teredo[1] if ip.teredo else None) if a is not None]
    return ip.is_global and not (ip.is_multicast or ip.is_private or ip.is_reserved or ip.is_loopback
                                 or ip.is_link_local or ip.is_unspecified) and all(joinable(str(a)) for a in inner)


def resolve_host(host: str, port: int) -> list[str]:
    """Les adresses d'un hôte, par le DNS du système (une adresse : elle-même) ; à appeler hors de la boucle."""
    return list(dict.fromkeys(str(info[4][0]) for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))


class _PublicOnly(httpcore.AsyncNetworkBackend):
    """Le réseau du relais : chaque connexion part vers l'adresse que l'hôte résout à cet instant, et seulement si toutes
    celles qu'il résout sont publiques (``joinable``) — la vérification et la connexion portent sur la même réponse du
    DNS. ``inner`` : le réseau du système (un faux dans les tests)."""

    def __init__(self, resolve: Resolver, inner: httpcore.AsyncNetworkBackend | None = None) -> None:
        self._resolve = resolve
        self._inner = inner or httpcore.AnyIOBackend()

    async def connect_tcp(self, host: str, port: int, timeout: float | None = None, local_address: str | None = None,
                          socket_options: Any = None) -> httpcore.AsyncNetworkStream:
        try:
            addresses = list(await asyncio.to_thread(self._resolve, host, port))
        except OSError:
            raise httpcore.ConnectError("l'hôte ne se résout pas") from None
        if not addresses or not all(joinable(a) for a in addresses):
            raise MapsUnavailable(OUT_OF_REACH)
        failed: Exception | None = None
        for address in addresses:
            try:
                return await self._inner.connect_tcp(address, port, timeout=timeout, local_address=local_address,
                                                     socket_options=socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                failed = exc
        assert failed is not None
        raise failed

    async def connect_unix_socket(self, path: str, timeout: float | None = None,
                                  socket_options: Any = None) -> httpcore.AsyncNetworkStream:
        raise MapsUnavailable(OUT_OF_REACH)

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class _GuardedTransport(httpx.AsyncHTTPTransport):
    """Le transport de httpx (sans proxy du système), sur le réseau de ``_PublicOnly`` : le SNI, la vérification du
    certificat et ``Host`` restent ceux du nom demandé, seule l'adresse jointe est celle qu'on a vérifiée."""

    def __init__(self, network: _PublicOnly) -> None:
        super().__init__(trust_env=False)
        self._pool = httpcore.AsyncConnectionPool(ssl_context=httpx.create_ssl_context(trust_env=False),
                                                  max_connections=20, keepalive_expiry=5.0,
                                                  network_backend=network)


def guarded_transport(resolve: Resolver = resolve_host,
                      network: httpcore.AsyncNetworkBackend | None = None) -> httpx.AsyncBaseTransport:
    """Le transport du relais : chaque connexion à une adresse publique que le DNS vient de rendre (``resolve``), sur
    le réseau du système ou ``network``."""
    return _GuardedTransport(_PublicOnly(resolve, network))


def on_hosts(url: str, hosts: Iterable[str]) -> bool:
    """Une adresse en https sur l'un de ces hôtes, ou l'un de leurs sous-domaines."""
    parts = urlsplit(url)
    host = (parts.hostname or "").rstrip(".").lower()
    return parts.scheme == "https" and any(host == h or host.endswith("." + h) for h in hosts)


class PhotoRelay:
    """Les photos des sources branchées, relevées une fois puis gardées dans ``folder`` ; ``today`` : le jour où l'on
    juge des droits. Sans ``transport`` (le serveur), la relève passe par ``guarded_transport`` et ``resolve``."""

    def __init__(self, folder: Path, *, sources: Iterable[PhotoSource] = (), today: Callable[[], date],
                 transport: httpx.AsyncBaseTransport | None = None, cache_max: int = CACHE_MAX_BYTES,
                 photo_max: int = PHOTO_MAX_BYTES, pace: Pace | None = None,
                 resolve: Resolver = resolve_host) -> None:
        self.folder = folder
        self.sources: list[PhotoSource] = list(sources)
        self.today = today
        self.cache_max = cache_max
        self.photo_max = photo_max
        self._transport = transport
        self._resolve = resolve
        self._pace = pace or Pace(PER_SECOND, wait_max=10.0, busy="Les photos sont très demandées : réessaie.")
        self._client: httpx.AsyncClient | None = None
        self._pending: dict[str, asyncio.Future[tuple[bytes, str]]] = {}
        #: depuis le démarrage, pour la console
        self.fetched = 0
        self.served = 0
        self.failed = 0
        self.last_error = ""

    def add_source(self, source: PhotoSource) -> None:
        self.sources.append(source)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = client(TIMEOUT_S, self._transport or guarded_transport(self._resolve))
        return self._client

    def _file(self, ref: str) -> Path:
        return self.folder / REF.match(ref).group(1)  # type: ignore[union-attr]

    def size(self) -> tuple[int, int]:
        """(fichiers, octets) du cache."""
        count = total = 0
        with contextlib.suppress(OSError), os.scandir(self.folder) as entries:
            for entry in entries:
                with contextlib.suppress(OSError):
                    if entry.is_file():
                        count += 1
                        total += entry.stat().st_size
        return count, total

    async def origin(self, ref: str) -> PhotoOrigin | None:
        for source in self.sources:
            found = await asyncio.to_thread(source.photo_origin, ref)
            if found is not None:
                return found
        return None

    async def get(self, ref: str) -> tuple[bytes, str]:
        """Les octets d'une photo et son type ; inconnue, ou ses droits finis : ``MapsNotFound`` ; ce qui ne va pas
        d'autre : ``MapsUnavailable``, en mots."""
        if not isinstance(ref, str) or not REF.match(ref):
            raise MapsNotFound(UNKNOWN)
        found = await self.origin(ref)
        if found is None:
            raise MapsNotFound(UNKNOWN)
        path = self._file(ref)
        if found.rights_end and found.rights_end < self.today().isoformat():
            path.unlink(missing_ok=True)
            raise MapsNotFound(EXPIRED)
        kept = await asyncio.to_thread(_read_kept, path)
        if kept is not None:
            self.served += 1
            return kept
        pending = self._pending.get(ref)
        if pending is None:  # la première demande la relève ; les autres attendent sa réponse
            pending = asyncio.ensure_future(self._fetch(ref, found, path))
            self._pending[ref] = pending
            pending.add_done_callback(lambda done, ref=ref: self._settled(ref, done))
        got = await asyncio.shield(pending)
        self.served += 1
        return got

    def _settled(self, ref: str, done: asyncio.Future[tuple[bytes, str]]) -> None:
        self._pending.pop(ref, None)
        if not done.cancelled():
            done.exception()  # lue : une relève que plus personne n'attendait ne se plaint pas au journal

    async def _fetch(self, ref: str, found: PhotoOrigin, path: Path) -> tuple[bytes, str]:
        try:
            url = found.url or (await found.resolve() if found.resolve is not None else "")
            data = await self._download(url, found.hosts)
            media = media_of(data[:16])
            if not media:  # elle a répondu, mais pas une image qu'on sert : un 502, pas une source muette
                raise MapsBadMedia("Ce que la source a rendu n'est pas une image.")
            self.fetched += 1
            await asyncio.to_thread(self._keep, path, data)
        except MapsUnavailable as exc:
            self.failed += 1
            self.last_error = str(exc)
            raise
        except (sqlite3.Error, OSError):  # la fiche relue (un nom expiré) ou la photo ne s'écrit pas : en mots (R3-02)
            self.failed += 1
            self.last_error = UNWRITTEN
            raise MapsUnavailable(UNWRITTEN) from None
        return data, media

    async def _download(self, url: str, hosts: tuple[str, ...] = ()) -> bytes:
        for _hop in range(REDIRECTS_MAX + 1):
            if not public_url(url) or (hosts and not on_hosts(url, hosts)):
                raise MapsUnavailable(OUT_OF_REACH)
            await self._pace.turn()
            try:
                async with self._http().stream("GET", url, headers={"Accept": "image/*"}) as r:
                    if r.status_code in (301, 302, 303, 307, 308):
                        url = urljoin(url, r.headers.get("location", ""))
                        continue
                    if r.status_code != 200:
                        raise MapsUnavailable(f"La source de cette photo a répondu HTTP {r.status_code}.")
                    return await read_capped(r, self.photo_max)
            except httpx.HTTPError as exc:
                raise MapsUnavailable(f"La source de cette photo ne répond pas ({type(exc).__name__}).") from None
            except ValueError:
                raise MapsUnavailable(f"Cette photo dépasse {self.photo_max // (1024 * 1024)} Mo.") from None
        raise MapsUnavailable("La source de cette photo renvoie trop loin.")

    def _keep(self, path: Path, data: bytes) -> None:
        """La photo gardée (écrite à côté, puis à sa place d'un seul coup) ; le cache ramené sous sa borne, les moins
        récemment servies d'abord."""
        self.folder.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(path.name + ".partiel")
        partial.write_bytes(data)
        os.replace(partial, path)
        entries = []
        with os.scandir(self.folder) as found:
            for entry in found:
                with contextlib.suppress(OSError):
                    if entry.is_file() and not entry.name.endswith(".partiel") and entry.name != path.name:
                        st = entry.stat()
                        entries.append((st.st_mtime_ns, st.st_size, entry.path))
        total = len(data) + sum(size for _at, size, _p in entries)  # la nouvelle reste
        if total <= self.cache_max:
            return
        for _at, size, old in sorted(entries):
            if total <= self.cache_max * CACHE_LOW:
                break
            with contextlib.suppress(OSError):
                os.unlink(old)
                total -= size


def _read_kept(path: Path) -> tuple[bytes, str] | None:
    """Une photo gardée, et son type ; marquée servie (son heure) pour rester ; ``None`` : pas gardée, ou abîmée."""
    try:
        data = path.read_bytes()
        os.utime(path)
    except OSError:
        return None
    media = media_of(data[:16])
    return (data, media) if media else None
