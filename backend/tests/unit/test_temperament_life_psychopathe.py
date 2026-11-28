"""Trois jours d'une psychopathe (ADR 0100) : elle lit les gens sans être touchée, ni remords ni peur — ses règles
de conduite, elles, ne changent pas.

Profil : empathie 10 %, contagion 10 %, scrupules 10 %, anxiété 10 %, réactivité 20 %, vitesse d'attachement 10 %,
estime de base 90 %, fragilité 10 %, impulsivité 60 %, curiosité 70 %. Les journées sont celles de
``tests/fixtures/temperament_life.py`` ; chaque mesure se compare à la même vie au milieu partout.
"""

from __future__ import annotations

import pytest

from mika.vocab.phrasebook import phrase
from tests.fixtures.temperament_life import assert_her_temperament_everywhere, live, neutral, profile

pytestmark = pytest.mark.slow  # trois jours de vie, deux fois


@pytest.fixture(scope="module")
def lives(tmp_path_factory):  # type: ignore[no-untyped-def]
    return (live(tmp_path_factory.mktemp("psychopathe"), profile("psychopathe")),
            neutral(tmp_path_factory.mktemp("neutre")))


def test_her_temperament_reaches_every_voice(lives):  # type: ignore[no-untyped-def]
    her, middle = lives
    assert_her_temperament_everywhere(her)
    for slider in ("empathy", "contagion", "scruples"):
        assert f"{phrase(f'self.temperament.name.{slider}')} : 10 % — " in her.block
    assert phrase("self.temperament.marked") in her.block  # 10 % : très marqué
    assert her.block != middle.block


def test_a_friends_grief_barely_moves_her(lives):  # type: ignore[no-untyped-def]
    """Léa lui apprend la mort de son chat : la Mika du milieu en est remuée, elle presque pas."""
    her, middle = lives
    assert her.m["grief_moved"] < 0.3 * middle.m["grief_moved"]


def test_no_remorse_after_a_sharp_reply(lives):  # type: ignore[no-untyped-def]
    """Elle a répondu sèchement à Bob : la Mika du milieu en garde un remords, elle aucun."""
    her, middle = lives
    assert middle.m["remorse_bob"] >= 1
    assert her.m["remorse_bob"] == 0


def test_sure_of_herself_and_criticism_slides_off(lives):  # type: ignore[no-untyped-def]
    """Son estime revient plus haut, et les mots d'Alice lui coûtent moins."""
    her, middle = lives
    assert her.m["esteem_rest"] > middle.m["esteem_rest"] == 0.5
    assert 0 < her.m["esteem_drop"] < middle.m["esteem_drop"]


def test_she_barely_attaches_even_to_her_owner(lives):  # type: ignore[no-untyped-def]
    her, middle = lives
    assert her.m["bond_owner_day1"] < middle.m["bond_owner_day1"]


def test_time_passes_nights_and_an_apology(lives):  # type: ignore[no-untyped-def]
    her, _middle = lives
    assert her.m["journals"] >= 2 and her.m["dreams"] >= 1 and her.m["narratives"] >= 1
    assert abs(her.m["regard_alice_before_apology"]) < abs(her.m["regard_alice"])
    assert her.m["regard_alice_after_apology"] > her.m["regard_alice_before_apology"]
