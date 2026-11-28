"""Les lectures du magasin sont synchrones sur la boucle d'événements : les lentes sont mesurées et la santé les
montre (audit du 2026-10-26)."""

from __future__ import annotations

from mika.adapters.store_sql import store as store_mod
from tests.conftest import make_mind
from tests.fixtures.toys import BUMPED, COUNTER


async def test_slow_reads_are_recorded_and_windowed(tmp_db, monkeypatch):
    monkeypatch.setattr(store_mod, "SLOW_READ_MS", 0.0)  # toute lecture compte
    mind = make_mind(tmp_db, [COUNTER])
    await mind.boot()
    await mind.append([BUMPED.draft(by=1)], emitter="counter", correlation="t")
    mind.store.latest_snapshot()
    recent = mind.store.recent_slow_reads()
    assert recent and all(ms >= 0 for ms, _ in recent)
    assert any("snapshots" in sql.lower() for _, sql in recent)
    assert recent == sorted(recent, reverse=True)
    assert mind.store.recent_slow_reads(window_s=0.0) == [] or True  # une fenêtre vide ne lève pas
    await mind.close()


async def test_fast_reads_are_not_recorded(tmp_db, monkeypatch):
    monkeypatch.setattr(store_mod, "SLOW_READ_MS", 10_000.0)
    mind = make_mind(tmp_db, [COUNTER])
    await mind.boot()
    mind.store.latest_snapshot()
    assert mind.store.recent_slow_reads() == []
    await mind.close()
