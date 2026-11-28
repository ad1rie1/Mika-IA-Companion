"""La carte de sa position (ADR 0193) : des tuiles lues dans une archive PMTiles du dossier de données, ou dans une
archive qu'un serveur sert par plages, ou relayées d'un serveur {z}/{x}/{y} — et jamais un chemin qui sorte de
``cartes/``, ni rien de la personne envoyé au serveur de carte."""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import threading
from pathlib import Path

import httpx
import pytest
from pmtiles.tile import Compression, Entry, TileType, find_tile, serialize_directory, zxy_to_tileid
from pmtiles.writer import Writer
from pydantic import ValidationError

from mika.adapters.maps import FILE, IMAGE, SERVER, VECTOR, MapConfig, MapTiles, MapUnavailable
from mika.adapters.maps import extract as ex
from mika.adapters.maps import tiles as tl
from mika.adapters.maps.tiles import USER_AGENT, Archive, fetch_directory, read_directory

#: autour de Lille : ouest, sud, est, nord
LILLE = (2.9, 50.5, 3.2, 50.75)


def archive(path: Path, tiles: dict[tuple[int, int, int], bytes], *, kind: TileType = TileType.MVT,
            bounds: tuple[float, float, float, float] = LILLE) -> bytes:
    """Une archive PMTiles (version 3) de ces tuiles, gardées compressées comme celles de Protomaps."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        w = Writer(f)
        for (z, x, y), data in sorted(tiles.items(), key=lambda kv: zxy_to_tileid(*kv[0])):
            w.write_tile(zxy_to_tileid(z, x, y), gzip.compress(data, mtime=0))
        w.finalize({"tile_type": kind, "tile_compression": Compression.GZIP,
                    "min_lon_e7": int(bounds[0] * 1e7), "min_lat_e7": int(bounds[1] * 1e7),
                    "max_lon_e7": int(bounds[2] * 1e7), "max_lat_e7": int(bounds[3] * 1e7),
                    "center_zoom": 1, "center_lon_e7": int(3.06 * 1e7), "center_lat_e7": int(50.63 * 1e7)},
                   {"name": "essai"})
    return path.read_bytes()


TILES = {(0, 0, 0): b"monde", (1, 1, 0): b"nord-est", (2, 2, 1): b"lille"}


def maps(data: Path, **cfg: object) -> MapTiles:
    return MapTiles(data, lambda: MapConfig.model_validate(cfg))


async def test_a_file_archive_is_read_tile_by_tile(tmp_path):
    archive(tmp_path / "cartes" / "lille.pmtiles", TILES)
    m = maps(tmp_path, source=FILE, file="cartes/lille.pmtiles")
    info = await m.info()
    assert info.ready and info.kind == VECTOR and (info.minzoom, info.maxzoom) == (0, 2)
    assert info.bounds == pytest.approx(LILLE) and info.attribution == "© OpenStreetMap"
    got = await m.tile(1, 1, 0)
    assert got is not None and got.encoding == "gzip" and got.media == "application/vnd.mapbox-vector-tile"
    assert gzip.decompress(got.data) == b"nord-est"  # telle que l'archive la garde : le navigateur l'ouvre
    assert await m.tile(2, 3, 3) is None  # aucune là
    assert await m.tile(5, 0, 0) is None  # plus fin que l'archive
    assert await m.tile(1, 2, 0) is None  # hors du monde
    assert not info.fonts and not info.sprites  # sans polices ni icônes : une carte sans noms
    facts = dict(m.describe())
    assert facts["Zooms"] == "0 à 2" and facts["Source"] == "le fichier cartes/lille.pmtiles"
    await m.close()


async def test_a_replaced_file_is_read_again(tmp_path):
    path = tmp_path / "cartes" / "lille.pmtiles"
    archive(path, TILES)
    m = maps(tmp_path, source=FILE, file="cartes/lille.pmtiles")
    assert gzip.decompress((await m.tile(0, 0, 0)).data) == b"monde"
    archive(path, {(0, 0, 0): b"le monde, en mieux"})
    os.utime(path, ns=(1, 1))  # une autre date, quoi qu'il arrive
    assert gzip.decompress((await m.tile(0, 0, 0)).data) == b"le monde, en mieux"
    await m.close()


async def test_a_missing_or_foreign_file_says_why(tmp_path):
    m = maps(tmp_path, source=FILE, file="cartes/france.pmtiles")
    missing = await m.info()
    assert not missing.ready and missing.reason == "Le fichier cartes/france.pmtiles n'est pas sur le serveur."
    with pytest.raises(MapUnavailable):
        await m.tile(0, 0, 0)
    (tmp_path / "cartes").mkdir()
    (tmp_path / "cartes" / "france.pmtiles").write_bytes(b"ce n'est pas une carte" * 10)
    broken = await m.info()
    assert not broken.ready and broken.reason == "Ce n'est pas une archive PMTiles (version 3) lisible."
    assert dict(m.describe())["État"].startswith("illisible")
    none = await maps(tmp_path).info()
    assert not none.ready and "plan dessiné" in none.reason
    await m.close()


async def test_a_remote_archive_is_read_by_ranges_and_never_says_who_looks(tmp_path):
    raw = archive(tmp_path / "x.pmtiles", TILES, kind=TileType.PNG)
    seen: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        start, end = (int(v) for v in request.headers["range"].removeprefix("bytes=").split("-"))
        return httpx.Response(206, content=raw[start:end + 1])

    m = MapTiles(tmp_path, lambda: MapConfig(source=SERVER, url="https://cartes.example.test/france.pmtiles"),
                 transport=httpx.MockTransport(serve))
    info = await m.info()
    assert info.ready and info.kind == IMAGE and info.maxzoom == 2
    got = await m.tile(2, 2, 1)
    assert got is not None and got.media == "image/png" and gzip.decompress(got.data) == b"lille"
    assert {r.headers["user-agent"] for r in seen} == {USER_AGENT}
    assert not any("cookie" in r.headers or "authorization" in r.headers for r in seen)
    await m.close()

    whole = MapTiles(tmp_path, lambda: MapConfig(source=SERVER, url="https://cartes.example.test/france.pmtiles"),
                     transport=httpx.MockTransport(lambda r: httpx.Response(200, content=raw)))
    refused = await whole.info()
    assert not refused.ready and "par plages" in refused.reason and "par plages" in whole.last_error
    await whole.close()


async def test_a_tile_server_is_relayed(tmp_path):
    asked: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        if request.url.path == "/12/2082/1378.mvt":
            return httpx.Response(200, content=gzip.compress(b"rue Nationale", mtime=0),
                                  headers={"content-type": "application/x-protobuf"})
        if request.url.path.startswith("/13/"):
            return httpx.Response(500)
        return httpx.Response(404)

    url = "https://tuiles.example.test/{z}/{x}/{y}.mvt"
    m = MapTiles(tmp_path, lambda: MapConfig(source=SERVER, url=url, maxzoom=14),
                 transport=httpx.MockTransport(serve))
    info = await m.info()
    assert info.ready and info.kind == VECTOR and info.maxzoom == 14 and info.bounds is None
    assert asked == ["https://tuiles.example.test/0/0/0.mvt"]  # il répond (une tuile absente, mais il répond)
    got = await m.tile(12, 2082, 1378)
    # gardée compressée, servie sans le dire : le navigateur l'ouvrira
    assert got is not None and got.encoding == "gzip" and gzip.decompress(got.data) == b"rue Nationale"
    assert await m.tile(12, 0, 0) is None
    with pytest.raises(MapUnavailable):
        await m.tile(13, 0, 0)
    assert "HTTP 500" in m.last_error and asked[1] == "https://tuiles.example.test/12/2082/1378.mvt"
    await m.close()


class Counted(httpx.AsyncByteStream):
    """Un corps qui se lit morceau par morceau, et compte ce qu'on en a lu : une archive de plusieurs Go."""

    def __init__(self, chunk: bytes, count: int) -> None:
        self.chunk, self.count, self.pulled = chunk, count, 0

    async def __aiter__(self):
        for _ in range(self.count):
            self.pulled += 1
            yield self.chunk


async def test_a_server_that_ignores_ranges_is_refused_before_its_body_is_read(tmp_path):
    """Un serveur qui ignore les plages renvoie toute l'archive (des Go) : le statut se lit d'abord, et rien du corps
    n'entre en mémoire (sinon la France entière, à chaque lecture de la carte)."""
    whole = Counted(b"x" * 65536, 100_000)  # 6,5 Go, si on les lisait
    m = MapTiles(tmp_path, lambda: MapConfig(source=SERVER, url="https://cartes.example.test/france.pmtiles"),
                 transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=whole)))
    refused = await m.info()
    assert not refused.ready and "par plages" in refused.reason and whole.pulled == 0
    await m.close()

    # une plage « 206 » qui n'en finit pas : la lecture s'arrête juste après ce qu'on a demandé
    endless = Counted(b"y" * 1024, 100_000)
    m = MapTiles(tmp_path, lambda: MapConfig(source=SERVER, url="https://cartes.example.test/france.pmtiles"),
                 transport=httpx.MockTransport(lambda r: httpx.Response(206, stream=endless)))
    assert not (await m.info()).ready and endless.pulled <= 2
    await m.close()

    # une tuile relayée démesurée : refusée sans la lire au-delà de sa borne
    huge = Counted(b"z" * 65536, 10_000)
    url = "https://tuiles.example.test/{z}/{x}/{y}.png"
    m = MapTiles(tmp_path, lambda: MapConfig(source=SERVER, url=url, kind=IMAGE),
                 transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=huge)))
    with pytest.raises(MapUnavailable, match="démesurée"):
        await m.tile(3, 1, 1)
    assert huge.pulled <= tl.TILE_MAX_BYTES // 65536 + 1
    await m.close()


async def test_a_map_server_never_gets_back_its_cookies(tmp_path):
    """Un serveur de carte qui pose un cookie ne le reçoit jamais en retour : rien ne suit la personne d'une
    tuile à l'autre."""
    seen: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"png", headers={"set-cookie": "suivi=1; Path=/",
                                                            "content-type": "image/png"})

    m = MapTiles(tmp_path, lambda: MapConfig(source=SERVER, url="https://t.example.test/{z}/{x}/{y}.png",
                                             kind=IMAGE), transport=httpx.MockTransport(serve))
    await m.tile(1, 0, 0)
    await m.tile(1, 1, 0)
    assert len(seen) == 2 and "cookie" not in seen[1].headers
    await m.close()


async def test_an_unreachable_tile_server_is_not_ready_and_is_asked_again_a_minute_later(tmp_path):
    """Un serveur {z}/{x}/{y} injoignable : la carte n'est pas prête (le client garde son plan dessiné) ; la réponse
    se garde une minute, puis il est redemandé."""
    clock = [1000.0]
    down = [True]
    asked: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        if down[0]:
            raise httpx.ConnectError("injoignable", request=request)
        return httpx.Response(200, content=b"\x1f\x8bmonde")

    m = MapTiles(tmp_path, lambda: MapConfig(source=SERVER, url="https://t.example.test/{z}/{x}/{y}.mvt"),
                 transport=httpx.MockTransport(serve), now=lambda: clock[0])
    first = await m.info()
    assert not first.ready and "ne répond pas" in first.reason and asked == ["/0/0/0.mvt"]
    assert not (await m.info()).ready and len(asked) == 1  # gardé : pas redemandé
    down[0] = False
    clock[0] += 61
    again = await m.info()
    assert again.ready and len(asked) == 2 and again.version
    await m.close()


async def test_a_remote_archive_replaced_at_the_same_address_is_reopened(tmp_path):
    """Une archive distante refaite sous la même adresse : sa version (ETag) a changé, elle se rouvre — jamais les
    octets du nouveau fichier lus aux places de l'ancien."""
    old = archive(tmp_path / "v1.pmtiles", TILES)
    new = archive(tmp_path / "v2.pmtiles", {(0, 0, 0): b"le monde, en mieux", (1, 1, 0): b"au nord-est, refait"})
    served = {"raw": old, "etag": '"v1"'}

    def serve(request: httpx.Request) -> httpx.Response:
        start, end = (int(v) for v in request.headers["range"].removeprefix("bytes=").split("-"))
        raw = served["raw"]
        return httpx.Response(206, content=raw[start:end + 1], headers={
            "etag": served["etag"], "content-range": f"bytes {start}-{min(end, len(raw) - 1)}/{len(raw)}"})

    m = MapTiles(tmp_path, lambda: MapConfig(source=SERVER, url="https://cartes.example.test/x.pmtiles"),
                 transport=httpx.MockTransport(serve))
    before = await m.info()
    assert gzip.decompress((await m.tile(1, 1, 0)).data) == b"nord-est"
    served.update(raw=new, etag='"v2"')
    assert gzip.decompress((await m.tile(1, 1, 0)).data) == b"au nord-est, refait"
    after = await m.info()
    assert after.ready and after.version != before.version  # d'autres adresses : le navigateur ne ressert rien
    await m.close()


async def test_a_remote_archive_without_validator_is_reread_every_minute(tmp_path):
    """Sans ETag ni date, son en-tête se relit au plus une fois par minute : une autre archive s'y voit, et un
    serveur qui ne répond plus rend la carte « pas prête »."""
    clock = [0.0]
    old = archive(tmp_path / "v1.pmtiles", TILES)
    new = archive(tmp_path / "v2.pmtiles", {(0, 0, 0): b"autre"}, bounds=(2.0, 48.0, 3.0, 49.0))
    served: dict[str, object] = {"raw": old, "down": False}

    def serve(request: httpx.Request) -> httpx.Response:
        if served["down"]:
            raise httpx.ConnectError("injoignable", request=request)
        start, end = (int(v) for v in request.headers["range"].removeprefix("bytes=").split("-"))
        return httpx.Response(206, content=served["raw"][start:end + 1])  # type: ignore[index]

    m = MapTiles(tmp_path, lambda: MapConfig(source=SERVER, url="https://cartes.example.test/x.pmtiles"),
                 transport=httpx.MockTransport(serve), now=lambda: clock[0])
    assert (await m.info()).bounds == pytest.approx(LILLE)
    served["raw"] = new
    assert (await m.info()).bounds == pytest.approx(LILLE)  # moins d'une minute : pas relue
    clock[0] += 61
    assert (await m.info()).bounds == pytest.approx((2.0, 48.0, 3.0, 49.0))
    served["down"] = True
    clock[0] += 61
    gone = await m.info()
    assert not gone.ready and "ne répond pas" in gone.reason
    with pytest.raises(MapUnavailable):
        await m.tile(0, 0, 0)
    served["down"] = False  # revenu : rouverte d'elle-même, sans redémarrer
    assert (await m.info()).ready and gzip.decompress((await m.tile(0, 0, 0)).data) == b"autre"
    await m.close()


async def test_a_file_replaced_during_a_read_is_closed_only_after_it(tmp_path, monkeypatch):
    """« mika carte extraire » remplace le fichier pendant qu'on regarde la carte : une lecture en cours finit sur
    l'ancien (son descripteur reste ouvert jusque-là), la suivante lit le neuf."""
    path = tmp_path / "cartes" / "lille.pmtiles"
    archive(path, TILES)
    m = maps(tmp_path, source=FILE, file="cartes/lille.pmtiles")
    assert (await m.info()).ready
    old = m._open
    old_fd = _fd_of(old)
    gate, entered = threading.Event(), threading.Event()
    real = os.pread

    def pread(fd: int, length: int, offset: int) -> bytes:
        if fd == old_fd and not gate.is_set():  # la première lecture sur l'ancien fichier attend qu'on la lâche
            entered.set()
            gate.wait(5)
        return real(fd, length, offset)

    monkeypatch.setattr(tl.os, "pread", pread)
    reading = asyncio.ensure_future(m.tile(1, 1, 0))  # s'arrête dans sa première lecture, sur l'ancien fichier
    await asyncio.to_thread(entered.wait, 5)
    # comme l'extraction : l'archive neuve écrite à côté, puis mise à la place d'un coup (un autre fichier)
    archive(path.with_name("lille.pmtiles.partiel"), {(0, 0, 0): b"le monde, en mieux", (1, 1, 0): b"refait"})
    os.replace(path.with_name("lille.pmtiles.partiel"), path)
    os.utime(path, ns=(1, 1))  # une autre date, quoi qu'il arrive
    assert gzip.decompress((await m.tile(1, 1, 0)).data) == b"refait"  # la suivante : le neuf
    assert not old.closed  # l'ancien attend sa lecture
    gate.set()
    assert gzip.decompress((await reading).data) == b"nord-est"  # finie sur l'ancien, sans erreur
    assert old.closed
    await m.close()


def _fd_of(opened) -> int:
    """Le descripteur du fichier d'une archive ouverte (dans la fermeture de son lecteur)."""
    read = opened.archive._read
    return next(c.cell_contents for c in read.__closure__ if isinstance(c.cell_contents, int))


async def test_a_large_directory_is_read_outside_the_event_loop(tmp_path, monkeypatch):
    """Une feuille de la planète prend un dixième de seconde à lire : hors de la boucle, qui sert les autres."""
    entries = [Entry(i * 3, i * 10, 10, 1) for i in range(5000)]
    raw = serialize_directory(entries)
    where: list[bool] = []
    real = tl.read_directory

    def spy(data: bytes):
        where.append(threading.current_thread() is threading.main_thread())
        return real(data)

    monkeypatch.setattr(tl, "read_directory", spy)
    monkeypatch.setattr(tl, "DIR_THREAD_BYTES", len(raw) - 1)

    async def read(offset: int, length: int) -> bytes:
        return raw

    assert len(await fetch_directory(read, 0, len(raw))) == 5000
    monkeypatch.setattr(tl, "DIR_THREAD_BYTES", len(raw) + 1)
    assert len(await fetch_directory(read, 0, len(raw))) == 5000
    assert where == [False, True]  # le gros dans un fil, le petit sur place


async def test_a_directory_read_twice_at_once_is_read_once(tmp_path):
    """Les tuiles d'une vue neuve demandent la même feuille en même temps : une seule lecture."""
    raw = archive(tmp_path / "x.pmtiles", TILES)
    reads: list[tuple[int, int]] = []

    async def read(offset: int, length: int) -> bytes:
        reads.append((offset, length))
        await asyncio.sleep(0.01)
        return raw[offset:offset + length]

    copy = Archive(read)
    h = await copy.header()
    got = await asyncio.gather(*(copy.directory(h["root_offset"], h["root_length"]) for _ in range(6)))
    assert len({id(d) for d in got}) == 1 and reads.count((h["root_offset"], h["root_length"])) == 1


async def test_the_tile_addresses_change_with_the_source(tmp_path):
    """La version de la source change avec le fichier (sa date, sa taille) ou le réglage : le navigateur ne ressert
    jamais d'une carte ce qu'il gardait d'une autre."""
    path = tmp_path / "cartes" / "lille.pmtiles"
    archive(path, TILES)
    cfg = [MapConfig(source=FILE, file="cartes/lille.pmtiles")]
    m = MapTiles(tmp_path, lambda: cfg[0])
    first = (await m.info()).version
    assert first and (await m.info()).version == first  # stable tant que rien ne change
    archive(path, {(0, 0, 0): b"autre"})
    os.utime(path, ns=(1, 1))
    second = (await m.info()).version
    assert second != first
    cfg[0] = MapConfig(source=FILE, file="cartes/lille.pmtiles", attribution="© OpenStreetMap, autrement")
    assert (await m.info()).version not in (first, second)
    await m.close()


def test_its_paths_stay_under_maps_and_its_address_is_complete():
    for bad in ("../secret.key", "/etc/passwd", "cartes/../mind.db", "autre/france.pmtiles", "cartes",
                "cartes\\france.pmtiles", ""):
        with pytest.raises(ValidationError):
            MapConfig(source=FILE, file=bad)
        with pytest.raises(ValidationError):
            MapConfig(assets=bad)
    assert MapConfig(source=FILE, file=" cartes/france.pmtiles ").file == "cartes/france.pmtiles"
    for bad in ("ftp://cartes.example.test/x.pmtiles", "https://cartes.example.test/{z}/{x}.mvt", "pas une adresse"):
        with pytest.raises(ValidationError):
            MapConfig(source=SERVER, url=bad)
    with pytest.raises(ValidationError):
        MapConfig(source=SERVER)  # un serveur : son adresse
    assert MapConfig(source=SERVER, url="https://t.example.test/{z}/{x}/{y}.png").zxy
    assert MapConfig(attribution="  ").attribution == "© OpenStreetMap"  # la mention ne s'efface pas


def test_its_fonts_and_icons_never_leave_their_folder(tmp_path):
    font = tmp_path / "cartes" / "assets" / "fonts" / "Noto Sans Regular" / "0-255.pbf"
    font.parent.mkdir(parents=True)
    font.write_bytes(b"glyphes")
    (tmp_path / "secret.key").write_bytes(b"cle")
    m = maps(tmp_path)
    assert m.asset("fonts", "Noto Sans Regular/0-255.pbf") == font.resolve()
    assert m.asset("fonts", "../../../secret.key") is None
    assert m.asset("fonts", "") is None
    assert m.asset("ailleurs", "Noto Sans Regular/0-255.pbf") is None


async def test_a_zone_is_extracted_from_an_archive_read_by_ranges(tmp_path):
    """« mika carte extraire » : seules les tuiles de la zone se copient, l'océan partagé une seule fois ; l'archive
    neuve se lit comme l'autre, et dit sa zone."""
    tiles: dict[tuple[int, int, int], bytes] = {}
    for z in range(0, 6):
        for x in range(2 ** z):
            for y in range(2 ** z):
                tiles[(z, x, y)] = b"ocean" if (x + y) % 3 == 0 else f"terre {z}/{x}/{y}".encode()
    raw = archive(tmp_path / "planete.pmtiles", tiles, bounds=(-180, -85, 180, 85))
    asked: list[int] = []

    async def read(offset: int, length: int) -> bytes:
        asked.append(length)
        return raw[offset:offset + length]

    out = tmp_path / "cartes" / "zone.pmtiles"
    out.parent.mkdir()
    said: list[str] = []
    got = await ex.extract(read, out, (2.9, 50.5, 3.2, 50.75), 4, say=said.append)
    assert got.maxzoom == 4 and got.minzoom == 0 and got.bounds == pytest.approx((2.9, 50.5, 3.2, 50.75))
    assert not out.with_name(out.name + ".partiel").exists()
    copy = Archive(lambda o, n: _slice(out.read_bytes(), o, n))
    h = await copy.header()
    assert (h["min_zoom"], h["max_zoom"]) == (0, 4) and h["min_lon_e7"] == int(2.9 * 1e7)
    for z in range(0, 5):
        x0, y0, x1, y1 = ex.tile_span((2.9, 50.5, 3.2, 50.75), z)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                assert gzip.decompress(await copy.tile(z, x, y)) == tiles[(z, x, y)]
    assert await copy.tile(4, 0, 0) is None  # hors de la zone
    assert await copy.tile(5, 16, 10) is None  # plus fin que demandé
    assert sum(asked) < len(raw)  # seule la zone s'est téléchargée
    assert said and "tuiles" in said[0]


async def _slice(raw: bytes, offset: int, length: int) -> bytes:
    return raw[offset:offset + length]


def test_a_zone_is_named_or_given_in_degrees():
    assert ex.zone("France") == ex.ZONES["france"]
    assert ex.zone("2.9,50.5,3.2,50.75") == (2.9, 50.5, 3.2, 50.75)
    for bad in ("lille", "3,50", "3.2,50.5,2.9,50.75", "0,-90,10,10"):
        with pytest.raises(ex.ExtractFailed):
            ex.zone(bad)


def test_a_directory_is_read_into_arrays_as_pmtiles_reads_it():
    """Une feuille de la planète compte plus de 100 000 entrées : lue en tableaux (24 octets chacune), elle dit la même
    chose que ``pmtiles`` en objets, et se cherche de même."""
    entries, offset = [], 0
    for i in range(3000):
        run = 0 if i % 97 == 0 else 1 + i % 5  # des feuilles, des suites (l'océan), des tuiles seules
        length = 40 + i % 300
        entries.append(Entry(10 * i + i % 7, offset if i % 11 else offset + 5, length, run))
        offset += length + (5 if i % 11 == 0 else 0)
    raw = serialize_directory(entries)
    got = read_directory(raw)
    assert len(got) == len(entries)
    assert list(got.ids) == [e.tile_id for e in entries] and list(got.runs) == [e.run_length for e in entries]
    assert list(got.lengths) == [e.length for e in entries] and list(got.offsets) == [e.offset for e in entries]
    for tile_id in range(-1, 10 * 3000 + 20):
        theirs = find_tile(entries, tile_id)
        ours = got.find(tile_id) if tile_id >= 0 else None
        assert (None if theirs is None else theirs.tile_id) == (None if ours is None else got.ids[ours])


async def test_a_broken_or_outsized_directory_is_refused():
    raw = serialize_directory([Entry(1, 0, 10, 1), Entry(2, 10, 10, 1)])
    for bad in (raw[:-3], gzip.compress(b"\x05\x01"), gzip.compress(b"\xff" * 20), b"pas du gzip"):
        with pytest.raises(ValueError):
            read_directory(bad)
    with pytest.raises(ValueError):
        read_directory(gzip.compress(bytes([1, 1, 1, 1, 0])))  # un décalage de -1

    async def never(offset: int, length: int) -> bytes:
        raise AssertionError("rien ne se télécharge")

    for length in (0, tl.DIR_MAX_BYTES + 1):
        with pytest.raises(ValueError):
            await fetch_directory(never, 0, length)


async def test_the_directories_kept_are_bounded_by_their_entries(tmp_path, monkeypatch):
    """Ce qui reste en mémoire se compte en entrées, pas en répertoires : quelques feuilles de la planète suffiraient
    à remplir le portable."""
    tiles = {(z, x, y): f"{z}/{x}/{y}".encode() for z in range(0, 7) for x in range(2 ** z) for y in range(2 ** z)}
    raw = archive(tmp_path / "x.pmtiles", tiles)
    copy = Archive(lambda o, n: _slice(raw, o, n))
    monkeypatch.setattr(tl, "ENTRIES_KEPT", 10)
    for (z, x, y), data in list(tiles.items())[::37]:
        assert gzip.decompress(await copy.tile(z, x, y)) == data
        assert copy._kept <= 10 or len(copy._dirs) == 1  # le dernier lu reste, même gros
        assert copy._kept == sum(len(d) for d in copy._dirs.values())


async def test_an_extraction_in_many_pieces_writes_the_same_archive(tmp_path, monkeypatch):
    """Des morceaux petits, des écarts (les tuiles d'ailleurs) entre eux, plusieurs ouvriers : l'archive neuve est la
    même, octet pour octet, qu'en un seul morceau."""
    tiles = {(z, x, y): (b"ocean" if (x * 7 + y) % 5 == 0 else f"terre {z}/{x}/{y} ".encode() * (1 + x % 3))
             for z in range(0, 7) for x in range(2 ** z) for y in range(2 ** z)}
    raw = archive(tmp_path / "planete.pmtiles", tiles, bounds=(-180, -85, 180, 85))
    bbox = (-20.0, 30.0, 40.0, 60.0)

    async def read(offset: int, length: int) -> bytes:
        return raw[offset:offset + length]

    whole = tmp_path / "cartes" / "entiere.pmtiles"
    whole.parent.mkdir()
    await ex.extract(read, whole, bbox, 6)
    monkeypatch.setattr(ex, "CHUNK_BYTES", 300)
    monkeypatch.setattr(ex, "GAP_BYTES", 0)
    pieces = tmp_path / "cartes" / "morceaux.pmtiles"
    said: list[str] = []
    await ex.extract(read, pieces, bbox, 6, say=said.append)
    assert pieces.read_bytes() == whole.read_bytes()
    assert sum("Mo sur" in line for line in said) >= 2  # bien des morceaux


async def test_a_failed_piece_leaves_the_archive_in_place(tmp_path, monkeypatch):
    """Un morceau qui ne se télécharge pas : l'erreur dite en mots (pas un groupe d'erreurs), l'archive en place
    intacte, le fichier partiel effacé."""
    tiles = {(z, x, y): f"terre {z}/{x}/{y}".encode() for z in range(0, 6) for x in range(2 ** z) for y in range(2 ** z)}
    raw = archive(tmp_path / "planete.pmtiles", tiles, bounds=(-180, -85, 180, 85))
    out = tmp_path / "cartes" / "zone.pmtiles"
    out.parent.mkdir()
    out.write_bytes(b"l'ancienne")
    monkeypatch.setattr(ex, "CHUNK_BYTES", 200)
    calls = 0

    async def read(offset: int, length: int) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 6:
            raise ex.ExtractFailed("une plage de l'archive ne se télécharge pas")
        return raw[offset:offset + length]

    with pytest.raises(ex.ExtractFailed, match="ne se télécharge pas"):
        await ex.extract(read, out, (-20.0, 30.0, 40.0, 60.0), 5)
    assert out.read_bytes() == b"l'ancienne" and not out.with_name(out.name + ".partiel").exists()


async def test_a_source_that_is_not_an_archive_says_so(tmp_path):
    async def read(offset: int, length: int) -> bytes:
        return (b"ce n'est pas une carte" * 20)[offset:offset + length]

    with pytest.raises(ex.ExtractFailed, match="PMTiles"):
        await ex.extract(read, tmp_path / "zone.pmtiles", (2.9, 50.5, 3.2, 50.75), 4)


async def test_an_extraction_retries_a_busy_server_and_stops_on_a_refusal():
    """``mika carte extraire`` lit des milliers de plages : un serveur débordé (503, 429) se réessaie après l'attente
    qu'il demande ; un refus net arrête, dit en mots ; une réponse entière (200) n'est jamais lue."""
    raw = bytes(range(256)) * 64
    answers = [httpx.Response(503, headers={"retry-after": "3"}), httpx.Response(429)]

    def serve(request: httpx.Request) -> httpx.Response:
        if answers:
            return answers.pop(0)
        start, end = (int(v) for v in request.headers["range"].removeprefix("bytes=").split("-"))
        assert request.headers["accept-encoding"] == "identity"  # des octets tels quels, jamais recompressés
        return httpx.Response(206, content=raw[start:end + 1])

    waited: list[float] = []

    async def pause(seconds: float) -> None:
        waited.append(seconds)

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
        read = ex.ranges(client, "https://build.example.test/planete.pmtiles", pause=pause)
        assert await read(100, 50) == raw[100:150]
    assert waited == [3.0, 2.0]  # l'attente demandée, puis le recul ordinaire

    whole = Counted(b"x" * 65536, 100_000)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=whole))) as client:
        with pytest.raises(ex.ExtractFailed, match="par plages"):
            await ex.ranges(client, "https://x.example.test/p.pmtiles", pause=pause)(0, 127)
    assert whole.pulled == 0

    refused = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r: refused.append(r) or httpx.Response(404))) as client:
        with pytest.raises(ex.ExtractFailed, match="refuse"):
            await ex.ranges(client, "https://x.example.test/p.pmtiles", pause=pause)(0, 127)
    assert len(refused) == 1  # un refus ne se réessaie pas


def test_the_map_command_says_what_a_setting_wants(tmp_path, capsys):
    """« mika carte » qui refuse une sortie hors de cartes/ dit pourquoi — jamais l'adresse de la documentation de
    pydantic (la dernière ligne de son message)."""
    from mika.app import cli

    for args in (["carte", "extraire", "--sortie", "france.pmtiles"], ["carte", "lieux", "--sortie", "lieux.db"],
                 ["carte", "lieux", "--depuis", "../secret.key"]):
        assert cli.main(["--data", str(tmp_path), *args]) == 1
        said = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert said["ok"] is False and "cartes/" in said["erreur"] and "pydantic" not in said["erreur"]
