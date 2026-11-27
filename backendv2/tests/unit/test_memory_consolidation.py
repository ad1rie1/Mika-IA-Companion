"""Ce qu'un témoignage devient dans sa mémoire (``memory.consolidation``) : un secret ne passe pas à un autre par
ressemblance, les secrets d'une conversation sont connus avant sa première étape, une promesse n'est une confidence
que si elle laisse deviner un secret, une négation remplace l'affirmation, un autre informateur ne remplace pas le
premier, les doublons se reconnaissent, un avis garde qui le porte (et part avec lui à l'oubli), les siens restent
des avis ; et une extraction en panne n'arrête pas la consolidation, qui reprend après un redémarrage."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete

from mika.adapters.vectors import HashEmbedder, SqliteVectorIndex
from mika.contracts import memory as mc
from mika.faculties.memory import kept, testimonies
from mika.faculties.memory import tables as tb
from mika.faculties.memory.consolidation import Consolidate
from mika.faculties.memory.conversation import Conversation, Line, Speaker
from mika.faculties.memory.extraction import Extraction, XCroyance, XPromesse, XSouvenir
from mika.faculties.memory.faculty import MemoryParams, MemoryState
from mika.faculties.memory.index import Index, _item_vector
from mika.faculties.memory.projections import Chunks, Items
from mika.faculties.memory.salience import Item, admissible
from mika.faculties.memory.speakers import People
from mika.faculties.memory.tables import DEFERRED_TABLE, ITEM_COLUMNS
from mika.kernel.clock import DAY, HOUR
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
    return await kept._drafts(ex, frame, MemoryState(), db, conv, people, [old] if old else [],
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


HUSHED = "Alice démissionne de son agence en mars"


def hushed_thread():
    """Un fil privé : Alice confie sa démission en demandant le silence, puis parle d'autre chose ; Mika promet."""
    frame = NS(now=2 * DAY, root=None,
        get=lambda fact: NS(name="Mika") if fact.name == "self.persona" else (),
        env=NS(tz_of=lambda root: ZoneInfo("Europe/Paris")))
    speakers = (Speaker("P1", "user_2", "Alice"),)
    conv = Conversation("private:user_2", speakers, (
        Line(101, 2 * DAY, "Alice", "Je démissionne de mon agence en mars, garde ça pour toi", "user_2"),
        Line(102, 2 * DAY + 1, "Alice", "Tu me rappelles la recette du gratin demain ?", "user_2"),
        Line(103, 2 * DAY + 2, "Mika", "Promis, je te la rappelle demain", None)))
    return frame, conv, People.of(speakers, {"alice": ("user_2",)}, "Mika")


def test_the_secrets_of_a_conversation_are_known_before_its_first_step(db):
    # le souvenir, relu avant la croyance, ne cite pas la demande de silence : il laisse deviner le secret qu'elle
    # porte, connu d'avance (``KeepContext.of``)
    frame, conv, people = hushed_thread()
    told = "Alice m'a parlé de sa démission de l'agence"
    ex = Extraction(souvenirs=[XSouvenir(texte=told, personnes=["Alice"], messages=[102])],
                    croyances=[XCroyance(texte=HUSHED, personnes=["Alice"], messages=[101])])
    k = kept.KeepContext.of(ex, frame, db, conv, people)
    assert k.secrets == [HUSHED]
    _sources, _told_by, cited = k.provenance([102])
    assert not k.asked_silence(False, cited, 1) and k.secret_of(False, cited, 1, told)


async def test_a_promise_is_a_confidence_only_when_it_lets_a_secret_be_guessed(db):
    # pas quand on a demandé le silence ailleurs dans la conversation : ``echoes_secret``, la moitié de ``secret_of``
    frame, conv, people = hushed_thread()
    gratin, departure = "Rappeler à Alice la recette du gratin", "Demander à Alice où en est sa démission de l'agence"
    k = kept.KeepContext.of(Extraction(croyances=[XCroyance(texte=HUSHED, personnes=["Alice"], messages=[101])]),
                            frame, db, conv, people)
    assert k.secret_of(False, [], 3, gratin) and not k.echoes_secret(gratin) and k.echoes_secret(departure)
    ex = Extraction(croyances=[XCroyance(texte=HUSHED, personnes=["Alice"], messages=[101])],
                    promesses=[XPromesse(texte=gratin, envers="Alice", messages=[103]),
                               XPromesse(texte=departure, envers="Alice", messages=[103])])
    out = await kept._drafts(ex, frame, MemoryState(), db, conv, people, [], [], None, MemoryParams(), "audit")
    promised = {d.data.text.text: d.data.sensitivity for d in out if d.type == mc.PROMISE_NOTICED}
    assert promised == {gratin: 2, departure: 3}


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


def test_exact_deduplication_survives_many_confidants_without_vector_candidates(db):
    text = "Alice habite à Lyon"
    Items().apply(db, [event(mc.BELIEVED.draft(text=Content.of(text), about=("user_2",),
        told_by=(f"user_{i}",), heard_by=(f"user_{i}",), holder=f"user_{i}"), i) for i in range(1, 101)], "")
    item = testimonies.twin_of(db, text, mc.BELIEF, ("user_2",), told_by=("user_100",), heard_by=("user_100",),
                        holder="user_100")
    # la même proposition, quel qu'en soit le témoin (ADR 0080) : la plus ancienne — un fait rapporté n'est à
    # personne, son porteur d'avant (le témoin) ne la sépare plus
    assert item == 1


def test_an_empty_key_does_not_hide_the_exact_twin(db):
    """La projection range les listes sans clé vide (``keys_json``) : le doublon exact les compare écrites de même —
    une clé vide dans ce qui arrive ne fait plus naître une seconde ligne de la même croyance, ni du même
    souvenir."""
    Items().apply(db, [event(mc.BELIEVED.draft(text=Content.of("Alice habite à Lyon"), about=("user_2",),
                                               told_by=("user_2",), heard_by=("user_2",)), 1),
                       event(mc.REMEMBERED.draft(text=Content.of("Alice a vu Bob au concert"), about=("user_2",),
                                                 told_by=("user_2",), heard_by=("user_2",)), 2)], "")
    assert testimonies.twin_of(db, "Alice habite à Lyon", mc.BELIEF, ("user_2", "")) == 1
    assert testimonies.twin_of(db, "Alice a vu Bob au concert", mc.EPISODE_MEMORY, ("", "user_2"), told_by=("user_2", ""),
                        heard_by=("user_2",)) == 2


async def test_reconcile_drops_the_vectors_of_what_was_forgotten(db):
    """L'index n'est qu'un cache : une ligne que l'oubli a effacée perd son vecteur au rapprochement suivant — par
    le ``remove`` que le port déclare, attendu."""
    Items().apply(db, [event(mc.BELIEVED.draft(text=Content.of(text), about=("user_2",), told_by=("user_2",),
                                               heard_by=("user_2",)), i)
                       for i, text in ((1, "Alice habite à Lyon"), (2, "Alice joue du violon"))], "")
    vectors = SqliteVectorIndex(db, HashEmbedder())
    await vectors.open()
    await vectors.upsert(Index()._fresh(db)[0])
    assert vectors.indexed() == {1, 2}
    db.execute(delete(tb.items()).where(tb.items().c.id == 2))
    todo, upto = await Index._reconcile(vectors, db)
    assert vectors.indexed() == {1} and todo == [] and upto == (1, 0)


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
    drafts = kept._about_self(XCroyance(texte="Mika aime le jazz", genre=genre, sur_elle=True),
        db, lambda _: ((1,), (), []), "audit-self", set())
    assert drafts[0].data.knowledge_kind == nature and drafts[0].data.about_self and drafts[0].data.durable


def test_forgetting_the_holder_erases_an_indirectly_reported_opinion(db):
    Items().apply(db, [event(mc.BELIEVED.draft(text=Content.of("Avis de Carol sur Alice, rapporté par Bob"),
        about=("user_2",), told_by=("user_3",), holder="user_4", knowledge_kind="opinion"), 1)], "")
    raw = db.query(f"SELECT {','.join(f'`{c}`' for c in ITEM_COLUMNS)} FROM memory_items")[0]
    assert "user_4" in _item_vector(dict(zip(ITEM_COLUMNS, raw, strict=True))).persons
    Items().forget(db, "user_4", "")
    assert db.query("SELECT id FROM memory_items") == []


def test_consolidation_never_takes_a_conversation_received_elsewhere(tmp_path):
    """La file des reprises sert aussi aux conversations reçues ailleurs (ADR 0224) : leurs messages ne sont pas dans
    le fil, la consolidation n'en prend aucune — ni pour la relire, ni pour régler son prochain réveil."""
    script = Script()
    kernel, clock, _, _ = build(tmp_path, script)

    async def main():
        await boot(kernel)
        kernel.scheduler.stop()  # seule la consolidation menée à la main lit la file
        await kernel.scheduler.cancel_all()
        later = kernel.mind.frame().now + HOUR
        detail = Content.of('{"issues": ["RuntimeError"], "output": ""}', level=3)
        await kernel.mind.append([
            mc.EXTRACTION_DEFERRED.draft(key=7, source=mc.FROM_RELAYED, messages=(7,), about=("user_1",),
                                         failure_code="provider_error", detail=detail),
            mc.EXTRACTION_DEFERRED.draft(key=9, messages=(9,), about=("user_2",), retry_at=later,
                                         failure_code="provider_error", detail=detail)],
            emitter="memory", correlation="file", origin=Origin.PROCESS)
        emitted = []

        async def emit(*drafts, **kw):
            emitted.extend(drafts)
        process = Consolidate()
        await process.run(NS(frame=kernel.mind.frame(), state=kernel.mind.root.slices["memory"],
                             ports={"store": kernel.mind.store}, llm=kernel.deps.gateway, run_id="file", emit=emit))
        rows = kernel.mind.store.query_mind(f"SELECT `key`, source, status FROM {DEFERRED_TABLE} ORDER BY `key`")
        await kernel.stop()
        return emitted, [tuple(r) for r in rows], process.next_job_at, later

    emitted, rows, next_job_at, later = run_virtual(clock, main)
    assert rows == [(7, "relayed", "queued"), (9, "thread", "queued")]
    assert not [d for d in emitted if d.type.name == mc.EXTRACTION_DEFERRED.name]  # la sienne n'est pas due
    assert not [r for r in script.calls if r.role == "extract"]
    assert next_job_at == later  # la sienne, pas celle du téléphone, due depuis longtemps


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
