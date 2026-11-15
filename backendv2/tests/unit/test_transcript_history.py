"""Le fil d'une personne (faculté ``transcript``) : l'historique par défaut couvre ce qui précède la première
compaction, et une compaction que le modèle coupe se reprend sur un lot réduit de moitié. Le fil d'une conversation
est une règle des contrats (``transcript.thread_where``, ``identity.thread_handles``), que lisent l'historique et
ses redites."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import insert, select

from mika.contracts import identity as identity_c
from mika.contracts.transcript import thread_table, thread_where
from mika.faculties.memory.projections import Chunks, Items
from mika.faculties.transcript import Thread, TranscriptParams, TranscriptState
from mika.faculties.transcript.history import _thread
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


def test_the_thread_of_a_conversation_is_its_room_its_strand_or_the_private_thread_of_its_addresses():
    """Un salon : tout le salon (il prime). Un fil de travail : ses seuls messages. Sinon, le fil privé de ces
    adresses, sans ce qu'elles ont dit dans un salon ni leurs fils de travail. Ni salon ni adresse : une erreur."""
    db = DB()
    Thread().create(db, "")
    rows = [(1, "user_1", None, None), (2, "ext_5", None, None), (3, "user_1", "salon", None),
            (4, "user_2", "salon", None), (5, "user_1", None, "s1"), (6, "user_1", None, "s2"), (7, "user_3", None, None)]
    db.execute(insert(thread_table()), [{"id": i, "at": DAY + i, "role": "user", "person": who, "room": room,
                                         "strand": strand, "text": f"m{i}", "folded": f"m{i}"}
                                        for i, who, room, strand in rows])
    t = thread_table()

    def ids(**kw) -> list[int]:
        return [int(r[0]) for r in db.query_mind(select(t.c.id).where(*thread_where(t, **kw)).order_by(t.c.id))]

    assert ids(room="salon") == [3, 4]
    assert ids(room="salon", handles=("user_1",), strand="s1") == [3, 4]
    assert ids(handles=("user_1",), strand="s1") == [5]
    assert ids(handles=("user_1",)) == [1]
    assert ids(handles=("ext_5", "user_1")) == [1, 2]
    with pytest.raises(ValueError):
        thread_where(t)
    db.conn.close()


def test_the_private_thread_rereads_her_confirmed_addresses_only_when_the_audience_allows_it():
    """Sa seule adresse, sauf quand sa fiche est ouverte à qui écrit (``private_ok``) : alors aussi celles dont la
    liaison est confirmée (``identity.THREAD``), triées, sans doublon."""
    facts = {identity_c.THREAD("ext_5"): ("user_1", "ext_5", "phone_9"), identity_c.THREAD("ext_7"): ()}

    def frame(audience):
        return NS(audience=audience, get=lambda ref: facts[ref])

    assert identity_c.thread_handles(frame(None), "ext_5") == ("ext_5",)
    assert identity_c.thread_handles(frame(NS(private_ok=False)), "ext_5") == ("ext_5",)
    assert identity_c.thread_handles(frame(NS(private_ok=True)), "ext_5") == ("ext_5", "phone_9", "user_1")
    assert identity_c.thread_handles(frame(NS(private_ok=True)), "ext_7") == ("ext_7",)


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
