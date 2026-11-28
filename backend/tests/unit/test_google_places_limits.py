"""Les bornes de Google (ADR 0256), sur le limiteur partagé des services de la carte, comptées en appels : par
seconde (cinq par défaut, espacés), sur 24 heures glissantes (tous niveaux), et par mois pour chaque SKU (recherches,
fiches avec avis, photos) — par défaut le quota offert de chacun, pour que rien ne soit facturé ; le mois de Google
commence à minuit, heure du Pacifique ; un appel compte dès qu'il part, jamais deux au-delà du plafond ; la réserve que
le fond laisse au direct ; chaque borne réglée dans la console et relue à chaque appel."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from pydantic import ValidationError

from mika.adapters.maps.config import ReviewsConfig
from mika.adapters.maps.google_places import DETAILS, GOOGLE_MONTH, NEARBY, PHOTO, reviews_limits, sku_limits
from mika.adapters.maps.hours import PARIS
from mika.adapters.maps.quota import DAY, MONTH, QuotaExceeded
from tests.fixtures import google_places as gp
from tests.fixtures.tourism import Clock

PHOTO_NAME = f"places/{gp.BELLEZZA}/photos/AV-photo-fictive-01"


def config(**fields) -> ReviewsConfig:
    return ReviewsConfig(api_key=gp.KEY, **fields)


def used(rig: gp.Rig, sku) -> int:  # noqa: ANN001
    return next(w.used for w in rig.client.skus[sku.service].status().windows if w.name == MONTH)


@pytest.mark.parametrize(("field", "value"), [("per_second", 10.5), ("per_second", 0.0), ("per_day", 0),
                                              ("per_day", 100_001), ("searches_per_month", -1),
                                              ("details_per_month", 1_000_001), ("photos_per_month", -5),
                                              ("reserve_pct", 95), ("cache_days", 0), ("cell_km", 25),
                                              ("split_depth", 3)])
def test_the_bounds_are_kept_and_the_defaults_bill_nothing(field, value):
    with pytest.raises(ValidationError) as caught:
        config(**{field: value})
    assert gp.KEY not in str(caught.value)
    cfg = ReviewsConfig()
    assert (cfg.per_second, cfg.per_day, cfg.reserve_pct, cfg.cache_days, cfg.cell_km, cfg.split_depth) == (
        5.0, 500, 20, 7, 3, 1)
    # par défaut, chaque plafond du mois est le quota offert de son SKU
    assert [sku_limits(cfg, s).per_month for s in (NEARBY, DETAILS, PHOTO)] == [NEARBY.free, DETAILS.free,
                                                                                PHOTO.free] == [1000] * 3
    limits = reviews_limits(cfg)
    assert (limits.per_second, limits.per_day, limits.per_month, limits.reserve) == (5.0, 500, None, 0.2)


async def test_five_calls_a_second_are_spaced(tmp_path):
    rig = gp.rig(tmp_path)
    for _ in range(5):
        await rig.client.details(gp.BELLEZZA)
    assert len(rig.clock.slept) == 4 and all(s == pytest.approx(0.2, abs=1e-3) for s in rig.clock.slept)


async def test_the_day_slides_over_24_hours_for_every_level(tmp_path):
    rig = gp.rig(tmp_path, cfg=config(per_day=3))
    await rig.client.details(gp.BELLEZZA)
    rig.clock.advance(hours=1)
    await rig.client.nearby(*gp.GRAND_PLACE, 500, "manger")
    rig.clock.advance(hours=1)
    await rig.client.photo_uri(PHOTO_NAME)
    with pytest.raises(QuotaExceeded) as caught:
        await rig.client.details(gp.BELLEZZA)
    assert caught.value.window == DAY and "le quota du jour de Google est atteint" in str(caught.value)
    rig.clock.advance(hours=22, seconds=1)  # 24 heures après le premier
    await rig.client.details(gp.BELLEZZA)


async def test_each_level_has_its_own_month_and_never_goes_past_its_cap(tmp_path):
    rig = gp.rig(tmp_path, cfg=config(details_per_month=2, reserve_pct=0))
    await rig.client.details(gp.BELLEZZA)
    await rig.client.details(gp.BELLEZZA)
    with pytest.raises(QuotaExceeded) as caught:
        await rig.client.details(gp.BELLEZZA)
    assert caught.value.window == MONTH and "le quota du mois de Google (fiches avec avis) est atteint" in \
        str(caught.value) and "le 1er décembre" in str(caught.value)
    assert rig.api.calls(gp.DETAILS) == 2  # le troisième n'est pas parti
    await rig.client.nearby(*gp.GRAND_PLACE, 500, "manger")  # les recherches ont leur propre mois
    await rig.client.photo_uri(PHOTO_NAME)
    assert (used(rig, NEARBY), used(rig, DETAILS), used(rig, PHOTO)) == (1, 2, 1)
    assert "2 fiches ce mois sur 2" in rig.client.skus[DETAILS.service].describe()


async def test_the_month_of_google_begins_at_midnight_pacific_time(tmp_path):
    # le 1er décembre à 08:30 à Paris : encore le 30 novembre en Californie, le mois de novembre de Google
    clock = Clock(datetime(2026, 12, 1, 8, 30, tzinfo=PARIS))
    rig = gp.rig(tmp_path, cfg=config(details_per_month=1, reserve_pct=0), clock=clock)
    await rig.client.details(gp.BELLEZZA)
    with pytest.raises(QuotaExceeded) as caught:
        await rig.client.details(gp.BELLEZZA)
    assert caught.value.until == datetime(2026, 12, 1, tzinfo=GOOGLE_MONTH)
    assert "à 09:00" in str(caught.value)  # minuit du Pacifique, à l'heure de Paris
    clock.advance(minutes=31)
    await rig.client.details(gp.BELLEZZA)


async def test_two_calls_at_once_never_both_pass_under_the_cap(tmp_path):
    rig = gp.rig(tmp_path, cfg=config(photos_per_month=1, reserve_pct=0))
    got = await asyncio.gather(rig.client.photo_uri(PHOTO_NAME), rig.client.photo_uri(PHOTO_NAME),
                               return_exceptions=True)
    assert sum(isinstance(g, str) for g in got) == 1 and sum(isinstance(g, QuotaExceeded) for g in got) == 1
    assert rig.api.calls(gp.MEDIA) == 1 and used(rig, PHOTO) == 1


def day_used(rig: gp.Rig) -> int:
    return next(w.used for w in rig.client.limiter.status().windows if w.name == DAY)


async def test_a_call_held_by_its_month_does_not_count_in_the_day(tmp_path):
    """R1-04 : le mois des photos atteint, chaque vignette redemandée inscrivait un appel qui n'était jamais parti
    dans les 24 heures de tout Google — les fiches et les recherches finissaient refusées, leurs mois intacts. Un appel
    retenu par son mois ne coûte rien ailleurs, même quand deux partent au même instant."""
    rig = gp.rig(tmp_path, cfg=config(photos_per_month=0, per_day=2, reserve_pct=0))
    for _ in range(3):
        with pytest.raises(QuotaExceeded) as caught:
            await rig.client.photo_uri(PHOTO_NAME)
        assert caught.value.window == MONTH
    assert day_used(rig) == 0 and rig.api.calls(gp.MEDIA) == 0
    await rig.client.details(gp.BELLEZZA)
    await rig.client.nearby(*gp.GRAND_PLACE, 500, "manger")
    assert day_used(rig) == 2
    other = gp.rig(tmp_path / "deux", cfg=config(photos_per_month=1, reserve_pct=0))
    await asyncio.gather(other.client.photo_uri(PHOTO_NAME), other.client.photo_uri(PHOTO_NAME),
                         return_exceptions=True)
    assert day_used(other) == 1 and other.api.calls(gp.MEDIA) == 1


async def test_background_work_leaves_the_reserve_to_what_a_person_opens(tmp_path):
    rig = gp.rig(tmp_path, cfg=config(searches_per_month=10, reserve_pct=30))
    for _ in range(7):
        await rig.client.nearby(*gp.GRAND_PLACE, 500, "voir", background=True)
    with pytest.raises(QuotaExceeded) as caught:
        await rig.client.nearby(*gp.GRAND_PLACE, 500, "voir", background=True)
    assert "la part de fond du quota du mois de Google (recherches à proximité)" in str(caught.value)
    for _ in range(3):
        await rig.client.nearby(*gp.GRAND_PLACE, 500, "voir")  # en direct : la réserve
    with pytest.raises(QuotaExceeded):
        await rig.client.nearby(*gp.GRAND_PLACE, 500, "voir")


async def test_a_bound_changed_in_the_console_is_read_at_the_next_call(tmp_path):
    rig = gp.rig(tmp_path, cfg=config(details_per_month=1, reserve_pct=0))
    await rig.client.details(gp.BELLEZZA)
    with pytest.raises(QuotaExceeded):
        await rig.client.details(gp.BELLEZZA)
    rig.config[0] = config(details_per_month=5, reserve_pct=0, per_second=1)
    await rig.client.details(gp.BELLEZZA)
    await rig.client.details(gp.BELLEZZA)
    assert rig.clock.slept[-1] == pytest.approx(1.0, abs=1e-3)  # une par seconde, désormais


async def test_the_counters_are_shared_and_survive_a_restart(tmp_path):
    first = gp.rig(tmp_path, cfg=config(per_day=2))
    await first.client.details(gp.BELLEZZA)
    await first.client.photo_uri(PHOTO_NAME)
    again = gp.rig(tmp_path, cfg=config(per_day=2), clock=first.clock)
    with pytest.raises(QuotaExceeded):
        await again.client.nearby(*gp.GRAND_PLACE, 500, "manger")
    assert (used(again, DETAILS), used(again, PHOTO), used(again, NEARBY)) == (1, 1, 0)
