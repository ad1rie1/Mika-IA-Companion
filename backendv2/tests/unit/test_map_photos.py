"""Les photos relayées (ADR 0245) : une référence ``p:<hash>`` ne mène qu'à une adresse venue des données (jamais à
une adresse donnée par un client), relevée une fois puis gardée sous ``cartes/photos`` (borné : les moins récemment
servies partent) ; ce qui n'est pas une image, ce qui est trop gros, une adresse du réseau local, une photo dont les
droits ont pris fin : refusés, en mots."""

from __future__ import annotations

import os
import socket
import sqlite3
from datetime import date
from pathlib import Path

import httpcore
import httpx
import pytest

from mika.adapters.maps.config import PlacesConfig, RoutingConfig
from mika.adapters.maps.datatourisme import EVENTS, PLACES
from mika.adapters.maps.desk import MapsDesk
from mika.adapters.maps.pace import Pace
from mika.adapters.maps.photos import (
    PhotoOrigin,
    PhotoRelay,
    guarded_transport,
    joinable,
    media_of,
    photo_ref,
    public_url,
)
from mika.ports.maps import MapsBadMedia, MapsUnavailable
from tests.fixtures import tourism as tf

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 64
TODAY = date(2026, 11, 18)


class Source:
    def __init__(self, known: dict[str, PhotoOrigin]) -> None:
        self.known = known

    def photo_origin(self, ref: str) -> PhotoOrigin | None:
        return self.known.get(ref)


class Host:
    """Le serveur d'images joué : ce qu'il rend pour chaque adresse, et ce qu'on lui a demandé."""

    def __init__(self, served: dict[str, httpx.Response]) -> None:
        self.served = served
        self.asked: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(str(request.url))
        return self.served.get(str(request.url), httpx.Response(404))


def relay(tmp_path: Path, urls: dict[str, tuple[httpx.Response, str]], **kwargs) -> tuple[PhotoRelay, Host]:
    host = Host({url: response for url, (response, _end) in urls.items()})
    source = Source({photo_ref(url): PhotoOrigin(url, "datatourisme", end) for url, (_r, end) in urls.items()})
    clock = tf.Clock()
    got = PhotoRelay(tmp_path / "cartes" / "photos", sources=[source], today=lambda: TODAY,
                     transport=httpx.MockTransport(host), pace=Pace(1000.0, now=clock.stamp, sleep=clock.sleep),
                     **kwargs)
    return got, host


async def test_a_known_photo_is_fetched_once_then_served_from_the_cache(tmp_path):
    url = "https://media.exemple.fr/a.jpg"
    photos, host = relay(tmp_path, {url: (httpx.Response(200, content=JPEG, headers={"content-type": "text/html"}),
                                          "")})
    assert await photos.get(photo_ref(url)) == (JPEG, "image/jpeg")  # le type lu aux octets, pas à l'en-tête
    assert await photos.get(photo_ref(url)) == (JPEG, "image/jpeg")
    assert host.asked == [url] and photos.fetched == 1 and photos.served == 2
    assert photos.size() == (1, len(JPEG))


async def test_an_unknown_reference_is_refused_and_nothing_is_fetched(tmp_path):
    photos, host = relay(tmp_path, {})
    for ref in (photo_ref("https://ailleurs.exemple/x.jpg"), "p:../../etc/passwd", "https://exemple.fr/x.jpg", "",
                "p:" + "0" * 31):
        with pytest.raises(MapsUnavailable) as caught:
            await photos.get(ref)
        assert "pas connue" in str(caught.value)
    assert host.asked == []


async def test_what_is_not_an_image_or_too_big_is_refused_and_not_kept(tmp_path):
    page, big = "https://media.exemple.fr/page.jpg", "https://media.exemple.fr/grosse.jpg"
    photos, _host = relay(tmp_path, {page: (httpx.Response(200, content=b"<html>pas une image</html>"), ""),
                                     big: (httpx.Response(200, content=JPEG + b"\x00" * 5000), "")}, photo_max=1024)
    with pytest.raises(MapsBadMedia) as caught:  # elle a répondu, pas une image : un 502, pas une source muette
        await photos.get(photo_ref(page))
    assert "pas une image" in str(caught.value)
    with pytest.raises(MapsUnavailable) as caught:
        await photos.get(photo_ref(big))
    assert "dépasse" in str(caught.value)
    assert photos.size() == (0, 0) and photos.failed == 2


async def test_a_cache_that_does_not_write_is_said_in_words_not_a_crash(tmp_path, monkeypatch):
    """R3-02 : la relève d'une photo de Google au nom expiré relit sa fiche, qui s'écrit dans le cache des avis ; une
    erreur de la base (``database is locked``) sortait du relais, et la route répondait 500. C'est une source qui ne
    peut pas servir (``MapsUnavailable``, un 503 en mots) ; de même quand le cache des photos ne s'écrit pas."""
    async def locked() -> str:
        raise sqlite3.OperationalError("database is locked")

    ref = "p:" + "a" * 32
    photos = PhotoRelay(tmp_path / "photos", sources=[Source({ref: PhotoOrigin("", "google", resolve=locked)})],
                        today=lambda: TODAY, transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with pytest.raises(MapsUnavailable) as caught:
        await photos.get(ref)
    assert "ne s'écrit pas" in str(caught.value) and photos.failed == 1
    url = "https://media.exemple.fr/plein.jpg"
    full, _host = relay(tmp_path, {url: (httpx.Response(200, content=JPEG), "")})

    def no_room(path, data):  # noqa: ANN001, ANN202
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(full, "_keep", no_room)
    with pytest.raises(MapsUnavailable) as caught:
        await full.get(photo_ref(url))
    assert "ne s'écrit pas" in str(caught.value)


async def test_a_photo_whose_rights_have_ended_is_no_longer_served(tmp_path):
    url = "https://media.exemple.fr/fin.jpg"
    photos, host = relay(tmp_path, {url: (httpx.Response(200, content=JPEG), "2026-12-31")})
    await photos.get(photo_ref(url))
    assert photos.size()[0] == 1
    photos.sources[0].known[photo_ref(url)] = PhotoOrigin(url, "datatourisme", "2026-11-17")
    with pytest.raises(MapsUnavailable) as caught:
        await photos.get(photo_ref(url))
    assert "droits" in str(caught.value) and photos.size() == (0, 0)
    assert host.asked == [url]


async def test_the_cache_stays_under_its_bound_the_least_recently_served_leaving_first(tmp_path):
    urls = {f"https://media.exemple.fr/{k}.png": (httpx.Response(200, content=PNG), "") for k in range(5)}
    photos, _host = relay(tmp_path, urls, cache_max=3 * len(PNG))
    for k, url in enumerate(urls):
        await photos.get(photo_ref(url))
        os.utime(photos.folder / photo_ref(url)[2:], (1_000_000 + k, 1_000_000 + k))  # servies l'une après l'autre
    count, size = photos.size()
    assert count <= 3 and size <= 3 * len(PNG)
    assert (photos.folder / photo_ref("https://media.exemple.fr/4.png")[2:]).exists()
    assert not (photos.folder / photo_ref("https://media.exemple.fr/0.png")[2:]).exists()


async def test_redirects_are_followed_only_to_public_hosts(tmp_path):
    public, private = "https://media.exemple.fr/r1.jpg", "https://media.exemple.fr/r2.jpg"
    photos, host = relay(tmp_path, {
        public: (httpx.Response(302, headers={"location": "https://cdn.exemple.fr/vraie.webp"}), ""),
        private: (httpx.Response(302, headers={"location": "http://192.168.1.22:8001/api"}), "")})
    host.served["https://cdn.exemple.fr/vraie.webp"] = httpx.Response(200, content=WEBP)
    assert await photos.get(photo_ref(public)) == (WEBP, "image/webp")
    with pytest.raises(MapsUnavailable) as caught:
        await photos.get(photo_ref(private))
    assert "qu'on ne joint pas" in str(caught.value) and "http://192.168.1.22:8001/api" not in host.asked


@pytest.mark.parametrize(("url", "ok"), [
    ("https://aisne.media.tourinsoft.eu/upload/a.jpg", True), ("http://93.184.216.34/a.jpg", True),
    ("http://127.0.0.1/a.jpg", False), ("http://localhost:8001/x", False), ("http://10.0.0.2/x", False),
    ("http://[::1]/x", False), ("http://169.254.169.254/latest", False), ("file:///etc/passwd", False),
    ("http://user:pass@exemple.fr/x", False), ("http://serveur/x", False), ("http://nas.local/x", False),
])
def test_only_public_addresses_are_joined(url, ok):
    assert public_url(url) is ok


@pytest.mark.parametrize("url", [
    # cette machine sous ses formes héritées, que le système lit comme une adresse (``inet_aton``)
    "http://127.1/a.jpg", "http://0177.0.0.1/a.jpg", "http://127.0.1/a.jpg", "http://0x7f.1/a.jpg",
    "http://0x7f.0x0.0x0.0x1/a.jpg", "http://2130706433/a.jpg", "http://0x7f000001/a.jpg", "http://017700000001/a",
    # cachée dans une IPv6 (mappée, compatible, 6to4, NAT64)
    "http://[::ffff:127.0.0.1]/a.jpg", "http://[::ffff:7f00:1]/a.jpg", "http://[::127.0.0.1]/a.jpg",
    "http://[2002:7f00:1::1]/a.jpg", "http://[64:ff9b::7f00:1]/a.jpg", "http://[::ffff:192.168.1.22]/a.jpg",
    # multidiffusion, réservée, partagée, locale au lien ou au site, non spécifiée
    "http://224.0.0.1/a.jpg", "http://239.255.255.250/a", "http://[ff02::1]/a.jpg", "http://240.0.0.1/a.jpg",
    "http://255.255.255.255/a", "http://0.0.0.0/a", "http://[::]/a", "http://100.64.0.1/a", "http://198.18.0.1/a",
    "http://[fe80::1]/a", "http://[fec0::1]/a", "http://[fc00::1]/a", "http://192.0.0.8/a",
])
def test_disguised_spellings_of_this_machine_or_the_local_network_are_refused(url):
    assert public_url(url) is False


@pytest.mark.parametrize(("address", "ok"), [
    ("93.184.216.34", True), ("2606:2800:220:1:248:1893:25c8:1946", True), ("::ffff:93.184.216.34", True),
    ("127.0.0.1", False), ("192.168.1.22", False), ("10.1.2.3", False), ("172.16.0.1", False), ("::1", False),
    ("fe80::1%eth0", False), ("224.0.0.251", False), ("ff05::2", False), ("::ffff:127.0.0.1", False),
    ("2002:c0a8:116::1", False), ("pas une adresse", False), ("", False),
])
def test_a_resolved_address_is_joined_only_if_public(address, ok):
    assert joinable(address) is ok


class Resolver:
    """Le DNS joué : les adresses de chaque nom, et ce qu'on lui a demandé (jamais le vrai DNS)."""

    def __init__(self, table: dict[str, list[str]]) -> None:
        self.table = table
        self.asked: list[str] = []

    def __call__(self, host: str, port: int) -> list[str]:
        self.asked.append(host)
        if host not in self.table:
            raise socket.gaierror(socket.EAI_NONAME, "inconnu")
        return self.table[host]


class Wire(httpcore.AsyncMockStream):
    """Une connexion jouée : ce qu'elle rend, et ce qu'on y a écrit."""

    def __init__(self, buffer: list[bytes], written: list[bytes]) -> None:
        super().__init__(buffer)
        self.written = written

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self.written.append(buffer)


class Network(httpcore.AsyncNetworkBackend):
    """Le réseau joué, sous le vrai transport : à quelle adresse on s'est connecté, ce que rend chacune."""

    def __init__(self, served: dict[str, bytes]) -> None:
        self.served = served
        self.joined: list[tuple[str, int]] = []
        self.written: list[bytes] = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):  # noqa: ANN001, ANN201
        self.joined.append((host, port))
        return Wire([self.served[host]], self.written)

    async def sleep(self, seconds: float) -> None:
        return None


def answer(status: str, body: bytes = b"", **headers: str) -> bytes:
    head = "".join(f"{k.replace('_', '-')}: {v}\r\n" for k, v in headers.items())
    return f"HTTP/1.1 {status}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n{head}\r\n".encode() + body


def guarded_relay(tmp_path: Path, urls: list[str], resolve: Resolver, network: Network) -> PhotoRelay:
    source = Source({photo_ref(url): PhotoOrigin(url, "datatourisme") for url in urls})
    clock = tf.Clock()
    return PhotoRelay(tmp_path / "cartes" / "photos", sources=[source], today=lambda: TODAY,
                      transport=guarded_transport(resolve, network),
                      pace=Pace(1000.0, now=clock.stamp, sleep=clock.sleep))


async def test_the_check_is_on_the_address_resolved_when_connecting(tmp_path):
    """Un nom qui se résout dans le réseau local (ou dont une seule des adresses l'est) n'est jamais joint ; un nom
    public l'est à l'adresse vérifiée, sous son nom (``Host``)."""
    local, mixed, public = ("http://media.exemple.fr/a.jpg", "http://mixte.exemple.fr/b.jpg",
                            "http://cdn.exemple.fr/c.jpg")
    resolve = Resolver({"media.exemple.fr": ["192.168.1.22"], "mixte.exemple.fr": ["93.184.216.34", "127.0.0.1"],
                        "cdn.exemple.fr": ["93.184.216.34"]})
    network = Network({"93.184.216.34": answer("200 OK", JPEG, content_type="image/jpeg")})
    photos = guarded_relay(tmp_path, [local, mixed, public], resolve, network)
    for url in (local, mixed):
        with pytest.raises(MapsUnavailable) as caught:
            await photos.get(photo_ref(url))
        assert "qu'on ne joint pas" in str(caught.value)
    assert network.joined == []
    assert await photos.get(photo_ref(public)) == (JPEG, "image/jpeg")
    assert network.joined == [("93.184.216.34", 80)]
    assert b"Host: cdn.exemple.fr" in b"".join(network.written)
    assert resolve.asked == ["media.exemple.fr", "mixte.exemple.fr", "cdn.exemple.fr"]


async def test_every_redirect_hop_is_checked_on_its_resolved_address(tmp_path):
    """Un hôte public qui renvoie vers une forme déguisée de cette machine (« 127.1 ») ou vers un nom qui se résout
    chez elle : refusé, rien ne part vers elle."""
    first, second = "http://media.exemple.fr/a.jpg", "http://vieux.exemple.fr/b.jpg"
    resolve = Resolver({"media.exemple.fr": ["93.184.216.34"], "vieux.exemple.fr": ["93.184.216.35"],
                        "rebond.exemple.fr": ["127.0.0.1"]})
    network = Network({"93.184.216.34": answer("302 Found", location="http://127.1:8001/api"),
                       "93.184.216.35": answer("302 Found", location="http://rebond.exemple.fr/api")})
    photos = guarded_relay(tmp_path, [first, second], resolve, network)
    for url in (first, second):
        with pytest.raises(MapsUnavailable) as caught:
            await photos.get(photo_ref(url))
        assert "qu'on ne joint pas" in str(caught.value)
    assert network.joined == [("93.184.216.34", 80), ("93.184.216.35", 80)]
    assert "127.1" not in resolve.asked and resolve.asked[-1] == "rebond.exemple.fr"


async def test_the_relay_resolves_through_its_guard_by_default(tmp_path):
    """Sans transport donné (le serveur), le relais passe par la garde : un nom résolu chez soi ne part pas — et un
    nom que le DNS ne connaît pas se dit en mots."""
    url, unknown = "https://media.exemple.fr/a.jpg", "https://inconnu.exemple.fr/a.jpg"
    resolve = Resolver({"media.exemple.fr": ["10.0.0.7"]})
    source = Source({photo_ref(u): PhotoOrigin(u, "datatourisme") for u in (url, unknown)})
    clock = tf.Clock()
    photos = PhotoRelay(tmp_path / "photos", sources=[source], today=lambda: TODAY, resolve=resolve,
                        pace=Pace(1000.0, now=clock.stamp, sleep=clock.sleep))
    try:
        with pytest.raises(MapsUnavailable) as caught:
            await photos.get(photo_ref(url))
        assert "qu'on ne joint pas" in str(caught.value)
        with pytest.raises(MapsUnavailable) as caught:
            await photos.get(photo_ref(unknown))
        assert "ne répond pas" in str(caught.value)
    finally:
        await photos.close()
    assert resolve.asked == ["media.exemple.fr", "inconnu.exemple.fr"]


def test_an_image_is_known_by_its_first_bytes():
    assert media_of(JPEG[:16]) == "image/jpeg" and media_of(PNG[:16]) == "image/png"
    assert media_of(WEBP[:16]) == "image/webp" and media_of(b"GIF89a....") == "image/gif"
    assert media_of(b"<svg xmlns=") == "" and media_of(b"") == ""


async def test_the_desk_relays_the_photos_of_its_tourism_fiches(tmp_path):
    index = tf.write_index(tmp_path / "cartes" / "lieux.db")
    sync, _tourism, clock, _cfg = tf.make_sync(tmp_path, tf.FakeApi({EVENTS: [], PLACES: tf.restaurants()}),
                                               index=index)
    await sync.run()
    host = Host({"https://aisne.media.tourinsoft.eu/upload/resort-barriere-lille--2--3.jpg":
                 httpx.Response(200, content=JPEG)})
    desk = MapsDesk(tmp_path, PlacesConfig, RoutingConfig, clock=clock, transport=httpx.MockTransport(host))
    try:
        [photo] = (await desk.place("w100")).tourism.photos
        assert await desk.photo(photo.ref) == (JPEG, "image/jpeg")
        with pytest.raises(MapsUnavailable):
            await desk.photo(photo_ref("https://ailleurs.exemple/x.jpg"))
        assert host.asked == ["https://aisne.media.tourinsoft.eu/upload/resort-barriere-lille--2--3.jpg"]
    finally:
        await desk.close()
