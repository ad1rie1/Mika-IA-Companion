"""La carte de sa position par l'API par personne (ADR 0193) : à travers le vrai serveur. Ses tuiles, ses polices et
ses icônes viennent de ce serveur seul, à qui est connecté ; sans carte réglée, rien ne se charge (le plan dessiné) ;
la console règle d'où elles viennent."""

from __future__ import annotations

import gzip

from mika.adapters.maps import FILE, MapConfig
from tests.protocol.test_moi_mail import API, login, second_person
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée
from tests.unit.test_maps import LILLE, TILES, archive

MAP = API + "/phone/map"


def with_map(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    archive(live.data / "cartes" / "lille.pmtiles", TILES)
    client.portal.call(live.settings.save_map_config, MapConfig(source=FILE, file="cartes/lille.pmtiles"))
    return client, live


def test_without_a_map_nothing_loads_and_a_session_is_needed(world):  # noqa: F811
    client, _, _ = world
    assert client.get(MAP).status_code == 401
    bootstrap(client)
    got = client.get(MAP).json()
    assert got["ready"] is False and "plan dessiné" in got["reason"]
    assert client.get(MAP + "/tiles/0/0/0").status_code == 404


def test_its_tiles_come_from_this_server_as_the_archive_keeps_them(world):  # noqa: F811
    client, live = with_map(world)
    got = client.get(MAP).json()
    assert got["ready"] and got["kind"] == "vecteur" and (got["minzoom"], got["maxzoom"]) == (0, 2)
    assert got["tiles"] == "/api/moi/phone/map/tiles/{z}/{x}/{y}" and got["attribution"] == "© OpenStreetMap"
    assert [round(v, 4) for v in got["bounds"]] == list(LILLE)
    assert got["glyphs"] is None and got["sprite"] is None  # sans polices ni icônes : une carte sans noms
    tile = client.get(MAP + "/tiles/2/2/1")
    assert tile.status_code == 200 and tile.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    assert tile.headers["content-encoding"] == "gzip" and tile.headers["cache-control"] == "private, max-age=86400"
    assert tile.content == b"lille"  # le client HTTP l'a ouverte, comme le navigateur
    empty = client.get(MAP + "/tiles/2/3/3")
    assert empty.status_code == 204 and not empty.content  # aucune tuile là : une tuile vide
    assert client.get(MAP + "/tiles/1/9/9").status_code == 204  # hors du monde
    second_person(client, live)
    login(client, "lea")  # la carte n'est à personne : chaque personne connectée la lit
    assert client.get(MAP + "/tiles/0/0/0").content == b"monde"


def test_its_fonts_and_icons_are_served_from_their_folder_only(world):  # noqa: F811
    client, live = with_map(world)
    fonts = live.data / "cartes" / "assets" / "fonts" / "Noto Sans Regular"
    fonts.mkdir(parents=True)
    (fonts / "0-255.pbf").write_bytes(gzip.compress(b"glyphes"))
    sprites = live.data / "cartes" / "assets" / "sprites" / "v4"
    sprites.mkdir(parents=True)
    (sprites / "light.json").write_text('{"poi": {"x": 0, "y": 0, "width": 16, "height": 16, "pixelRatio": 1}}')
    got = client.get(MAP).json()
    assert got["glyphs"] == "/api/moi/phone/map/fonts/{fontstack}/{range}.pbf"
    assert got["sprite"] == "/api/moi/phone/map/sprites/v4"
    font = client.get(MAP + "/fonts/Noto Sans Medium,Noto Sans Regular/0-255.pbf")  # la première de la pile qui est là
    assert font.status_code == 200 and font.headers["content-type"] == "application/x-protobuf"
    sprite = client.get(MAP + "/sprites/v4/light.json")
    assert sprite.status_code == 200 and sprite.json()["poi"]["width"] == 16
    assert client.get(MAP + "/sprites/v4/light.svg").status_code == 404
    assert client.get(MAP + "/fonts/..%2F..%2F..%2Fsecret.key/0-255.pbf").status_code == 404
    assert client.get(MAP + "/sprites/..%2F..%2F..%2Fsecret.key").status_code == 404


def test_the_console_sets_where_the_map_comes_from(world):  # noqa: F811
    client, live = with_map(world)
    url = "/inspecteur/reglages/carte"
    page = client.get(url)
    assert page.status_code == 200 and "Carte de sa position" in page.text and "0 à 2" in page.text
    saved = client.post(url, data={"csrf": client.cookies.get("csrftoken"), "_section": "carte",
                                   "_champs": ["source", "url"], "source": "serveur",
                                   "url": "https://tuiles.example.test/{z}/{x}/{y}.mvt"})
    assert saved.status_code in (200, 303), saved.text[:300]
    cfg = client.portal.call(live.settings.map_config)
    assert cfg.source == "serveur" and cfg.zxy
    refused = client.post(url, data={"csrf": client.cookies.get("csrftoken"), "_section": "carte",
                                     "_champs": ["source", "file"], "source": "fichier", "file": "../secret.key"})
    assert refused.status_code == 400 and client.portal.call(live.settings.map_config).source == "serveur"
