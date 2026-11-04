"""Les tuiles de la carte de sa position (ADR 0193) : lues dans une archive PMTiles — un fichier du dossier de données,
ou une archive qu'un serveur de carte sert par plages —, ou relayées d'un serveur ``{z}/{x}/{y}``. Le navigateur ne
parle qu'à ce serveur : ce qu'il regarde ne part nulle part ailleurs, sinon vers le serveur de carte réglé, et sans
rien de la personne (ni son adresse, ni ses cookies)."""

from __future__ import annotations

import asyncio
import os
import zlib
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from pmtiles.tile import (
    Compression,
    Entry,
    HeaderDict,
    MagicNumberNotFound,
    SpecVersionUnsupported,
    TileType,
    deserialize_directory,
    deserialize_header,
    find_tile,
    zxy_to_tileid,
)

from mika.adapters.maps.config import FILE, IMAGE, NONE, SERVER, VECTOR, MapConfig

#: ce que ce serveur dit de lui en joignant un serveur de carte (rien de la personne)
USER_AGENT = "Mika/2 (carte de sa position)"
TIMEOUT_S = 10.0
#: les répertoires d'une archive gardés en mémoire : la racine et les feuilles des derniers endroits regardés
DIRS_KEPT = 256
#: le zoom le plus fin qu'on demande (au-delà, la carte agrandit le dernier)
ZOOM_MAX = 22
#: une tuile relayée plus grosse est refusée (une tuile fait quelques dizaines de Ko)
TILE_MAX_BYTES = 4 * 1024 * 1024
MEDIA = {TileType.MVT: "application/vnd.mapbox-vector-tile", TileType.PNG: "image/png",
         TileType.JPEG: "image/jpeg", TileType.WEBP: "image/webp"}
ENCODINGS = {Compression.NONE: "", Compression.GZIP: "gzip", Compression.BROTLI: "br", Compression.ZSTD: "zstd"}
#: ce qu'une archive abîmée, tronquée ou d'une autre sorte lève en se lisant
BROKEN = (OSError, ValueError, EOFError, zlib.error, MagicNumberNotFound, SpecVersionUnsupported)
#: les premiers octets d'un flux gzip
GZIP_MAGIC = b"\x1f\x8b"


class MapUnavailable(Exception):
    """La carte ne se lit pas (fichier absent ou illisible, serveur injoignable) ; le message le dit en mots."""


@dataclass(frozen=True, slots=True)
class MapInfo:
    """Ce que le client sait de la carte : prête ou non (et pourquoi), ses tuiles, sa zone, ses polices et icônes."""

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


@dataclass(frozen=True, slots=True)
class Tile:
    data: bytes
    media: str
    #: le ``Content-Encoding`` des octets tels quels (``gzip`` pour une archive Protomaps) ; vide : en clair
    encoding: str = ""


Read = Callable[[int, int], Awaitable[bytes]]


class Archive:
    """Une archive PMTiles (version 3) lue par morceaux : son en-tête et ses répertoires gardés en mémoire."""

    def __init__(self, read: Read) -> None:
        self._read = read
        self._header: HeaderDict | None = None
        self._dirs: OrderedDict[tuple[int, int], list[Entry]] = OrderedDict()

    async def header(self) -> HeaderDict:
        if self._header is None:
            got = deserialize_header(await self._read(0, 127))
            if got["internal_compression"] is not Compression.GZIP:
                raise MapUnavailable("Cette archive range ses répertoires autrement qu'en gzip : refaites-la avec "
                                     "pmtiles (deploy/README.md).")
            self._header = got
        return self._header

    async def directory(self, offset: int, length: int) -> list[Entry]:
        """Un répertoire de l'archive (la racine, une feuille), gardé en mémoire."""
        key = (offset, length)
        found = self._dirs.get(key)
        if found is not None:
            self._dirs.move_to_end(key)
            return found
        found = deserialize_directory(await self._read(offset, length))
        self._dirs[key] = found
        while len(self._dirs) > DIRS_KEPT:
            self._dirs.popitem(last=False)
        return found

    async def tile(self, z: int, x: int, y: int) -> bytes | None:
        h = await self.header()
        if not h["min_zoom"] <= z <= h["max_zoom"]:
            return None
        wanted = zxy_to_tileid(z, x, y)
        offset, length = h["root_offset"], h["root_length"]
        for _depth in range(4):  # la racine, puis au plus trois niveaux de feuilles
            entry = find_tile(await self.directory(offset, length), wanted)
            if entry is None:
                return None
            if entry.run_length > 0:
                return await self._read(h["tile_data_offset"] + entry.offset, entry.length)
            offset, length = h["leaf_directory_offset"] + entry.offset, entry.length
        return None


def _file_reader(path: Path) -> tuple[Read, Callable[[], None]]:
    fd = os.open(path, os.O_RDONLY)

    async def read(offset: int, length: int) -> bytes:
        return await asyncio.to_thread(os.pread, fd, length, offset)

    return read, lambda: os.close(fd)


def _size_words(size: int) -> str:
    return f"{size / 1e9:.1f} Go".replace(".", ",") if size >= 1e9 else f"{max(1, round(size / 1e6))} Mo"


class MapTiles:
    """La carte réglée (``config`` est relu à chaque fois : la console la change sans redémarrer) ; ``data`` : le
    dossier de données, d'où se lisent le fichier et les polices et icônes."""

    def __init__(self, data: Path, config: Callable[[], MapConfig], *,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.data = data
        self.config = config
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._open: tuple[tuple[object, ...], Archive, Callable[[], None]] | None = None
        #: la dernière fois que la carte ne s'est pas lue, en mots (la console le montre) ; vide : rien
        self.last_error = ""

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT},
                                             transport=self._transport, follow_redirects=False)
        return self._client

    async def close(self) -> None:
        if self._open is not None:
            self._open[2]()
            self._open = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── la source ──
    def _archive(self, cfg: MapConfig) -> Archive | None:
        """L'archive de la source réglée, rouverte quand elle change (le fichier remplacé, une autre adresse) ;
        ``None`` : pas une archive (des tuiles ``{z}/{x}/{y}``)."""
        if cfg.source == FILE:
            path = self.data / cfg.file
            try:
                st = path.stat()
            except OSError:
                raise MapUnavailable(f"Le fichier {cfg.file} n'est pas sur le serveur.") from None
            key: tuple[object, ...] = (FILE, str(path), st.st_mtime_ns, st.st_size)
            if self._open is None or self._open[0] != key:
                read, close = _file_reader(path)
                self._swap(key, read, close)
        elif cfg.source == SERVER and not cfg.zxy:
            key = (SERVER, cfg.url)
            if self._open is None or self._open[0] != key:
                self._swap(key, self._range_reader(cfg.url), lambda: None)
        else:
            return None
        assert self._open is not None
        return self._open[1]

    def _swap(self, key: tuple[object, ...], read: Read, close: Callable[[], None]) -> None:
        if self._open is not None:
            self._open[2]()
        self._open = (key, Archive(read), close)

    def _range_reader(self, url: str) -> Read:
        async def read(offset: int, length: int) -> bytes:
            try:
                r = await self._http().get(url, headers={"Range": f"bytes={offset}-{offset + length - 1}"})
            except httpx.HTTPError as exc:
                raise MapUnavailable(f"Le serveur de carte ne répond pas ({type(exc).__name__}).") from None
            if r.status_code != 206:
                raise MapUnavailable(f"Le serveur de carte ne sert pas cette archive par plages (HTTP "
                                     f"{r.status_code}).")
            return r.content

        return read

    def _has(self, cfg: MapConfig, kind: str) -> bool:
        return (self.data / cfg.assets / kind).is_dir()

    # ── ce que le client lit ──
    async def info(self) -> MapInfo:
        cfg = self.config()
        said = {"attribution": cfg.attribution, "fonts": self._has(cfg, "fonts"), "sprites": self._has(cfg, "sprites")}
        if cfg.source == NONE:
            return MapInfo(False, "Aucune carte n'est réglée : le plan dessiné.", **said)
        try:
            archive = self._archive(cfg)
            if archive is None:  # des tuiles {z}/{x}/{y} : ce que la console en a dit
                return MapInfo(True, kind=cfg.kind, maxzoom=cfg.maxzoom, **said)
            h = await archive.header()
        except MapUnavailable as exc:
            return self._failed(str(exc), said)
        except BROKEN:
            return self._failed("Ce n'est pas une archive PMTiles (version 3) lisible.", said)
        if h["tile_type"] not in MEDIA:
            return self._failed("Ses tuiles ne sont ni vectorielles ni des images.", said)
        bounds = (h["min_lon_e7"] / 1e7, h["min_lat_e7"] / 1e7, h["max_lon_e7"] / 1e7, h["max_lat_e7"] / 1e7)
        self.last_error = ""
        return MapInfo(True, kind=VECTOR if h["tile_type"] is TileType.MVT else IMAGE, minzoom=h["min_zoom"],
                       maxzoom=h["max_zoom"], bounds=bounds, **said)

    def _failed(self, reason: str, said: dict[str, object]) -> MapInfo:
        self.last_error = reason
        return MapInfo(False, reason, **said)  # type: ignore[arg-type]

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
        try:
            archive = self._archive(cfg)
            assert archive is not None
            h = await archive.header()
            data = await archive.tile(z, x, y)
        except MapUnavailable as exc:
            self.last_error = str(exc)
            raise
        except BROKEN:
            self.last_error = "Ce n'est pas une archive PMTiles (version 3) lisible."
            raise MapUnavailable(self.last_error) from None
        if data is None:
            return None
        return Tile(data, MEDIA.get(h["tile_type"], "application/octet-stream"),
                    ENCODINGS.get(h["tile_compression"], ""))

    async def _relayed(self, cfg: MapConfig, z: int, x: int, y: int) -> Tile | None:
        url = cfg.url.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
        try:
            r = await self._http().get(url)
        except httpx.HTTPError as exc:
            self.last_error = f"Le serveur de carte ne répond pas ({type(exc).__name__})."
            raise MapUnavailable(self.last_error) from None
        if r.status_code in (204, 404):
            return None
        if r.status_code != 200 or len(r.content) > TILE_MAX_BYTES:
            self.last_error = f"Le serveur de carte a répondu HTTP {r.status_code}."
            raise MapUnavailable(self.last_error)
        data = r.content  # httpx a déjà ouvert ce que le serveur annonçait compressé
        media = r.headers.get("content-type", "").split(";")[0].strip()
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
