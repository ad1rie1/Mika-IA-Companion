"""Preuve M0 — oubli : une chaîne témoin passe par ``forget`` et devient
introuvable dans ``mind.db``, ``views.db``, les WAL et les instantanés ; le
rejeu fonctionne encore."""

from __future__ import annotations

from pathlib import Path

from mika.kernel.events import Content
from mika.runtime.projections import ensure_t0
from tests.conftest import make_mind
from tests.fixtures.projectors import with_projectors
from tests.fixtures.toys import BUMPED

CANARY = "Léa-part-à-Reykjavik-7f3a9c"


def files_containing(root: Path, needle: bytes) -> list[str]:
    hits = []
    for p in root.iterdir():
        if p.is_file() and needle in p.read_bytes():
            hits.append(p.name)
    return hits


async def test_forget_removes_canary_everywhere_and_replay_survives(tmp_path):
    fac = with_projectors(t0=True)
    mind = make_mind(tmp_path, [fac], snapshot_every=2)
    await mind.boot(append_boot=False)
    await ensure_t0(mind)
    await mind.append([BUMPED.draft(by=1, note=Content.of(f"confidence : {CANARY}", level=2), who="lea")],
                      emitter="counter", correlation="t")
    for i in range(5):
        await mind.append([BUMPED.draft(by=1, note=Content.of(f"banal {i}"), who="bob")],
                          emitter="counter", correlation="t")
    needle = CANARY.encode()
    assert files_containing(tmp_path, needle), "le témoin doit d'abord être présent"
    removed = await mind.forget("lea")
    assert removed == 1
    await mind.close()
    assert files_containing(tmp_path, needle) == []
    # l'enveloppe survit : le rejeu fonctionne, le compteur est intact
    mind2 = make_mind(tmp_path, [fac], snapshot_every=10**9)
    await mind2.boot(append_boot=False)
    assert mind2.root.slices["counter"].n == 6
    assert mind2.root.slices["counter"].notes == 6
    rows = mind2.store.query_mind("SELECT who, body FROM textlog ORDER BY seq")
    assert [r[0] for r in rows] == ["bob"] * 5
    await mind2.close()
