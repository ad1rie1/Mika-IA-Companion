"""Extraire une zone de la carte (ADR 0193) : d'une archive PMTiles lue par plages — la planète de Protomaps, refaite
chaque jour — vers un fichier du dossier de données, ce que fait ``pmtiles extract`` ; et les polices et icônes de son
style (``protomaps/basemaps-assets``). Rien d'autre à installer sur le serveur : ``mika carte extraire``, ``mika carte
polices``.

Seuls les répertoires et les tuiles de la zone se téléchargent : la racine, les feuilles qui la touchent (lues une à
une, puis lâchées), puis les tuiles, regroupées en morceaux (``CHUNK_BYTES``), quelques-uns à la fois. L'archive
s'écrit à côté (``….partiel``) et ne prend sa place qu'une fois entière. La mémoire reste bornée, quelques centaines
de Mo pour la France au zoom 15 : des tableaux, jamais un objet par tuile ni une feuille gardée."""

from __future__ import annotations

import asyncio
import gzip
import io
import math
import os
import shutil
from array import array
from bisect import bisect_left
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
from pmtiles.tile import Compression, HeaderDict, serialize_header, write_varint, zxy_to_tileid

from mika.adapters.maps.tiles import (
    BROKEN,
    DIR_MAX_BYTES,
    USER_AGENT,
    Archive,
    MapUnavailable,
    Read,
    fetch_directory,
    no_cookies,
    read_capped,
)

#: la liste des cartes de la planète refaites chaque jour, et où elles se lisent
BUILDS = "https://build-metadata.protomaps.dev/builds.json"
BUILD_BASE = "https://build.protomaps.com/"
#: les polices et les icônes du style Protomaps (licence OFL pour les polices)
ASSETS_BASE = "https://raw.githubusercontent.com/protomaps/basemaps-assets/main/"
FONTS = ("Noto Sans Regular", "Noto Sans Medium", "Noto Sans Italic")
FLAVORS = ("light", "dark")
#: des zones nommées : ouest, sud, est, nord (la France métropolitaine et la Corse)
ZONES = {"france": (-5.5, 41.2, 9.8, 51.2)}
#: un morceau téléchargé d'un coup, et l'écart entre deux tuiles qu'on lit avec elles plutôt que de couper
CHUNK_BYTES = 16 * 1024 * 1024
GAP_BYTES = 256 * 1024
PARALLEL = 4
TRIES = 4
#: ce qu'un serveur répond en passant (débordé, en maintenance, « pas si vite ») : réessayé, comme une coupure
TRANSIENT = frozenset({408, 425, 429, 500, 502, 503, 504})
#: une attente demandée (``Retry-After``) n'est suivie que jusque-là
RETRY_AFTER_MAX_S = 60.0
#: la racine d'une archive tient dans les premiers 16 Kio (avec l'en-tête)
ROOT_MAX = 16384 - 127
TIMEOUT = httpx.Timeout(120.0, connect=20.0)


class ExtractFailed(Exception):
    """L'extraction n'a pas abouti : dit en mots ; le fichier en place reste tel quel."""


@dataclass(frozen=True, slots=True)
class Extracted:
    path: Path
    tiles: int
    size: int
    minzoom: int
    maxzoom: int
    bounds: tuple[float, float, float, float]


def zone(text: str) -> tuple[float, float, float, float]:
    """Une zone nommée (« france »), ou « ouest,sud,est,nord » en degrés."""
    if text.strip().lower() in ZONES:
        return ZONES[text.strip().lower()]
    try:
        w, s, e, n = (float(v) for v in text.split(","))
    except ValueError:
        raise ExtractFailed(f"une zone : {', '.join(ZONES)}, ou ouest,sud,est,nord en degrés") from None
    if not (-180 <= w < e <= 180 and -85.06 <= s < n <= 85.06):
        raise ExtractFailed("une zone : ouest < est entre -180 et 180, sud < nord entre -85 et 85")
    return w, s, e, n


def tile_span(bbox: tuple[float, float, float, float], z: int) -> tuple[int, int, int, int]:
    """Les tuiles d'un zoom qui couvrent la zone : x et y de début et de fin, inclus."""
    w, s, e, n = bbox
    size = 2 ** z

    def x_of(lon: float) -> int:
        return min(size - 1, max(0, int((lon + 180) / 360 * size)))

    def y_of(lat: float) -> int:
        r = math.radians(max(-85.0511, min(85.0511, lat)))
        return min(size - 1, max(0, int((1 - math.asinh(math.tan(r)) / math.pi) / 2 * size)))

    return x_of(w), y_of(n), x_of(e), y_of(s)


def wanted(bbox: tuple[float, float, float, float], minzoom: int, maxzoom: int) -> array:
    """Les identifiants (courbe de Hilbert) des tuiles de la zone, triés. Ceux d'un zoom précèdent tous ceux du
    suivant : chaque zoom se trie à part (la liste d'un seul en mémoire à la fois)."""
    ids = array("Q")
    for z in range(minzoom, maxzoom + 1):
        x0, y0, x1, y1 = tile_span(bbox, z)
        ids.extend(sorted(zxy_to_tileid(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)))
    return ids


def _directory(ids: array, runs: array, lengths: array, offsets: array, lo: int, hi: int) -> bytes:
    """Un répertoire PMTiles (version 3) des entrées ``lo:hi``, compressé en gzip (comme ``serialize_directory``)."""
    b = io.BytesIO()
    write_varint(b, hi - lo)
    last = 0
    for i in range(lo, hi):
        write_varint(b, ids[i] - last)
        last = ids[i]
    for i in range(lo, hi):
        write_varint(b, runs[i])
    for i in range(lo, hi):
        write_varint(b, lengths[i])
    for i in range(lo, hi):
        if i > lo and offsets[i] == offsets[i - 1] + lengths[i - 1]:
            write_varint(b, 0)
        else:
            write_varint(b, offsets[i] + 1)
    return gzip.compress(b.getvalue(), mtime=0)


def directories(ids: array, runs: array, lengths: array, offsets: array) -> tuple[bytes, bytes]:
    """La racine et les feuilles : tout dans la racine si elle tient, sinon des feuilles de plus en plus grandes."""
    count = len(ids)
    root = _directory(ids, runs, lengths, offsets, 0, count)
    if len(root) < ROOT_MAX:
        return root, b""
    leaf_size = 4096
    while True:
        leaves = io.BytesIO()
        r_ids, r_runs, r_lens, r_offs = array("Q"), array("I"), array("I"), array("Q")
        for lo in range(0, count, leaf_size):
            leaf = _directory(ids, runs, lengths, offsets, lo, min(count, lo + leaf_size))
            r_ids.append(ids[lo])
            r_runs.append(0)
            r_lens.append(len(leaf))
            r_offs.append(leaves.tell())
            leaves.write(leaf)
        root = _directory(r_ids, r_runs, r_lens, r_offs, 0, len(r_ids))
        if len(root) < ROOT_MAX:
            return root, leaves.getvalue()
        leaf_size *= 2


async def latest_build(client: httpx.AsyncClient) -> str:
    """L'adresse de la dernière carte de la planète refaite par Protomaps."""
    try:
        r = await client.get(BUILDS)
        r.raise_for_status()
        keys = sorted(str(b["key"]) for b in r.json() if str(b.get("key", "")).endswith(".pmtiles"))
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise ExtractFailed(f"la liste des cartes de Protomaps ne se lit pas ({type(exc).__name__})") from None
    if not keys:
        raise ExtractFailed("Protomaps ne liste aucune carte")
    return BUILD_BASE + keys[-1]


def _retry_after(value: str) -> float:
    """L'attente que demande un serveur (``Retry-After`` en secondes) ; une date ou rien : aucune."""
    return min(RETRY_AFTER_MAX_S, float(value)) if value.strip().isdigit() else 0.0


def ranges(client: httpx.AsyncClient, url: str, *,
           pause: Callable[[float], Awaitable[object]] = asyncio.sleep) -> Read:
    """Lire une archive distante par plages, en flux : le statut d'abord (un serveur qui ignore les plages renverrait
    toute l'archive), puis au plus la plage demandée. Ce qui échoue en passant — une coupure, une plage courte, un
    serveur débordé (5xx, 429) — se réessaie, après l'attente qu'il demande ; un refus net (200 à une demande de
    plage, 404…) arrête tout, dit en mots."""
    async def read(offset: int, length: int) -> bytes:
        for attempt in range(TRIES):
            wait = float(2 ** attempt)
            try:
                async with client.stream("GET", url, headers={"Range": f"bytes={offset}-{offset + length - 1}",
                                                              "Accept-Encoding": "identity"}) as r:
                    if r.status_code == 206:
                        try:
                            data = await read_capped(r, length)
                        except ValueError:
                            raise ExtractFailed("le serveur rend plus que la plage demandée : il ne sert pas cette "
                                                "archive par plages") from None
                        if len(data) == length:
                            return data
                    elif r.status_code in TRANSIENT:
                        wait = max(wait, _retry_after(r.headers.get("retry-after", "")))
                    elif r.status_code in (200, 416):
                        raise ExtractFailed(f"le serveur ne sert pas cette archive par plages (HTTP {r.status_code})")
                    else:
                        raise ExtractFailed(f"le serveur refuse cette archive (HTTP {r.status_code})")
            except httpx.TransportError:
                pass
            if attempt + 1 < TRIES:
                await pause(wait)
        raise ExtractFailed(f"une plage de l'archive ne se télécharge pas ({offset}, {length} octets)")

    return read


async def _zone_entries(read: Read, h: HeaderDict, want: array) -> tuple[array, array, array, int]:
    """Les entrées de la zone (identifiant, où est son contenu dans la source, sa longueur), dans l'ordre des
    identifiants, et le nombre de répertoires lus : la racine, puis les feuilles qui touchent la zone, lues une à une
    et lâchées aussitôt (une feuille de la planète pèse quelques Mo, même en tableaux)."""
    ids, src, lengths = array("Q"), array("Q"), array("I")
    read_dirs = 0

    async def walk(offset: int, length: int, end: int) -> None:
        nonlocal read_dirs
        found = await fetch_directory(read, offset, length)
        read_dirs += 1
        for i in range(len(found)):
            tile_id, run = found.ids[i], found.runs[i]
            if run == 0:  # une feuille : les identifiants de la sienne à la suivante
                stop = found.ids[i + 1] if i + 1 < len(found) else end
                if bisect_left(want, tile_id) < bisect_left(want, stop):
                    await walk(h["leaf_directory_offset"] + found.offsets[i], found.lengths[i], stop)
                continue
            for k in range(bisect_left(want, tile_id), bisect_left(want, tile_id + run)):
                ids.append(want[k])
                src.append(h["tile_data_offset"] + found.offsets[i])
                lengths.append(found.lengths[i])

    await walk(h["root_offset"], h["root_length"], 2 ** 64)
    return ids, src, lengths, read_dirs


async def extract(read: Read, out: Path, bbox: tuple[float, float, float, float], maxzoom: int,
                  say: Callable[[str], None] = lambda _text: None) -> Extracted:
    """Écrire dans ``out`` les tuiles de la zone, jusqu'à ``maxzoom`` (au plus celui de la source)."""
    try:
        h = await Archive(read).header()
    except MapUnavailable as exc:
        raise ExtractFailed(str(exc)) from None
    except BROKEN:
        raise ExtractFailed("ce n'est pas une archive PMTiles (version 3) lisible") from None
    if h["tile_compression"] is Compression.UNKNOWN:
        raise ExtractFailed("la compression de ses tuiles est inconnue")
    minzoom, top = h["min_zoom"], min(maxzoom, h["max_zoom"])
    w, s, e, n = (max(bbox[0], h["min_lon_e7"] / 1e7), max(bbox[1], h["min_lat_e7"] / 1e7),
                  min(bbox[2], h["max_lon_e7"] / 1e7), min(bbox[3], h["max_lat_e7"] / 1e7))
    if not (w < e and s < n):
        raise ExtractFailed("la zone est hors de cette carte")
    want = wanted((w, s, e, n), minzoom, top)
    say(f"{len(want)} tuiles possibles dans la zone, zooms {minzoom} à {top}")

    # 1. les entrées de la zone, dans l'ordre des identifiants
    try:
        ids, src, lengths, read_dirs = await _zone_entries(read, h, want)
    except BROKEN:
        raise ExtractFailed("un répertoire de la carte source est abîmé") from None
    del want
    if not ids:
        raise ExtractFailed("aucune tuile de cette carte dans la zone")
    say(f"{len(ids)} tuiles trouvées dans {read_dirs} répertoires")

    # 2. une copie par contenu (l'océan, les terres vides partagent la leur), rangées dans l'ordre de la source : un
    #    tri d'indices et des tableaux, jamais un objet par tuile (la France en compte des millions)
    order = sorted(range(len(src)), key=src.__getitem__)
    new_of = array("Q", bytes(8 * len(src)))  # où va le contenu de chaque tuile, dans l'archive neuve
    u_src, u_len, u_new = array("Q"), array("I"), array("Q")
    total, last, here = 0, -1, 0
    for i in order:
        if src[i] != last:
            last, here = src[i], total
            u_src.append(last)
            u_len.append(lengths[i])
            u_new.append(here)
            total += lengths[i]
        new_of[i] = here
    del order
    free = shutil.disk_usage(out.parent).free
    if total * 1.05 + 64 * 1024 * 1024 > free:
        raise ExtractFailed(f"il faut {total / 1e9:.1f} Go libres à côté de {out.name} ({free / 1e9:.1f} Go)")

    # 3. les entrées de l'archive neuve : des suites d'identifiants qui partagent un contenu se replient
    o_ids, o_runs, o_lens, o_offs = array("Q"), array("I"), array("I"), array("Q")
    for k in range(len(ids)):
        tile_id, new = ids[k], new_of[k]
        if o_ids and o_offs[-1] == new and o_ids[-1] + o_runs[-1] == tile_id:
            o_runs[-1] += 1
            continue
        o_ids.append(tile_id)
        o_runs.append(1)
        o_lens.append(lengths[k])
        o_offs.append(new)
    addressed = len(ids)
    del ids, src, lengths, new_of
    root, leaves = directories(o_ids, o_runs, o_lens, o_offs)
    if not 0 <= h["metadata_length"] <= DIR_MAX_BYTES:
        raise ExtractFailed("les métadonnées de la carte source sont démesurées")
    metadata = await read(h["metadata_offset"], h["metadata_length"])  # compressé comme ses répertoires : tel quel
    lon, lat = (w + e) / 2, (s + n) / 2
    header = {**h, "root_offset": 127, "root_length": len(root), "metadata_offset": 127 + len(root),
              "metadata_length": len(metadata), "leaf_directory_offset": 127 + len(root) + len(metadata),
              "leaf_directory_length": len(leaves),
              "tile_data_offset": 127 + len(root) + len(metadata) + len(leaves), "tile_data_length": total,
              "addressed_tiles_count": addressed, "tile_entries_count": len(o_ids), "tile_contents_count": len(u_src),
              "clustered": True, "internal_compression": Compression.GZIP, "min_zoom": minzoom, "max_zoom": top,
              "min_lon_e7": int(w * 1e7), "min_lat_e7": int(s * 1e7), "max_lon_e7": int(e * 1e7),
              "max_lat_e7": int(n * 1e7), "center_zoom": min(top, max(minzoom, 6)), "center_lon_e7": int(lon * 1e7),
              "center_lat_e7": int(lat * 1e7)}
    del o_ids, o_runs, o_lens, o_offs
    say(f"{addressed} tuiles, {len(u_src)} contenus : {total / 1e6:.0f} Mo à copier")

    # 4. l'archive à côté, puis les tuiles par morceaux : PARALLEL ouvriers, chacun un morceau en mémoire à la fois
    partial = out.with_name(out.name + ".partiel")
    base = header["tile_data_offset"]
    # des morceaux de contenus voisins dans la source (des indices de u_src, et où finit le dernier octet à lire) :
    # un téléchargement chacun
    spans: list[tuple[int, int, int]] = []
    a, end = 0, 0
    for b in range(1, len(u_src) + 1):
        end = max(end, u_src[b - 1] + u_len[b - 1])
        if b == len(u_src) or u_src[b] - end > GAP_BYTES or u_src[b] + u_len[b] - u_src[a] > CHUNK_BYTES:
            spans.append((a, b, end))
            a, end = b, 0
    todo = iter(spans)
    done = [0, 0]  # octets copiés, morceaux

    async def worker(fd: int) -> None:
        for a, b, end in todo:  # un itérateur partagé : chaque morceau va à un seul ouvrier
            start = u_src[a]
            view = memoryview(await read(start, end - start))
            # ces contenus se suivent dans l'archive neuve ; dans la source, des tuiles d'ailleurs les séparent
            # parfois : une écriture par suite contiguë, sans recopie (et dans la boucle : rien n'écrit après la
            # fermeture du fichier)
            j = a
            while j < b:
                k = j + 1
                while k < b and u_src[k] == u_src[k - 1] + u_len[k - 1]:
                    k += 1
                _write_all(fd, view[u_src[j] - start:u_src[k - 1] + u_len[k - 1] - start], base + u_new[j])
                j = k
            done[0] += u_new[b - 1] + u_len[b - 1] - u_new[a]
            done[1] += 1
            if done[1] % 20 == 0 or done[1] == len(spans):
                say(f"{done[0] / 1e6:.0f} Mo sur {total / 1e6:.0f} Mo")

    fd = os.open(partial, os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o640)
    try:
        _write_all(fd, serialize_header(header) + root + metadata + leaves, 0)
        async with asyncio.TaskGroup() as workers:  # un ouvrier en échec arrête les autres, attendus avant la suite
            for _ in range(min(PARALLEL, len(spans))):
                workers.create_task(worker(fd))
        os.fsync(fd)
    except BaseException as exc:
        os.close(fd)
        partial.unlink(missing_ok=True)
        if isinstance(exc, BaseExceptionGroup):
            raise _first(exc) from None
        raise
    os.close(fd)
    os.replace(partial, out)
    return Extracted(out, addressed, out.stat().st_size, minzoom, top, (w, s, e, n))


def _write_all(fd: int, data: bytes | memoryview, offset: int) -> None:
    view = memoryview(data)
    while view:
        wrote = os.pwrite(fd, view, offset)
        if wrote <= 0:
            raise OSError("l'archive ne s'écrit plus")
        view, offset = view[wrote:], offset + wrote


def _first(group: BaseExceptionGroup) -> BaseException:
    """La première erreur d'un groupe d'ouvriers : celle qui a tout arrêté."""
    first = group.exceptions[0]
    return _first(first) if isinstance(first, BaseExceptionGroup) else first


async def assets(client: httpx.AsyncClient, folder: Path, say: Callable[[str], None] = lambda _text: None,
                 base: str = ASSETS_BASE) -> int:
    """Les polices (``FONTS``, leurs 256 plages) et les planches d'icônes (``FLAVORS``) du style Protomaps, dans
    ``folder`` (``fonts/`` et ``sprites/v4/``) ; rend le nombre de fichiers écrits."""
    wanted_files = [f"fonts/{font}/{i * 256}-{i * 256 + 255}.pbf" for font in FONTS for i in range(256)]
    wanted_files += ["fonts/OFL.txt"]
    wanted_files += [f"sprites/v4/{flavor}{scale}.{ext}" for flavor in FLAVORS for scale in ("", "@2x")
                     for ext in ("json", "png")]
    gate = asyncio.Semaphore(8)
    written = 0

    async def fetch(rel: str) -> None:
        nonlocal written
        async with gate:
            for attempt in range(TRIES):
                try:
                    r = await client.get(base + rel.replace(" ", "%20"))
                except httpx.TransportError:
                    await asyncio.sleep(2 ** attempt)
                    continue
                if r.status_code == 404:  # une plage qu'une police n'a pas
                    return
                if r.status_code == 200:
                    target = folder / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(r.content)
                    written += 1
                    return
                await asyncio.sleep(2 ** attempt)
        raise ExtractFailed(f"{rel} ne se télécharge pas")

    await asyncio.gather(*(fetch(rel) for rel in wanted_files))
    (folder / "LISEZMOI.txt").write_text(
        "Les polices et les icônes de la carte de sa position (ADR 0193), tirées de "
        f"{base} (polices sous licence OFL : fonts/OFL.txt).\n", encoding="utf-8")
    say(f"{written} fichiers dans {folder}")
    return written


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True,
                             cookies=no_cookies())

