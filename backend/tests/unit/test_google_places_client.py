"""Le client de l'API Places (New) de Google (ADR 0256), sur ses réponses réelles (réduites) : le masque de chaque appel
et le SKU qu'il fait facturer (une recherche jamais au niveau « Atmosphere », les avis seulement à la fiche) ; ce qui
part (un cercle, les types premiers, la langue ; la clé dans l'en-tête seul) ; ce qu'on lit d'un lieu, d'un avis, d'une
photo ; les erreurs dites en mots — et la clé jamais recopiée ni journalisée."""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from mika.adapters.maps.config import ReviewsConfig
from mika.adapters.maps.google_places import (
    ATMOSPHERE,
    ATMOSPHERE_FIELDS,
    AUTH,
    BROKEN,
    BUSY,
    DETAILS,
    DETAILS_MASK,
    ENTERPRISE,
    FORBIDDEN,
    MISSING,
    NEARBY,
    NETWORK,
    PHOTO,
    PRIMARY_TYPES,
    REFUSED,
    SEARCH_MASK,
    SERVER,
    SKUS,
    TYPES_MAX,
    PlacesUnavailable,
    attribute_facts,
    google_url,
    price_range,
    read_photos,
    read_place,
    read_review,
    tier,
)
from mika.adapters.maps.quota import QuotaExceeded
from tests.fixtures import google_places as gp

#: des types de la table A de Google (la page « Place Types (New) », lue le 2026-11-20 : « Food and Drink »,
#: « Lodging », « Culture », « Entertainment and Recreation », « Places of Worship ») — un type qui n'y est pas fait
#: refuser la recherche entière (400)
TABLE_A = frozenset("""
african_restaurant american_restaurant asian_restaurant bakery bar bar_and_grill belgian_restaurant bistro
breakfast_restaurant brunch_restaurant buffet_restaurant cafe chinese_restaurant coffee_shop family_restaurant
fast_food_restaurant fine_dining_restaurant french_restaurant gastropub greek_restaurant hamburger_restaurant
ice_cream_shop indian_restaurant italian_restaurant japanese_restaurant kebab_shop korean_restaurant
lebanese_restaurant mediterranean_restaurant mexican_restaurant middle_eastern_restaurant moroccan_restaurant
pastry_shop pizza_restaurant portuguese_restaurant pub ramen_restaurant restaurant sandwich_shop seafood_restaurant
spanish_restaurant steak_house sushi_restaurant tapas_restaurant tea_house thai_restaurant turkish_restaurant
vegan_restaurant vegetarian_restaurant vietnamese_restaurant
bed_and_breakfast campground camping_cabin cottage extended_stay_hotel farmstay guest_house hostel hotel inn lodging
motel private_guest_room resort_hotel rv_park
art_gallery art_museum castle cultural_landmark fountain historical_place history_museum monument museum
performing_arts_theater sculpture
amphitheatre amusement_park aquarium botanical_garden city_park concert_hall cultural_center ferris_wheel garden
historical_landmark hiking_area marina national_park observation_deck opera_house park philharmonic_hall planetarium
plaza state_park tourist_attraction visitor_center water_park wildlife_park zoo
buddhist_temple church hindu_temple mosque synagogue
""".split())


def month_used(rig: gp.Rig, sku) -> int:  # noqa: ANN001
    return next(w.used for w in rig.client.skus[sku.service].status().windows if w.name == "mois")


def test_a_search_never_asks_for_an_atmosphere_field_and_reviews_only_come_with_a_fiche():
    searched = {f.removeprefix("places.") for f in SEARCH_MASK.split(",")}
    assert not searched & ATMOSPHERE_FIELDS and all(f.startswith("places.") for f in SEARCH_MASK.split(","))
    assert tier(SEARCH_MASK) == ENTERPRISE and {"rating", "userRatingCount", "priceLevel", "photos",
                                                "regularOpeningHours"} <= searched
    assert tier(DETAILS_MASK) == ATMOSPHERE and {"reviews", "editorialSummary", "servesVegetarianFood",
                                                 "outdoorSeating", "priceRange"} <= set(DETAILS_MASK.split(","))
    assert " " not in SEARCH_MASK and " " not in DETAILS_MASK  # Google refuse un blanc dans le masque
    assert [(s.name, s.free, s.price) for s in SKUS] == [
        ("Nearby Search Enterprise", 1000, 35.0), ("Place Details Enterprise + Atmosphere", 1000, 25.0),
        ("Place Details Photos", 1000, 7.0)]
    assert NEARBY.billed(1000) == 0 and NEARBY.billed(1200) == pytest.approx(7.0)


def test_each_sort_lists_at_most_fifty_primary_types_and_none_twice():
    for sort, types in PRIMARY_TYPES.items():
        assert 0 < len(types) <= TYPES_MAX and len(set(types)) == len(types), sort
        assert set(types) <= TABLE_A, set(types) - TABLE_A
    assert {"restaurant", "pastry_shop", "italian_restaurant"} <= set(PRIMARY_TYPES["manger"])
    assert "shopping_mall" not in {t for types in PRIMARY_TYPES.values() for t in types}


async def test_a_search_sends_a_circle_primary_types_and_the_key_in_a_header_only(tmp_path):
    rig = gp.rig(tmp_path)
    found = await rig.client.nearby(50.6377, 3.0612, 707.1, "manger", background=True)
    [asked] = rig.api.requests
    body = json.loads(asked.content)
    assert asked.method == "POST" and str(asked.url) == "https://places.googleapis.com/v1/places:searchNearby"
    assert body["includedPrimaryTypes"] == list(PRIMARY_TYPES["manger"]) and "includedTypes" not in body
    assert (body["maxResultCount"], body["rankPreference"], body["languageCode"]) == (20, "POPULARITY", "fr")
    assert body["locationRestriction"] == {"circle": {"center": {"latitude": 50.6377, "longitude": 3.0612},
                                                      "radius": 707.1}}
    assert asked.headers["x-goog-api-key"] == gp.KEY and gp.KEY not in str(asked.url) and gp.KEY not in body.__repr__()
    assert asked.headers["x-goog-fieldmask"] == SEARCH_MASK
    # le centre commercial typé aussi « restaurant » ne remonte pas : son type premier est « shopping_mall »
    assert [p["id"] for p in found] == [gp.BELLEZZA, gp.MEERT]
    assert month_used(rig, NEARBY) == 1 and month_used(rig, DETAILS) == month_used(rig, PHOTO) == 0


async def test_a_fiche_asks_its_atmosphere_mask_and_a_photo_its_media_each_on_its_own_sku(tmp_path):
    rig = gp.rig(tmp_path)
    fiche = await rig.client.details(gp.BELLEZZA)
    uri = await rig.client.photo_uri(fiche["photos"][0]["name"])
    [details, media] = rig.api.requests
    assert details.method == "GET" and details.url.path == f"/v1/places/{gp.BELLEZZA}"
    assert dict(details.url.params) == {"languageCode": "fr"} and details.headers["x-goog-fieldmask"] == DETAILS_MASK
    assert dict(media.url.params) == {"maxWidthPx": "800", "skipHttpRedirect": "true"}
    assert media.url.path.endswith("/photos/AV-photo-fictive-01/media") and "x-goog-fieldmask" not in media.headers
    assert uri.startswith("https://lh3.googleusercontent.com/")
    assert (month_used(rig, NEARBY), month_used(rig, DETAILS), month_used(rig, PHOTO)) == (0, 1, 1)


def test_a_place_reads_what_a_list_shows_and_a_fiche_what_it_adds():
    [_mall, meert, bellezza] = [read_place(p, "manger") for p in gp.nearby()]
    assert (bellezza.id, bellezza.name, bellezza.kind, bellezza.sort) == (gp.BELLEZZA, "La Bellezza Lille",
                                                                         "italian_restaurant", "manger")
    assert (bellezza.rating, bellezza.count, bellezza.price) == (4.8, 29867, "€€")
    assert meert.price == "" and meert.kind == "pastry_shop" and bellezza.status == "OPERATIONAL"
    assert bellezza.url.startswith("https://maps.google.com/?cid=") and "Lille" in bellezza.address
    assert bellezza.hours[0] == "lundi: 11:45 – 14:30, 18:15 – 22:30"
    assert [p.author for p in bellezza.photos] == ["Photographe fictif 15", "Photographe fictif 16"]
    assert bellezza.photos[0].author_url.startswith("https://maps.google.com/maps/contrib/")
    assert not bellezza.detailed and bellezza.reviews == ()
    fiche = read_place(gp.details(), "manger", detailed=True)
    assert fiche.detailed and fiche.price_range == "20–40 €" and fiche.summary.startswith("Spécialités italiennes")
    assert dict(fiche.attributes) == {"outdoorSeating": False, "servesVegetarianFood": True}
    assert dict(attribute_facts(fiche.attributes)) == {"Terrasse": "non (selon Google)",
                                                       "Végétarien": "oui (selon Google)"}
    assert len(fiche.reviews) == 3 and len(fiche.photos) == 3


def test_a_review_reads_its_author_and_when_and_a_place_without_identity_is_left():
    first = read_review(gp.details()["reviews"][0])
    assert (first.rating, first.author, first.date, first.relative, first.language, first.title) == (
        5.0, "Autrice fictive 1", "2026-11-15", "il y a moins d'une semaine", "fr", "")
    assert first.author_url == "https://www.google.com/maps/contrib/100000000000000000001/reviews"
    assert first.text.startswith("Cadre magnifique\nVue sur les cuisines")
    assert read_review({"text": {"text": "sans note"}}) is None
    assert read_place({"id": "ChIJsansnom0", "location": {"latitude": 1, "longitude": 2}}) is None
    assert read_place("nimporte") is None
    raw = gp.details()
    raw["googleMapsUri"] = "https://evil.example.org/maps"
    raw["photos"][0]["name"] = "../../etc/passwd"
    seen = read_place(raw, detailed=True)
    assert seen.url == "" and len(seen.photos) == 2
    assert google_url("http://maps.google.com/x") == "" and google_url("https://www.google.com/maps/contrib/1")
    assert price_range({"startPrice": {"currencyCode": "EUR", "units": "100"}}) == "100 € et plus"
    assert price_range({"startPrice": {"units": "10"}}) == "" and read_photos("rien") == ()


@pytest.mark.parametrize(("status", "kind", "said"), [
    (400, REFUSED, "Google refuse la demande (HTTP 400 : refus 400 …)"),
    (401, AUTH, "Google refuse la clé (HTTP 401"),
    (403, FORBIDDEN, "l'API Places (New) n'est pas activée sur ce projet"),
    (404, MISSING, "Google ne connaît pas (ou plus) ce lieu ou cette photo (HTTP 404"),
    (503, SERVER, "Google est en panne (HTTP 503)"),
    ("broken", BROKEN, "Google a rendu une réponse illisible"),
])
async def test_errors_are_said_in_words_and_never_repeat_the_key(tmp_path, caplog, status, kind, said):
    caplog.set_level(logging.DEBUG)
    rig = gp.rig(tmp_path, gp.FakeGoogle(statuses=[status]))
    with pytest.raises(PlacesUnavailable) as caught:
        await rig.client.details(gp.BELLEZZA)
    assert caught.value.kind == kind and said in str(caught.value)
    assert gp.KEY not in str(caught.value) and gp.KEY not in caplog.text and gp.KEY not in rig.client.last_error
    # un appel compte au mois dès qu'il part, même en erreur : le compteur ne sous-estime jamais la facture
    assert month_used(rig, DETAILS) == 1


async def test_a_wrong_key_is_said_as_such(tmp_path):
    rig = gp.rig(tmp_path, cfg=ReviewsConfig(api_key="une-autre-cle-fausse"))
    with pytest.raises(PlacesUnavailable) as caught:
        await rig.client.nearby(*gp.GRAND_PLACE, 500, "voir")
    assert caught.value.kind == AUTH and "Google refuse la clé (HTTP 400 : API key not valid" in str(caught.value)


async def test_a_429_holds_back_that_sku_for_the_time_said(tmp_path):
    rig = gp.rig(tmp_path, gp.FakeGoogle(statuses=[429], headers={"Retry-After": "120"}))
    with pytest.raises(PlacesUnavailable) as caught:
        await rig.client.nearby(*gp.GRAND_PLACE, 500, "manger", background=True)
    assert caught.value.kind == BUSY
    with pytest.raises(QuotaExceeded) as held:
        await rig.client.nearby(*gp.GRAND_PLACE, 500, "manger", background=True)
    assert "Google (recherches à proximité) a demandé d'attendre" in str(held.value)
    await rig.client.details(gp.BELLEZZA)  # une recherche a reculé : la fiche part
    rig.clock.advance(seconds=121)
    await rig.client.nearby(*gp.GRAND_PLACE, 500, "manger", background=True)


async def test_no_key_means_nothing_leaves(tmp_path):
    rig = gp.rig(tmp_path, cfg=ReviewsConfig())
    with pytest.raises(PlacesUnavailable) as caught:
        await rig.client.photo_uri(f"places/{gp.BELLEZZA}/photos/AV-photo-fictive-01")
    assert caught.value.kind == AUTH and rig.api.requests == [] and not rig.client.ready()
    assert month_used(rig, PHOTO) == 0


async def test_a_server_that_does_not_answer_is_said(tmp_path):
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé", request=request)

    rig = gp.rig(tmp_path)
    rig.client._transport = httpx.MockTransport(down)
    with pytest.raises(PlacesUnavailable) as caught:
        await rig.client.details(gp.BELLEZZA)
    assert caught.value.kind == NETWORK and "ne répond pas (ConnectError)" in str(caught.value)


async def test_a_photo_address_elsewhere_than_google_is_refused(tmp_path):
    def elsewhere(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"photoUri": "https://evil.example.org/photo.jpg"})

    rig = gp.rig(tmp_path)
    rig.client._transport = httpx.MockTransport(elsewhere)
    with pytest.raises(PlacesUnavailable) as caught:
        await rig.client.photo_uri(f"places/{gp.BELLEZZA}/photos/AV-photo-fictive-01")
    assert caught.value.kind == BROKEN
    with pytest.raises(ValueError):
        await rig.client.photo_uri("https://evil.example.org/x")
