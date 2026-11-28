"""Les courbes de la console : une mesure déclarée (``@f.series``) est
échantillonnée à son rythme dans ``views.db``, lue en moyennes par tranches,
élaguée au-delà de sa rétention — et ne touche jamais au journal."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from mika.kernel.clock import DAY, HOUR, MINUTE, US
from mika.kernel.faculty import Faculty
from mika.runtime.series import TABLE
from mika.sim.clock import run_virtual
from tests.fixtures.harness import build


@dataclass(frozen=True, slots=True)
class Gauge:
    level: float = 0.5


GAUGE = Faculty("gauge", state=Gauge, init=lambda p: Gauge())
calls: list[int] = []


@GAUGE.series("niveau", label="Niveau", lo=0, hi=1, every_s=600)
def _level(s: Gauge, frame) -> float:
    calls.append(frame.now)
    return 0.25 + (frame.now // (10 * MINUTE)) % 3 * 0.25


@GAUGE.series("casse", label="Cassée", every_s=600)
def _broken(s: Gauge, frame) -> float:
    raise ValueError("une mesure qui lève ne casse rien")


def test_series_are_sampled_read_and_pruned(tmp_path):
    kernel, clock, _ = build(tmp_path, [GAUGE])

    async def main():
        await kernel.start()
        head = kernel.mind.head
        start = kernel.mind.clock.now()
        await asyncio.sleep(2 * HOUR / US)
        now = kernel.mind.clock.now()
        points = kernel.series.read("gauge.niveau", start, now, 240)
        coarse = kernel.series.read("gauge.niveau", start, now, 4)
        broken = kernel.series.read("gauge.casse", start, now, 240)
        journal_untouched = kernel.mind.head == head
        await kernel.series.write([("gauge.niveau", now - 90 * DAY, 1.0)], now - 89 * DAY)
        await kernel.series.write([("gauge.niveau", now + 1, 0.5)], now + 2 * DAY)
        old = kernel.mind.store.query_views(
            f"SELECT COUNT(*) FROM {TABLE} WHERE at < ?", (now - 60 * DAY,))
        await kernel.stop()
        return points, coarse, broken, journal_untouched, old

    points, coarse, broken, journal_untouched, old = run_virtual(clock, main)
    assert 11 <= len(points) <= 13  # une mesure toutes les dix minutes pendant deux heures
    assert {round(v, 2) for _, v in points} <= {0.25, 0.5, 0.75}
    assert len(coarse) <= 4 and all(0.25 <= v <= 0.75 for _, v in coarse)  # moyennes par tranches
    assert broken == []
    assert journal_untouched  # les courbes vivent hors du journal
    assert old[0][0] == 0  # au-delà de la rétention : élagué
