"""Voir venir, constater (ADR 0086) : comment un moment a tourné, ce qu'elle en attendait, ce qu'elle en apprend, et ce
qu'elle ressent de ce qui approche.

Avant, rien ne gardait l'issue d'un moment : « reporté » n'était qu'une date qui change, « annulé » n'existait pas, et
« alors, ça s'est passé comment ? » se demandait même pour un entretien annulé. Elle n'apprenait rien de qui reporte
tout, ne parlait jamais plus prudemment quand ses attentes se trompaient, n'attendait rien avec espoir ni crainte, et
un moment vécu à travers quelqu'un (« je te montrerai tout ») ne devenait jamais un souvenir à elle. Chaque cible
échoue sur l'arbre d'avant.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from mika.contracts import memory as mc
from mika.contracts import social as social_c
from mika.faculties.attention.anticipation import _anticipated_felt, _anticipation
from mika.faculties.attention.faculty import AttentionParams, AttentionState
from mika.faculties.goals.faculty import GoalsParams, GoalsState
from mika.faculties.goals.tend import Seed
from mika.faculties.memory import likelihood as lk
from mika.faculties.memory.consolidation import Consolidate
from mika.faculties.memory.extraction import (
    Conversation,
    Extraction,
    Line,
    People,
    Speaker,
    XConstat,
    XEvenement,
)
from mika.faculties.memory.faculty import (
    MemoryParams,
    MemoryState,
    _ahead,
    _moment_resolved,
    _moment_resolved_felt,
    _to_check,
)
from mika.faculties.memory.recall import Moment, Recall, _ahead_moments, _moment_line, _moments
from mika.faculties.memory.recall import _ahead as ahead_section
from mika.faculties.memory.reread import expired
from mika.faculties.memory.tables import life
from mika.faculties.others.faculty import OthersParams, _cheer_window
from mika.kernel.clock import DAY, HOUR
from mika.kernel.events import Content, Origin
from mika.kernel.frame import Audience
from mika.kernel.state import FrozenDict
from mika.ports.sql import json_field
from mika.sim.clock import run_virtual
from mika.vocab import causes
from mika.vocab.affect import Emotion
from mika.vocab.privacy import Sensitivity, Verdict
from tests.fixtures.mika import at_paris, boot, build
from tests.unit.test_audit_regressions import event
from tests.unit.test_bonds_over_time import Script
from tests.unit.test_knowledge_coherence import FRAME, Frame, Store, alice_says
from tests.unit.test_readings import LLM, read, store
from tests.unit.test_readings import night as reread_night

UTC = ZoneInfo("UTC")
NOW = FRAME.now  # jeudi 8 octobre 2026, midi
ALICE, BOB, CAROL = "user_2", "user_3", "user_4"
P = MemoryParams()


def moment(db: Store, seq: int, text: str, when: int, **kw) -> mc.LifeEvent:
    """Un moment noté (et archivé) tel que le noyau l'écrit."""
    kw.setdefault("about", (ALICE,))
    kw.setdefault("told_by", (ALICE,))
    e = db.put(mc.EVENT_NOTED.draft(text=Content.of(text, level=1), when=when, sensitivity=1, **kw), seq, when - DAY)
    return mc.life_event_of(seq, e.data)


async def constats(db: Store, passed: dict[int, mc.LifeEvent], lines: tuple[Line, ...], *found: XConstat,
                   speakers=(Speaker("P1", ALICE, "Alice"),), frame=FRAME, upcoming=None) -> list:
    conv = Conversation(f"private:{speakers[0].person}", speakers, lines)
    people = People.of(speakers, {}, "Mika", scope=conv.key)
    return await Consolidate()._drafts(Extraction(constats=list(found)), frame, MemoryState(), db, conv, people, [],
                                       [], None, P, "audit", moments=upcoming, passed=passed)


def of(out: list, et) -> list:
    return [d.data for d in out if d.type.name == et.name]


def resolved(outcome: str, **kw) -> NS:
    kw.setdefault("likelihood", 0.9)
    kw.setdefault("importance", 0.7)
    kw.setdefault("surprise", lk.surprise(outcome, kw["likelihood"], kw["importance"]))
    data = mc.RESOLVED.payload(event=5, thread=5, outcome=outcome, **kw)
    return NS(type=mc.RESOLVED, data=data, seq=9, at=NOW)


CX = NS(params=P, facts=NS(get=lambda _r: None), now=NOW, tz=UTC)


# ── Ses mots à elle constatent son moment ───────────────────────────────────


async def test_their_words_resolve_their_moment():
    db = store()
    ev = moment(db, 5, "Son entretien chez Ubisoft", NOW - DAY)
    said = alice_says("c'était hier, et c'est fait : j'ai passé l'entretien !")
    (r,) = of(await constats(db, {5: ev}, (said,), XConstat(numero=5, issue="a eu lieu", messages=[10000])),
              mc.RESOLVED)
    assert (r.event, r.outcome, r.by, r.teller, r.nature) == (5, mc.HAPPENED, ALICE, ALICE, lk.FIRST_HAND)
    bob = Line(10000, NOW, "Bob", "il paraît que l'entretien d'Alice a été annulé", BOB)
    rumor = await constats(db, {5: ev}, (bob,), XConstat(numero=5, issue="annulé", messages=[10000]),
                           speakers=(Speaker("P1", BOB, "Bob"),))
    assert of(rumor, mc.RESOLVED) == []  # ce qu'un autre en dit n'est qu'une rumeur
    uncited = await constats(db, {5: ev}, (said,), XConstat(numero=5, issue="a eu lieu"))
    assert of(uncited, mc.RESOLVED) == []  # ses mots, cités
    # un moment à venir s'annule d'avance ; il n'a pas encore « eu lieu »
    irm = moment(db, 6, "Son IRM du genou", NOW + DAY)
    off = alice_says("finalement mon IRM de demain est annulée")
    (r,) = of(await constats(db, {}, (off,), XConstat(numero=6, issue="annulé", messages=[10000]), upcoming={6: irm}),
              mc.RESOLVED)
    assert (r.event, r.outcome) == (6, mc.CANCELLED)
    assert of(await constats(db, {}, (off,), XConstat(numero=6, issue="a eu lieu", messages=[10000]),
                             upcoming={6: irm}), mc.RESOLVED) == []
    db.conn.close()


# ── Sans nouvelles, on ne sait pas ──────────────────────────────────────────


async def test_no_news_expires_unknown_without_surprise_or_learning():
    db = store()
    old = moment(db, 5, "Son rendez-vous chez le notaire", NOW - 30 * DAY, likelihood=0.9)
    assert [ev.id for ev in expired(Frame(), db, P)] == [5]
    out = await reread_night(db, LLM())  # rien à relire : aucun appel, mais elle tranche
    (r,) = of(out, mc.RESOLVED)
    assert (r.outcome, r.surprise, r.by) == (mc.UNKNOWN, 0.0, "")
    s = MemoryState(events=FrozenDict({5: old}))
    after = _moment_resolved(s, event(mc.RESOLVED.draft(**r.model_dump()), 9, NOW), CX)
    assert after.events[5].outcome == mc.UNKNOWN
    assert (after.track, after.calibration) == (s.track, s.calibration)  # rien n'apprend
    assert _moment_resolved_felt(event(mc.RESOLVED.draft(**r.model_dump()), 9, NOW), CX) is None  # ni ne se ressent
    db.put(mc.RESOLVED.draft(**r.model_dump()), 9, NOW)
    assert expired(Frame(), db, P) == []  # tranché une fois pour toutes
    db.put(mc.RESOLVED.draft(**{**r.model_dump(), "outcome": mc.HAPPENED}), 10, NOW)
    (row,) = db.query_mind(select(json_field(life().c.payload, "outcome")).where(life().c.id == 5))
    assert row[0] == mc.UNKNOWN  # une issue ne se retranche pas
    db.conn.close()


# ── La surprise est l'écart à ce qu'elle attendait ──────────────────────────


def test_surprise_is_prediction_error():
    assert lk.surprise(mc.HAPPENED, 0.9, 1.0) == 0.1  # c'était prévu
    assert lk.surprise(mc.CANCELLED, 0.9, 1.0) == 0.9  # c'était prévu, et annulé
    assert lk.surprise(mc.CANCELLED, 0.9, 0.2) == 0.18  # un détail : ça compte peu
    assert lk.surprise(mc.HAPPENED, 0.25, 1.0) == 0.75  # elle n'y croyait pas
    assert lk.surprise(mc.UNKNOWN, 0.9, 1.0) == lk.surprise(mc.HAPPENED, None, 1.0) == 0.0
    big = _moment_resolved_felt(resolved(mc.CANCELLED, importance=1.0), CX)
    assert [(a.emotion, a.reason) for a in big] == [(Emotion.SURPRISED, causes.TURNED_OUT)]
    assert _moment_resolved_felt(resolved(mc.HAPPENED), CX) is None  # ce qui arrive comme prévu ne surprend pas


# ── Qui reporte tout ────────────────────────────────────────────────────────


async def test_reschedules_lower_the_next_likelihood():
    s = MemoryState()
    for i in range(3):
        s = _moment_resolved(s, event(mc.RESOLVED.draft(event=10 + i, outcome=mc.MOVED, teller=ALICE, nature=lk.FIRST_HAND,
                                                 likelihood=0.9), 20 + i, NOW), CX)
    assert s.track[ALICE] == (0, 3)
    assert lk.likelihood(lk.FIRST_HAND, None, P, s.track[ALICE]) < lk.likelihood(lk.FIRST_HAND, None, P) == 0.9
    assert lk.likelihood(lk.FIRST_HAND, None, P, (10, 0)) == 0.9  # tenir parole ne dépasse pas sa nature
    # le report se constate quand la date change de jour ; préciser une période (novembre → le 12) n'en est pas un
    db = store()
    ev = moment(db, 5, "Son entretien chez Ubisoft", NOW + DAY)
    later = Consolidate._moved(ev, NOW + 5 * DAY, FRAME, (ALICE,), (10000,), "audit")
    assert [(d.data.outcome, d.data.teller) for d in later] == [(mc.MOVED, ALICE)]
    month = moment(db, 6, "Son déménagement", NOW + 20 * DAY, until=NOW + 50 * DAY, precision="month")
    assert Consolidate._moved(month, NOW + 30 * DAY, FRAME, (ALICE,), (10000,), "audit") == []
    # et le moment suivant qu'elle annonce est moins sûr
    out = await _noting(s, "jeudi j'ai mon rendez-vous à la banque",
                        XEvenement(texte="Son rendez-vous à la banque", quand="2026-10-15", personnes=["P1"],
                                   messages=[10000]))
    assert out[0].likelihood < 0.9
    db.conn.close()


async def _noting(state: MemoryState, said: str, *events: XEvenement) -> list:
    db = store()
    conv = Conversation("private:user_2", (Speaker("P1", ALICE, "Alice"),), (alice_says(said),))
    people = People.of(conv.speakers, {}, "Mika", scope=conv.key)
    out = await Consolidate()._drafts(Extraction(evenements=list(events)), FRAME, state, db, conv, people, [], [],
                                      None, P, "audit")
    db.conn.close()
    return of(out, mc.EVENT_NOTED)


# ── Vécu à travers quelqu'un ────────────────────────────────────────────────


class Owned(Frame):
    def get(self, key):
        return key.arg == ALICE if key.name == "identity.is_owner" else super().get(key)


async def test_a_shared_moment_lived_becomes_her_memory_stronger_with_her_owner():
    db = store()
    ev = moment(db, 5, "Le salon du jeu vidéo avec Alice", NOW - DAY, shared=True)
    said = alice_says("le salon c'était génial, je t'envoie les photos !")
    found = XConstat(numero=5, issue="a eu lieu", messages=[10000])
    (lived,) = of(await constats(db, {5: ev}, (said,), found), mc.REMEMBERED)
    assert lived.text.text == "J'ai vécu à travers Alice : Le salon du jeu vidéo avec Alice"
    assert lived.importance == P.lived_importance and lived.about == (ALICE,) and lived.told_by == (ALICE,)
    (owner,) = of(await constats(db, {5: ev}, (said,), found, frame=Owned()), mc.REMEMBERED)
    assert owner.importance == P.lived_owner_importance > lived.importance  # comme si elle y était allée
    plain = moment(db, 6, "Son entretien chez Ubisoft", NOW - DAY)
    assert of(await constats(db, {6: plain}, (said,), XConstat(numero=6, issue="a eu lieu", messages=[10000])),
              mc.REMEMBERED) == []  # pas partagé : son moment à elle, pas un souvenir de Mika
    db.conn.close()


# ── Ce qui approche ─────────────────────────────────────────────────────────


def _cx(upcoming, closeness=None, owners=()):
    closeness = closeness or {}

    def get(ref):
        if ref.name == "memory.upcoming":
            return upcoming
        if ref.name == "identity.person":
            return ref.arg
        if ref.name == "identity.owners":
            return owners
        if ref.name == "social.closeness":
            return closeness.get(ref.arg, social_c.STRANGER)
        return None

    return NS(params=AttentionParams(), facts=NS(get=get), now=NOW, tz=UTC)


def _upcoming(i, who, when, importance=0.7, empathy=()):
    return mc.LifeEvent(id=i, about=(who,), when=when, all_day=True, sensitivity=1, told_by=(who,), text_ref="r",
                        importance=importance, likelihood=0.9, empathy=empathy)


def test_one_dominant_anticipation_rises():
    interview = _upcoming(5, ALICE, NOW + DAY)
    concert = _upcoming(6, CAROL, NOW + DAY)  # une amie : attendu aussi, moins fort
    stranger = _upcoming(7, BOB, NOW + 2 * HOUR, importance=0.95)
    got = _anticipation(AttentionState(), _cx((interview, concert, stranger), {ALICE: social_c.CLOSE,
                                                                               CAROL: social_c.FRIEND}))
    assert (got.event, got.emotion) == (5, Emotion.HOPEFUL.value)  # le plus fort, et un seul
    assert _anticipation(AttentionState(), _cx((concert,), {CAROL: social_c.FRIEND})) is not None
    far = _upcoming(5, ALICE, NOW + 5 * DAY)
    assert _anticipation(AttentionState(), _cx((far,), {ALICE: social_c.CLOSE})) is None  # trop loin encore
    assert _anticipation(AttentionState(), _cx((stranger,))) is None  # un inconnu ne se fait pas attendre
    surgery = _upcoming(8, ALICE, NOW + DAY, importance=0.95, empathy=(("anxious", 0.7),))
    worried = _anticipation(AttentionState(), _cx((surgery,), {ALICE: social_c.CLOSE}))
    assert worried.emotion == Emotion.ANXIOUS.value
    owner = _anticipation(AttentionState(), _cx((interview,), owners=(ALICE,)))
    assert owner.weight > got.weight  # sa propriétaire, comme si elle y allait
    felt = _anticipated_felt(NS(data=worried), NS(params=AttentionParams()))
    assert (felt.emotion, felt.reason) == (Emotion.ANXIOUS, causes.DREADING)
    assert felt.intensity <= AttentionParams().anticipation_max


# ── Espoir déçu, crainte levée ──────────────────────────────────────────────


def test_hoped_then_cancelled_disappoints():
    hoped = _moment_resolved_felt(resolved(mc.CANCELLED, valence=0.8, likelihood=0.2), CX)
    assert [(a.emotion, a.reason) for a in hoped] == [(Emotion.SAD, causes.LET_DOWN)]
    dreaded = _moment_resolved_felt(resolved(mc.CANCELLED, valence=-0.8, likelihood=0.2), CX)
    assert [(a.emotion, a.reason) for a in dreaded] == [(Emotion.RELIEVED, causes.FEAR_LIFTED)]
    came = _moment_resolved_felt(resolved(mc.HAPPENED, valence=0.8), CX)
    assert [(a.emotion, a.reason) for a in came] == [(Emotion.HAPPY, causes.AWAITED)]
    assert _moment_resolved_felt(resolved(mc.UNKNOWN, valence=0.8), CX) is None


# ── Le monde, constaté par ce qu'elle lit ───────────────────────────────────


async def test_world_moment_resolved_by_later_headline():
    db = store()
    moment(db, 5, "Le concert de Daft Punk au Stade de France", NOW + 3 * DAY, about=(), told_by=("rss:Musique",),
           scope=mc.WORLD, likelihood=0.98, official=True)
    moment(db, 6, "L'éclipse partielle de Lune", NOW + 3 * DAY, about=(), told_by=("rss:Ciel",), scope=mc.WORLD)
    read(db, 7, "Daft Punk : le concert du Stade de France est annulé",
         "Le concert de Daft Punk prévu au Stade de France n'aura pas lieu, ont annoncé les organisateurs.")
    llm = LLM({"constats": [{"moment": 5, "lecture": 1, "issue": "annulé"},
                            {"moment": 6, "lecture": 1, "issue": "annulé"}]})  # rien sur l'éclipse dans cet article
    out = await reread_night(db, llm)
    assert "Le concert de Daft Punk au Stade de France" in llm.calls[0].messages[0].content
    (r,) = of(out, mc.RESOLVED)
    assert (r.event, r.outcome, r.by, r.nature) == (5, mc.CANCELLED, "rss:Science", lk.OFFICIAL)
    assert r.surprise == round(0.98 * 0.7, 3)  # une date officielle, annulée
    db.conn.close()


# ── Vérifier ce qui lui tient à cœur, pas plus ──────────────────────────────


def test_she_checks_only_what_she_cares_about_bounded():
    def world(i, importance, empathy=(), when=NOW - DAY):
        return mc.LifeEvent(id=i, about=(), when=when, all_day=True, sensitivity=0, told_by=("rss:Le Monde",),
                            text_ref=f"{i}.text", importance=importance, scope=mc.WORLD, empathy=empathy)

    election = world(5, 0.9)
    eclipse = world(6, 0.4, empathy=(("curious", 0.6),))
    trivia = world(7, 0.4)
    old = world(8, 0.9, when=NOW - 10 * DAY)
    alice = mc.LifeEvent(id=9, about=(ALICE,), when=NOW - DAY, all_day=True, sensitivity=1, told_by=(ALICE,),
                         text_ref="9.text", importance=0.9)
    s = MemoryState(events=FrozenDict({ev.id: ev for ev in (election, eclipse, trivia, old, alice)}))
    assert [ev.id for ev in _to_check(s, CX)] == [5, 6]  # important, ou attendu avec un sentiment ; le monde seul
    frame = NS(now=NOW, root=None, local=Frame().local, env=NS(tz_of=lambda *_: UTC),
               get=lambda ref: (election, eclipse) if ref.name == "memory.to_check" else ())
    p = GoalsParams()
    assert Seed()._check(GoalsState(), frame, p).id == 5
    done = GoalsState(explored=FrozenDict({"check:5": NOW - DAY}))
    assert Seed()._check(done, frame, p).id == 6  # déjà vérifié : le suivant
    week = GoalsState(explored=FrozenDict({"check:1": NOW - DAY, "check:2": NOW - 2 * DAY}))
    assert Seed()._check(week, frame, p) is None  # deux par semaine
    stale = GoalsState(explored=FrozenDict({"check:1": NOW - 8 * DAY, "check:2": NOW - 9 * DAY}))
    assert Seed()._check(stale, frame, p).id == 5  # une semaine glissante


# ── Des mots plus prudents quand ses attentes se trompent ───────────────────


def test_calibration_makes_words_cautious():
    assert lk.likely_words(0.98) == "c'est sûr"
    assert lk.likely_words(0.98, careful=True) == "c'est prévu"
    assert not lk.cautious((4, 3.0), P)  # trop peu de cas pour juger
    assert not lk.cautious((10, 0.5), P)  # ses attentes tombaient juste
    s = MemoryState()
    for i in range(5):  # cinq dates officielles « sûres », toutes annulées
        s = _moment_resolved(s, event(mc.RESOLVED.draft(event=10 + i, outcome=mc.CANCELLED, nature=lk.OFFICIAL,
                                                 likelihood=0.98), 20 + i, NOW), CX)
    assert lk.cautious(s.calibration[lk.OFFICIAL], P)
    ev = mc.LifeEvent(id=5, about=(), when=NOW + DAY, all_day=True, sensitivity=0, told_by=("rss:Le Monde",),
                      text_ref="5.text", scope=mc.WORLD, official=True, likelihood=0.98)
    assert "(c'est prévu)" in _ahead_line(s, ev) and "(c'est sûr)" in _ahead_line(MemoryState(), ev)


def _ahead_line(s: MemoryState, ev: mc.LifeEvent) -> str:
    db = Store()
    db.texts["5.text"] = "L'élection présidentielle"
    friend = Audience(persons=(CAROL,), public=False, level=int(Sensitivity.PERSONAL),
                      witness_level=int(Sensitivity.PERSONAL), private_ok=True)

    class Seen(Frame):
        def get(self, key):
            return (ev,) if key.name == "memory.ahead" else super().get(key)

    frame = Seen(friend)
    body = ahead_section(s, frame, {"recall": Recall(ahead=_ahead_moments(frame, db, CAROL, friend, P, {}))})
    db.conn.close()
    assert body is not None
    return body.content



# ── Ce qui est tranché ne se redemande pas ──────────────────────────────────


def test_what_is_settled_is_not_asked_again():
    concert = mc.LifeEvent(id=5, about=(), when=NOW + DAY, all_day=True, sensitivity=0, told_by=("rss:Musique",),
                           text_ref="5.text", scope=mc.WORLD)
    s = MemoryState(events=FrozenDict({5: concert}))
    assert [ev.id for ev in _ahead(s, CX)] == [5]
    after = _moment_resolved(s, event(mc.RESOLVED.draft(event=5, outcome=mc.CANCELLED), 9, NOW), CX)
    assert _ahead(after, CX) == ()  # annulé : ça ne vient plus
    interview = mc.LifeEvent(id=6, about=(ALICE,), when=NOW - DAY, all_day=True, sensitivity=1, told_by=(ALICE,),
                             text_ref="6.text", importance=0.8, outcome=mc.CANCELLED)
    line = _moment_line(Moment(interview, "Son entretien", Verdict(True), "Son entretien"), FRAME, close=True)
    assert line.endswith("finalement annulé.") and "comment ça s'est passé" not in line
    later = mc.LifeEvent(id=7, about=(ALICE,), when=NOW + 5 * HOUR, all_day=False, sensitivity=1, told_by=(ALICE,),
                         text_ref="7.text")
    assert _cheer_window(later, FRAME, OthersParams()) is not None  # cet après-midi : « bonne chance » ce matin…
    cancelled = replace(later, outcome=mc.CANCELLED)
    assert _cheer_window(cancelled, FRAME, OthersParams()) is None  # …mais pas pour ce qui n'aura pas lieu


def test_a_shared_moment_once_lived_is_said_in_the_past():
    """« tu le vivras à travers Alice », dit d'un concert qui a eu lieu il y a une heure (sonde réelle du 2026-10-10) :
    passé, elle l'a vécu."""
    db = Store()
    concert = moment(db, 5, "Le concert de jazz au Duc des Lombards", NOW - HOUR, all_day=False, shared=True)
    salon = moment(db, 6, "Le salon du jeu vidéo", NOW + 2 * DAY, shared=True)
    alice = Audience(persons=(ALICE,), public=False, level=int(Sensitivity.CONFIDENCE),
                     witness_level=int(Sensitivity.CONFIDENCE), private_ok=True)

    class Hers(Frame):
        def get(self, key):
            return (concert, salon) if key.name == "memory.life_events" else super().get(key)

    labels = {m.event.id: m.label for m in _moments(Hers(alice), db, ALICE, alice, P, {})}
    assert labels[5].endswith("tu l'as vécu à travers Alice") and labels[6].endswith("tu le vivras à travers Alice")
    db.conn.close()


def test_the_console_shows_what_she_expected_and_who_keeps_their_word():
    """Ses attentes se lisent dans la console (le réglage le promettait : « le chiffre se lit dans la console, jamais
    dans ses phrases ») — par sorte d'annonce, l'écart moyen et si elle en parle plus prudemment ; et ce qu'elle
    apprend de qui annonce (lot I du chantier « émotions, conscience, mémoire »)."""
    from types import SimpleNamespace as NS

    from mika.faculties.memory.faculty import MemoryParams, MemoryState
    from mika.faculties.memory.inspect import _seeing_ahead
    from mika.kernel.inspect import Badge, Meter, Table
    from mika.kernel.state import FrozenDict

    s = MemoryState(calibration=FrozenDict({mc.FIRST_HAND: (6, 2.4), mc.OFFICIAL: (2, 0.0)}),
                    track=FrozenDict({"user_2": (1, 4)}))
    frame = NS(env=NS(params_of=lambda *_: MemoryParams()), root=None,
               get=lambda key: NS(name="Alice") if key.name == "identity.identity" else ())
    calibration, tellers = _seeing_ahead(s, frame, None)
    assert isinstance(calibration, Table) and isinstance(tellers, Table)
    first = next(r for r in calibration.rows if r.cells[0] == "de la bouche de la personne")
    assert first.cells[2] == "0,400" and first.cells[3] == Badge("plus prudente", "warn")
    official = next(r for r in calibration.rows if r.cells[0] == "une date officielle")
    assert official.cells[3].tone == "muted"  # trop peu de cas pour juger
    alice = tellers.rows[0]
    assert alice.cells[:3] == ("Alice", 1, 4) and isinstance(alice.cells[3], Meter) and alice.cells[3].ratio < 0.5


# ── Une prévision passée se constate (ADR 0099) ─────────────────────────────


async def test_a_forecast_that_came_true_is_constated_and_she_learns_from_it():
    """« Je pense que je serai prise » (Alice, il y a dix jours, pour hier) : passée, la prévision se montre à la
    relecture avec les moments passés ; Alice dit « j'ai été prise ! » — constatée, réalisée. Elle en apprend : qui
    prévoyait (Alice tient ce qu'elle annonce), et ses attentes de la sorte « prévision » (sa calibration). Une
    rumeur ne constate rien ; constatée, elle ne se montre plus."""
    db = store()
    db.put(mc.BELIEVED.draft(text=Content.of("Alice pense qu'elle sera prise chez Ubisoft", level=1), about=(ALICE,),
                             told_by=(ALICE,), heard_by=(ALICE,), sensitivity=1, knowledge_kind="prediction",
                             holder=ALICE, likelihood=0.7, expected=NOW - DAY), 7, NOW - 10 * DAY)
    speakers = (Speaker("P1", ALICE, "Alice"),)
    conv = Conversation(f"private:{ALICE}", speakers, (alice_says("j'ai été prise !!"),))
    shown, foreseen = Consolidate._forecasts(FRAME, db, conv, P, {ALICE: "Alice [P1]"})
    assert [i for i, _w, _t in shown] == [7] and "une prévision" in shown[0][2]
    behind, _past, _f = Consolidate()._behind(FRAME, db, MemoryState(), conv, P, {ALICE: "Alice [P1]"})
    assert 7 in [i for i, _w, _t in behind]  # montrée à la relecture, avec les moments passés
    people = People.of(speakers, {}, "Mika", scope=conv.key)
    out = await Consolidate()._drafts(Extraction(constats=[XConstat(numero=7, issue="a eu lieu", messages=[10000])]),
                                      FRAME, MemoryState(), db, conv, people, [], [], None, P, "audit",
                                      foreseen=foreseen)
    (r,) = of(out, mc.RESOLVED)
    assert (r.event, r.outcome, r.by, r.teller, r.nature) == (7, mc.HAPPENED, ALICE, ALICE, mc.PREDICTION)
    s = _moment_resolved(MemoryState(), NS(data=r, seq=9, at=NOW), CX)
    assert s.track[ALICE] == (1, 0) and s.calibration[mc.PREDICTION] == (1, pytest.approx(0.09))
    bob = (Speaker("P1", BOB, "Bob"),)
    rumor = Conversation(f"private:{BOB}", bob, (Line(10000, NOW, "Bob", "Alice a été prise, il paraît", BOB),))
    _shown, seen_by_bob = Consolidate._forecasts(FRAME, db, rumor, P, {BOB: "Bob [P1]"})
    assert seen_by_bob == {}  # pas une personne qu'elle concerne : ni montrée…
    told = await Consolidate()._drafts(Extraction(constats=[XConstat(numero=7, issue="a eu lieu",
                                                                     messages=[10000])]),
                                       FRAME, MemoryState(), db, rumor, People.of(bob, {}, "Mika", scope=rumor.key),
                                       [], [], None, P, "audit", foreseen=foreseen)
    assert of(told, mc.RESOLVED) == []  # … ni constatée par ce qu'un autre en dit
    db.put(mc.RESOLVED.draft(**r.model_dump()), 11, NOW)
    assert Consolidate._forecasts(FRAME, db, conv, P, {ALICE: "Alice [P1]"}) == ([], {})
    db.conn.close()


# ── L'issue d'un moment précisé le jour même ; un report compte à moitié (audit du 2026-10-12) ─────────────────


def test_an_outcome_under_a_number_replaced_the_same_day_lands_on_the_moment_without_undoing_the_append(tmp_path):
    """« Finalement c'est à 14 h », puis « ah non, il est annulé », relus ensemble : la précision remplace le moment (le
    même jour, le même fil) et l'issue arrive sous l'ancien numéro, que l'archive vient d'effacer. L'archive lisait
    l'occurrence d'une issue, qui n'en a pas : tout l'ajout était défait — et la consolidation rejouait les mêmes
    brouillons à chaque passage. L'issue va au moment tel qu'il est noté maintenant, dans la tranche et dans
    l'archive."""
    kernel, clock, _llm, _out = build(tmp_path, Script(), start=at_paris(2026, 9, 28, 15, 0))
    morning, afternoon = at_paris(2026, 9, 29, 10, 0), at_paris(2026, 9, 29, 14, 0)

    def noted(text, when, **kw):
        return mc.EVENT_NOTED.draft(text=Content.of(text, level=1), when=when, about=(ALICE,), told_by=(ALICE,),
                                    all_day=False, sensitivity=1, **kw)

    async def main():
        await boot(kernel)
        try:
            (first,) = (await kernel.mind.append([noted("Son entretien chez Ubisoft", morning)], emitter="memory",
                                                 correlation="genese", origin=Origin.GENESIS)).seqs
            commit = await kernel.mind.append(
                [noted("Son entretien chez Ubisoft, à 14 h", afternoon, replaces=first),
                 mc.RESOLVED.draft(event=first, thread=first, outcome=mc.CANCELLED, by=ALICE)],
                emitter="memory", correlation="relecture", origin=Origin.GENESIS)
            now = commit.seqs[0]
            rows = kernel.mind.store.query_mind(
                select(life().c.id, json_field(life().c.payload, "outcome")).order_by(life().c.id))
            return now, kernel.mind.frame().state("memory").events[now].outcome, rows
        finally:
            await kernel.stop()

    now, outcome, rows = run_virtual(clock, main)
    assert outcome == mc.CANCELLED  # la tranche : le même moment, annulé
    assert rows == [(now, mc.CANCELLED)]  # l'archive : pareil, et l'ancien numéro n'y est plus


def test_a_moved_moment_counts_half_in_her_expectations_as_in_her_surprise():
    """Déplacé, un moment n'a pas eu lieu ce jour-là mais aura lieu : à moitié (``OUTCOME_VALUE``). La surprise le
    comptait ainsi ; ses attentes (le score de Brier) le comptaient comme une annulation."""
    s = _moment_resolved(MemoryState(), event(mc.RESOLVED.draft(event=10, outcome=mc.MOVED, nature=lk.FIRST_HAND,
                                                                likelihood=0.9), 20, NOW), CX)
    assert s.calibration[lk.FIRST_HAND] == (1, pytest.approx((0.9 - mc.OUTCOME_VALUE[mc.MOVED]) ** 2))
    assert lk.surprise(mc.MOVED, 0.9, 1.0) == pytest.approx(0.9 - mc.OUTCOME_VALUE[mc.MOVED])
    s = _moment_resolved(s, event(mc.RESOLVED.draft(event=11, outcome=mc.CANCELLED, nature=lk.FIRST_HAND,
                                                    likelihood=0.9), 21, NOW), CX)
    assert s.calibration[lk.FIRST_HAND][1] == pytest.approx(0.16 + 0.81)  # une annulation, elle, compte pleine
