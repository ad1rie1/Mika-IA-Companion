"""Les tuiles de la carte de sa position (ADR 0193) : lues dans une archive PMTiles — un fichier du dossier de données,
ou une archive qu'un serveur de carte sert par plages —, ou relayées d'un serveur ``{z}/{x}/{y}``. Le navigateur ne
parle qu'à ce serveur : ce qu'il regarde ne part nulle part ailleurs, sinon vers le serveur de carte réglé, et sans
rien de la personne (ni son adresse, ni ses cookies).

Ce qui vient d'un serveur de carte se lit en flux et borné : le statut d'abord (un serveur qui ignore les plages
renverrait toute l'archive), puis au plus ce qu'on a demandé. Une archive distante remplacée à la même adresse se voit
(sa version, ``ETag`` ou ``Last-Modified``, change ; son en-tête est relu au plus une fois par minute) et se rouvre ;
un fichier remplacé aussi (sa date, sa taille), et l'ancien ne se ferme qu'une fois finies les lectures en cours."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import time
import zlib
from array import array
from bisect import bisect_right
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from http.cookiejar import CookieJar, DefaultCookiePolicy
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from pmtiles.tile import (
    Compression,
    HeaderDict,
    MagicNumberNotFound,
    SpecVersionUnsupported,
    TileType,
    deserialize_header,
    zxy_to_tileid,
)

from mika.adapters.maps.config import FILE, IMAGE, NONE, SERVER, VECTOR, MapConfig

#: ce que ce serveur dit de lui en joignant un serveur de carte (rien de la personne)
USER_AGENT = "Mika/2 (carte de sa position)"
TIMEOUT_S = 10.0
#: les entrées de répertoires gardées en mémoire (24 octets chacune) : la racine et les feuilles des derniers endroits
#: regardés. Une feuille de la planète Protomaps en compte plus de 100 000 ; une de ``mika carte extraire``, 4 096.
ENTRIES_KEPT = 1 << 20
#: un répertoire plus gros ne se lit pas : compressé (une feuille de la planète fait moins d'1 Mo), puis ouvert
DIR_MAX_BYTES = 16 * 1024 * 1024
DIR_PLAIN_MAX = 64 * 1024 * 1024
#: un répertoire plus gros que ça (compressé) s'ouvre hors de la boucle d'événements : une feuille de la planète
#: prend un dixième de seconde à lire, qui figerait le serveur
DIR_THREAD_BYTES = 64 * 1024
#: le zoom le plus fin qu'on demande (au-delà, la carte agrandit le dernier)
ZOOM_MAX = 22
#: une tuile relayée plus grosse est refusée (une tuile fait quelques dizaines de Ko)
TILE_MAX_BYTES = 4 * 1024 * 1024
#: un serveur de carte se revérifie au plus tant de secondes après la dernière fois : l'en-tête d'une archive
#: distante relu (a-t-elle changé ?), une tuile d'un serveur {z}/{x}/{y} demandée (répond-il ?)
CHECK_S = 60.0
MEDIA = {TileType.MVT: "application/vnd.mapbox-vector-tile", TileType.PNG: "image/png",
         TileType.JPEG: "image/jpeg", TileType.WEBP: "image/webp"}
ENCODINGS = {Compression.NONE: "", Compression.GZIP: "gzip", Compression.BROTLI: "br", Compression.ZSTD: "zstd"}
#: ce qu'une archive abîmée, tronquée ou d'une autre sorte lève en se lisant
BROKEN = (OSError, ValueError, EOFError, zlib.error, MagicNumberNotFound, SpecVersionUnsupported)
#: les premiers octets d'un flux gzip
GZIP_MAGIC = b"\x1f\x8b"
#: une archive distante qui change encore à la relecture : on renonce pour cette fois
CHANGING = "L'archive du serveur de carte change pendant qu'on la lit : réessaie dans un instant."


class MapUnavailable(Exception):
    """La carte ne se lit pas (fichier absent ou illisible, serveur injoignable) ; le message le dit en mots."""


class ArchiveChanged(Exception):
    """L'archive d'un serveur de carte n'est plus celle qu'on a ouverte (sa version a changé) : à rouvrir."""


@dataclass(frozen=True, slots=True)
class MapInfo:
    """Ce que le client sait de la carte : prête ou non (et pourquoi), ses tuiles, sa zone, ses polices et icônes.
    ``version`` change avec la source (le réglage, le fichier, l'archive distante) : les adresses de ses tuiles la
    portent, et le navigateur ne ressert pas, d'une carte remplacée, ce qu'il gardait de l'autre."""

    ready: bool
    reason: str = ""
    kind: str = VECTOR
    minzoom: int = 0
    maxzoom: int = 15
    #: ouest, sud, est, nord (degrés) ; ``None`` : partout
    bounds: tuple[float, float, float, float] | None = None
    attribution: str = ""
    fonts: bool = False
    sprites: bool = False
    version: str = ""


@dataclass(frozen=True, slots=True)
class Tile:
    data: bytes
    media: str
    #: le ``Content-Encoding`` des octets tels quels (``gzip`` pour une archive Protomaps) ; vide : en clair
    encoding: str = ""


Read = Callable[[int, int], Awaitable[bytes]]


def no_cookies() -> CookieJar:
    """Un bocal qui refuse tout cookie : ce serveur ne renvoie jamais à un serveur du dehors ce qu'il a voulu poser.
    Le bocal lui-même, pas des ``httpx.Cookies`` : httpx les recopierait dans un bocal ordinaire."""
    return CookieJar(policy=DefaultCookiePolicy(allowed_domains=[]))


async def read_capped(response: httpx.Response, cap: int) -> bytes:
    """Le corps d'une réponse ouverte en flux, lu jusqu'à ``cap`` octets ; au-delà : ``ValueError``, et rien de plus
    n'est lu (la réponse se ferme sans le reste)."""
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > cap:
        raise ValueError("une réponse démesurée")
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > cap:
            raise ValueError("une réponse démesurée")
        chunks.append(chunk)
    return b"".join(chunks)


@dataclass(frozen=True, slots=True)
class Directory:
    """Un répertoire PMTiles (version 3) — la racine, ou une feuille — en tableaux : 24 octets par entrée, quand un
    objet par entrée en prend quelque 150 (``pmtiles.tile.Entry``). ``runs[i] == 0`` : l'entrée mène à une feuille."""

    ids: array
    runs: array
    lengths: array
    offsets: array

    def __len__(self) -> int:
        return len(self.ids)

    def find(self, tile_id: int) -> int | None:
        """L'entrée qui porte cette tuile, ou la feuille où la chercher ; ``None`` : aucune (``find_tile``)."""
        i = bisect_right(self.ids, tile_id) - 1
        if i < 0:
            return None
        run = self.runs[i]
        return i if run == 0 or tile_id - self.ids[i] < run else None


def _varints(data: bytes) -> Iterator[int]:
    value = shift = 0
    for byte in data:
        value |= (byte & 0x7F) << shift
        if byte & 0x80:
            shift += 7
        else:
            yield value
            value = shift = 0


def read_directory(raw: bytes) -> Directory:
    """Un répertoire compressé en gzip, lu en tableaux ; abîmé, tronqué ou démesuré : ``ValueError``."""
    unzip = zlib.decompressobj(wbits=31)
    try:
        plain = unzip.decompress(raw, DIR_PLAIN_MAX)
    except zlib.error:
        raise ValueError("un répertoire qui n'est pas en gzip") from None
    if not unzip.eof:
        raise ValueError("un répertoire tronqué ou démesuré")
    values = _varints(plain)
    ids, runs, lengths, offsets = array("Q"), array("I"), array("I"), array("Q")
    try:
        count = next(values)
        if 4 * count > len(plain):  # quatre nombres par entrée, d'un octet au moins
            raise ValueError("un répertoire tronqué")
        last = 0
        for _ in range(count):
            last += next(values)
            ids.append(last)
        for _ in range(count):
            runs.append(next(values))
        for _ in range(count):
            lengths.append(next(values))
        for i in range(count):
            value = next(values)
            offsets.append(offsets[i - 1] + lengths[i - 1] if i > 0 and value == 0 else value - 1)
    except (StopIteration, OverflowError):
        raise ValueError("un répertoire tronqué ou abîmé") from None
    return Directory(ids, runs, lengths, offsets)


async def fetch_directory(read: Read, offset: int, length: int) -> Directory:
    """Lire un répertoire de l'archive, sans le garder ; un gros s'ouvre dans un fil à part (la boucle continue)."""
    if not 0 < length <= DIR_MAX_BYTES:
        raise ValueError("un répertoire hors des bornes")
    raw = await read(offset, length)
    if len(raw) > DIR_THREAD_BYTES:
        return await asyncio.to_thread(read_directory, raw)
    return read_directory(raw)


class Archive:
    """Une archive PMTiles (version 3) lue par morceaux : son en-tête et ses répertoires gardés en mémoire. Deux
    lectures du même répertoire en même temps n'en font qu'une."""

    def __init__(self, read: Read) -> None:
        self._read = read
        self._header: HeaderDict | None = None
        #: les octets de l'en-tête lu : une relecture qui en rend d'autres dit une autre archive (``recheck``)
        self.raw_header = b""
        self._dirs: OrderedDict[tuple[int, int], Directory] = OrderedDict()
        self._kept = 0
        self._loading: dict[tuple[int, int], asyncio.Future[Directory]] = {}

    async def header(self) -> HeaderDict:
        if self._header is None:
            raw = await self._read(0, 127)
            got = deserialize_header(raw)
            if got["internal_compression"] is not Compression.GZIP:
                raise MapUnavailable("Cette archive range ses répertoires autrement qu'en gzip : refaites-la avec "
                                     "pmtiles (deploy/README.md).")
            self._header, self.raw_header = got, raw
        return self._header

    async def recheck(self) -> None:
        """Relire l'en-tête : d'autres octets, c'est une autre archive (``ArchiveChanged``)."""
        if self._header is None:
            await self.header()
            return
        if await self._read(0, 127) != self.raw_header:
            raise ArchiveChanged()

    async def directory(self, offset: int, length: int) -> Directory:
        """Un répertoire de l'archive (la racine, une feuille), gardé en mémoire tant qu'il y a de la place
        (``ENTRIES_KEPT``) : le plus anciennement lu s'en va d'abord, le dernier reste."""
        key = (offset, length)
        found = self._dirs.get(key)
        if found is not None:
            self._dirs.move_to_end(key)
            return found
        loading = self._loading.get(key)
        if loading is None:  # le premier qui le demande le lit ; les autres attendent la même lecture
            loading = asyncio.ensure_future(self._load(key))
            self._loading[key] = loading
            loading.add_done_callback(lambda done, key=key: self._settled(key, done))
        return await asyncio.shield(loading)

    def _settled(self, key: tuple[int, int], done: asyncio.Future[Directory]) -> None:
        self._loading.pop(key, None)
        if not done.cancelled():
            done.exception()  # lue : une lecture que plus personne n'attendait ne se plaint pas au journal

    async def _load(self, key: tuple[int, int]) -> Directory:
        found = await fetch_directory(self._read, *key)
        if key not in self._dirs:
            self._dirs[key] = found
            self._kept += len(found)
            while self._kept > ENTRIES_KEPT and len(self._dirs) > 1:
                self._kept -= len(self._dirs.popitem(last=False)[1])
        return found

    async def tile(self, z: int, x: int, y: int) -> bytes | None:
        h = await self.header()
        if not h["min_zoom"] <= z <= h["max_zoom"]:
            return None
        wanted = zxy_to_tileid(z, x, y)
        offset, length = h["root_offset"], h["root_length"]
        for _depth in range(4):  # la racine, puis au plus trois niveaux de feuilles
            found = await self.directory(offset, length)
            i = found.find(wanted)
            if i is None:
                return None
            if found.runs[i] > 0:
                if found.lengths[i] > TILE_MAX_BYTES:
                    raise ValueError("une tuile démesurée")
                return await self._read(h["tile_data_offset"] + found.offsets[i], found.lengths[i])
            offset, length = h["leaf_directory_offset"] + found.offsets[i], found.lengths[i]
        return None


def _file_reader(path: Path) -> tuple[Read, Callable[[], None]]:
    fd = os.open(path, os.O_RDONLY)

    async def read(offset: int, length: int) -> bytes:
        return await asyncio.to_thread(os.pread, fd, length, offset)

    return read, lambda: os.close(fd)


class _Remote:
    """Une archive qu'un serveur de carte sert par plages, lue en flux : le statut d'abord, puis au plus la plage.
    Chaque réponse dit sa version (``ETag``, sinon ``Last-Modified``) ; une autre que la première : l'archive a
    changé (``ArchiveChanged``)."""

    def __init__(self, http: Callable[[], httpx.AsyncClient], url: str) -> None:
        self.url = url
        self._http = http
        self.version = ""

    async def read(self, offset: int, length: int) -> bytes:
        headers = {"Range": f"bytes={offset}-{offset + length - 1}", "Accept-Encoding": "identity"}
        try:
            async with self._http().stream("GET", self.url, headers=headers) as r:
                if r.status_code != 206:
                    raise MapUnavailable(f"Le serveur de carte ne sert pas cette archive par plages (HTTP "
                                         f"{r.status_code}).")
                said = r.headers.get("content-range", "")
                if said and not said.replace(" ", "").startswith(f"bytes{offset}-"):
                    raise MapUnavailable("Le serveur de carte a rendu une autre plage que celle demandée.")
                seen = r.headers.get("etag") or r.headers.get("last-modified") or ""
                if seen and not self.version:
                    self.version = seen
                elif seen and seen != self.version:
                    raise ArchiveChanged()
                try:
                    data = await read_capped(r, length)
                except ValueError:
                    raise MapUnavailable("Le serveur de carte a rendu plus que la plage demandée.") from None
        except httpx.HTTPError as exc:
            raise MapUnavailable(f"Le serveur de carte ne répond pas ({type(exc).__name__}).") from None
        if len(data) != length:
            raise MapUnavailable("Le serveur de carte a rendu une plage incomplète.")
        return data


class _Opened:
    """Une archive ouverte et ce qui la lit. Chaque usage la tient (``lease``) le temps de ses lectures : remplacée
    (un fichier neuf, une archive distante qui a changé), elle n'est fermée qu'une fois lâchée par tous."""

    def __init__(self, key: tuple[object, ...], read: Read, close: Callable[[], None], *,
                 remote: _Remote | None = None, now: float = 0.0) -> None:
        self.key = key
        self.archive = Archive(read)
        self.remote = remote
        self._close = close
        self.users = 0
        self.retired = False
        self.closed = False
        #: la dernière fois que son en-tête a été lu ou relu (une archive distante)
        self.checked = now

    @contextlib.contextmanager
    def lease(self) -> Iterator[Archive]:
        self.users += 1
        try:
            yield self.archive
        finally:
            self.users -= 1
            self._settle()

    def retire(self) -> None:
        self.retired = True
        self._settle()

    def _settle(self) -> None:
        if self.retired and self.users == 0 and not self.closed:
            self.closed = True
            self._close()


def _size_words(size: int) -> str:
    return f"{size / 1e9:.1f} Go".replace(".", ",") if size >= 1e9 else f"{max(1, round(size / 1e6))} Mo"


class MapTiles:
    """La carte réglée (``config`` est relu à chaque fois : la console la change sans redémarrer) ; ``data`` : le
    dossier de données, d'où se lisent le fichier et les polices et icônes."""

    def __init__(self, data: Path, config: Callable[[], MapConfig], *,
                 transport: httpx.AsyncBaseTransport | None = None,
                 now: Callable[[], float] = time.monotonic) -> None:
        self.data = data
        self.config = config
        self._transport = transport
        self._now = now
        self._client: httpx.AsyncClient | None = None
        self._open: _Opened | None = None
        #: un serveur {z}/{x}/{y} demandé : (son adresse, quand, pourquoi il ne sert pas — vide : il sert)
        self._probed: tuple[str, float, str] | None = None
        self._probing = asyncio.Lock()
        #: la dernière fois que la carte ne s'est pas lue, en mots (la console le montre) ; vide : rien
        self.last_error = ""

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT},
                                             transport=self._transport, follow_redirects=False, cookies=no_cookies())
        return self._client

    async def close(self) -> None:
        if self._open is not None:
            self._open.retire()
            self._open = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── la source ──
    def _archive(self, cfg: MapConfig) -> _Opened | None:
        """L'archive de la source réglée, rouverte quand elle change (le fichier remplacé, une autre adresse, une
        archive distante qui a changé) ; ``None`` : pas une archive (des tuiles ``{z}/{x}/{y}``)."""
        if cfg.source == FILE:
            path = self.data / cfg.file
            try:
                st = path.stat()
            except OSError:
                raise MapUnavailable(f"Le fichier {cfg.file} n'est pas sur le serveur.") from None
            key: tuple[object, ...] = (FILE, str(path), st.st_mtime_ns, st.st_size)
            if self._open is None or self._open.key != key:
                read, close = _file_reader(path)
                self._swap(_Opened(key, read, close, now=self._now()))
        elif cfg.source == SERVER and not cfg.zxy:
            key = (SERVER, cfg.url)
            if self._open is None or self._open.key != key:
                remote = _Remote(self._http, cfg.url)
                self._swap(_Opened(key, remote.read, lambda: None, remote=remote, now=self._now()))
        else:
            return None
        assert self._open is not None
        return self._open

    def _swap(self, opened: _Opened) -> None:
        if self._open is not None:
            self._open.retire()  # fermée une fois finies les lectures qui la tiennent encore
        self._open = opened

    def _drop(self, opened: _Opened) -> None:
        """Oublier cette archive : la prochaine lecture la rouvre (son en-tête, ses répertoires relus)."""
        if self._open is opened:
            self._open = None
        opened.retire()

    def _has(self, cfg: MapConfig, kind: str) -> bool:
        return (self.data / cfg.assets / kind).is_dir()

    def _version(self, cfg: MapConfig, ident: object) -> str:
        raw = json.dumps([cfg.model_dump(mode="json"), ident], sort_keys=True, default=str)
        return hashlib.blake2s(raw.encode(), digest_size=6).hexdigest()

    # ── ce que le client lit ──
    async def info(self) -> MapInfo:
        cfg = self.config()
        said = {"attribution": cfg.attribution, "fonts": self._has(cfg, "fonts"), "sprites": self._has(cfg, "sprites")}
        if cfg.source == NONE:
            return MapInfo(False, "Aucune carte n'est réglée : le plan dessiné.", **said)
        if cfg.source == SERVER and cfg.zxy:
            reason = await self._probe(cfg)
            if reason:
                return self._failed(reason, said)
            return MapInfo(True, kind=cfg.kind, maxzoom=cfg.maxzoom, version=self._version(cfg, None), **said)
        opened: _Opened | None = None
        for attempt in range(2):
            try:
                opened = self._archive(cfg)
                assert opened is not None
                with opened.lease() as archive:
                    h = await archive.header()
                    if opened.remote is not None and self._now() - opened.checked >= CHECK_S:
                        await archive.recheck()  # l'archive distante a-t-elle changé, répond-elle encore ?
                        opened.checked = self._now()
                break
            except ArchiveChanged:
                assert opened is not None
                self._drop(opened)
                if attempt:
                    return self._failed(CHANGING, said)
            except MapUnavailable as exc:
                self._forget_remote(opened)
                return self._failed(str(exc), said)
            except BROKEN:
                self._forget_remote(opened)
                return self._failed("Ce n'est pas une archive PMTiles (version 3) lisible.", said)
        assert opened is not None
        if h["tile_type"] not in MEDIA:
            return self._failed("Ses tuiles ne sont ni vectorielles ni des images.", said)
        bounds = (h["min_lon_e7"] / 1e7, h["min_lat_e7"] / 1e7, h["max_lon_e7"] / 1e7, h["max_lat_e7"] / 1e7)
        self.last_error = ""
        ident = opened.key if opened.remote is None else (opened.archive.raw_header.hex(), opened.remote.version)
        return MapInfo(True, kind=VECTOR if h["tile_type"] is TileType.MVT else IMAGE, minzoom=h["min_zoom"],
                       maxzoom=h["max_zoom"], bounds=bounds, version=self._version(cfg, ident), **said)

    def _forget_remote(self, opened: _Opened | None) -> None:
        """Une archive distante qui ne se lit plus est oubliée : la prochaine fois, elle se rouvre (ou dit qu'elle
        ne répond toujours pas)."""
        if opened is not None and opened.remote is not None:
            self._drop(opened)

    def _failed(self, reason: str, said: dict[str, object]) -> MapInfo:
        self.last_error = reason
        return MapInfo(False, reason, **said)  # type: ignore[arg-type]

    async def _probe(self, cfg: MapConfig) -> str:
        """Un serveur {z}/{x}/{y} répond-il ? Sa tuile du zoom 0 demandée, la réponse gardée ``CHECK_S`` : vide s'il
        sert, sinon pourquoi pas."""
        async with self._probing:  # une seule demande à la fois, les autres lisent sa réponse
            got = self._probed
            if got is not None and got[0] == cfg.url and self._now() - got[1] < CHECK_S:
                return got[2]
            try:
                await self._relayed(cfg, 0, 0, 0)
                reason = ""
            except MapUnavailable as exc:
                reason = str(exc)
            self._probed = (cfg.url, self._now(), reason)
            return reason

    async def tile(self, z: int, x: int, y: int) -> Tile | None:
        """Une tuile ; ``None`` : il n'y en a pas là (hors de la zone, hors des zooms). ``MapUnavailable`` : la
        carte ne se lit pas."""
        cfg = self.config()
        if cfg.source == NONE:
            raise MapUnavailable("Aucune carte n'est réglée.")
        if not (0 <= z <= ZOOM_MAX and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
            return None
        if cfg.source == SERVER and cfg.zxy:
            return await self._relayed(cfg, z, x, y)
        opened: _Opened | None = None
        for attempt in range(2):
            try:
                opened = self._archive(cfg)
                assert opened is not None
                with opened.lease() as archive:
                    h = await archive.header()
                    data = await archive.tile(z, x, y)
                break
            except ArchiveChanged:  # une archive distante remplacée : rouverte, la tuile redemandée
                assert opened is not None
                self._drop(opened)
                if attempt:
                    self.last_error = CHANGING
                    raise MapUnavailable(CHANGING) from None
            except MapUnavailable as exc:
                self.last_error = str(exc)
                self._forget_remote(opened)
                raise
            except BROKEN:
                self.last_error = "Ce n'est pas une archive PMTiles (version 3) lisible."
                self._forget_remote(opened)
                raise MapUnavailable(self.last_error) from None
        if data is None:
            return None
        return Tile(data, MEDIA.get(h["tile_type"], "application/octet-stream"),
                    ENCODINGS.get(h["tile_compression"], ""))

    async def _relayed(self, cfg: MapConfig, z: int, x: int, y: int) -> Tile | None:
        url = cfg.url.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
        try:
            async with self._http().stream("GET", url) as r:
                if r.status_code in (204, 404):
                    return None
                if r.status_code != 200:
                    self.last_error = f"Le serveur de carte a répondu HTTP {r.status_code}."
                    raise MapUnavailable(self.last_error)
                try:
                    data = await read_capped(r, TILE_MAX_BYTES)  # httpx ouvre ce que le serveur annonçait compressé
                except ValueError:
                    self.last_error = "Le serveur de carte a rendu une tuile démesurée."
                    raise MapUnavailable(self.last_error) from None
                media = r.headers.get("content-type", "").split(";")[0].strip()
        except httpx.HTTPError as exc:
            self.last_error = f"Le serveur de carte ne répond pas ({type(exc).__name__})."
            self._probed = None  # la prochaine lecture de la carte redemande s'il répond
            raise MapUnavailable(self.last_error) from None
        if cfg.kind == VECTOR:
            # une tuile vectorielle gardée compressée, servie sans le dire : le navigateur l'ouvrira
            return Tile(data, "application/vnd.mapbox-vector-tile", "gzip" if data[:2] == GZIP_MAGIC else "")
        return Tile(data, media if media.startswith("image/") else "image/png")

    def asset(self, kind: str, rel: str) -> Path | None:
        """Une police (``fonts``) ou une planche d'icônes (``sprites``) du dossier réglé ; ``None`` : rien là (ou un
        chemin qui en sortirait)."""
        if kind not in ("fonts", "sprites"):
            return None
        base = (self.data / self.config().assets / kind).resolve()
        target = (base / rel).resolve()
        if base not in target.parents or not target.is_file():
            return None
        return target

    # ── ce que la console en dit ──
    def describe(self) -> list[tuple[str, str]]:
        cfg = self.config()
        if cfg.source == NONE:
            return [("Source", "aucune : Téléphone › Position montre le plan dessiné")]
        fonts = "présentes" if self._has(cfg, "fonts") and self._has(cfg, "sprites") else \
            f"absentes de {cfg.assets} : une carte sans noms ni icônes"
        if cfg.source == SERVER:
            facts = [("Source", f"un serveur de carte : {urlsplit(cfg.url.replace('{', '').replace('}', '')).hostname}"),
                     ("Polices et icônes", fonts)]
            return facts + ([("Dernière erreur", self.last_error)] if self.last_error else [])
        path = self.data / cfg.file
        if not path.is_file():
            return [("Source", f"le fichier {cfg.file}"), ("État", "absent du serveur (deploy/README.md, « La carte "
                                                                    "de sa position »)")]
        try:
            with path.open("rb") as f:
                h = deserialize_header(f.read(127))
            size = path.stat().st_size
        except BROKEN:
            return [("Source", f"le fichier {cfg.file}"), ("État", "illisible : ce n'est pas une archive PMTiles "
                                                                    "(version 3)")]
        zone = (f"{h['min_lon_e7'] / 1e7:.2f}, {h['min_lat_e7'] / 1e7:.2f} → {h['max_lon_e7'] / 1e7:.2f}, "
                f"{h['max_lat_e7'] / 1e7:.2f}")
        return [("Source", f"le fichier {cfg.file}"), ("Taille", _size_words(size)),
                ("Zooms", f"{h['min_zoom']} à {h['max_zoom']}"), ("Zone (ouest, sud → est, nord)", zone),
                ("Polices et icônes", fonts)]
