"""Le vrai, le contesté, le révolu (ADR 0081) : la vérité ne se juge plus avec l'audience.

Avant, une correction ne remplaçait une croyance que si leurs confidents étaient les mêmes (`_can_replace`) : Alice
qui disait elle-même « j'habite à Paris maintenant » ne remplaçait pas ce que Bob avait dit d'elle — deux croyances
contradictoires restaient actives. Désormais la vérité se juge par la sûreté de qui parle : la personne concernée,
ou un témoin de première main, ou le même qui se corrige, remplacent ; une source moins sûre conteste — elle doute,
et le dit quand les deux côtés peuvent se dire. Ce qu'elle croyait et qu'on lui redit revient. Changer d'avis
elle-même se ressent. Chaque cible échoue sur l'arbre d'avant.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

from mika.contracts import attention as attention_c
from mika.contracts import memory as mc
from mika.faculties.attention.faculty import AttentionParams, AttentionState, _revised
from mika.faculties.memory import knowledge as kn
from mika.faculties.memory.consolidation import Consolidate
from mika.faculties.memory.extraction import Conversation, Extraction, Line, People, Speaker, XCroyance
from mika.faculties.memory.faculty import MemoryParams, MemoryState
from mika.faculties.memory.knowledge import CONTEST, SUPERSEDE, judge
from mika.faculties.memory.recall import contested_line, items_by_id
from mika.kernel.events import Content
from mika.kernel.frame import Audience
from mika.vocab.privacy import Sensitivity
from tests.unit.test_knowledge_coherence import FRAME, Store

ALICE, BOB, CAROL = "user_2", "user_3", "user_4"
SPEAKERS = {ALICE: Speaker("P1", ALICE, "Alice"), BOB: Speaker("P1", BOB, "Bob"), CAROL: Speaker("P1", CAROL, "Carol")}


def believed(text, about, told_by, *, secret=False, sensitivity=2, kind="claim", holder=None, about_self=False,
             durable=False):
    return mc.BELIEVED.draft(text=Content.of(text, level=sensitivity), about=about, told_by=told_by,
                             heard_by=told_by, source=told_by[0] if told_by else None, secret=secret,
                             sensitivity=sensitivity, knowledge_kind=kind, holder=holder, about_self=about_self,
                             durable=durable)


async def said_by(db, who, text, *, personnes=(), remplace=None, genre=None, premiere_main=False, point_de_vue=None):
    """La relecture d'une conversation de ``who`` qui dit ``text`` (une croyance), désignant ``remplace`` parmi ce
    qu'elle sait déjà (la croyance n° 1, montrée)."""
    speaker = SPEAKERS[who]
    conv = Conversation(f"private:{who}", (speaker,), (Line(10000, FRAME.now, speaker.name, text, who),))
    directory = {"alice": (ALICE,), "bob": (BOB,), "carol": (CAROL,)}
    people = People.of((speaker,), directory, "Mika", scope=conv.key)
    ex = Extraction(croyances=[XCroyance(texte=text, personnes=list(personnes), messages=[10000], source="P1",
                                         remplace=remplace, genre=genre, de_premiere_main=premiere_main,
                                         point_de_vue=point_de_vue)])
    known = [(i, t) for i, t in db.query(f"SELECT id, text FROM {mc.KNOWLEDGE_VIEW} WHERE kind='belief'")]
    return await Consolidate()._drafts(ex, FRAME, MemoryState(), db, conv, people, known, [], None, MemoryParams(),
                                       "verite")


def _belief(out):
    (d,) = [d for d in out if d.type.name == mc.BELIEVED.name]
    return d.data


# ── Qui remplace, qui conteste ──────────────────────────────────────────────


def test_judge_ranks_who_speaks():
    told = kn.Testimony(1, (BOB,), (BOB,), 2, False, 0.8, origin="told")
    subject = kn.Testimony(2, (ALICE,), (ALICE,), 2, False, 0.8, origin="told", first_hand=True)
    other = kn.Testimony(3, (CAROL,), (CAROL,), 2, False, 0.8, origin="told")
    again = kn.Testimony(4, (BOB,), (BOB,), 2, False, 0.8, origin="told")
    assert judge([told], other) == CONTEST  # un autre, pas plus sûr : elle doute
    assert judge([told], subject) == SUPERSEDE  # la personne concernée : elle la croit
    assert judge([told], again) == SUPERSEDE  # le même qui se corrige
    assert judge([subject], other) == CONTEST  # un ragot ne remplace pas ce qu'Alice a dit d'elle


async def test_a_less_reliable_teller_contests_instead_of_superseding():
    db = Store()
    db.put(believed("Alice habite à Lyon", (ALICE,), (ALICE,)), 1)
    db.query("UPDATE memory_testimonies SET first_hand=1")
    d = _belief(await said_by(db, CAROL, "Alice a quitté Lyon", personnes=["Alice"], remplace=1))
    assert d.replaces is None and d.contests == 1
    db.conn.close()


async def test_the_subject_first_hand_supersedes_across_audiences():
    """Ce que Bob avait dit d'Alice, Alice le corrige elle-même : remplacé — même si Bob l'avait dit ailleurs, à
    d'autres (avant, les confidents différents laissaient deux croyances contradictoires actives)."""
    db = Store()
    db.put(believed("Alice habite à Lyon", (ALICE,), (BOB,)), 1)
    d = _belief(await said_by(db, ALICE, "Alice habite à Paris maintenant", personnes=["P1"], remplace=1))
    assert d.replaces == 1 and d.contests is None


async def test_the_same_teller_corrects_himself():
    db = Store()
    db.put(believed("Le restaurant du coin ouvre le dimanche", (BOB,), (BOB,), sensitivity=1), 1)
    d = _belief(await said_by(db, BOB, "Le restaurant du coin est fermé le dimanche", remplace=1))
    assert d.replaces == 1


async def test_another_holders_opinion_neither_supersedes_nor_contests():
    db = Store()
    db.put(believed("Le dernier Zelda est raté", (BOB,), (BOB,), kind="opinion", holder=BOB, sensitivity=1), 1)
    d = _belief(await said_by(db, CAROL, "Le dernier Zelda est génial", genre="avis", remplace=1))
    assert d.replaces is None and d.contests is None  # deux avis, deux porteurs : aucun n'a tort


# ── Ce qui est remplacé, contesté, ravivé ───────────────────────────────────


def test_a_superseded_row_points_to_its_successor_and_a_contest_is_kept_both_ways():
    db = Store()
    db.put(believed("Alice habite à Lyon", (ALICE,), (BOB,)), 1)
    db.put(mc.BELIEVED.draft(text=Content.of("Alice habite à Paris"), about=(ALICE,), told_by=(ALICE,),
                             heard_by=(ALICE,), source=ALICE, replaces=1), 2)
    assert db.query(f"SELECT status, superseded_by FROM {mc.LEDGER_VIEW} WHERE id=1") == [("superseded", 2)]
    db.put(mc.BELIEVED.draft(text=Content.of("Alice habite à Marseille"), about=(ALICE,), told_by=(CAROL,),
                             heard_by=(CAROL,), source=CAROL, contests=2), 3)
    assert sorted(db.query("SELECT item, other FROM memory_contests")) == [(2, 3), (3, 2)]
    assert db.query(f"SELECT COUNT(*) FROM {mc.KNOWLEDGE_VIEW} WHERE id IN (2, 3)") == [(2,)]  # elle doute
    db.conn.close()


async def test_saying_a_superseded_fact_again_revives_it():
    db = Store()
    db.put(believed("Le restaurant du coin ouvre le dimanche", (BOB,), (BOB,), sensitivity=1), 1)
    db.put(mc.BELIEVED.draft(text=Content.of("Le restaurant du coin est fermé le dimanche"), about=(BOB,),
                             told_by=(BOB,), heard_by=(BOB,), source=BOB, sensitivity=1, replaces=1), 2)
    out = await said_by(db, BOB, "Le restaurant du coin ouvre le dimanche")
    (back,) = [d for d in out if d.type.name == mc.ATTESTED.name]
    assert back.data.item == 1 and back.data.replaces == 2  # ce qu'elle croyait revient
    db.put(back, 3)
    assert db.query(f"SELECT id, status FROM {mc.LEDGER_VIEW} ORDER BY id") == [(1, "active"), (2, "superseded")]
    db.conn.close()


# ── Le doute, dit seulement quand les deux côtés peuvent se dire ────────────


def test_a_contest_is_voiced_only_when_both_sides_can_be_said():
    db = Store()
    db.put(believed("Alice habite à Lyon", (ALICE,), (BOB,), sensitivity=1), 1)
    db.put(mc.BELIEVED.draft(text=Content.of("Alice habite à Marseille"), about=(ALICE,), told_by=(CAROL,),
                             heard_by=(CAROL,), source=CAROL, sensitivity=1, contests=1), 2)
    friend = Audience(persons=(BOB,), public=False, level=int(Sensitivity.PERSONAL),
                      witness_level=int(Sensitivity.PERSONAL), private_ok=True)
    item = items_by_id(db, [1])[1]
    line = contested_line(FRAME, item, BOB, friend, {}, db, {CAROL: "Carol"})
    assert "Marseille" in line and "Carol" in line  # « mais Carol t'a dit autre chose »
    db.put(mc.ATTESTED.draft(item=2, told_by=(CAROL,), heard_by=(CAROL,), restricts=True, secret=True), 3)
    assert contested_line(FRAME, item, BOB, friend, {}, db, {CAROL: "Carol"}) == ""  # l'autre côté se tait
    db.conn.close()


def test_the_other_side_is_never_attributed_to_a_testimony_this_audience_cannot_hear():
    """Alice lui a confié en secret que « Inès habite à Marseille » ; Bob, à qui elle parle, le lui a dit aussi. Le doute
    sur « Inès habite à Lyon » s'attribue à Bob — c'est lui qui le lui a dit —, jamais au premier témoignage, celui
    d'Alice, que Bob ne peut pas entendre (il était repris d'office : « mais Alice t'a dit autre chose », audit du
    2026-10-12). Vu par elle-même, sans témoin qui s'entende ici : « quelqu'un »."""
    ines = "user_5"
    friend = Audience(persons=(BOB,), public=False, level=int(Sensitivity.PERSONAL),
                      witness_level=int(Sensitivity.PERSONAL), private_ok=True)
    for second, said_by in ((mc.ATTESTED.draft(item=2, told_by=(BOB,), heard_by=(BOB,), source=BOB, sensitivity=1),
                             "Bob"),
                            (mc.ATTESTED.draft(item=2, origin=mc.OBSERVED, sensitivity=1), "quelqu'un")):
        db = Store()
        db.put(believed("Inès habite à Lyon", (ines,), (CAROL,), sensitivity=1), 1)
        db.put(mc.BELIEVED.draft(text=Content.of("Inès habite à Marseille"), about=(ines,), told_by=(ALICE,),
                                 heard_by=(ALICE,), source=ALICE, sensitivity=1, secret=True, contests=1), 2)
        db.put(second, 3)
        line = contested_line(FRAME, items_by_id(db, [1])[1], BOB, friend, {}, db, {})
        assert "Marseille" in line and said_by in line and "Alice" not in line
        db.conn.close()


# ── Changer d'avis se ressent ───────────────────────────────────────────────


def _event(draft, seq):
    return NS(type=draft.type, data=draft.data, seq=seq, at=FRAME.now)


def test_changing_her_durable_opinion_is_felt_and_an_anecdote_is_not():
    cx = NS(params=AttentionParams(), facts=NS(get=lambda _r: None), now=FRAME.now)
    durable = mc.BELIEVED.draft(text=Content.of("Au fond, je préfère les lasagnes"), about_self=True, durable=True,
                                knowledge_kind="preference", replaces=1)
    s = _revised(AttentionState(), _event(durable, 5), cx)
    assert [q.origin for q in s.pending] == [attention_c.REVISION]  # changer d'avis sur ce qui la définit : ressenti
    anecdote = mc.BELIEVED.draft(text=Content.of("Finalement j'ai pas dessiné ce soir"), about_self=True,
                                 replaces=2)
    assert _revised(AttentionState(), _event(anecdote, 6), cx).pending == ()  # une anecdote : rien
