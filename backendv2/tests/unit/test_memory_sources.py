"""Ce qui naît de ses souvenirs en garde les sources : un portrait ne valide pas le contraire de ce qu'on lui a dit,
une réflexion hérite de la permission de sa confidence, deux témoignages identiques partagent une ligne et gardent
leurs deux sources."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace as NS

from mika.contracts import attention as ac
from mika.contracts import memory as mc
from mika.faculties.memory.faculty import REFLECTION_MARK, MemoryState, _retained
from mika.faculties.memory.night import Reflect, Reflection
from mika.faculties.memory.recall import Recalled, _add_recalled, verdict_of
from mika.faculties.memory.salience import Item, Verdict
from mika.faculties.social.profile import grounded
from mika.kernel.clock import DAY
from mika.kernel.events import Content, Origin
from mika.kernel.frame import Audience
from mika.sim.clock import run_virtual
from tests.fixtures.memory import Script
from tests.fixtures.mika import boot, build, connect


def test_profiles_do_not_validate_opposite_relationship_status():
    assert grounded("Alice est célibataire.", ["alice est mariee."]) == ""
    assert grounded("Alice est mariée.", ["alice est mariee."]) == "Alice est mariée."
    assert grounded("Alice est mariée.", ["alice n'est pas mariee."]) == ""


def test_reflection_inherits_its_confidants_permission(tmp_path):
    kernel, clock, _, _ = build(tmp_path, Script())

    async def main():
        await boot(kernel)
        await connect(kernel, 'user_2', 'Alice')
        await connect(kernel, 'user_3', 'Bob')
        result = await kernel.mind.append([mc.BELIEVED.draft(text=Content.of('CANARI Alice va partir'),
            about=('user_2',), told_by=('user_3',), secret=True, sensitivity=2)],
            emitter='memory', origin=Origin.GENESIS, correlation='review')
        source = result.seqs[0]
        result = await kernel.mind.append([ac.THOUGHT_BORN.draft(text=Content.of('CANARI Alice va partir'),
            about=('user_2',), emotion='sad', intensity=.8, origin='concern', source=source)],
            emitter='attention', origin=Origin.GENESIS, correlation='review')
        thought = result.seqs[0]
        state = MemoryState(reflections=(Reflection(thought, f'{thought}.text', ('user_2',), 2, 'sad'),))
        saved = []
        async def emit(*drafts):
            saved.extend(drafts)
        await Reflect().run(NS(frame=kernel.mind.frame(), state=state, ports={'store': kernel.mind.store}, emit=emit))
        d = saved[0].data
        assert not d.internal_only and d.constraints and not d.told_by
        saved_result = await kernel.mind.append(saved, emitter='memory', origin=Origin.PROCESS, correlation='review')
        from mika.faculties.memory.recall import items_by_id
        item = items_by_id(kernel.mind.store, saved_result.seqs)[saved_result.seqs[0]]
        aud = Audience(public=False, private_ok=True, level=3)
        assert not verdict_of(kernel.mind.frame(), item, 'user_2', aud, {}).ok
        assert verdict_of(kernel.mind.frame(), item, 'user_3', aud, {}).ok
        from mika.faculties.memory.night import _disclosure
        again, unknown = _disclosure(kernel.mind.frame(), kernel.mind.store, item.id)
        assert not unknown and again == item.constraints
        await kernel.stop()
    run_virtual(clock, main)


def test_the_souvenir_of_a_night_reflection_is_recognised_when_it_returns(tmp_path):
    """La nuit marque le souvenir d'une réflexion (``call_id`` : ``réflexion:<pensée>``), et son retour au journal la
    retire de ce qui reste à repenser : la marque posée est celle que la réduction relit (``REFLECTION_MARK``) —
    l'une sans l'autre, la réflexion resterait à écrire chaque nuit. La valeur est comparée au littéral, pas à la
    constante : les souvenirs déjà au journal portent ``réflexion:<pensée>``, et une constante changée des deux côtés
    à la fois ne les reconnaîtrait plus."""
    kernel, clock, _, _ = build(tmp_path, Script())

    async def main():
        await boot(kernel)
        await connect(kernel, 'user_2', 'Alice')
        result = await kernel.mind.append([ac.THOUGHT_BORN.draft(text=Content.of('Alice a perdu son chat'),
            about=('user_2',), emotion='sad', intensity=.8, origin='concern')],
            emitter='attention', origin=Origin.GENESIS, correlation='review')
        thought = result.seqs[0]
        state = MemoryState(reflections=(Reflection(thought, f'{thought}.text', ('user_2',), 1, 'sad'),))
        saved = []
        async def emit(*drafts):
            saved.extend(drafts)
        await Reflect().run(NS(frame=kernel.mind.frame(), state=state, ports={'store': kernel.mind.store}, emit=emit))
        assert REFLECTION_MARK == 'réflexion'
        assert [d.data.call_id for d in saved] == [f'réflexion:{thought}']
        back = _retained(state, NS(type=saved[0].type, data=saved[0].data, at=DAY, seq=thought + 1), NS(params=None))
        assert back.reflections == ()
        await kernel.stop()
    run_virtual(clock, main)


def test_identical_visible_claims_share_a_line_but_keep_both_sources():
    values = dict(id=1, kind=mc.BELIEF, text='Le concert est samedi.', about=('user_2',), sensitivity=0,
                  importance=.5, confidence=.7, origin='told', source=None, emotion=None,
                  born_at=DAY, touched_at=DAY, recalled_at=0, recalls=0, status='active')
    first = Item(**values, told_by=('user_3',))
    second = replace(first, id=2, told_by=('user_4',))
    bucket = []
    for item in (first, second):
        _add_recalled(bucket, Recalled(item, Verdict(True), item.text), 5)
    assert len(bucket) == 1 and bucket[0].evidence == (1, 2)
