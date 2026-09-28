"""Preuve M0 — projections : un événement empoisonné est réessayé puis mis en
quarantaine, la projection continue ; une reconstruction bleu/vert donne la
même table."""

from __future__ import annotations

import asyncio

from mika.kernel.codec import digest
from mika.runtime.projections import ProjectionWorker
from tests.conftest import make_mind
from tests.fixtures.projectors import with_projectors
from tests.fixtures.toys import BUMPED


def table(mind, name: str) -> list[tuple]:
    return mind.store.query_views(f"SELECT * FROM {name} ORDER BY 1")


async def test_poison_is_quarantined_and_projection_continues(tmp_path):
    mind = make_mind(tmp_path, [with_projectors(t1=1)])
    await mind.boot()
    worker = ProjectionWorker(mind)
    for who in ["alice", "bob", "poison", "alice", "carol"]:
        await mind.append([BUMPED.draft(by=1, who=who)], emitter="counter", correlation="t")
    await worker.catch_up(mind.registry.projectors["tally"])
    assert worker.quarantined and worker.quarantined[0][0] == "tally"
    rows = dict(table(mind, "tally_v1"))
    assert rows == {"alice": 2, "bob": 1, "carol": 1}
    assert worker.lag()["tally"] == 0
    q = mind.store.query_views("SELECT name, seq FROM projector_quarantine")
    assert len(q) == 1
    await mind.close()


async def test_blue_green_rebuild_gives_the_same_table(tmp_path):
    v1 = with_projectors(t1=1)
    mind = make_mind(tmp_path, [v1])
    await mind.boot()
    for i in range(40):
        await mind.append([BUMPED.draft(by=i % 3 + 1, who=f"p{i % 5}")], emitter="counter", correlation="t")
    await ProjectionWorker(mind).catch_up(mind.registry.projectors["tally"])
    before = digest(table(mind, "tally_v1"))
    await mind.close()

    mind2 = make_mind(tmp_path, [with_projectors(t1=2)])
    await mind2.boot(append_boot=False)
    worker = ProjectionWorker(mind2)
    await worker.catch_up(mind2.registry.projectors["tally"])
    assert mind2.store.projector_state("tally") == (2, mind2.head)
    assert digest(table(mind2, "tally_v2")) == before
    tables = {r[0] for r in mind2.store.query_views("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "tally_v1" not in tables  # l'ancienne version est abandonnée après bascule
    await mind2.close()


async def test_t2_runs_prepare_outside_writer(tmp_path):
    mind = make_mind(tmp_path, [with_projectors(t2=True)])
    await mind.boot()
    for i in range(5):
        await mind.append([BUMPED.draft(by=1, who="x")], emitter="counter", correlation="t")
    worker = ProjectionWorker(mind)
    await asyncio.wait_for(worker.catch_up(mind.registry.projectors["heavy"]), timeout=30)
    assert len(table(mind, "heavy_v1")) == 5
    await mind.close()
