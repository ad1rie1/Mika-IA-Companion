"""Les adresses (ADR 0194) : la Géoplateforme de l'IGN, relayée par ce serveur. Seul le texte cherché part — jamais la
position de la personne, ni ses cookies ; rien ne part sans le choix d'un opérateur ; ce qui ne va pas se dit en
mots. La réponse a la forme de celle du vrai service (``data.geopf.fr/geocodage/search``, le 2026-11-05)."""

from __future__ import annotations

import json

import httpx
import pytest

from mika.adapters.maps import geocode as gc
from mika.adapters.maps.config import GEOPLATEFORME, PlacesConfig
from mika.adapters.maps.pace import Pace
from mika.adapters.maps.tiles import USER_AGENT
from mika.ports.maps import MapsUnavailable

#: la forme de la réponse du vrai service, pour « Place de la Concorde Paris »
CONCORDE = {"type": "FeatureCollection", "query": "Place de la Concorde Paris", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [2.321554, 48.867063]},
     "properties": {"label": "Place de la Concorde 75008 Paris", "score": 0.96, "id": "75108_2259",
                    "name": "Place de la Concorde", "postcode": "75008", "citycode": "75108", "city": "Paris",
                    "district": "Paris 8e Arrondissement", "context": "75, Paris, Île-de-France", "type": "street",
                    "importance": 0.56598, "street": "Place de la Concorde", "_type": "address"}},
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [2.322482, 48.865053]},
     "properties": {"label": "Place de la Concorde 75001 Paris", "score": 0.95, "name": "Place de la Concorde",
                    "postcode": "75001", "city": "Paris", "context": "75, Paris, Île-de-France", "type": "street"}},
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": ["abîmé", 48.0]}, "properties": {"label": "x"}},
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [2.0, 48.0]},
     "properties": {"label": "1 Rue de l'Essai 75001 Paris", "type": "housenumber", "city": "Paris"}},
]}


def geocoder(handler, *, addresses: str = GEOPLATEFORME) -> gc.Geocoder:
    return gc.Geocoder(lambda: PlacesConfig(addresses=addresses), transport=httpx.MockTransport(handler),
                       pace=Pace(1000.0))


async def test_only_the_searched_text_leaves():
    seen: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=CONCORDE, headers={"set-cookie": "suivi=1"})

    g = geocoder(serve)
    got = await g.search("  Place de la   Concorde Paris ", limit=3)
    await g.search("Place de la Concorde Paris")
    request = seen[0]
    assert str(request.url).startswith("https://data.geopf.fr/geocodage/search?")
    assert dict(request.url.params) == {"q": "Place de la Concorde Paris", "limit": "3", "index": "address"}
    assert request.headers["user-agent"] == USER_AGENT and "cookie" not in seen[1].headers
    assert not any(k in request.url.params for k in ("lat", "lon"))  # jamais la position de la personne
    assert [h.name for h in got] == ["Place de la Concorde 75008 Paris", "Place de la Concorde 75001 Paris",
                                     "1 Rue de l'Essai 75001 Paris"]  # ce qui ne se lit pas est laissé
    first = got[0]
    assert (first.id, first.kind, first.kind_fr, first.category, first.town) == ("a:0", "address", "Rue", "adresse",
                                                                                 "Paris")
    assert (first.lat, first.lon) == (48.867063, 2.321554)
    assert got[2].kind_fr == "Adresse" and got[2].id == "a:2"
    await g.close()


async def test_nothing_leaves_without_the_operator_choosing_it():
    seen: list[httpx.Request] = []
    g = geocoder(lambda r: seen.append(r) or httpx.Response(200, json=CONCORDE), addresses="aucune")
    assert not g.ready()
    with pytest.raises(MapsUnavailable, match="Réglages › Canaux › Lieux et adresses"):
        await g.search("Place de la Concorde Paris")
    assert seen == []


async def test_a_short_text_asks_nothing_and_a_long_one_is_bounded():
    seen: list[httpx.Request] = []
    g = geocoder(lambda r: seen.append(r) or httpx.Response(200, json={"features": []}))
    assert await g.search("ab") == [] and seen == []
    await g.search("rue " * 100, limit=50)
    assert len(seen[0].url.params["q"]) <= gc.TEXT_MAX and seen[0].url.params["limit"] == str(gc.LIMIT_MAX)
    await g.close()


@pytest.mark.parametrize(("answer", "said"), [
    (httpx.Response(429), "demande d'attendre"),
    (httpx.Response(503), "HTTP 503"),
    (httpx.Response(200, content=b"<html>pas du json"), "illisible"),
    (httpx.Response(200, json={"features": "aucune"}), "illisible"),
    ("coupure", "ne répond pas"),
])
async def test_what_goes_wrong_is_said_in_words(answer, said):
    def serve(request: httpx.Request) -> httpx.Response:
        if answer == "coupure":
            raise httpx.ConnectTimeout("trop long", request=request)
        return answer

    g = geocoder(serve)
    with pytest.raises(MapsUnavailable, match=said):
        await g.search("Place de la Concorde Paris")
    assert g.failed == 1 and said in g.last_error
    await g.close()


def test_its_pace_is_one_for_the_whole_server():
    a = gc.Geocoder(lambda: PlacesConfig(addresses=GEOPLATEFORME))
    b = gc.Geocoder(lambda: PlacesConfig(addresses=GEOPLATEFORME))
    assert a._pace is b._pace is gc._PACE and gc._PACE.rate == gc.PER_SECOND


def test_its_address_is_a_complete_http_one():
    assert PlacesConfig(addresses_url="https://data.geopf.fr/geocodage/").addresses_url == \
        "https://data.geopf.fr/geocodage"  # sans « / » final : on y ajoute le chemin de l'API
    for bad in ("ftp://x.example.test", "pas une adresse", "https://x.example.test/?q=1"):
        with pytest.raises(ValueError):
            PlacesConfig(addresses_url=bad)
    assert PlacesConfig(addresses_url="").addresses_url == "https://data.geopf.fr/geocodage"
    assert json.loads(PlacesConfig().model_dump_json())["addresses"] == "aucune"  # par défaut : rien ne sort
