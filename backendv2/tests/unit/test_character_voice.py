"""Son caractère s'entend dans sa réponse (banc de conversation du 2026-10-15).

Réfléchie, solaire ou kuudere, elle parlait pareil : le texte de sa persona l'emportait sur sa matrice, et un juge
ne retrouvait le profil d'une conversation qu'une fois sur trois, le hasard. Ses traits les plus marqués, traduits en
façon d'écrire dans un chat, sont le dernier mot de son état interne (« TA RÉPONSE ») : solaire contre kuudere, le
juge les distingue 17 fois sur 18.
"""

from __future__ import annotations

from mika.faculties.expression import marked_traits
from mika.vocab import temperament as T
from mika.vocab.phrasebook import phrase


def test_her_most_marked_traits_are_said_as_a_way_of_writing():
    cold = T.apply_profile(T.Temperament(), "kuudere")
    got = marked_traits(cold)
    assert got[0] == phrase("expression.answer.traits.expressiveness.low")  # 10 % : le plus marqué d'abord
    assert "phrases courtes" in got[0]
    sunny = marked_traits(T.apply_profile(T.Temperament(), "solaire"))
    assert len(sunny) == 3 and phrase("expression.answer.traits.expressiveness.high") in sunny


def test_a_temperament_like_most_people_adds_nothing():
    assert marked_traits(T.Temperament()) == []
    assert marked_traits(None) == []
