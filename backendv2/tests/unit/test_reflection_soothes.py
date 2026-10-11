"""Une réflexion n'est pas un exploit (lot G du chantier « émotions, conscience, mémoire », ADR 0096).

Repenser à ce qu'une amie lui a confié (« Repenser à ce que « Adrien » m'a confié »), à ce qu'elle croyait : menée au
bout, elle la rendait fière comme une chose accomplie, relevait son estime, comptait dans « tu mènes au bout ce que tu
entreprends » — l'inquiétude pour quelqu'un devenait un trophée. Désormais : un apaisement (le soulagement d'avoir
pris le temps d'y repenser), sans estime ni compte de réussites ; une réflexion qui n'aboutit pas reste un peu lourde,
sans frustration ni coup à l'estime. Ce qu'elle entreprend pour de bon garde sa fierté.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from mika.contracts import goals as goals_c
from mika.faculties.goals.faculty import _closed_felt
from mika.faculties.self import SelfParams, SelfState
from mika.faculties.self.esteem import _goal_closed
from mika.faculties.self.model import _goal_finished
from mika.faculties.self.records import DONE, REFLECTED
from mika.kernel.clock import HOUR
from mika.kernel.events import Content
from mika.vocab import causes, circadian
from mika.vocab.affect import Emotion
from tests.fixtures.mika import PARIS, at_paris

T0 = at_paris(2026, 9, 28, 15, 0)


def closed(status=goals_c.ACHIEVED, origin=goals_c.FROM_EXCHANGE, source="thought:12"):
    return NS(at=T0 + HOUR, data=goals_c.GoalClosed(
        goal=7, status=status, kind=goals_c.EXPLORATION, authority=goals_c.SELF,
        title=Content(ref="7.title", text="Repenser à ce que « Adrien » m'a confié", level=2), source=source,
        origin=origin, owner="user_1", about=("user_1",), sensitivity=2))


def cx():
    return NS(params=SelfParams(), tz=PARIS, now=T0 + HOUR,
              facts=NS(get=lambda key: circadian.DEFAULT if key.name == "body.rhythm" else None))


@pytest.mark.parametrize("origin, source", [(goals_c.FROM_EXCHANGE, "thought:12"), (goals_c.FROM_REVISION, "thought:3"),
                                            ("", "thought:12")])  # un journal d'avant : née d'une pensée
def test_an_achieved_reflection_soothes_it_does_not_make_her_proud(origin, source):
    felt = _closed_felt(closed(origin=origin, source=source), None)
    assert (felt.emotion, felt.reason) == (Emotion.RELIEVED, causes.REFLECTED)
    stuck = _closed_felt(closed(goals_c.STUCK, origin=origin, source=source), None)
    assert stuck.emotion is Emotion.MELANCHOLIC  # ça reste un peu lourd : pas de frustration


def test_what_she_undertakes_for_real_keeps_its_pride():
    felt = _closed_felt(closed(origin=goals_c.FROM_INTEREST, source="interest:Les plantes"), None)
    assert (felt.emotion, felt.reason) == (Emotion.PROUD, causes.ACHIEVED)


def test_a_reflection_neither_raises_nor_lowers_her_esteem():
    s = SelfState(esteem=0.5, esteem_at=T0)
    for status in (goals_c.ACHIEVED, goals_c.STUCK):
        after = _goal_closed(s, closed(status), cx())
        assert after.esteem == pytest.approx(s.esteem)
    assert [d.what for d in _goal_closed(s, closed(), cx()).deeds] == [REFLECTED]
    real = _goal_closed(s, closed(origin=goals_c.FROM_INTEREST, source="interest:x"), cx())
    assert real.esteem > s.esteem and [d.what for d in real.deeds] == [DONE]


def test_a_reflection_is_not_counted_among_what_she_brings_to_completion():
    s = SelfState()
    assert _goal_finished(s, closed(), cx()).record == s.record
    assert _goal_finished(s, closed(origin=goals_c.FROM_INTEREST, source="interest:x"), cx()).record != s.record
