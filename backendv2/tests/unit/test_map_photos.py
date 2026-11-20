"""Les photos relayées (ADR 0245) : une référence ``p:<hash>`` ne mène qu'à une adresse venue des données (jamais à
une adresse donnée par un client), relevée une fois puis gardée sous ``cartes/photos`` (borné : les moins récemment
servies partent) ; ce qui n'est pas une image, ce qui est trop gros, une adresse du réseau local, une photo dont les
droits ont pris fin : refusés, en mots."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import httpx
import pytest

from mika.adapters.maps.config import PlacesConfig, RoutingConfig
from mika.adapters.maps.datatourisme import EVENTS, PLACES
from mika.adapters.maps.desk import MapsDesk
from mika.adapters.maps.pace import Pace
from mika.adapters.maps.photos import PhotoOrigin, PhotoRelay, media_of, photo_ref, public_url
from mika.ports.maps import MapsUnavailable
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
    with pytest.raises(MapsUnavailable) as caught:
        await photos.get(photo_ref(page))
    assert "pas une image" in str(caught.value)
    with pytest.raises(MapsUnavailable) as caught:
        await photos.get(photo_ref(big))
    assert "dépasse" in str(caught.value)
    assert photos.size() == (0, 0) and photos.failed == 2


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
