"""Le limiteur des services de la carte (ADR 0245) : des bornes facultatives qui se combinent — par seconde, par heure
et par jour (glissantes), par mois (un compteur du coût réel) —, une réserve que le travail de fond laisse au direct,
un recul quand le service dit d'attendre ; des compteurs qui survivent à un redémarrage (``cartes/quotas.db``), chaque
service les siens ; ce qui bloque dit en mots, avec l'heure où il revient."""

from __future__ import annotations

from datetime import datetime

import pytest

from mika.adapters.maps.hours import PARIS
from mika.adapters.maps.quota import DAY, HOUR, MONTH, WAIT, Limiter, Limits, QuotaExceeded, QuotaStore
from tests.fixtures.tourism import Clock

#: le mercredi 18 novembre 2026, 10:00 à Paris
NOW = datetime(2026, 11, 18, 10, 0, tzinfo=PARIS)


def limiter(tmp_path, limits: Limits, clock: Clock, service: str = "essai") -> Limiter:
    return Limiter(service, QuotaStore(tmp_path / "cartes" / "quotas.db"), lambda: limits, label="Essai",
                   now=clock.stamp, sleep=clock.sleep)


async def test_an_hourly_cap_waits_for_the_oldest_call_of_the_hour_or_says_when_it_comes_back(tmp_path):
    clock = Clock(NOW)
    lim = limiter(tmp_path, Limits(per_hour=2), clock)
    await lim.take()
    clock.advance(minutes=5)
    await lim.take()
    with pytest.raises(QuotaExceeded) as caught:
        await lim.take(wait_max=60)
    assert caught.value.window == HOUR and caught.value.until.strftime("%H:%M") == "11:00"
    assert str(caught.value) == "le quota de l'heure de Essai est atteint : il revient à 11:00."
    await lim.take(wait_max=3600)  # elle attend que la première sorte de l'heure
    assert clock.at.strftime("%H:%M") == "11:00"


async def test_background_work_leaves_the_reserve_to_live_requests(tmp_path):
    clock = Clock(NOW)
    lim = limiter(tmp_path, Limits(per_hour=10, reserve=0.3), clock)
    for _ in range(7):
        await lim.take(background=True)
    with pytest.raises(QuotaExceeded) as caught:
        await lim.take(background=True)
    assert "la part de fond du quota de l'heure" in str(caught.value)
    for _ in range(3):
        await lim.take()  # le direct a encore sa réserve
    with pytest.raises(QuotaExceeded):
        await lim.take()
    [window] = lim.status().windows
    assert (window.used, window.limit, window.kept) == (10, 10, 3)
    assert "10 demandes dans l'heure sur 10 (3 gardées pour le direct)" in lim.describe()


async def test_a_day_window_slides_over_24_hours(tmp_path):
    clock = Clock(NOW)
    lim = limiter(tmp_path, Limits(per_day=2), clock)
    await lim.take()
    clock.advance(hours=20)
    await lim.take()
    with pytest.raises(QuotaExceeded) as caught:
        await lim.take()
    assert caught.value.window == DAY and str(caught.value).endswith("du jour de Essai est atteint : il revient à 10:00.")
    clock.advance(hours=4, seconds=1)
    await lim.take()


async def test_a_month_counts_the_real_cost_of_each_call(tmp_path):
    clock = Clock(NOW)
    lim = limiter(tmp_path, Limits(per_month=100, reserve=0.1), clock)
    await lim.take(cost=20)
    await lim.charge(85)  # l'appel a rendu 85 entités
    with pytest.raises(QuotaExceeded) as caught:
        await lim.take(cost=20)
    assert caught.value.window == MONTH and "le 1er décembre" in str(caught.value)
    assert caught.value.until == datetime(2026, 12, 1, tzinfo=PARIS)
    with pytest.raises(QuotaExceeded):
        await lim.take(cost=10, background=True)  # le fond s'arrête à 90
    clock.advance(days=13)  # décembre : un mois neuf
    await lim.take(cost=20)


async def test_seconds_space_the_calls_out(tmp_path):
    clock = Clock(NOW)
    lim = limiter(tmp_path, Limits(per_second=4), clock)
    for _ in range(5):
        await lim.take()
    assert clock.slept and all(abs(s - 0.25) < 1e-6 for s in clock.slept)


async def test_a_429_backs_off_every_instance_until_the_time_said(tmp_path):
    clock = Clock(NOW)
    lim = limiter(tmp_path, Limits(per_hour=100), clock)
    lim.back_off(600)
    other = limiter(tmp_path, Limits(per_hour=100), clock)  # un autre processus, la même base
    with pytest.raises(QuotaExceeded) as caught:
        await other.take()
    assert caught.value.window == WAIT and "a demandé d'attendre : il revient à 10:10" in str(caught.value)
    await other.take(wait_max=601)


async def test_counters_survive_a_restart_and_each_service_has_its_own(tmp_path):
    clock = Clock(NOW)
    first = limiter(tmp_path, Limits(per_hour=2), clock, "a")
    await first.take()
    await first.take()
    again = limiter(tmp_path, Limits(per_hour=2), clock, "a")
    with pytest.raises(QuotaExceeded):
        await again.take()
    await limiter(tmp_path, Limits(per_hour=2), clock, "b").take()


def test_reading_never_creates_the_file_and_without_limits_nothing_blocks(tmp_path):
    clock = Clock(NOW)
    lim = limiter(tmp_path, Limits(), clock)
    assert lim.status().windows == () and lim.describe() == "aucune borne"
    assert not (tmp_path / "cartes" / "quotas.db").exists()


async def test_the_bounds_are_read_again_at_each_call(tmp_path):
    clock = Clock(NOW)
    bounds = [Limits(per_hour=1)]
    lim = Limiter("essai", QuotaStore(tmp_path / "q.db"), lambda: bounds[0], now=clock.stamp, sleep=clock.sleep)
    await lim.take()
    with pytest.raises(QuotaExceeded):
        await lim.take()
    bounds[0] = Limits(per_hour=5)  # réglé dans la console : sans redémarrer
    await lim.take()
