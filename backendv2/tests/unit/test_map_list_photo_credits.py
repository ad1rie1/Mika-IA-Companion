"""Une vignette dans une liste se montre avec ce qu'il faut citer (ADR 0269, relecture des clients) : un lieu d'une
liste qui porte sa première photo (``PlaceHit.photo``) porte aussi d'où elle vient, son auteur et son lien — Google les
demande avec chaque photo —, la ligne de sa fiche de même ; un événement qui porte la sienne (une photo de l'office de
tourisme) porte son auteur et sa licence. Rien de tout cela ne sort : une liste ne lit que les caches."""

from __future__ import annotations

import copy

from mika.adapters.maps.cells import cell_of
from mika.adapters.maps.config import PlacesConfig, RoutingConfig, TourismConfig
from mika.adapters.maps.datatourisme import EVENTS, PLACES
from mika.adapters.maps.desk import MapsDesk
from mika.ports.maps import extras
from tests.fixtures import google_places as gp
from tests.fixtures import tourism as tf

BELLEZZA_AT = (50.6389756, 3.058805)


async def test_a_listed_google_photo_carries_its_author_and_link(tmp_path):
    maps, outside, _clock, _config = gp.desk(tmp_path, gp.FakeGoogle())
    await maps.review_cells.load(cell_of(*BELLEZZA_AT, 3), "manger", background=True)
    outside.seen.clear()
    listed = {h.osm: h for h in await maps.around(*gp.GRAND_PLACE, 900)}["n301"]
    assert listed.photo.startswith("p:") and outside.seen == []  # une liste ne lit que le cache
    row = maps.reviews.photo_row(listed.photo)  # la photo telle que le cache la garde
    assert row is not None and row["author"] and row["author_url"].startswith("https://")
    assert (listed.photo_source, listed.photo_credit, listed.photo_credit_url) == ("google", row["author"],
                                                                                   row["author_url"])
    assert listed.photo_licence == "" and {"photo_source", "photo_credit", "photo_credit_url"} <= set(extras(listed))
    assert "photo_licence" not in extras(listed)  # ce qu'on ne sait pas n'y est pas
    # sa fiche lue, la liste montre sa nouvelle première photo, avec son auteur
    first = (await maps.place("n301")).reviews.photos[0]
    again = {h.osm: h for h in await maps.around(*gp.GRAND_PLACE, 900)}["n301"]
    assert (again.photo, again.photo_credit, again.photo_credit_url) == (first.ref, first.credit, first.credit_url)


async def test_the_line_of_a_fiche_cites_its_first_photo(tmp_path):
    maps, _outside, _clock, _config = gp.desk(tmp_path, gp.FakeGoogle())
    detail = await maps.place("n301")
    first = detail.reviews.photos[0]
    hit = detail.hit
    assert (hit.photo, hit.photo_source, hit.photo_credit, hit.photo_credit_url) == (
        first.ref, "google", first.credit, first.credit_url)


async def test_a_listed_event_photo_carries_its_author_and_licence(tmp_path):
    events = tf.events()
    # une fiche d'événement avec son image, comme DATAtourisme la donne (celle du Resort Barrière, sur Julien Clerc)
    image = next(o for o in tf.restaurants() if o["uuid"] == tf.RESORT)["hasMainRepresentation"]
    for o in events:
        if o["uuid"] == tf.JULIEN_CLERC:
            o["hasMainRepresentation"] = copy.deepcopy(image)
    index = tf.write_index(tmp_path / "cartes" / "lieux.db")
    sync, _tourism, clock, _cfg = tf.make_sync(tmp_path, tf.FakeApi({EVENTS: events, PLACES: tf.restaurants()}),
                                               index=index)
    await sync.run()
    desk = MapsDesk(tmp_path, PlacesConfig, RoutingConfig, tourism=lambda: TourismConfig(), clock=clock)
    try:
        [clerc] = await desk.events(near=(50.6365, 3.0635), radius_m=30_000, text="Julien Clerc")
        detail = await desk.event(clerc.id)
    finally:
        await desk.close()
    [photo] = detail.photos
    assert clerc.photo == photo.ref and photo.credit == "Patrick Messina" and photo.licence == "By-NC-ND 4.0"
    assert (clerc.photo_source, clerc.photo_credit, clerc.photo_licence) == ("datatourisme", "Patrick Messina",
                                                                             "By-NC-ND 4.0")
