"""Le fil d'une personne (faculté ``transcript``) : l'historique par défaut couvre ce qui précède la première
compaction, et une compaction que le modèle coupe se reprend sur un lot réduit de moitié."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import insert

from mika.contracts.transcript import thread_table
from mika.faculties.memory.projections import Chunks, Items
from mika.faculties.transcript import Thread, TranscriptParams, TranscriptState, _thread
from mika.kernel.clock import DAY
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from tests.fixtures.memory import Script
from tests.fixtures.mika import boot, build, connect, said
from tests.fixtures.sqldb import SqlDB as DB


@pytest.fixture
def db():
    db = DB()
    Items().create(db, "")
    Chunks().create(db, "")
    yield db
    db.conn.close()


async def test_default_history_covers_the_gap_before_first_compaction(db):
    Thread().create(db, "")
    db.execute(insert(thread_table()), [{"id": i, "at": DAY + i, "role": "user", "person": "user_2",
                                         "text": f"Message {i}", "folded": f"message {i}"} for i in range(1, 62)])
    frame = NS(episode=NS(target="user_2", attrs={}), audience=None, root=None, now=DAY + 62,
               env=NS(params_of=lambda *a: TranscriptParams(), tz_of=lambda *a: ZoneInfo("UTC")))
    view = await _thread(TranscriptState(), frame, {"store": db})
    assert [t.id for t in view.turns] == list(range(1, 62))


def test_compaction_halves_a_truncated_batch_and_retries_without_new_messages(tmp_path):
    from mika.faculties.transcript import TranscriptParams
    class Truncated(Script):
        def __call__(self, req):
            if req.role == 'compact':
                self.calls.append(req)
                count = sum(call.role == 'compact' for call in self.calls)
                return LLMResponse('résumé coupé', stop='max_tokens') if count <= 2 else LLMResponse('Alice cultive des roses.')
            return super().__call__(req)
    script = Truncated()
    kernel, clock, _, _ = build(tmp_path, script)
    async def main():
        await boot(kernel)
        await kernel.set_params('transcript', TranscriptParams(compact_after=10, keep=4, compact_retry_us=60_000_000))
        await connect(kernel, 'user_2', 'Alice')
        for i in range(12):
            result = await kernel.perceive(said('user_2', f'Je cultive des roses depuis {i} jours'))
            await result.reply
        await asyncio.sleep(20 * 60)
        compact = [req for req in script.calls if req.role == 'compact']
        assert len(compact) >= 3
        assert len(compact[2].messages[-1].content) < len(compact[0].messages[-1].content)
        assert kernel.mind.root.slices['transcript'].summaries
        await kernel.stop()
    run_virtual(clock, main)
