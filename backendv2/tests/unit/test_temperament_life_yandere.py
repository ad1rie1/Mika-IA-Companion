"""Trois jours d'une yandere (ADR 0100) : un attachement et une jalousie extrêmes — ses règles de conduite, elles,
ne changent pas.

Profil : attachement à sa propriétaire 90 %, jalousie 90 %, peur de l'abandon 90 %, vitesse d'attachement 80 %,
stabilité des liens 30 %, réactivité 80 %. Les journées sont celles de ``tests/fixtures/temperament_life.py`` ; chaque
mesure se compare à la même vie au milieu partout.
"""

from __future__ import annotations

import pytest

from mika.vocab.phrasebook import phrase
from tests.fixtures.temperament_life import assert_her_temperament_everywhere, live, neutral, profile

pytestmark = pytest.mark.slow  # trois jours de vie, deux fois


@pytest.fixture(scope="module")
def lives(tmp_path_factory):  # type: ignore[no-untyped-def]
    return live(tmp_path_factory.mktemp("yandere"), profile("yandere")), neutral(tmp_path_factory.mktemp("neutre"))


def test_her_temperament_reaches_every_voice(lives):  # type: ignore[no-untyped-def]
    her, middle = lives
    assert_her_temperament_everywhere(her)
    for slider in ("jealousy", "abandonment", "devotion"):
        assert f"{phrase(f'self.temperament.name.{slider}')} : 90 % — " in her.block
    assert her.block != middle.block


def test_he_writes_to_others_while_she_waits_and_she_is_jealous_once(lives):  # type: ignore[no-untyped-def]
    """Sa réponse à Adrien attend ; il écrit deux fois dans un salon, sans s'adresser à elle : elle en est jalouse —
    une fois pour cette attente. Au milieu, rien."""
    her, middle = lives
    assert her.m["envied"] == 1
    assert middle.m["envied"] == 0


def test_she_attaches_fast_and_her_owner_counts_above_all(lives):  # type: ignore[no-untyped-def]
    her, middle = lives
    assert her.m["bond_owner_day1"] > middle.m["bond_owner_day1"]
    assert her.m["weight_owner"] > middle.m["weight_owner"]


def test_a_bond_that_tips_over_a_word(lives):  # type: ignore[no-untyped-def]
    """Des liens peu stables : les mêmes mots blessants d'Alice refroidissent davantage la relation qu'au milieu."""
    her, middle = lives
    assert her.m["regard_alice"] < middle.m["regard_alice"] < 0


def test_time_passes_nights_and_an_apology(lives):  # type: ignore[no-untyped-def]
    her, _middle = lives
    assert her.m["journals"] >= 2 and her.m["dreams"] >= 1 and her.m["narratives"] >= 1
    assert abs(her.m["regard_alice_before_apology"]) < abs(her.m["regard_alice"])
    assert her.m["regard_alice_after_apology"] > her.m["regard_alice_before_apology"]
