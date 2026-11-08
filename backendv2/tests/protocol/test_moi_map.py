"""La carte de sa position par l'API par personne (ADR 0193) : à travers le vrai serveur. Ses tuiles, ses polices et
ses icônes viennent de ce serveur seul, à qui est connecté ; sans carte réglée, rien ne se charge (le plan dessiné) ;
la console règle d'où elles viennent."""

from __future__ import annotations

import gzip
import os
import re

from pmtiles.tile import Compression

from mika.adapters.maps import FILE, MapConfig, MapsDesk, PlacesConfig, RoutingConfig
from tests.protocol.test_moi_mail import API, login, second_person
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée
from tests.unit.test_maps import LILLE, TILES, archive

MAP = API + "/phone/map"
#: où l'en-tête d'une archive PMTiles (version 3) dit comment ses répertoires sont compressés
INTERNAL_COMPRESSION = 97
NOT_READY = "La carte n'est pas encore prête sur ce serveur."


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


def test_a_server_without_a_map_says_so_to_everyone(world):  # noqa: F811
    """Rien de réglé n'est pas une panne, et cela ne demande rien à personne : tout le monde le lit."""
    client, live, _ = world
    bootstrap(client)
    second_person(client, live)
    login(client, "lea")
    assert "plan dessiné" in client.get(MAP).json()["reason"]


def test_a_person_reads_that_the_map_is_not_ready_never_what_is_wrong_with_it(world):  # noqa: F811
    """Une personne n'a ni la console ni le serveur : d'une carte réglée qui ne se lit pas, elle lit que ça n'est pas
    prêt, sans la consigne ni le fichier. Une opératrice, sur les mêmes routes, lit ce qui ne va pas."""
    client, live = with_map(world)
    file = live.data / "cartes" / "lille.pmtiles"
    raw = bytearray(file.read_bytes())
    raw[INTERNAL_COMPRESSION] = Compression.NONE.value
    file.write_bytes(raw)

    def said() -> list[str]:
        got, tile = client.get(MAP).json(), client.get(MAP + "/tiles/0/0/0")
        assert got["ready"] is False and tile.status_code == 503
        return [got["reason"], tile.json()["error"]]

    assert all("refaites-la" in text and "deploy/README.md" in text for text in said())
    second_person(client, live)
    login(client, "lea")
    assert said() == [NOT_READY, NOT_READY]
    file.unlink()
    assert said() == [NOT_READY, NOT_READY]


def test_its_tiles_come_from_this_server_as_the_archive_keeps_them(world):  # noqa: F811
    client, live = with_map(world)
    got = client.get(MAP).json()
    assert got["ready"] and got["kind"] == "vecteur" and (got["minzoom"], got["maxzoom"]) == (0, 2)
    assert re.fullmatch(r"/api/moi/phone/map/tiles/\{z\}/\{x\}/\{y\}\?v=[0-9a-f]{12}", got["tiles"])
    assert got["attribution"] == "© OpenStreetMap"
    assert [round(v, 4) for v in got["bounds"]] == list(LILLE)
    assert got["glyphs"] is None and got["sprite"] is None  # sans polices ni icônes : une carte sans noms
    versioned = client.get(got["tiles"].replace("{z}", "2").replace("{x}", "2").replace("{y}", "1"))
    assert versioned.status_code == 200 and versioned.content == b"lille"  # la version : acceptée, ignorée
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
    version = got["tiles"].rpartition("?v=")[2]
    assert got["glyphs"] == f"/api/moi/phone/map/fonts/{{fontstack}}/{{range}}.pbf?v={version}"
    # MapLibre ajoute « /light.json », « /dark@2x.png »… au chemin des icônes : leur version est un segment
    assert got["sprite"] == f"/api/moi/phone/map/sprites/~{version}/v4"
    font = client.get(MAP + "/fonts/Noto Sans Medium,Noto Sans Regular/0-255.pbf")  # la première de la pile qui est là
    assert font.status_code == 200 and font.headers["content-type"] == "application/x-protobuf"
    stack = got["glyphs"].replace("{fontstack}", "Noto Sans Regular").replace("{range}", "0-255")
    assert client.get(stack).status_code == 200
    sprite = client.get(MAP + "/sprites/v4/light.json")
    assert sprite.status_code == 200 and sprite.json()["poi"]["width"] == 16
    assert client.get(got["sprite"] + "/light.json").json() == sprite.json()
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


def test_a_replaced_map_gets_new_tile_addresses(world):  # noqa: F811
    """Le navigateur garde une tuile un jour : une carte remplacée (un autre fichier, une autre source) lui donne
    d'autres adresses, et il ne ressert rien de l'ancienne."""
    client, live = with_map(world)
    before = client.get(MAP).json()["tiles"]
    path = live.data / "cartes" / "lille.pmtiles"
    archive(path, {(0, 0, 0): b"le monde, en mieux"})
    os.utime(path, ns=(1, 1))
    after = client.get(MAP).json()["tiles"]
    assert after != before and after.split("?")[0] == before.split("?")[0]
    assert client.get(after.replace("{z}", "0").replace("{x}", "0").replace("{y}", "0")).content == \
        b"le monde, en mieux"


def test_the_kernel_has_the_maps_port(world):  # noqa: F811
    """Le port ``maps`` du noyau : ce que le plugin des voyages et l'API de l'écran Carte lisent (ADR 0194)."""
    _client, live, _ = world
    desk = live.kernel.ports.get("maps")
    assert isinstance(desk, MapsDesk)


def test_the_console_sets_places_addresses_and_routes(world):  # noqa: F811
    """Réglages › Carte et téléphone : « Lieux et adresses », « Itinéraires » (ADR 0194) — par défaut rien ne sort ; un
    Valhalla à soi demande son adresse."""
    client, live, _ = world
    bootstrap(client)
    places = client.get("/inspecteur/reglages/lieux")
    assert places.status_code == 200 and "Lieux et adresses" in places.text
    assert "mika carte lieux" in places.text and "aucune : rien ne sort" in places.text
    saved = client.post("/inspecteur/reglages/lieux", data={
        "csrf": client.cookies.get("csrftoken"), "_section": "lieux", "_champs": ["index", "addresses"],
        "index": "cartes/lieux.db", "addresses": "geoplateforme"})
    assert saved.status_code in (200, 303), saved.text[:300]
    assert client.portal.call(live.settings.places_config) == PlacesConfig(addresses="geoplateforme")
    desk = live.kernel.ports.get("maps")
    assert client.portal.call(desk.addresses_ready)  # relu à chaque usage : sans redémarrer
    routes = client.get("/inspecteur/reglages/itineraires")
    assert routes.status_code == 200 and "Itinéraires" in routes.text and "aucun" in routes.text
    refused = client.post("/inspecteur/reglages/itineraires", data={
        "csrf": client.cookies.get("csrftoken"), "_section": "itineraires", "_champs": ["source", "url"],
        "source": "valhalla", "url": ""})
    assert refused.status_code == 400 and client.portal.call(live.settings.routing_config).source == "aucun"
    saved = client.post("/inspecteur/reglages/itineraires", data={
        "csrf": client.cookies.get("csrftoken"), "_section": "itineraires", "_champs": ["source", "url"],
        "source": "fossgis", "url": ""})
    assert saved.status_code in (200, 303), saved.text[:300]
    assert client.portal.call(live.settings.routing_config) == RoutingConfig(source="fossgis")
    assert client.portal.call(desk.routing_ready)
    assert client.portal.call(desk.routing_provider) == "Valhalla, serveur public de FOSSGIS"
    assert "une demande par seconde" in client.get("/inspecteur/reglages/itineraires").text
