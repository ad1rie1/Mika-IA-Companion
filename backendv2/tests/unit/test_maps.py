"""La carte de sa position (ADR 0193) : des tuiles lues dans une archive PMTiles du dossier de données, ou dans une
archive qu'un serveur sert par plages, ou relayées d'un serveur {z}/{x}/{y} — et jamais un chemin qui sorte de
``cartes/``, ni rien de la personne envoyé au serveur de carte."""

from __future__ import annotations

import gzip
import os
from pathlib import Path

import httpx
import pytest
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer
from pydantic import ValidationError

from mika.adapters.maps import FILE, IMAGE, SERVER, VECTOR, MapConfig, MapTiles, MapUnavailable
from mika.adapters.maps import extract as ex
from mika.adapters.maps.tiles import USER_AGENT, Archive

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
    got = await m.tile(12, 2082, 1378)
    # gardée compressée, servie sans le dire : le navigateur l'ouvrira
    assert got is not None and got.encoding == "gzip" and gzip.decompress(got.data) == b"rue Nationale"
    assert await m.tile(12, 0, 0) is None
    with pytest.raises(MapUnavailable):
        await m.tile(13, 0, 0)
    assert "HTTP 500" in m.last_error and asked[0] == "https://tuiles.example.test/12/2082/1378.mvt"
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
