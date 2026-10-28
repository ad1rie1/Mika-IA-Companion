"""Une proposition, des témoignages (ADR 0080) : la même chose dite par deux personnes est une seule croyance, que
chacune a confiée à sa façon.

Avant, ce qu'Alice et Bob disaient pareil faisait deux lignes : la confiance ne se cumulait pas, et la plus stricte
des deux décidait seule (le secret d'Alice taisait ce que Bob avait dit devant tout le monde) — ou l'inverse, selon
la ligne que le rappel trouvait d'abord. Désormais elle peut en parler là où un témoignage le permet, en l'attribuant
à ce témoin, sans laisser deviner l'autre ; la personne concernée qui demande la discrétion ferme tout ; ce que la
même personne redit ne la rend pas plus sûre ; la nuit réunit les doublons de son journal. Chaque cible échoue sur
l'arbre d'avant.
"""

from __future__ import annotations

from mika.contracts import memory as mc
from mika.contracts import transcript as transcript_c
from mika.faculties.memory import consolidation as cons
from mika.faculties.memory import knowledge as kn
from mika.faculties.memory.extraction import Conversation, Extraction, People, XCroyance
from mika.faculties.memory.faculty import MemoryParams, MemoryState
from mika.faculties.memory.knowledge import pooled
from mika.faculties.memory.night import joinable_pairs
from mika.faculties.memory.projections import TESTIMONIES_TABLE, Items
from mika.faculties.memory.recall import heard_confidence, items_by_id, verdict_of
from mika.faculties.social.faculty import SocialState, _knit
from mika.kernel.builtin import SUBJECT_FORGOTTEN
from mika.kernel.events import Content
from mika.kernel.frame import Audience
from mika.vocab.privacy import Sensitivity
from tests.unit.test_knowledge_coherence import ALICE as ALICE_SPEAKS
from tests.unit.test_knowledge_coherence import CX, FRAME, Store, alice_says, drafts, event

ALICE, BOB, CAROL, INES = "user_2", "user_3", "user_4", "user_5"
FRIEND = Audience(persons=(CAROL,), public=False, level=int(Sensitivity.PERSONAL),
                  witness_level=int(Sensitivity.PERSONAL), private_ok=True)


def believed(text, about, told_by, *, secret=False, sensitivity=2, confidence=0.8, relations=()):
    return mc.BELIEVED.draft(text=Content.of(text, level=sensitivity), about=about, told_by=told_by,
                             heard_by=told_by, source=told_by[0] if told_by else None, secret=secret,
                             sensitivity=sensitivity, confidence=confidence, relations=relations)


def attested(item, told_by, *, secret=False, sensitivity=2, confidence=0.8, **kw):
    return mc.ATTESTED.draft(item=item, told_by=told_by, heard_by=told_by, source=told_by[0] if told_by else None,
                             secret=secret, sensitivity=sensitivity, confidence=confidence, **kw)


def item(db, i):
    return items_by_id(db, [i])[i]


def to(person):
    return Audience(persons=(person,), public=False, level=int(Sensitivity.PERSONAL),
                    witness_level=int(Sensitivity.PERSONAL), private_ok=True)


# ── Une proposition, plusieurs témoignages ──────────────────────────────────


async def test_a_second_teller_attests_instead_of_a_second_row():
    db = Store()
    db.put(believed("Alice a eu une promotion", (ALICE,), (CAROL,)), 1)
    ex = Extraction(croyances=[XCroyance(texte="Alice a eu une promotion", personnes=["P1"], messages=[10000],
                                         source="P1")])
    out = await drafts(db, ex, (alice_says("j'ai eu une promotion !"),))
    beliefs = [d for d in out if d.type.name == mc.BELIEVED.name]
    testimonies = [d for d in out if d.type.name == mc.ATTESTED.name]
    assert beliefs == [] and [d.data.item for d in testimonies] == [1]  # la même chose, de sa bouche
    assert testimonies[0].data.told_by == (ALICE,)
    db.conn.close()


def test_the_same_teller_repeating_adds_no_confidence():
    db = Store()
    db.put(believed("Le restaurant du coin ferme", (), (CAROL,), sensitivity=1), 1)
    db.put(attested(1, (CAROL,), sensitivity=1), 2)
    db.put(attested(1, (CAROL,), sensitivity=1), 3)
    assert abs(item(db, 1).confidence - 0.8) < 1e-9  # redit par la même : pas plus sûre
    db.put(attested(1, (BOB,), sensitivity=1), 4)
    assert 0.85 < item(db, 1).confidence <= 0.95  # dit par un autre : plus sûre, bornée
    rows = db.query(f"SELECT COUNT(*) FROM {TESTIMONIES_TABLE} WHERE item=1")
    assert rows[0][0] == 2  # deux témoins, deux témoignages
    db.conn.close()
    # … et la mise en commun ne compte qu'une fois chaque témoin, même noté deux fois
    twice = [kn.Testimony(seq, (CAROL,), (CAROL,), 1, False, 0.8) for seq in (1, 2)]
    assert abs(pooled(twice) - 0.8) < 1e-9
    assert pooled([*twice, kn.Testimony(3, (BOB,), (BOB,), 1, False, 0.8)]) > 0.85


# ── Là où un témoignage le permet ───────────────────────────────────────────


def test_she_may_say_it_where_bobs_testimony_allows_and_names_only_bob():
    """Alice a confié en secret qu'Inès quitte la boîte ; Bob le dit aussi, sans secret. Devant Carol, une amie :
    elle peut en parler, attribué à Bob — jamais à Alice."""
    db = Store()
    db.put(believed("Inès quitte la boîte", (INES,), (ALICE,), secret=True), 1)
    db.put(attested(1, (BOB,)), 2)
    verdict = verdict_of(FRAME, item(db, 1), CAROL, FRIEND, {}, db)
    assert verdict.ok and verdict.tellers == (BOB,) and not verdict.secret
    db.conn.close()


def test_nothing_passes_when_no_testimony_admits_it():
    db = Store()
    db.put(believed("Inès quitte la boîte", (INES,), (ALICE,), secret=True), 1)
    db.put(attested(1, (BOB,), secret=True), 2)
    assert not verdict_of(FRAME, item(db, 1), CAROL, FRIEND, {}, db).ok
    db.conn.close()


def test_the_subject_asking_discretion_closes_every_testimony():
    db = Store()
    db.put(believed("Inès quitte la boîte", (INES,), (BOB,)), 1)
    db.put(attested(1, (CAROL,)), 2)
    assert verdict_of(FRAME, item(db, 1), ALICE, to(ALICE), {}, db).ok  # contrôle : ça se disait
    db.put(attested(1, (CAROL,), restricts=True, secret=True), 3)  # Carol, pas concernée : son témoignage seul
    assert verdict_of(FRAME, item(db, 1), ALICE, to(ALICE), {}, db).ok
    db.put(attested(1, (INES,), restricts=True, secret=True, everyone=True), 4)  # Inès elle-même : tout se ferme
    assert not verdict_of(FRAME, item(db, 1), ALICE, to(ALICE), {}, db).ok
    db.conn.close()


def test_the_subjects_discretion_closes_what_others_say_afterwards():
    """« Garde-le pour toi », demandé par Inès sur ce qu'elle vit : ce que Bob en dira ensuite, ouvertement, ne
    l'ouvre pas (sonde réelle du 2026-10-09 : la rumeur d'un collègue n'atteignait pas la discrétion demandée)."""
    db = Store()
    db.put(believed("Inès quitte la boîte", (INES,), (INES,)), 1)
    db.put(attested(1, (INES,), restricts=True, secret=True, everyone=True), 2)
    db.put(attested(1, (BOB,)), 3)  # plus tard, Bob le dit, sans secret
    assert not verdict_of(FRAME, item(db, 1), CAROL, FRIEND, {}, db).ok
    assert verdict_of(FRAME, item(db, 1), INES, to(INES), {}, db).ok  # Inès, elle, peut en reparler
    db.conn.close()


async def test_discretion_asked_by_the_person_concerned_is_for_everyone():
    db = Store()
    db.put(believed("Alice quitte la boîte", (ALICE,), (BOB,)), 1)
    conv = Conversation("private:user_2", ALICE_SPEAKS, (alice_says("garde ça pour toi stp"),))
    people = People.of(ALICE_SPEAKS, {}, "Mika", scope=conv.key)
    out = await cons._drafts(Extraction(confidentiel=[1]), FRAME, MemoryState(), db, conv, people,
                             [(1, "Alice quitte la boîte")], [], None, MemoryParams(), "audit")
    (closing,) = [d for d in out if d.type.name == mc.ATTESTED.name]
    assert closing.data.restricts and closing.data.everyone and closing.data.item == 1
    db.conn.close()


async def test_discretion_also_closes_the_souvenir_of_the_same_words():
    """« Garde-le pour toi », dit après coup : le souvenir né du même message se ferme avec la croyance (sonde réelle
    du 2026-10-09 : « Alice m'a dit qu'elle allait quitter sa boîte » restait dicible à toute amie, et le portrait le
    reprenait). Un souvenir né d'un autre de ses messages reste ouvert."""
    db = Store()
    for seq, text in ((71, "je quitte ma boîte, j'ai signé ailleurs"), (72, "et j'ai adopté un chat")):
        db.execute(f"INSERT INTO {transcript_c.THREAD_TABLE}(id,at,role,person,text,room) VALUES(?,?,?,?,?,?)",
                   (seq, FRAME.now, "user", ALICE, text, None))

    def remembered(text, sources):
        return mc.REMEMBERED.draft(text=Content.of(text, level=2), about=(ALICE,), told_by=(ALICE,),
                                   heard_by=(ALICE,), sensitivity=2, sources=sources)

    db.put(remembered("Alice m'a dit qu'elle quittait sa boîte, elle a signé ailleurs", (71, 75)), 1)
    db.put(remembered("Alice m'a parlé de son nouveau chat", (72,)), 2)
    db.put(mc.BELIEVED.draft(text=Content.of("Alice quitte sa boîte"), about=(ALICE,), told_by=(ALICE,),
                             heard_by=(ALICE,), source=ALICE, sensitivity=2, sources=(71,)), 3)
    assert verdict_of(FRAME, item(db, 1), CAROL, FRIEND, {}, db).ok  # contrôle : il se disait à une amie
    conv = Conversation("private:user_2", ALICE_SPEAKS, (alice_says("garde-le pour toi stp", seq=80),))
    people = People.of(ALICE_SPEAKS, {}, "Mika", scope=conv.key)
    out = await cons._drafts(Extraction(confidentiel=[3]), FRAME, MemoryState(), db, conv, people,
                             [(3, "Alice quitte sa boîte")], [], None, MemoryParams(), "audit")
    assert [d.data.item for d in out if d.type.name == mc.REINFORCED.name] == [1]  # pas le souvenir du chat
    for n, d in enumerate(out, start=4):
        db.put(d, n)
    assert not verdict_of(FRAME, item(db, 1), CAROL, FRIEND, {}, db).ok
    assert verdict_of(FRAME, item(db, 1), ALICE, to(ALICE), {}, db).ok  # Alice peut en reparler
    assert verdict_of(FRAME, item(db, 2), CAROL, FRIEND, {}, db).ok
    db.conn.close()


def test_a_legacy_reinforcement_never_widens_diffusion():
    db = Store()
    db.put(believed("Inès quitte la boîte", (INES,), (ALICE,), secret=True), 1)
    # un ancien renfort qui nommait Bob, sans secret : il compte pour la confiance, il n'ouvre rien
    db.put(mc.REINFORCED.draft(item=1, corroborated=True, source=BOB, told_by=(BOB,), heard_by=(BOB,)), 2)
    assert not verdict_of(FRAME, item(db, 1), CAROL, FRIEND, {}, db).ok
    db.conn.close()


def test_pooled_confidence_ignores_testimonies_this_audience_cannot_hear():
    db = Store()
    db.put(believed("Inès quitte la boîte", (INES,), (ALICE,), secret=True), 1)
    db.put(attested(1, (BOB,)), 2)
    it = item(db, 1)
    for_carol = heard_confidence(FRAME, it, CAROL, FRIEND, {}, db)
    for_alice = heard_confidence(FRAME, it, ALICE, to(ALICE), {}, db)
    assert abs(for_carol - 0.8) < 1e-9  # devant Carol, seulement ce que Bob a dit
    assert for_alice > for_carol  # devant Alice, ses deux témoins
    db.conn.close()


# ── L'oubli d'un témoin ─────────────────────────────────────────────────────


def test_forgetting_a_second_teller_removes_their_testimony_even_after_a_rebuild():
    db = Store()
    events = [db.put(believed("Le restaurant du coin ferme", (), (CAROL,), sensitivity=1), 1),
              db.put(attested(1, (BOB,), sensitivity=1), 2)]
    Items().forget(db, BOB, "")
    assert db.query(f"SELECT told_by FROM {TESTIMONIES_TABLE} WHERE item=1") == [('["user_4"]',)]
    forgot = event(SUBJECT_FORGOTTEN.draft(subject=BOB), 3)
    Items().drop(db, "")
    Items().create(db, "")
    Items().apply(db, [*events, forgot], "")
    assert db.query(f"SELECT told_by FROM {TESTIMONIES_TABLE} WHERE item=1") == [('["user_4"]',)]
    db.conn.close()


# ── La nuit réunit les doublons ─────────────────────────────────────────────


def test_the_night_joins_legacy_twins_and_social_edges_follow():
    db = Store()
    tie = mc.Relation(subject=ALICE, other=BOB, kind="friend", status="active")
    first = db.put(believed("Alice est amie avec Bob", (ALICE, BOB), (CAROL,), relations=(tie,)), 1)
    second = db.put(believed("Alice est amie avec Bob", (ALICE, BOB), (INES,), relations=(tie,)), 2)
    social = _knit(_knit(SocialState(), first, CX), second, CX)
    pairs = joinable_pairs(db, MemoryParams())
    assert pairs == ((1, 2),)
    joined = db.put(mc.JOINED.draft(night="2026-10-08", pairs=pairs), 3)
    social = _knit(social, joined, CX)
    assert db.query(f"SELECT status FROM {mc.LEDGER_VIEW} WHERE id=2") == [("joined",)]
    assert sorted(db.query(f"SELECT told_by FROM {TESTIMONIES_TABLE} WHERE item=1")) == [('["user_4"]',),
                                                                                        ('["user_5"]',)]
    assert {e.item for edges in social.relations.values() for e in edges.values()} == {1}
    assert db.query(f"SELECT id FROM {mc.KNOWLEDGE_VIEW} WHERE kind='belief'") == [(1,)]
    db.conn.close()


def test_twins_of_different_natures_are_not_joined():
    db = Store()
    db.put(believed("Le restaurant du coin ferme", (), (CAROL,), sensitivity=1), 1)
    db.put(mc.BELIEVED.draft(text=Content.of("Le restaurant du coin ferme"), told_by=(BOB,), heard_by=(BOB,),
                             source=BOB, knowledge_kind="hypothesis"), 2)
    assert joinable_pairs(db, MemoryParams()) == ()
    db.conn.close()

