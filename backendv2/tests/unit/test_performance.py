"""Preuve M0 — performances (sur cette machine) : ajout + application p95 <
10 ms en ``synchronous=FULL`` pendant qu'une projection T2 tourne ; rejeu d'un
million d'événements à travers dix réducteurs < 60 s ; chargement d'instantané
< 1 s."""

from __future__ import annotations

import asyncio
import json
import shutil
import statistics
import tempfile
import time
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from mika.adapters.store_sqlite import SqliteStore
from mika.adapters.system import RandomIdGen, RealClock
from mika.kernel.faculty import Faculty
from mika.kernel.ids import encode_ulid
from mika.kernel.registry import Registry
from mika.ports.store import StoredEvent
from mika.runtime.mind import Mind
from mika.runtime.projections import ProjectionWorker
from mika.runtime.state import RUNTIME
from tests.fixtures.projectors import with_projectors
from tests.fixtures.toys import BUMPED, COUNTER

pytestmark = pytest.mark.slow


@dataclass(frozen=True, slots=True)
class Sum:
    total: int = 0
    count: int = 0


def summers(n: int) -> list[Faculty]:
    out = []
    for i in range(n):
        f = Faculty(f"sum{i}", state=Sum, init=lambda p: Sum())

        @f.reducer(BUMPED)
        def _r(s: Sum, e, cx) -> Sum:
            return replace(s, total=s.total + e.data.by, count=s.count + 1)

        out.append(f)
    return out


async def test_append_p95_under_10ms_while_t2_runs():
    # Sur le vrai disque (pas /tmp, qui est en mémoire) : on mesure le fsync.
    disk = Path(__file__).resolve().parents[2] / ".perf"
    disk.mkdir(exist_ok=True)
    tmp_path = Path(tempfile.mkdtemp(dir=disk))
    store = SqliteStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=True, mind_synchronous="FULL")
    mind = Mind(Registry([RUNTIME, with_projectors(t2=True)]), store, RealClock(), RandomIdGen())
    await mind.boot()
    worker = ProjectionWorker(mind)
    background = asyncio.create_task(worker.run())
    durations = []
    for i in range(300):
        t0 = time.perf_counter()
        await mind.append([BUMPED.draft(by=1, who=f"p{i % 7}")], emitter="counter", correlation="perf")
        durations.append((time.perf_counter() - t0) * 1000)
        if i % 10 == 0:
            await asyncio.sleep(0)
    worker.stop()
    await asyncio.wait_for(background, timeout=60)
    p95 = statistics.quantiles(durations, n=20)[18]
    await mind.close()
    shutil.rmtree(tmp_path, ignore_errors=True)
    assert p95 < 10.0, f"p95 = {p95:.2f} ms"


async def test_replay_one_million_events_and_snapshot_load(tmp_path):
    n = 1_000_000
    store = SqliteStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False, mind_synchronous="OFF")
    reg = Registry([RUNTIME, COUNTER, *summers(9)])
    await store.open()
    batch: list[StoredEvent] = []
    t_at = 1_790_000_000_000_000
    for seq in range(1, n + 1):
        batch.append(StoredEvent(seq, encode_ulid(t_at // 1000 + seq, seq), "counter.bumped", 1, t_at + seq * 1000,
                                 None, "gen", 0, "external", json.dumps({"by": seq % 5, "note": None, "who": ""})))
        if len(batch) == 100_000:
            store.bulk_load(batch)
            batch = []
    await store.close()

    mind = Mind(reg, SqliteStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False),
                RealClock(), RandomIdGen(), snapshot_every=10**12)
    t0 = time.perf_counter()
    report = await mind.boot(append_boot=False)
    replay_s = time.perf_counter() - t0
    assert report.replayed == n
    assert mind.root.slices["sum8"].count == n
    assert replay_s < 60.0, f"rejeu : {replay_s:.1f} s"

    data = mind.snapshot_data(mind.root)
    t1 = time.perf_counter()
    from mika.ports.store import SnapshotRow

    root, stale = mind._load_snapshot(SnapshotRow(mind.head, mind.root.at, data))
    load_s = time.perf_counter() - t1
    assert not stale and root.slices["sum8"].count == n
    assert load_s < 1.0, f"instantané : {load_s:.3f} s"
    await mind.close()
