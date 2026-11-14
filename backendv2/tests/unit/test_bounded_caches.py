"""Les caches bornés de sa vie et de ses liens (``LIFE_CACHE_CAP``, ``RELATION_CACHE_CAP``) : la croissance n'efface
ni une relation active ni une date annuelle, et ce que l'éviction sort, un rappel le retrouve dans les archives."""

from __future__ import annotations

from types import SimpleNamespace as NS

from mika.contracts import memory as mc
from mika.faculties.memory.archive import LifeArchive, decode, for_people, recall_life
from mika.faculties.memory.faculty import LIFE_CACHE_CAP, MemoryState, _life_recalled, _noted
from mika.faculties.memory.projections import Items
from mika.faculties.social.archive import Relations, recall_relations
from mika.faculties.social.faculty import RELATION_CACHE_CAP, SocialState, _knit, _relations_recalled, _ties
from mika.kernel.clock import DAY
from mika.kernel.events import Content
from tests.fixtures.memory import event
from tests.fixtures.sqldb import SqlDB as DB


def test_growth_does_not_erase_active_relations_or_annual_dates():
    relations = SocialState()
    for n in range(2, 535):
        relations = _knit(relations, event(mc.BELIEVED.draft(text=Content.of("Amitié déclarée"),
            relations=(mc.Relation(subject=f"user_{n}", other="user_1", kind="friend", status="active"),),
            told_by=(f"user_{n}",)), n), None)
    assert len(relations.relations) == 533 and "user_2" in relations.relations
    state = MemoryState()
    for n in range(1, 302):
        state = _noted(state, event(mc.EVENT_NOTED.draft(text=Content.of(f"Anniversaire {n}"),
            when=100 * DAY, about=(f"user_{n}",), yearly=True), n), NS(params=None))
    assert len(state.events) == 301 and 1 in state.events


def test_life_and_relationship_archives_survive_eviction():
    db = DB()
    Items().create(db, '')
    LifeArchive().create(db, '')
    Relations().create(db, '')
    state, social = MemoryState(), SocialState()
    cx = NS(params=None, facts=NS(get=lambda key: key.arg))
    for i in range(1, LIFE_CACHE_CAP + 5):
        draft = mc.EVENT_NOTED.draft(text=Content.of(f'Anniversaire {i}'), about=(f'user_{i}',), when=100 * DAY, yearly=True)
        ev = event(draft, i)
        ev.data = ev.data.model_copy(update={'text': Content(ref=f'{i}.text', text=f'Anniversaire {i}')})
        Items().apply(db, [ev], '')
        LifeArchive().apply(db, [ev], '')
        state = _noted(state, ev, cx)
    assert len(state.events) == LIFE_CACHE_CAP and 1 not in state.events
    assert for_people(db, ('user_1',))[0].id == 1
    frame = NS(get=lambda key: () if key.name == 'identity.handles' else key.arg,
               env=NS(params_of=lambda *_: None), root=None)
    incoming = NS(at=101 * DAY, data=NS(handle='user_1'))
    drafts = recall_life(state, frame, incoming, {'store': db})
    state = _life_recalled(state, event(drafts[0], 3000), cx)
    assert 1 in state.events and len(state.events) == LIFE_CACHE_CAP
    for i in range(1, RELATION_CACHE_CAP + 5):
        draft = mc.BELIEVED.draft(text=Content.of('amitié'), told_by=(f'user_{i}',), relations=(
            mc.Relation(subject=f'user_{i}', other=f'friend_{i}', kind='friend', status='active'),))
        ev = event(draft, i)
        Relations().apply(db, [ev], '')
        social = _knit(social, ev, cx)
    assert sum(map(len, social.relations.values())) == RELATION_CACHE_CAP
    assert not _ties(social, cx, 'friend_1')
    incoming.data.handle = 'friend_1'
    drafts = recall_relations(social, frame, incoming, {'store': db})
    social = _relations_recalled(social, event(drafts[0], 4000), cx)
    assert _ties(social, cx, 'friend_1') == ('user_1',)
    assert sum(map(len, social.relations.values())) == RELATION_CACHE_CAP
    # Une fin reste vraie même si l'élément n'était plus dans la tranche.
    LifeArchive().apply(db, [event(mc.SITUATION_ENDED.draft(event=2), 5000)], '')
    assert decode(db.query('SELECT payload FROM memory_life WHERE id=2')[0][0]).ended_at
    db.conn.close()
