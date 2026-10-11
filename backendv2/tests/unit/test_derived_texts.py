"""Ce qui en dérive (ADR 0082) : un texte qu'elle a tiré de ce qu'elle sait suit ses sources.

Avant, un portrait, son récit d'elle-même, une pensée, un rêve, son journal gardaient ce qu'ils avaient repris d'un
élément devenu secret, ou remplacé, depuis : le portrait de Sam disait encore ce que Sam venait de demander de taire,
le récit se réécrivait en recopiant l'ancien. Un résumé de salon gardait un secret dit dans le salon, et survivait à
l'oubli d'un participant. Chaque cible échoue sur l'arbre d'avant.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

from mika.contracts import memory as mc
from mika.contracts import self_ as self_c
from mika.contracts import social as sc
from mika.contracts import transcript as tc
from mika.faculties.attention.faculty import AttentionState, Thought, _sources_withdrawn
from mika.faculties.self import SelfState
from mika.faculties.self.narrative import _narrated
from mika.faculties.self.narrative import _sources_withdrawn as self_withdrawn
from mika.faculties.self.night import dream_hearable, journal_ref
from mika.faculties.self.records import Dream, Journal
from mika.faculties.social.faculty import SocialState, _portrait_sources, _profiled
from mika.faculties.social.profile import Revise
from mika.faculties.transcript import TranscriptState, _compact_lines, _compacted, _speaker_forgotten
from mika.kernel.builtin import SUBJECT_FORGOTTEN
from mika.kernel.events import Content, VoiceProvenance
from mika.kernel.frame import Audience
from mika.kernel.state import FrozenDict
from mika.vocab.lineage import Lineage, requirement
from mika.vocab.privacy import Sensitivity
from tests.unit.test_knowledge_coherence import FRAME

SAM, BOB = "user_2", "user_3"
CX = NS(params=None, facts=NS(get=lambda _r: None), now=FRAME.now)
PRIVATE = Audience(persons=(SAM,), public=False, level=int(Sensitivity.CONFIDENCE),
                   witness_level=int(Sensitivity.CONFIDENCE), private_ok=True)


def _event(draft, seq=99):
    return NS(type=draft.type, data=draft.data, seq=seq, at=FRAME.now)


SECRET_5 = mc.ATTESTED.draft(item=5, told_by=(SAM,), heard_by=(SAM,), restricts=True, secret=True)
REPLACED_5 = mc.BELIEVED.draft(text=Content(ref="r"), about=(SAM,), told_by=(SAM,), replaces=5)


# ── Une seule définition ────────────────────────────────────────────────────


def test_every_withdrawal_is_known_from_its_event():
    def of(draft, seq=9):
        return mc.withdrawals(draft.type.name, draft.data, seq)

    assert of(SECRET_5) == (mc.Withdrawal(5, mc.SECRET),)
    assert of(REPLACED_5) == (mc.Withdrawal(5, mc.SUPERSEDED, 9),)
    assert of(mc.BELIEVED.draft(text=Content(ref="r"), contests=4)) == (mc.Withdrawal(4, mc.CONTESTED, 9),)
    assert of(mc.JOINED.draft(night="n", pairs=((1, 2),))) == (mc.Withdrawal(2, mc.JOINED_TO, 1),)
    assert of(mc.NIGHT_SORTED.draft(night="n", merges=((1, 3),))) == (mc.Withdrawal(3, mc.JOINED_TO, 1),)
    assert of(mc.SITUATION_ENDED.draft(event=7)) == (mc.Withdrawal(7, mc.ENDED),)
    assert of(mc.REINFORCED.draft(item=8, secret=True)) == (mc.Withdrawal(8, mc.SECRET),)
    assert of(mc.ATTESTED.draft(item=1, told_by=(BOB,))) == ()  # un témoignage de plus ne retire rien
    assert set(mc.WITHDRAWING) >= {mc.BELIEVED, mc.ATTESTED, mc.REINFORCED, mc.JOINED, mc.NIGHT_SORTED}


# ── Une pensée ──────────────────────────────────────────────────────────────


def _thought(lineage):
    return Thought(40, "t", "confused", 0.5, FRAME.now, FRAME.now, "revision", (SAM,), 2, lineage=lineage)


def test_a_thought_whose_source_became_secret_is_forgotten():
    s = AttentionState(thoughts=FrozenDict({40: _thought(Lineage(sources=(5, 6)))}))
    assert 40 in _sources_withdrawn(s, _event(REPLACED_5), CX).thoughts  # remplacée : c'est son histoire
    assert 40 not in _sources_withdrawn(s, _event(SECRET_5), CX).thoughts  # devenue secrète : elle s'oublie
    legacy = AttentionState(thoughts=FrozenDict({40: _thought(None)}))
    assert 40 in _sources_withdrawn(legacy, _event(SECRET_5), CX).thoughts  # une pensée d'avant : l'ancienne règle


# ── Un rêve, son journal ────────────────────────────────────────────────────


def _lineage():
    return Lineage(sources=(5,), requirements=(requirement(5, (SAM,), 2, told_by=(SAM,), heard_by=(SAM,)),))


def test_a_dream_or_a_journal_whose_source_became_secret_is_not_told():
    frame = NS(get=lambda _r: "")
    dream = Dream(30, "2026-10-07", "rêve", "pleasant", 0.9, "happy", (SAM,), 2, FRAME.now, lineage=_lineage())
    journal = Journal("2026-10-07", "intime", (SAM,), "happy", FRAME.now, shareable_ref="partageable",
                      lineage=_lineage())
    s = SelfState(dreams=(dream,), journals=FrozenDict({"2026-10-07": journal}))

    def reading(state):
        d, j = state.dreams[0], state.journals["2026-10-07"]
        return (self_c.DreamReading(d.id, d.night, d.text_ref, d.kind, d.vividness, d.emotion, d.about,
                                    d.sensitivity, d.recalled, d.lineage, d.masked),
                self_c.JournalReading(j.day, j.text_ref, j.about, j.dominant, j.shareable_ref, j.lineage, j.masked))

    d0, j0 = reading(s)
    assert dream_hearable(d0, SAM, PRIVATE, frame) and journal_ref(j0, SAM, PRIVATE, frame) == "intime"  # contrôle
    d1, j1 = reading(self_withdrawn(s, _event(SECRET_5), CX))
    assert not dream_hearable(d1, SAM, PRIVATE, frame)
    assert journal_ref(j1, SAM, PRIVATE, frame) == "partageable"


# ── Son récit d'elle-même ───────────────────────────────────────────────────


def _narration(sources):
    return mc_event(self_c.NARRATED.draft(text=Content(ref="récit"), voice=VoiceProvenance(
        call_id="x", persona_hash="-", role="narrative", model="-"), souvenirs=3, sources=sources))


def mc_event(draft, seq=50):
    return NS(type=draft.type, data=draft.data, seq=seq, at=FRAME.now)


def test_the_narrative_hides_and_rewrites_when_a_source_becomes_secret():
    s = _narrated(SelfState(), _narration((5, 6)), CX)
    assert not s.narrative_masked and not s.narrative_stale
    secret = self_withdrawn(s, _event(SECRET_5), CX)
    assert secret.narrative_masked and secret.narrative_stale  # il se tait, et se réécrit
    replaced = self_withdrawn(s, _event(REPLACED_5), CX)
    assert replaced.narrative_stale and not replaced.narrative_masked  # remplacé : il se réécrit sans se recopier
    joined = self_withdrawn(s, _event(mc.JOINED.draft(night="n", pairs=((1, 5),))), CX)
    assert not joined.narrative_stale  # joint à la même croyance : rien n'a changé


# ── Un portrait ─────────────────────────────────────────────────────────────


def _portrait():
    revised = sc.PROFILE_REVISED.draft(person=SAM, summary=Content(ref="portrait"), upto=6, sources=(5, 6))
    return _profiled(SocialState(), mc_event(revised), CX)


def test_a_fact_made_secret_masks_the_portrait_at_once():
    s = _portrait()
    assert not s.profiles[SAM].masked
    s = _portrait_sources(s, _event(SECRET_5), CX)
    assert s.profiles[SAM].masked and s.profiles[SAM].stale


class _Store:
    def content(self, refs):
        return {r: "Sam est cuisinier, il habite à Lyon." for r in refs}


def test_a_replaced_fact_is_not_fed_back_to_the_next_portrait():
    frame = NS(get=lambda r: NS(name="Sam") if r.name == "identity.identity" else NS(name="Mika", nature="ai"))
    fresh = _portrait()
    prompt = Revise()._prompt(frame, fresh, SAM, [(7, "Sam cuisine", 0.5)], _Store())
    assert "Sam est cuisinier" in prompt  # contrôle : le portrait d'avant se redonne
    stale = _portrait_sources(fresh, _event(REPLACED_5), CX)
    prompt = Revise()._prompt(frame, stale, SAM, [(7, "Sam cuisine", 0.5)], _Store())
    assert "Sam est cuisinier" not in prompt


# ── Un résumé de salon ──────────────────────────────────────────────────────


def test_a_room_summary_names_who_spoke_so_that_forgetting_them_erases_it():
    assert "speakers" in tc.COMPACTED.subject_fields
    s = _compacted(TranscriptState(), mc_event(tc.COMPACTED.draft(
        person="room:salon", upto=40, summary=Content(ref="résumé"), speakers=(SAM, BOB))), CX)
    s = _speaker_forgotten(s, mc_event(SUBJECT_FORGOTTEN.draft(subject=BOB)), CX)
    assert "room:salon" not in s.summaries
    legacy = replace_summaries({"room:vieux": (10, "r")})
    assert "room:vieux" not in _speaker_forgotten(legacy, mc_event(SUBJECT_FORGOTTEN.draft(subject=BOB)), CX).summaries


def replace_summaries(summaries):
    return TranscriptState(summaries=FrozenDict(summaries))


def test_a_secret_said_in_a_room_is_not_kept_by_its_summary():
    frame = NS(get=lambda r: NS(name="Sam") if r.name == "identity.identity" else NS(name="Mika", nature="ai"),
               env=NS(tz_of=lambda _r: FRAME.env.tz_of(None)), root=None, now=FRAME.now)
    rows = [{"id": 10, "at": FRAME.now - 600, "role": "user", "person": SAM, "text": "CANARI je change de boulot"},
            {"id": 11, "at": FRAME.now - 500, "role": "user", "person": SAM, "text": "et sinon ça va"}]
    lines = _compact_lines(frame, "room:salon", rows, 20 * 60 * 10**6, withheld={10})
    assert "CANARI" not in lines and "et sinon ça va" in lines
