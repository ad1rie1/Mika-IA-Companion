"""Les points faibles relevés par l'audit « émotions, conscience, mémoire » (2026-10-11), corrigés.

- quelqu'un qu'elle ne peut pas reconnaître (une adresse jetable) la touchait davantage qu'une inconnue connue : son
  humeur n'en était pas amortie ;
- une humeur sombre née d'un échange avec quelqu'un débordait vers qui était là — cette personne comprise : sa colère
  contre Bob la poussait à écrire à Bob.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace as NS

from mika.contracts import affect as affect_c
from mika.contracts import expression as expression_c
from mika.contracts import social as social_c
from mika.faculties.affect import AffectState, _declared, _not_to_whom_upset_her
from mika.faculties.affect import physics as ph
from mika.faculties.affect.params import DEFAULT
from mika.kernel.arbitration import RowView
from mika.vocab import affect as A
from mika.vocab import causes, circadian
from mika.vocab.affect import Declared, Emotion
from tests.fixtures.mika import PARIS, at_paris

T0 = at_paris(2026, 9, 28, 15, 0)


def said_to(target: str, declared: Declared):
    notes = {expression_c.EMOTION_ANNOTATION: declared.encode()}
    return NS(at=T0, data=NS(kind="REPLY", target=target, visible=True, annotation=notes.get))


def cx(closeness: dict[str, str]):
    def get(key):
        if key.name == "identity.person":
            return key.arg
        if key.name == social_c.CLOSENESS.name:
            return closeness.get(key.arg, social_c.STRANGER)
        if key.name == "body.rhythm":
            return circadian.DEFAULT
        raise KeyError(key.name)

    return NS(params=DEFAULT, tz=PARIS, facts=NS(get=get), local=lambda t: datetime.fromtimestamp(t / 1e6, PARIS))


def moved(target: str, closeness: dict[str, str]) -> float:
    s = _declared(AffectState(), said_to(target, Declared(Emotion.ANGRY, 0.8)), cx(closeness))
    rest = ph.common_home(T0, DEFAULT, ph.Clockwork(PARIS, circadian.DEFAULT))
    return A.distance(ph.mood_position(s.mood, DEFAULT), rest)


def test_someone_she_cannot_recognize_moves_her_no_more_than_a_stranger():
    stranger = moved("user_9", {"user_9": social_c.STRANGER})
    anonymous = moved("anon_7f3a", {})
    friend = moved("user_2", {"user_2": social_c.FRIEND})
    assert anonymous <= stranger + 1e-9 < friend


def mood(felt: Emotion, cause: str = causes.TALK, person: str = "user_3"):
    reading = affect_c.MoodReading(position=(0.0, 0.0, 0.0), home=(0.0, 0.0, 0.0), felt=felt, felt_intensity=0.7,
                                   overflow=0.8, label=felt, intensity=0.7, cause=cause, cause_person=person)
    return NS(get=lambda key: reading if key.name == affect_c.MOOD.name else key.arg,
              env=NS(params_of=lambda *_: DEFAULT), root=None)


def shift(frame, target: str, reasons=(affect_c.MOOD_OVERFLOW,)) -> float:
    return _not_to_whom_upset_her(None, frame, RowView("INITIATIVE", target, 5.0, reasons)).shift


def test_a_dark_overflow_does_not_go_to_whom_caused_it():
    angry_at_bob = mood(Emotion.ANGRY)
    assert shift(angry_at_bob, "user_3") < 0  # pas vers Bob
    assert shift(angry_at_bob, "user_2") == 0  # vers une amie qui est là, si
    assert shift(mood(Emotion.HAPPY), "user_3") == 0  # une joie qu'elle lui doit peut aller vers lui
    assert shift(mood(Emotion.ANGRY, cause=causes.UNANSWERED), "user_3") == 0  # rien ne dit que c'est lui
    assert shift(angry_at_bob, "user_3", ("check_in",)) == 0  # une autre raison de lui écrire garde son poids
