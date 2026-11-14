"""Les liens entre les gens (faculté ``social``) : ni une hypothèse, ni une mention, ni une coprésence ne donnent
une permission ; une relation déclarée est dirigée, attribuée, et peut finir ; oubliée, elle reste révoquée après
une reconstruction et un redémarrage, et son nom quitte les enveloppes du journal."""

from __future__ import annotations

import json
from types import SimpleNamespace as NS

from mika.contracts import memory as mc
from mika.contracts import social as sc
from mika.faculties.social.faculty import SocialState, _knit, _ties
from mika.kernel.events import Content, Origin
from mika.sim.clock import run_virtual
from tests.fixtures.memory import Script, event
from tests.fixtures.mika import boot, build, connect


def test_a_hypothesis_cannot_grant_relationship_permissions():
    draft = mc.BELIEVED.draft(text=Content.of("Alice et Bob sont peut-être amis"), knowledge_kind="hypothesis",
        about=("user_2", "user_3"), told_by=("user_2",), relations=(mc.Relation(
            subject="user_2", other="user_3", kind="friend", status="active"),))
    state = _knit(SocialState(), event(draft, 1), None)
    assert not _ties(state, NS(facts=NS(get=lambda f: f.arg)), "user_3")


def test_mention_and_copresence_never_create_a_social_permission():
    cx = NS(params=None, facts=NS(get=lambda fact: fact.arg))
    draft = mc.BELIEVED.draft(text=Content.of("Alice ne veut plus jamais voir Bob après sa trahison"),
        about=("user_2", "user_3"), told_by=("user_2",), heard_by=("user_2", "user_3"))
    state = _knit(SocialState(), event(draft, 1), cx)
    assert not _ties(state, cx, "user_2") and not _ties(state, cx, "user_3")


def test_explicit_relationship_is_directed_attributed_and_can_end():
    cx = NS(params=None, facts=NS(get=lambda fact: fact.arg))
    relation = mc.Relation(subject="user_2", other="user_3", kind="friend", status="active")
    draft = mc.BELIEVED.draft(text=Content.of("Alice considère Bob comme un ami"),
        about=("user_2", "user_3"), told_by=("user_2",), sources=(1,), relations=(relation,))
    state = _knit(SocialState(), event(draft, 2), cx)
    assert _ties(state, cx, "user_3") == ("user_2",)
    assert not _ties(state, cx, "user_2")
    ended = mc.BELIEVED.draft(text=Content.of("Alice ne considère plus Bob comme un ami"),
        about=("user_2", "user_3"), told_by=("user_2",), sources=(3,), replaces=2,
        relations=(relation.model_copy(update={"status": "ended"}),))
    state = _knit(state, event(ended, 4), cx)
    assert not _ties(state, cx, "user_3")
    assert next(iter(state.relations["user_2"].values())).sources == (3,)


def test_forgotten_relations_stay_revoked_after_rebuild_and_restart(tmp_path):
    kernel, clock, _, _ = build(tmp_path, Script())

    async def first():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await connect(kernel, "user_3", "Bob")
        await kernel.mind.append([mc.BELIEVED.draft(text=Content.of("Alice est amie avec Bob"),
            about=("user_2", "user_3"), told_by=("user_2",), sources=(1,),
            relations=(mc.Relation(subject="user_2", other="user_3", kind="friend", status="active"),))],
            emitter="memory", correlation="audit", origin=Origin.GENESIS)
        assert kernel.mind.frame().get(sc.TIES("user_3")) == ("user_2",)
        await kernel.forget("user_2")
        assert not kernel.mind.frame().get(sc.TIES("user_3"))
        await kernel.mind.rebuild(["social"])
        assert not kernel.mind.frame().get(sc.TIES("user_3"))
        await kernel.stop()

    run_virtual(clock, first)
    kernel, clock, _, _ = build(tmp_path, Script(), seed=1)

    async def again():
        await boot(kernel)
        assert not kernel.mind.frame().get(sc.TIES("user_3"))
        await kernel.stop()

    run_virtual(clock, again)


def test_forgetting_a_named_relation_removes_the_plain_name_from_envelopes(tmp_path):
    kernel, clock, _, _ = build(tmp_path, Script())
    name = 'name:scope:prénom unique'
    async def main():
        await boot(kernel)
        await connect(kernel, 'user_2', 'Alice')
        await kernel.mind.append([mc.BELIEVED.draft(text=Content.of('Connaissance confidentielle'),
            told_by=('user_2',), relations=(mc.Relation(subject='user_2', other=name, kind='friend', status='active'),))],
            emitter='memory', origin=Origin.GENESIS, correlation='review')
        await kernel.forget(name)
        assert all(name not in json.dumps(json.loads(ev.data), ensure_ascii=False) for ev in kernel.mind.store.read())
        assert not kernel.mind.store.query_mind('SELECT * FROM social_relations')
        assert not kernel.mind.store.query_mind('SELECT * FROM memory_items')
        await kernel.stop()
    run_virtual(clock, main)
