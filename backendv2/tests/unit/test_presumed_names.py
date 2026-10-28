"""Un prénom seul se présume, il ne se relie pas (ADR 0075) ; et une croyance naît bornée par sa nature.

- la nouvelle collègue « Alice » de Bob reste une mention : l'identité la présume être l'Alice qu'elle connaît (la
  seule de ce nom), sans la relier — contre-exemples : un nom complet, ou un prénom porté par quelqu'un vu en salon
  avec Bob, se relient comme avant ;
- la présomption est révisable d'elle-même : une seconde Alice connue, un « ce n'est pas elle », une liaison
  d'opérateur, et elle tombe ;
- elle sert à y penser, jamais à la traiter comme elle : ni ``identity.person``, ni la porte de sa fiche ; la ligne
  rappelée porte son doute ;
- l'oubli d'Alice emporte ce qu'on présumait d'elle ;
- ce qu'on lui a dit ne naît pas plus sûr que 0,8, ce qu'elle a vu que 0,9, ce qu'elle déduit que 0,6 — et seule
  une autre personne qui le lui redit le fait monter au-delà ;
- une présomption ne protège jamais moins qu'une liaison : le lien de l'ADR 0058 l'exige, les sujets délicats de la
  personne présumée comptent, un « garde-le pour toi » après coup la vise encore, et l'oubli emporte la mention
  partout où elle figure (relecture du 2026-10-09).
"""

from __future__ import annotations

from mika.contracts import identity as identity_c
from mika.contracts import memory as mc
from mika.faculties.memory import consolidation as cons
from mika.faculties.memory.consolidation import Consolidate, known_beliefs
from mika.faculties.memory.extraction import (
    CONFIDENCE_CAP,
    Conversation,
    Extraction,
    Line,
    People,
    Speaker,
    XCroyance,
    born_confidence,
    mention_scope,
)
from mika.faculties.memory.projections import Items
from mika.faculties.memory.recall import (
    canon,
    doubted,
    items_by_id,
    named_people,
    presumed_of,
    sensitivity_of,
)
from mika.faculties.memory.salience import admissible
from mika.kernel.events import Content, Origin
from mika.kernel.frame import Audience
from mika.ports.vectors import VectorItem
from mika.runtime.operations import FIXED_FIELD, forget_subject, perform
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity
from tests.fixtures.mika import connect, said
from tests.unit.test_audit_regressions import event
from tests.unit.test_identity_security import form, run, say
from tests.unit.test_knowledge_coherence import ALICE, Frame, Store, alice_says, drafts, index, mika_says

BOB = (Speaker("P1", "user_3", "Bob"),)
SCOPE = mention_scope("private:user_3")
MENTION = f"name:{SCOPE}:alice"


# ── l'extraction : une mention, pas une liaison ──────────────────────────


def test_a_first_name_alone_stays_a_mention_of_that_conversation():
    """« Ma nouvelle collègue Alice » : Mika connaît une seule Alice, mais Bob n'a jamais été vu avec elle."""
    people = People.of(BOB, {"alice": ("user_2",)}, "Mika", scope="private:user_3")
    assert people.one("Alice") == MENTION


def test_a_full_name_or_a_first_name_met_in_a_room_still_links():
    """Contre-exemples : « Alice Martin », que porte une seule personne, la désigne ; « Inès », qu'elle a vue dans
    un salon avec Bob, aussi — c'est l'Inès qu'ils connaissent tous deux."""
    directory = {"alice martin": ("user_2",), "alice": ("user_2",), "ines": ("user_5",)}
    people = People.of(BOB, directory, "Mika", scope="private:user_3", near=("user_5",))
    assert people.one("Alice Martin") == "user_2"
    assert people.one("Inès") == "user_5"
    assert people.one("Alice") == MENTION


# ── l'identité : une présomption révisable ───────────────────────────────


async def _mention(kernel, text: str = "ma nouvelle collègue Alice est super stressée (CANARI-P1)") -> None:
    p = await say(kernel, said("user_3", text))
    await kernel.mind.append([mc.BELIEVED.draft(
        text=Content.of(text, level=2), about=(MENTION,), sensitivity=2, source="user_3", told_by=("user_3",),
        sources=(p.seq,))], emitter="memory", correlation="genese", origin=Origin.GENESIS)


def test_the_only_alice_she_knows_is_presumed_never_linked(tmp_path):
    """Présumée : un indice. Ni ``identity.person`` ni les liens ne la suivent ; une seconde Alice connue, et la
    présomption tombe (deux Alice ne se devinent pas)."""
    async def scenario(kernel, llm):
        await connect(kernel, "user_2", "Alice")
        await connect(kernel, "user_3", "Bob")
        await _mention(kernel)
        frame = kernel.mind.frame()
        alone = frame.get(identity_c.PRESUMED(MENTION)), frame.get(identity_c.PERSON(MENTION))
        await connect(kernel, "user_4", "Alice")
        return alone, kernel.mind.frame().get(identity_c.PRESUMED(MENTION))

    (presumed, person), with_two = run(tmp_path, scenario)
    assert presumed == "user_2" and person == MENTION
    assert with_two == ""


def test_an_operator_settles_the_presumption_either_way(tmp_path):
    """« Ce n'est pas elle » : plus de présomption. « C'est elle » : une liaison, plus une présomption."""
    async def scenario(kernel, llm):
        await connect(kernel, "user_1", "Adrien", operator=True)
        await connect(kernel, "user_2", "Alice")
        await connect(kernel, "user_3", "Bob")
        await _mention(kernel)
        dismissed = await perform(kernel, "identity.ecarter_nom", {
            "_champs": [], FIXED_FIELD: ["name", "person"], "name": [MENTION], "person": ["user_2"]},
            by="user_1", subject="user_2", nonce="a")
        after_no = kernel.mind.frame().get(identity_c.PRESUMED(MENTION))
        bound = await perform(kernel, "identity.nommer", {
            **form(name="Alice", confirmed="on"), FIXED_FIELD: ["key"], "key": [MENTION]},
            by="user_1", subject="user_2", nonce="b")
        frame = kernel.mind.frame()
        return dismissed, after_no, bound, frame.get(identity_c.PRESUMED(MENTION)), frame.get(
            identity_c.PERSON(MENTION))

    dismissed, after_no, bound, after_yes, person = run(tmp_path, scenario)
    assert dismissed.ok and after_no == ""
    assert bound.ok and after_yes == "" and person == "user_2"


def test_forgetting_alice_takes_what_was_presumed_of_her(tmp_path):
    """Dans le doute, on oublie plus, jamais moins : ce que Bob a dit d'« Alice » part avec elle."""
    async def scenario(kernel, llm):
        await connect(kernel, "user_1", "Adrien", operator=True)
        await connect(kernel, "user_2", "Alice")
        await connect(kernel, "user_3", "Bob")
        await _mention(kernel)
        await forget_subject(kernel, "person", "user_2", by="user_1", action="oublier.person")
        return kernel.mind.store.query_mind("SELECT text FROM memory_items WHERE text LIKE '%CANARI-P1%'")

    assert run(tmp_path, scenario) == []


# ── le rappel : y penser, avec son doute ─────────────────────────────────


class Presuming(Frame):
    """Le cadre de test, avec une identité qui présume la mention d'Alice (et de Carol), et une Alice dont l'alcool
    est un sujet délicat."""

    def get(self, key):
        if key.name == "identity.presumed":
            return {MENTION: "user_2", CAROL: "user_4"}.get(key.arg, "")
        if key.name == "social.sensitive":
            return ("alcool",) if key.arg == "user_2" else ()
        return super().get(key)


def test_a_presumed_mention_is_thought_of_with_its_doubt_never_treated_as_her():
    db = Store()
    db.put(mc.BELIEVED.draft(text=Content.of("Alice est super stressée par son nouveau travail"), about=(MENTION,),
                             told_by=("user_3",), heard_by=("user_3",), sensitivity=1), 1)
    frame, memo = Presuming(), {}
    # Inès demande des nouvelles d'Alice : la mention se range sous Alice (elle y pense)…
    named = named_people(frame, db, "des nouvelles d'Alice ?", "user_5", memo, scope=mention_scope("private:user_5"))
    assert named == {"user_2": (MENTION,)}
    # … mais rien ne la traite comme Alice : la clé reste la sienne, et la ligne dit son doute
    assert canon(frame, (MENTION,), memo) == (MENTION,) and presumed_of(frame, MENTION, memo) == "user_2"
    item = items_by_id(db, [1])[1]
    assert doubted(frame, item, memo) == phrase("memory.tag.presumed", name="Alice", who="Bob")
    assert doubted(Frame(), item, {}) == "", "sans présomption, rien à mettre en doute"
    db.conn.close()


# ── la confiance d'une croyance qui naît ─────────────────────────────────


def test_a_belief_is_born_no_surer_than_its_nature():
    assert born_confidence(0.99, "told") == CONFIDENCE_CAP["told"] == 0.8
    assert born_confidence(0.99, "observed") == 0.9
    assert born_confidence(0.99, "inferred") == born_confidence(0.99, "told", "hypothesis") == 0.6
    assert born_confidence(0.5, "told") == 0.5, "sous la borne, rien ne change"


async def test_the_extractor_cannot_make_what_she_was_told_certain():
    db = Store()
    ex = Extraction(croyances=[
        XCroyance(texte="Alice déménage à Lyon en mai", personnes=["Alice"], confiance=0.99, origine="dit",
                  messages=[10000]),
        XCroyance(texte="Alice a sûrement peur de partir", personnes=["Alice"], confiance=0.95, origine="déduit",
                  messages=[10000])])
    got = [d.data for d in await drafts(db, ex, (alice_says("je déménage à Lyon en mai"),), speakers=ALICE)
           if d.type.name == mc.BELIEVED.name]
    assert sorted(d.confidence for d in got) == [0.6, 0.8]
    db.conn.close()


def test_only_someone_else_saying_it_too_raises_it_past_its_birth():
    """Contre-exemple : une autre personne qui le lui redit (``corroborated``) la fait monter au-delà de 0,8."""
    db = Store()
    Items().apply(db, [event(mc.BELIEVED.draft(text=Content.of("Alice déménage à Lyon"), about=("user_2",),
                                               confidence=0.8, told_by=("user_2",)), 1)], "")
    Items().apply(db, [event(mc.REINFORCED.draft(item=1, corroborated=True, told_by=("user_3",)), 2)], "")
    # un ancien renfort corroboré : un témoin de plus, mis en commun (ADR 0080) — plus sûr, borné
    (confidence,), = db.query("SELECT confidence FROM memory_items")
    assert 0.85 < confidence <= 0.95
    db.conn.close()


def test_a_speaker_named_by_another_of_her_addresses_stays_herself():
    """Bob s'appelle « Robert » sur une autre de ses adresses : dans sa propre conversation, ce nom est lui."""
    people = People.of(BOB, {"robert": ("user_3",)}, "Mika", scope="private:user_3")
    assert people.one("Robert") == "user_3"


# ── une présomption ne protège jamais moins qu'une liaison ───────────────

CAROL = f"name:{mention_scope('private:user_2')}:carol"
DAVE = Audience(persons=("user_5",), public=False, level=1, witness_level=2, private_ok=False, tied_level=3,
                ties=("user_2",))


def test_a_presumed_carol_still_needs_a_tie_with_carol():
    """La confidence d'Alice qui nomme « Carol » (présumée être Carol) : Dave, lié à Alice seulement, ne la reçoit
    pas — comme si Carol était reliée. Contre-exemple (ADR 0058) : un inconnu nommé (« Marc ») reste un détail de
    l'histoire d'Alice. Sans de quoi lire la présomption, rien ne s'ouvre."""
    frame, memo = Presuming(), {}
    presumed = lambda key: presumed_of(frame, key, memo)  # noqa: E731
    marc = f"name:{mention_scope('private:user_2')}:marc"
    confided = dict(told_by=("user_2",), heard_by=("user_2",))
    assert not admissible(("user_2", CAROL), 3, "user_5", DAVE, presumed=presumed, **confided).ok
    assert admissible(("user_2", "user_4"), 3, "user_5", DAVE, presumed=presumed, **confided).ok is False
    assert admissible(("user_2", marc), 3, "user_5", DAVE, presumed=presumed, **confided).ok
    assert not admissible(("user_2", marc), 3, "user_5", DAVE, **confided).ok, "sans présomption lisible : fermé"


def test_her_sensitive_topics_count_for_a_presumed_mention():
    """« Alice boit trop d'alcool », dit par Bob : l'alcool est un sujet délicat d'Alice, présumée — c'est une
    confidence, comme si elle était reliée. Sans présomption, rien ne la relève."""
    db = Store()
    db.put(mc.BELIEVED.draft(text=Content.of("Alice boit beaucoup trop d'alcool ces temps-ci"), about=(MENTION,),
                             told_by=("user_3",), heard_by=("user_3",), sensitivity=2), 1)
    item = items_by_id(db, [1])[1]
    assert sensitivity_of(Presuming(), item, "user_5") == Sensitivity.CONFIDENCE
    assert sensitivity_of(Frame(), item, "user_5") == 2
    db.conn.close()


async def test_a_later_request_for_silence_still_reaches_a_mention_of_this_conversation():
    """Bob a parlé de sa collègue « Alice », puis dit « garde-le pour toi » : la croyance sur la mention est montrée
    à l'extraction, qui peut la rendre secrète (``confidentiel``)."""
    db = Store()
    text = "Alice, la collègue de Bob, est enceinte"
    db.put(mc.BELIEVED.draft(text=Content.of(text), about=(MENTION,), told_by=("user_3",), heard_by=("user_3",),
                             sensitivity=2), 1)
    vectors = await index(db, [VectorItem(1, mc.BELIEF, text, ())])
    conv = Conversation("private:user_3", BOB, (Line(101, Frame.now, "Bob", "pour Alice, garde-le pour toi", "user_3"),))
    people = People.of(BOB, {}, "Mika", scope="private:user_3")
    known = await known_beliefs(db, vectors, conv, people, {})
    assert [i for i, _t in known] == [1]
    db.conn.close()


def test_forgetting_alice_takes_a_mention_that_only_holds_an_opinion(tmp_path):
    """« Alice pense que Paul devrait démissionner », raconté par Carol : la mention d'Alice n'y est que ``holder``.
    L'oubli d'Alice l'emporte quand même — l'index des sujets du journal, pas seulement « à propos de »."""
    alice = f"name:{mention_scope('private:user_4')}:alice"

    async def scenario(kernel, llm):
        await connect(kernel, "user_1", "Adrien", operator=True)
        await connect(kernel, "user_2", "Alice")
        await connect(kernel, "user_4", "Carol")
        p = await say(kernel, said("user_4", "Alice pense que Paul devrait démissionner (CANARI-H1)"))
        await kernel.mind.append([mc.BELIEVED.draft(
            text=Content.of("Paul devrait démissionner (CANARI-H1)", level=1), about=(), sensitivity=1,
            source="user_4", told_by=("user_4",), sources=(p.seq,), knowledge_kind="opinion", holder=alice)],
            emitter="memory", correlation="genese", origin=Origin.GENESIS)
        await forget_subject(kernel, "person", "user_2", by="user_1", action="oublier.person")
        return kernel.mind.store.query_mind("SELECT text FROM memory_items WHERE text LIKE '%CANARI-H1%'")

    assert run(tmp_path, scenario) == []


# ── le rappel : dans la conversation de Bob, son Alice ───────────────────


def test_in_bobs_conversation_alice_is_the_one_he_talks_about():
    """Chez Bob, « Alice » désigne sa collègue (la mention faite ici) : l'Alice qu'elle connaît ne revient pas
    mélangée. Chez Inès, la mention présumée rejoint l'Alice connue. Et devant Bob, qui l'a raconté, pas de doute
    affiché (il sait de qui il parle)."""
    db = Store()
    db.put(mc.BELIEVED.draft(text=Content.of("Alice jardine le week-end"), about=("user_2",), told_by=("user_2",),
                             heard_by=("user_2",), sensitivity=1), 1)
    db.put(mc.BELIEVED.draft(text=Content.of("Alice pleure tous les jours"), about=(MENTION,), told_by=("user_3",),
                             heard_by=("user_3",), sensitivity=2), 2)
    frame = Presuming()
    at_bobs = named_people(frame, db, "et Alice, tu en penses quoi ?", "user_3", {}, scope=SCOPE)
    at_ines = named_people(frame, db, "et Alice ?", "user_5", {}, scope=mention_scope("private:user_5"))
    assert at_bobs == {MENTION: (MENTION,)}
    assert at_ines == {"user_2": tuple(sorted(("user_2", MENTION)))}
    item = items_by_id(db, [2])[2]
    assert doubted(frame, item, {}, "user_3") == "" and doubted(frame, item, {}, "user_5")
    db.conn.close()


def test_rooms_are_read_once_then_only_what_follows():
    """Les salons où chacun a été vu : la première lecture prend le fil, les suivantes seulement la suite."""
    db = Store()
    rows = [(1, "user_2", "salon"), (2, "user_3", "salon"), (3, "user_5", None)]
    for i, who, room in rows:
        db.execute("INSERT INTO thread(id,at,role,person,text,room) VALUES(?,?,?,?,?,?)",
                   (i, Frame.now, "user", who, "…", room))
    process = Consolidate()
    first = process._rooms(Frame(), db)
    db.execute("INSERT INTO thread(id,at,role,person,text,room) VALUES(?,?,?,?,?,?)",
               (4, Frame.now, "user", "user_5", "…", "atelier"))
    second = process._rooms(Frame(), db)
    assert first == {"user_2": {"salon"}, "user_3": {"salon"}} and process.rooms_read == 4
    assert second["user_5"] == {"atelier"}
    assert cons._near(Conversation("private:user_3", BOB, ()), second) == ("user_2", "user_3")
    db.conn.close()


# ── ce qu'elle redit n'est pas une note sur elle ─────────────────────────


async def test_her_recap_of_what_alice_told_her_is_not_a_note_about_herself():
    """« Qu'est-ce que tu sais de moi ? » — « Je sais que tu es comptable à Lyon » : le modèle range « Alice est
    comptable à Lyon » sur elle (sonde réelle du 2026-10-09). Rangée ainsi, la note ne concernait personne et se
    disait à tous. Elle nomme Alice : ce n'est pas sa vie à elle, et redire n'est pas apprendre — rien n'est
    gardé. Contre-exemple : « j'adore les ramen », dit par elle, reste une note sur elle."""
    db = Store()
    lines = (alice_says("qu'est-ce que tu sais de moi ?"), mika_says("Je sais que tu es comptable à Lyon"))
    recap = Extraction(croyances=[XCroyance(texte="Alice est comptable à Lyon.", sur_elle=True, messages=[10001])])
    got = [d.data for d in await drafts(db, recap, lines) if d.type.name == mc.BELIEVED.name]
    assert not any(d.about_self or not d.about for d in got), got
    ramen = Extraction(croyances=[XCroyance(texte="J'adore les ramen", sur_elle=True, genre="gout",
                                            messages=[10001])])
    mine = [d.data for d in await drafts(Store(), ramen, (mika_says("J'adore les ramen"),))
            if d.type.name == mc.BELIEVED.name]
    assert len(mine) == 1 and mine[0].about_self
    db.conn.close()


def test_a_text_names_someone_by_a_speaker_or_a_known_name_never_by_her_own():
    people = People.of(BOB, {"alice": ("user_2",), "alice martin": ("user_2",)}, "Mika", scope="private:user_3")
    assert people.names_someone("Alice est comptable à Lyon")
    assert people.names_someone("je trouve que Bob a raison")
    assert not people.names_someone("Mika adore les ramen")
    assert not people.names_someone("J'aime alicaments et salades")
