"""Preuve M0 — déterminisme : 7 jours simulés (interlocuteurs synthétiques,
latences log-normales) → même empreinte sous deux ``PYTHONHASHSEED`` ; rejouer
depuis la genèse et depuis un instantané intermédiaire redonne l'état ; le tout
en moins de 30 s."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from mika.adapters.store_sqlite import SqliteStore
from mika.kernel.clock import ManualClock
from mika.kernel.ids import SeededIdGen
from mika.kernel.registry import Registry
from mika.runtime.mind import Mind
from mika.runtime.state import RUNTIME
from tests.conftest import START
from tests.fixtures.sim_week import FRIENDLY, state_digest

ROOT = Path(__file__).resolve().parents[2]


def run_child(tmp: Path, hashseed: str) -> dict:
    env = dict(os.environ, PYTHONHASHSEED=hashseed, PYTHONPATH=str(ROOT))
    out = subprocess.run([sys.executable, "-m", "tests.fixtures.sim_week", str(tmp), "7"], cwd=ROOT, env=env,
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


async def replay_digest(tmp: Path, *, keep_snapshot: str) -> tuple[str, int]:
    store = SqliteStore(tmp / "mind.db", tmp / "views.db", threaded=False)
    await store.open()
    if keep_snapshot == "none":
        await store.run_mind(lambda sql: sql.execute("DELETE FROM snapshots"))
    elif keep_snapshot == "oldest":
        await store.run_mind(lambda sql: sql.execute(
            "DELETE FROM snapshots WHERE seq <> (SELECT min(seq) FROM snapshots)"))
    rows = store.query_mind("SELECT seq FROM snapshots")
    await store.close()
    reg = Registry([RUNTIME, FRIENDLY])
    mind = Mind(reg, SqliteStore(tmp / "mind.db", tmp / "views.db", threaded=False), ManualClock(START),
                SeededIdGen(0))
    report = await mind.boot(append_boot=False)
    d = state_digest(mind.root, reg)
    await mind.close()
    return d, (rows[0][0] if rows else 0) if report else 0


def test_same_week_under_two_hash_seeds_and_replays(tmp_path):
    t0 = time.perf_counter()
    a = run_child(tmp_path / "a", "0")
    b = run_child(tmp_path / "b", "12345")
    elapsed = time.perf_counter() - t0
    assert a == b, (a, b)
    assert a["events"] > 100 and a["initiatives"] > 0
    assert elapsed < 60, elapsed  # deux semaines simulées

    live = a["state"]
    genesis, _ = asyncio.run(replay_digest(tmp_path / "a", keep_snapshot="none"))
    assert genesis == live
    mid, snap_seq = asyncio.run(replay_digest(tmp_path / "b", keep_snapshot="oldest"))
    assert snap_seq > 0 and mid == live
