"""Contre-exemples de l'audit : sources, contradictions, identité, contexte et croissance."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import insert

from mika.adapters.llm.config import BackendSpec, LLMConfig, build_gateway
from mika.adapters.vectors import HashEmbedder, SqliteVectorIndex
from mika.contracts import memory as mc
from mika.contracts import social as sc
from mika.contracts.transcript import thread_table
from mika.faculties.memory.consolidation import Consolidate, Index, _item_vector
from mika.faculties.memory.extraction import Conversation, Extraction, Line, People, Speaker, XCroyance, parse
from mika.faculties.memory.faculty import MemoryParams, MemoryState, _noted
from mika.faculties.memory.projections import ITEM_COLUMNS, Chunks, Items
from mika.faculties.memory.salience import Item, admissible
from mika.faculties.social.faculty import SocialState, _knit, _ties
from mika.faculties.social.profile import grounded
from mika.faculties.transcript import Thread, TranscriptParams, TranscriptState, _thread
from mika.kernel.clock import DAY, ManualClock
from mika.kernel.events import Content, Origin
from mika.kernel.faculty import SectionSpec, Zone
from mika.kernel.frame import Audience
from mika.kernel.prompt import Budget, ChatTurn, Composer, Fragment, PromptBudgetError, SectionBody
from mika.ports.llm import LLMRequest, LLMResponse, Message, ToolCall
from mika.ports.llm_budget import LLMLimits
from mika.ports.vectors import VectorItem
from mika.sim.clock import run_virtual
from mika.vocab.people import named_label
from tests.fixtures.memory import Script
from tests.fixtures.mika import boot, build, connect
from tests.fixtures.sqldb import SqlDB


class DB(SqlDB):
    """Une base en mémoire derrière le port ``Sql`` (``tests.fixtures.sqldb``)."""


@pytest.fixture
def db():
    db = DB()
    Items().create(db, "")
    Chunks().create(db, "")
    yield db
    db.conn.close()


def event(draft, seq, at=DAY):
    return NS(type=draft.type, data=draft.data, seq=seq, at=at)


def spec(key, zone, **kw):
    return SectionSpec("probe", key, zone, frozenset({"REPLY"}), lambda *a: None, **kw)


def compose(blocks, budget=1000, message="Bonjour"):
    return Composer().compose(blocks, kind="REPLY", audience_level=3,
        muted_tags=frozenset(), message=message, budget=Budget(max_tokens=budget, chars_per_token=1.0))


def test_names_are_exact_and_unknown_mentions_are_scoped():
    alice = People.of([Speaker("P1", "user_2", "Alice Dupont")], {})
    bob = People.of([Speaker("P1", "user_3", "Bob")], {})
    assert alice.one("Alice") == alice.one("Alice Dupont") == "user_2"
    assert alice.one("Alice Martin") != "user_2"
    assert alice.one("Alex") != bob.one("Alex")
    assert alice.one("Alex") == People.of([Speaker("P9", "user_2", "Alice Dupont")], {}).one("Alex")


@pytest.mark.parametrize("text", ['{"error":"context too long"}',
                                  '{"souvenirs":42}', '{}'])
def test_invalid_extraction_never_validates_a_window(text):
    assert parse(LLMResponse(text)) is None


def test_explicit_empty_tool_result_is_valid_but_truncated_result_is_not():
    response = LLMResponse("", tool_calls=(ToolCall("x", "record_memories", {}),), stop="tool_use")
    assert parse(response) == Extraction()
    assert parse(replace(response, stop="max_tokens")) is None


@pytest.mark.parametrize("blocks,message", [
    ([(spec("history", Zone.HISTORY), SectionBody((ChatTurn("user", "Résumé " * 400, pinned=True),)))], "Bonjour"),
    ([(spec("identity", Zone.VOLATILE, floor_chars=400), SectionBody("Identité et situation. " * 25))], "x" * 950),
])
def test_pins_and_floors_cannot_overrun_provider_budget(blocks, message):
    prompt, trace = compose(blocks, message=message)
    assert prompt.chars() <= 1000 and trace.chars == prompt.chars()


def test_partial_memory_sections_keep_only_the_sources_of_whole_facts():
    fragments = (Fragment("- Premier fait anodin.", ("memory:1",)),
                 Fragment("- CANARI_SECOND " + "information " * 300, ("memory:2",)))
    prompt, trace = compose([(spec("memories", Zone.VOLATILE), SectionBody(
        "\n".join(f.text for f in fragments), provenance=("memory:1", "memory:2"), fragments=fragments))], 120)
    assert "CANARI_SECOND" not in prompt.system_volatile
    assert trace.provenance == ("memory:1",)


def test_exchange_deduplication_uses_history_after_budget_trimming():
    fragment = Fragment("Souvenir du rendez-vous", ("chunk:2",), (1, 2))
    blocks = [(spec("history", Zone.HISTORY), SectionBody((ChatTurn("user", "question " * 60, id=1),
                                                         ChatTurn("assistant", "réponse " * 60, id=2)))),
              (spec("recall", Zone.VOLATILE), SectionBody(fragment.text, provenance=fragment.provenance,
                                                        fragments=(fragment,)))]
    large, trace = compose(blocks, 3000)
    assert not large.system_volatile and not trace.provenance
    small, trace = compose(blocks, 300)
    assert "rendez-vous" in small.system_volatile and trace.provenance == ("chunk:2",)


async def test_default_history_covers_the_gap_before_first_compaction(db):
    Thread().create(db, "")
    db.execute(insert(thread_table()), [{"id": i, "at": DAY + i, "role": "user", "person": "user_2",
                                         "text": f"Message {i}", "folded": f"message {i}"} for i in range(1, 62)])
    frame = NS(episode=NS(target="user_2", attrs={}), audience=None, root=None, now=DAY + 62,
               env=NS(params_of=lambda *a: TranscriptParams(), tz_of=lambda *a: ZoneInfo("UTC")))
    view = await _thread(TranscriptState(), frame, {"store": db})
    assert [t.id for t in view.turns] == list(range(1, 62))


def test_history_protocol_overhead_is_reserved_only_for_rendered_turns():
    turns = tuple(ChatTurn("user", "message " * 60, id=i) for i in range(1000))
    budget = Budget(2000, chars_per_token=1, message_overhead=16)
    prompt, trace = Composer().compose([(spec("history", Zone.HISTORY), SectionBody(turns))],
        kind="REPLY", audience_level=3, muted_tags=frozenset(), message="Bonjour", budget=budget, reserved=96)
    assert prompt.history and prompt.chars() + trace.reserved <= budget.max_chars


def test_valid_extraction_does_not_drop_promises_above_the_old_cap():
    raw = {"promesses": [{"texte": f"Promesse numéro {i}", "envers": "Alice"} for i in range(20)]}
    assert len(parse(LLMResponse(json.dumps(raw))).promesses) == 20


def test_profiles_do_not_validate_opposite_relationship_status():
    assert grounded("Alice est célibataire.", "alice est mariee.") == ""
    assert grounded("Alice est mariée.", "alice est mariee.") == "Alice est mariée."
    assert grounded("Alice est mariée.", "alice n'est pas mariee.") == ""


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
    return await Consolidate()._drafts(ex, frame, MemoryState(), db, conv, people, [old] if old else [],
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
    row = db.query(f"SELECT {','.join(ITEM_COLUMNS)} FROM memory_items WHERE id=1")[0]
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
    item = await Consolidate()._twin(db, None, text, mc.BELIEF, ("user_2",), MemoryParams(),
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
    drafts = Consolidate()._about_self(XCroyance(texte="Mika aime le jazz", genre=genre, sur_elle=True),
        db, lambda _: ((1,), (), []), "audit-self", set())
    assert drafts[0].data.knowledge_kind == nature and drafts[0].data.about_self and drafts[0].data.durable


def test_forgetting_the_holder_erases_an_indirectly_reported_opinion(db):
    Items().apply(db, [event(mc.BELIEVED.draft(text=Content.of("Avis de Carol sur Alice, rapporté par Bob"),
        about=("user_2",), told_by=("user_3",), holder="user_4", knowledge_kind="opinion"), 1)], "")
    raw = db.query(f"SELECT {','.join(ITEM_COLUMNS)} FROM memory_items")[0]
    assert "user_4" in _item_vector(dict(zip(ITEM_COLUMNS, raw, strict=True))).persons
    Items().forget(db, "user_4", "")
    assert db.query("SELECT id FROM memory_items") == []


def test_a_hypothesis_cannot_grant_relationship_permissions():
    draft = mc.BELIEVED.draft(text=Content.of("Alice et Bob sont peut-être amis"), knowledge_kind="hypothesis",
        about=("user_2", "user_3"), told_by=("user_2",), relations=(mc.Relation(
            subject="user_2", other="user_3", kind="friend", status="active"),))
    state = _knit(SocialState(), event(draft, 1), None)
    assert not _ties(state, NS(facts=NS(get=lambda f: f.arg)), "user_3")


async def test_superseded_versions_cannot_fill_all_search_results(db):
    Items().apply(db, [event(mc.BELIEVED.draft(text=Content.of("Alice habite à Lyon"), about=("user_2",),
        replaces=i - 1 if i > 1 else None), i) for i in range(1, 102)], "")
    vectors = SqliteVectorIndex(db, HashEmbedder())
    await vectors.open()
    todo, _ = Index()._fresh(db)
    await vectors.upsert(todo)
    assert [k for k, _ in await vectors.search("Alice habite à Lyon", 40)] == [101]


async def test_disk_search_matches_ram_and_removes_only_replaced_rows(db):
    ram = SqliteVectorIndex(db, HashEmbedder(), table="ram_vectors")
    disk = SqliteVectorIndex(db, HashEmbedder(), table="disk_vectors", max_resident_vectors=10)
    for index in (ram, disk):
        await index.open()
        await index.upsert([VectorItem(i, "belief", f"Alice cultive des roses numéro {i}", (f"user_{i % 3}",))
                            for i in range(1, 2061)])  # trois blocs sur disque, avec des ex æquo entre blocs
    assert disk._spilled and disk._mat.size == 0
    for filters in ({}, {"persons": ["user_2"]}, {"keys": [1, 4, 10, 1024, 2048]}, {"kinds": ["souvenir"]}):
        left = await ram.search("roses numéro 10", 8, **filters)
        right = await disk.search("roses numéro 10", 8, **filters)
        assert [i for i, _ in left] == [i for i, _ in right]
        assert [s for _, s in left] == pytest.approx([s for _, s in right], abs=1e-6)
    assert ram.digest() == disk.digest()
    for index in (ram, disk):
        await index.remove([1, 3, 59])
        await index.forget("user_2")
    assert ram.indexed() == disk.indexed() and ram.digest() == disk.digest()
    loaded = SqliteVectorIndex(db, HashEmbedder(), table="disk_vectors", max_resident_vectors=10)
    await loaded.open()
    assert loaded._spilled and loaded._mat.size == 0 and loaded.digest() == disk.digest()


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


def test_provider_budgets_migrate_without_overwriting_explicit_values():
    cfg = LLMConfig.model_validate({"context_tokens": 32000, "backends": {
        "a": {"kind": "openai", "model": "a"},
        "b": {"kind": "ollama", "model": "b", "context_tokens": 8000}}})
    assert cfg.backends["a"].context_tokens == 32000 and cfg.backends["b"].context_tokens == 8000
    assert "context_tokens" not in cfg.model_dump()


def test_provider_budget_counts_tools_and_preserves_tool_call_pairs():
    limits = LLMLimits(2000, 300, 1.0)
    req = LLMRequest("reply", "call", "system", max_tokens=700,
        messages=(Message("user", "question"), Message("assistant", tool_calls=(ToolCall("id", "search", {}),)),
                  Message("tool", "x" * 9000, tool_call_id="id", name="search")))
    fitted = limits.fit(req)
    assert fitted.max_tokens == 300 and limits.size(fitted) <= 1700
    assert fitted.messages[-1].tool_call_id == "id" and "abrégé" in fitted.messages[-1].content
    with pytest.raises(PromptBudgetError):
        limits.fit(replace(req, messages=(Message("user", "x" * 9000),)))


async def test_routing_uses_each_providers_budget_and_never_switches_on_failure():
    class Backend:
        def __init__(self, name):
            self.name, self.requests = name, []

        async def complete(self, req):
            self.requests.append(req)
            if self.name == "main":
                raise RuntimeError("unavailable")
            return LLMResponse("ok")

    cfg = LLMConfig(backends={
        "main": BackendSpec(kind="openai", model="a", context_tokens=8000, fallback="small"),
        "small": BackendSpec(kind="openai", model="b", context_tokens=2000, max_output_tokens=100, chars_per_token=1)},
        routes={"extract": "small", "reply": "main", "validate": "main"})
    gateway = build_gateway(cfg, ManualClock(0), make=lambda n, s: Backend(n))
    assert gateway.budget("reply", 1000).max_tokens == 7000
    assert gateway.budget("extract", 1000).max_tokens == 1900
    req = LLMRequest("validate", "test", "system", messages=(Message("user", "x" * 4000),))
    with pytest.raises(RuntimeError, match="unavailable"):
        await gateway.call(req)
    assert len(gateway.backends["main"].requests) == 1 and not gateway.backends["small"].requests
