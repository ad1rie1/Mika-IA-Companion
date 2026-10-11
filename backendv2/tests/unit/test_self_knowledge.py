"""Ce qu'elle sait d'elle (ADR 0088) : tenir parole, mener au bout, voir venir.

Ses réussites et ses ratés ne laissaient de trace que dans son estime — un chiffre qui revient vers 0,5 en trois
jours. Elle ne savait pas qu'elle tient parole, ni qu'elle bloque souvent, ni que ses attentes tombent juste. Elle
le sait maintenant, en tendances (jamais un nombre, jamais une obligation), et son estime n'en bouge pas : une
promesse tenue ne la gonfle toujours pas (ADR 0046).
"""

from __future__ import annotations

import re
from types import SimpleNamespace as NS

from mika.contracts import attention as attention_c
from mika.contracts import goals as goals_c
from mika.contracts import memory as mc
from mika.contracts import projects as projects_c
from mika.contracts import self_ as c
from mika.faculties.self import SelfParams, SelfState
from mika.faculties.self.inspect import _inspect_becoming
from mika.faculties.self.model import (
    _changes,
    _foreseen,
    _goal_finished,
    _objective_finished,
    _promise_late,
    _promise_resolved,
    _self_model,
    knows,
)
from mika.kernel.clock import DAY, HOUR
from mika.kernel.events import Content, Origin
from mika.vocab.privacy import Sensitivity
from tests.unit.test_knowledge_coherence import FRAME, SALON, Frame, Store
from tests.unit.test_self_said import JAZZ, NO_JAZZ, said_of_herself

P = SelfParams()
NOW = FRAME.now


def event(et, at: int = NOW, **data) -> NS:
    return NS(type=et, data=et.payload(**data), at=at, seq=1)


def apply(s: SelfState, *events: NS) -> SelfState:
    reducers = {mc.PROMISE_RESOLVED.name: _promise_resolved, attention_c.EXPECTATION_MISSED.name: _promise_late,
                goals_c.GOAL_CLOSED.name: _goal_finished, projects_c.OBJECTIVE_CLOSED.name: _objective_finished,
                mc.RESOLVED.name: _foreseen}
    for e in events:
        s = reducers[e.type.name](s, e, None)
    return s


def kept(i: int, at: int = NOW) -> NS:
    return event(mc.PROMISE_RESOLVED, at, promise=i, status=mc.HONORED, by=mc.KEPT_BY)


def lapsed(i: int, at: int = NOW) -> NS:
    return event(mc.PROMISE_RESOLVED, at, promise=i, status=mc.DROPPED, by=mc.EXPIRED_BY)


def closed(i: int, status: str = goals_c.ACHIEVED, reason: str = "", kind: str = goals_c.EXPLORATION) -> NS:
    return event(goals_c.GOAL_CLOSED, goal=i, status=status, kind=kind, reason=reason,
                 title=Content.of(f"but {i}", level=1))


def resolved(i: int, outcome: str, likelihood: float | None, nature: str = mc.FIRST_HAND) -> NS:
    return event(mc.RESOLVED, event=i, outcome=outcome, likelihood=likelihood, nature=nature)


# ── tenir parole ──────────────────────────────────────────────────────────


def test_three_kept_promises_say_she_keeps_her_word_one_lapsed_erases_it():
    s = apply(SelfState(), kept(1), kept(2))
    assert c.PROMISES_KEPT not in knows(s.record, NOW, P)
    s = apply(s, kept(3))
    assert knows(s.record, NOW, P) == (c.PROMISES_KEPT,)
    s = apply(s, lapsed(4))
    assert c.PROMISES_KEPT not in knows(s.record, NOW, P)
    s = apply(s, lapsed(5), lapsed(6), lapsed(7))
    assert c.PROMISES_SLIP in knows(s.record, NOW, P)  # plus de filées que de tenues


def test_a_late_promise_kept_afterwards_is_not_kept_on_time():
    late = event(attention_c.EXPECTATION_MISSED, kind=attention_c.PROMISE, person="user_2", since=NOW - DAY, ref=3)
    s = apply(SelfState(), kept(1), kept(2), late, kept(3))
    assert [m.outcome for m in s.record] == ["kept", "kept", "slipped"]  # tenue en retard : une seule marque
    assert c.PROMISES_KEPT not in knows(s.record, NOW, P)
    renounced = event(mc.PROMISE_RESOLVED, promise=9, status=mc.DROPPED, by="consolidation")
    carried = event(mc.PROMISE_RESOLVED, promise=10, status=mc.DROPPED, by=mc.REMINDER_BY)
    assert apply(SelfState(), renounced, carried).record == ()  # la personne y renonce, un rappel la porte : rien


# ── mener au bout ─────────────────────────────────────────────────────────


def test_what_she_carries_through_not_her_daydreams():
    musing = next(iter(goals_c.MUSINGS))
    s = apply(SelfState(), closed(1, reason=musing), closed(2, reason=musing), closed(3, reason=musing),
              closed(4, kind=goals_c.REMINDER), closed(5, goals_c.ABANDONED))
    assert s.record == ()  # rêveries, rappel dit, abandon : ni réussite ni raté
    objective = event(projects_c.OBJECTIVE_CLOSED, project=1, objective=2, status=projects_c.DONE,
                      title=Content.of("objectif", level=1))
    impersonal = event(projects_c.OBJECTIVE_CLOSED, project=1, objective=3, status=projects_c.DONE,
                       mode=projects_c.PLAIN, title=Content.of("objectif", level=1))
    s = apply(s, closed(6), closed(7), objective, impersonal)
    assert knows(s.record, NOW, P) == (c.FINISHING_DONE,)  # deux buts et un objectif à elle ; l'impersonnel non
    s = apply(s, closed(8, goals_c.STUCK), closed(9, goals_c.STUCK), closed(10, goals_c.STUCK),
              closed(11, goals_c.STUCK))
    assert knows(s.record, NOW, P) == (c.FINISHING_STRUGGLE,)


# ── voir venir ────────────────────────────────────────────────────────────


def test_what_she_foresees_is_judged_on_enough_outcomes_never_on_official_dates():
    right = [resolved(i, mc.HAPPENED, 0.9) for i in range(4)]
    s = apply(SelfState(), *right, resolved(10, mc.HAPPENED, 0.1, nature=mc.OFFICIAL),
              resolved(11, mc.UNKNOWN, 0.9), resolved(12, mc.HAPPENED, None))
    assert knows(s.record, NOW, P) == ()  # quatre seulement : la date officielle, l'inconnu, sans attente exclus
    s = apply(s, resolved(5, mc.CANCELLED, 0.1))
    assert knows(s.record, NOW, P) == (c.FORESIGHT_RIGHT,)
    wrong = apply(SelfState(), *(resolved(i, mc.CANCELLED, 0.9) for i in range(5)))
    assert knows(wrong.record, NOW, P) == (c.FORESIGHT_OFF,)


def test_what_she_knows_slides_with_time():
    s = apply(SelfState(), kept(1, NOW - 40 * DAY), kept(2, NOW - 40 * DAY), kept(3))
    assert knows(s.record, NOW, P) == ()  # deux d'il y a quarante jours ne comptent plus
    old = apply(SelfState(), *(kept(i, NOW - 100 * DAY) for i in range(5)), kept(9))
    assert [m.ref for m in old.record] == [9]  # au-delà de quatre-vingt-dix jours, les marques s'en vont


# ── ce que son prompt en dit ──────────────────────────────────────────────


class Room(Frame):
    env = NS(tz_of=FRAME.env.tz_of, params_of=lambda owner, *_: P if owner == "self" else FRAME.env.params_of())

    def __init__(self, known=(), **kw):
        super().__init__(**kw)
        self.known = tuple(known)

    def get(self, key):
        return self.known if key.name == "self.knows" else super().get(key)


async def test_the_prompt_says_tendencies_never_numbers_and_keeps_secret_changes():
    db = Store()
    (jazz,) = said_of_herself(db, JAZZ, "avis")
    db.put(jazz, 5)
    (no,) = said_of_herself(db, NO_JAZZ, "avis", remplace=5, known=(5,))
    db.put(no, 6, at=NOW - HOUR)
    private, salon = Room(known=(c.PROMISES_KEPT, c.FORESIGHT_RIGHT)), Room(audience=SALON)
    changes = await _changes(SelfState(), private, {"store": db})
    body = _self_model(SelfState(), private, {"self_changes": changes})
    assert "tu tiens parole" in body.content and "tombe souvent juste" in body.content
    assert f"avant, « {JAZZ} » ; maintenant, « {NO_JAZZ} »" in body.content
    assert not re.search(r"\d", body.content)  # jamais un nombre
    assert len(await _changes(SelfState(), salon, {"store": db})) == 1  # un avis anodin se dit partout
    (hush,) = said_of_herself(db, "Je n'aime plus le rap", "avis")
    db.put(hush, 7)
    db.put(mc.BELIEVED.draft(text=Content.of("J'aime le rap, en secret"), about_self=True, durable=True,
                             knowledge_kind="opinion", secret=True, sensitivity=int(Sensitivity.CONFIDENCE),
                             replaces=7), 8, at=NOW - HOUR // 2)  # plus récent : montré d'abord, s'il l'était
    assert [ch.item for ch in await _changes(SelfState(), salon, {"store": db})] == [6]  # le secret, jamais
    old = Room(known=())
    db.execute(f"UPDATE {mc.ITEMS_TABLE} SET superseded_at=? WHERE id IN (5, 7)", (NOW - 30 * DAY,))
    assert await _changes(SelfState(), old, {"store": db}) == []  # il y a un mois : plus présent
    assert _self_model(SelfState(), old, {"self_changes": []}) is None


# ── son estime n'en bouge pas ─────────────────────────────────────────────


def test_keeping_promises_is_known_not_flattering(tmp_path):
    from tests.unit.test_esteem import run

    async def scenario(kernel):
        drafts = [mc.PROMISE_RESOLVED.draft(promise=100 + i, status=mc.HONORED, by=mc.KEPT_BY) for i in range(3)]
        await kernel.mind.append(drafts, emitter="memory", correlation="parole", origin=Origin.GENESIS)
        frame = kernel.mind.frame()
        return frame.get(c.ESTEEM), frame.get(c.KNOWS)

    (esteem, known), _ = run(tmp_path, scenario)
    assert esteem == 0.5 and known == (c.PROMISES_KEPT,)


# ── la console ────────────────────────────────────────────────────────────


def test_the_console_shows_marks_thresholds_and_what_the_prompt_says():
    db = Store()
    (jazz,) = said_of_herself(db, JAZZ, "avis")
    db.put(jazz, 5)
    (no,) = said_of_herself(db, NO_JAZZ, "avis", remplace=5, known=(5,))
    db.put(no, 6)
    s = apply(SelfState(), kept(1), kept(2), kept(3))
    knowing, _passions, _leads, changes, defining = _inspect_becoming(s, Room(), NS(store=db))
    first = knowing.rows[0]
    assert first[0] == "tenir parole" and first[1].startswith("3 tenue(s)") and "tu tiens parole" in first[3].text
    assert changes.rows[0][0].text == JAZZ and changes.rows[0][1].text == NO_JAZZ
    assert [r[0].text for r in defining.rows] == [NO_JAZZ]  # ce qu'elle pense maintenant la définit
