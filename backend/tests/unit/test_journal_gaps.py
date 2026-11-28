"""Un journal relu avec des trous (audit du 2026-10-26) : des événements ont disparu — une réparation à la main, une
base recopiée à moitié. La relecture le voit (``BootReport.gaps``, ``Mind.gaps``), le dit en anomalie, et
``replay --verify`` le compte comme un échec ; un journal sain n'a aucun trou."""

from __future__ import annotations

from sqlalchemy import delete

from mika.ports.journal import JournalEvent
from tests.conftest import make_mind
from tests.fixtures.toys import BUMPED, COUNTER


async def _life(tmp_db) -> None:
    mind = make_mind(tmp_db, [COUNTER])
    await mind.boot()
    for _ in range(5):
        await mind.append([BUMPED.draft(by=1)], emitter="counter", correlation="t")
    await mind.close()


async def test_a_whole_journal_has_no_gap(tmp_db):
    await _life(tmp_db)
    mind = make_mind(tmp_db, [COUNTER])
    report = await mind.boot(append_boot=False)
    assert report.gaps == () and mind.gaps == ()
    await mind.close()


async def test_boot_reports_a_hole_in_the_journal(tmp_db):
    await _life(tmp_db)
    mind = make_mind(tmp_db, [COUNTER])
    await mind.boot(append_boot=False)
    await mind.store.run_mind(lambda sql: sql.execute(delete(JournalEvent).where(JournalEvent.seq.in_((3, 4)))))
    await mind.close()
    again = make_mind(tmp_db, [COUNTER])
    report = await again.boot(append_boot=False)
    assert report.gaps == ((3, 5),)  # les seq 3 et 4 manquent : on attendait 3, on a relu 5
    assert again.gaps == report.gaps
    assert any("trou" in a for a in again.anomalies)
    assert any(t.kind == "gaps" for t in again.traces)
    await again.close()


async def test_rebuild_sees_the_hole_too(tmp_db):
    await _life(tmp_db)
    mind = make_mind(tmp_db, [COUNTER])
    await mind.boot(append_boot=False)
    await mind.store.run_mind(lambda sql: sql.execute(delete(JournalEvent).where(JournalEvent.seq == 2)))
    report = await mind.rebuild(["counter"])
    assert report["gaps"] == [(2, 3)]
    await mind.close()
