"""Contre-exemples de l'audit de la mémoire du 2026-10-08 : ce qu'elle croit savoir, de qui elle le tient, et devant
qui elle peut le redire.

- un secret ne sort que devant qui l'a confié : répondre à la personne qui l'a confié, dans un salon, ne suffit pas ;
- un lien du graphe suit la croyance d'où il vient : devenue secrète, remplacée, il ne revient pas au rechargement ;
- une situation finie qui revient est une récidive, et deux moments à deux dates ne s'écrasent pas sur une
  ressemblance ;
- la console relie la mention exacte dont on lui a parlé, et une mention d'ailleurs ne rend pas un prénom ambigu ;
- des souvenirs que l'audience ne peut pas entendre n'étouffent pas ceux qu'elle peut ;
- ce que d'autres disent d'elle n'est pas ce qu'elle raconte d'elle, et son secret à elle le reste ;
- chercher parmi quelques clés ne lit pas toute la mémoire.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

from mika.adapters.vectors import HashEmbedder, SqliteVectorIndex
from mika.contracts import identity as identity_c
from mika.contracts import memory as mc
from mika.contracts import social as sc
from mika.faculties.memory.archive import LifeArchive
from mika.faculties.memory.consolidation import Consolidate
from mika.faculties.memory.extraction import (
    Conversation,
    Extraction,
    Line,
    People,
    Speaker,
    XCroyance,
    XEvenement,
    mention_scope,
)
from mika.faculties.memory.faculty import MEMORY, MemoryParams, MemoryState
from mika.faculties.memory.projections import Chunks, Items
from mika.faculties.memory.recall import _body, _recall, named_people
from mika.faculties.memory.salience import admissible
from mika.faculties.memory.tools import SearchArgs, memory_search
from mika.faculties.social.archive import Relations, recall_relations
from mika.faculties.social.faculty import SOCIAL, SocialState, _knit, _relations_recalled, _ties
from mika.faculties.transcript import Thread
from mika.kernel.clock import DAY
from mika.kernel.events import Content, Origin
from mika.kernel.frame import Audience
from mika.ports.vectors import VectorItem
from mika.runtime.operations import FIXED_FIELD, perform
from mika.vocab.privacy import Sensitivity
from tests.fixtures.mika import connect, said
from tests.unit.test_audit_regressions import DB, event
from tests.unit.test_identity_security import form, run, say

NAMES = {"user_2": "Alice", "user_3": "Bob", "user_4": "Carol", "user_5": "Inès"}


def _subscribed(faculty, table: str) -> frozenset[str]:
    """Les événements qu'un projecteur reçoit, tels qu'il les déclare : le magasin de test projette comme le noyau."""
    return next(spec.types for spec in faculty.projectors if spec.name == table)


LIFE_TYPES = _subscribed(MEMORY, mc.LIFE_TABLE)
RELATION_TYPES = _subscribed(SOCIAL, sc.RELATIONS_TABLE)


class Store(DB):
    """Le magasin de la mémoire et du graphe, en mémoire vive, projeté comme le noyau le projette."""

    def __init__(self):
        super().__init__()
        self.texts: dict[str, str] = {}
        for cls in (Items, Chunks, LifeArchive, Relations, Thread):
            cls().create(self, "")

    def content(self, refs):
        return {r: self.texts.get(r) for r in refs}

    def put(self, draft, seq, at=DAY):
        e = event(draft, seq, at)
        if hasattr(e.data, "text"):
            text = e.data.text.text
            ref = f"{seq}.text"
            self.texts[ref] = text
            e.data = e.data.model_copy(update={"text": Content(ref=ref, text=text)})
        Items().apply(self, [e], "")
        if e.type.name in LIFE_TYPES:
            LifeArchive().apply(self, [e], "")
        if e.type.name in RELATION_TYPES:
            Relations().apply(self, [e], "")
        return e


class Frame:
    now = int(datetime(2026, 10, 8, 12, tzinfo=UTC).timestamp() * 1e6)
    root = None
    env = NS(tz_of=lambda *_: ZoneInfo("UTC"), params_of=lambda *_: MemoryParams())

    def __init__(self, audience: Audience | None = None, **attrs):
        self.episode = NS(target="user_2", attrs={"reply_to": 10000, **attrs})
        self.audience = audience or Audience(persons=("user_2",), public=False, level=1, witness_level=2,
                                             private_ok=True)

    def local(self, at=None):
        return datetime.fromtimestamp((self.now if at is None else at) / 1e6, tz=ZoneInfo("UTC"))

    def get(self, key):
        if key.name == "self.persona":
            return NS(name="Mika")
        if key.name == "identity.person":
            return key.arg
        if key.name == "identity.identity":
            return NS(name=NAMES.get(key.arg, key.arg))
        if key.name == "social.sensitive_ref":
            return ""
        if key.name == "social.closeness":
            return "stranger"
        if key.name == "memory.hard_times":
            return 0
        if key.name == "affect.mood":
            return NS(felt_intensity=0, felt="neutral")
        if key.name == "affect.bond":
            return 0.0
        return ()


FRAME = Frame()
CX = NS(params=None, facts=NS(get=FRAME.get))
SALON = Audience(persons=("user_2",), room="salon", public=True, level=1, witness_level=1, private_ok=False)
ALICE = (Speaker("P1", "user_2", "Alice"),)


def ask(db: Store, text: str, *, room: str | None = None) -> None:
    db.execute("INSERT INTO thread(id,at,role,person,text,room) VALUES(?,?,?,?,?,?)",
               (10000, FRAME.now, "user", "user_2", text, room))


async def index(db: Store, items: list[VectorItem], **kw) -> SqliteVectorIndex:
    vectors = SqliteVectorIndex(db, HashEmbedder(), **kw)
    await vectors.open()
    await vectors.upsert(items)
    return vectors


async def drafts(db: Store, ex: Extraction, lines: tuple[Line, ...], *, people: People | None = None,
                 speakers=ALICE, key: str = "private:user_2") -> list:
    conv = Conversation(key, speakers, lines)
    people = people or People.of(speakers, {}, "Mika", scope=conv.key)
    return await Consolidate()._drafts(ex, FRAME, MemoryState(), db, conv, people, [], [], None, MemoryParams(),
                                       "audit")


def alice_says(text: str, seq: int = 10000) -> Line:
    return Line(seq, FRAME.now, "Alice", text, "user_2")


def mika_says(text: str, seq: int = 10001) -> Line:
    return Line(seq, FRAME.now, "Mika", text)


# ── 1. un secret en salon ─────────────────────────────────────────────────


def test_her_own_secret_never_leaves_for_a_room_even_when_she_is_the_one_answered():
    """Alice a demandé de garder pour soi quelque chose d'anodin : en tête-à-tête avec elle, ça se redit ; dans un
    salon où elle parle, non — d'autres l'entendent. Sur ce qu'elle a confié d'un autre (la surprise de Bob), pareil."""
    for about in (("user_2",), ("user_2", "user_3")):
        private = Audience(persons=("user_2",), public=False, level=1, witness_level=2, private_ok=False)
        kw = dict(told_by=("user_2",), heard_by=("user_2",), secret=True)
        assert admissible(about, Sensitivity.ANODYNE, "user_2", private, **kw).ok
        verdict = admissible(about, Sensitivity.ANODYNE, "user_2", SALON, **kw)
        assert not verdict.ok and verdict.secret
        # contrôle : ce qui n'est pas secret, anodin, se dit dans le salon comme avant
        assert admissible(about, Sensitivity.ANODYNE, "user_2", SALON, told_by=("user_2",),
                          heard_by=("user_2",)).ok


async def test_her_secret_does_not_reach_the_room_section_of_the_prompt():
    db = Store()
    secret = "Les romans de dragons pour mon cadeau surprise"
    db.put(mc.BELIEVED.draft(text=Content.of(secret), about=("user_2",), told_by=("user_2",), heard_by=("user_2",),
                             sensitivity=1, secret=True), 1, FRAME.now)
    ask(db, "Tu connais mes lectures de romans de dragons ?", room="salon")
    vectors = await index(db, [VectorItem(1, mc.BELIEF, secret, ("user_2",))])
    private = Frame()
    body = _body(await _recall(MemoryState(), private, {"store": db, "vectors": vectors}), private, witness=False)
    assert body and secret in body.content  # contrôle : en tête-à-tête, elle s'en souvient
    room = Frame(SALON, room="salon")
    body = _body(await _recall(MemoryState(), room, {"store": db, "vectors": vectors}), room, witness=False)
    assert not body or secret not in body.content
    db.conn.close()


# ── 2. le graphe suit la croyance ─────────────────────────────────────────


def _friends(db: Store) -> SocialState:
    relation = mc.Relation(subject="user_2", other="user_3", kind="friend", status="active")
    believed = db.put(mc.BELIEVED.draft(text=Content.of("Alice est amie avec Bob"), told_by=("user_2",),
                                        relations=(relation,)), 1)
    social = _knit(SocialState(), believed, CX)
    assert _ties(social, CX, "user_3") == ("user_2",)  # contrôle : le lien ouvre les confidences d'Alice à Bob
    return social


def _reloaded(db: Store, social: SocialState, seq: int) -> SocialState:
    recalled = recall_relations(social, FRAME, NS(data=NS(handle="user_3")), {"store": db})
    return _relations_recalled(social, event(recalled[0], seq), CX) if recalled else social


def test_a_belief_made_secret_takes_its_tie_with_it_in_memory_and_in_the_archive():
    db = Store()
    social = _knit(_friends(db), db.put(mc.REINFORCED.draft(item=1, secret=True, sensitivity=3), 2), CX)
    assert _ties(social, CX, "user_3") == ()
    assert json.loads(db.query("SELECT payload FROM social_relations")[0][0])["secret"] is True
    assert _ties(_reloaded(db, SocialState(), 3), CX, "user_3") == ()  # rechargé à froid : secret aussi
    db.conn.close()


def test_a_tie_replaced_by_a_reinforcement_does_not_come_back_at_the_next_encounter():
    db = Store()
    social = _friends(db)
    db.put(mc.BELIEVED.draft(text=Content.of("Alice et Bob ne sont plus amis"), about=("user_2", "user_3")), 3)
    social = _knit(social, db.put(mc.REINFORCED.draft(item=3, replaces=1), 4), CX)
    assert _ties(social, CX, "user_3") == ()
    assert _ties(_reloaded(db, social, 5), CX, "user_3") == ()
    db.conn.close()


# ── 3. des moments distincts ──────────────────────────────────────────────


async def test_a_situation_that_ended_and_comes_back_is_a_new_one():
    db = Store()
    db.put(mc.EVENT_NOTED.draft(text=Content.of("Le chat Moustache est malade"), when=FRAME.now - 20 * DAY,
                                ongoing=True, about=("user_2",), told_by=("user_2",), heard_by=("user_2",)), 1)
    db.put(mc.SITUATION_ENDED.draft(event=1), 2, FRAME.now - 10 * DAY)
    ex = Extraction(evenements=[XEvenement(texte="Le chat Moustache est malade", quand="2026-10-08", en_cours=True,
                                           personnes=["P1"], messages=[10000])])
    noted = [d for d in await drafts(db, ex, (alice_says("Moustache est de nouveau malade"),))
             if d.type.name == mc.EVENT_NOTED.name]
    assert len(noted) == 1 and noted[0].data.ongoing and noted[0].data.replaces is None
    db.conn.close()


async def test_a_physics_exam_on_another_day_does_not_erase_the_maths_exam():
    db = Store()
    db.put(mc.EVENT_NOTED.draft(text=Content.of("Alice passe un examen de mathématiques"), when=FRAME.now + DAY,
                                about=("user_2",), told_by=("user_2",), heard_by=("user_2",)), 1)

    async def noted(text: str, when: str):
        ex = Extraction(evenements=[XEvenement(texte=text, quand=when, personnes=["P1"], messages=[10000])])
        return [d for d in await drafts(db, ex, (alice_says(text),)) if d.type.name == mc.EVENT_NOTED.name]

    physics = await noted("Alice passe un examen de physique", "2026-10-10")
    assert len(physics) == 1 and physics[0].data.replaces is None
    # contrôle : les mêmes mots à une autre date, c'est le même examen, reporté
    moved = await noted("Alice passe son examen de mathématiques, décalé", "2026-10-12")
    assert len(moved) == 1 and moved[0].data.replaces == 1
    db.conn.close()


# ── 4. les mentions d'une conversation ────────────────────────────────────


def test_a_mention_from_another_conversation_does_not_make_a_known_name_ambiguous():
    db = Store()
    elsewhere = f"name:{mention_scope('private:user_4')}:ines"
    db.put(mc.BELIEVED.draft(text=Content.of("Inès part au Japon"), about=(elsewhere,), told_by=("user_4",)), 1)
    db.put(mc.BELIEVED.draft(text=Content.of("Inès adore le thé"), about=("user_5",), told_by=("user_5",)), 2)
    text = "tu as des nouvelles d'Inès ?"
    here = mention_scope("private:user_2")
    assert named_people(FRAME, db, text, "user_2", {}) == {}  # sans portée : deux « Inès », aucune
    assert named_people(FRAME, db, text, "user_2", {}, scope=here) == {"user_5": ("user_5",)}
    db.conn.close()


def test_the_console_binds_the_alice_of_that_very_conversation(tmp_path):
    """La console propose de relier l'« Alice Martin » dont Bob a parlé : c'est cette mention-là (portée par sa
    conversation) qui la désigne ensuite, et « Détacher un nom » la défait."""
    key = f"name:{mention_scope('private:user_2')}:alice martin"

    def mention(**values: str) -> dict[str, list[str]]:
        """Le formulaire tel que la console le poste : la mention, posée par la page, en champ fixe."""
        return {**form(**values), FIXED_FIELD: ["key"], "key": [key]}

    async def scenario(kernel, llm):
        await connect(kernel, "user_1", "Adrien", operator=True)
        await connect(kernel, "user_2", "Bob")
        await connect(kernel, "user_3", "Alice")
        p = await say(kernel, said("user_2", "ma coloc Alice Martin part vivre au Japon en décembre"))
        await kernel.mind.append([mc.BELIEVED.draft(
            text=Content.of("Alice Martin, la coloc de Bob, part vivre au Japon", level=1), about=(key,),
            sensitivity=1, source="user_2", told_by=("user_2",), sources=(p.seq,))],
            emitter="memory", correlation="genese", origin=Origin.GENESIS)
        wrong = await perform(kernel, "identity.nommer", mention(name="Bob", confirmed="on"), by="user_1",
                              subject="user_3", nonce="a")
        done = await perform(kernel, "identity.nommer", mention(name="Alice Martin", confirmed="on"),
                             by="user_1", subject="user_3", nonce="b")
        bound = kernel.mind.frame().get(identity_c.PERSON(key))
        undone = await perform(kernel, "identity.denommer", form(name="Alice Martin"), by="user_1",
                               subject="user_3", nonce="c")
        return wrong, done, bound, undone, kernel.mind.frame().get(identity_c.PERSON(key))

    wrong, done, bound, undone, after = run(tmp_path, scenario)
    assert not wrong.ok  # un nom qui n'est pas celui de la mention ne la relie pas
    assert done.ok and bound == "user_3"
    assert undone.ok and after == key


# ── 5. ce qui ne se dit pas n'étouffe pas ce qui se dit ───────────────────


async def test_forty_secrets_of_bob_do_not_make_her_forget_alices_garden():
    db = Store()
    query = "Tu te souviens de mon projet de potager avec des tomates ?"
    garden = "Alice cultive des tomates dans son potager pour son projet"
    db.put(mc.BELIEVED.draft(text=Content.of(garden), about=("user_2",), told_by=("user_2",),
                             heard_by=("user_2",)), 100, FRAME.now)
    for i in range(1, 41):
        db.put(mc.BELIEVED.draft(text=Content.of(query), about=("user_3",), told_by=("user_3",), heard_by=("user_3",),
                                 sensitivity=3, secret=True), i, FRAME.now)
    ask(db, query)
    vectors = await index(db, [VectorItem(100, mc.BELIEF, garden, ("user_2",)),
                               *(VectorItem(i, mc.BELIEF, query, ("user_3",)) for i in range(1, 41))])
    recall = await _recall(MemoryState(), Frame(), {"store": db, "vectors": vectors})
    assert any(r.item.id == 100 for r in recall.beliefs)
    assert not any(r.item.id <= 40 for r in recall.beliefs)
    db.conn.close()


async def test_a_deliberate_search_goes_further_while_nothing_sayable_was_found():
    """Ce que Carol a dit d'anodin, Alice peut l'entendre — même derrière quarante secrets de Bob plus proches."""
    db = Store()
    query = "Le potager de Carol et ses tomates"
    carol = "Carol a planté des tomates dans son potager"
    db.put(mc.BELIEVED.draft(text=Content.of(carol), about=("user_4",), told_by=("user_4",), heard_by=("user_4",)),
           100, FRAME.now)
    for i in range(1, 41):
        db.put(mc.BELIEVED.draft(text=Content.of(query), about=("user_3",), told_by=("user_3",), heard_by=("user_3",),
                                 sensitivity=3, secret=True), i, FRAME.now)
    vectors = await index(db, [VectorItem(100, mc.BELIEF, carol, ("user_4",)),
                               *(VectorItem(i, mc.BELIEF, query, ("user_3",)) for i in range(1, 41))])
    said_back = await memory_search(SearchArgs(query=query), NS(ports={"store": db, "vectors": vectors},
                                                                frame=Frame()))
    assert carol in said_back
    db.conn.close()


# ── 6. ce qu'elle dit d'elle, ce qu'on dit d'elle ─────────────────────────


async def test_what_someone_else_told_her_about_herself_keeps_its_teller_and_its_secret():
    db = Store()
    ex = Extraction(croyances=[XCroyance(texte="Mon code personnel est ORCHIDEE", sur_elle=True, genre="fait",
                                         sensibilite="confidence", secret=True, messages=[10000])])
    got = await drafts(db, ex, (alice_says("Ton code personnel est ORCHIDEE, garde-le pour toi."),))
    beliefs = [d.data for d in got if d.type.name == mc.BELIEVED.name]
    assert len(beliefs) == 1
    assert beliefs[0].told_by == ("user_2",) and beliefs[0].secret and not beliefs[0].about_self
    db.conn.close()


async def test_her_own_secret_about_herself_stays_a_secret():
    db = Store()
    lines = (alice_says("Tu as un rêve secret ?"), mika_says("Je rêve d'écrire un roman, mais garde ça pour toi"))
    ex = Extraction(croyances=[XCroyance(texte="Je rêve d'écrire un roman", sur_elle=True, genre="fait",
                                         secret=True, messages=[10001])])
    mine = [d.data for d in await drafts(db, ex, lines) if d.type.name == mc.BELIEVED.name]
    assert len(mine) == 1 and mine[0].about_self and mine[0].secret
    assert mine[0].sensitivity >= Sensitivity.CONFIDENCE and not mine[0].told_by
    # contrôle : sa vie de tous les jours, elle, reste anodine
    ex = Extraction(croyances=[XCroyance(texte="J'adore les ramen", sur_elle=True, genre="gout", messages=[10001])])
    plain = [d.data for d in await drafts(Store(), ex, (mika_says("J'adore les ramen"),))
             if d.type.name == mc.BELIEVED.name]
    assert plain[0].sensitivity == Sensitivity.ANODYNE and not plain[0].secret
    db.conn.close()


async def test_her_own_request_for_silence_holds_even_when_the_model_does_not_flag_it():
    """« garde ça pour toi », dit par elle : la note sur elle reste secrète sans le drapeau du modèle."""
    db = Store()
    lines = (alice_says("Tu as un rêve secret ?"), mika_says("Je rêve d'écrire un roman, mais garde ça pour toi"))
    ex = Extraction(croyances=[XCroyance(texte="Je rêve d'écrire un roman", sur_elle=True, genre="fait",
                                         messages=[10001])])
    mine = [d.data for d in await drafts(db, ex, lines) if d.type.name == mc.BELIEVED.name]
    assert len(mine) == 1 and mine[0].about_self and mine[0].secret
    assert mine[0].sensitivity >= Sensitivity.CONFIDENCE
    db.conn.close()


async def test_what_she_said_of_herself_in_secret_is_not_recalled_in_a_room():
    db = Store()
    dream = "Je rêve d'écrire un roman"
    db.put(mc.BELIEVED.draft(text=Content.of(dream), about_self=True, durable=True, secret=True,
                             sensitivity=int(Sensitivity.CONFIDENCE)), 1, FRAME.now)
    ask(db, "c'est quoi ton rêve ?", room="salon")
    vectors = await index(db, [VectorItem(1, mc.BELIEF, dream, ())])
    recall = await _recall(MemoryState(), Frame(SALON, room="salon"), {"store": db, "vectors": vectors})
    assert not any(it.id == 1 for it in recall.self_said)
    db.conn.close()


# ── 10. chercher parmi quelques clés ──────────────────────────────────────


async def test_a_disk_search_among_a_few_keys_reads_only_them():
    db = Store()
    vectors = await index(db, [VectorItem(i, mc.BELIEF, f"Potager numéro {i}", (f"user_{i}",)) for i in range(1, 301)],
                          max_resident_vectors=10)
    read: list[int] = []
    query = db.query

    def tracked(sql, args=()):
        rows = query(sql, args)
        if "SELECT key, persons, vec" in sql:
            read.append(len(rows))
        return rows

    db.query = tracked
    assert (await vectors.search("potager", 1, keys=[7]))[0][0] == 7
    assert sum(read) == 1
    read.clear()
    assert (await vectors.search("potager", 3, persons=["user_9"]))[0][0] == 9
    assert sum(read) == 1
    db.conn.close()
