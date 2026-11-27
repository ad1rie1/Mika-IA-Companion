"""L'opératrice corrige sa mémoire depuis la console (ADR 0230, audit du 2026-11-05 : C2-01, décision C2-Q1).

Avant, une croyance fausse, une promesse tenue que la relecture n'avait pas vue, un moment annulé ne se corrigeaient
qu'en oubliant toute la personne : la mémoire n'offrait qu'une action, « Reprendre cette extraction ». Chaque
correction est maintenant un événement ajouté au journal, sur le vrai noyau : une promesse tenue ou abandonnée, une
situation finie, l'issue d'un moment, un souvenir ou une croyance démenti — et seulement là où elle a un sens.

Une correction n'est pas un moment de sa vie : une issue posée par l'opératrice ne se ressent pas, ne lui apprend rien
de qui l'avait annoncée ni de ce qu'elle en attendait, et ne compte pas pour « voir venir » ; abandonnée par
l'opératrice, une promesse n'est pas « laissée filer » ; tenue, elle compte pour « tenir parole ». Un élément démenti
sort de ce qu'elle sait, de son rappel et de l'index des vecteurs, son texte gardé au journal ; le rejeu du journal
redonne le même état ; le portrait et le récit qui le reprenaient se réécrivent sans lui.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from mika.contracts import memory as mc
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.contracts import social as social_c
from mika.faculties.memory import tables as tb
from mika.faculties.memory.faculty import MEMORY, _moment_resolved_felt
from mika.faculties.memory.inspect import BELIEFS, EPISODE_MEMORIES, STATUS_FR, STATUS_TONE
from mika.faculties.memory.params import MemoryParams
from mika.faculties.memory.projections import Items
from mika.faculties.self.faculty import SELF, SelfState
from mika.faculties.self.model import FORESIGHT, KEPT, PROMISES, SLIPPED
from mika.faculties.self.narrative import _narrated
from mika.faculties.self.narrative import _sources_withdrawn as narrative_sources_withdrawn
from mika.faculties.social.faculty import SOCIAL, SocialState, _portrait_sources, _profiled
from mika.kernel.clock import DAY, MINUTE, US
from mika.kernel.codec import digest
from mika.kernel.events import Content, Origin, VoiceProvenance
from mika.kernel.forms import RENDERED
from mika.runtime.effects import with_content
from mika.runtime.operations import FIXED_FIELD, perform
from mika.sim.clock import run_virtual
from tests.fixtures.memory import Script, event
from tests.fixtures.mika import at_paris, befriend, boot, build, connect, said
from tests.unit.test_memory_tables import DB

ALICE, BOB = "user_2", "user_3"
OPERATOR = "user_1"
START = at_paris(2026, 10, 5, 10, 0)  # un lundi matin
#: Alice demande ce qu'elle sait de son chat : la croyance qui le dit lui revient, tant qu'elle n'est pas démentie
ASKED = "tu te souviens de mon chat Moustache ?"
CANARY = "CANARI-C1"


def _form(**values: object) -> dict[str, list[str]]:
    """Le formulaire d'une action posée sur une carte : l'élément dans un champ caché, reposté tel quel ; le choix
    d'une issue, un champ rendu."""
    hidden = [k for k in values if k != "outcome"]
    return {FIXED_FIELD: hidden, RENDERED: [k for k in values if k not in hidden],
            **{k: [str(v)] for k, v in values.items()}}


async def _genesis(kernel, draft) -> int:
    commit = await kernel.mind.append([draft], emitter="memory", correlation=f"genese:{draft.type.name}",
                                      origin=Origin.GENESIS)
    return commit.seqs[-1]


def _events(kernel, *types) -> list:
    names = {t.name for t in types}
    return [kernel.mind.decode(e) for e in kernel.mind.store.read() if e.type in names]


def _status(kernel, item: int) -> str:
    t = tb.items()
    return kernel.mind.store.query_mind(select(t.c.status).where(t.c.id == item))[0][0]


def _known(kernel) -> set[int]:
    return {int(r[0]) for r in kernel.mind.store.query_mind(select(mc.KNOWLEDGE.c.id))}


def _prompt(script: Script) -> str:
    return script.replies(ALICE)[-1]


@pytest.fixture(scope="module")
def corrected(tmp_path_factory):
    """Lundi : Alice lui a confié une croyance et un souvenir, elle lui a fait deux promesses, son chat est malade
    depuis hier, Bob a annoncé l'entretien d'Alice mercredi (elle y croyait peu, et l'espérait pour elle) et un dîner
    samedi dernier. L'opératrice corrige chacun, et tente chaque geste là où il n'a pas de sens."""
    tmp = tmp_path_factory.mktemp("corrections")
    script = Script()
    kernel, clock, _llm, _out = build(tmp, script, start=START)
    box: dict = {}

    async def act(key: str, **values: object):
        return await perform(kernel, f"memory.{key}", _form(**values), by=OPERATOR)

    async def ask() -> None:
        p = await kernel.perceive(said(ALICE, ASKED))
        if p.reply is not None:
            await p.reply
        await asyncio.sleep(MINUTE / US)

    async def main():
        await boot(kernel)
        await befriend(kernel, ALICE, social_c.FRIEND)
        await connect(kernel, ALICE, "Alice")
        from_alice = {"about": (ALICE,), "told_by": (ALICE,), "heard_by": (ALICE,), "sensitivity": 1}
        souvenir = await _genesis(kernel, mc.REMEMBERED.draft(
            text=Content.of("CANARI-S1 Alice m'a montré une photo de son chat", level=1), **from_alice))
        belief = await _genesis(kernel, mc.BELIEVED.draft(
            text=Content.of(f"{CANARY} Alice a un chat qui s'appelle Moustache", level=1), source=ALICE,
            **from_alice))
        recipe = await _genesis(kernel, mc.PROMISE_NOTICED.draft(
            text=Content.of("lui envoyer la recette des crêpes", level=1), to=ALICE, due=START + 2 * DAY))
        book = await _genesis(kernel, mc.PROMISE_NOTICED.draft(
            text=Content.of("lui prêter mon livre", level=1), to=ALICE, due=START + 3 * DAY))
        sick = await _genesis(kernel, mc.EVENT_NOTED.draft(
            text=Content.of("son chat Moustache est malade", level=1), when=START - DAY, ongoing=True,
            **from_alice))
        await _genesis(kernel, mc.EVENT_NOTED.draft(  # une autre situation, qui dure encore
            text=Content.of("son déménagement", level=1), when=START - DAY, ongoing=True, **from_alice))
        hoped = {"about": (ALICE,), "told_by": (BOB,), "heard_by": (BOB,), "sensitivity": 1, "all_day": False,
                 "likelihood": 0.3, "importance": 0.9, "empathy": (("happy", 0.8),)}
        interview = await _genesis(kernel, mc.EVENT_NOTED.draft(
            text=Content.of("son entretien chez Ubisoft", level=1), when=START + 2 * DAY, **hoped))
        dinner = await _genesis(kernel, mc.EVENT_NOTED.draft(
            text=Content.of("son dîner chez ses parents", level=1), when=START - 2 * DAY, **hoped))
        await asyncio.sleep(10 * MINUTE / US)  # l'index des vecteurs suit
        await ask()
        box["before"] = {"prompt": _prompt(script), "known": _known(kernel),
                         "indexed": kernel.ports["vectors"].indexed()}
        box["ids"] = dict(souvenir=souvenir, belief=belief, recipe=recipe, book=book, sick=sick,
                          interview=interview, dinner=dinner)
        out = {}
        # ses promesses
        out["tenir"] = await act("tenir", promise=recipe)
        out["tenir encore"] = await act("tenir", promise=recipe)
        out["tenir une situation"] = await act("tenir", promise=sick)
        out["abandonner"] = await act("abandonner", promise=book)
        out["tenir sans promesse"] = await act("tenir", promise=book)
        # la vie des autres
        out["finir un moment daté"] = await act("finir", event=interview)
        out["finir"] = await act("finir", event=sick)
        out["finir encore"] = await act("finir", event=sick)
        out["issue d'une situation"] = await act("issue", event=sick, outcome=mc.HAPPENED)
        out["a eu lieu avant d'avoir lieu"] = await act("issue", event=interview, outcome=mc.HAPPENED)
        out["annulé d'avance"] = await act("issue", event=interview, outcome=mc.CANCELLED)
        out["issue encore"] = await act("issue", event=interview, outcome=mc.MOVED)
        out["a eu lieu"] = await act("issue", event=dinner, outcome=mc.HAPPENED)
        # ce qu'elle sait
        out["démentir une promesse"] = await act("dementir", item=recipe)
        out["démentir"] = await act("dementir", item=belief)
        out["démentir encore"] = await act("dementir", item=belief)
        out["démentir un souvenir"] = await act("dementir", item=souvenir)
        await asyncio.sleep(10 * MINUTE / US)
        # l'index, avant qu'un nouvel échange ne le fasse repasser : le démenti seul l'y fait revenir
        indexed = kernel.ports["vectors"].indexed()
        await ask()
        frame = kernel.mind.frame()
        box.update(
            out=out, after={"prompt": _prompt(script), "known": _known(kernel), "indexed": indexed},
            status={name: _status(kernel, i) for name, i in box["ids"].items()},
            memory=frame.state("memory"), self=frame.state("self"),
            resolved=_events(kernel, mc.PROMISE_RESOLVED, mc.SITUATION_ENDED, mc.RESOLVED, mc.RETRACTED),
            audited=_events(kernel, rt.OPERATED))
        # le rejeu : les tranches reconstruites depuis la genèse, la projection des éléments rejouée à neuf
        owners = ["memory", "self", "attention"]
        before = {o: digest(kernel.mind.root.slices[o]) for o in owners}
        await kernel.mind.rebuild(owners)
        box["replayed"] = (before, {o: digest(kernel.mind.root.slices[o]) for o in owners})
        spec = next(p for p in MEMORY.projectors if p.name == mc.ITEMS_TABLE)
        journal = [with_content(kernel.mind, kernel.mind.decode(e)) for e in kernel.mind.store.read()
                   if e.type in spec.types]
        box["journal"] = journal
        t = tb.items()
        box["live"] = sorted(kernel.mind.store.query_mind(select(t.c.id, t.c.status, t.c.text)))
        await kernel.stop()
        return box

    return run_virtual(clock, main)


def test_each_correction_writes_its_event_where_it_makes_sense(corrected):
    out, ids = corrected["out"], corrected["ids"]
    done = {k for k, o in out.items() if o.ok}
    assert done == {"tenir", "abandonner", "finir", "annulé d'avance", "a eu lieu", "démentir",
                    "démentir un souvenir"}, {k: o.message for k, o in out.items()}
    # tenter un geste là où il n'a pas de sens : un refus qui dit pourquoi, rien d'écrit
    assert "plus en cours" in out["tenir encore"].message and "plus en cours" in out["tenir une situation"].message
    assert out["tenir sans promesse"].message == "Cette action n'est pas possible en ce moment."  # plus rien à tenir
    assert "pas une situation en cours" in out["finir un moment daté"].message
    assert "déjà finie" in out["finir encore"].message
    assert "Seul un moment daté" in out["issue d'une situation"].message
    assert "pas encore commencé" in out["a eu lieu avant d'avoir lieu"].message
    assert "déjà une issue" in out["issue encore"].message
    assert "Seul un souvenir ou une croyance" in out["démentir une promesse"].message
    assert "déjà plus" in out["démentir encore"].message
    written = [(e.type.name, getattr(e.data, "promise", None) or getattr(e.data, "event", None)
                or e.data.item, getattr(e.data, "status", None) or getattr(e.data, "outcome", None),
                getattr(e.data, "by", None)) for e in corrected["resolved"]]
    assert written == [
        (mc.PROMISE_RESOLVED.name, ids["recipe"], mc.HONORED, mc.OPERATOR_BY),
        (mc.PROMISE_RESOLVED.name, ids["book"], mc.DROPPED, mc.OPERATOR_BY),
        (mc.SITUATION_ENDED.name, ids["sick"], None, None),
        (mc.RESOLVED.name, ids["interview"], mc.CANCELLED, mc.OPERATOR_BY),
        (mc.RESOLVED.name, ids["dinner"], mc.HAPPENED, mc.OPERATOR_BY),
        (mc.RETRACTED.name, ids["belief"], None, mc.OPERATOR_BY),
        (mc.RETRACTED.name, ids["souvenir"], None, mc.OPERATOR_BY),
    ]
    # chaque geste tenté est audité, refus compris, sous la clé de son action et au nom de qui agit (une action
    # qui n'est pas offerte ne s'exécute pas : rien à auditer)
    audited = [(e.data.action, e.data.outcome, e.data.seqs) for e in corrected["audited"]
               if e.data.action.startswith("memory.")]
    assert len(audited) == len(out) - 1
    assert [(a, o) for a, o, seqs in audited if seqs] == [(a, "done") for a in (
        "memory.tenir", "memory.abandonner", "memory.finir", "memory.issue", "memory.issue", "memory.dementir",
        "memory.dementir")]
    assert ("memory.dementir", "refused", ()) in audited
    assert {e.data.by for e in corrected["audited"] if e.data.action.startswith("memory.")} == {OPERATOR}
    # et l'élément garde ce que la projection en dit : tenue, abandonnée, finie
    status = corrected["status"]
    assert (status["recipe"], status["book"], status["sick"]) == (mc.HONORED, mc.DROPPED, "ended")


def test_an_outcome_set_by_the_operator_is_neither_felt_nor_learned_from(corrected):
    """Annulé un entretien qu'elle espérait pour Alice, eu lieu un dîner qu'elle ne croyait pas : par la relecture,
    l'un attristerait et surprendrait, les deux lui apprendraient de Bob et de ses attentes, et compteraient pour
    « voir venir ». Posés par l'opératrice, rien de tout cela — mais elle sait comment ils ont tourné."""
    m, ids = corrected["memory"], corrected["ids"]
    assert m.events[ids["interview"]].outcome == mc.CANCELLED and m.events[ids["dinner"]].outcome == mc.HAPPENED
    assert BOB not in m.track and dict(m.calibration) == {}
    issues = [e for e in corrected["resolved"] if e.type.name == mc.RESOLVED.name]
    for e in issues:
        assert (e.data.likelihood, e.data.surprise, e.data.valence, e.data.nature, e.data.teller) == \
            (None, 0.0, 0.0, "", ""), e.data
    cx = NS(params=MemoryParams(), facts=NS(get=lambda _r: 1.0), now=START, tz=ZoneInfo("Europe/Paris"))
    assert [_moment_resolved_felt(e, cx) for e in issues] == [None, None]
    assert not [mark for mark in corrected["self"].record if mark.domain == FORESIGHT]


def test_a_promise_dropped_by_the_operator_did_not_slip_and_one_kept_counts(corrected):
    marks = {(mark.ref, mark.outcome) for mark in corrected["self"].record if mark.domain == PROMISES}
    ids = corrected["ids"]
    assert (ids["recipe"], KEPT) in marks  # « tenir parole »
    assert not {(ref, out) for ref, out in marks if ref == ids["book"]}  # ni tenue, ni laissée filer
    assert SLIPPED not in {out for _ref, out in marks}
    assert not corrected["memory"].promises


def test_a_denied_belief_leaves_what_she_knows_her_recall_and_the_index(corrected):
    before, after, ids = corrected["before"], corrected["after"], corrected["ids"]
    assert CANARY in before["prompt"], "le témoin : avant le démenti, la croyance lui revient"
    assert CANARY not in after["prompt"]
    for name in ("belief", "souvenir"):
        item = ids[name]
        assert item in before["known"] and item not in after["known"]
        assert item in before["indexed"] and item not in after["indexed"]
        assert corrected["status"][name] == mc.RETRACTED_STATUS
    # rien ne s'efface : son texte reste, au journal comme sur sa ligne
    live = {i: text for i, _status, text in corrected["live"]}
    assert CANARY in live[ids["belief"]]
    assert any(e.seq == ids["belief"] and CANARY in e.data.text.text for e in corrected["journal"])


def test_the_replayed_journal_gives_the_same_state(corrected):
    before, after = corrected["replayed"]
    assert before == after
    db = DB()
    Items().apply(db, corrected["journal"], "")
    t = tb.items()
    assert sorted(db.query(select(t.c.id, t.c.status, t.c.text))) == corrected["live"]


def test_a_denied_item_is_said_and_offered_to_the_filter():
    assert mc.RETRACTED_STATUS in mc.FORMER_STATUSES
    assert STATUS_TONE[mc.RETRACTED_STATUS] == "muted" and "opératrice" in STATUS_FR[mc.RETRACTED_STATUS]
    assert dict(EPISODE_MEMORIES.statuses)[mc.RETRACTED_STATUS] == "démenti"
    assert dict(BELIEFS.statuses)[mc.RETRACTED_STATUS] == "démentie"


def test_only_an_item_she_still_holds_can_be_denied():
    """La projection ne démentit qu'un souvenir ou une croyance encore actif : un élément remplacé reste remplacé,
    une promesse reste ce qu'elle est."""
    db = DB()
    from_alice = {"about": (ALICE,), "told_by": (ALICE,), "sensitivity": 1}
    drafts = [mc.BELIEVED.draft(text=Content.of("Alice habite à Lyon", level=1), **from_alice),
              mc.BELIEVED.draft(text=Content.of("Alice habite à Nantes", level=1), replaces=1, **from_alice),
              mc.PROMISE_NOTICED.draft(text=Content.of("lui écrire", level=1), to=ALICE),
              mc.RETRACTED.draft(item=1), mc.RETRACTED.draft(item=2), mc.RETRACTED.draft(item=3)]
    Items().apply(db, [event(d, i, i * DAY) for i, d in enumerate(drafts, 1)], "")
    t = tb.items()
    assert dict(db.query(select(t.c.id, t.c.status))) == {1: "superseded", 2: mc.RETRACTED_STATUS, 3: "pending"}
    assert [int(r[0]) for r in db.query(select(mc.KNOWLEDGE.c.id))] == [3]
    assert [int(r[0]) for r in db.query(select(mc.FORMER.c.id).order_by(mc.FORMER.c.id))] == [1, 2]


def test_what_was_written_from_a_denied_item_is_rewritten_without_it():
    """Le portrait d'Alice et son récit reprenaient la croyance que l'opératrice dément : comme pour une source
    remplacée, ils se réécrivent sans la recopier (ADR 0082) — sans se taire, rien n'est devenu secret. Une seule
    définition (``withdrawals``), que reçoit chaque faculté qui garde un texte dérivé."""
    denied = mc.RETRACTED.draft(item=5)
    assert mc.withdrawals(denied.type.name, denied.data, 9) == (mc.Withdrawal(5, mc.SUPERSEDED),)
    assert mc.RETRACTED in mc.WITHDRAWING
    for faculty, fn in ((SOCIAL, _portrait_sources), (SELF, narrative_sources_withdrawn)):
        assert any(mc.RETRACTED in r.types and r.fn is fn for r in faculty.reducers), faculty.name
    cx = NS(params=None, facts=NS(get=lambda _r: None), now=START)

    def ev(draft, seq: int):
        return NS(type=draft.type, data=draft.data, seq=seq, at=START)

    portrait = _profiled(SocialState(), ev(social_c.PROFILE_REVISED.draft(
        person=ALICE, summary=Content(ref="portrait"), upto=6, sources=(5, 6)), 8), cx)
    narrated = _narrated(SelfState(), ev(self_c.NARRATED.draft(text=Content(ref="récit"), voice=VoiceProvenance(
        call_id="x", persona_hash="-", role="narrative", model="-"), sources=(5, 6)), 8), cx)
    assert not portrait.profiles[ALICE].stale and not narrated.narrative_stale  # le témoin
    # un élément qu'ils ne reprenaient pas, démenti : rien ne change
    elsewhere = ev(mc.RETRACTED.draft(item=7), 9)
    assert not _portrait_sources(portrait, elsewhere, cx).profiles[ALICE].stale
    assert not narrative_sources_withdrawn(narrated, elsewhere, cx).narrative_stale
    portrait = _portrait_sources(portrait, ev(denied, 10), cx)
    narrated = narrative_sources_withdrawn(narrated, ev(denied, 10), cx)
    assert portrait.profiles[ALICE].stale and not portrait.profiles[ALICE].masked
    assert narrated.narrative_stale and not narrated.narrative_masked
