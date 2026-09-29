from __future__ import annotations

import pytest

from mika.kernel.codec import digest
from mika.kernel.events import Content, Origin
from tests.conftest import make_mind
from tests.fixtures.toys import BUMPED, COUNTER, ECHO, PEOPLE, SAID, VALUE


async def test_append_reduces_and_double_buffers(tmp_db):
    mind = make_mind(tmp_db, [COUNTER, ECHO, PEOPLE])
    await mind.boot()
    c = await mind.append([BUMPED.draft(by=2), BUMPED.draft(by=3)], emitter="counter", correlation="t")
    assert c.seqs == (2, 3)  # 1 = kernel.boot
    assert mind.frame().get(VALUE) == 5
    # echo a lu la valeur d'avant chaque événement
    assert mind.root.slices["echo"].seen == (0, 2)
    await mind.close()


async def test_only_owner_emits(tmp_db):
    mind = make_mind(tmp_db, [COUNTER, PEOPLE])
    await mind.boot()
    with pytest.raises(PermissionError):
        await mind.append([BUMPED.draft(by=1)], emitter="people", correlation="t")
    await mind.close()


async def test_content_is_split_from_envelope(tmp_db):
    mind = make_mind(tmp_db, [COUNTER])
    await mind.boot()
    c = await mind.append(
        [BUMPED.draft(by=1, note=Content.of("un secret de Léa"), who="alice")], emitter="counter", correlation="t"
    )
    ev = c.events[0]
    assert ev.data.note.text is None and ev.data.note.ref == f"{ev.seq}.note"
    row = mind.store.query_mind("SELECT data FROM events WHERE seq=?", (ev.seq,))[0][0]
    assert "secret" not in row
    assert mind.content_text(ev.data.note) == "un secret de Léa"
    await mind.close()


async def test_dedupe_returns_original_commit(tmp_db):
    mind = make_mind(tmp_db, [COUNTER])
    await mind.boot()
    first = await mind.append([BUMPED.draft(by=1, dedupe_key="k1")], emitter="counter", correlation="t")
    again = await mind.append([BUMPED.draft(by=1, dedupe_key="k1")], emitter="counter", correlation="t")
    assert again.deduped and again.seqs == first.seqs
    assert mind.root.slices["counter"].n == 1
    await mind.close()


async def test_replay_equals_live_and_snapshot_plus_tail(tmp_db):
    mind = make_mind(tmp_db, [COUNTER, ECHO, PEOPLE], snapshot_every=7)
    await mind.boot()
    for i in range(20):
        await mind.append([BUMPED.draft(by=i)], emitter="counter", correlation="t")
        await mind.append([SAID.draft(who=f"p{i % 3}")], emitter="people", correlation="t", origin=Origin.EXTERNAL)
    live = digest({k: v for k, v in mind.root.slices.items()})
    await mind.close()

    # relance : instantané + queue
    again = make_mind(tmp_db, [COUNTER, ECHO, PEOPLE], snapshot_every=7)
    report = await again.boot(append_boot=False)
    assert report.snapshot_seq > 0
    assert digest({k: v for k, v in again.root.slices.items()}) == live
    await again.close()

    # rejeu complet depuis la genèse (sans instantané)
    fresh = make_mind(tmp_db, [COUNTER, ECHO, PEOPLE], snapshot_every=10**9)
    await fresh.store.open()
    await fresh.store.run_mind(lambda sql: sql.execute("DELETE FROM snapshots"))
    await fresh.store.close()
    report = await fresh.boot(append_boot=False)
    assert report.snapshot_seq == 0 and report.replayed > 40
    assert digest({k: v for k, v in fresh.root.slices.items()}) == live
    await fresh.close()


async def test_a_write_cancelled_in_flight_is_still_published(tmp_db):
    """Avec le fil d'écriture (serveur), annuler l'appelant pendant qu'il attend
    la transaction ne doit pas perdre la racine : la transaction va au bout,
    elle est publiée, et l'ajout suivant prend le ``seq`` d'après (la file de
    sortie mourait sur « UNIQUE constraint failed: events.seq »)."""
    import asyncio

    mind = make_mind(tmp_db, [COUNTER], threaded=True)
    await mind.boot()
    task = asyncio.ensure_future(mind.append([BUMPED.draft(by=1)], emitter="counter", correlation="t"))
    for _ in range(50):  # jusqu'à ce que l'écriture soit partie vers le fil
        await asyncio.sleep(0)
        if mind._lock.locked():
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    after = await mind.append([BUMPED.draft(by=2)], emitter="counter", correlation="t")
    assert mind.root.slices["counter"].n == 3 and after.seqs == (3,)  # 1 + 2 : les deux sont là
    assert [r[0] for r in mind.store.query_mind("SELECT seq FROM events ORDER BY seq")] == [1, 2, 3]
    await mind.close()
