"""Preuve M0 — file de sortie : ``kill -9`` entre le commit et l'effet, ou
pendant l'effet → après redémarrage l'effet part exactement une fois, et
jamais avant le commit."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fixtures.outbox_toy import make, sink_path

ROOT = Path(__file__).resolve().parents[2]


def run_child(tmp: Path, mode: str, crash_in_effect: bool = False) -> int:
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    if crash_in_effect:
        env["CRASH_IN_EFFECT"] = "1"
    return subprocess.run([sys.executable, "-m", "tests.fixtures.outbox_toy", str(tmp), mode],
                          cwd=ROOT, env=env).returncode


def sent(tmp: Path) -> int:
    p = sink_path(tmp)
    if not p.exists():
        return 0
    conn = sqlite3.connect(p)
    try:
        return conn.execute("SELECT count(*) FROM sent").fetchone()[0]
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


async def restart_and_drain(tmp: Path) -> tuple[int, int, list[str]]:
    mind, executor = make(tmp)
    await mind.boot(append_boot=False)
    first = await executor.drain()
    second = await executor.drain()
    statuses = [r[0] for r in mind.store.query_mind("SELECT status FROM outbox")]
    await mind.close()
    return first, second, statuses


@pytest.mark.parametrize("mode,crash_in_effect", [("after_commit", False), ("during_effect", True)])
def test_effect_runs_exactly_once_after_kill(tmp_path, mode, crash_in_effect):
    code = run_child(tmp_path, mode, crash_in_effect)
    assert code == 9
    before = sent(tmp_path)
    assert before == (1 if mode == "during_effect" else 0)
    first, second, statuses = asyncio.run(restart_and_drain(tmp_path))
    assert sent(tmp_path) == 1  # exactement une fois (le gestionnaire est idempotent par id d'événement)
    assert second == 0
    assert statuses == ["done"]


def test_no_effect_without_commit(tmp_path):
    code = run_child(tmp_path, "before_commit")
    assert code == 9
    first, second, statuses = asyncio.run(restart_and_drain(tmp_path))
    assert sent(tmp_path) == 0 and statuses == [] and first == 0
