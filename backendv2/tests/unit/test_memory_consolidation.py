"""Ce qu'un témoignage devient dans sa mémoire (``memory.consolidation``) : un secret ne passe pas à un autre par
ressemblance, une négation remplace l'affirmation, un autre informateur ne remplace pas le premier, les doublons
se reconnaissent, un avis garde qui le porte (et part avec lui à l'oubli), les siens restent des avis ; et une
extraction en panne n'arrête pas la consolidation, qui reprend après un redémarrage."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest

from mika.adapters.vectors import HashEmbedder, SqliteVectorIndex
from mika.contracts import memory as mc
from mika.faculties.memory import consolidation as cons
from mika.faculties.memory.consolidation import Consolidate, Index, _item_vector
from mika.faculties.memory.extraction import Conversation, Extraction, Line, People, Speaker, XCroyance
from mika.faculties.memory.faculty import MemoryParams, MemoryState
from mika.faculties.memory.projections import DEFERRED_TABLE, ITEM_COLUMNS, Chunks, Items
from mika.faculties.memory.salience import Item, admissible
from mika.kernel.clock import DAY
from mika.kernel.events import Content, Origin
from mika.kernel.frame import Audience
from mika.sim.clock import run_virtual
from mika.vocab.people import named_label
from tests.fixtures.memory import Script, event
from tests.fixtures.mika import boot, build, connect, said
from tests.fixtures.sqldb import SqlDB as DB


@pytest.fixture
def db():
    db = DB()
    Items().create(db, "")
    Chunks().create(db, "")
    yield db
    db.conn.close()


async def drafts_for(db, text, *, teller="user_2", old=None, genre=None):
    vectors = SqliteVectorIndex(db, HashEmbedder())
    await vectors.open()
    fresh, _ = Index()._fresh(db)
    await vectors.upsert(fresh)
    frame = NS(now=2 * DAY, root=None,
        get=lambda fact: NS(name="Mika") if fact.name == "self.persona" else (),
        env=NS(tz_of=lambda root: ZoneInfo("Europe/Paris")))
    name = "Alice" if teller == "user_2" else "Bob"
    speakers = (Speaker("P1", teller, name),)
    conv = Conversation(f"private:{teller}", speakers, (Line(101, 2 * DAY, name, text, teller),))
    people = People.of(speakers, {"alice": ("user_2",)}, "Mika")
    ex = Extraction(croyances=[XCroyance(texte=text, personnes=["Alice"], messages=[101],
                                        remplace=old[0] if old else None, genre=genre)])
    return await cons._drafts(ex, frame, MemoryState(), db, conv, people, [old] if old else [],
                              [], vectors, MemoryParams(), "audit")


async def test_semantic_similarity_cannot_give_bob_alices_secret(db):
    original = ("Alice prépare son installation dans un nouvel appartement à Nantes pour novembre, "
                "avec son chat, ses meubles, ses livres et son matériel de dessin. "
                "Elle organise les cartons, réserve le camion et prévoit de repeindre la cuisine, "
                "le salon et la chambre avant de recevoir ses amis pour la crémaillère. Son salaire est 7200 euros.")
    Items().apply(db, [event(mc.BELIEVED.draft(text=Content.of(original), about=("user_2",),
        told_by=("user_2",), heard_by=("user_2",), secret=True, sensitivity=3), 1)], "")
    drafts = await drafts_for(db, original.split(" Son salaire")[0], teller="user_3")
    assert len(drafts) == 1 and drafts[0].type == mc.BELIEVED
    Items().apply(db, [event(drafts[0], 2)], "")
    row = db.query(f"SELECT {','.join(f'`{c}`' for c in ITEM_COLUMNS)} FROM memory_items WHERE id=1")[0]
    item = Item.of(dict(zip(ITEM_COLUMNS, row, strict=True)))
    audience = Audience(persons=("user_3",), public=False, level=1, witness_level=2, private_ok=True)
    assert not admissible(item.about, item.sensitivity, "user_3", audience,
                          told_by=item.told_by, heard_by=item.heard_by, secret=item.secret).ok


async def test_explicit_negation_replaces_the_positive_claim(db):
    old, new = "Alice habite à Lyon", "Alice n'habite plus à Lyon"
    Items().apply(db, [event(mc.BELIEVED.draft(text=Content.of(old), about=("user_2",),
        told_by=("user_2",), heard_by=("user_2",)), 1)], "")
    drafts = await drafts_for(db, new, old=(1, old))
    Items().apply(db, [event(drafts[0], 2)], "")
    assert db.query("SELECT text,status FROM memory_items ORDER BY id") == [(old, "superseded"), (new, "active")]


async def test_another_informant_cannot_replace_the_first_informants_claim(db):
    old = "Alice habite à Lyon"
    Items().apply(db, [event(mc.BELIEVED.draft(text=Content.of(old), about=("user_2",),
        told_by=("user_2",), heard_by=("user_2",), holder="user_2"), 1)], "")
    drafts = await drafts_for(db, "Alice n'habite plus à Lyon", teller="user_3", old=(1, old))
    assert drafts[0].data.replaces is None


async def test_exact_deduplication_survives_many_confidants_without_vector_candidates(db):
    text = "Alice habite à Lyon"
    Items().apply(db, [event(mc.BELIEVED.draft(text=Content.of(text), about=("user_2",),
        told_by=(f"user_{i}",), heard_by=(f"user_{i}",), holder=f"user_{i}"), i) for i in range(1, 101)], "")
    item = await cons.twin_of(db, None, text, mc.BELIEF, ("user_2",), MemoryParams(),
                              told_by=("user_100",), heard_by=("user_100",), holder="user_100")
    # la même proposition, quel qu'en soit le témoin (ADR 0080) : la plus ancienne — un fait rapporté n'est à
    # personne, son porteur d'avant (le témoin) ne la sépare plus
    assert item == 1


def test_legacy_night_merge_cannot_erase_a_negation(db):
    a = mc.REMEMBERED.draft(text=Content.of("Alice aime le café"), about=("user_2",))
    b = mc.REMEMBERED.draft(text=Content.of("Alice n'aime pas le café"), about=("user_2",))
    Items().apply(db, [event(a, 1), event(b, 2), event(mc.NIGHT_SORTED.draft(night="2026-10-08",
                                                                        merges=((1, 2),)), 3)], "")
    assert db.query("SELECT status FROM memory_items ORDER BY id") == [("active",), ("active",)]


async def test_an_opinion_keeps_its_holder_distinct_from_its_subject(db):
    drafts = await drafts_for(db, "Bob pense qu'Alice devrait quitter son travail", teller="user_3", genre="avis")
    data = drafts[0].data
    # Bob, seul avec Mika, nomme « Alice » : une mention (présumée être Alice, ADR 0075), pas Bob lui-même
    assert data.knowledge_kind == "opinion" and data.holder == "user_3"
    assert len(data.about) == 1 and named_label(data.about[0]) == "alice"
    Items().apply(db, [event(drafts[0], 1)], "")
    assert db.query("SELECT knowledge_kind,holder FROM memory_items") == [("opinion", "user_3")]


@pytest.mark.parametrize("genre,nature", [("avis", "opinion"), ("gout", "preference"), ("fait", "claim")])
async def test_her_own_opinions_are_not_reclassified_as_facts(db, genre, nature):
    drafts = cons._about_self(XCroyance(texte="Mika aime le jazz", genre=genre, sur_elle=True),
        db, lambda _: ((1,), (), []), "audit-self", set())
    assert drafts[0].data.knowledge_kind == nature and drafts[0].data.about_self and drafts[0].data.durable


def test_forgetting_the_holder_erases_an_indirectly_reported_opinion(db):
    Items().apply(db, [event(mc.BELIEVED.draft(text=Content.of("Avis de Carol sur Alice, rapporté par Bob"),
        about=("user_2",), told_by=("user_3",), holder="user_4", knowledge_kind="opinion"), 1)], "")
    raw = db.query(f"SELECT {','.join(f'`{c}`' for c in ITEM_COLUMNS)} FROM memory_items")[0]
    assert "user_4" in _item_vector(dict(zip(ITEM_COLUMNS, raw, strict=True))).persons
    Items().forget(db, "user_4", "")
    assert db.query("SELECT id FROM memory_items") == []


def test_failed_extraction_progresses_and_retries_after_restart(tmp_path):
    class Failing(Script):
        def __call__(self, req):
            if req.role == 'extract':
                raise RuntimeError('provider unavailable')
            return super().__call__(req)
    kernel, clock, _, _ = build(tmp_path, Failing())

    async def first():
        await boot(kernel)
        await connect(kernel, 'user_2', 'Alice')
        for i in range(6):
            result = await kernel.perceive(said('user_2', f'Je plante des roses {i}'))
            await result.reply
        await asyncio.sleep(15 * 60)
        # Une panne passagère : la fenêtre attend d'un seul tenant, rien n'est encore mis en file.
        assert not kernel.mind.store.query_mind(f'SELECT `key` FROM {DEFERRED_TABLE}')
        assert kernel.mind.root.slices['memory'].pending
        await asyncio.sleep(2 * 60 * 60)
        # Au-delà de max_attempts passages, elle part en file et la consolidation avance.
        rows = kernel.mind.store.query_mind(f'SELECT `key`,attempts,retry_at FROM {DEFERRED_TABLE}')
        assert rows and max(row[1] for row in rows) >= 2
        assert kernel.mind.root.slices['memory'].checkpoint > rows[0][0]
        assert not kernel.mind.root.slices['memory'].pending
        await kernel.stop()
    run_virtual(clock, first)
    kernel, clock, _, _ = build(tmp_path, Script())

    async def again():
        await boot(kernel)
        rows = kernel.mind.store.query_mind(f'SELECT retry_at FROM {DEFERRED_TABLE}')
        assert rows
        # Les heures de reprise sont persistées ; un processus neuf ne remet pas le compteur à zéro.
        clock.advance_to(max(row[0] for row in rows))
        process = Consolidate()
        async def emit(*drafts, **kw):
            await kernel.mind.append(list(drafts), emitter='memory', correlation='review', origin=Origin.PROCESS)
        for _ in rows:
            await process.run(NS(frame=kernel.mind.frame(), state=kernel.mind.root.slices['memory'],
                                ports={'store': kernel.mind.store}, llm=kernel.deps.gateway, run_id='review', emit=emit))
        assert not kernel.mind.store.query_mind(f'SELECT `key` FROM {DEFERRED_TABLE}')
        await kernel.stop()
    run_virtual(clock, again)
