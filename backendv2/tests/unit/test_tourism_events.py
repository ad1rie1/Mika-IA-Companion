"""Les événements de la base des données touristiques (ADR 0245), par le port ``maps`` : les copies d'un même événement
(une fiche par date) n'en font qu'un, avec toutes leurs dates ; les plus tôt d'abord, puis les plus proches ; les
thèmes, le texte, « gratuit », la période ; le lieu d'un événement est le lieu nommé d'OpenStreetMap où il se tient, ou
son adresse ; sa fiche dit ses dates, ses tarifs, ses contacts, son auteur et sa date. Sur des fiches réelles."""

from __future__ import annotations

from datetime import date

import pytest

from mika.adapters.maps.config import PlacesConfig, RoutingConfig, TourismConfig
from mika.adapters.maps.datatourisme import EVENTS, PLACES
from mika.adapters.maps.desk import MapsDesk
from mika.ports.maps import MapsUnavailable
from tests.fixtures import tourism as tf

LILLE = (50.6365, 3.0635)
LAM = (50.63770, 3.14870)


@pytest.fixture
async def desk(tmp_path):
    index = tf.write_index(tmp_path / "cartes" / "lieux.db")
    sync, _tourism, clock, _cfg = tf.make_sync(tmp_path, tf.FakeApi({EVENTS: tf.events(), PLACES: tf.restaurants()}),
                                               index=index)
    await sync.run()
    got = MapsDesk(tmp_path, PlacesConfig, RoutingConfig, tourism=lambda: TourismConfig(), clock=clock)
    yield got
    await got.close()


async def test_the_copies_of_an_event_are_one_with_all_their_dates(desk):
    hits = await desk.events(near=LAM, radius_m=500, limit=50)
    obsession = [h for h in hits if h.name == "Obsession"]
    assert len(obsession) == 1 and obsession[0].id == f"e:{min(tf.OBSESSION)}"
    detail = await desk.event(obsession[0].id)
    assert detail.merged == 5
    other = await desk.event(f"e:{max(tf.OBSESSION)}")
    assert other.hit.id == obsession[0].id and other.dates == detail.dates
    starts = [d.start[:10] for d in detail.dates]
    assert starts == sorted(starts) and len(starts) == len(set(starts)) > 5
    assert obsession[0].place == "LaM, Villeneuve-d'Ascq" and detail.venue == "LaM" and detail.venue_place == "w103"


async def test_events_come_soonest_first_then_nearest(desk):
    hits = await desk.events(near=LILLE, radius_m=30_000, limit=50)
    assert hits and all(h.id.startswith("e:") and h.when_text for h in hits)
    starts = [h.start[:10] for h in hits]
    assert starts == sorted(starts)
    assert all(h.distance_m is not None and h.distance_m <= 30_000 for h in hits)
    assert len({h.id for h in hits}) == len(hits)


async def test_a_week_of_dates_is_said_by_its_days(desk):
    hits = await desk.events(near=LILLE, radius_m=30_000, limit=50)
    said = {h.name: h.when_text for h in hits}
    assert said["Obsession"] == "du mer. au dim. · 11:00–19:00"  # fermé le lundi : la suite des jours d'abord
    assert said["Ça capte !"] == "mer., sam., dim. · 14:00–18:00"
    [clerc] = await desk.events(near=LILLE, radius_m=30_000, text="Julien Clerc")
    assert clerc.when_text == "dim. 22 nov. · 17:00–19:00"
    assert (clerc.start, clerc.end) == ("2026-11-22T17:00+01:00", "2026-11-22T19:00+01:00")


async def test_themes_text_free_and_the_window_filter(desk):
    concerts = await desk.events(near=LILLE, radius_m=30_000, themes=frozenset({"concerts"}), limit=50)
    assert {h.name for h in concerts} >= {"Quatuor Poulenc", "Julien Clerc", "Les Tout Petits Concerts"}
    assert all("concerts" in h.themes for h in concerts)
    free = await desk.events(near=LILLE, radius_m=30_000, free=True, limit=50)
    assert free and all(h.free is True for h in free)
    assert "Julien Clerc" not in {h.name for h in free}
    found = await desk.events(near=LILLE, radius_m=30_000, text="poulenc")
    assert [h.name for h in found] == ["Quatuor Poulenc"]
    december = await desk.events(near=LILLE, radius_m=30_000, start=date(2026, 12, 5), end=date(2026, 12, 10),
                                 limit=50)
    assert {"Les Tout Petits Concerts", "Mercredi tout est permis"} <= {h.name for h in december}
    assert all(h.start[:10] >= "2026-12-05" for h in december)
    assert "Julien Clerc" not in {h.name for h in december}


async def test_a_zone_finds_the_events_inside_it(desk):
    roubaix = await desk.events(bbox=(3.15, 50.67, 3.18, 50.70), limit=50)
    assert {h.name for h in roubaix} >= {"Julien Clerc", "Fabrice Éboué", "Quatuor Poulenc"}
    assert all(h.distance_m is None for h in roubaix)


async def test_the_place_of_an_event_is_its_named_venue_or_its_address(desk):
    [clerc] = await desk.events(near=LILLE, radius_m=30_000, text="Julien Clerc")
    assert clerc.place == "Le Colisée, Roubaix"  # le théâtre, pas le kebab d'à côté, plus près
    [poulenc] = await desk.events(near=LILLE, radius_m=30_000, text="Poulenc")
    assert poulenc.place.endswith(", Roubaix") and "Colisée" not in poulenc.place


async def test_an_event_detail_says_its_dates_prices_contacts_author_and_date(desk):
    [poulenc] = await desk.events(near=LILLE, radius_m=30_000, text="Poulenc")
    detail = await desk.event(poulenc.id)
    assert detail.hit == poulenc or detail.hit.id == poulenc.id
    assert detail.prices == "Entrée 10€/7€/5€" and detail.hit.free is False
    assert detail.author == "Hauts-de-France Tourisme" and len(detail.updated) == 10
    assert detail.dates[0].text == "ven. 20 nov. · 19:00–20:30" and detail.more_dates == 0
    assert detail.address.endswith("Roubaix") and detail.town == "Roubaix"
    assert detail.description and "**" not in detail.description
    assert all("Jeanne" not in value for _label, value in detail.contacts)


async def test_unknown_ids_and_bad_arguments(desk):
    assert await desk.event("e:00000000-0000-0000-0000-000000000000") is None
    assert await desk.event("e:pas-un-uuid") is None and await desk.event("l12") is None
    with pytest.raises(ValueError):
        await desk.events(near=LILLE, themes=frozenset({"opera"}))
    with pytest.raises(ValueError):
        await desk.events(near=LILLE, start=date(2026, 12, 1), end=date(2026, 11, 1))
    with pytest.raises(ValueError):
        await desk.events(near=LILLE, start=date(2026, 11, 18), end=date(2028, 1, 1))
    with pytest.raises(ValueError):
        await desk.events(bbox=(3.2, 50.6, 3.1, 50.7))


async def test_without_a_base_events_say_so_in_words(tmp_path):
    desk = MapsDesk(tmp_path, PlacesConfig, RoutingConfig, clock=tf.Clock())
    with pytest.raises(MapsUnavailable) as caught:
        await desk.events(near=LILLE)
    assert "pas réglées" in str(caught.value)
    assert desk.tourism_coverage(near=LILLE).note.startswith("Les données touristiques ne sont pas réglées")
    assert desk.tourism_summary() == {"ready": False, "places": 0, "events": 0, "synced": ""}
    await desk.close()


def test_the_summary_says_what_the_base_holds(desk):
    summary = desk.tourism_summary()
    assert summary["ready"] and summary["places"] == 8 and summary["events"] > 10 and summary["synced"]
