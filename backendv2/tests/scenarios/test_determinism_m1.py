"""La composition complète est déterministe : S13 réduit (pannes comprises),
joué sous deux ``PYTHONHASHSEED``, produit le même journal."""

from __future__ import annotations

import os
import subprocess
import sys

CODE = """
import logging, sys, tempfile
from pathlib import Path
logging.disable(logging.WARNING)
from mika.app.composition import for_simulation
from mika.kernel.codec import digest
from mika.adapters.store_sqlite import SqliteStore
from mika.sim.catalog import QUICK, run_plan
import asyncio
plan = next(p for p in QUICK if p.name.startswith("S13"))
with tempfile.TemporaryDirectory() as tmp:
    run_plan(plan, for_simulation(), Path(tmp), 4)
    store = SqliteStore(Path(tmp) / "mind.db", Path(tmp) / "views.db", threaded=False)
    asyncio.run(store.open())
    print(digest([(s.seq, s.type, s.at, s.data) for s in store.read()]))
    asyncio.run(store.close())
"""


def test_same_log_under_two_hash_seeds():
    outs = set()
    for hashseed in ("0", "31337"):
        env = dict(os.environ, PYTHONHASHSEED=hashseed)
        res = subprocess.run([sys.executable, "-c", CODE], env=env, capture_output=True, text=True, check=True)
        outs.add(res.stdout.strip().splitlines()[-1])
    assert len(outs) == 1, outs
