"""Les avis dans l'écran Carte (ADR 0256), à travers le vrai ``MapsDesk`` : une liste (``search``, ``around``) ne lit que
le cache — elle n'appelle jamais Google — et chaque lieu rapproché y porte sa note, le nombre de ses avis, son prix et
sa photo ; ``min_rating`` écarte les lieux sans note, ``sort="rating"`` met les mieux notés d'abord, et ceux du cache un
peu plus loin rejoignent les plus proches. La fiche d'un lieu (``place``) lit en direct ce qui lui manque — le lieu
cherché tout près de lui, puis sa fiche avec ses avis —, une fois par durée du cache ; quand le quota manque, elle
montre ce qu'elle avait en le disant ; « Actualiser » (``place_refresh``) relit tout. Ce que Google dit de la fiche
complète ce qu'OpenStreetMap ne dit pas, jamais à sa place. Les photos passent par ce serveur, depuis les hôtes des
images de Google seulement, et un nom de photo expiré fait relire la fiche."""

from __future__ import annotations

import sqlite3

import pytest

from mika.adapters.maps.cells import cell_of
from mika.adapters.maps.config import ReviewsConfig
from mika.adapters.maps.photos import photo_ref
from mika.ports.maps import MapsUnavailable
from tests.fixtures import google_places as gp

LILLE = gp.GRAND_PLACE
MEERT_AT, BELLEZZA_AT = (50.6377202, 3.0619917), (50.6389756, 3.058805)


async def loaded(tmp_path, api=None, **kw):  # noqa: ANN001, ANN201
    """Le vrai guichet, les cases de Méert et de La Bellezza lues (leurs restaurants) ; puis plus rien de ce qui sort
    n'est compté."""
    maps, outside, clock, config = gp.desk(tmp_path, api, **kw)
    for at in (MEERT_AT, BELLEZZA_AT):
        await maps.review_cells.load(cell_of(*at, 3), "manger", background=True)
    outside.seen.clear()
    outside.api.requests.clear()
    return maps, outside, clock, config


async def test_a_list_reads_the_cache_and_never_calls_google(tmp_path):
    maps, outside, _clock, _config = await loaded(tmp_path)
    noted = {h.osm: h for h in await maps.around(*LILLE, 900)}
    bellezza = noted["n301"]
    assert (bellezza.rating, bellezza.reviews, bellezza.price) == (4.8, 29867, "€€")
    assert bellezza.photo.startswith("p:") and noted["n302"].rating == 4.3 and noted["n302"].price == ""
    assert noted["n304"].rating is None and noted["w303"].rating is None  # La Chicorée ; le centre commercial
    await maps.search("", near=LILLE, category="manger", sort="rating")
    await maps.search("Bellezza", near=LILLE, min_rating=2)
    await maps.search("", bbox=(3.05, 50.63, 3.07, 50.64), min_rating=3)
    assert outside.seen == []  # rien n'est sorti


async def test_a_google_place_without_twin_never_shows_as_a_place_of_its_own(tmp_path):
    api = gp.FakeGoogle(places=[*gp.nearby(), gp.place("ChIJfantome01", "Le Bistrot Fantôme", 50.6372, 3.0634,
                                                       rating=4.9, count=90_000)])
    maps, _outside, _clock, _config = await loaded(tmp_path, api)
    names = [h.name for h in await maps.around(*LILLE, 600, sort="rating", limit=50)]
    assert "Le Bistrot Fantôme" not in names and len(names) == len(set(names))
    assert names.count("La Bellezza") == 1


async def test_min_rating_drops_places_without_a_rating_and_sort_by_rating_ranks(tmp_path):
    maps, _outside, _clock, _config = await loaded(tmp_path)
    ranked = await maps.around(*LILLE, 600, category="manger", sort="rating")
    assert [h.osm for h in ranked] == ["n301", "n304"]  # 4,8 ; sans note à la fin
    assert [h.osm for h in await maps.around(*LILLE, 600, min_rating=4.5)] == ["n301"]
    assert [h.osm for h in await maps.around(*LILLE, 600, min_rating=4)] == ["n302", "n301"]  # la distance
    with pytest.raises(ValueError):
        await maps.around(*LILLE, 300, sort="avis")
    with pytest.raises(ValueError):
        await maps.search("", near=LILLE, min_rating=6)


async def test_the_best_rated_a_little_further_join_the_nearest(tmp_path):
    far = gp.place("ChIJlointain1", "Le Bistrot Lointain", 50.6400, 3.0700, rating=4.9, count=900)  # à ~600 m
    # soixante restaurants plus près, sans note : l'index ne rend que les cinquante plus proches
    crowd = tuple((f"n{400 + k}", f"Restaurant voisin {k}", "restaurant", "manger", 50.6372 + k * 1e-5, 3.0633)
                  for k in range(60))
    places = (*gp.GRAND_PLACE_PLACES, *crowd,
              ("n307", "Le Bistrot Lointain", "restaurant", "manger", 50.64002, 3.07003))
    api = gp.FakeGoogle(places=[*gp.nearby(), far])
    maps, _outside, _clock, _config = await loaded(tmp_path, api, places=places)
    await maps.review_cells.load(cell_of(50.6400, 3.0700, 3), "manger", background=True)
    nearest = await maps.places.search("", near=LILLE, category="manger", limit=50)
    assert "n307" not in {h.osm for h in nearest}
    best = await maps.search("", near=LILLE, category="manger", limit=2, sort="rating")
    assert [h.osm for h in best] == ["n307", "n301"] and best[0].rating == 4.9 and best[0].distance_m > 500


async def test_opening_a_place_reads_what_it_lacks_once_per_cache_life(tmp_path):
    api = gp.FakeGoogle()
    maps, outside, clock, _config = gp.desk(tmp_path, api)
    detail = await maps.place("n301")
    facts = detail.reviews
    # pas encore rapprochée : cherchée tout près d'elle (une recherche, par la distance), puis sa fiche avec ses avis
    [probe] = api.bodies()
    assert probe["rankPreference"] == "DISTANCE" and probe["locationRestriction"]["circle"]["radius"] == 100
    assert (api.calls(gp.NEARBY), api.calls(gp.DETAILS), api.calls(gp.MEDIA)) == (1, 1, 0)
    assert facts.id == gp.BELLEZZA and facts.source == "google" and (facts.rating, facts.count) == (4.8, 29867)
    assert (facts.price, facts.price_range) == ("€€", "20–40 €") and facts.summary.startswith("Spécialités")
    assert [r.author for r in facts.reviews] == ["Autrice fictive 1", "Autrice fictive 2", "Autrice fictive 3"]
    assert facts.reviews[0].relative == "il y a moins d'une semaine" and facts.reviews[0].author_url
    assert facts.photos[0].source == "google" and facts.photos[0].credit == "Photographe fictif 17"
    assert facts.photos[0].credit_url.startswith("https://maps.google.com/maps/contrib/") and len(facts.photos) == 3
    assert facts.url.startswith("https://maps.google.com/?cid=") and facts.cached and not facts.note
    assert facts.distribution == () and facts.subratings == ()  # Google n'en donne pas
    assert (detail.hit.rating, detail.hit.reviews, detail.hit.photo) == (4.8, 29867, facts.photos[0].ref)
    count = len(api.requests)
    await maps.place("n301")
    assert len(api.requests) == count  # fraîche : rien ne repart
    clock.advance(days=7, minutes=1)
    await maps.place("n301")
    assert [gp._kind(r) for r in api.requests[count:]] == [gp.DETAILS]  # vieille : sa fiche seule
    assert set(outside.hosts()) == {gp.HOST}


async def test_a_place_google_does_not_have_is_said_and_not_looked_for_again(tmp_path):
    api = gp.FakeGoogle()
    maps, _outside, clock, _config = gp.desk(tmp_path, api)
    facts = (await maps.place("n304")).reviews  # La Chicorée
    assert facts.id == "" and "Rien trouvé sur Google sous ce nom à moins de 100 m" in facts.note
    assert "le 18 novembre" in facts.note and len(api.requests) == 1
    await maps.place("n304")
    assert len(api.requests) == 1  # gardé sept jours
    clock.advance(days=8)
    await maps.place("n304")
    assert len(api.requests) == 2


async def test_a_place_whose_reviews_we_do_not_read_asks_nothing(tmp_path):
    api = gp.FakeGoogle()
    maps, _outside, _clock, _config = gp.desk(tmp_path, api)
    assert (await maps.place("w305")).reviews is None  # une pharmacie
    assert (await maps.place("w303")).reviews is None  # un centre commercial
    assert api.requests == []
    assert (await maps.place("n302")).reviews.id == gp.MEERT  # une pâtisserie : elle se mange
    assert gp._kind(api.requests[0]) == gp.NEARBY


async def test_without_a_key_the_place_shows_what_the_cache_has_and_nothing_leaves(tmp_path):
    maps, outside, _clock, config = await loaded(tmp_path)
    config[0] = ReviewsConfig()
    assert (await maps.place("n301")).reviews.rating == 4.8
    assert (await maps.place("n304")).reviews is None
    assert outside.seen == []


async def test_a_quota_reached_shows_what_was_there_and_says_why(tmp_path):
    maps, outside, _clock, config = await loaded(tmp_path)
    config[0] = ReviewsConfig(api_key=gp.KEY, details_per_month=0, searches_per_month=2, reserve_pct=0)
    facts = (await maps.place("n301")).reviews
    assert facts.rating == 4.8 and facts.reviews == () and len(facts.photos) == 2  # ceux de la liste
    assert "le quota du mois de Google (fiches avec avis) est atteint : il revient le 1er décembre." in facts.note
    assert "On montre ce qu'on avait." in facts.note
    probe = (await maps.place("n304")).reviews  # les deux recherches du mois sont prises (les deux cases)
    assert probe.id == "" and "Ce lieu n'a pas pu se chercher sur Google" in probe.note
    assert outside.seen == []


async def test_refresh_reads_everything_again_whatever_its_age(tmp_path):
    api = gp.FakeGoogle()
    maps, _outside, _clock, config = gp.desk(tmp_path, api)
    await maps.place("n301")
    count = len(api.requests)
    detail = await maps.place_refresh("n301")
    assert [gp._kind(r) for r in api.requests[count:]] == [gp.DETAILS]
    assert detail.reviews.id == gp.BELLEZZA and detail.osm is not None
    await maps.place("n304")
    count = len(api.requests)
    await maps.place_refresh("n304")  # « rien trouvé », recherché tout de suite
    assert [gp._kind(r) for r in api.requests[count:]] == [gp.NEARBY]
    assert await maps.place_refresh("n999") is None
    config[0] = ReviewsConfig(api_key=gp.KEY, details_per_month=0)
    with pytest.raises(MapsUnavailable) as caught:
        await maps.place_refresh("n301")
    assert "le quota du mois de Google (fiches avec avis) est atteint" in str(caught.value)


async def test_google_completes_the_fiche_where_osm_is_silent_and_never_replaces_it(tmp_path):
    maps, _outside, _clock, _config = gp.desk(tmp_path)
    db = sqlite3.connect(tmp_path / "cartes" / "lieux.db")
    db.execute("UPDATE place SET tags = ? WHERE osm = 'n301'", ('{"outdoor_seating": "yes"}',))
    db.commit()
    db.close()
    detail = await maps.place("n301")
    assert ("Terrasse", "oui") in detail.osm.facts  # OpenStreetMap le dit : Google (« non ») ne le remplace pas
    said = dict(detail.reviews.facts)
    assert "Terrasse" not in said and said["Végétarien"] == "oui (selon Google)"
    assert said["Horaires"].startswith("lundi: 11:45 – 14:30") and said["Horaires"].endswith("(selon Google)")


async def test_photos_are_relayed_from_the_image_hosts_of_google_only(tmp_path):
    api = gp.FakeGoogle()
    maps, outside, _clock, _config = gp.desk(tmp_path, api)
    facts = (await maps.place("n301")).reviews
    outside.seen.clear()
    data, media = await maps.photo(facts.photos[0].ref)
    assert media == "image/jpeg" and data == gp.JPEG
    assert [r.url.host for r in outside.seen] == [gp.HOST, "lh3.googleusercontent.com"]
    assert outside.seen[0].url.path.endswith("/media") and "x-goog-api-key" not in outside.seen[1].headers
    await maps.photo(facts.photos[0].ref)
    assert len(outside.seen) == 2  # gardée : plus rien ne part, plus rien ne se compte
    with pytest.raises(MapsUnavailable):
        await maps.photo(photo_ref("https://lh3.googleusercontent.com/inconnue"))


async def test_an_expired_photo_name_reads_the_fiche_again_and_keeps_its_reference(tmp_path):
    api = gp.FakeGoogle()
    maps, _outside, _clock, _config = gp.desk(tmp_path, api)
    facts = (await maps.place("n301")).reviews
    api.rotate()  # Google a changé le nom de ses photos
    api.requests.clear()
    data, _media = await maps.photo(facts.photos[1].ref)
    assert data == gp.JPEG
    assert [gp._kind(r) for r in api.requests] == [gp.MEDIA, gp.DETAILS, gp.MEDIA]
    assert api.requests[-1].url.path.endswith("AV-photo-fictive-02v2/media")
    again = (await maps.place("n301")).reviews
    assert [p.ref for p in again.photos] == [p.ref for p in facts.photos]  # les mêmes références


async def test_the_coverage_says_when_the_ratings_were_read(tmp_path):
    maps, _outside, _clock, config = await loaded(tmp_path)
    coverage = maps.reviews_coverage(near=MEERT_AT)
    assert coverage.ready and coverage.cells == 1 and coverage.loaded == 0 and coverage.oldest
    assert "pas encore toutes lues" in coverage.note
    config[0] = ReviewsConfig()
    assert "aucune clé Google" in maps.reviews_coverage(near=LILLE).note
