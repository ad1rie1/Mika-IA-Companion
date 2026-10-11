"""Ce qu'elle dit d'elle-même tient (ADR 0087).

Son image d'elle-même se nourrit de ce qu'elle a dit d'elle : ses goûts, ses avis, ce qui est vrai de sa vie. La
mémoire le rangeait mal — « mes goûts » devenait un fait rapporté, une préférence s'effaçait en quelques jours comme
une anecdote, une anecdote redite comme un goût ne le devenait jamais, et revenir à ce qu'elle pensait avant d'en
changer laissait deux notes contraires vivantes. Une note sur elle pouvait naître d'une réplique où elle mentait.
Ce qu'elle a vécu à travers quelqu'un (ADR 0086) se dit maintenant aussi en bref, sans personne (« un concert de
jazz ») ; deux vues de la porte le donnent à lire, avec ses changements d'avis.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from mika.contracts import memory as mc
from mika.faculties.memory.consolidation import Consolidate
from mika.faculties.memory.extraction import (
    IMPORTANCE,
    Extraction,
    People,
    Speaker,
    XConstat,
    XCroyance,
    XPrevision,
    XSouvenir,
    gist_of,
    kind_of_genre,
)
from mika.faculties.memory.faculty import MemoryParams
from mika.faculties.memory.inspect import Kept, _detail
from mika.faculties.memory.projections import ITEM_COLUMNS
from mika.faculties.memory.salience import Item, salience
from mika.kernel.clock import DAY
from mika.kernel.events import Content
from mika.vocab.lineage import Lineage, Requirement, Restriction, requirement, without_whom
from mika.vocab.privacy import Sensitivity
from tests.unit.test_knowledge_coherence import FRAME, Store, alice_says, drafts, mika_says
from tests.unit.test_seeing_ahead import constats, moment, of

P = MemoryParams()
ALICE = "user_2"
JAZZ, NO_JAZZ = "J'aime le jazz", "Je n'aime plus le jazz"


def said_of_herself(db: Store, text: str, genre: str | None = None, *, remplace: int | None = None,
                    known: tuple[int, ...] = ()) -> list:
    """Ce que la relecture garde d'une de ses répliques sur elle-même."""
    return Consolidate()._about_self(XCroyance(texte=text, genre=genre, sur_elle=True, remplace=remplace), db,
                                     lambda _: ((1,), (), []), "self", set(known))


def item(db: Store, seq: int) -> Item:
    raw = db.query(f"SELECT {','.join(ITEM_COLUMNS)} FROM {mc.ITEMS_TABLE} WHERE id=?", (seq,))[0]
    return Item.of(dict(zip(ITEM_COLUMNS, raw, strict=True)))


def status(db: Store) -> dict[int, str]:
    return dict(db.query(f"SELECT id, status FROM {mc.ITEMS_TABLE} ORDER BY id"))


# ── ce qu'elle aime la définit ─────────────────────────────────────────────


@pytest.mark.parametrize("genre", ["goûts", "gout", "préférence", "Préférences"])
def test_her_tastes_are_what_defines_her(genre):
    (d,) = said_of_herself(Store(), "J'adore les films de Miyazaki", genre)
    assert d.data.knowledge_kind == "preference" and d.data.durable and d.data.about_self
    assert d.data.importance == IMPORTANCE[3]  # ce qui la définit compte
    assert (kind_of_genre("hypothèse"), kind_of_genre("anecdote"), kind_of_genre(None)) == (
        "hypothesis", "claim", "claim")


def test_an_anecdote_said_again_as_a_taste_becomes_one():
    db = Store()
    (first,) = said_of_herself(db, "J'adore les films de Miyazaki")  # sans genre : une anecdote, qui s'efface
    db.put(first, 5)
    anecdote = item(db, 5)
    assert not anecdote.durable_self and anecdote.knowledge_kind == "claim"
    (again,) = said_of_herself(db, "J'adore les films de Miyazaki", "gout")
    assert again.type.name == mc.ATTESTED.name and again.data.item == 5 and again.data.durable
    db.put(again, 6)
    taste = item(db, 5)
    assert taste.durable_self and taste.knowledge_kind == "preference" and taste.importance >= IMPORTANCE[3]
    month = FRAME.now + 30 * DAY
    assert salience(taste, month, P) > 2 * salience(anecdote, month, P)  # elle tient des mois
    (plain,) = said_of_herself(db, "J'adore les films de Miyazaki")  # redite sans genre : jamais l'inverse
    db.put(plain, 7)
    assert item(db, 5).durable_self and item(db, 5).knowledge_kind == "preference" and len(status(db)) == 1


def test_coming_back_to_what_she_thought_brings_it_back():
    db = Store()
    (jazz,) = said_of_herself(db, JAZZ, "avis")
    db.put(jazz, 5)
    (no,) = said_of_herself(db, NO_JAZZ, "avis", remplace=5, known=(5,))
    db.put(no, 6)
    assert status(db) == {5: "superseded", 6: "active"}
    (back,) = said_of_herself(db, JAZZ, "avis", known=(6,))
    assert back.type.name == mc.ATTESTED.name and (back.data.item, back.data.replaces) == (5, 6)
    db.put(back, 7)
    assert status(db) == {5: "active", 6: "superseded"}  # une seule de ses deux idées vit
    changes = db.query(f"SELECT {','.join(mc.SELF_CHANGES_COLUMNS[:4])} FROM {mc.SELF_CHANGES_VIEW}")
    assert changes == [(6, NO_JAZZ, 5, JAZZ)]


def test_her_changes_of_mind_are_only_hers():
    db = Store()
    db.put(mc.BELIEVED.draft(text=Content.of("Alice travaille chez Ubisoft"), about=(ALICE,), told_by=(ALICE,)), 5)
    db.put(mc.BELIEVED.draft(text=Content.of("Alice travaille chez Ankama"), about=(ALICE,), told_by=(ALICE,),
                             replaces=5), 6)
    (jazz,) = said_of_herself(db, JAZZ, "avis")
    db.put(jazz, 7)
    (no,) = said_of_herself(db, NO_JAZZ, "avis", remplace=7, known=(7,))
    db.put(no, 8)
    assert status(db)[5] == "superseded"
    assert db.query(f"SELECT was, item FROM {mc.SELF_CHANGES_VIEW}") == [(7, 8)]


# ── jamais une note sur elle née d'un mensonge ─────────────────────────────


async def test_what_she_said_while_lying_is_never_a_note_about_her():
    asked = alice_says("tu aimes le jazz ?")
    ex = Extraction(
        croyances=[XCroyance(texte="Je déteste le jazz", genre="avis", sur_elle=True, messages=[10001])],
        souvenirs=[XSouvenir(texte="J'ai détesté mon premier concert de jazz", sur_elle=True, messages=[10001])],
        previsions=[XPrevision(texte="Je n'irai jamais à un concert de jazz", sur_elle=True, messages=[10001])])
    lying = replace(mika_says("moi je déteste le jazz, mon premier concert était nul"), lie=True)
    out = await drafts(Store(), ex, (asked, lying))
    assert of(out, mc.BELIEVED) == [] and of(out, mc.REMEMBERED) == []
    uncited = Extraction(croyances=[XCroyance(texte="Je déteste le jazz", genre="avis", sur_elle=True)])
    assert of(await drafts(Store(), uncited, (asked, lying)), mc.BELIEVED) == []  # dans le doute, on ferme
    honest = await drafts(Store(), ex, (asked, mika_says("moi je déteste le jazz, mon premier concert était nul")))
    assert {d.text.text for d in of(honest, mc.BELIEVED)} == {  # une note sur elle, souvenir compris
        "Je déteste le jazz", "J'ai détesté mon premier concert de jazz", "Je n'irai jamais à un concert de jazz"}
    assert all(d.about_self for d in of(honest, mc.BELIEVED))


# ── la console dit ce qui tient ────────────────────────────────────────────


def test_the_console_says_what_lasts():
    db = Store()
    (taste,) = said_of_herself(db, "J'adore les films de Miyazaki", "gout")
    db.put(taste, 5)
    (anecdote,) = said_of_herself(db, "J'ai ressorti mon fer à souder")
    db.put(anecdote, 6)

    def shown(seq: int) -> str:
        return dict(_detail(Kept(item(db, seq), (), None), FRAME, {}, None)[1].pairs)["sur elle"]

    assert "tient des mois" in shown(5) and "s'efface en quelques jours" in shown(6)


# ── ce qu'elle a vécu à travers quelqu'un, en bref et sans personne ────────


async def test_a_lived_moment_keeps_a_gist_without_anyone():
    db = Store()
    ev = moment(db, 5, "Le concert de jazz d'Alice au Duc des Lombards", FRAME.now - DAY, shared=True)
    said = alice_says("le concert c'était génial !")
    found = XConstat(numero=5, issue="a eu lieu", en_bref="un concert de jazz", messages=[10000])
    (draft,) = [d for d in await constats(db, {5: ev}, (said,), found) if d.type.name == mc.REMEMBERED.name]
    lived = draft.data
    assert lived.gist.text == "un concert de jazz" and lived.text.text.startswith("J'ai vécu à travers Alice")
    db.put(draft, 9)
    assert db.query(f"SELECT id, gist FROM {mc.LIVED_VIEW}") == [(9, "un concert de jazz")]
    for gist in ("le concert de jazz d'Alice", "un concert le 12 octobre", "x" * 81, ""):
        named = XConstat(numero=5, issue="a eu lieu", en_bref=gist, messages=[10000])
        (other,) = of(await constats(db, {5: ev}, (said,), named), mc.REMEMBERED)
        assert other.gist is None, gist  # un nom, un chiffre, trop long, rien : pas d'« en bref »
    secret = moment(db, 6, "La soirée d'Alice", FRAME.now - DAY, shared=True, secret=True)
    (hidden,) = of(await constats(db, {6: secret}, (said,), found.model_copy(update={"numero": 6})),
                   mc.REMEMBERED)
    assert hidden.gist is None  # un moment secret ne se raconte pas, même sans nom


def test_the_gist_net():
    people = People.of((Speaker("P1", ALICE, "Alice"),), {}, "Mika", scope="private:user_2")
    assert gist_of("  un salon du jeu vidéo. ", people) == "un salon du jeu vidéo"
    assert gist_of("la fête d'Alice", people) is None and gist_of("le 3e concert", people) is None


def test_without_whom_says_what_can_be_told_without_naming():
    personal = Lineage(requirements=(requirement(5, (ALICE,), Sensitivity.PERSONAL, told_by=(ALICE,)),))
    assert without_whom(personal, Sensitivity.PERSONAL) and not without_whom(personal, Sensitivity.ANODYNE)
    secret = Lineage(requirements=(requirement(5, (ALICE,), Sensitivity.PERSONAL, told_by=(ALICE,), secret=True),))
    assert not without_whom(secret, Sensitivity.CONFIDENCE)
    assert not without_whom(personal.model_copy(update={"internal_only": True}), Sensitivity.CONFIDENCE)
    assert not without_whom(Lineage(requirements=(Requirement(item=5),)), Sensitivity.CONFIDENCE)  # rien de connu
    twice = Lineage(requirements=(Requirement(item=5, any_of=(
        Restriction(about=(ALICE,), sensitivity=int(Sensitivity.CONFIDENCE), secret=True),
        Restriction(about=(ALICE,), sensitivity=int(Sensitivity.ANODYNE)))),))
    assert without_whom(twice, Sensitivity.ANODYNE)  # appris une fois au grand jour : ça suffit
