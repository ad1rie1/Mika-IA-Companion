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
  une autre personne qui le lui redit le fait monter au-delà.
"""

from __future__ import annotations

from mika.contracts import identity as identity_c
from mika.contracts import memory as mc
from mika.faculties.memory.extraction import (
    CONFIDENCE_CAP,
    Extraction,
    People,
    Speaker,
    XCroyance,
    born_confidence,
    mention_scope,
)
from mika.faculties.memory.projections import Items
from mika.faculties.memory.recall import canon, doubted, items_by_id, named_people, presumed_of
from mika.kernel.events import Content, Origin
from mika.runtime.operations import FIXED_FIELD, forget_subject, perform
from mika.vocab.phrasebook import phrase
from tests.fixtures.mika import connect, said
from tests.unit.test_audit_regressions import event
from tests.unit.test_identity_security import form, run, say
from tests.unit.test_knowledge_coherence import ALICE, Frame, Store, alice_says, drafts

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
    """Le cadre de test, avec une identité qui présume la mention d'Alice."""

    def get(self, key):
        if key.name == "identity.presumed":
            return "user_2" if key.arg == MENTION else ""
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
    assert doubted(frame, item, memo) == phrase("memory.tag.presumed", name="Alice")
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
    assert db.query("SELECT confidence FROM memory_items") == [(0.9,)]
    db.conn.close()
